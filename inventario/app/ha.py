"""Lectura de Home Assistant: registros por websocket, versión y host por el Supervisor.

Los registros (áreas, dispositivos, entidades) no están en la API REST: solo
por websocket, y requieren un usuario administrador.
"""
import json
import logging
import os
import urllib.request

from websocket import create_connection

log = logging.getLogger("ha")

SUP_WS = "ws://supervisor/core/websocket"
SUP_API = "http://supervisor"
URL_POR_DEFECTO = "http://192.168.1.10:8123"


class ErrorHA(Exception):
    pass


def token_supervisor():
    """La imagen base arranca con s6, que limpia el entorno: el token puede
    no llegar como variable y quedar en /run/s6/container_environment."""
    for k in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    for k in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN"):
        try:
            with open(os.path.join("/run/s6/container_environment", k), encoding="utf-8") as f:
                t = f.read().strip()
            if t:
                return t
        except OSError:
            continue
    return ""


class ClienteWS:
    def __init__(self, url, token, timeout=20):
        self.ws = create_connection(url, timeout=timeout)
        msg = json.loads(self.ws.recv())
        if msg.get("type") != "auth_required":
            raise ErrorHA("respuesta inesperada al conectar: %s" % msg.get("type"))
        self.ws.send(json.dumps({"type": "auth", "access_token": token}))
        msg = json.loads(self.ws.recv())
        if msg.get("type") != "auth_ok":
            raise ErrorHA("autenticación rechazada (%s)" % (msg.get("message") or msg.get("type")))
        self.ha_version = msg.get("ha_version", "")
        self.n = 0

    def pedir(self, tipo, **extra):
        self.n += 1
        pedido = {"id": self.n, "type": tipo}
        pedido.update(extra)
        self.ws.send(json.dumps(pedido))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") != self.n or msg.get("type") != "result":
                continue
            if not msg.get("success"):
                err = msg.get("error") or {}
                raise ErrorHA("%s: %s" % (tipo, err.get("message") or err.get("code") or "error"))
            return msg.get("result")

    def cerrar(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _candidatos(cfg):
    out = []
    propio = (cfg.get("ha_token") or "").strip()
    if propio:
        url = (cfg.get("ha_url") or URL_POR_DEFECTO).strip().rstrip("/")
        ws = url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/api/websocket"
        out.append(("token propio", ws, propio))
    sup = token_supervisor()
    if sup:
        out.append(("supervisor", SUP_WS, sup))
    return out


def _conectar(cfg):
    errores = []
    for via, url, token in _candidatos(cfg):
        try:
            return via, ClienteWS(url, token)
        except Exception as e:
            log.warning("conexión %s falló: %s", via, e)
            errores.append("%s: %s" % (via, e))
    if not errores:
        raise ErrorHA("sin token: cargá ha_token en la configuración de la app")
    raise ErrorHA("no se pudo conectar (" + " · ".join(errores) + ")")


def leer_registros(cfg):
    via, cli = _conectar(cfg)
    try:
        datos = {
            "via": via,
            "ha_version": cli.ha_version,
            "areas": cli.pedir("config/area_registry/list"),
            "dispositivos": cli.pedir("config/device_registry/list"),
            "entidades": cli.pedir("config/entity_registry/list"),
            "estados": cli.pedir("get_states"),
            "config": cli.pedir("get_config"),
        }
        try:
            datos["pisos"] = cli.pedir("config/floor_registry/list")
        except ErrorHA:
            datos["pisos"] = []
        return datos
    finally:
        cli.cerrar()


def _sup_get(ruta, token):
    req = urllib.request.Request(SUP_API + ruta, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=10) as r:
        return (json.loads(r.read().decode("utf-8")) or {}).get("data") or {}


def info_supervisor():
    """Versión de Supervisor y OS, máquina y host. Si falla, vuelve vacío."""
    token = token_supervisor()
    if not token:
        return {}
    info = {}
    for ruta in ("/info", "/host/info"):
        try:
            info.update(_sup_get(ruta, token))
        except Exception as e:
            log.warning("supervisor %s: %s", ruta, e)
    return info
