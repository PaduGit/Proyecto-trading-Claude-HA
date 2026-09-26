"""Tasa TAMAR de bancos privados, desde la API del BCRA.

Variable 44 de estadisticas monetarias, en porcentaje nominal anual:
tasa de plazos fijos de mas de mil millones de pesos. La 45 es la misma
en efectivo anual y no sirve: los bonos le suman el margen a la nominal.

Se usa en los bonos duales CER/TAMAR. La pata TAMAR no toma la tasa de
un dia: toma el promedio aritmetico simple de todas las publicadas
entre diez habiles antes de la emision y diez habiles antes del
vencimiento. `promedio_proyectado()` arma ese promedio con lo publicado
hasta hoy y completa el resto con la tasa vigente, que es el mismo
criterio de proyeccion que la BADLAR: un valor constante hasta el final.
"""

import logging
from datetime import date, timedelta

import requests

import cer as CER
import db

log = logging.getLogger("tamar")

BASE = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/44"
BASE_V3 = "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/44"
REZAGO_HABILES = 10

ultimo_error = None
ultima_respuesta = None
_ultimo_fallo = None
ESPERA_TRAS_FALLO = 300   # segundos

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tamar (
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
    c.executemany("INSERT OR REPLACE INTO tamar (fecha, valor) VALUES (?,?)",
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
            import red
            r = red.get(url, "bcra_tamar", params=params,
                        headers=CER.CABECERAS, timeout=30, verify=verify)
            if r.status_code == 200:
                d = r.json() or {}
                ultima_respuesta = str(r.text)[:400]
                ultimo_error = None
                break
            # el rango pedido va en el mensaje: sin eso un 500 no se
            # puede reproducir desde afuera
            ultimo_error = "%s?desde=%s&hasta=%s -> HTTP %s: %s" % (
                url, desde, hasta, r.status_code, (r.text or "")[:200] or "(cuerpo vacio)")
            log.warning("BCRA %s", ultimo_error)
        except Exception as e:
            ultimo_error = "%s?desde=%s&hasta=%s -> %s: %s" % (
                url, desde, hasta, type(e).__name__, str(e)[:160])
            log.warning("BCRA %s", ultimo_error)

    if d is None:
        _ultimo_fallo = _dt.now()
        return 0
    _ultimo_fallo = None

    # el JSON del BCRA tiene el mismo formato para todas las series
    filas = CER._extraer(d)
    if filas:
        _guardar(filas)
        log.info("TAMAR: +%d días entre %s y %s (último %s = %s)",
                 len(filas), desde, hasta, filas[-1][0], filas[-1][1])
    else:
        ultimo_error = ("el BCRA respondió pero no encontré valores. "
                        "Claves recibidas: %s" % list(d)[:8])
        log.warning("TAMAR: %s", ultimo_error)
        _ultimo_fallo = _dt.now()
    return len(filas)


_fallidas = set()
_intentados = set()


def valor(f, verificar_ssl=True):
    """TAMAR publicada a una fecha, en % nominal anual.

    Si el día no tiene publicación (feriado o fin de semana), toma la
    última anterior. Devuelve None si no hay dato ni se pudo bajar.
    """
    if isinstance(f, date):
        f = f.isoformat()
    r = db.conn().execute(
        "SELECT fecha, valor FROM tamar WHERE fecha <= ? "
        "ORDER BY fecha DESC LIMIT 1", (f,)).fetchone()
    if r and (date.fromisoformat(f) - date.fromisoformat(r["fecha"])).days <= 7:
        return r["valor"]

    if f in _fallidas:
        return r["valor"] if r else None
    descargar((date.fromisoformat(f) - timedelta(days=30)).isoformat(),
              f, verificar_ssl)
    r2 = db.conn().execute(
        "SELECT valor FROM tamar WHERE fecha <= ? "
        "ORDER BY fecha DESC LIMIT 1", (f,)).fetchone()
    if r2:
        return r2["valor"]
    _fallidas.add(f)
    return None


def vigente(al=None, verificar_ssl=True):
    """TAMAR aplicable a una fecha, ya rezagada 10 días hábiles.

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


def devengado(desde, hasta, verificar_ssl=True):
    """Lo que rindió la TAMAR entre dos fechas, en tanto por uno.

    TAMAR no es un índice: es una tasa nominal anual que se publica
    todos los días hábiles. Comparar el nivel de hoy contra el del alta
    —23,50% contra 23,18%— da un 1,4% que no significa nada. Lo que hay
    que medir es lo que se hubiera devengado colocando a esa tasa día
    por día.

    Se capitaliza diario sobre actual/365, arrastrando la última tasa
    publicada en los días sin publicación, que es como liquida un plazo
    fijo. Devuelve None si no hay serie que cubra el período: es
    preferible no mostrar el patrón a mostrarlo mal.
    """
    if isinstance(desde, str):
        desde = date.fromisoformat(desde[:10])
    if isinstance(hasta, str):
        hasta = date.fromisoformat(hasta[:10])
    if not desde or not hasta or hasta <= desde:
        return 0.0

    # Solo se baja si la serie local no cubre el periodo. `medir()` corre
    # en cada request de la cartera: llamar a asegurar_rango siempre le
    # pegaba al BCRA aunque el dato ya estuviera, porque su control es
    # por tramo anual completo y un alta de hace tres meses nunca llega a
    # los 200 dias que espera.
    cob = db.conn().execute(
        "SELECT MIN(fecha) AS d0, MAX(fecha) AS d1, COUNT(*) AS n "
        "FROM tamar WHERE fecha BETWEEN ? AND ?",
        (desde.isoformat(), hasta.isoformat())).fetchone()
    habiles = sum(1 for i in range((hasta - desde).days)
                  if (desde + timedelta(days=i)).weekday() < 5)
    if not cob or (cob["n"] or 0) < habiles * 0.8:
        asegurar_rango(desde, hasta, verificar_ssl)
    filas = db.conn().execute(
        "SELECT fecha, valor FROM tamar WHERE fecha BETWEEN ? AND ? "
        "ORDER BY fecha", (desde.isoformat(), hasta.isoformat())).fetchall()
    if not filas:
        return None

    tasas = {f["fecha"]: f["valor"] for f in filas}
    # la tasa vigente al arrancar, por si el alta cayó en fin de semana
    ultima = valor(desde, verificar_ssl)
    if ultima is None:
        return None

    acum = 1.0
    d = desde
    while d < hasta:
        ultima = tasas.get(d.isoformat(), ultima)
        acum *= 1 + (ultima / 100.0) / 365.0
        d += timedelta(days=1)
    return acum - 1


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
    # el BCRA responde 500 si el rango termina en el futuro
    hoy = date.today()
    if d1 > hoy:
        d1 = hoy
    total = 0
    while d0 <= d1:
        corte = min(date(d0.year, 12, 31), d1, hoy)
        hay = db.conn().execute(
            "SELECT COUNT(*) AS n FROM tamar WHERE fecha BETWEEN ? AND ?",
            (d0.isoformat(), corte.isoformat())).fetchone()
        # Se compara contra los habiles del tramo, no contra un año
        # entero: los duales piden tramos parciales en cada valuacion y
        # con el umbral fijo de la BADLAR se bajaria el tramo cada vez.
        # Y un tramo ya intentado hoy no se vuelve a pedir.
        habiles = sum(1 for i in range((corte - d0).days + 1)
                      if CER.es_habil(d0 + timedelta(days=i)))
        clave = (d0.isoformat(), corte.isoformat(), hoy.isoformat())
        if ((not hay or (hay["n"] or 0) < habiles * 0.9 - 2)
                and clave not in _intentados):
            _intentados.add(clave)
            total += descargar(d0.isoformat(), corte.isoformat(), verificar_ssl)
        d0 = date(d0.year + 1, 1, 1)
    return total


def resumen():
    """Cobertura de la serie, para la pestaña Explorar."""
    r = db.conn().execute(
        "SELECT COUNT(*) AS n, MIN(fecha) AS desde, MAX(fecha) AS hasta "
        "FROM tamar").fetchone()
    if not r or not r["n"]:
        return {"dias": 0, "desde": None, "hasta": None, "ultimo": None}
    u = db.conn().execute(
        "SELECT valor FROM tamar ORDER BY fecha DESC LIMIT 1").fetchone()
    return {"dias": r["n"], "desde": r["desde"], "hasta": r["hasta"],
            "ultimo": u["valor"] if u else None}


def promedio_proyectado(inicio, fin, al=None, verificar_ssl=True):
    """Promedio simple de la TAMAR entre dos fechas, a lo que se sabe hoy.

    `inicio` y `fin` son las fechas ya rezagadas del bono: diez habiles
    antes de la emision y diez habiles antes del vencimiento. Lo
    publicado hasta el rezago de `al` entra con su valor; los dias
    habiles que faltan hasta `fin` entran con la tasa vigente. Devuelve
    (promedio, dias_publicados, dias_proyectados) o None si no hay dato.
    """
    al = al or date.today()
    if isinstance(al, str):
        al = date.fromisoformat(al[:10])
    corte = CER._restar_habiles(al, REZAGO_HABILES)
    tope = min(corte, fin)
    if inicio <= tope:
        asegurar_rango(inicio, tope, verificar_ssl)
    filas = db.conn().execute(
        "SELECT valor FROM tamar WHERE fecha BETWEEN ? AND ?",
        (inicio.isoformat(), tope.isoformat())).fetchall()
    publicados = [f["valor"] for f in filas]
    vig = valor(tope, verificar_ssl)
    if vig is None and not publicados:
        return None
    faltan = 0
    d = max(tope, inicio - timedelta(days=1)) + timedelta(days=1)
    while d <= fin:
        if CER.es_habil(d):
            faltan += 1
        d += timedelta(days=1)
    if faltan and vig is None:
        return None
    total = sum(publicados) + (vig or 0) * faltan
    n = len(publicados) + faltan
    if not n:
        return None
    return total / n, len(publicados), faltan
