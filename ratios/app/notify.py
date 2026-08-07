"""Envio de alertas: notificacion nativa de HA y/o Telegram."""

import logging
import os

import requests

log = logging.getLogger("notify")

SUPERVISOR = "http://supervisor/core/api"


class Notificador:
    def __init__(self, cfg):
        self.canal = (cfg.get("canal_alertas") or "ambos").lower()
        self.tg_token = (cfg.get("telegram_token") or "").strip()
        self.tg_chat = (cfg.get("telegram_chat_id") or "").strip()
        self.servicio_ha = (cfg.get("ha_notify_service") or "").strip()
        self.token_sup = os.environ.get("SUPERVISOR_TOKEN", "")

        self.tg_ok = bool(self.tg_token and self.tg_chat)
        self.ha_ok = bool(self.servicio_ha and self.token_sup)

        if self.canal in ("ha", "ambos") and not self.ha_ok:
            log.warning("Notificacion de HA sin configurar "
                        "(falta ha_notify_service o el token del Supervisor)")
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
                "clickAction": "/ratios_iol",
                "actions": [
                    {"action": "URI", "title": "Ver screener",
                     "uri": "/ratios_iol"},
                ],
            },
        }
        try:
            r = requests.post(
                "%s/services/notify/%s" % (SUPERVISOR, servicio),
                headers={"Authorization": "Bearer " + self.token_sup,
                         "Content-Type": "application/json"},
                json=datos, timeout=15)
            if r.status_code >= 300:
                log.error("HA notify %s: %s", r.status_code, r.text[:180])
                return False
            return True
        except Exception as e:
            log.error("HA notify fallo: %s", e)
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

    def publicar_sensor(self, alias, estado, atributos):
        """Expone el ratio como sensor de HA para dashboards y automatizaciones."""
        if not self.token_sup:
            return False
        eid = "sensor.ratio_" + _slug(alias)
        try:
            r = requests.post(
                "%s/states/%s" % (SUPERVISOR, eid),
                headers={"Authorization": "Bearer " + self.token_sup,
                         "Content-Type": "application/json"},
                json={"state": round(estado, 6) if estado else None,
                      "attributes": atributos},
                timeout=10)
            return r.status_code < 300
        except Exception as e:
            log.debug("sensor %s: %s", eid, e)
            return False


def _sin_html(t):
    for a, b in (("<b>", ""), ("</b>", ""), ("<i>", ""), ("</i>", "")):
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
