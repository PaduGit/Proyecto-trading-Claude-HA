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
ultima_respuesta = None
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



def _extraer(d):
    """Saca (fecha, valor) del JSON del BCRA.

    La v3 devuelve los valores sueltos en 'results'; la v4 los anida en
    'detalle'. Recorremos la estructura sin asumir cuál vino.
    """
    filas = []

    def _mirar(x):
        if isinstance(x, list):
            for y in x:
                _mirar(y)
            return
        if not isinstance(x, dict):
            return
        f = x.get("fecha")
        v = x.get("valor")
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
    # sin duplicados, por si la estructura los repite
    return sorted({f: v for f, v in filas}.items())


def _intentar(url, params, verify):
    import red
    return red.get(url, "bcra_cer", params=params, headers=CABECERAS,
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
    global ultimo_error, ultima_respuesta, _ultimo_fallo
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
                ultima_respuesta = str(r.text)[:400]
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

    filas = _extraer(d)
    if filas:
        _guardar(filas)
        log.info("CER: +%d días entre %s y %s (último %s = %s)",
                 len(filas), desde, hasta, filas[-1][0], filas[-1][1])
    else:
        ultimo_error = ("el BCRA respondió pero no encontré valores. "
                        "Claves recibidas: %s" % list(d)[:8])
        log.warning("CER: %s", ultimo_error)
        _ultimo_fallo = _dt.now()
    return len(filas)


_fallidas = set()


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

    if f in _fallidas:
        return None
    d = date.fromisoformat(f)
    descargar((d - timedelta(days=30)).isoformat(), f, verificar_ssl)
    r = db.conn().execute(
        "SELECT fecha, valor FROM cer WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
        (f,)).fetchone()
    if not r:
        global ultimo_error
        _fallidas.add(f)
        ultimo_error = ("no hay CER guardado para %s ni antes. "
                        "Hay que descargar la serie desde esa fecha." % f)
        log.warning("CER: %s", ultimo_error)
        return None
    # Un CER de hace meses daría una TIR disparatada sin que se note.
    # Mejor devolver nada que un número falso.
    hueco = (d - date.fromisoformat(r["fecha"])).days
    if hueco > 15:
        ultimo_error = ("para %s el CER más cercano es del %s (%d días antes). "
                        "Falta descargar ese tramo de la serie."
                        % (f, r["fecha"], hueco))
        log.warning("CER: %s", ultimo_error)
        return None
    return r["valor"]


# Feriados nacionales que caen en dia de semana. Sin esto, la cuenta de
# diez dias habiles se corre y el CER base sale de otra fecha.
FERIADOS = {
    "2022-01-01", "2022-02-28", "2022-03-01", "2022-03-24", "2022-04-14",
    "2022-04-15", "2022-04-24", "2022-05-02", "2022-05-18", "2022-05-25",
    "2022-06-17", "2022-06-20", "2022-07-08", "2022-07-09", "2022-08-15",
    "2022-10-07", "2022-10-10", "2022-11-20", "2022-11-21", "2022-12-08",
    "2022-12-09",
    "2023-01-01", "2023-02-20", "2023-02-21", "2023-03-24", "2023-04-06",
    "2023-04-07", "2023-05-01", "2023-05-25", "2023-05-26", "2023-06-19",
    "2023-06-20", "2023-07-09", "2023-08-21", "2023-10-13", "2023-10-16",
    "2023-11-20", "2023-12-08", "2023-12-25",
    "2024-01-01", "2024-02-12", "2024-02-13", "2024-03-24", "2024-03-28",
    "2024-03-29", "2024-04-01", "2024-04-02", "2024-05-01", "2024-05-25",
    "2024-06-17", "2024-06-20", "2024-06-21", "2024-07-09", "2024-08-19",
    "2024-10-11", "2024-10-12", "2024-11-18", "2024-12-25",
    "2025-01-01", "2025-03-03", "2025-03-04", "2025-03-24", "2025-04-17",
    "2025-04-18", "2025-05-01", "2025-05-02", "2025-06-16", "2025-06-20",
    "2025-07-09", "2025-08-15", "2025-08-18", "2025-10-10", "2025-10-13",
    "2025-11-21", "2025-11-24", "2025-12-08", "2025-12-25",
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-03-24", "2026-04-02",
    "2026-04-03", "2026-05-01", "2026-05-25", "2026-06-15", "2026-06-19",
    "2026-07-09", "2026-08-17", "2026-10-12", "2026-11-23", "2026-12-08",
    "2026-12-25",
}


def _habil(d):
    return d.weekday() < 5 and d.isoformat() not in FERIADOS


def es_habil(d):
    """Publico: lo usa el monitor para saber si hay rueda."""
    return _habil(d)


def _restar_habiles(f, n):
    d = f
    while n > 0:
        d -= timedelta(days=1)
        if _habil(d):
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


def asegurar_rango(desde, hasta, verificar_ssl=True):
    """Descarga la serie por tramos anuales.

    El BCRA acota cuántos días devuelve por pedido, así que pedirle diez
    años de una no funciona: hay que ir por partes.
    """
    if isinstance(desde, str):
        desde = date.fromisoformat(desde[:10])
    if isinstance(hasta, str):
        hasta = date.fromisoformat(hasta[:10])

    total = 0
    cur = desde
    while cur <= hasta:
        fin = min(date(cur.year, 12, 31), hasta)
        # ¿ya lo tenemos completo?
        r = db.conn().execute(
            "SELECT COUNT(*) n FROM cer WHERE fecha BETWEEN ? AND ?",
            (cur.isoformat(), fin.isoformat())).fetchone()
        habiles = sum(1 for i in range((fin - cur).days + 1)
                      if (cur + timedelta(days=i)).weekday() < 5)
        if r["n"] < habiles * 0.9:
            reintentar_ya()
            total += descargar(cur.isoformat(), fin.isoformat(), verificar_ssl)
        cur = date(cur.year + 1, 1, 1)
    return total


def sincronizar(bonos, verificar_ssl=True):
    """Se asegura de tener el CER de cada emisión y el de hoy."""
    ajustables = {tk: cfg for tk, cfg in (bonos or {}).items()
                  if (cfg.get("ajuste") or "").lower() == "cer"}
    if not ajustables:
        return []

    # una sola pasada que cubre desde la emisión más vieja hasta hoy
    emisiones = []
    for cfg in ajustables.values():
        try:
            emisiones.append(date.fromisoformat(str(cfg.get("emision"))[:10]))
        except (TypeError, ValueError):
            pass
    if emisiones:
        desde = min(emisiones) - timedelta(days=40)
        # la serie arranca el 2/2/2002 con base 1
        if desde < date(2002, 2, 2):
            desde = date(2002, 2, 2)
        n = asegurar_rango(desde, date.today(), verificar_ssl)
        if n:
            log.info("CER: serie completa desde %s (+%d días)", desde, n)

    faltan = [tk for tk, cfg in ajustables.items()
              if not base_de(cfg.get("emision"), verificar_ssl)]
    if not vigente(verificar_ssl=verificar_ssl):
        faltan.append("actual")
    return faltan
