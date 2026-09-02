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
# El BCRA publica varias series de tipo de cambio: minorista, mayorista
# A3500 y los limites de la banda. La que corresponde a un dolar linked
# es la A3500 de referencia. El numero se descubre listando el catalogo,
# no adivinando.
SERIE = 5
REZAGO_HABILES = 1
CATALOGO = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias"

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


CLAVE_SERIE = "a3500_serie"


def serie_efectiva(verificar_ssl=True):
    """La serie a usar: la guardada, o la que encuentre en el catalogo."""
    guardada = db.get_estado(CLAVE_SERIE)
    if guardada:
        try:
            return int(guardada)
        except ValueError:
            pass
    f = buscar_a3500(verificar_ssl)
    if f:
        try:
            n = int(f["id"])
        except (TypeError, ValueError):
            return SERIE
        # primera deteccion: lo que hubiera bajado antes se hizo con una
        # serie sin confirmar, asi que no es confiable
        c = db.conn()
        hay = c.execute("SELECT COUNT(*) n FROM a3500").fetchone()["n"]
        if hay:
            c.execute("DELETE FROM a3500")
            c.commit()
            log.info("A3500: se descarto lo bajado antes de fijar la serie")
        db.set_estado(CLAVE_SERIE, n)
        log.info("A3500: serie %s (%s)", n, f["descripcion"][:80])
        return n
    return SERIE


def fijar_serie(n):
    """Cambiar de serie invalida lo guardado.

    Si se bajo con la serie equivocada, los valores viejos siguen ahi y
    conviven con los nuevos: al ser la misma tabla indexada por fecha, se
    mezclarian dos series distintas.
    """
    n = int(n)
    previa = db.get_estado(CLAVE_SERIE)
    if previa and str(previa) != str(n):
        c = db.conn()
        c.execute("DELETE FROM a3500")
        c.commit()
        log.info("A3500: serie %s -> %s, se borro lo guardado", previa, n)
    db.set_estado(CLAVE_SERIE, n)


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

    v4, v3 = _urls(serie or serie_efectiva(verificar_ssl))
    params = {"desde": desde, "hasta": hasta, "limit": 3000}
    intentos = [(v4, True), (v3, True), (v4, False), (v3, False)]
    if not verificar_ssl:
        intentos = [(v4, False), (v3, False)]

    d = None
    for url, verify in intentos:
        try:
            import red
            r = red.get(url, "bcra_a3500", params=params, headers=CABECERAS,
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


def catalogo(verificar_ssl=True):
    """Las series que publica el BCRA, con su numero y descripcion."""
    global ultimo_error
    for url, verify in ((CATALOGO, verificar_ssl), (CATALOGO, False)):
        try:
            import red
            r = red.get(url, "bcra_a3500", headers=CABECERAS, timeout=30,
                        verify=verify)
            if r.status_code != 200:
                ultimo_error = "%s -> HTTP %s" % (url, r.status_code)
                continue
            d = r.json() or {}
        except Exception as e:
            ultimo_error = "%s: %s" % (type(e).__name__, str(e)[:160])
            continue

        filas = []

        def _mirar(x):
            if isinstance(x, list):
                for y in x:
                    _mirar(y)
                return
            if not isinstance(x, dict):
                return
            idv = x.get("idVariable") or x.get("id")
            desc = x.get("descripcion") or x.get("descripcionSerie")
            if idv is not None and desc:
                filas.append({"id": idv, "descripcion": str(desc),
                              "valor": x.get("valor"),
                              "fecha": x.get("fecha")})
            for k in ("results", "detalle", "datos", "data"):
                if k in x:
                    _mirar(x[k])

        _mirar(d)
        if filas:
            ultimo_error = None
            return filas
    return []


def buscar_a3500(verificar_ssl=True):
    """El numero de serie del mayorista A3500, buscado por descripcion.

    Evita depender de un numero fijo: si el BCRA reordena el catalogo, se
    vuelve a encontrar solo.
    """
    for f in catalogo(verificar_ssl):
        t = f["descripcion"].lower()
        if "3500" in t and "mayorista" in t:
            return f
    for f in catalogo(verificar_ssl):
        if "3500" in f["descripcion"]:
            return f
    return None


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
            "serie": db.get_estado(CLAVE_SERIE) or SERIE,
            "ultimo_error": ultimo_error,
            "vigente": vigente() if r["n"] else None}
