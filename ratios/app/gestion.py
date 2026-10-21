"""Gestion de la cartera: asignacion objetivo, riesgo y beneficio, rebalanceo.

Todo en dolares y a un año, que es como se mide la cartera entera.

**Bloques**, por funcion y no por instrumento:

- `dcorto`: dolar de baja duration (hard dollar con MD < 2,5, ON en
  dolares, caucion y efectivo en dolares);
- `hd`: hard dollar soberano de duration media o larga;
- `rv`: CEDEARs y acciones;
- `pesos`: CER, tasa en pesos, dolar linked, FCI y efectivo en pesos;
- `otros`: lo que no se pudo clasificar.

**Riesgo y beneficio de cada especie** ("si sale mal" y "si sale bien"):

- con stop y objetivo por precio: la distancia a cada uno; a la renta
  variable se le suma un deslizamiento al stop (puede abrir por debajo);
- con stop y objetivo por TIR (bonos): duration por la distancia en TIR,
  mas el carry del año; en los bonos en pesos el stop no cubre la
  devaluacion y el escenario de devaluacion se suma al riesgo;
- sin niveles: la renta fija rinde su TIR (los CER, TIR real mas
  inflacion menos la suba del MEP; las tasas en pesos, tasa menos MEP) y
  arriesga el escenario malo de su bloque; la renta variable, supuestos.

Los supuestos son opiniones, no datos: se editan desde la pantalla y se
guardan en `estado` (clave `gestion`), igual que la asignacion objetivo y
los niveles de cada especie. Los niveles tambien disparan avisos al
tocarse (`cruces`).
"""

import json
import logging
from datetime import datetime

import db

log = logging.getLogger("ratios.gestion")

BLOQUES = [
    {"k": "dcorto", "nombre": "Dólar de baja duration", "obj": 40, "banda": 5},
    {"k": "hd", "nombre": "Hard dollar soberano", "obj": 20, "banda": 5},
    {"k": "rv", "nombre": "CEDEARs y acciones", "obj": 20, "banda": 4},
    {"k": "pesos", "nombre": "Pesos tácticos", "obj": 15, "banda": 5},
    {"k": "otros", "nombre": "Táctico y otros", "obj": 5, "banda": 3},
]
SUPUESTOS = {"mal_dcorto": 5, "mal_hd": 17, "mal_rv": 30, "mal_pesos": 20,
             "mal_otros": 15, "mal_dl": 8, "esp_rv": 10, "deval": 25,
             "infl": 28, "desliz": 2}
MD_CORTA = 2.5
TIR_MAX = 40        # por encima, la TIR no se usa como retorno esperado
TOLERANCIA = 20     # caida aceptada de la cartera, en %
REGLA = 2.0         # relacion buscada: ganancia esperada por cada punto de caida


def _leer():
    try:
        g = json.loads(db.get_estado("gestion") or "{}")
        return g if isinstance(g, dict) else {}
    except (ValueError, TypeError):
        return {}


def config():
    g = _leer()
    obj = {b["k"]: (b["obj"], b["banda"]) for b in BLOQUES}
    for k, v in (g.get("asignacion") or {}).items():
        if k in obj and isinstance(v, (list, tuple)) and len(v) == 2:
            obj[k] = (float(v[0]), float(v[1]))
    sup = dict(SUPUESTOS)
    sup.update({k: float(v) for k, v in (g.get("supuestos") or {}).items()
                if k in SUPUESTOS})
    return {"asignacion": obj, "supuestos": sup, "niveles": g.get("niveles") or {}}


def guardar(cambios):
    """Mezcla los cambios con lo guardado. Un nivel en None o sin stop ni
    objetivo borra los niveles de esa especie (y su estado de aviso)."""
    g = _leer()
    for k in ("asignacion", "supuestos"):
        if isinstance(cambios.get(k), dict):
            g.setdefault(k, {}).update(cambios[k])
    for sim, n in (cambios.get("niveles") or {}).items():
        niv = g.setdefault("niveles", {})
        prev = niv.get(sim) or {}
        if not n or (n.get("stop") is None and n.get("obj") is None):
            niv.pop(sim, None)
        else:
            niv[sim] = {"modo": n.get("modo") or "precio",
                        "stop": n.get("stop"), "obj": n.get("obj")}
            if niv[sim]["modo"] == "ny":
                niv[sim]["ny"] = (n.get("ny") or ticker_ny(sim) or sim).strip().upper()
            # La nota se conserva si el cambio no la trae: editar el stop
            # desde la tarjeta no tiene que borrar el fundamento cargado.
            nota = n["nota"] if "nota" in n else prev.get("nota")
            nota = (nota or "").strip()[:600]
            if nota:
                niv[sim]["nota"] = nota
        g.setdefault("avisados", {}).pop(sim, None)
    db.set_estado("gestion", json.dumps(g))
    return config()


def archivar_nivel(sim, motivo=None, resultado=None, fecha=None, precio=None):
    """Saca los niveles de una especie que ya no se tiene y los guarda en
    `archivados` con el motivo de la salida y el resultado. Dejan de
    avisar. Devuelve True si habia niveles."""
    g = _leer()
    n = (g.get("niveles") or {}).pop(sim, None)
    if not n:
        return False
    g.setdefault("avisados", {}).pop(sim, None)
    arch = g.setdefault("archivados", [])
    arch.append(dict(n, simbolo=sim, motivo=motivo, resultado=resultado,
                     fecha=fecha, precio_salida=precio))
    g["archivados"] = arch[-200:]
    db.set_estado("gestion", json.dumps(g))
    return True


def archivados():
    return list(reversed(_leer().get("archivados") or []))


def _bloque(p, md):
    expo, tipo = p.get("exposicion") or "", p.get("tipo") or ""
    if tipo in ("acciones", "cedears") or expo in ("Acciones", "CEDEARs"):
        return "rv", None
    if expo == "CER":
        return "pesos", "real"
    if expo == "Dólar linked":
        return "pesos", "dl"
    if expo in ("Tasa $", "FCI"):
        return "pesos", "nominal"
    if expo == "Hard dollar":
        if tipo in ("on", "moneda") or md is None or md < MD_CORTA:
            return "dcorto", None
        return "hd", None
    return "otros", None


def _rb(e, sup):
    """(mal, bien, fuente, sin_stop) de una especie, en %."""
    n, md, tir, clase = e.get("niveles"), e.get("md"), e.get("tir"), e["clase"]
    fx = sup["mal_pesos"] if clase in ("real", "nominal") else \
        sup["mal_dl"] if clase == "dl" else 0
    if tir is not None:
        carry = tir + sup["infl"] - sup["deval"] if clase == "real" else \
            tir - sup["deval"] if clase == "nominal" else tir
    else:
        carry = None
    if n and n.get("stop") is not None and n.get("obj") is not None:
        if n.get("modo") == "tir" and md and tir is not None:
            return (md * (n["stop"] - tir) + fx, md * (tir - n["obj"]) + (carry or 0),
                    "stop y objetivo por TIR" + (" + devaluación" if fx else ""), False)
        if n.get("modo") == "ny":
            p_ny = e.get("precio_ny")
            if p_ny:
                desl = sup["desliz"] if e["bloque"] == "rv" else 0
                return ((p_ny - n["stop"]) / p_ny * 100 + desl,
                        (n["obj"] - p_ny) / p_ny * 100, "stop y objetivo en NY", False)
        precio = e.get("precio") if n.get("modo") != "ny" else None
        if precio:
            desl = sup["desliz"] if e["bloque"] == "rv" else 0
            return ((precio - n["stop"]) / precio * 100 + desl,
                    (n["obj"] - precio) / precio * 100, "stop y objetivo", False)
    if carry is not None:
        fuente = {"real": "TIR real + inflación − MEP", "nominal": "tasa − MEP",
                  "dl": "su TIR (A3500)"}.get(clase, "su TIR")
        return (fx or sup["mal_" + e["bloque"]], carry, fuente, True)
    if e["bloque"] == "rv":
        return (sup["mal_rv"], sup["esp_rv"], "supuesto", True)
    return (sup["mal_" + e["bloque"]], 0.0, "sin dato", True)


def calcular(posiciones, tir_md):
    """`posiciones`: las de `cartera.valuar`; `tir_md`: {simbolo: (tir, md)}
    de la tabla de BONOS."""
    cfg = config()
    sup, asig = cfg["supuestos"], cfg["asignacion"]
    ny = precios_ny()
    esp = {}
    for p in posiciones:
        if not p.get("valor"):
            continue
        sim = p["simbolo"]
        e = esp.get(sim)
        if not e:
            tir, md = tir_md.get(sim, (None, None))
            # Una TIR fuera de rango es un precio raro o un bono cerca del
            # default (MR43O daba 106%): no sirve como retorno esperado.
            if tir is not None and not (-10 <= tir <= TIR_MAX):
                tir = None
            if p.get("tipo") == "moneda" and tir is None:
                tir = 0.0
            bl, clase = _bloque(p, md)
            e = esp[sim] = {"simbolo": sim, "descripcion": p.get("descripcion"),
                            "bloque": bl, "clase": clase, "tir": tir, "md": md,
                            "precio": p.get("precio"), "valor": 0.0, "brokers": [],
                            "tipo": p.get("tipo"), "ticker_ny": ticker_ny(sim, p.get("tipo")),
                            "precio_ny": (ny.get(sim) or {}).get("precio"),
                            "ny_fecha": (ny.get(sim) or {}).get("fecha")}
        e["valor"] += p["valor"]
        e["brokers"].append(p.get("broker"))
    total = sum(e["valor"] for e in esp.values()) or 1.0
    for e in esp.values():
        e["peso"] = e["valor"] / total * 100
        e["niveles"] = cfg["niveles"].get(e["simbolo"])
        mal, bien, fuente, sin = _rb(e, sup)
        e.update(mal=mal, bien=bien, fuente=fuente, sin_stop=sin,
                 relacion=(bien / mal) if mal > 0 else None)

    def agrega(lista):
        w = sum(x["peso"] for x in lista)
        if not w:
            return {"peso": 0, "mal": None, "bien": None, "relacion": None}
        mal = sum(x["mal"] * x["peso"] for x in lista) / w
        bien = sum(x["bien"] * x["peso"] for x in lista) / w
        return {"peso": w, "mal": mal, "bien": bien,
                "relacion": bien / mal if mal > 0 else None}

    todas = list(esp.values())
    cartera = agrega(todas)
    bloques = []
    for b in BLOQUES:
        ag = agrega([e for e in todas if e["bloque"] == b["k"]])
        obj, banda = asig[b["k"]]
        dif = ag["peso"] - obj
        bloques.append(dict(ag, k=b["k"], nombre=b["nombre"], obj=obj, banda=banda,
                            fuera=abs(dif) > banda, dif=dif))
    suma = sum(b["obj"] for b in bloques)
    con = [b for b in bloques if b["mal"] is not None]
    w = sum(b["obj"] for b in con) or 1
    en_obj = {"mal": sum(b["mal"] * b["obj"] for b in con) / w,
              "bien": sum(b["bien"] * b["obj"] for b in con) / w}
    en_obj["relacion"] = en_obj["bien"] / en_obj["mal"] if en_obj["mal"] else None
    rebal = []
    for b in bloques:
        if not b["fuera"]:
            continue
        if b["dif"] > 0:
            peores = sorted((e for e in todas if e["bloque"] == b["k"]),
                            key=lambda e: e["relacion"] if e["relacion"] is not None else 99)[:2]
            rebal.append({"accion": "reducir", "bloque": b["nombre"],
                          "pp": b["dif"] - b["banda"],
                          "especies": [e["simbolo"] for e in peores]})
        else:
            rebal.append({"accion": "aumentar", "bloque": b["nombre"],
                          "pp": -b["dif"] - b["banda"], "especies": []})
    avisos = []
    if cartera["mal"] and cartera["mal"] > TOLERANCIA:
        avisos.append("El escenario malo (−%.1f%%) supera tu tolerancia de %d%%."
                      % (cartera["mal"], TOLERANCIA))
    sin_rv = [e["simbolo"] for e in todas if e["sin_stop"] and e["bloque"] == "rv"
              and e["peso"] >= 1]
    if sin_rv:
        avisos.append("Renta variable sin stop: %s" % ", ".join(sin_rv[:8]) +
                      (" y %d más." % (len(sin_rv) - 8) if len(sin_rv) > 8 else "."))
    malas = [e["simbolo"] for e in todas if not e["sin_stop"] and
             (e["relacion"] or 0) < REGLA]
    if malas:
        avisos.append("Con stop y objetivo, pero menos de 2 a 1: %s." % ", ".join(malas))
    con_stop = sum(e["peso"] for e in todas if not e["sin_stop"])
    return {"cartera": cartera, "bloques": bloques, "especies": sorted(
                todas, key=lambda e: (e["relacion"] if e["relacion"] is not None else 99)),
            "en_objetivo": en_obj, "suma_objetivo": suma, "rebalanceo": rebal,
            "avisos": avisos, "con_stop_pct": con_stop, "supuestos": sup,
            "tolerancia": TOLERANCIA, "regla": REGLA}


# -- avisos de stop y objetivo (pendiente 50) ---------------------------

def _estado_nivel(n, precio, tir, ny=None):
    """'stop', 'objetivo' o None segun donde esta hoy contra los niveles.
    Por TIR el stop se toca cuando la TIR sube (el precio cae)."""
    if n.get("modo") == "ny":
        precio = (ny or {}).get("precio")
        if not precio:
            return None
        if n.get("stop") is not None and precio <= n["stop"]:
            return "stop"
        if n.get("obj") is not None and precio >= n["obj"]:
            return "objetivo"
        return None
    if n.get("modo") == "tir":
        if tir is None:
            return None
        if n.get("stop") is not None and tir >= n["stop"]:
            return "stop"
        if n.get("obj") is not None and tir <= n["obj"]:
            return "objetivo"
        return None
    if not precio:
        return None
    if n.get("stop") is not None and precio <= n["stop"]:
        return "stop"
    if n.get("obj") is not None and precio >= n["obj"]:
        return "objetivo"
    return None


def cruces(precios, tir_md):
    """Niveles tocados que todavia no se avisaron. Una vez avisado, se
    rearma recien cuando vuelve adentro del rango: un precio que oscila
    sobre el stop no avisa en cada ciclo. Devuelve [(simbolo, que, nivel,
    actual, modo)] y guarda el estado."""
    purgar_sin_tenencia()
    g = _leer()
    niv, avisados = g.get("niveles") or {}, g.get("avisados") or {}
    ny = precios_ny()
    nuevos, vigentes = [], {}
    for sim, n in niv.items():
        tir = (tir_md.get(sim) or (None, None))[0]
        que = _estado_nivel(n, precios.get(sim), tir, ny.get(sim))
        if que:
            vigentes[sim] = que
            if avisados.get(sim) != que:
                actual = tir if n.get("modo") == "tir" else \
                    (ny.get(sim) or {}).get("precio") if n.get("modo") == "ny" \
                    else precios.get(sim)
                nuevos.append((sim, que, n["stop"] if que == "stop" else n["obj"],
                               actual, n.get("modo") or "precio"))
    if vigentes != avisados:
        g["avisados"] = vigentes
        db.set_estado("gestion", json.dumps(g))
    return nuevos


def purgar_sin_tenencia():
    """Archiva los niveles de las especies que ya no estan en ninguna
    cuenta, salga como salga la posicion (boletos, JSON, IOL o a mano).
    El motivo es el nivel tocado si lo habia, o "sin tenencia". Sin
    ninguna tenencia cargada no toca nada: una base vacia no es una
    cartera vendida."""
    try:
        tenidos = {r[0] for r in db.conn().execute(
            "SELECT simbolo FROM tenencia GROUP BY simbolo HAVING SUM(cantidad) > 0")}
    except Exception:
        return []
    if not tenidos:
        return []
    g = _leer()
    fuera = [s_ for s_ in (g.get("niveles") or {}) if s_ not in tenidos]
    avisados = g.get("avisados") or {}
    hechos = []
    for s_ in fuera:
        if archivar_nivel(s_, avisados.get(s_) or "sin tenencia", None,
                          datetime.now().date().isoformat(), None):
            hechos.append(s_)
    return hechos


def tocados():
    """Lo que esta hoy en stop u objetivo, para Inicio."""
    purgar_sin_tenencia()
    return dict(_leer().get("avisados") or {})


# -- stop y objetivo en dolares de NY (CEDEARs y ADRs) ----------------

# Acciones locales con ADR: el ticker en NY no siempre es el local. Las
# que no estan aca no ofrecen el modo, salvo que se cargue a mano.
ADR = {"YPFD": "YPF", "PAMP": "PAM", "TECO2": "TEO", "TGSU2": "TGS",
       "CRES": "CRESY", "IRSA": "IRS", "GGAL": "GGAL", "BMA": "BMA",
       "BBAR": "BBAR", "SUPV": "SUPV", "CEPU": "CEPU", "LOMA": "LOMA",
       "EDN": "EDN"}
MERCADOS_NY = ("nYSE", "nASDAQ", "aMEX")


def ticker_ny(sim, tipo=None):
    """Ticker en NY sugerido: el del ADR para una local, el mismo para un
    CEDEAR, None si no hay de donde sacarlo."""
    sim = (sim or "").upper()
    if sim in ADR:
        return ADR[sim]
    if (tipo or "").lower() == "cedears":
        return sim
    return None


def precios_ny():
    """{simbolo local: {ticker, mercado, precio, fecha, ts}} de la ultima
    revision. Se pide una vez por dia, a las 12."""
    try:
        d = json.loads(db.get_estado("ny_precios") or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def cotizar_ny(iol, tk):
    """(mercado, ultimo precio) de un ticker de NY probando los mercados,
    o (None, None). Para el grafico de un nivel que todavia no se guardo."""
    for mer in MERCADOS_NY:
        try:
            c = iol.cotizacion(mer, tk) or {}
        except Exception:
            continue
        p = c.get("ultimo") or c.get("ref")
        if p:
            return mer, float(p)
    return None, None


# Si la ultima actualizacion de NY termino entera. Un 429 o un error de
# red la dejan incompleta y el monitor la reintenta mas tarde en el dia.
ny_completo = True


def actualizar_ny(iol, solo=None):
    """Ultimo precio en NY de las especies con niveles en modo ny.

    El mercado (NYSE, NASDAQ o AMEX) se descubre la primera vez y queda
    guardado: despues es un solo pedido por especie.
    """
    from datetime import date as _d, datetime as _dt
    global ny_completo
    niv = config()["niveles"]
    previos = precios_ny()
    out = dict(previos)
    hechos = 0
    ny_completo = True
    for sim, n in niv.items():
        if n.get("modo") != "ny" or (solo and sim not in solo):
            continue
        tk = (n.get("ny") or ticker_ny(sim) or sim).upper()
        prev = previos.get(sim) or {}
        orden = ([prev["mercado"]] if prev.get("ticker") == tk and prev.get("mercado")
                 else []) + [m for m in MERCADOS_NY if m != prev.get("mercado")]
        de_red = 0
        for mer in orden:
            try:
                c = iol.cotizacion(mer, tk) or {}
            except Exception as e:
                st = getattr(e, "status", None)
                if st == 429:
                    ny_completo = False
                    db.set_estado("ny_precios", json.dumps(out))
                    return hechos
                # 404 = no cotiza en ese mercado; lo demas es transitorio
                if st != 404:
                    de_red += 1
                continue
            p = c.get("ultimo") or c.get("ref")
            if p:
                out[sim] = {"ticker": tk, "mercado": mer, "precio": float(p),
                            "fecha": _d.today().isoformat(),
                            "ts": _dt.now().isoformat(timespec="seconds")}
                hechos += 1
                break
        else:
            if de_red:
                ny_completo = False
            out[sim] = dict(prev, ticker=tk, error="sin cotización en NY")
    db.set_estado("ny_precios", json.dumps(out))
    return hechos


# -- cargar niveles pegando JSON ----------------------------------------

MODOS = ("precio", "tir", "ny")


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip()
    if "," in t:                       # 1.234,5 -> 1234.5
        t = t.replace(".", "").replace(",", ".")
    return float(t)


def revisar_importacion(datos, en_cartera, actuales=None):
    """Vista previa de un JSON de niveles: {"niveles": {SIM: {...}}}.

    Devuelve (filas, validos). Cada fila dice que pasaria con la especie:
    nuevo, reemplaza, se omite (no esta en cartera) o error. Solo lo
    valido y en cartera va en `validos`: una especie vendida no tiene que
    quedar avisando ni pidiendo su precio de NY todos los dias.
    """
    actuales = config()["niveles"] if actuales is None else actuales
    niveles = (datos or {}).get("niveles") if isinstance(datos, dict) else None
    if not isinstance(niveles, dict) or not niveles:
        raise ValueError('falta "niveles": {"SIMBOLO": {"modo", "stop", "obj"}}')
    filas, validos = [], {}
    for sim, n in niveles.items():
        sim = (sim or "").strip().upper()
        f = {"simbolo": sim}
        try:
            if not isinstance(n, dict):
                raise ValueError("cada especie va como objeto")
            modo = (n.get("modo") or "precio").strip().lower()
            if modo not in MODOS:
                raise ValueError("modo %r: tiene que ser precio, tir o ny" % modo)
            stop, obj = _num(n.get("stop")), _num(n.get("obj", n.get("objetivo")))
            if stop is None and obj is None:
                raise ValueError("sin stop ni objetivo")
            # Por precio el stop va abajo; por TIR, arriba (la TIR sube
            # cuando el precio cae).
            if stop is not None and obj is not None and \
                    ((modo == "tir" and stop <= obj) or (modo != "tir" and stop >= obj)):
                raise ValueError("stop y objetivo invertidos para el modo %s" % modo)
            d = {"modo": modo, "stop": stop, "obj": obj}
            if modo == "ny":
                d["ny"] = (n.get("ny") or ticker_ny(sim, "cedears") or sim).strip().upper()
            if n.get("nota"):
                d["nota"] = str(n["nota"]).strip()[:600]
            f.update(d)
            if sim not in en_cartera:
                f["estado"] = "omitida"
                f["motivo"] = "no está en cartera"
            else:
                f["estado"] = "reemplaza" if sim in actuales else "nueva"
                if sim in actuales:
                    f["antes"] = actuales[sim]
                validos[sim] = d
        except (TypeError, ValueError) as e:
            f["estado"] = "error"
            f["motivo"] = str(e)
        filas.append(f)
    return filas, validos
