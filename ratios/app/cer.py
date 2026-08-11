"""Coeficiente de Estabilización de Referencia, desde la API del BCRA.

Serie 30 de estadísticas monetarias, base 2/2/2002 = 1. Es pública y no
necesita credenciales. Se cachea en la base: el CER de una fecha pasada no
cambia nunca, así que se consulta una vez.
"""

import logging
from datetime import date, timedelta

import requests

import db

log = logging.getLogger("cer")

BASE = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/30"
BASE_V3 = "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/30"
REZAGO_HABILES = 10     # el capital ajusta por el CER de 10 días hábiles antes

# El BCRA rechaza pedidos sin User-Agent de navegador.
CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Accept-Language": "es-AR,es;q=0.9",
}

ultimo_error = None
_ultimo_fallo = None
ESPERA_TRAS_FALLO = 300   # segundos

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


def _guardar(filas):
    c = db.conn()
    c.executemany("INSERT OR REPLACE INTO cer (fecha, valor) VALUES (?,?)", filas)
    c.commit()


def _de_la_base(desde, hasta):
    return {r["fecha"]: r["valor"] for r in db.conn().execute(
        "SELECT fecha, valor FROM cer WHERE fecha BETWEEN ? AND ?",
        (desde, hasta))}


def _intentar(url, params, verify):
    return requests.get(url, params=params, headers=CABECERAS,
                        timeout=30, verify=verify)


def reintentar_ya():
    """Limpia el enfriamiento: lo usa el botón de prueba."""
    global _ultimo_fallo
    _ultimo_fallo = None


def descargar(desde, hasta, verificar_ssl=True):
    """Trae un rango del BCRA y lo guarda. Devuelve cuántos días sumó.

    Prueba v4, después v3, y si el certificado falla reintenta sin
    verificarlo: los sitios del Estado suelen tener la cadena incompleta.
    """
    global ultimo_error, _ultimo_fallo
    from datetime import datetime as _dt

    # si el BCRA acaba de fallar, no lo golpeamos en cada consulta
    if _ultimo_fallo and (_dt.now() - _ultimo_fallo).total_seconds() < ESPERA_TRAS_FALLO:
        return 0

    params = {"desde": desde, "hasta": hasta, "limit": 3000}
    d = None
    intentos = [(BASE, True), (BASE_V3, True), (BASE, False), (BASE_V3, False)]
    if not verificar_ssl:
        intentos = [(BASE, False), (BASE_V3, False)]

    for url, verify in intentos:
        try:
            r = _intentar(url, params, verify)
            if r.status_code == 200:
                d = r.json() or {}
                ultimo_error = None
                if not verify:
                    log.info("CER: el BCRA respondió sin verificar el "
                             "certificado (cadena incompleta de su lado)")
                break
            ultimo_error = "%s -> HTTP %s: %s" % (url, r.status_code, r.text[:120])
            log.warning("BCRA %s", ultimo_error)
        except Exception as e:
            ultimo_error = "%s -> %s: %s" % (url, type(e).__name__, str(e)[:160])
            log.warning("BCRA %s", ultimo_error)

    if d is None:
        _ultimo_fallo = _dt.now()
        return 0
    _ultimo_fallo = None

    filas = []
    for x in (d.get("results") or []):
        f = str(x.get("fecha") or "")[:10]
        try:
            v = float(x.get("valor"))
        except (TypeError, ValueError):
            continue
        if f and v > 0:
            filas.append((f, v))
    if filas:
        _guardar(filas)
        log.info("CER: +%d días entre %s y %s", len(filas), desde, hasta)
    return len(filas)


def valor(f, verificar_ssl=True):
    """CER de una fecha. Si es feriado o fin de semana, toma el anterior."""
    if isinstance(f, date):
        f = f.isoformat()
    r = db.conn().execute(
        "SELECT valor FROM cer WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
        (f,)).fetchone()
    if r:
        # si el más cercano quedó a más de una semana, falta descargar
        r2 = db.conn().execute(
            "SELECT fecha FROM cer WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
            (f,)).fetchone()
        if r2 and (date.fromisoformat(f) - date.fromisoformat(r2["fecha"])).days <= 7:
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
    """CER que se aplica hoy: el de 10 días hábiles antes."""
    al = al or date.today()
    return valor(_restar_habiles(al, REZAGO_HABILES), verificar_ssl)


def base_de(emision, verificar_ssl=True):
    """CER a la fecha de emisión de un bono, para el ajuste del capital."""
    if isinstance(emision, str):
        emision = date.fromisoformat(emision[:10])
    return valor(_restar_habiles(emision, REZAGO_HABILES), verificar_ssl)


def sincronizar(bonos, verificar_ssl=True):
    """Se asegura de tener el CER de cada emisión y el de hoy."""
    faltan = []
    for tk, cfg in (bonos or {}).items():
        if (cfg.get("ajuste") or "").lower() != "cer":
            continue
        if not base_de(cfg.get("emision"), verificar_ssl):
            faltan.append(tk)
    if not vigente(verificar_ssl=verificar_ssl):
        faltan.append("actual")
    return faltan
