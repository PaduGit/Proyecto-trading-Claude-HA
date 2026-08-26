"""Tipo de cambio mayorista de referencia, Comunicacion A 3500.

Es lo que necesitan los bonos dolar linked: estan denominados en dolares
pero cotizan y pagan en pesos, convertidos a ese tipo de cambio. Sin la
serie no se puede calcular ni el valor tecnico ni la TIR.

Misma mecanica que el CER: se baja del BCRA por tramos, se guarda en la
base y se sirve de ahi. La diferencia es el rezago: el CER ajusta con el
valor de diez habiles antes, y el A3500 con el del dia habil anterior al
pago, que es la convencion habitual de estos instrumentos.
"""

import logging
from datetime import date, datetime, timedelta

import requests

import db
import cer as CER          # reutiliza el calendario de dias habiles

log = logging.getLogger("dolar")

# La serie del BCRA. No la pude confirmar contra la documentacion, asi
# que es configurable: si el numero no fuera este, la opcion "Probar
# A3500" del menu lo dice en un toque.
SERIE = 4
REZAGO_HABILES = 1

CABECERAS = CER.CABECERAS
ESPERA_TRAS_FALLO = 300

ultimo_error = None
ultima_respuesta = None
_ultimo_fallo = None

ESQUEMA = """
CREATE TABLE IF NOT EXISTS a3500 (
    fecha  TEXT PRIMARY KEY,
    valor  REAL NOT NULL
);
"""


def init():
    c = db.conn()
    c.executescript(ESQUEMA)
    c.commit()


def _urls(serie=None):
    s = serie or SERIE
    return ("https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/%s" % s,
            "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/%s" % s)


def _guardar(filas):
    c = db.conn()
    c.executemany("INSERT OR REPLACE INTO a3500 (fecha, valor) VALUES (?,?)",
                  filas)
    c.commit()


def reintentar_ya():
    global _ultimo_fallo
    _ultimo_fallo = None


def descargar(desde, hasta, verificar_ssl=True, serie=None):
    """Trae un rango del BCRA y lo guarda. Devuelve cuantos dias sumo."""
    global ultimo_error, ultima_respuesta, _ultimo_fallo

    if _ultimo_fallo and (datetime.now() - _ultimo_fallo).total_seconds() \
            < ESPERA_TRAS_FALLO:
        return 0

    v4, v3 = _urls(serie)
    params = {"desde": desde, "hasta": hasta, "limit": 3000}
    intentos = [(v4, True), (v3, True), (v4, False), (v3, False)]
    if not verificar_ssl:
        intentos = [(v4, False), (v3, False)]

    d = None
    for url, verify in intentos:
        try:
            r = requests.get(url, params=params, headers=CABECERAS,
                             timeout=30, verify=verify)
            if r.status_code == 200:
                d = r.json() or {}
                ultima_respuesta = str(r.text)[:400]
                ultimo_error = None
                break
            ultimo_error = "%s -> HTTP %s: %s" % (url, r.status_code,
                                                  r.text[:120])
            log.warning("BCRA %s", ultimo_error)
        except Exception as e:
            ultimo_error = "%s -> %s: %s" % (url, type(e).__name__,
                                             str(e)[:160])
            log.warning("BCRA %s", ultimo_error)

    if d is None:
        _ultimo_fallo = datetime.now()
        return 0
    _ultimo_fallo = None

    filas = CER._extraer(d)
    if filas:
        _guardar(filas)
        log.info("A3500: +%d dias entre %s y %s (ultimo %s = %s)",
                 len(filas), desde, hasta, filas[-1][0], filas[-1][1])
    else:
        ultimo_error = ("el BCRA respondio pero no encontre valores. "
                        "Claves recibidas: %s" % list(d)[:8])
        log.warning("A3500: %s", ultimo_error)
        _ultimo_fallo = datetime.now()
    return len(filas)


def valor(f, verificar_ssl=True):
    """El A3500 de una fecha, o el ultimo anterior si ese dia no hubo.

    El tipo de cambio no publica los fines de semana ni feriados, asi que
    se toma el ultimo disponible en vez de devolver nada.
    """
    if isinstance(f, str):
        f = date.fromisoformat(f[:10])
    txt = f.isoformat()

    r = db.conn().execute(
        "SELECT fecha, valor FROM a3500 WHERE fecha <= ? "
        "ORDER BY fecha DESC LIMIT 1", (txt,)).fetchone()
    if r and (f - date.fromisoformat(r["fecha"])).days <= 7:
        return r["valor"]

    descargar((f - timedelta(days=30)).isoformat(), txt, verificar_ssl)
    r = db.conn().execute(
        "SELECT fecha, valor FROM a3500 WHERE fecha <= ? "
        "ORDER BY fecha DESC LIMIT 1", (txt,)).fetchone()
    return r["valor"] if r else None


def vigente(al=None, verificar_ssl=True):
    """El que corresponde hoy, con el rezago de un dia habil."""
    d = al or date.today()
    for _ in range(REZAGO_HABILES):
        d -= timedelta(days=1)
        while not CER.es_habil(d):
            d -= timedelta(days=1)
    return valor(d, verificar_ssl)


def asegurar_rango(desde, hasta, verificar_ssl=True):
    """Baja lo que falte del rango, por tramos anuales.

    El BCRA corta la respuesta si el rango es largo, igual que con el
    CER.
    """
    if isinstance(desde, str):
        desde = date.fromisoformat(desde[:10])
    if isinstance(hasta, str):
        hasta = date.fromisoformat(hasta[:10])
    total = 0
    tramo = desde
    while tramo <= hasta:
        fin = min(date(tramo.year, 12, 31), hasta)
        hay = db.conn().execute(
            "SELECT COUNT(*) n FROM a3500 WHERE fecha BETWEEN ? AND ?",
            (tramo.isoformat(), fin.isoformat())).fetchone()["n"]
        # un anio habil ronda los 250 dias; si hay muchos menos, falta
        if hay < (fin - tramo).days * 0.5:
            total += descargar(tramo.isoformat(), fin.isoformat(),
                               verificar_ssl)
        tramo = date(tramo.year + 1, 1, 1)
    return total


def estado():
    r = db.conn().execute(
        "SELECT COUNT(*) n, MIN(fecha) desde, MAX(fecha) hasta "
        "FROM a3500").fetchone()
    return {"dias": r["n"], "desde": r["desde"], "hasta": r["hasta"],
            "serie": SERIE, "ultimo_error": ultimo_error,
            "vigente": vigente() if r["n"] else None}
