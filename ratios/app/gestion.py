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
        if not n or (n.get("stop") is None and n.get("obj") is None):
            niv.pop(sim, None)
        else:
            niv[sim] = {"modo": n.get("modo") or "precio",
                        "stop": n.get("stop"), "obj": n.get("obj")}
        g.setdefault("avisados", {}).pop(sim, None)
    db.set_estado("gestion", json.dumps(g))
    return config()


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
        precio = e.get("precio")
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
                            "precio": p.get("precio"), "valor": 0.0, "brokers": []}
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

def _estado_nivel(n, precio, tir):
    """'stop', 'objetivo' o None segun donde esta hoy contra los niveles.
    Por TIR el stop se toca cuando la TIR sube (el precio cae)."""
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
    g = _leer()
    niv, avisados = g.get("niveles") or {}, g.get("avisados") or {}
    nuevos, vigentes = [], {}
    for sim, n in niv.items():
        tir = (tir_md.get(sim) or (None, None))[0]
        que = _estado_nivel(n, precios.get(sim), tir)
        if que:
            vigentes[sim] = que
            if avisados.get(sim) != que:
                actual = tir if n.get("modo") == "tir" else precios.get(sim)
                nuevos.append((sim, que, n["stop"] if que == "stop" else n["obj"],
                               actual, n.get("modo") or "precio"))
    if vigentes != avisados:
        g["avisados"] = vigentes
        db.set_estado("gestion", json.dumps(g))
    return nuevos


def tocados():
    """Lo que esta hoy en stop u objetivo, para Inicio."""
    return dict(_leer().get("avisados") or {})
