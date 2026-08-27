"""Spreads verticales sobre acciones.

Tres estructuras, todas de riesgo acotado:

- **BULL con calls**: compro la base baja, vendo la alta. Débito.
- **BEAR con puts**: compro la base alta, vendo la baja. Débito.
- **BEAR con calls**: vendo la base baja, compro la alta. Crédito, y el
  broker inmoviliza la diferencia de bases como garantía.

Las tres se leen con la misma escala: **riesgo sobre el ancho de bases**.
En los débitos el riesgo es lo que se paga; en el crédito es el ancho
menos la prima cobrada. Un riesgo del 33% es el ratio 1 a 3 de siempre:
se arriesga 1 para que la posición valga 3 al vencimiento.

Todo se valúa contra puntas: se compra contra el ask y se vende contra el
bid. No hay precios teóricos.
"""

import logging
import re
from datetime import date, datetime, timedelta

log = logging.getLogger("opciones")

LOTE = 100.0        # una opción da derecho sobre 100 acciones

# Sufijo de mes en el símbolo de IOL: GFGC6800AG vence en agosto.
MESES = {"EN": 1, "FE": 2, "MZ": 3, "AB": 4, "MY": 5, "JU": 6,
         "JL": 7, "AG": 8, "SE": 9, "OC": 10, "NO": 11, "DI": 12}

# El símbolo termina en la letra del mes más, a veces, un dígito de año.
_SUFIJO = re.compile(r"([A-Z]{2})(\d?)$")


def _f(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if x > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def tercer_viernes(anio, mes):
    """Los vencimientos del mercado argentino caen el tercer viernes."""
    d = date(anio, mes, 1)
    viernes = d + timedelta(days=(4 - d.weekday()) % 7)
    return viernes + timedelta(days=14)


def _vencimiento(simbolo, crudo=None):
    """Fecha de vencimiento. Se prefiere lo que informe IOL."""
    for clave in ("fechaVencimiento", "vencimiento", "fechaExpiracion"):
        v = (crudo or {}).get(clave)
        if not v:
            continue
        txt = str(v)[:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(txt, fmt).date()
            except ValueError:
                pass

    m = _SUFIJO.search((simbolo or "").upper())
    if not m or m.group(1) not in MESES:
        return None
    mes = MESES[m.group(1)]
    hoy = date.today()
    anio = hoy.year
    if m.group(2):
        anio = 2020 + int(m.group(2))
        if anio < hoy.year - 1:
            anio += 10
    elif mes < hoy.month:
        anio += 1
    return tercer_viernes(anio, mes)


# Base y mes dentro del símbolo: GFGC6200AG es un call de Galicia, base
# 6200, agosto. La base puede traer decimales: ALUC700.OC vale 700,0.
_SIMBOLO = re.compile(r"^([A-Z]{3})([CV])(\d+(?:\.\d*)?)([A-Z]{2})(\d?)$")


def _base(crudo, simbolo):
    """El strike sale de la descripción; si no viene, del símbolo."""
    desc = str((crudo or {}).get("descripcion") or "")
    partes = desc.split()
    if len(partes) > 2:
        b = _f(partes[2])
        if b:
            return b
    for p in partes:
        b = _f(p)
        if b:
            return b
    m = _SIMBOLO.match((simbolo or "").upper())
    if m:
        return _f(m.group(3))
    return 0.0


def _tipo(crudo, simbolo):
    desc = str((crudo or {}).get("descripcion") or "").upper()
    if "CALL" in desc:
        return "CALL"
    if "PUT" in desc:
        return "PUT"
    # cuarta letra del símbolo: C de call, V de venta (put)
    m = _SIMBOLO.match((simbolo or "").upper())
    if m:
        return "CALL" if m.group(2) == "C" else "PUT"
    return ""


def parsear_serie(crudo, de_quien):
    """Una serie de la cadena, o None si no sirve.

    `de_quien` mapea símbolo de opción a subyacente. No se puede deducir
    del prefijo: las opciones de GGAL empiezan con GFG.
    """
    sim = str((crudo or {}).get("simbolo") or "").upper()
    if not sim:
        return None

    sub = de_quien.get(sim)
    if not sub:
        return None

    tipo = _tipo(crudo, sim)
    base = _base(crudo, sim)
    venc = _vencimiento(sim, crudo)
    if not tipo or not base or not venc:
        return None

    puntas = crudo.get("puntas")
    if isinstance(puntas, list) and puntas:
        p0 = puntas[0] or {}
    elif isinstance(puntas, dict):
        p0 = puntas
    else:
        p0 = {}

    return {
        "simbolo": sim,
        "subyacente": sub,
        "tipo": tipo,
        "base": base,
        "vencimiento": venc.isoformat(),
        "dias": (venc - date.today()).days,
        "compra": _f(p0.get("precioCompra")) or _f(crudo.get("precioCompra")),
        "venta": _f(p0.get("precioVenta")) or _f(crudo.get("precioVenta")),
        "q_compra": _f(p0.get("cantidadCompra")) or _f(crudo.get("cantidadCompra")),
        "q_venta": _f(p0.get("cantidadVenta")) or _f(crudo.get("cantidadVenta")),
        "ultimo": _f(crudo.get("ultimoPrecio")),
    }


def mapa_subyacentes(iol, subyacentes, mercado="bCBA", horas_cache=12):
    """Simbolo de opcion -> subyacente.

    Se cachea por medio dia: la lista de series de un subyacente cambia
    cuando se listan vencimientos nuevos, no cada diez minutos. Sin
    cache, este era un request por subyacente en cada ciclo, o sea la
    mitad del consumo del modulo para un dato que no se mueve.
    """
    import db
    de_quien = {}
    for sub in subyacentes:
        clave = "opciones_de:%s:%s" % (mercado, sub)
        simbolos = db.cache_get(clave, horas_cache) if horas_cache else None
        if simbolos is None:
            try:
                d = iol.opciones_de(sub, mercado)
            except Exception as e:
                log.warning("opciones de %s: %s", sub, e)
                continue
            filas = d if isinstance(d, list) else (d or {}).get("titulos") or []
            simbolos = [str((t or {}).get("simbolo") or "").upper()
                        for t in filas]
            simbolos = [x for x in simbolos if x]
            if simbolos:
                db.cache_set(clave, simbolos)
        for sim in simbolos:
            de_quien[sim] = sub
    return de_quien


def cadena(iol, subyacentes, pais="argentina", mercado="bCBA",
           horas_cache=12, crudos=None):
    """La cadena con puntas. Devuelve (series, diagnostico).

    Si el ciclo ya bajo el instrumento de opciones, se le pasan los
    titulos en `crudos` y no se pide nada: pedirlo aparte era bajar dos
    veces lo mismo en el mismo ciclo.
    """
    de_quien = mapa_subyacentes(iol, subyacentes, mercado, horas_cache)
    if crudos is None:
        d = iol.panel_orleans("opciones", pais)
        crudos = (d or {}).get("titulos") or []

    series = []
    for t in crudos:
        s = parsear_serie(t, de_quien)
        if s:
            series.append(s)

    con_puntas = len([s for s in series if s["compra"] and s["venta"]])
    diag = {"en_panel": len(crudos), "mapeadas": len(de_quien),
            "parseadas": len(series), "con_puntas": con_puntas,
            "vencimientos": sorted({s["vencimiento"] for s in series}),
            "campos": sorted((crudos[0] or {}).keys()) if crudos else [],
            "muestra": crudos[0] if crudos else None}
    return series, diag


# -- costos ----------------------------------------------------------

def _costos(comisiones, derechos=None, iva_pct=0):
    """Costo porcentual de una pata, en tanto por uno, con IVA.

    Las opciones sobre acciones privadas no estan exentas como los
    titulos publicos: el IVA va sobre el arancel y sobre el derecho de
    mercado, que para estas es 0,20% de la prima.
    """
    import costos
    return costos.pct(comisiones, "opciones", derechos, iva_pct)


# -- armado ----------------------------------------------------------

def _combinar(series, spot, estructura, cfg, comisiones,
              derechos=None, iva_pct=0):
    """Todas las combinaciones de una estructura para un vencimiento."""
    saltos = int(cfg.get("saltos") or 3)
    limite = float(cfg.get("limite_base_pct") or 5) / 100.0
    tope = float(cfg.get("riesgo_max_tabla_pct") or 45) / 100.0
    costo_pata = _costos(comisiones, derechos, iva_pct)

    # una sola serie por base: si IOL repite, gana la que tenga las dos puntas
    por_base = {}
    for s in series:
        v = por_base.get(s["base"])
        if not v or (s["compra"] and s["venta"] and not (v["compra"] and v["venta"])):
            por_base[s["base"]] = s
    bases = sorted(por_base)

    out = []
    for i, b_baja in enumerate(bases):
        for j in range(1, saltos + 1):
            if i + j >= len(bases):
                break
            b_alta = bases[i + j]
            ancho = b_alta - b_baja
            if ancho <= 0:
                continue

            baja = por_base[b_baja]
            alta = por_base[b_alta]

            if estructura == "BULL_CALL":
                compro, vendo = baja, alta
            else:                       # BEAR_PUT y BEAR_CALL compran la alta
                compro, vendo = alta, baja

            # la base comprada manda: hasta 5% arriba del spot en el bull,
            # hasta 5% abajo en el bear
            if estructura == "BULL_CALL":
                if not (spot <= compro["base"] <= spot * (1 + limite)):
                    continue
            else:
                if not (spot * (1 - limite) <= compro["base"] <= spot):
                    continue

            pago = compro["venta"]      # compro contra el ask
            cobro = vendo["compra"]     # vendo contra el bid
            if not pago or not cobro:
                continue

            comision = (pago + cobro) * costo_pata
            if estructura == "BEAR_CALL":
                # crédito: cobro la baja y pago la alta
                prima = cobro - pago - comision
                riesgo = ancho - prima
            else:
                riesgo = pago - cobro + comision
                prima = None
            if riesgo <= 0 or riesgo >= ancho:
                continue

            riesgo_pct = riesgo / ancho
            if riesgo_pct > tope:
                continue

            lotes = int(min(compro["q_venta"], vendo["q_compra"]))
            if lotes <= 0:
                continue

            equilibrio = (b_baja + riesgo if estructura == "BULL_CALL"
                          else b_alta - riesgo)
            out.append({
                "id": "%s-%s-%s" % (estructura, compro["simbolo"],
                                    vendo["simbolo"]),
                "estructura": estructura,
                "subyacente": compro["subyacente"],
                "vencimiento": compro["vencimiento"],
                "dias": compro["dias"],
                "spot": round(spot, 2),
                "base_compra": compro["base"],
                "base_venta": vendo["base"],
                "ancho": round(ancho, 4),
                "saltos": j,
                "riesgo": round(riesgo, 4),
                "riesgo_pct": round(riesgo_pct * 100, 2),
                "ganancia": round(ancho - riesgo, 4),
                "ratio": round(ancho / riesgo, 2) if riesgo else None,
                "prima": round(prima, 4) if prima is not None else None,
                "comision": round(comision, 4),
                "equilibrio": round(equilibrio, 2),
                "var_equilibrio_pct": round((equilibrio / spot - 1) * 100, 2),
                "var_max_pct": round(
                    ((b_alta if estructura == "BULL_CALL" else b_baja)
                     / spot - 1) * 100, 2),
                "lotes": lotes,
                "garantia": round(ancho * LOTE, 2)
                            if estructura == "BEAR_CALL" else 0,
                "riesgo_total": round(riesgo * LOTE, 2),
                "ganancia_total": round((ancho - riesgo) * LOTE, 2),
                "patas": [
                    {"accion": "Comprar", "simbolo": compro["simbolo"],
                     "tipo": compro["tipo"], "base": compro["base"],
                     "precio": pago, "punta": compro["q_venta"],
                     "importe": round(pago * LOTE, 2)},
                    {"accion": "Vender", "simbolo": vendo["simbolo"],
                     "tipo": vendo["tipo"], "base": vendo["base"],
                     "precio": cobro, "punta": vendo["q_compra"],
                     "importe": round(cobro * LOTE, 2)},
                ],
            })
    return out


def _tendencia(cierres):
    """Cruce de medias de 9 y 21 ruedas sobre el subyacente."""
    v = [c for c in cierres if c]
    if len(v) < 21:
        return None
    m9 = sum(v[-9:]) / 9.0
    m21 = sum(v[-21:]) / 21.0
    return {"m9": round(m9, 2), "m21": round(m21, 2),
            "sesgo": "alcista" if m9 > m21 else "bajista"}


def a_favor(estructura, tendencia):
    if not tendencia:
        return None
    alcista = tendencia["sesgo"] == "alcista"
    return alcista if estructura == "BULL_CALL" else not alcista


def analizar(series, spots, cfg, comisiones, cierres=None,
             derechos=None, iva_pct=0):
    """Todas las combinaciones que pasan el filtro de tabla.

    `spots` y `cierres` van por subyacente.
    """
    dias_min = int(cfg.get("dias_min") or 15)
    dias_max = int(cfg.get("dias_max") or 80)
    bear_con = (cfg.get("bear_instrumento") or "ambos").lower()

    estructuras = ["BULL_CALL"]
    if bear_con in ("puts", "ambos"):
        estructuras.append("BEAR_PUT")
    if bear_con in ("calls", "ambos"):
        estructuras.append("BEAR_CALL")

    tendencias = {}
    for sub in spots:
        tendencias[sub] = _tendencia(
            [c for _, c in (cierres or {}).get(sub, [])])

    filas = []
    for sub, spot in spots.items():
        if not spot:
            continue
        vivas = [s for s in series
                 if s["subyacente"] == sub and dias_min <= s["dias"] <= dias_max]
        vencs = sorted({s["vencimiento"] for s in vivas})
        for venc in vencs:
            calls = [s for s in vivas
                     if s["vencimiento"] == venc and s["tipo"] == "CALL"]
            puts = [s for s in vivas
                    if s["vencimiento"] == venc and s["tipo"] == "PUT"]
            for est in estructuras:
                fuente = puts if est == "BEAR_PUT" else calls
                if len(fuente) < 2:
                    continue
                for f in _combinar(fuente, spot, est, cfg, comisiones,
                                   derechos, iva_pct):
                    f["tendencia"] = tendencias.get(sub)
                    f["a_favor"] = a_favor(est, tendencias.get(sub))
                    filas.append(f)

    filas.sort(key=lambda f: (f["subyacente"], f["vencimiento"],
                              f["riesgo_pct"]))
    return {
        "filas": filas,
        "spots": {k: round(v, 2) for k, v in spots.items()},
        "tendencias": tendencias,
        "sin_comisiones": _costos(comisiones, derechos, iva_pct) <= 0,
        "umbral_alarma": float(cfg.get("riesgo_max_alarma_pct") or 33),
    }


# -- alertas ---------------------------------------------------------

def cruces(filas, previo, cfg):
    """Combinaciones que acaban de cruzar el umbral hacia adentro.

    Se avisa en el cruce, no mientras se mantiene: una combinacion que se
    queda barata toda la rueda avisa una vez. Vuelve a armarse cuando sale
    y entra de nuevo.
    """
    umbral = float(cfg.get("riesgo_max_alarma_pct") or 33)
    lotes_min = int(cfg.get("lotes_min") or 2)
    ciclos = max(1, int(cfg.get("ciclos_persistencia") or 1))

    estado, avisos = {}, []
    for f in filas:
        adentro = f["riesgo_pct"] <= umbral and f["lotes"] >= lotes_min
        prev = (previo or {}).get(f["id"]) or {}
        seguidos = (prev.get("seguidos") or 0) + 1 if adentro else 0
        estado[f["id"]] = {"adentro": adentro, "seguidos": seguidos,
                           "avisado": prev.get("avisado") or False}
        if not adentro:
            estado[f["id"]]["avisado"] = False
            continue
        if seguidos >= ciclos and not prev.get("avisado"):
            estado[f["id"]]["avisado"] = True
            avisos.append(f)
    return avisos, estado


def valuar(pos, series):
    """Cuanto vale hoy desarmar una posicion.

    Se sale contra las puntas contrarias: la pata comprada se vende a su
    bid y la vendida se recompra a su ask. Nunca se cobra el ancho
    entero, aunque el spread este del todo adentro.
    """
    por_sim = {s["simbolo"]: s for s in series}
    c = por_sim.get(pos.get("sim_compra"))
    v = por_sim.get(pos.get("sim_venta"))
    if not c or not v:
        return None
    salida = c["compra"] - v["venta"]      # vendo al bid, recompro al ask
    if pos["estructura"] == "BEAR_CALL":
        # entro cobrando: el resultado es la prima menos lo que cuesta salir
        prima = pos["ancho"] - pos["riesgo"]
        gan = prima + salida
    else:
        gan = salida - pos["riesgo"]
    return {"salida": round(salida, 4),
            "ganancia": round(gan, 4),
            "ganancia_pct": round(gan / pos["riesgo"] * 100, 2)
                            if pos["riesgo"] else None,
            "ganancia_total": round(gan * LOTE * (pos.get("lotes") or 1), 2),
            "lotes_salida": int(min(c["q_compra"], v["q_venta"]))}


def motivos_desarme(pos, val, spot, cfg):
    """Las tres condiciones, en OR. Cualquiera alcanza."""
    gan_min = float(cfg.get("ganancia_min_pct") or 100)
    dias_min = int(cfg.get("dias_min_desarme") or 10)
    mov = float(cfg.get("mov_contrario_pct") or 4)

    out = []
    if val and val.get("ganancia_pct") is not None \
            and val["ganancia_pct"] >= gan_min:
        out.append("ganancia %.0f%% sobre el riesgo" % val["ganancia_pct"])

    try:
        d = (date.fromisoformat(pos["vencimiento"]) - date.today()).days
    except Exception:
        d = None
    if d is not None and 0 <= d < dias_min:
        out.append("quedan %d dias" % d)

    ref = pos.get("spot_alta")
    if ref and spot:
        var = (spot / ref - 1) * 100
        contra = -var if pos["estructura"] == "BULL_CALL" else var
        if contra >= mov:
            out.append("el papel se movio %.1f%% en contra" % contra)
    return out
