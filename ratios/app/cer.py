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
REZAGO_HABILES = 10     # el capital ajusta por el CER de 10 días hábiles antes

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


def descargar(desde, hasta, verificar_ssl=True):
    """Trae un rango del BCRA y lo guarda. Devuelve cuántos días sumó."""
    try:
        r = requests.get(BASE, params={"desde": desde, "hasta": hasta,
                                       "limit": 3000},
                         timeout=30, verify=verificar_ssl)
        if r.status_code != 200:
            log.warning("BCRA %s: %s", r.status_code, r.text[:150])
            return 0
        d = r.json() or {}
    except Exception as e:
        log.warning("BCRA no respondió (%s): %s", desde, e)
        return 0

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
