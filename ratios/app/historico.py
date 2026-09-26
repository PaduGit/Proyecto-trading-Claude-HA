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

    filas = RF.flujo(cfg, f, tasa_var=tv)
    if not filas:
        return None
    r = RF.tir(p, cfg, f, filas)
    if r is None:
        return None
    mac, md = RF.duration(p, cfg, f, r, filas)
    return (simbolo, f.isoformat(), precio, r * 100, md, mac,
            RF.residual(cfg, f), coef, tv)


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

    for sim in objetivo:
        info = esps.get(sim)
        if not info:
            continue
        cfg = bonos_cfg.get(info["cronograma"])
        if not cfg:
            continue

        # los hard dollar que cotizan en pesos necesitan el MEP de cada
        # día, que no tenemos hacia atrás: se reconstruyen las especies
        # dolarizadas (D y C) y las ajustables por CER. Los bonos que
        # rinden en pesos tampoco necesitan MEP, asi que entran igual.
        if not reconstruible(cfg, info):
            continue

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
            p = calcular_punto(sim, f, precio, cfg, info)
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


def reconstruible(cfg, info):
    """Si la TIR de una especie se puede calcular hacia atras.

    Los hard dollar que cotizan en pesos necesitan el MEP de cada dia y
    no lo tenemos: entran las especies dolarizadas (D y C), las CER y
    las que rinden en pesos, duales incluidos.
    """
    en_pesos = (not (cfg.get("ajuste") or "")
                and (cfg.get("moneda") or "").upper() == "ARS")
    return info["moneda"] in ("USD", "CER") or en_pesos


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
    from iol import IOLError

    def pedir(d0, d1):
        return iol.serie(mercado, sim, d0.isoformat(), d1.isoformat()) or []

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
                except Exception as e2:
                    huecos_.append([s0.isoformat(), s1.isoformat()])
                    log.warning("histórico %s %s a %s: %s", sim, s0, s1,
                                str(e2)[:120])
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
