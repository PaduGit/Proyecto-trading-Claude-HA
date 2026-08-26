"""Que se cobra y cuando, cruzando tenencias con cronogramas.

Los cronogramas ya estan cargados para calcular TIR; lo unico que falta
es multiplicarlos por lo que hay en cada cuenta. Sirve para dos cosas:
saber cuanto entra y cuando, y avisar antes de cada pago.

Los importes son estimados y esta bien que lo sean: un pago ajustable
por CER se liquida con el coeficiente del dia de pago, que todavia no
existe. Se usa el vigente y se marca.
"""

import logging
from datetime import date, timedelta

import bonos as BO
import db
import renta_fija as RF

log = logging.getLogger("cobros")


def _factor(cfg, cer_actual=0):
    """Cuanto vale una unidad de flujo, y en que moneda queda.

    Devuelve (factor, moneda, estimado).
    """
    ajuste = (cfg.get("ajuste") or "").lower()

    if ajuste == "cer":
        base = cfg.get("cer_base")
        if not base:
            import cer as CER
            base = CER.base_de(cfg.get("emision"))
        actual = cer_actual
        if not actual:
            import cer as CER
            actual = CER.vigente()
        if not (base and actual):
            return None, "ARS", True
        nb = float(cfg.get("nominal_base") or 100) / 100.0
        return (actual / base) * nb, "ARS", True

    if ajuste in ("dolar_linked", "dolarlinked", "dl"):
        import dolar as DL
        tc = DL.vigente()
        if not tc:
            return None, "ARS", True
        return tc, "ARS", True

    if (cfg.get("moneda") or "").upper() == "USD":
        return 1.0, "USD", False
    return 1.0, "ARS", False


def proximos(dias=365, cer_actual=0, incluir_extranjeros=False,
             brokers_fuera=None):
    """Pagos futuros de lo que hay en cartera, ordenados por fecha."""
    bonos_cfg, _ = BO.cargar()
    esps = BO.especies()
    fuera = {b.upper() for b in (brokers_fuera or set())}
    hoy = date.today()
    tope = hoy + timedelta(days=dias)

    por_simbolo = {}
    for t in db.tenencias():
        if not incluir_extranjeros and t["broker"].upper() in fuera:
            continue
        if not t["cantidad"]:
            continue
        por_simbolo.setdefault(t["simbolo"].upper(), []).append(t)

    salida = []
    for sim, filas in por_simbolo.items():
        info = esps.get(sim)
        cfg = bonos_cfg.get(info["cronograma"]) if info else None
        if not cfg:
            continue
        factor, moneda, estimado = _factor(cfg, cer_actual)
        try:
            flujo = RF.flujo(cfg, hoy)
        except Exception as e:
            log.debug("flujo de %s: %s", sim, e)
            continue

        for p in flujo:
            f = p["fecha"]
            if f > tope:
                break
            nominales = sum(x["cantidad"] for x in filas)
            unidad = p["total"] / 100.0        # el flujo va por cada 100
            importe = (nominales * unidad * factor) if factor else None
            salida.append({
                "simbolo": sim,
                "nombre": cfg.get("nombre") or sim,
                "fecha": f.isoformat(),
                "dias": (f - hoy).days,
                "nominales": nominales,
                "renta": p["renta"], "amortizacion": p["amortizacion"],
                "por_cada_100": p["total"],
                "importe": importe, "moneda": moneda,
                "estimado": estimado,
                "brokers": sorted({x["broker"] for x in filas}),
            })
    salida.sort(key=lambda x: (x["fecha"], x["simbolo"]))
    return salida


CLAVE_AVISADOS = "cobros_avisados"


def _avisados():
    import json
    try:
        return set(json.loads(db.get_estado(CLAVE_AVISADOS) or "[]"))
    except Exception:
        return set()


def _guardar_avisados(s):
    import json
    # solo lo futuro: si no, la lista crece para siempre
    hoy = date.today().isoformat()
    db.set_estado(CLAVE_AVISADOS,
                  json.dumps(sorted(x for x in s if x.split("|")[-1] >= hoy)))


def por_avisar(dias_aviso=2, **kw):
    """Pagos que entran en la ventana de aviso y todavia no se avisaron.

    El aviso se guarda en la base y no en memoria: si no, cada reinicio
    volveria a avisar lo mismo.
    """
    ventana = proximos(dias=max(dias_aviso, 1), **kw)
    ya = _avisados()
    nuevos = [p for p in ventana
              if 0 <= p["dias"] <= dias_aviso
              and "%s|%s" % (p["simbolo"], p["fecha"]) not in ya]
    if nuevos:
        ya |= {"%s|%s" % (p["simbolo"], p["fecha"]) for p in nuevos}
        _guardar_avisados(ya)
    return nuevos
