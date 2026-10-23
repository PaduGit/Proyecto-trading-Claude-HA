"""Precio y escenarios de una posicion, para el grafico de la ficha.

Una sola idea para acciones, CEDEARs y bonos: la historia de un año,
la volatilidad de los ultimos 6 meses y un abanico hacia adelante sin tendencia
(ni alcista ni bajista por defecto). Lo que cambia es la escala:

- Precio (acciones, CEDEARs, bonos con stop por precio): el abanico es
  lognormal, precio de hoy por exp(+-k * vol * raiz(t)).
- TIR (bonos): el abanico es normal en puntos basicos, TIR de hoy +- k *
  vol * raiz(t). La TIR no sube sola con el paso del tiempo como el
  precio de un bono que va cobrando, asi que el abanico no queda torcido.
- NY (CEDEARs y ADRs con niveles en dolares de NY): precio en US$ de NY.

El abanico y la probabilidad de tocar stop u objetivo (principio de
reflexion, sin tendencia) los calcula la pantalla con la volatilidad que
devuelve esto: cambiar de horizonte no vuelve a pedir nada.
"""

import logging
import math
from datetime import date, timedelta

import db

log = logging.getLogger("escenarios")

DIAS_HIST = 366          # historia de un año
RUEDAS_VOL = 126         # la volatilidad sale de los ultimos 6 meses
RUEDAS_ANIO = 252

# Series que ya se pidieron hacia atras hoy: si IOL no tiene historia
# anterior (especie nueva), no se vuelve a pedir en cada apertura.
_atras = {}


def _habil_anterior(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def serie_cierres(iol, mercado, simbolo, clave=None):
    """Cierres del ultimo año, de `cierres` y completados con IOL.

    Se guardan con `clave` (el simbolo local, o "NY:AMZN" para la serie
    de Nueva York) y se piden a IOL solo los dias que faltan hasta la
    rueda anterior: abrir la ficha dos veces no gasta dos pedidos. Si lo
    guardado empieza tarde (antes se guardaban 3 o 6 meses), se pide una
    vez por dia desde el principio del año.
    """
    clave = clave or simbolo
    hoy = date.today()
    desde = hoy - timedelta(days=DIAS_HIST)
    guardados = db.cierres_de(clave, desde.isoformat())
    if db._en_bono_hist(clave):
        # La serie de un bono es la de bono_hist: no se pide ni se copia.
        return [(r["fecha"], r["cierre"]) for r in guardados]
    ultimo = guardados[-1]["fecha"] if guardados else None
    falta_desde = (date.fromisoformat(ultimo) + timedelta(days=1)) if ultimo else desde
    if (guardados and guardados[0]["fecha"] > (desde + timedelta(days=10)).isoformat()
            and _atras.get(clave) != hoy):
        _atras[clave] = hoy
        falta_desde = desde
    if iol is not None and falta_desde <= _habil_anterior(hoy):
        try:
            datos = iol.serie(mercado, simbolo, falta_desde.isoformat(),
                              hoy.isoformat()) or []
            filas = []
            for p in datos:
                f = str(p.get("fechaHora") or "")[:10]
                v = p.get("ultimoPrecio") or p.get("cierreAnterior")
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                if f and v > 0 and f < hoy.isoformat():
                    filas.append((f, v))
            if filas:
                db.guardar_cierres(clave, filas)
                guardados = db.cierres_de(clave, desde.isoformat())
        except Exception as e:
            log.info("serie %s %s: %s", mercado, simbolo, e)
    return [(r["fecha"], r["cierre"]) for r in guardados]


def serie_tir(simbolo):
    """(fecha, TIR, MD) del ultimo año, de `bono_hist`."""
    desde = (date.today() - timedelta(days=DIAS_HIST)).isoformat()
    return [(r["fecha"], r["tir"], r["md"]) for r in db.conn().execute(
        "SELECT fecha, tir, md FROM bono_hist WHERE simbolo=? AND fecha >= ? "
        "AND tir IS NOT NULL ORDER BY fecha", (simbolo, desde))]


def volatilidad(valores, modo):
    """Anual, de las ultimas 126 ruedas (6 meses) aunque la serie sea mas
    larga. Precio: desvio de los retornos logaritmicos. TIR: desvio de
    los cambios diarios, en puntos de TIR (1 = 100 pb)."""
    valores = list(valores)[-(RUEDAS_VOL + 1):]
    if len(valores) < 20:
        return None
    if modo == "tir":
        d = [b - a for a, b in zip(valores, valores[1:])]
    else:
        d = [math.log(b / a) for a, b in zip(valores, valores[1:]) if a > 0 and b > 0]
    if len(d) < 15:
        return None
    m = sum(d) / len(d)
    var = sum((x - m) ** 2 for x in d) / (len(d) - 1)
    return math.sqrt(var * RUEDAS_ANIO)


def tir_curva(simbolo, tir_hoy):
    """TIR a la que volveria si el desvio contra la curva vuelve a su
    media: TIR de hoy menos (residuo de hoy - media) en pb."""
    try:
        import curva as CU
        filas = db.conn().execute(
            "SELECT residuo FROM residuo_hist WHERE simbolo=? ORDER BY fecha DESC "
            "LIMIT ?", (simbolo, CU.VENTANA)).fetchall()
        if len(filas) < CU.MIN_HISTORIA or tir_hoy is None:
            return None
        hist = [r["residuo"] for r in filas]
        media = sum(hist) / len(hist)
        return tir_hoy - (hist[0] - media) / 100.0
    except Exception:
        return None
