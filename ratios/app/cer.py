"""Coeficiente de Estabilizacion de Referencia, desde la API del BCRA.

Serie 30 de estadisticas monetarias, base 2/2/2002 = 1. Es publica y no
necesita credenciales. Se cachea en la base: el CER de una fecha pasada no
cambia nunca, asi que se consulta una vez.
"""

import logging
from datetime import date, datetime, timedelta

import requests

import db

log = logging.getLogger("cer")

BASE = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/30"
BASE_V3 = "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/30"
REZAGO_HABILES = 10
ESPERA_TRAS_FALLO = 300

CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Accept-Language": "es-AR,es;q=0.9",
}

ultimo_error = None
ultima_respuesta = None
_ultimo_fallo = None

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cer (
    fecha  TEXT PRIMARY KEY,
    valor  REAL NOT NULL
);
"""


def init():
    c = db.conn()
    c.executescript(ESQUEMA)
    c.commit()


def reintentar_ya():
    global _ultimo_fallo
    _ultimo_fallo = None


def _guardar(filas):
    c = db.conn()
    c.executemany("INSERT OR REPLACE INTO cer (fecha, valor) VALUES (?,?)", filas)
    c.commit()


def _extraer(d):
    """Saca (fecha, valor) del JSON del BCRA.

    La v3 devuelve los valores sueltos en 'results'; la v4 los anida en
    'detalle'. Recorremos la estructura sin asumir cual vino.
    """
    filas = []

    def _mirar(x):
        if isinstance(x, list):
            for y in x:
                _mirar(y)
            return
        if not isinstance(x, dict):
            return
        f, v = x.get("fecha"), x.get("valor")
        if f is not None and v is not None:
            try:
                val = float(v)
            except (TypeError, ValueError):
                val = 0
            if val > 0:
                filas.append((str(f)[:10], val))
        for k in ("detalle", "results", "datos", "data"):
            if k in x:
                _mirar(x[k])

    _mirar(d)
    return sorted({f: v for f, v in filas}.items())


def descargar(desde, hasta, verificar_ssl=True):
    """Trae un rango del BCRA y lo guarda. Devuelve cuantos dias sumo."""
    global ultimo_error, ultima_respuesta, _ultimo_fallo

    if _ultimo_fallo and \
            (datetime.now() - _ultimo_fallo).total_seconds() < ESPERA_TRAS_FALLO:
        return 0

    params = {"desde": desde, "hasta": hasta, "limit": 3000}
    d = None
    intentos = [(BASE, True), (BASE_V3, True), (BASE, False), (BASE_V3, False)]
    if not verificar_ssl:
        intentos = [(BASE, False), (BASE_V3, False)]

    for url, verify in intentos:
        try:
            r = requests.get(url, params=params, headers=CABECERAS,
                             timeout=30, verify=verify)
            if r.status_code == 200:
                d = r.json() or {}
                ultima_respuesta = str(r.text)[:400]
                ultimo_error = None
                if not verify:
                    log.info("CER: el BCRA respondio sin verificar el certificado")
                break
            ultimo_error = "%s -> HTTP %s: %s" % (url, r.status_code, r.text[:120])
            log.warning("BCRA %s", ultimo_error)
        except Exception as e:
            ultimo_error = "%s -> %s: %s" % (url, type(e).__name__, str(e)[:160])
            log.warning("BCRA %s", ultimo_error)

    if d is None:
        _ultimo_fallo = datetime.now()
        return 0

    filas = _extraer(d)
    if filas:
        _ultimo_fallo = None
        _guardar(filas)
        log.info("CER: +%d dias entre %s y %s (ultimo %s = %s)",
                 len(filas), desde, hasta, filas[-1][0], filas[-1][1])
    else:
        ultimo_error = ("el BCRA respondio pero no encontre valores. "
                        "Claves recibidas: %s" % list(d)[:8])
        log.warning("CER: %s", ultimo_error)
        _ultimo_fallo = datetime.now()
    return len(filas)


def valor(f, verificar_ssl=True):
    """CER de una fecha. Si es feriado o fin de semana, toma el anterior."""
    if isinstance(f, date):
        f = f.isoformat()
    r = db.conn().execute(
        "SELECT fecha, valor FROM cer WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
        (f,)).fetchone()
    if r and (date.fromisoformat(f) - date.fromisoformat(r["fecha"])).days <= 7:
        return r["valor"]

    d = date.fromisoformat(f)
    descargar((d - timedelta(days=20)).isoformat(), f, verificar_ssl)
    r = db.conn().execute(
        "SELECT valor FROM cer WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
        (f,)).fetchone()
    return r["valor"] if r else None


def _restar_habiles(f, n):
    d = f
    while n > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def vigente(al=None, verificar_ssl=True):
    """CER que se aplica hoy: el de 10 dias habiles antes."""
    al = al or date.today()
    return valor(_restar_habiles(al, REZAGO_HABILES), verificar_ssl)


def base_de(emision, verificar_ssl=True):
    """CER a la fecha de emision de un bono."""
    if isinstance(emision, str):
        emision = date.fromisoformat(emision[:10])
    return valor(_restar_habiles(emision, REZAGO_HABILES), verificar_ssl)


def sincronizar(bonos, verificar_ssl=True):
    """Se asegura de tener el CER de cada emision y el de hoy."""
    faltan = []
    for tk, cfg in (bonos or {}).items():
        if (cfg.get("ajuste") or "").lower() != "cer":
            continue
        if not base_de(cfg.get("emision"), verificar_ssl):
            faltan.append(tk)
    if not vigente(verificar_ssl=verificar_ssl):
        faltan.append("actual")
    return faltan
