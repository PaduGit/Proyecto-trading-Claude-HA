"""Bonos duales CER/TAMAR: al vencimiento pagan el maximo de dos patas.

Condiciones de las resoluciones conjuntas 23, 25 y 32 de 2026:

- Pata CER: capital ajustado por CER entre diez habiles antes de la
  emision y diez habiles antes del vencimiento. Sin margen.
- Pata TAMAR: promedio aritmetico simple de la TAMAR de bancos privados
  en el mismo periodo, mas el margen, convertido a tasa efectiva
  mensual a 32 dias y capitalizado por DIAS 30/360:

      TEM = [(1 + (TAMAR + margen) / (365/32)) ^ (365/32)] ^ (1/12) - 1
      VPV = VNO * (1 + TEM) ^ (DIAS/360 * 12)

  El margen se suma a la TNA antes de convertir, no a la TEM.

Un solo pago, al vencimiento. Todo por cada 100 VNO, en pesos.

Proyeccion, con el mismo criterio que BADLAR y CER: el CER se congela
en el vigente y la TAMAR que falta publicar se completa con la vigente.
Congelar el CER es suponer inflacion cero de aca al vencimiento, asi
que la pata TAMAR casi siempre gana en la proyeccion. Por eso ademas se
informa la inflacion de equilibrio: la que falta para que la pata CER
empate a la TAMAR.
"""

import logging
from datetime import date

import cer as CER

log = logging.getLogger("dual")


def es_dual(cfg):
    return (cfg.get("tipo") or "").strip().lower() == "dual"


def _fecha(v):
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _dias_30_360(d1, d2):
    dd1 = min(d1.day, 30)
    dd2 = min(d2.day, 30) if dd1 == 30 else d2.day
    return (d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (dd2 - dd1)


def tem(tna_pct, margen_pct):
    """TEM a partir de la TNA en %, con el margen sumado antes."""
    n = 365.0 / 32.0
    return ((1 + (tna_pct + margen_pct) / 100.0 / n) ** n) ** (1 / 12.0) - 1


def calcular(cfg, al=None):
    """Las dos patas proyectadas al vencimiento, con los datos de `al`.

    Devuelve None si falta la TAMAR; la pata CER puede faltar sola y
    entonces el maximo es la TAMAR, marcado en `falta_cer`.
    """
    import tamar as TA
    al = _fecha(al or date.today())
    emi = _fecha(cfg["emision"])
    vto = _fecha(cfg["vencimiento"])
    margen = float(cfg.get("margen_tamar") or 0)
    inicio = CER._restar_habiles(emi, CER.REZAGO_HABILES)
    fin = CER._restar_habiles(vto, CER.REZAGO_HABILES)

    pr = TA.promedio_proyectado(inicio, fin, al)
    if pr is None:
        return None
    prom, n_pub, n_proy = pr
    t = tem(prom, margen)
    meses = _dias_30_360(emi, vto) / 360.0 * 12
    vpv_tamar = 100.0 * (1 + t) ** meses

    base = float(cfg.get("cer_base") or 0)
    if not base:
        try:
            base = CER.base_de(cfg.get("emision")) or 0
        except Exception as e:
            log.debug("CER base: %s", e)
            base = 0
    try:
        cer_vig = CER.vigente(al) or 0
    except Exception:
        cer_vig = 0
    vpv_cer = 100.0 * cer_vig / base if (base and cer_vig) else None

    gana = "CER" if (vpv_cer is not None and vpv_cer > vpv_tamar) else "TAMAR"
    vpv = max(vpv_tamar, vpv_cer or 0)

    # inflacion que falta para que la pata CER empate a la TAMAR
    eq = None
    if base and cer_vig:
        dias = (vto - al).days
        factor = (base * vpv_tamar / 100.0) / cer_vig
        if dias > 0:
            eq = {"factor": factor,
                  "mensual": (factor ** (30.4375 / dias) - 1) * 100,
                  "anual": (factor ** (365.0 / dias) - 1) * 100,
                  "ya_supera": factor <= 1}

    return {
        "vpv": vpv, "gana": gana,
        "vpv_tamar": vpv_tamar, "vpv_cer": vpv_cer,
        "tamar_promedio": prom, "tamar_publicados": n_pub,
        "tamar_proyectados": n_proy, "margen": margen,
        "tem": t * 100, "meses": meses,
        "cer_base": base or None, "cer_vigente": cer_vig or None,
        "cer_base_fecha": inicio.isoformat(),
        "falta_cer": vpv_cer is None,
        "equilibrio": eq,
    }


def filas(cfg, desde=None):
    """El flujo con el formato de renta_fija: un solo pago de VPV."""
    desde = _fecha(desde or date.today())
    vto = _fecha(cfg["vencimiento"])
    if vto <= desde:
        return []
    r = calcular(cfg, desde)
    if r is None:
        return []
    v = round(r["vpv"], 6)
    return [{"fecha": vto, "renta": round(v - 100.0, 6),
             "amortizacion": 100.0, "total": v, "residual_previo": 100.0}]


def tecnico(cfg, al=None):
    """Valor tecnico a hoy: el maximo de lo devengado por cada pata.

    La pata TAMAR devenga con el promedio publicado hasta hoy, sin
    proyectar; la CER con el coeficiente vigente.
    """
    import tamar as TA
    al = _fecha(al or date.today())
    emi = _fecha(cfg["emision"])
    inicio = CER._restar_habiles(emi, CER.REZAGO_HABILES)
    corte = CER._restar_habiles(al, CER.REZAGO_HABILES)
    pr = TA.promedio_proyectado(inicio, corte, al)
    v_t = None
    if pr is not None:
        t = tem(pr[0], float(cfg.get("margen_tamar") or 0))
        v_t = 100.0 * (1 + t) ** (_dias_30_360(emi, al) / 360.0 * 12)
    r = calcular(cfg, al)
    v_c = r["vpv_cer"] if r else None
    vals = [x for x in (v_t, v_c) if x is not None]
    return max(vals) if vals else None
