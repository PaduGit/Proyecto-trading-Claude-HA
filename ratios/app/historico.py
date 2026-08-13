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
    PRIMARY KEY (simbolo, fecha)
);
CREATE INDEX IF NOT EXISTS ix_bh_simbolo ON bono_hist(simbolo, fecha);
"""


def init():
    c = db.conn()
    c.executescript(ESQUEMA)
    c.commit()


def _guardar(filas):
    if not filas:
        return 0
    c = db.conn()
    c.executemany(
        "INSERT OR REPLACE INTO bono_hist "
        "(simbolo, fecha, precio, tir, md, duration, residual, cer) "
        "VALUES (?,?,?,?,?,?,?,?)", filas)
    c.commit()
    return len(filas)


def _cer_de(f):
    """CER que aplicaba en esa fecha, con el rezago de diez hábiles."""
    try:
        return CER.valor(CER._restar_habiles(f, CER.REZAGO_HABILES))
    except Exception:
        return None


def calcular_punto(simbolo, f, precio, cfg, info, mep=None):
    """TIR y duration de un bono en una fecha, con los datos de ese día."""
    if not precio or precio <= 0:
        return None

    es_cer = (cfg.get("ajuste") or "").lower() == "cer"
    coef = None

    if es_cer:
        base = cfg.get("cer_base") or CER.base_de(cfg.get("emision"))
        coef = _cer_de(f)
        if not base or not coef:
            return None
        p = precio / (coef / base)
    elif info["moneda"] == "USD":
        p = precio
    else:
        # bono hard dollar cotizando en pesos: sin MEP de esa fecha no
        # se puede convertir, así que ese punto se omite
        if not mep:
            return None
        p = precio / mep

    filas = RF.flujo(cfg, f)
    if not filas:
        return None
    r = RF.tir(p, cfg, f, filas)
    if r is None:
        return None
    mac, md = RF.duration(p, cfg, f, r, filas)
    return (simbolo, f.isoformat(), precio, r * 100, md, mac,
            RF.residual(cfg, f), coef)


def reconstruir(iol, simbolo=None, desde=None, hasta=None, mercado="bCBA"):
    """Baja los cierres de IOL y calcula la serie. Idempotente."""
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
        # dolarizadas (D y C) y las ajustables por CER
        if info["moneda"] not in ("USD", "CER"):
            continue

        ultimo = db.conn().execute(
            "SELECT MAX(fecha) f FROM bono_hist WHERE simbolo=?", (sim,)
        ).fetchone()["f"]
        arranque = desde
        if ultimo:
            arranque = date.fromisoformat(ultimo) + timedelta(days=1)
        if arranque > hasta:
            continue

        emision = RF._fecha(cfg["emision"])
        if arranque < emision:
            arranque = emision

        try:
            serie = iol.serie(mercado, sim, arranque.isoformat(),
                              hasta.isoformat())
        except Exception as e:
            log.warning("histórico %s: %s", sim, e)
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

    db.set_estado("hist_bonos_hasta", hasta.isoformat())
    return total


def sin_serie():
    """Especies con cronograma pero sin ningún punto guardado.

    Sirve para reconstruir solo lo que falta: un bono agregado después
    del primer backfill se completa solo, sin rehacer todo."""
    esps = BO.especies()
    ya = {r["simbolo"] for r in db.conn().execute(
        "SELECT DISTINCT simbolo FROM bono_hist")}
    return [s for s, i in esps.items()
            if s not in ya and i["moneda"] in ("USD", "CER")]


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
