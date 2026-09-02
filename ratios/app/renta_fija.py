"""Flujos de fondos, TIR y duration de bonos.

Los cronogramas salen de bonos.yaml, transcritos del archivo oficial del
Ministerio de Economía. Todo se calcula sobre valor nominal 100.
"""

import logging
from datetime import date, timedelta

log = logging.getLogger("renta_fija")

VN = 100.0


# -- utilidades de calendario ----------------------------------------

def _fecha(v):
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _sumar_meses(f, n):
    m = f.month - 1 + n
    a = f.year + m // 12
    m = m % 12 + 1
    d = min(f.day, [31, 29 if a % 4 == 0 and (a % 100 or a % 400 == 0) else 28,
                    31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(a, m, d)


def _ultimo_habil(a, m):
    d = _sumar_meses(date(a, m, 1), 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _dias_30_360(d1, d2):
    dd1 = min(d1.day, 30)
    dd2 = min(d2.day, 30) if dd1 == 30 else d2.day
    return (d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (dd2 - dd1)


def _frac(base, d1, d2):
    """Fraccion de año devengada entre dos fechas, segun la convencion."""
    b = (base or "30/360").replace(" ", "").lower()
    if b.startswith("30"):
        return _dias_30_360(d1, d2) / 360.0
    if b.endswith("365"):
        return (d2 - d1).days / 365.0
    return (d2 - d1).days / 360.0


def _tasa_vigente(tramos, f):
    tasa = 0.0
    for t in tramos or []:
        if f >= _fecha(t["desde"]):
            tasa = float(t["tasa"])
    return tasa


def tasa_variable(esp, al=None):
    """Tasa a proyectar en un bono de cupon variable, en % nominal anual.

    La convencion acordada es tomar un solo valor -el de la fecha de
    valuacion, ya rezagado- y proyectarlo constante hasta el
    vencimiento. Asi un punto historico no cambia cuando el BCRA
    publica tasas nuevas.

    Devuelve None si no hay dato: el llamador decide si cae a los
    tramos fijos o si directamente no puede valuar el bono.
    """
    var = (esp.get("interes") or {}).get("variable")
    if not var:
        return None
    fuente = (var.get("fuente") or "").strip().lower()
    spread = float(var.get("spread") or 0)
    if fuente == "badlar":
        import badlar as BA
        v = BA.vigente(al)
        return None if v is None else v + spread
    log.warning("fuente de tasa variable desconocida: %r", fuente)
    return None


def _tasa_para(esp, f, tasa_var=None):
    """Tasa que rige un devengamiento, fija o variable."""
    it = esp.get("interes") or {}
    if it.get("variable"):
        if tasa_var is not None:
            return float(tasa_var)
        v = tasa_variable(esp)
        if v is not None:
            return v
    return _tasa_vigente(it.get("tramos"), f)


# -- construccion del flujo ------------------------------------------

def fechas_amortizacion(esp):
    am = esp.get("amortizacion") or {}
    if am.get("tipo") == "bullet":
        return [(_fecha(esp["vencimiento"]), 100.0)]

    cuotas = am.get("cuotas")
    if not cuotas:
        n = int(am.get("cuotas_iguales") or 1)
        cuotas = [100.0 / n] * n
    ini = _fecha(am["fechas_desde"])
    paso = int(am.get("frecuencia_meses") or 6)
    return [(_sumar_meses(ini, paso * i), c) for i, c in enumerate(cuotas)]


def fechas_interes(esp, hasta):
    it = esp["interes"]
    paso = int(it.get("frecuencia_meses") or 6)
    if it.get("dia_pago") == "ultimo_habil":
        f = _fecha(esp["emision"])
        out = []
        cur = _ultimo_habil(f.year, f.month)
        if cur <= f:
            cur = _sumar_meses(cur, 1)
            cur = _ultimo_habil(cur.year, cur.month)
        while cur <= hasta:
            out.append(cur)
            n = _sumar_meses(cur, paso)
            cur = _ultimo_habil(n.year, n.month)
        if out and out[-1] != hasta:
            out.append(hasta)
        return out

    # Se cuenta desde el ancla, no encadenando: sumar 6 meses a un 31 de
    # diciembre da 30 de junio, y si de ahi se sigue encadenando el dia
    # 31 se pierde para siempre. Amortizacion ya lo hacia asi.
    ancla = _fecha(it["primer_pago"])
    out = []
    i = 0
    while True:
        cur = _sumar_meses(ancla, paso * i)
        if cur > hasta:
            break
        out.append(cur)
        i += 1
    # el vencimiento siempre paga cupón, aunque el día no caiga justo
    # en la serie (pasa cuando el prospecto corre la última fecha)
    if out and out[-1] != hasta:
        # a pocos dias: es el mismo servicio, solo corrido
        if abs((hasta - out[-1]).days) <= 15:
            out[-1] = hasta
        elif hasta > out[-1]:
            out.append(hasta)
    return out


def _pegar_a_cupon(amorts, pagos_int, tolerancia=3, venc=None):
    """Alinea la fecha de amortización con la del cupón más cercano.

    Una cuota que caería después del vencimiento se pega a él: los
    prospectos redondean distinto la última fecha de cada pata.
    """
    if not pagos_int:
        return amorts
    out = {}
    for f, c in amorts.items():
        if venc and f > venc:
            out[venc] = out.get(venc, 0.0) + c
            continue
        cerca = min(pagos_int, key=lambda p: abs((p - f).days))
        if abs((cerca - f).days) <= tolerancia:
            out[cerca] = out.get(cerca, 0.0) + c
        else:
            out[f] = out.get(f, 0.0) + c
    return out


def flujo(esp, desde=None, tasa_var=None):
    """Flujo futuro por cada 100 de valor nominal original.

    Devuelve lista de dicts con fecha, renta, amortizacion y residual.
    En bonos de cupon variable, `tasa_var` fija la tasa a proyectar; si
    no viene, se resuelve contra la fuente configurada.
    """
    desde = desde or date.today()
    venc = _fecha(esp["vencimiento"])
    amorts = dict(fechas_amortizacion(esp))
    pagos_int = fechas_interes(esp, venc)
    base = esp.get("base", "30/360")
    if (esp.get("interes") or {}).get("variable") and tasa_var is None:
        tasa_var = tasa_variable(esp, desde)

    # si una amortización cae a uno o dos días de un cupón, es el mismo
    # servicio: los prospectos redondean distinto la fecha de cada pata
    amorts = _pegar_a_cupon(amorts, pagos_int, venc=venc)
    todas = sorted(set(list(amorts) + pagos_int))
    residual = 100.0
    anterior = _fecha(esp["emision"])
    filas = []

    pagos_set = set(pagos_int)
    # El interes se acumula por subperiodos y se paga entero en la fecha
    # de cupon. Antes cada fecha de la lista cortaba el devengamiento, y
    # una amortizacion que cae lejos de todo cupon dejaba el cupon
    # siguiente devengado desde esa fecha y no desde el pago anterior:
    # salia cobrado de menos. Cuando amortizacion y cupon coinciden -que
    # es lo que pasa en los 42 bonos cargados hoy- el resultado es
    # identico al de antes.
    devengado = 0.0
    for f in todas:
        tasa = _tasa_para(esp, anterior, tasa_var)
        devengado += residual * tasa / 100.0 * _frac(base, anterior, f)
        es_cupon = f in pagos_set
        renta = devengado if es_cupon else 0.0
        amort = amorts.get(f, 0.0)

        if f > desde:
            filas.append({
                "fecha": f, "renta": round(renta, 6),
                "amortizacion": round(amort, 6),
                "total": round(renta + amort, 6),
                "residual_previo": round(residual, 6),
            })
        if es_cupon:
            devengado = 0.0
        residual -= amort
        anterior = f

    return filas


def residual(esp, al=None):
    al = al or date.today()
    r = 100.0
    for f, c in fechas_amortizacion(esp):
        if f <= al:
            r -= c
    return round(r, 6)


def interes_corrido(esp, al=None, tasa_var=None):
    """Cupon devengado desde el ultimo pago."""
    al = al or date.today()
    venc = _fecha(esp["vencimiento"])
    pagos = fechas_interes(esp, venc)
    previos = [f for f in pagos if f <= al] or [_fecha(esp["emision"])]
    ultimo = max(previos)
    if (esp.get("interes") or {}).get("variable") and tasa_var is None:
        tasa_var = tasa_variable(esp, al)
    tasa = _tasa_para(esp, ultimo, tasa_var)
    res = residual(esp, ultimo)
    frac = _frac(esp.get("base", "30/360"), ultimo, al)
    return round(res * tasa / 100.0 * frac, 6)


# -- metricas ---------------------------------------------------------

def _vpn(tasa, filas, liq):
    t = 0.0
    for f in filas:
        años = (f["fecha"] - liq).days / 365.0
        t += f["total"] / (1 + tasa) ** años
    return t


TIR_MAX = 5.0        # 500% anual: arriba de esto el precio esta roto


def tir(precio, esp, liq=None, filas=None):
    """TIR efectiva anual. precio por cada 100 de VN, en la moneda del flujo.

    Devuelve None si el precio queda fuera del rango que la biseccion
    puede resolver. Antes, con un precio muy bajo, la busqueda se
    clavaba contra el techo y devolvia 5.0 exacto, que la tabla mostraba
    como "TIR 500%" igual que si fuera una cuenta hecha.
    """
    liq = liq or date.today()
    filas = filas if filas is not None else flujo(esp, liq)
    if not filas or precio <= 0:
        return None

    lo, hi = -0.95, TIR_MAX
    if _vpn(lo, filas, liq) < precio:
        return None
    # si ni al techo el valor presente baja hasta el precio, la TIR esta
    # por encima del rango: no hay numero que devolver
    if _vpn(hi, filas, liq) > precio:
        return None
    for _ in range(200):
        m = (lo + hi) / 2
        if _vpn(m, filas, liq) > precio:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def duration(precio, esp, liq=None, r=None, filas=None):
    """Devuelve (Macaulay, modificada) en años."""
    liq = liq or date.today()
    filas = filas if filas is not None else flujo(esp, liq)
    r = r if r is not None else tir(precio, esp, liq, filas)
    if r is None or not filas:
        return None, None

    num = den = 0.0
    for f in filas:
        años = (f["fecha"] - liq).days / 365.0
        vp = f["total"] / (1 + r) ** años
        num += vp * años
        den += vp
    if not den:
        return None, None
    mac = num / den
    return mac, mac / (1 + r)



def metricas(esp, precio, liq=None):
    """Todo junto, para una fila de la tabla."""
    liq = liq or date.today()
    # se resuelve una sola vez: si cada llamada la buscara por su
    # cuenta, el flujo y el corrido podrian quedar con tasas distintas
    tv = tasa_variable(esp, liq)
    filas = flujo(esp, liq, tasa_var=tv)
    r = tir(precio, esp, liq, filas)
    mac, mod = duration(precio, esp, liq, r, filas)
    prox = filas[0] if filas else None
    return {
        "tir": r * 100 if r is not None else None,
        "duration": mac,
        "md": mod,
        "residual": residual(esp, liq),
        "interes_corrido": interes_corrido(esp, liq, tasa_var=tv),
        "vencimiento": _fecha(esp["vencimiento"]).isoformat(),
        "años_al_vto": (_fecha(esp["vencimiento"]) - liq).days / 365.0,
        "proximo_pago": {
            "fecha": prox["fecha"].isoformat(),
            "renta": prox["renta"],
            "amortizacion": prox["amortizacion"],
            "total": prox["total"],
        } if prox else None,
        "cupon_vigente": _tasa_para(esp, liq, tv),
        "tasa_variable": tv,
    }
