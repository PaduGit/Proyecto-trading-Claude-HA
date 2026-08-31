"""Envio de alertas: notificacion nativa de HA y/o Telegram."""

import logging
import os

import requests

log = logging.getLogger("notify")

SUPERVISOR = "http://supervisor/core/api"
CORE_DIRECTO = "http://homeassistant:8123/api"


class Notificador:
    def __init__(self, cfg):
        self.canal = (cfg.get("canal_alertas") or "ambos").lower()
        self.tg_token = (cfg.get("telegram_token") or "").strip()
        self.tg_chat = (cfg.get("telegram_chat_id") or "").strip()
        self.servicio_ha = (cfg.get("ha_notify_service") or "").strip()
        self.panel = (cfg.get("panel_path") or "").strip()
        if self.panel and not self.panel.startswith("/"):
            self.panel = "/" + self.panel
        # el nombre de la variable cambió entre versiones del Supervisor
        self.token_sup = (os.environ.get("SUPERVISOR_TOKEN")
                          or os.environ.get("HASSIO_TOKEN") or "")

        # respaldo: token de larga duración creado por el usuario en su perfil.
        # No depende de los permisos del add-on.
        self.token_largo = (cfg.get("ha_token") or "").strip()
        self.url_core = (cfg.get("ha_url") or "").strip().rstrip("/")

        if self.token_largo:
            self.token = self.token_largo
            self.base_api = (self.url_core + "/api") if self.url_core else CORE_DIRECTO
            self.via = "token propio"
        else:
            self.token = self.token_sup
            self.base_api = SUPERVISOR
            self.via = "supervisor"

        self.tg_ok = bool(self.tg_token and self.tg_chat)
        self.error_ha = None
        self.ha_ok = bool(self.servicio_ha and self.token)

        if self.canal in ("ha", "ambos") and not self.ha_ok:
            falta = []
            if not self.servicio_ha:
                falta.append("ha_notify_service en la configuración")
            if not self.token:
                falta.append("un token. O el add-on no recibe el del "
                             "Supervisor, o cargá ha_token en la configuración "
                             "(Perfil → Tokens de acceso de larga duración)")
            log.warning("Notificación de HA sin configurar. Falta %s",
                        "; ".join(falta))
        if self.canal in ("telegram", "ambos") and not self.tg_ok:
            log.warning("Telegram sin configurar")

    # -- canales ------------------------------------------------------

    def _telegram(self, texto):
        try:
            r = requests.post(
                "https://api.telegram.org/bot%s/sendMessage" % self.tg_token,
                json={"chat_id": self.tg_chat, "text": texto,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=15)
            if r.status_code != 200:
                log.error("Telegram %s: %s", r.status_code, r.text[:180])
                return False
            return True
        except Exception as e:
            log.error("Telegram fallo: %s", e)
            return False

    def _hass(self, titulo, texto, urgente=True):
        """Llama a notify.<servicio> por la API del Supervisor."""
        servicio = self.servicio_ha
        if servicio.startswith("notify."):
            servicio = servicio[len("notify."):]

        datos = {
            "title": titulo,
            "message": texto,
            "data": {
                "channel": "Ratios",
                "importance": "high" if urgente else "default",
                "ttl": 0,
                "priority": "high" if urgente else "normal",
            },
        }
        if self.panel:
            datos["data"]["clickAction"] = self.panel
            datos["data"]["actions"] = [
                {"action": "URI", "title": "Ver screener", "uri": self.panel}]
        try:
            r = requests.post(
                "%s/services/notify/%s" % (self.base_api, servicio),
                headers={"Authorization": "Bearer " + self.token,
                         "Content-Type": "application/json"},
                json=datos, timeout=15)
            if r.status_code >= 300:
                self.error_ha = "%s -> HTTP %s: %s" % (
                    self.base_api, r.status_code, r.text[:160])
                log.error("HA notify %s", self.error_ha)
                return False
            self.error_ha = None
            return True
        except Exception as e:
            self.error_ha = "%s -> %s: %s" % (
                self.base_api, type(e).__name__, str(e)[:200])
            log.error("HA notify %s", self.error_ha)
            return False

    # -- api ----------------------------------------------------------

    def enviar(self, titulo, texto_html, texto_plano=None, urgente=True):
        plano = texto_plano or _sin_html(texto_html)
        enviado = False

        if self.canal in ("ha", "ambos") and self.ha_ok:
            enviado = self._hass(titulo, plano, urgente) or enviado
        if self.canal in ("telegram", "ambos") and self.tg_ok:
            enviado = self._telegram(texto_html) or enviado

        if not enviado:
            log.info("[alerta no enviada] %s | %s", titulo, plano)
        return enviado

    def diagnostico(self):
        """Para el botón de prueba: qué está y qué falta."""
        # nombres (no valores) de las variables que podrían traer el token
        candidatas = sorted(k for k in os.environ
                            if "TOKEN" in k.upper() or "SUPERVISOR" in k.upper()
                            or "HASSIO" in k.upper())
        return {
            "env_detectadas": candidatas,
            "canal": self.canal,
            "ha_servicio": self.servicio_ha or None,
            "ha_token": bool(self.token),
            "via": self.via,
            "api": self.base_api,
            "ha_listo": self.ha_ok,
            "telegram_listo": self.tg_ok,
            "panel_path": self.panel or None,
            "error_ha": self.error_ha,
            "servicio_final": (self.servicio_ha or "").replace("notify.", ""),
        }

    def probar(self):
        ok = self.enviar("Ratios IOL",
                         "Prueba de notificación. Si te llegó, está andando.",
                         urgente=False)
        d = self.diagnostico()
        d["enviada"] = ok
        return d

    def publicar_sensor(self, alias, estado, atributos):
        """Expone el ratio como sensor de HA para dashboards y automatizaciones."""
        if not self.token:
            return False
        eid = "sensor.ratio_" + _slug(alias)
        try:
            r = requests.post(
                "%s/states/%s" % (self.base_api, eid),
                headers={"Authorization": "Bearer " + self.token,
                         "Content-Type": "application/json"},
                json={"state": round(estado, 6) if estado else None,
                      "attributes": atributos},
                timeout=10)
            return r.status_code < 300
        except Exception as e:
            log.debug("sensor %s: %s", eid, e)
            return False


def _sin_html(t):
    # El <br> tiene que volverse un salto real: Home Assistant muestra el
    # texto plano tal cual, asi que hasta ahora la etiqueta se veia
    # escrita en la notificacion.
    for a, b in (("<br>", "\n"), ("<br/>", "\n"), ("<br />", "\n"),
                 ("<b>", ""), ("</b>", ""), ("<i>", ""), ("</i>", "")):
        t = t.replace(a, b)
    return t


def _slug(s):
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_") or "par"
