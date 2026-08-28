"""Tasa BADLAR de bancos privados, desde la API del BCRA.

Serie 7 de estadísticas monetarias, en porcentaje nominal anual. Es
pública y no necesita credenciales. Se cachea en la base igual que el
CER: la tasa de un día pasado no cambia nunca.

A diferencia del CER, que es un coeficiente puntual, la BADLAR se usa
para proyectar cupones futuros. La convención acordada es tomar el
valor de una sola fecha y proyectarlo constante hasta el vencimiento,
con el mismo rezago de 10 días hábiles que usa el CER. Así un punto
histórico ya guardado no cambia cuando el BCRA publica tasas nuevas.
"""

import logging
from datetime import date, timedelta

import requests

import cer as CER
import db

log = logging.getLogger("badlar")

BASE = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/7"
BASE_V3 = "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/7"
REZAGO_HABILES = 10

ultimo_error = None
ultima_respuesta = None
_ultimo_fallo = None
ESPERA_TRAS_FALLO = 300   # segundos

ESQUEMA = """
CREATE TABLE IF NOT EXISTS badlar (
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
    c.executemany("INSERT OR REPLACE INTO badlar (fecha, valor) VALUES (?,?)",
                  filas)
    c.commit()


def reintentar_ya():
    """Limpia el enfriamiento: lo usa el botón de prueba."""
    global _ultimo_fallo
    _ultimo_fallo = None


def descargar(desde, hasta, verificar_ssl=True):
    """Trae un rango del BCRA y lo guarda. Devuelve cuántos días sumó.

    Misma secuencia de intentos que el CER: v4, después v3, y si el
    certificado falla reintenta sin verificarlo.
    """
    global ultimo_error, ultima_respuesta, _ultimo_fallo
    from datetime import datetime as _dt

    if _ultimo_fallo and (_dt.now() - _ultimo_fallo).total_seconds() < ESPERA_TRAS_FALLO:
        return 0

    params = {"desde": desde, "hasta": hasta, "limit": 3000}
    d = None
    intentos = [(BASE, True), (BASE_V3, True), (BASE, False), (BASE_V3, False)]
    if not verificar_ssl:
        intentos = [(BASE, False), (BASE_V3, False)]

    for url, verify in intentos:
        try:
            r = requests.get(url, params=params, headers=CER.CABECERAS,
                             timeout=30, verify=verify)
            if r.status_code == 200:
                d = r.json() or {}
                ultima_respuesta = str(r.text)[:400]
                ultimo_error = None
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

    # el JSON del BCRA tiene el mismo formato para todas las series
    filas = CER._extraer(d)
    if filas:
        _guardar(filas)
        log.info("BADLAR: +%d días entre %s y %s (último %s = %s)",
                 len(filas), desde, hasta, filas[-1][0], filas[-1][1])
    else:
        ultimo_error = ("el BCRA respondió pero no encontré valores. "
                        "Claves recibidas: %s" % list(d)[:8])
        log.warning("BADLAR: %s", ultimo_error)
        _ultimo_fallo = _dt.now()
    return len(filas)


_fallidas = set()


def valor(f, verificar_ssl=True):
    """BADLAR publicada a una fecha, en % nominal anual.

    Si el día no tiene publicación (feriado o fin de semana), toma la
    última anterior. Devuelve None si no hay dato ni se pudo bajar.
    """
    if isinstance(f, date):
        f = f.isoformat()
    r = db.conn().execute(
        "SELECT fecha, valor FROM badlar WHERE fecha <= ? "
        "ORDER BY fecha DESC LIMIT 1", (f,)).fetchone()
    if r and (date.fromisoformat(f) - date.fromisoformat(r["fecha"])).days <= 7:
        return r["valor"]

    if f in _fallidas:
        return r["valor"] if r else None
    descargar((date.fromisoformat(f) - timedelta(days=30)).isoformat(),
              f, verificar_ssl)
    r2 = db.conn().execute(
        "SELECT valor FROM badlar WHERE fecha <= ? "
        "ORDER BY fecha DESC LIMIT 1", (f,)).fetchone()
    if r2:
        return r2["valor"]
    _fallidas.add(f)
    return None


def vigente(al=None, verificar_ssl=True):
    """BADLAR aplicable a una fecha, ya rezagada 10 días hábiles.

    Es la que hay que usar para valuar: el prospecto cierra el cálculo
    diez hábiles antes, así que la tasa de hoy todavía no rige.
    """
    al = al or date.today()
    if not isinstance(al, date):
        al = date.fromisoformat(str(al)[:10])
    return valor(CER._restar_habiles(al, REZAGO_HABILES), verificar_ssl)


def tasa(al=None, verificar_ssl=True):
    """Igual que vigente() pero en tanto por uno, listo para devengar."""
    v = vigente(al, verificar_ssl)
    return None if v is None else v / 100.0


def asegurar_rango(desde, hasta, verificar_ssl=True):
    """Descarga lo que falte para cubrir un rango, por tramos anuales.

    La respuesta tiene tope de 3000 registros, así que un pedido de
    varios años se corta. La serie arranca en 1999.
    """
    if isinstance(desde, date):
        desde = desde.isoformat()
    if isinstance(hasta, date):
        hasta = hasta.isoformat()
    d0 = date.fromisoformat(desde)
    d1 = date.fromisoformat(hasta)
    total = 0
    while d0 <= d1:
        corte = min(date(d0.year, 12, 31), d1)
        hay = db.conn().execute(
            "SELECT COUNT(*) AS n FROM badlar WHERE fecha BETWEEN ? AND ?",
            (d0.isoformat(), corte.isoformat())).fetchone()
        # un año hábil ronda los 250 días; si falta mucho, se baja el tramo
        if not hay or (hay["n"] or 0) < 200:
            total += descargar(d0.isoformat(), corte.isoformat(), verificar_ssl)
        d0 = date(d0.year + 1, 1, 1)
    return total


def resumen():
    """Cobertura de la serie, para la pestaña Explorar."""
    r = db.conn().execute(
        "SELECT COUNT(*) AS n, MIN(fecha) AS desde, MAX(fecha) AS hasta "
        "FROM badlar").fetchone()
    if not r or not r["n"]:
        return {"dias": 0, "desde": None, "hasta": None, "ultimo": None}
    u = db.conn().execute(
        "SELECT valor FROM badlar ORDER BY fecha DESC LIMIT 1").fetchone()
    return {"dias": r["n"], "desde": r["desde"], "hasta": r["hasta"],
            "ultimo": u["valor"] if u else None}
