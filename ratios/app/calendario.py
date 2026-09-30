"""Calendario bursatil: cuando hay rueda y cuando se liquida.

Son dos calendarios distintos. BYMA tiene dias con negociacion y sin
liquidacion: los puentes turisticos, el Dia del Bancario (6/11) y el
24/12. Ese dia hay precios -la base tiene cierres propios del 21/11/2025,
del 23/03/2026 y del 10/07/2026- pero nada liquida, no corre el
contado inmediato ni las cauciones, y los bancos estan cerrados.

- `hay_rueda(d)`: el monitor, el cierre diario del historico, la
  antiguedad de la ultima operacion y el rearme de los canjes.
- `habil_liquidacion(d)`: la T+1, el rezago del CER y de la TAMAR, los
  duales, el A3500. Es tambien el habil bancario.

Fuentes, en orden:

1. **BYMA**, la pagina del calendario bursatil. Trae el año en curso con
   una referencia por dia: (1) y (2) feriado, (3) sin liquidacion con
   negociacion, (4) sin negociacion ni liquidacion. Las filas "(USA)" se
   descartan: aca ese dia hay rueda y liquidacion normales. Una
   referencia que la pagina no define -el (5) del 10/07/2026- se toma
   como (3) y se anota en el registro.
2. **ArgentinaDatos** (`/v1/feriados/{año}`) para un año que BYMA todavia
   no publico: inamovibles y trasladables como feriado, puentes como (3),
   y se agregan el 6/11 y el 24/12 como (3) y el 31/12 como (4).
3. **La lista fija** de este modulo, ultimo respaldo y unica fuente para
   los años anteriores al primero que se bajo.

Se baja una vez por mes (`DIAS_REFRESCO`), o a mano desde Explorar. Lo
bajado se guarda en la base: sin red, sigue valiendo lo ultimo.
"""

import html
import json
import logging
import re
import threading
from datetime import date, datetime, timedelta

log = logging.getLogger("ratios.calendario")

URL_BYMA = "https://www.byma.com.ar/en/market/calendario-bursatil"
URL_AD = "https://api.argentinadatos.com/v1/feriados/%d"
DIAS_REFRESCO = 30

FERIADO = "feriado"             # ni rueda ni liquidacion
SIN_LIQ = "sin_liquidacion"     # hay rueda, no se liquida
SIN_RUEDA = "sin_rueda"         # ni rueda ni liquidacion, sin ser feriado

# Feriados nacionales que caen en dia de semana, 2022-2026. Es la lista
# que vivia en cer.py, con dos correcciones de 2026 segun el calendario
# de BYMA: el 19/06 no es feriado aca (es el Juneteenth de EE.UU.) y
# faltaban los puentes.
_FERIADOS = {
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
    "2026-04-03", "2026-05-01", "2026-05-25", "2026-06-15", "2026-07-09",
    "2026-08-17", "2026-10-12", "2026-11-23", "2026-12-08", "2026-12-25",
}

# Dias de la lista fija que tuvieron negociacion sin liquidacion. Salen
# de las circulares de BYMA y de los cierres guardados en la base; para
# los puentes anteriores no hay dato y quedan como feriado.
_CON_RUEDA = {
    "2025-11-21",                                   # Comunicado 18859
    "2026-03-23", "2026-07-10", "2026-12-07",       # puentes 2026
}


def _fijos(anio):
    """Los dias que se repiten todos los años, para las fuentes que no
    los traen: el 6/11 y el 24/12 negocian sin liquidar; el 31/12 no
    negocia ni liquida (BYMA, Comunicado 18897)."""
    d = {"%d-11-06" % anio: (SIN_LIQ, "Día del Bancario")}
    # 24 y 31/12: desde 2025, que es de cuando hay circular. Para los
    # años anteriores no hay dato.
    if anio >= 2025:
        d["%d-12-24" % anio] = (SIN_LIQ, "Nochebuena")
        d["%d-12-31" % anio] = (SIN_RUEDA, "Sin negociación ni liquidación")
    return d


def _lista_fija(anio):
    dias = {}
    for f in _FERIADOS:
        if f.startswith(str(anio)):
            dias[f] = {"tipo": SIN_LIQ if f in _CON_RUEDA else FERIADO,
                       "nombre": ""}
    for f, (tipo, nombre) in _fijos(anio).items():
        dias.setdefault(f, {"tipo": tipo, "nombre": nombre})
    return dias


# -- estado en memoria -------------------------------------------------

_lock = threading.Lock()
_cache = None          # {"2026": {"fuente":..., "dias": {iso: {...}}}}


def _cargar():
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is None:
            guardado = {}
            try:
                import db
                guardado = json.loads(db.get_estado("calendario") or "{}")
            except Exception as e:
                log.debug("calendario guardado: %s", e)
            _cache = (guardado.get("anios") or {}) if isinstance(
                guardado, dict) else {}
    return _cache


def _dias_de(anio):
    a = _cargar().get(str(anio))
    if a and a.get("dias"):
        return a["dias"]
    return _lista_fija(anio)


def tipo(d):
    """None si es un dia comun; si no, FERIADO, SIN_LIQ o SIN_RUEDA."""
    if isinstance(d, datetime):
        d = d.date()
    x = _dias_de(d.year).get(d.isoformat())
    return x["tipo"] if x else None


def hay_rueda(d):
    """Si ese dia BYMA negocia."""
    if d.weekday() >= 5:
        return False
    return tipo(d) not in (FERIADO, SIN_RUEDA)


def habil_liquidacion(d):
    """Si ese dia se liquida. Tambien es el habil bancario."""
    if d.weekday() >= 5:
        return False
    return tipo(d) is None


# -- fuentes -----------------------------------------------------------

_MESES = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}

_FILA = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2})(?:,\s*(\d{4}))?\s+"
    r"[A-Za-zéá]+\s+"                 # el dia de la semana, con errores
    r"(.{3,120}?)\s*\((\d+|USA)\)")


def parsear_byma(texto):
    """(año, {iso: {"tipo", "nombre", "ref"}}, referencias desconocidas).

    Se trabaja sobre el texto sin etiquetas: el HTML es de Webflow y la
    estructura cambia, el texto de las filas no.
    """
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", texto,
               flags=re.S | re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"\s+", " ", t)
    # La tabla arranca despues del encabezado HOLIDAY (o FERIADO).
    i = max(t.find("HOLIDAY"), t.find("FERIADO"))
    if i >= 0:
        t = t[i:]
    anio = None
    m = re.search(r"(\d{4})_TRADING_CALENDAR", texto) or re.search(
        r"December\s+31,\s*(\d{4})", t)
    if m:
        anio = int(m.group(1))
    dias, raras = {}, set()
    for mes, dia, a, nombre, ref in _FILA.findall(t):
        if ref == "USA":
            continue
        a = int(a) if a else anio
        if not a:
            continue
        try:
            f = date(a, _MESES[mes.lower()], int(dia))
        except ValueError:
            continue
        if ref in ("1", "2"):
            tp = FERIADO
        elif ref == "3":
            tp = SIN_LIQ
        elif ref == "4":
            tp = SIN_RUEDA
        else:
            tp = SIN_LIQ
            raras.add(ref)
        dias[f.isoformat()] = {"tipo": tp, "nombre": nombre.strip(),
                               "ref": ref}
    return anio, dias, sorted(raras)


def _bajar_byma():
    import red
    r = red.get(URL_BYMA, "byma", origen="calendario", timeout=30,
                headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    anio, dias, raras = parsear_byma(r.text)
    if raras:
        log.warning("calendario BYMA: referencias sin definir %s, "
                    "tomadas como sin liquidacion", ", ".join(raras))
    # Menos de ocho feriados nacionales es una pagina que no se entendio.
    if not anio or sum(1 for x in dias.values()
                       if x["tipo"] == FERIADO) < 8:
        raise ValueError("no se pudo leer la tabla (%d dias)" % len(dias))
    return anio, dias


def _bajar_ad(anio):
    import red
    r = red.get(URL_AD % anio, "argentinadatos", origen="calendario",
                timeout=30)
    r.raise_for_status()
    dias = {}
    for x in r.json() or []:
        f = str(x.get("fecha") or "")[:10]
        if not f.startswith(str(anio)):
            continue
        tp = SIN_LIQ if (x.get("tipo") or "") == "puente" else FERIADO
        dias[f] = {"tipo": tp, "nombre": x.get("nombre") or ""}
    if len(dias) < 8:
        raise ValueError("%d dias" % len(dias))
    for f, (tp, nombre) in _fijos(anio).items():
        dias.setdefault(f, {"tipo": tp, "nombre": nombre})
    return dias


def actualizar(forzar=False, hoy=None):
    """Baja el año en curso y el siguiente. Devuelve un resumen.

    Sin `forzar` no hace nada si la ultima bajada fue hace menos de
    `DIAS_REFRESCO` dias. Un año que BYMA ya publico no se pisa con
    ArgentinaDatos.
    """
    import db
    global _cache
    hoy = hoy or date.today()
    try:
        guardado = json.loads(db.get_estado("calendario") or "{}")
    except (ValueError, TypeError):
        guardado = {}
    if not isinstance(guardado, dict):
        guardado = {}
    ultima = guardado.get("bajado") or ""
    if not forzar and ultima and \
            ultima >= (hoy - timedelta(days=DIAS_REFRESCO)).isoformat():
        return {"hecho": False, "motivo": "bajado el %s" % ultima}

    anios = dict(guardado.get("anios") or {})
    errores = []
    # ArgentinaDatos para los dos años: es la base. La pagina de BYMA no
    # lista todo -la de 2026 no trae el 1/1- y se aplica encima, porque
    # es la que distingue los dias con rueda y sin liquidacion.
    ad = {}
    for a in (hoy.year, hoy.year + 1):
        try:
            ad[a] = _bajar_ad(a)
        except Exception as e:
            errores.append("ArgentinaDatos %d: %s" % (a, str(e)[:150]))
    byma_anio, byma_dias = None, {}
    try:
        byma_anio, byma_dias = _bajar_byma()
    except Exception as e:
        errores.append("BYMA: %s" % str(e)[:150])
    for a in sorted(set(ad) | ({byma_anio} if byma_anio else set())):
        previo = anios.get(str(a)) or {}
        if a == byma_anio:
            base = ad.get(a) or _lista_fija(a)
            anios[str(a)] = {"fuente": "byma", "dias": dict(base, **byma_dias),
                             "bajado": hoy.isoformat()}
        elif previo.get("fuente") == "byma":
            continue        # BYMA ya lo publico: no se pisa
        else:
            anios[str(a)] = {"fuente": "argentinadatos", "dias": ad[a],
                             "bajado": hoy.isoformat()}
    nuevo = {"anios": anios, "errores": errores,
             "intento": hoy.isoformat(),
             # Si no se bajo nada, se reintenta al dia siguiente y no en
             # un mes.
             "bajado": hoy.isoformat() if (ad or byma_anio) else ultima}
    db.set_estado("calendario", json.dumps(nuevo))
    with _lock:
        _cache = anios
    for e in errores:
        log.warning("calendario: %s", e)
    return {"hecho": True, "errores": errores,
            "anios": {k: v.get("fuente") for k, v in anios.items()}}


def listar(anio):
    """Para Explorar: los dias no comunes del año, con su fuente."""
    a = _cargar().get(str(anio))
    fuente = (a or {}).get("fuente") if a and a.get("dias") else "lista fija"
    dias = _dias_de(anio)
    filas = []
    for f in sorted(dias):
        d = date.fromisoformat(f)
        x = dias[f]
        filas.append({"fecha": f, "dia": d.weekday(), "tipo": x["tipo"],
                      "nombre": x.get("nombre") or "",
                      "ref": x.get("ref") or "",
                      "rueda": hay_rueda(d), "liquida": habil_liquidacion(d)})
    try:
        import db
        g = json.loads(db.get_estado("calendario") or "{}")
    except Exception:
        g = {}
    return {"anio": anio, "fuente": fuente, "dias": filas,
            "bajado": (a or {}).get("bajado") or g.get("bajado"),
            "errores": g.get("errores") or []}
