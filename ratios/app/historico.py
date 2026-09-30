"""Serie histórica de TIR y duration por bono.

Se calcula una vez desde 2023 con los cierres de IOL y después se agrega
un punto por día. Cada fila guarda el precio, la TIR y la duration de esa
fecha, con el residual y el CER que correspondían a ese día.
"""

import logging
from datetime import date, datetime, timedelta

import bonos as BO
import cer as CER
import db
import renta_fija as RF

log = logging.getLogger("historico")

DESDE = date(2023, 1, 1)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS bono_hist (
    simbolo   TEXT NOT NULL,
    fecha     TEXT NOT NULL,
    precio    REAL NOT NULL,
    tir       REAL,
    md        REAL,
    duration  REAL,
    residual  REAL,
    cer       REAL,
    badlar    REAL,
    PRIMARY KEY (simbolo, fecha)
);
"""


def init():
    c = db.conn()
    c.executescript(ESQUEMA)
    # la columna se agrego despues: en bases ya creadas no viene sola
    cols = [r[1] for r in c.execute("PRAGMA table_info(bono_hist)")]
    if "badlar" not in cols:
        c.execute("ALTER TABLE bono_hist ADD COLUMN badlar REAL")
    c.commit()
    # 0.48.0: con BYMA como fuente, los intentos hacia atras anotados con
    # IOL solo se vuelven a hacer una vez.
    try:
        if db.get_estado("hist_fuente") != "byma":
            db.set_estado("hist_atras", "{}")
            db.set_estado("hist_huecos", "{}")
            db.set_estado("hist_fuente", "byma")
    except Exception as e:
        log.warning("estado del histórico: %s", e)


def limpiar_no_habiles():
    """Borra los puntos que no son de una rueda. Corre en cada arranque.

    - **Sabados y domingos**, siempre: `cerrar_dia_bonos` los grababa
      con el precio de la ultima rueda hasta que se le puso la guarda.
      Entraban al z como un dia mas.
    - **26 y 27/09/2024**, una sola vez: quedaron de una ventana
      anterior de BYMA sin desajustar (AL30 46.567 contra 70.800) y
      ninguna corrida posterior los alcanzaba. El recalculo forzado los
      vuelve a pedir, ahora a IOL.

    Los feriados no se tocan: BYMA tiene dias con negociacion y sin
    liquidacion (puentes, 6/11, 24/12) y esos cierres son reales.
    """
    c = db.conn()
    n = 0
    for t in ("bono_hist", "residuo_hist"):
        try:
            n += c.execute("DELETE FROM %s WHERE strftime('%%w', fecha) "
                           "IN ('0','6')" % t).rowcount
        except Exception as e:
            log.warning("limpieza de %s: %s", t, e)
    try:
        if not db.get_estado("migr_hist_2024_09"):
            for t in ("bono_hist", "residuo_hist"):
                n += c.execute("DELETE FROM %s WHERE fecha IN "
                               "('2024-09-26','2024-09-27')" % t).rowcount
            db.set_estado("migr_hist_2024_09", "1")
    except Exception as e:
        log.warning("limpieza de 09/2024: %s", e)
    c.commit()
    if n:
        log.info("histórico: %d puntos fuera de rueda borrados", n)
    return n


def _guardar(filas):
    if not filas:
        return 0
    c = db.conn()
    c.executemany(
        "INSERT OR REPLACE INTO bono_hist "
        "(simbolo, fecha, precio, tir, md, duration, residual, cer, badlar) "
        "VALUES (?,?,?,?,?,?,?,?,?)", filas)
    c.commit()
    return len(filas)


def _cer_de(f):
    """CER que aplicaba en esa fecha, con el rezago de diez hábiles."""
    try:
        return CER.valor(CER._restar_habiles(f, CER.REZAGO_HABILES))
    except Exception:
        return None


def _badlar_de(f):
    """BADLAR que regia esa fecha, ya rezagada diez hábiles."""
    try:
        import badlar as BA
        return BA.vigente(f)
    except Exception:
        return None


def calcular_punto(simbolo, f, precio, cfg, info, mep=None):
    """TIR y duration de un bono en una fecha, con los datos de ese día."""
    if not precio or precio <= 0:
        return None

    es_cer = (cfg.get("ajuste") or "").lower() == "cer"
    coef = None
    tv = None

    if es_cer:
        base = cfg.get("cer_base") or CER.base_de(cfg.get("emision"))
        coef = _cer_de(f)
        if not base or not coef:
            return None
        p = precio / (coef / base * float(cfg.get("nominal_base") or 100) / 100)
    elif (not (cfg.get("ajuste") or "")
          and (cfg.get("moneda") or "").upper() == "ARS"):
        # bono en pesos: la TIR se calcula en pesos, sin pasar por MEP
        p = precio / (float(cfg.get("nominal_base") or 100) / 100)
    elif (cfg.get("ajuste") or "").lower() in ("dolar_linked",
                                                 "dolarlinked", "dl"):
        # cotiza en pesos y ajusta por A3500: el precio se lleva a dolares
        # con el tipo de cambio vigente ese dia, como en la tabla en vivo
        import dolar as DL
        tc = DL.vigente(f)
        if not tc:
            return None
        p = precio / tc / (float(cfg.get("nominal_base") or 100) / 100)
    elif info["moneda"] == "USD":
        p = precio / (float(cfg.get("nominal_base") or 100) / 100)
    else:
        # bono hard dollar cotizando en pesos: sin MEP de esa fecha no
        # se puede convertir, así que ese punto se omite
        if not mep:
            return None
        p = precio / mep / (float(cfg.get("nominal_base") or 100) / 100)

    # cupon variable: se congela la tasa de esa fecha y se proyecta
    # constante, asi el punto no cambia cuando el BCRA publica mas datos
    if (cfg.get("interes") or {}).get("variable"):
        tv = _badlar_de(f)
        if tv is None:
            return None
        tv += float(cfg["interes"]["variable"].get("spread") or 0)

    # Liquidacion T+1, como en vivo: desde la fecha ex el pago ya no es
    # del comprador y no puede seguir en el flujo.
    liq = BO.liquidacion(f)
    filas = RF.flujo(cfg, liq, tasa_var=tv)
    if not filas:
        return None
    r = RF.tir(p, cfg, liq, filas)
    if r is None:
        return None
    mac, md = RF.duration(p, cfg, liq, r, filas)
    return (simbolo, f.isoformat(), precio, r * 100, md, mac,
            RF.residual(cfg, liq), coef, tv)


def arranque_badlar(cfg, desde):
    """Desde cuando hace falta la BADLAR para reconstruir un bono.

    No sirve pedir desde 1999: alcanza con la emision del bono, o con el
    arranque de la serie historica si es posterior.
    """
    try:
        emi = RF._fecha(cfg["emision"])
    except Exception:
        return desde
    return max(emi, desde) if isinstance(desde, date) else emi


def reconstruir(iol, simbolo=None, desde=None, hasta=None, mercado="bCBA",
                forzar=False, marcar=True):
    """Baja los cierres de IOL y calcula la serie.

    Por defecto arranca donde quedó, así que solo agrega hacia adelante.
    Con `forzar` recalcula desde el principio: hace falta cuando cambia
    un insumo del cálculo y los puntos viejos quedaron mal. Le pasó al
    DICP, que se armó con una base CER equivocada porque la serie del
    CER todavía no llegaba hasta 2003.
    """
    init()
    desde = desde or DESDE
    hasta = hasta or date.today()
    bonos_cfg, _ = BO.cargar()
    esps = BO.especies()

    objetivo = [simbolo] if simbolo else sorted(esps)
    total = 0
    meps = {}

    for sim in objetivo:
        info = esps.get(sim)
        if not info:
            continue
        cfg = bonos_cfg.get(info["cronograma"])
        if not cfg:
            continue

        if not reconstruible(cfg, info):
            continue

        # Un hard dollar que cotiza en pesos se lleva a dolares con el MEP
        # de ese dia, reconstruido de AL30 sobre AL30D en esta misma
        # tabla. Sin MEP ese dia el punto queda sin TIR.
        necesita_mep = (_tipo_rf(cfg) == "hard_dollar"
                        and info["moneda"] != "USD")
        es_dl = (cfg.get("ajuste") or "").lower() in ("dolar_linked",
                                                      "dolarlinked", "dl")
        if es_dl:
            try:
                import dolar as DL
                DL.asegurar_rango(arranque_badlar(cfg, desde), date.today())
            except Exception as e:
                log.warning("A3500 para %s: %s", sim, e)

        # con cupon variable el punto de cada dia necesita la tasa de ese
        # dia: sin la serie entera solo saldrian los ultimos dias
        if (cfg.get("interes") or {}).get("variable"):
            try:
                import badlar as BA
                BA.asegurar_rango(arranque_badlar(cfg, desde), date.today())
            except Exception as e:
                log.warning("BADLAR para %s: %s", sim, e)

        arranque = desde
        if not forzar:
            ultimo = db.conn().execute(
                "SELECT MAX(fecha) f FROM bono_hist WHERE simbolo=?", (sim,)
            ).fetchone()["f"]
            if ultimo:
                arranque = date.fromisoformat(ultimo) + timedelta(days=1)
        if arranque > hasta:
            continue

        emision = RF._fecha(cfg["emision"])
        if arranque < emision:
            arranque = emision

        serie, huecos, err = serie_en_tramos(iol, mercado, sim, arranque,
                                             hasta)
        _anotar(sim, huecos, err)
        if err and not serie:
            log.warning("histórico %s: %s", sim, err)
            continue
        # Solo lo de BYMA viene ajustado. Lo de IOL anterior a su ventana
        # ya es el precio real y no se toca.
        de_byma = [p for p in serie or [] if p.get("_fuente") == "byma"]
        if de_byma:
            otros = [p for p in serie if p.get("_fuente") != "byma"]
            de_byma = desajustar(iol, mercado, sim, de_byma, cfg, info)
            serie = [p for p in otros + de_byma
                     if str(p.get("fechaHora") or "")[:10] <= hasta.isoformat()]

        filas = []
        for punto in serie or []:
            fecha = str(punto.get("fechaHora") or "")[:10]
            precio = punto.get("ultimoPrecio") or punto.get("cierreAnterior")
            try:
                precio = float(precio)
            except (TypeError, ValueError):
                continue
            if not fecha or precio <= 0:
                continue
            try:
                f = date.fromisoformat(fecha)
            except ValueError:
                continue
            mep = None
            if necesita_mep:
                if f not in meps:
                    try:
                        meps[f] = BO.mep_al(f)
                    except Exception:
                        meps[f] = None
                mep = meps[f]
            p = calcular_punto(sim, f, precio, cfg, info, mep=mep)
            if p:
                filas.append(p)

        n = _guardar(filas)
        total += n
        if n:
            log.info("histórico %s: +%d días", sim, n)

    # un relleno hacia atras no mueve la marca: termina antes de hoy
    if marcar:
        db.set_estado("hist_bonos_hasta", hasta.isoformat())
    return total


# -- series de BYMA ajustadas ------------------------------------------

TOLERANCIA_FACTOR = 0.005     # 0,5% entre cronograma e IOL


def _fecha_punto(p):
    try:
        return date.fromisoformat(str(p.get("fechaHora") or "")[:10])
    except ValueError:
        return None


def _precio_punto(p):
    try:
        return float(p.get("ultimoPrecio") or p.get("cierreAnterior"))
    except (TypeError, ValueError):
        return None


def _pagos(cfg):
    """(fecha, total por 100 VN original) de cada pago del cronograma."""
    try:
        emi = RF._fecha(cfg["emision"])
        return [(x["fecha"], x["total"])
                for x in RF.flujo(cfg, emi - timedelta(days=1))
                if x.get("total")]
    except Exception:
        return []


def _pago_en_precio(cfg, info, total, dia, mep=None):
    """Un pago del cronograma en la misma unidad que el precio.

    Las mismas conversiones que `calcular_punto`, al reves. Sin forma de
    saber la plata -tasa variable, duales- devuelve None y el factor
    queda para IOL.
    """
    nb = float(cfg.get("nominal_base") or 100) / 100
    ajuste = (cfg.get("ajuste") or "").lower()
    if (cfg.get("interes") or {}).get("variable") or \
            (cfg.get("tipo") or "").strip().lower() == "dual":
        return None
    if ajuste == "cer":
        base = cfg.get("cer_base") or CER.base_de(cfg.get("emision"))
        coef = _cer_de(dia)
        return total * coef / base * nb if base and coef else None
    if not ajuste and (cfg.get("moneda") or "").upper() == "ARS":
        return total * nb
    if ajuste in ("dolar_linked", "dolarlinked", "dl"):
        import dolar as DL
        tc = DL.vigente(dia)
        return total * tc * nb if tc else None
    if info.get("moneda") == "USD":
        return total * nb
    return total * mep * nb if mep else None


def _cierre_iol(iol, mercado, sim, dia):
    """Cierre real de un dia, sin ajustar. Un solo dia por pedido: con
    rangos largos IOL devuelve 500 en varias especies, y el dia suelto
    responde. El `hasta` de IOL es excluyente."""
    try:
        pts = iol.serie(mercado, sim, dia.isoformat(),
                        (dia + timedelta(days=1)).isoformat(),
                        ajustada="sinAjustar") or []
    except Exception as e:
        log.info("cierre IOL %s %s: %s", sim, dia, str(e)[:120])
        return None
    for p in pts:
        if _fecha_punto(p) == dia:
            return _precio_punto(p)
    return None


def desajustar(iol, mercado, sim, serie, cfg, info):
    """Devuelve la serie de BYMA con los precios reales.

    BYMA ajusta hacia atras por cada pago: multiplica todo lo anterior a
    la fecha ex por 1 - pago / cierre del dia anterior, y los factores se
    acumulan. AL30D el 07/07/2026 figuraba 56,13 contra 64,40 real
    (0,8716); antes del 08/01/2026, 0,7630 = 0,8716 x 0,8754.

    Por cada pago, del mas nuevo al mas viejo: el factor sale del
    cronograma y se verifica contra el cierre real de IOL del ultimo dia
    con el pago. Si difieren mas de 0,5% manda IOL; si IOL no responde
    queda el del cronograma, marcado "sin verificar"; si no hay ninguno
    de los dos, ese tramo queda como vino, marcado "sin factor".
    Lo que se decide queda en `hist_ajustes`, para Explorar.
    """
    pts = sorted((p for p in serie if _fecha_punto(p) and _precio_punto(p)),
                 key=_fecha_punto)
    if len(pts) < 2:
        return serie
    fechas = [_fecha_punto(p) for p in pts]
    hoy = date.today()
    guardado = _leer_estado("hist_ajustes").get(sim) or {}
    eventos = []
    for fpago, total in _pagos(cfg):
        if fpago > hoy or fpago <= fechas[0]:
            continue
        # fecha ex: el primer dia que liquida el dia del pago o despues
        i = next((k for k, d in enumerate(fechas)
                  if BO.liquidacion(d) >= fpago), None)
        if i is None or i == 0:
            continue
        eventos.append((fechas[i], fechas[i - 1], fpago, total))
    if not eventos:
        return serie

    factor_despues = 1.0
    factores = []                      # (fecha ex, factor acumulado antes)
    registro = {}
    for ex, cum, fpago, total in sorted(eventos, reverse=True):
        clave = ex.isoformat()
        previo = guardado.get(clave)
        if previo and previo.get("estado") in ("verificado",
                                               "corregido con IOL",
                                               "desde IOL"):
            f = previo["factor"]       # el factor de un pago no cambia
            estado = previo["estado"]
        else:
            ajustado = _precio_punto(pts[fechas.index(cum)])
            mep = None
            if info.get("moneda") != "USD" and not cfg.get("ajuste"):
                try:
                    mep = BO.mep_al(cum)
                except Exception:
                    mep = None
            pago = _pago_en_precio(cfg, info, total, cum, mep)
            # f = 1 - pago / real, con real = ajustado / (f x lo de
            # despues): despejando, f = 1 / (1 + pago x despues / ajustado)
            f_cr = (1 / (1 + pago * factor_despues / ajustado)) \
                if pago and pago > 0 and ajustado else None
            real_iol = _cierre_iol(iol, mercado, sim, cum)
            f_iol = (ajustado / real_iol / factor_despues) \
                if real_iol else None
            if f_cr and f_iol:
                if abs(f_cr / f_iol - 1) <= TOLERANCIA_FACTOR:
                    f, estado = f_cr, "verificado"
                else:
                    f, estado = f_iol, "corregido con IOL"
            elif f_iol:
                f, estado = f_iol, "desde IOL"
            elif f_cr:
                f, estado = f_cr, "sin verificar"
            else:
                f, estado = 1.0, "sin factor"
        factor_despues *= f
        factores.append((ex, factor_despues))
        registro[clave] = {"factor": round(f, 6), "estado": estado,
                           "pago": fpago.isoformat()}

    todos = _leer_estado("hist_ajustes")
    todos[sim] = registro
    db.set_estado("hist_ajustes", json.dumps(todos))

    salida = []
    for p, d in zip(pts, fechas):
        # factor acumulado de todos los pagos cuya fecha ex es posterior
        acum = 1.0
        for ex, fac in factores:        # del mas nuevo al mas viejo
            if d < ex:
                acum = fac
        q = dict(p)
        q["ultimoPrecio"] = _precio_punto(p) / acum
        salida.append(q)
    return salida


def ajustes():
    return _leer_estado("hist_ajustes")


def reconstruible(cfg, info):
    """Si la TIR de una especie se puede calcular hacia atras.

    Hoy entran todas: los hard dollar en pesos se convierten con el MEP
    de cada dia, reconstruido de AL30 sobre AL30D, y los dolar linked
    con el A3500. Antes se decidia por la moneda de la especie, y un CER
    cuya especie figura en pesos -DIP0, PAP0- quedaba afuera aunque su
    familia tiene curva. Aunque una familia no llegue a los cinco bonos
    que pide la curva, conviene tener la historia: cuando se agreguen
    bonos, el desvio se arma sin volver a bajar nada.
    """
    return bool(cfg and info)


def _tipo_rf(cfg):
    import bonos as _BO
    return _BO._tipo(cfg)


def inicio_de(cfg):
    """Desde cuando tiene sentido pedir la serie: la emision o 2023."""
    try:
        return max(RF._fecha(cfg["emision"]), DESDE)
    except Exception:
        return DESDE


# Margen entre la emision y el primer precio guardado antes de considerar
# que falta historia: un bono puede tardar unos dias en operar.
TOLERANCIA_INICIO = 20


def sin_serie():
    """Especies a las que les falta historia, con el tramo que falta.

    Devuelve una lista de (simbolo, desde, hasta). Antes solo contaba las
    que no tenian ningun punto: un bono agregado a mitad de camino
    recibia el punto del ciclo diario antes que el backfill, y con uno
    solo ya quedaba afuera para siempre. Ahora tambien cuenta el hueco
    hacia atras, una sola vez por especie: si IOL no tiene precios
    anteriores, el intento queda anotado y no se repite en cada arranque.
    """
    bonos_cfg, _ = BO.cargar()
    esps = BO.especies()
    primeras = {r["simbolo"]: r["d0"] for r in db.conn().execute(
        "SELECT simbolo, MIN(fecha) AS d0 FROM bono_hist GROUP BY simbolo")}
    intentos = _leer_estado("hist_atras")
    out = []
    for sim, info in sorted(esps.items()):
        cfg = bonos_cfg.get(info["cronograma"])
        if not cfg or not reconstruible(cfg, info):
            continue
        ini = inicio_de(cfg)
        d0 = primeras.get(sim)
        if d0 is None:
            out.append((sim, ini, None))
            continue
        d0 = date.fromisoformat(d0)
        if (d0 - ini).days > TOLERANCIA_INICIO and \
                intentos.get(sim) != d0.isoformat():
            out.append((sim, ini, d0 - timedelta(days=1)))
    return out


# -- estado de la reconstruccion -------------------------------------

import json
import threading

progreso = {"corriendo": False, "actual": None, "hechas": 0, "total": 0,
            "puntos": 0, "inicio": None, "fin": None, "error": None}
_lock = threading.Lock()


def _leer_estado(clave):
    try:
        return json.loads(db.get_estado(clave) or "{}")
    except Exception:
        return {}


def _anotar(sim, huecos, err):
    """Huecos y errores por especie, para mostrarlos en pantalla."""
    d = _leer_estado("hist_huecos")
    if huecos or err:
        d[sim] = {"huecos": huecos, "error": err,
                  "fecha": date.today().isoformat()}
    else:
        d.pop(sim, None)
    db.set_estado("hist_huecos", json.dumps(d))


def huecos():
    return _leer_estado("hist_huecos")


def serie_en_tramos(iol, mercado, sim, desde, hasta):
    """La serie de IOL, partida si hace falta.

    Para varias especies -los Boncer TZX, TX28, X30S6- IOL devuelve 500
    con rangos largos y responde bien con un mes. Se intenta el rango
    entero, que para la mayoria anda y cuesta una sola llamada; si
    falla, se pide de a un mes, y un mes que falla se parte en semanas.
    Una semana que igual falla queda como hueco, sin perder la especie.

    Devuelve (puntos, huecos, error). Un 429 corta todo: IOL pidio
    frenar y seguir partiendo solo multiplica las llamadas.
    """
    # BYMA primero: una llamada, y responde donde IOL falla. IOL queda
    # para cuando BYMA no tiene nada y para lo anterior a su ventana.
    try:
        import byma as BY
        # Hasta hoy aunque se pida menos: la serie viene ajustada por
        # todos los pagos hasta el dia de la descarga, y para desajustarla
        # hacen falta los precios de alrededor de cada uno. `reconstruir`
        # recorta despues de desajustar.
        pts = BY.historia(sim, desde, max(hasta, date.today()))
        if pts:
            for p in pts:
                p["_fuente"] = "byma"
            return _antes_de_byma(iol, mercado, sim, desde, pts)
    except Exception as e:
        log.info("histórico %s: BYMA sin datos (%s), sigo con IOL", sim,
                 str(e)[:120])
    return _serie_iol(iol, mercado, sim, desde, hasta)


# Margen antes de ir a buscar a IOL lo que BYMA no trae: el primer punto
# de BYMA cae en el primer habil de su ventana, no en el `desde` pedido.
MARGEN_BYMA = 7


def _antes_de_byma(iol, mercado, sim, desde, pts):
    """Completa con IOL lo anterior al primer punto de BYMA.

    BYMA devuelve una ventana movil de unos dos años. Si se le pide desde
    la emision, lo anterior queda sin tocar: ni un recalculo forzado lo
    alcanzaba, y AL30 seguia con 987 dias sin TIR de una corrida vieja.
    Peor, los dos primeros dias de una ventana anterior (26 y 27/09/2024)
    quedaron grabados ajustados y ninguna corrida posterior los piso.

    Los puntos de IOL van marcados con `_fuente = "iol"`: vienen
    `sinAjustar` y no pasan por `desajustar`. Un error de IOL no tira la
    serie de BYMA: se anota como hueco.
    """
    primero = min(str(p.get("fechaHora") or "")[:10] for p in pts)
    try:
        inicio = date.fromisoformat(primero)
    except ValueError:
        return pts, [], None
    if inicio - desde <= timedelta(days=MARGEN_BYMA):
        return pts, [], None
    previos, huecos_, err = _serie_iol(iol, mercado, sim, desde,
                                       inicio - timedelta(days=1))
    if err and not previos:
        huecos_ = huecos_ or [[desde.isoformat(),
                               (inicio - timedelta(days=1)).isoformat()]]
    for p in previos:
        p["_fuente"] = "iol"
    return previos + pts, huecos_, None


def _serie_iol(iol, mercado, sim, desde, hasta):
    """La serie de IOL `sinAjustar`, partida en tramos si hace falta."""
    from iol import IOLError

    def pedir(d0, d1):
        # El `hasta` de IOL es excluyente: pedido igual al `desde` vuelve
        # vacio, y cada tramo perdia su ultimo dia.
        pts = iol.serie(mercado, sim, d0.isoformat(),
                        (d1 + timedelta(days=1)).isoformat()) or []
        return [p for p in pts
                if d0.isoformat() <= str(p.get("fechaHora") or "")[:10]
                <= d1.isoformat()]

    try:
        return pedir(desde, hasta), [], None
    except IOLError as e:
        if getattr(e, "status", None) == 429 or "429" in str(e)[:4]:
            return [], [], str(e)[:200]
        primer_error = str(e)[:200]
    except Exception as e:
        return [], [], str(e)[:200]

    puntos, huecos_ = [], []
    d0 = desde
    while d0 <= hasta:
        fin_mes = min(RF._sumar_meses(date(d0.year, d0.month, 1), 1)
                      - timedelta(days=1), hasta)
        try:
            puntos += pedir(d0, fin_mes)
        except Exception as e:
            if "429" in str(e)[:40]:
                huecos_.append([d0.isoformat(), hasta.isoformat()])
                return puntos, huecos_, str(e)[:200]
            s0 = d0
            while s0 <= fin_mes:
                s1 = min(s0 + timedelta(days=6), fin_mes)
                try:
                    puntos += pedir(s0, s1)
                except Exception:
                    # una semana que falla se pide de a un dia: cada dia
                    # suelto responde aunque la semana entera no
                    for i in range((s1 - s0).days + 1):
                        dia = s0 + timedelta(days=i)
                        if dia.weekday() >= 5:
                            continue
                        try:
                            puntos += pedir(dia, dia)
                        except Exception as e3:
                            huecos_.append([dia.isoformat(), dia.isoformat()])
                            log.warning("histórico %s %s: %s", sim, dia,
                                        str(e3)[:120])
                s0 = s1 + timedelta(days=1)
        d0 = fin_mes + timedelta(days=1)
    err = None if puntos else primer_error
    return puntos, huecos_, err


def completar(iol, tareas=None):
    """Rellena lo que devuelve sin_serie() y rearma los desvios."""
    tareas = sin_serie() if tareas is None else tareas
    total = 0
    intentos = _leer_estado("hist_atras")
    with _lock:
        progreso.update({"total": len(tareas), "hechas": 0, "puntos": 0})
    for sim, d0, d1 in tareas:
        progreso["actual"] = sim
        try:
            if d1 is None:
                n = reconstruir(iol, sim, desde=d0)
            else:
                n = reconstruir(iol, sim, desde=d0, hasta=d1, forzar=True,
                                marcar=False)
                primera = db.conn().execute(
                    "SELECT MIN(fecha) AS f FROM bono_hist WHERE simbolo=?",
                    (sim,)).fetchone()["f"]
                intentos[sim] = primera
                db.set_estado("hist_atras", json.dumps(intentos))
            total += n
        except Exception as e:
            log.warning("histórico %s: %s", sim, e)
            _anotar(sim, [], str(e)[:200])
        progreso["hechas"] += 1
        progreso["puntos"] = total
    if total:
        try:
            import curva as CU
            CU.reconstruir()
        except Exception as e:
            log.warning("residuos: %s", e)
    return total


def en_fondo(iol, simbolo=None, forzar=False):
    """Corre la reconstruccion en un hilo aparte y vuelve enseguida.

    Dentro de un pedido web, recalcular todo tardaba mas que el tiempo
    que el ingress de Home Assistant espera: la pantalla decia que habia
    fallado mientras el trabajo seguia. Ahora el pedido solo lo arranca
    y el avance se consulta aparte.
    """
    if progreso["corriendo"]:
        return False

    def trabajo():
        from datetime import datetime as _dt
        progreso.update({"corriendo": True, "inicio": _dt.now().isoformat(
            timespec="seconds"), "fin": None, "error": None,
            "hechas": 0, "total": 0, "puntos": 0, "actual": None})
        try:
            if forzar:
                bonos_cfg, _ = BO.cargar()
                esps = BO.especies()
                objetivo = [simbolo] if simbolo else sorted(esps)
                tareas = []
                for s in objetivo:
                    info = esps.get(s)
                    cfg = bonos_cfg.get(info["cronograma"]) if info else None
                    if cfg and reconstruible(cfg, info):
                        tareas.append((s, inicio_de(cfg), None))
                # AL30 y AL30D primero: de ellas sale el MEP de cada dia
                # con el que se convierten los hard dollar en pesos.
                tareas.sort(key=lambda t: (t[0] not in ("AL30", "AL30D"),
                                           t[0]))
                progreso["total"] = len(tareas)
                total = 0
                for s, d0, _ in tareas:
                    progreso["actual"] = s
                    try:
                        total += reconstruir(iol, s, desde=d0, forzar=True)
                    except Exception as e:
                        _anotar(s, [], str(e)[:200])
                    progreso["hechas"] += 1
                    progreso["puntos"] = total
                import curva as CU
                CU.reconstruir()
            else:
                completar(iol)
        except Exception as e:
            log.warning("reconstruccion en fondo: %s", e)
            progreso["error"] = str(e)[:200]
        finally:
            progreso["corriendo"] = False
            progreso["actual"] = None
            progreso["fin"] = _dt.now().isoformat(timespec="seconds")

    threading.Thread(target=trabajo, daemon=True, name="hist-fondo").start()
    return True


def agregar_hoy(cotizaciones, mep=None, f=None):
    """Un punto por día con el cierre de la rueda."""
    init()
    f = f or date.today()
    bonos_cfg, _ = BO.cargar()
    esps = BO.especies()
    filas = []

    for sim, info in esps.items():
        c = cotizaciones.get(sim)
        if not c:
            continue
        precio = c.get("ultimo") or c.get("ref")
        cfg = bonos_cfg.get(info["cronograma"])
        if not cfg or not precio:
            continue
        p = calcular_punto(sim, f, precio, cfg, info, mep)
        if p:
            filas.append(p)

    return _guardar(filas)


def serie(simbolo, desde=None, hasta=None):
    q = "SELECT fecha, precio, tir, md, residual FROM bono_hist WHERE simbolo=?"
    args = [simbolo]
    if desde:
        q += " AND fecha >= ?"
        args.append(desde if isinstance(desde, str) else desde.isoformat())
    if hasta:
        q += " AND fecha <= ?"
        args.append(hasta if isinstance(hasta, str) else hasta.isoformat())
    q += " ORDER BY fecha"
    return [dict(r) for r in db.conn().execute(q, args)]


def resumen():
    r = db.conn().execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT simbolo) esp, "
        "MIN(fecha) a, MAX(fecha) b FROM bono_hist").fetchone()
    return {"filas": r["n"], "especies": r["esp"],
            "desde": r["a"], "hasta": r["b"],
            "ultimo_backfill": db.get_estado("hist_bonos_hasta")}


def reconstruir_precios(iol, simbolos, desde=None, hasta=None,
                        mercado="bCBA"):
    """Baja solo el precio de cierre, sin calcular nada mas.

    `reconstruir` saltea a proposito los hard dollar que cotizan en pesos:
    su TIR necesita el MEP de cada dia y no lo tenemos hacia atras. Pero
    para el MEP no hace falta la TIR, solo el precio de las dos puntas:
    AL30 en pesos sobre AL30D en dolares. De ahi este camino aparte.

    No pisa lo que ya esta: si un dia tiene punto completo -con TIR, MD y
    residual- se respeta. Esto solo rellena los dias que faltan, con el
    precio y el resto en blanco.
    """
    init()
    desde = desde or DESDE
    hasta = hasta or date.today()
    if isinstance(desde, str):
        desde = date.fromisoformat(desde)
    if isinstance(hasta, str):
        hasta = date.fromisoformat(hasta)

    c = db.conn()
    total, detalle = 0, {}
    for sim in simbolos:
        sim = (sim or "").strip().upper()
        if not sim:
            continue
        try:
            serie_iol = iol.serie(mercado, sim, desde.isoformat(),
                                  hasta.isoformat())
        except Exception as e:
            log.warning("serie de %s: %s", sim, e)
            detalle[sim] = {"error": str(e)}
            continue

        filas = []
        for p in (serie_iol or []):
            f = str(p.get("fechaHora") or p.get("fecha") or "")[:10]
            precio = p.get("ultimoPrecio") or p.get("cierre")
            if not f or not precio:
                continue
            filas.append((sim, f, float(precio)))
        if not filas:
            detalle[sim] = {"puntos": 0}
            continue
        # INSERT OR IGNORE: el punto completo, si existe, manda.
        c.executemany("INSERT OR IGNORE INTO bono_hist (simbolo, fecha, "
                      "precio) VALUES (?,?,?)", filas)
        c.commit()
        detalle[sim] = {"puntos": len(filas),
                        "desde": min(f for _, f, _ in filas),
                        "hasta": max(f for _, f, _ in filas)}
        total += len(filas)
    return {"puntos": total, "detalle": detalle}
