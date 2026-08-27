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


def _tasa_vigente(tramos, f):
    tasa = 0.0
    for t in tramos:
        if f >= _fecha(t["desde"]):
            tasa = float(t["tasa"])
    return tasa


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

    cur = _fecha(it["primer_pago"])
    out = []
    while cur <= hasta:
        out.append(cur)
        cur = _sumar_meses(cur, paso)
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


def flujo(esp, desde=None):
    """Flujo futuro por cada 100 de valor nominal original.

    Devuelve lista de dicts con fecha, renta, amortizacion y residual.
    """
    desde = desde or date.today()
    venc = _fecha(esp["vencimiento"])
    amorts = dict(fechas_amortizacion(esp))
    pagos_int = fechas_interes(esp, venc)
    base = esp.get("base", "30/360")
    tramos = esp["interes"]["tramos"]

    # si una amortización cae a uno o dos días de un cupón, es el mismo
    # servicio: los prospectos redondean distinto la fecha de cada pata
    amorts = _pegar_a_cupon(amorts, pagos_int, venc=venc)
    todas = sorted(set(list(amorts) + pagos_int))
    residual = 100.0
    anterior = _fecha(esp["emision"])
    filas = []

    for f in todas:
        tasa = _tasa_vigente(tramos, anterior)
        if base.startswith("30"):
            dias = _dias_30_360(anterior, f)
            frac = dias / 360.0
        else:
            frac = (f - anterior).days / 360.0
        renta = residual * tasa / 100.0 * frac if f in pagos_int else 0.0
        amort = amorts.get(f, 0.0)

        if f > desde:
            filas.append({
                "fecha": f, "renta": round(renta, 6),
                "amortizacion": round(amort, 6),
                "total": round(renta + amort, 6),
                "residual_previo": round(residual, 6),
            })
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


def interes_corrido(esp, al=None):
    """Cupon devengado desde el ultimo pago."""
    al = al or date.today()
    venc = _fecha(esp["vencimiento"])
    pagos = fechas_interes(esp, venc)
    previos = [f for f in pagos if f <= al] or [_fecha(esp["emision"])]
    ultimo = max(previos)
    tasa = _tasa_vigente(esp["interes"]["tramos"], ultimo)
    res = residual(esp, ultimo)
    if esp.get("base", "30/360").startswith("30"):
        frac = _dias_30_360(ultimo, al) / 360.0
    else:
        frac = (al - ultimo).days / 360.0
    return round(res * tasa / 100.0 * frac, 6)


# -- metricas ---------------------------------------------------------

def _vpn(tasa, filas, liq):
    t = 0.0
    for f in filas:
        años = (f["fecha"] - liq).days / 365.0
        t += f["total"] / (1 + tasa) ** años
    return t


def tir(precio, esp, liq=None, filas=None):
    """TIR efectiva anual. precio por cada 100 de VN, en la moneda del flujo."""
    liq = liq or date.today()
    filas = filas if filas is not None else flujo(esp, liq)
    if not filas or precio <= 0:
        return None

    lo, hi = -0.95, 5.0
    if _vpn(lo, filas, liq) < precio:
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
    filas = flujo(esp, liq)
    r = tir(precio, esp, liq, filas)
    mac, mod = duration(precio, esp, liq, r, filas)
    prox = filas[0] if filas else None
    return {
        "tir": r * 100 if r is not None else None,
        "duration": mac,
        "md": mod,
        "residual": residual(esp, liq),
        "interes_corrido": interes_corrido(esp, liq),
        "vencimiento": _fecha(esp["vencimiento"]).isoformat(),
        "años_al_vto": (_fecha(esp["vencimiento"]) - liq).days / 365.0,
        "proximo_pago": {
            "fecha": prox["fecha"].isoformat(),
            "renta": prox["renta"],
            "amortizacion": prox["amortizacion"],
            "total": prox["total"],
        } if prox else None,
        "cupon_vigente": _tasa_vigente(esp["interes"]["tramos"], liq),
    }
