"""Diario de trading: cada posicion desde que se abre hasta que vuelve a cero.

Tres fuentes, segun el broker:

- **boleto** (Veta): los boletos aplicados, omitidos o descartados. Precio, gastos y
  fecha reales.
- **iol** (las cuentas de IOL): `/api/v2/operaciones`. Precio real
  (`precioOperado`, `montoOperado`); la API no trae las comisiones, asi
  que los gastos se estiman con la tabla de costos.
- **tenencia** (ECO y los demas sin API): los movimientos confirmados de
  la diferencia entre dos fotos. Aproximado: el precio es el de la foto,
  no el ejecutado, y dos operaciones entre las mismas fotos se ven como
  una. Un broker con boletos usa esta fuente solo antes de su primer
  boleto.

Cada operacion es una fila de `diario_op`. Las posiciones no se guardan:
se arman al leer, por broker y especie, en orden. El resultado se mide
contra el PPC con gastos; en dolares, cada movimiento al MEP de su dia.
El acierto se mide en dolares.

Lo que el diario agrega a cada operacion: estrategia, motivo de la
venta, comentario, el enlace de rotacion (una venta cuyo neto entro en
una compra) y la copia del stop y objetivo de Gestion vigentes al
comprar, para el R multiplo aunque despues se muevan.

Nada de esto toca la tenencia ni el ledger de las estrategias.
"""

import logging
from datetime import date, datetime, timedelta

import db

log = logging.getLogger("ratios.diario")

MOTIVOS = ("stop", "objetivo", "propio", "rotacion", "sin motivo")
# Tolerancia del stop respetado: salir hasta 1% debajo cuenta como
# respetado (la venta se ejecuta en la punta, no en el nivel exacto).
TOL_STOP = 0.01
# La copia de los niveles se toma solo para compras recientes: una compra
# de hace meses que entra en la primera carga no tenia estos niveles.
DIAS_COPIA = 7
# Cuanto antes de la operacion se busca la alerta que la precedio.
DIAS_ALERTA = 5
# Ventana para unir una venta y una compra como rotacion.
DIAS_ROTACION = 5
# "Para completar" pide motivo y estrategia solo desde esta fecha
# (decidido el 22/10: lo anterior es historia de IOL desde 2017). Lo viejo
# se puede completar desde el detalle.
DESDE_PENDIENTES = "2026-01-01"
NO_OPERA = ("moneda",)
MONEDAS = ("ARS", "USD", "MEP", "CCL", "CAUCION", "US$", "PESOS", "DOLARES")

_listo = False


def _asegurar():
    global _listo
    if _listo:
        return
    c = db.conn()
    c.executescript("""
CREATE TABLE IF NOT EXISTS diario_op (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ref        TEXT NOT NULL UNIQUE,   -- bol:<n> | iol:<broker>:<numero> | mov:<id>:<lado>
  fuente     TEXT NOT NULL,          -- boleto | iol | tenencia
  broker     TEXT NOT NULL,
  simbolo    TEXT NOT NULL,
  crudo      TEXT,                   -- el simbolo tal como vino (AO29D)
  fecha      TEXT NOT NULL,          -- de la operacion; en tenencia, la foto
  lado       TEXT NOT NULL,          -- compra | venta
  cantidad   REAL NOT NULL,
  precio     REAL,                   -- en la base en que cotiza
  base       REAL,
  moneda     TEXT NOT NULL DEFAULT 'ARS',
  bruto      REAL,                   -- en `moneda`, sin gastos
  gastos     REAL,                   -- en `moneda`, con IVA
  gastos_est INTEGER NOT NULL DEFAULT 0,
  mep        REAL,
  estrategia_id INTEGER,
  motivo     TEXT,
  nota       TEXT,
  rot_id     INTEGER,                -- venta -> la compra en la que entro
  stop_ent   REAL,
  obj_ent    REAL,
  modo_ent   TEXT,
  creado     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_diario_pos ON diario_op(broker, simbolo, fecha);
""")
    c.commit()
    _listo = True


def init():
    _asegurar()


# -- utilidades ----------------------------------------------------------

def _ahora():
    return datetime.now().isoformat(timespec="seconds")


def _mep(fecha):
    try:
        import bonos as BO
        return BO.mep_al(str(fecha)[:10])
    except Exception:
        return None


def _gastos_est(cfg, tipo, bruto):
    """Gastos estimados de una pata con la tabla de costos de la app."""
    if not bruto:
        return 0.0
    import costos as CO
    inst = (tipo or "acciones").lower()
    if inst in ("fci", "moneda"):
        return 0.0
    try:
        p = CO.pct((cfg or {}).get("comisiones") or {}, inst,
                   (cfg or {}).get("derechos_mercado"), (cfg or {}).get("iva_pct") or 0)
    except Exception:
        p = 0.0
    return round(abs(bruto) * p, 2)


def _tipo(sim):
    r = db.conn().execute("SELECT tipo FROM tenencia WHERE simbolo=? AND tipo IS NOT NULL "
                          "LIMIT 1", (sim,)).fetchone()
    if not r:
        r = db.conn().execute("SELECT tipo FROM tenencia_hist WHERE simbolo=? AND tipo IS NOT "
                              "NULL ORDER BY ts DESC LIMIT 1", (sim,)).fetchone()
    if r:
        return r["tipo"]
    try:
        import bonos as BO
        if sim in BO.especies():
            return "bonos"
    except Exception:
        pass
    return None


def _base(sim):
    b = db.base_cotizacion(sim)
    if b:
        return float(b)
    return 100.0 if _tipo(sim) in ("bonos", "letras", "on", "bcra") else 1.0


def _niveles():
    try:
        import gestion as GE
        return GE.config()["niveles"] or {}
    except Exception:
        return {}


def _insertar(c, op, niveles=None):
    """Inserta si la referencia no existe. Devuelve True si entro."""
    if c.execute("SELECT 1 FROM diario_op WHERE ref=?", (op["ref"],)).fetchone():
        return False
    stop = obj = modo = None
    if op["lado"] == "compra" and niveles is not None:
        try:
            dias = (date.today() - date.fromisoformat(op["fecha"][:10])).days
        except ValueError:
            dias = 999
        n = niveles.get(op["simbolo"])
        if n and dias <= DIAS_COPIA:
            stop, obj, modo = n.get("stop"), n.get("obj"), n.get("modo") or "precio"
    c.execute(
        "INSERT INTO diario_op (ref, fuente, broker, simbolo, crudo, fecha, lado, cantidad, "
        "precio, base, moneda, bruto, gastos, gastos_est, mep, estrategia_id, motivo, "
        "stop_ent, obj_ent, modo_ent, creado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (op["ref"], op["fuente"], op["broker"], op["simbolo"], op.get("crudo"), op["fecha"],
         op["lado"], op["cantidad"], op.get("precio"), op.get("base"), op.get("moneda") or "ARS",
         op.get("bruto"), op.get("gastos"), 1 if op.get("gastos_est") else 0,
         op.get("mep") or _mep(op["fecha"]), op.get("estrategia_id"), op.get("motivo"),
         stop, obj, modo, _ahora()))
    return True


# -- fuente: boletos -----------------------------------------------------

def sincronizar_boletos():
    """Los boletos aplicados, omitidos y descartados: omitir o descartar
    solo evita tocar la tenencia, la operacion existio (decidido el
    21/10). Los pendientes entran al confirmarlos, con el motivo elegido."""
    _asegurar()
    import boletos as BOL
    BOL._asegurar()
    c = db.conn()
    niv = _niveles()
    n = 0
    for b in c.execute("SELECT * FROM boleto WHERE estado IN ('aplicado','omitido','descartado') "
                       "AND tipo IN ('compra','venta') AND cantidad > 0").fetchall():
        sim = (b["simbolo"] or "").upper()
        base = _base(sim)
        bruto = b["cantidad"] * b["precio"] / base if b["precio"] is not None else None
        gastos = (b["gastos"] or 0) + (b["iva"] or 0)
        motivo = b["nota"] if (b["tipo"] == "venta" and b["nota"] in MOTIVOS) else None
        if _insertar(c, {"ref": "bol:%s" % b["bol"], "fuente": "boleto", "broker": b["broker"],
                         "simbolo": sim, "crudo": sim, "fecha": b["fecha"] or b["liquida"] or "",
                         "lado": b["tipo"], "cantidad": b["cantidad"], "precio": b["precio"],
                         "base": base, "moneda": "USD" if b["moneda"] == "USD" else "ARS",
                         "bruto": bruto, "gastos": round(gastos, 2), "gastos_est": False,
                         "estrategia_id": db._estrategia_de(sim), "motivo": motivo}, niv):
            n += 1
    c.commit()
    return n


def _primer_boleto(broker):
    import boletos as BOL
    BOL._asegurar()
    r = db.conn().execute("SELECT MIN(fecha) f FROM boleto WHERE broker=? AND tipo IN "
                          "('compra','venta')", (broker,)).fetchone()
    return r["f"] if r and r["f"] else None


# -- fuente: diferencia entre tenencias ---------------------------------

def sincronizar_tenencia(directos, broker_boletos=None, cfg=None):
    """Los movimientos confirmados de los brokers sin fuente directa.

    `directos` son las cuentas de IOL: esas salen de la API desde la
    primera compra de su tenencia y no se toman de aca. El broker de los
    boletos se toma de aca solo antes de su primer boleto.
    """
    _asegurar()
    c = db.conn()
    corte_bol = _primer_boleto(broker_boletos) if broker_boletos else None
    niv = _niveles()
    n = 0
    filas = c.execute("SELECT * FROM mov_propuesto WHERE estado='confirmado' "
                      "ORDER BY hasta, id").fetchall()
    for m in filas:
        if m["broker"] in directos:
            continue
        if broker_boletos and m["broker"] == broker_boletos and corte_bol and m["hasta"] >= corte_bol:
            continue
        if (m["signo"] or 1) < 0:
            continue    # lanzadas y saldos deudores: no son compras ni ventas
        patas = []
        if m["sale"] and m["cant_sale"]:
            patas.append(("venta", m["sale"], m["cant_sale"], m["precio_sale"]))
        if m["entra"] and m["cant_entra"]:
            patas.append(("compra", m["entra"], m["cant_entra"], m["precio_entra"]))
        ids = {}
        for lado, sim, cant, precio in patas:
            sim = sim.upper()
            tipo = _tipo(sim)
            if sim in MONEDAS or (tipo or "").lower() in NO_OPERA:
                continue
            base = _base(sim)
            bruto = cant * precio / base if precio else None
            ref = "mov:%s:%s" % (m["id"], lado)
            n += _insertar(c, {"ref": ref, "fuente": "tenencia", "broker": m["broker"],
                          "simbolo": sim, "crudo": sim, "fecha": m["hasta"], "lado": lado,
                          "cantidad": abs(cant), "precio": precio, "base": base,
                          "bruto": bruto, "gastos": _gastos_est(cfg, tipo, bruto) if bruto else None,
                          "gastos_est": True,
                          "estrategia_id": m["estrategia_id"] or db._estrategia_de(sim)}, niv)
            r = c.execute("SELECT id FROM diario_op WHERE ref=?", (ref,)).fetchone()
            ids[lado] = r["id"]
        if m["tipo"] == "rotacion" and "venta" in ids and "compra" in ids:
            c.execute("UPDATE diario_op SET rot_id=?, motivo=COALESCE(motivo,'rotacion') "
                      "WHERE id=? AND rot_id IS NULL", (ids["compra"], ids["venta"]))
    # Rotaciones entre brokers: dos propuestas unidas (retiro + aporte de
    # especies distintas).
    for m in c.execute("SELECT a.id ia, b.id ib FROM mov_propuesto a JOIN mov_propuesto b "
                       "ON b.unido_a = a.id WHERE a.estado='confirmado' AND b.estado='confirmado'"):
        va = c.execute("SELECT id, lado, simbolo FROM diario_op WHERE ref IN (?,?,?,?)",
                       ("mov:%s:venta" % m["ia"], "mov:%s:compra" % m["ia"],
                        "mov:%s:venta" % m["ib"], "mov:%s:compra" % m["ib"])).fetchall()
        v = [x for x in va if x["lado"] == "venta"]
        k = [x for x in va if x["lado"] == "compra"]
        if len(v) == 1 and len(k) == 1 and v[0]["simbolo"] != k[0]["simbolo"]:
            c.execute("UPDATE diario_op SET rot_id=?, motivo=COALESCE(motivo,'rotacion') "
                      "WHERE id=? AND rot_id IS NULL", (k[0]["id"], v[0]["id"]))
    c.commit()
    return n


# -- fuente: IOL ---------------------------------------------------------

def _operaciones(cli, desde, hasta):
    """Las operaciones de un rango, de a un año: la primera carga de una
    cuenta abierta en 2017 son nueve años y un pedido tan largo puede
    vencer o venir cortado. Las repetidas en los bordes se filtran por
    numero."""
    out, vistos = [], set()
    d = date.fromisoformat(desde[:10])
    fin = date.fromisoformat(hasta[:10])
    while d <= fin:
        h = min(fin, d + timedelta(days=365))
        r = cli.operaciones(d.isoformat(), h.isoformat())
        if not isinstance(r, list):
            raise RuntimeError("IOL devolvió una respuesta inesperada")
        for o in r:
            k = o.get("numero")
            if k is None or k not in vistos:
                out.append(o)
                vistos.add(k)
        d = h + timedelta(days=1)
    return out


def _corte_inicial(cli, broker):
    """Desde cuando importar la primera vez: la primera compra de las
    tenencias actuales del broker (el alta de la posicion vigente).

    Las que no tienen fecha de alta se reconstruyen con las operaciones de
    los ultimos cinco años. Devuelve (corte, operaciones ya bajadas o
    None)."""
    import operaciones as OPS
    ten = [t for t in db.tenencias(broker)
           if (t.get("tipo") or "").lower() not in NO_OPERA and t["simbolo"] not in MONEDAS
           and (t.get("cantidad") or 0) > 0]
    altas = [t["fecha_alta"][:10] for t in ten if t.get("fecha_alta")]
    if ten and len(altas) == len(ten):
        return min(altas), None
    desde = (date.today() - timedelta(days=5 * 365)).isoformat()
    ops = _operaciones(cli, desde, date.today().isoformat())
    rec = OPS.reconstruir(ops, [t["simbolo"] for t in ten])
    for t in ten:
        b = OPS.simbolo_base(t["simbolo"], set(rec))
        if b in rec and rec[b].get("fecha_alta"):
            altas.append(rec[b]["fecha_alta"])
    return (min(altas) if altas else date.today().isoformat()), ops


def importar_iol(cli, broker, cfg=None):
    """Baja las operaciones de una cuenta y guarda las nuevas.

    La primera vez, desde la primera compra de las tenencias actuales;
    despues, desde la ultima importacion menos tres dias (las repetidas
    no entran: la referencia es el numero de operacion).
    """
    import operaciones as OPS
    _asegurar()
    k = "diario_iol:" + broker
    ult = db.get_estado(k)
    hoy = date.today().isoformat()
    ops = None
    if ult:
        desde = (date.fromisoformat(ult[:10]) - timedelta(days=3)).isoformat()
    else:
        desde, ops = _corte_inicial(cli, broker)
        db.set_estado("diario_iol_corte:" + broker, desde)
    if ops is None:
        ops = _operaciones(cli, desde, hoy)
    c = db.conn()
    pares = [(x, o) for x, o in ((OPS.limpiar(o), o) for o in ops)
             if x and x["fecha"] >= desde and x.get("numero")]
    limpias = [x for x, _ in pares]
    vistos = {x["simbolo"] for x in limpias} | {t["simbolo"] for t in db.tenencias(broker)}
    niv = _niveles()
    nuevas = 0
    for x, o in pares:
        usd = OPS.en_dolares(x["simbolo_crudo"], vistos)
        sim = OPS.simbolo_base(x["simbolo"], vistos)
        base = OPS.base_de(x) or _base(sim)
        tipo = _tipo(sim)
        fecha = str(o.get("fechaOperada") or o.get("fechaOrden") or x["fecha"])[:19]
        bruto = x["monto"] if x["monto"] else (x["cantidad"] * x["precio"] / base
                                                if x["precio"] else None)
        if _insertar(c, {"ref": "iol:%s:%s" % (broker, x["numero"]), "fuente": "iol",
                         "broker": broker, "simbolo": sim, "crudo": x["simbolo_crudo"],
                         "fecha": fecha, "lado": "compra" if x["signo"] > 0 else "venta",
                         "cantidad": x["cantidad"], "precio": x["precio"], "base": base,
                         "moneda": "USD" if usd else "ARS", "bruto": bruto,
                         "gastos": _gastos_est(cfg, tipo, bruto), "gastos_est": True,
                         "estrategia_id": db._estrategia_de(sim)}, niv):
            nuevas += 1
    c.commit()
    db.set_estado(k, _ahora())
    db.set_estado("diario_iol_error:" + broker, "")
    return {"broker": broker, "desde": desde, "operaciones": len(limpias), "nuevas": nuevas}


# -- rotaciones ----------------------------------------------------------

def vincular_rotaciones():
    """Une venta y compra cuando el ledger de una estrategia registro una
    rotacion (boletos marcados como rotacion, o movimientos confirmados
    en las cuentas de IOL). Solo si hay una venta y una compra sin unir
    en la ventana."""
    _asegurar()
    c = db.conn()
    n = 0
    for r in c.execute("SELECT ticker_de, ticker_a, ts FROM estrategia_mov WHERE tipo='rotacion' "
                       "AND ticker_de IS NOT NULL AND ticker_a IS NOT NULL").fetchall():
        f = (r["ts"] or "")[:10]
        if not f:
            continue
        try:
            d0 = (date.fromisoformat(f) - timedelta(days=DIAS_ROTACION)).isoformat()
        except ValueError:
            continue
        hasta = f + "T23:59:59"
        v = c.execute("SELECT id FROM diario_op WHERE lado='venta' AND simbolo=? AND fecha>=? "
                      "AND fecha<=? AND rot_id IS NULL", (r["ticker_de"], d0, hasta)).fetchall()
        k = c.execute("SELECT id FROM diario_op WHERE lado='compra' AND simbolo=? AND fecha>=? "
                      "AND fecha<=? AND id NOT IN (SELECT rot_id FROM diario_op WHERE rot_id "
                      "IS NOT NULL)", (r["ticker_a"], d0, hasta)).fetchall()
        if len(v) == 1 and len(k) == 1:
            c.execute("UPDATE diario_op SET rot_id=?, motivo=COALESCE(motivo,'rotacion') WHERE id=?",
                      (k[0]["id"], v[0]["id"]))
            n += 1
    c.commit()
    return n


def sincronizar_local(directos, broker_boletos=None, cfg=None):
    """Todo lo que no pide nada afuera: boletos, movimientos confirmados y
    rotaciones. Corre al abrir el diario."""
    out = {"boletos": 0, "tenencia": 0, "rotaciones": 0}
    try:
        out["boletos"] = sincronizar_boletos()
    except Exception as e:
        log.warning("diario boletos: %s", e)
    try:
        out["tenencia"] = sincronizar_tenencia(set(directos), broker_boletos, cfg)
    except Exception as e:
        log.warning("diario tenencia: %s", e)
    try:
        out["rotaciones"] = vincular_rotaciones()
    except Exception as e:
        log.warning("diario rotaciones: %s", e)
    return out


def sincronizar(cuentas, broker_boletos=None, cfg=None):
    """La revision diaria: IOL por API y despues lo local. `cuentas` es
    [(nombre, cliente)]."""
    res = []
    for nombre, cli in cuentas:
        try:
            with cli.como("diario"):
                res.append(importar_iol(cli, nombre, cfg))
        except Exception as e:
            db.set_estado("diario_iol_error:" + nombre, str(e)[:300])
            log.warning("diario %s: %s", nombre, e)
            res.append({"broker": nombre, "error": str(e)})
    loc = sincronizar_local([n for n, _ in cuentas], broker_boletos, cfg)
    db.set_estado("diario_revision", _ahora())
    return {"iol": res, "local": loc}


# -- posiciones ----------------------------------------------------------

def _ajustar(ops, sim):
    """Lleva cantidad y precio a la escala de hoy si hubo un evento
    societario despues de la operacion. Lo pagado no cambia."""
    try:
        evs = [e for e in db.eventos(sim) if e.get("factor") and e["factor"] != 1]
    except Exception:
        evs = []
    for o in ops:
        o["q"], o["px"] = o["cantidad"], o["precio"]
        for e in evs:
            if o["fecha"][:10] < e["fecha"]:
                o["q"] *= float(e["factor"])
                if o["px"]:
                    o["px"] /= float(e["factor"])
    return ops


def _pesos_dolares(o):
    """Bruto, gastos y neto en pesos y el neto en dolares de una operacion.
    El neto es lo que salio (compra) o entro (venta)."""
    if o["bruto"] is None:
        return None
    g = o["gastos"] or 0
    neto = o["bruto"] + g if o["lado"] == "compra" else o["bruto"] - g
    mep = o["mep"]
    if o["moneda"] == "USD":
        return {"neto": neto * mep if mep else None, "neto_usd": neto,
                "bruto": o["bruto"] * mep if mep else None, "gastos": g * mep if mep else None}
    return {"neto": neto, "neto_usd": neto / mep if mep else None,
            "bruto": o["bruto"], "gastos": g}


def _alertas(sim, fecha, lado):
    """La alerta mas reciente sobre la especie en los dias previos."""
    try:
        d0 = (date.fromisoformat(fecha[:10]) - timedelta(days=DIAS_ALERTA)).isoformat()
    except ValueError:
        return None
    hasta = fecha[:10] + "T23:59:59"
    c = db.conn()
    if lado == "compra":
        r = c.execute("SELECT id, ts, tipo, mensaje FROM alertas WHERE ts>=? AND ts<=? AND ("
                      "(tipo='curva_barato' AND alias=?) OR (tipo='canje' AND alias<>? AND "
                      "mensaje LIKE ?)) ORDER BY ts DESC LIMIT 1",
                      (d0, hasta, sim, sim, "%" + sim + "%")).fetchone()
    else:
        r = c.execute("SELECT id, ts, tipo, mensaje FROM alertas WHERE ts>=? AND ts<=? AND alias=? "
                      "AND tipo IN ('nivel_stop','nivel_objetivo','curva_caro','canje') "
                      "ORDER BY ts DESC LIMIT 1", (d0, hasta, sim)).fetchone()
    if not r:
        return None
    txt = (r["mensaje"] or "").replace("<b>", "").replace("</b>", "").strip().split("\n")[0]
    return {"id": r["id"], "ts": r["ts"], "tipo": r["tipo"], "texto": txt[:160]}


def posiciones(precios=None, mep_hoy=None):
    """Arma las posiciones a partir de las operaciones.

    `precios`: precio actual por simbolo (en pesos, en la base en que
    cotiza) para el resultado latente de las abiertas. `mep_hoy` para
    llevarlo a dolares.
    """
    _asegurar()
    c = db.conn()
    precios = precios or {}
    ops = [dict(r) for r in c.execute("SELECT * FROM diario_op ORDER BY broker, simbolo, fecha, id")]
    # MEP faltante: se completa si la serie ya llega
    for o in ops:
        if o["mep"] is None:
            m = _mep(o["fecha"])
            if m:
                o["mep"] = m
                c.execute("UPDATE diario_op SET mep=? WHERE id=?", (m, o["id"]))
    c.commit()
    estr = {e["id"]: e["nombre"] for e in db.estrategias(incluir_cerradas=True)}
    niv_hoy = _niveles()
    grupos = {}
    for o in ops:
        grupos.setdefault((o["broker"], o["simbolo"]), []).append(o)

    pos, de_op = [], {}
    for (broker, sim), lista in grupos.items():
        _ajustar(lista, sim)
        actual, q = None, 0.0
        for o in lista:
            if o["lado"] == "compra":
                if actual is None or q <= 1e-9:
                    actual = {"broker": broker, "simbolo": sim, "ops": [], "incompleta": False}
                    pos.append(actual)
                    q = 0.0
                actual["ops"].append(o)
                q += o["q"]
            else:
                if actual is None or q <= 1e-9:
                    # Venta sin compras registradas: la posicion empezo
                    # antes de lo importado o entro por transferencia.
                    actual = {"broker": broker, "simbolo": sim, "ops": [], "incompleta": True}
                    pos.append(actual)
                    q = 0.0
                if o["q"] > q + 1e-6:
                    actual["incompleta"] = True
                actual["ops"].append(o)
                q = max(0.0, q - o["q"])
            de_op[o["id"]] = actual
        # nada mas: la ultima puede quedar abierta

    # Una abierta que tiene en la cuenta mas de lo que suman sus
    # operaciones empezo antes de lo registrado (la diferencia de tenencias
    # arranca con la primera foto; una transferencia no tiene compra).
    ten = {}
    for t in db.tenencias():
        ten[(t["broker"], t["simbolo"])] = ten.get((t["broker"], t["simbolo"]), 0) + (t["cantidad"] or 0)
    ultima = {}
    for p in pos:
        ultima[(p["broker"], p["simbolo"])] = p
    for k, p in ultima.items():
        q = sum(o["q"] if o["lado"] == "compra" else -o["q"] for o in p["ops"])
        if q > 1e-9 and ten.get(k, 0) > q * 1.01 + 1e-6:
            p["incompleta"] = True
        # Al reves: las operaciones dicen que sigue abierta y la cuenta ya
        # no la tiene. Salio por un vencimiento, un rescate, un canje o una
        # transferencia, que no son ventas: queda cerrada sin salida
        # registrada y fuera de las estadisticas.
        elif q > 1e-9 and ten.get(k, 0) <= 1e-9:
            p["sin_salida"] = True
    out = []
    for p in pos:
        d = _medir(p, precios, mep_hoy, niv_hoy)
        d["estrategia"] = estr.get(d["estrategia_id"])
        out.append(d)
    ids = {id(p): d for p, d in zip(pos, out)}
    # rotaciones: de la venta a la posicion de la compra
    for p, d in zip(pos, out):
        for o in p["ops"]:
            if o["lado"] == "venta" and o["rot_id"] and o["rot_id"] in de_op:
                dst = ids[id(de_op[o["rot_id"]])]
                d["rot_a"] = {"id": dst["id"], "simbolo": dst["simbolo"], "broker": dst["broker"]}
                dst["rot_de"] = {"id": d["id"], "simbolo": d["simbolo"], "broker": d["broker"]}
    out.sort(key=lambda x: (x["abierta"], x["fecha_fin"] or x["fecha_ini"]), reverse=True)
    return out


def _medir(p, precios, mep_hoy, niv_hoy):
    ops = p["ops"]
    compras = [o for o in ops if o["lado"] == "compra"]
    ventas = [o for o in ops if o["lado"] == "venta"]
    q = costo = costo_u = res = res_u = 0.0
    costo_tot = costo_u_tot = 0.0
    sin_precio = sin_mep = False
    for o in ops:
        v = _pesos_dolares(o)
        if v is None or v["neto"] is None:
            # Sin precio, o en dolares sin el MEP del dia: no hay pesos
            # con que medir.
            sin_precio = True
            if v is not None:
                sin_mep = True
            if o["lado"] == "compra":
                q += o["q"]
            else:
                q = max(0.0, q - o["q"])
            continue
        if v["neto_usd"] is None:
            sin_mep = True
        if o["lado"] == "compra":
            q += o["q"]
            costo += v["neto"]
            costo_tot += v["neto"]
            if v["neto_usd"] is not None:
                costo_u += v["neto_usd"]
                costo_u_tot += v["neto_usd"]
        else:
            if q <= 1e-9:
                continue
            f = min(1.0, o["q"] / q)
            cs, csu = costo * f, costo_u * f
            res += v["neto"] - cs
            if v["neto_usd"] is not None:
                res_u += v["neto_usd"] - csu
            costo -= cs
            costo_u -= csu
            q = max(0.0, q - o["q"])
    sin_salida = bool(p.get("sin_salida"))
    abierta = q > 1e-9 and not sin_salida
    primera = compras[0] if compras else ops[0]
    ultima = ops[-1]
    base = primera.get("base") or 1.0
    fuentes = {o["fuente"] for o in ops}
    fuente = "tenencia" if "tenencia" in fuentes else ("iol" if "iol" in fuentes else "boleto")
    eid = next((o["estrategia_id"] for o in compras if o["estrategia_id"]), None) \
        or next((o["estrategia_id"] for o in ops if o["estrategia_id"]), None)
    if not eid and abierta:
        eid = db._estrategia_de(p["simbolo"])
    motivo = ventas[-1]["motivo"] if ventas and not abierta and not p.get("sin_salida") else None

    lat = lat_u = None
    if abierta and not sin_precio and not p["incompleta"]:
        px = precios.get(p["simbolo"])
        if px:
            v_act = q * px / (_base(p["simbolo"]) or base)
            lat = v_act - costo
            if mep_hoy and not sin_mep:
                lat_u = v_act / mep_hoy - costo_u
    # Compra y venta de la misma especie el mismo dia, una en pesos y la
    # otra en dolares: es una compra o venta de dolar MEP, no una posicion
    # (decidido el 22/10). Fuera de las estadisticas y de "Para completar".
    cambio = (bool(compras) and bool(ventas) and q <= 1e-9
              and len({o["fecha"][:10] for o in ops}) == 1
              and len({o["moneda"] for o in ops}) > 1)
    medible = not sin_precio and not p["incompleta"] and not cambio and not sin_salida

    # R: con la copia de los niveles de la primera compra, solo por precio
    stop = primera.get("stop_ent") if compras else None
    obj = primera.get("obj_ent") if compras else None
    modo = primera.get("modo_ent") if compras else None
    r = riesgo = None
    if compras and stop and (modo or "precio") == "precio" and primera["px"] and primera["moneda"] == "ARS":
        riesgo = compras[0]["q"] * (primera["px"] - stop) / base
        if riesgo > 0 and medible:
            r = (res / riesgo) if not abierta else (lat / riesgo if lat is not None else None)
    v_ars = [o for o in ventas if o["px"] and o["moneda"] == "ARS"]
    pxs = (sum(o["q"] * o["px"] for o in v_ars) / sum(o["q"] for o in v_ars)) if v_ars else None
    resp = None
    if not abierta and motivo == "stop" and stop and pxs and (modo or "precio") == "precio":
        resp = pxs >= stop * (1 - TOL_STOP)

    c_comp = [o for o in compras if o["px"] and o["moneda"] == "ARS"]
    px_ent = (sum(o["q"] * o["px"] for o in c_comp) / sum(o["q"] for o in c_comp)) if c_comp else None
    q_comp = sum(o["q"] for o in compras)
    alertas = []
    if compras:
        a = _alertas(p["simbolo"], primera["fecha"], "compra")
        if a:
            alertas.append(dict(a, cuando="entrada"))
    if ventas and not abierta:
        a = _alertas(p["simbolo"], ultima["fecha"], "venta")
        if a:
            alertas.append(dict(a, cuando="salida"))
    nh = niv_hoy.get(p["simbolo"]) if abierta else None
    return {
        "id": primera["id"], "broker": p["broker"], "simbolo": p["simbolo"],
        "estrategia_id": eid, "fuente": fuente, "abierta": abierta,
        "incompleta": p["incompleta"], "cambio": cambio, "sin_salida": sin_salida, "sin_precio": sin_precio, "sin_mep": sin_mep,
        "medible": medible, "gastos_est": any(o["gastos_est"] for o in ops),
        "fecha_ini": primera["fecha"], "fecha_fin": None if abierta else ultima["fecha"],
        "dias": ((date.today() if abierta else date.fromisoformat(ultima["fecha"][:10]))
                 - date.fromisoformat(primera["fecha"][:10])).days,
        "cantidad": round(q, 6), "base": base,
        "ppc_cg": (costo_tot / q_comp * base) if q_comp and costo_tot and not sin_precio else None,
        "px_entrada": px_ent, "px_salida": pxs,
        "res": None if abierta or not medible else round(res, 2),
        "res_usd": None if abierta or not medible or sin_mep else round(res_u, 2),
        "pct": None if abierta or not medible or not costo_tot else res / costo_tot * 100,
        "pct_usd": (None if abierta or not medible or sin_mep or not costo_u_tot
                    else res_u / costo_u_tot * 100),
        "lat": None if lat is None else round(lat, 2),
        "lat_usd": None if lat_u is None else round(lat_u, 2),
        "lat_pct": (lat / costo * 100) if (lat is not None and costo) else None,
        "lat_pct_usd": (lat_u / costo_u * 100) if (lat_u is not None and costo_u) else None,
        "stop_ent": stop, "obj_ent": obj, "modo_ent": modo,
        "hoy": ({"stop": nh.get("stop"), "obj": nh.get("obj"), "modo": nh.get("modo")} if nh else None),
        "riesgo": None if riesgo is None else round(riesgo, 2), "r": r,
        "stop_respetado": resp, "motivo": motivo,
        "nota": primera.get("nota") or "", "alertas": alertas,
        "ops": [{"id": o["id"], "fecha": o["fecha"], "lado": o["lado"], "cantidad": o["q"],
                 "precio": o["px"], "moneda": o["moneda"], "fuente": o["fuente"],
                 "gastos": o["gastos"], "gastos_est": bool(o["gastos_est"]),
                 "neto": (_pesos_dolares(o) or {}).get("neto"), "mep": o["mep"],
                 "motivo": o["motivo"]} for o in ops],
    }


# -- para completar y edicion -------------------------------------------

def pendientes(pos=None):
    """Lo que falta clasificar: ventas sin motivo y posiciones sin
    estrategia. "Sin motivo" es un motivo: elegirlo la saca de la lista."""
    pos = pos if pos is not None else posiciones()
    archivados = {}
    try:
        import gestion as GE
        for a in GE.archivados():
            archivados.setdefault(a.get("simbolo"), a)
    except Exception:
        pass
    out = []
    for p in pos:
        # Una posicion con historia incompleta queda fuera de las
        # estadisticas: clasificarla no cambia nada.
        if p["incompleta"] or p["cambio"] or p["sin_salida"]:
            continue
        reciente = p["abierta"] or (p["fecha_fin"] or "") >= DESDE_PENDIENTES
        # Las ventas del mismo dia son una salida (TRAN vendio en cuatro
        # boletos): se pregunta una vez, por la ultima.
        dias = {}
        for o in p["ops"]:
            if o["lado"] == "venta":
                dias.setdefault(o["fecha"][:10], []).append(o)
        filas = []
        if not p["estrategia_id"] and reciente:
            filas.append((p["ops"][0], p["ops"][0]["cantidad"]))
        for f, vs in dias.items():
            if not vs[-1]["motivo"] and f >= DESDE_PENDIENTES:
                filas.append((vs[-1], sum(v["cantidad"] for v in vs)))
        for o, cant in filas:
            falta_e = not p["estrategia_id"] and o["id"] == p["id"]
            falta_m = o["lado"] == "venta" and not o["motivo"]
            sug = None
            if falta_m:
                a = archivados.get(p["simbolo"])
                if a and a.get("motivo") in ("stop", "objetivo"):
                    sug = a["motivo"]
            out.append({"op_id": o["id"], "pos_id": p["id"], "broker": p["broker"],
                        "simbolo": p["simbolo"], "fecha": o["fecha"], "lado": o["lado"],
                        "cantidad": cant, "precio": o["precio"], "moneda": o["moneda"],
                        "falta_estrategia": falta_e, "falta_motivo": falta_m,
                        "estrategia_id": p["estrategia_id"], "motivo_sugerido": sug,
                        "candidatos_rot": candidatos_rotacion(o["id"]) if falta_m else []})
    out.sort(key=lambda x: x["fecha"], reverse=True)
    return out


def candidatos_rotacion(op_id):
    """Compras de otra especie en los dias de la venta, sin unir."""
    c = db.conn()
    v = c.execute("SELECT * FROM diario_op WHERE id=?", (op_id,)).fetchone()
    if not v or v["lado"] != "venta":
        return []
    f = v["fecha"][:10]
    d0 = (date.fromisoformat(f) - timedelta(days=DIAS_ROTACION)).isoformat()
    d1 = (date.fromisoformat(f) + timedelta(days=DIAS_ROTACION)).isoformat() + "T23:59:59"
    return [dict(r) for r in c.execute(
        "SELECT id, broker, simbolo, fecha, cantidad FROM diario_op WHERE lado='compra' AND "
        "simbolo<>? AND fecha>=? AND fecha<=? AND id NOT IN (SELECT rot_id FROM diario_op "
        "WHERE rot_id IS NOT NULL AND id<>?) ORDER BY fecha", (v["simbolo"], d0, d1, op_id))]


def _ops_de(pos_id):
    """Los ids de las operaciones de la posicion que empieza en `pos_id`."""
    for p in posiciones():
        if p["id"] == pos_id:
            return p, [o["id"] for o in p["ops"]]
    return None, []


def guardar_op(op_id, d):
    """Estrategia y motivo desde "Para completar". La estrategia va a toda
    la posicion; el motivo a la venta."""
    _asegurar()
    c = db.conn()
    o = c.execute("SELECT * FROM diario_op WHERE id=?", (op_id,)).fetchone()
    if not o:
        raise ValueError("operación inexistente")
    pos_id = None
    for p in posiciones():
        if any(x["id"] == op_id for x in p["ops"]):
            pos_id = p["id"]
            ids = [x["id"] for x in p["ops"]]
            break
    else:
        ids = [op_id]
    if "estrategia_id" in d:
        eid = int(d["estrategia_id"]) if d.get("estrategia_id") else None
        c.execute("UPDATE diario_op SET estrategia_id=? WHERE id IN (%s)" % ",".join("?" * len(ids)),
                  [eid] + ids)
    if "motivo" in d and o["lado"] == "venta":
        m = d.get("motivo") or None
        if m and m not in MOTIVOS:
            raise ValueError("motivo inválido")
        mismas = [op_id]
        if pos_id is not None:
            mismas = [x for x in ids if c.execute(
                "SELECT 1 FROM diario_op WHERE id=? AND lado='venta' AND substr(fecha,1,10)=?",
                (x, o["fecha"][:10])).fetchone()] or [op_id]
        c.execute("UPDATE diario_op SET motivo=? WHERE id IN (%s)" % ",".join("?" * len(mismas)),
                  [m] + mismas)
        if m == "rotacion" and d.get("rot_a"):
            rid = int(d["rot_a"])
            if not c.execute("SELECT 1 FROM diario_op WHERE id=? AND lado='compra'", (rid,)).fetchone():
                raise ValueError("la compra de la rotación no existe")
            c.execute("UPDATE diario_op SET rot_id=NULL WHERE rot_id=? AND id<>?", (rid, op_id))
            c.execute("UPDATE diario_op SET rot_id=? WHERE id=?", (rid, op_id))
        elif m != "rotacion":
            c.execute("UPDATE diario_op SET rot_id=NULL WHERE id=?", (op_id,))
    c.commit()
    return pos_id


def guardar_pos(pos_id, d):
    """Estrategia, motivo de la ultima venta, comentario y, si no hay
    copia, el stop y objetivo al entrar (cargados a mano)."""
    _asegurar()
    c = db.conn()
    p, ids = _ops_de(pos_id)
    if not p:
        raise ValueError("posición inexistente")
    marcas = ",".join("?" * len(ids))
    if "estrategia_id" in d:
        eid = int(d["estrategia_id"]) if d.get("estrategia_id") else None
        c.execute("UPDATE diario_op SET estrategia_id=? WHERE id IN (%s)" % marcas, [eid] + ids)
    if "nota" in d:
        c.execute("UPDATE diario_op SET nota=? WHERE id=?", ((d.get("nota") or "").strip()[:1000], pos_id))
    if "motivo" in d:
        ventas = [o for o in p["ops"] if o["lado"] == "venta"]
        if ventas:
            guardar_op(ventas[-1]["id"], {"motivo": d["motivo"], "rot_a": d.get("rot_a")})
    if "stop_ent" in d or "obj_ent" in d:
        def num(v):
            try:
                return float(str(v).replace(",", ".")) if v not in (None, "") else None
            except ValueError:
                raise ValueError("número inválido: %s" % v)
        c.execute("UPDATE diario_op SET stop_ent=?, obj_ent=?, modo_ent='precio' WHERE id=?",
                  (num(d.get("stop_ent")), num(d.get("obj_ent")), pos_id))
    c.commit()
    return pos_id


def estado(cuentas_iol, broker_boletos=None):
    return {"revision": db.get_estado("diario_revision"),
            "boletos_revision": db.get_estado("boletos_revision"),
            "broker_boletos": broker_boletos,
            "iol": [{"broker": n, "ultima": db.get_estado("diario_iol:" + n),
                     "corte": db.get_estado("diario_iol_corte:" + n),
                     "error": db.get_estado("diario_iol_error:" + n) or None}
                    for n in cuentas_iol]}
