"""Diario de trading: cada posicion desde que se abre hasta que vuelve a cero.

Una sola fuente por dato (22/10/2026). El diario no copia lo que ya esta
en otra tabla: lee cada operacion de donde vive.

- **boleto** (Veta): la tabla `boleto` (aplicados, omitidos o
  descartados: omitir o descartar solo evita tocar la tenencia, la
  operacion existio). Precio, gastos y fecha reales.
- **iol** (las cuentas de IOL): `/api/v2/operaciones`. No hay otra copia
  local, asi que se guardan en `diario_op`, una fila por operacion de
  IOL. Precio real; la API no trae comisiones: los gastos se estiman con
  la tabla de costos al leer.
- **tenencia** (ECO y los demas sin API): los movimientos confirmados de
  `mov_propuesto`. Aproximado: el precio es el de la foto. Un broker con
  boletos usa esta fuente solo antes de su primer boleto.

Lo unico propio del diario esta en `diario_anot`, por referencia de
operacion: motivo de la venta, comentario, la rotacion elegida a mano, la
estrategia de la historia sin ledger y la copia del stop y objetivo al
comprar (historia para el R). El MEP de cada dia y los gastos estimados
se calculan al leer, no se guardan.

La estrategia de una posicion abierta es la asignacion de la especie
(`estrategia_especie`); la de una cerrada, el ledger (`estrategia_mov`).
Las posiciones no se guardan: se arman al leer, por broker y especie.
"""

import logging
from datetime import date, datetime, timedelta

import db

log = logging.getLogger("ratios.diario")

MOTIVOS = ("stop", "objetivo", "propio", "rotacion", "sin motivo")
# Salir hasta 1% debajo del stop cuenta como respetado.
TOL_STOP = 0.01
# Los niveles de Gestion se copian como "al entrar" solo si se cargan en
# los dias siguientes a la compra.
DIAS_COPIA = 7
# Cuanto antes de la operacion se busca la alerta que la precedio.
DIAS_ALERTA = 5
# Ventana para unir una venta y una compra como rotacion.
DIAS_ROTACION = 5
# "Para completar" pide motivo y estrategia desde esta fecha (22/10).
DESDE_PENDIENTES = "2026-01-01"
NO_OPERA = ("moneda",)
MONEDAS = ("ARS", "USD", "MEP", "CCL", "CAUCION", "US$", "PESOS", "DOLARES")
# Diferencia de cantidad tolerada para tomar el PPC del diario.
TOL_CANT = 0.005

_listo = False
_cfg = {"directos": [], "boletos": None, "cfg": {}}
_mep_cache = {}
_ppc_cache = {"clave": None, "datos": {}}


def configurar(directos, broker_boletos, cfg):
    """Que cuentas son de IOL, cual es el broker de los boletos y la
    configuracion (para los gastos estimados). Lo llama la app al armarse."""
    _cfg.update({"directos": list(directos or []), "boletos": broker_boletos, "cfg": cfg or {}})
    _ppc_cache["clave"] = None


def _asegurar():
    global _listo
    if _listo:
        return
    c = db.conn()
    c.executescript("""
-- Solo las operaciones de IOL: no tienen otra copia local.
CREATE TABLE IF NOT EXISTS diario_op (
  ref        TEXT PRIMARY KEY,       -- iol:<broker>:<numero>
  broker     TEXT NOT NULL,
  simbolo    TEXT NOT NULL,
  crudo      TEXT,                   -- el simbolo tal como vino (AO29D)
  fecha      TEXT NOT NULL,
  lado       TEXT NOT NULL,          -- compra | venta
  cantidad   REAL NOT NULL,
  precio     REAL,                   -- en la base en que cotiza
  base       REAL,
  moneda     TEXT NOT NULL DEFAULT 'ARS',
  bruto      REAL,                   -- montoOperado, en `moneda`
  creado     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_diario_pos ON diario_op(broker, simbolo, fecha);
-- Lo que el diario agrega a una operacion de cualquier fuente.
CREATE TABLE IF NOT EXISTS diario_anot (
  ref        TEXT PRIMARY KEY,       -- iol:… | bol:<n> | mov:<id>:<lado>
  motivo     TEXT,
  nota       TEXT,
  rot_ref    TEXT,                   -- venta -> la compra en la que entro
  estrategia_id INTEGER,             -- solo historia cerrada sin ledger
  stop_ent   REAL,
  obj_ent    REAL,
  modo_ent   TEXT
);
""")
    c.commit()
    _listo = True


def init():
    _asegurar()
    migrar()


def migrar():
    """Del diario de la 0.68/0.69, que copiaba boletos y movimientos y
    guardaba en cada fila la estrategia, el MEP y los gastos estimados, a
    este: IOL en `diario_op` y lo propio en `diario_anot`. Una vez."""
    if db.get_estado("diario_v3"):
        return
    c = db.conn()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(diario_op)")}
    if "motivo" in cols:
        viejas = [dict(r) for r in c.execute("SELECT * FROM diario_op")]
        ref_de = {r["id"]: r["ref"] for r in viejas}
        # el motivo que el boleto guardaba en `nota` (0.69.0 y antes)
        mot_bol = {}
        try:
            for b in c.execute("SELECT bol, nota FROM boleto WHERE tipo='venta' AND nota IS NOT NULL"):
                if b["nota"] in MOTIVOS:
                    mot_bol["bol:%s" % b["bol"]] = b["nota"]
            c.execute("UPDATE boleto SET nota=NULL WHERE tipo='venta'")
        except Exception as e:
            log.info("migrar motivos de boletos: %s", e)
        ya = bool(db.get_estado("diario_fuente_unica"))
        for r in viejas:
            motivo = r["motivo"] or mot_bol.get(r["ref"])
            # La estrategia que la importacion copiaba no se pasa (salvo que
            # la 0.69.1 ya la hubiera limpiado y quede solo la elegida).
            eid = r["estrategia_id"] if ya else None
            rot = ref_de.get(r["rot_id"]) if r.get("rot_id") else None
            if any(v is not None and v != "" for v in (motivo, r["nota"], rot, eid, r["stop_ent"], r["obj_ent"])):
                c.execute("INSERT OR REPLACE INTO diario_anot (ref, motivo, nota, rot_ref, estrategia_id, "
                          "stop_ent, obj_ent, modo_ent) VALUES (?,?,?,?,?,?,?,?)",
                          (r["ref"], motivo, r["nota"] or None, rot, eid, r["stop_ent"], r["obj_ent"],
                           r["modo_ent"]))
        c.executescript("""
ALTER TABLE diario_op RENAME TO diario_op_vieja;
CREATE TABLE diario_op (
  ref TEXT PRIMARY KEY, broker TEXT NOT NULL, simbolo TEXT NOT NULL, crudo TEXT,
  fecha TEXT NOT NULL, lado TEXT NOT NULL, cantidad REAL NOT NULL, precio REAL, base REAL,
  moneda TEXT NOT NULL DEFAULT 'ARS', bruto REAL, creado TEXT NOT NULL);
INSERT INTO diario_op (ref, broker, simbolo, crudo, fecha, lado, cantidad, precio, base, moneda, bruto, creado)
  SELECT ref, broker, simbolo, crudo, fecha, lado, cantidad, precio, base, moneda, bruto, creado
  FROM diario_op_vieja WHERE fuente='iol';
DROP TABLE diario_op_vieja;
CREATE INDEX IF NOT EXISTS ix_diario_pos ON diario_op(broker, simbolo, fecha);
""")
    c.commit()
    db.set_estado("diario_v3", _ahora())


# -- utilidades ----------------------------------------------------------

def _ahora():
    return datetime.now().isoformat(timespec="seconds")


def _mep(fecha):
    """MEP de un dia, de la serie AL30/AL30D. Calculado, no guardado; se
    recuerda en memoria solo lo que se encontro."""
    f = str(fecha or "")[:10]
    if not f:
        return None
    if f in _mep_cache:
        return _mep_cache[f]
    try:
        import bonos as BO
        m = BO.mep_al(f)
    except Exception:
        m = None
    if m:
        _mep_cache[f] = m
    return m


def _gastos_est(tipo, bruto):
    """Gastos estimados de una pata con la tabla de costos de la app."""
    if not bruto:
        return 0.0
    import costos as CO
    inst = (tipo or "acciones").lower()
    if inst in ("fci", "moneda"):
        return 0.0
    cfg = _cfg["cfg"] or {}
    try:
        p = CO.pct(cfg.get("comisiones") or {}, inst, cfg.get("derechos_mercado"), cfg.get("iva_pct") or 0)
    except Exception:
        p = 0.0
    return round(abs(bruto) * p, 2)


def _tipo(sim):
    c = db.conn()
    r = c.execute("SELECT tipo FROM tenencia WHERE simbolo=? AND tipo IS NOT NULL LIMIT 1", (sim,)).fetchone()
    if not r:
        r = c.execute("SELECT tipo FROM tenencia_hist WHERE simbolo=? AND tipo IS NOT NULL "
                      "ORDER BY ts DESC LIMIT 1", (sim,)).fetchone()
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


def _anotaciones():
    _asegurar()
    return {r["ref"]: dict(r) for r in db.conn().execute("SELECT * FROM diario_anot")}


def _anotar(ref, **campos):
    """Escribe en la anotacion de una operacion (la crea si no existe)."""
    _asegurar()
    c = db.conn()
    c.execute("INSERT OR IGNORE INTO diario_anot (ref) VALUES (?)", (ref,))
    for k, v in campos.items():
        if k not in ("motivo", "nota", "rot_ref", "estrategia_id", "stop_ent", "obj_ent", "modo_ent"):
            raise ValueError("campo inválido: %s" % k)
        c.execute("UPDATE diario_anot SET %s=? WHERE ref=?" % k, (v, ref))
    c.commit()


# -- lectura de las tres fuentes ----------------------------------------

def _primer_boleto(broker):
    try:
        r = db.conn().execute("SELECT MIN(fecha) f FROM boleto WHERE broker=? AND tipo IN "
                              "('compra','venta')", (broker,)).fetchone()
        return r["f"] if r and r["f"] else None
    except Exception:
        return None


def _ops_boletos():
    out = []
    try:
        filas = db.conn().execute(
            "SELECT * FROM boleto WHERE estado IN ('aplicado','omitido','descartado') "
            "AND tipo IN ('compra','venta') AND cantidad > 0").fetchall()
    except Exception:
        return out
    for b in filas:
        sim = (b["simbolo"] or "").upper()
        base = _base(sim)
        out.append({"ref": "bol:%s" % b["bol"], "fuente": "boleto", "broker": b["broker"],
                    "simbolo": sim, "fecha": b["fecha"] or b["liquida"] or "", "lado": b["tipo"],
                    "cantidad": b["cantidad"], "precio": b["precio"], "base": base,
                    "moneda": "USD" if b["moneda"] == "USD" else "ARS",
                    "bruto": b["cantidad"] * b["precio"] / base if b["precio"] is not None else None,
                    "gastos": round((b["gastos"] or 0) + (b["iva"] or 0), 2), "gastos_est": False})
    return out


def _ops_movimientos():
    """Movimientos confirmados de los brokers sin fuente directa, y las
    rotaciones que ya dicen (dentro del broker o unidas entre dos)."""
    directos = set(_cfg["directos"])
    bol = _cfg["boletos"]
    corte = _primer_boleto(bol) if bol else None
    c = db.conn()
    out, rot = [], {}
    filas = c.execute("SELECT * FROM mov_propuesto WHERE estado='confirmado' ORDER BY hasta, id").fetchall()
    for m in filas:
        if m["broker"] in directos or (m["signo"] or 1) < 0:
            continue
        if bol and m["broker"] == bol and corte and m["hasta"] >= corte:
            continue
        patas = []
        if m["sale"] and m["cant_sale"]:
            patas.append(("venta", m["sale"], m["cant_sale"], m["precio_sale"]))
        if m["entra"] and m["cant_entra"]:
            patas.append(("compra", m["entra"], m["cant_entra"], m["precio_entra"]))
        refs = {}
        for lado, sim, cant, precio in patas:
            sim = sim.upper()
            tipo = _tipo(sim)
            if sim in MONEDAS or (tipo or "").lower() in NO_OPERA:
                continue
            base = _base(sim)
            bruto = abs(cant) * precio / base if precio else None
            ref = "mov:%s:%s" % (m["id"], lado)
            refs[lado] = ref
            out.append({"ref": ref, "fuente": "tenencia", "broker": m["broker"], "simbolo": sim,
                        "fecha": m["hasta"], "lado": lado, "cantidad": abs(cant), "precio": precio,
                        "base": base, "moneda": "ARS", "bruto": bruto,
                        "gastos": _gastos_est(tipo, bruto) if bruto else None, "gastos_est": True})
        if m["tipo"] == "rotacion" and len(refs) == 2:
            rot[refs["venta"]] = refs["compra"]
    for m in c.execute("SELECT a.id ia, b.id ib, a.tipo ta, b.tipo tb FROM mov_propuesto a "
                       "JOIN mov_propuesto b ON b.unido_a = a.id WHERE a.estado='confirmado' "
                       "AND b.estado='confirmado'"):
        if {m["ta"], m["tb"]} == {"retiro", "aporte"}:
            v = "mov:%s:venta" % (m["ia"] if m["ta"] == "retiro" else m["ib"])
            k = "mov:%s:compra" % (m["ib"] if m["ta"] == "retiro" else m["ia"])
            rot[v] = k
    return out, rot


def _ops_iol():
    out = []
    for r in db.conn().execute("SELECT * FROM diario_op"):
        d = dict(r)
        tipo = _tipo(d["simbolo"])
        d.update(fuente="iol", gastos=_gastos_est(tipo, d["bruto"]), gastos_est=True)
        out.append(d)
    return out


def _todas():
    """Todas las operaciones, con sus anotaciones y las rotaciones que las
    fuentes ya dicen. Devuelve (ops, rotaciones {venta_ref: compra_ref})."""
    _asegurar()
    ops = _ops_iol() + _ops_boletos()
    mov, rot = _ops_movimientos()
    ops += mov
    anot = _anotaciones()
    for o in ops:
        a = anot.get(o["ref"]) or {}
        o["motivo"] = a.get("motivo")
        o["nota"] = a.get("nota")
        o["rot_ref"] = a.get("rot_ref")
        o["estrategia_id"] = a.get("estrategia_id")
        o["stop_ent"], o["obj_ent"], o["modo_ent"] = a.get("stop_ent"), a.get("obj_ent"), a.get("modo_ent")
        o["mep"] = _mep(o["fecha"])
    # Rotaciones del ledger de las estrategias (boletos marcados como
    # rotacion, movimientos confirmados en IOL): una venta y una compra
    # sin unir en la ventana.
    por_ref = {o["ref"]: o for o in ops}
    elegidas = {o["rot_ref"] for o in ops if o.get("rot_ref")} | set(rot.values())
    for r in db.conn().execute("SELECT ticker_de, ticker_a, ts FROM estrategia_mov WHERE tipo='rotacion' "
                               "AND ticker_de IS NOT NULL AND ticker_a IS NOT NULL"):
        f = (r["ts"] or "")[:10]
        try:
            d0 = (date.fromisoformat(f) - timedelta(days=DIAS_ROTACION)).isoformat()
        except ValueError:
            continue
        h = f + "T23:59:59"
        v = [o for o in ops if o["lado"] == "venta" and o["simbolo"] == r["ticker_de"]
             and d0 <= o["fecha"] <= h and not o.get("rot_ref") and o["ref"] not in rot]
        k = [o for o in ops if o["lado"] == "compra" and o["simbolo"] == r["ticker_a"]
             and d0 <= o["fecha"] <= h and o["ref"] not in elegidas]
        if len(v) == 1 and len(k) == 1:
            rot[v[0]["ref"]] = k[0]["ref"]
            elegidas.add(k[0]["ref"])
    for v, k in rot.items():
        o = por_ref.get(v)
        if o and not o.get("rot_ref"):
            o["rot_ref"] = k
            o["rot_auto"] = True
            if not o["motivo"]:
                o["motivo"] = "rotacion"
    ops.sort(key=lambda o: (o["broker"], o["simbolo"], o["fecha"], o["ref"]))
    return ops


# -- importacion de IOL --------------------------------------------------

def _operaciones(cli, desde, hasta):
    """Las operaciones de un rango, de a un año (la primera carga de una
    cuenta de 2017 son nueve años). Las repetidas se filtran por numero."""
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
    """La primera vez: desde la primera compra de las tenencias actuales del
    broker. Las que no tienen fecha de alta se reconstruyen con cinco años
    de operaciones. Devuelve (corte, operaciones ya bajadas o None)."""
    import operaciones as OPS
    ten = [dict(r) for r in db.conn().execute(
        "SELECT simbolo, tipo, cantidad, fecha_alta FROM tenencia WHERE broker=?", (broker,))]
    ten = [t for t in ten if (t.get("tipo") or "").lower() not in NO_OPERA
           and t["simbolo"] not in MONEDAS and (t.get("cantidad") or 0) > 0]
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
    """Baja las operaciones de una cuenta y guarda las nuevas en
    `diario_op`. La primera vez, desde la primera compra de las tenencias
    actuales; despues, desde la ultima importacion menos tres dias."""
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
    vistos = {x["simbolo"] for x, _ in pares} | {r["simbolo"] for r in c.execute(
        "SELECT simbolo FROM tenencia WHERE broker=?", (broker,))}
    nuevas = 0
    for x, o in pares:
        usd = OPS.en_dolares(x["simbolo_crudo"], vistos)
        sim = OPS.simbolo_base(x["simbolo"], vistos)
        base = OPS.base_de(x) or _base(sim)
        fecha = str(o.get("fechaOperada") or o.get("fechaOrden") or x["fecha"])[:19]
        bruto = x["monto"] if x["monto"] else (x["cantidad"] * x["precio"] / base if x["precio"] else None)
        cur = c.execute(
            "INSERT OR IGNORE INTO diario_op (ref, broker, simbolo, crudo, fecha, lado, cantidad, precio, "
            "base, moneda, bruto, creado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("iol:%s:%s" % (broker, x["numero"]), broker, sim, x["simbolo_crudo"], fecha,
             "compra" if x["signo"] > 0 else "venta", x["cantidad"], x["precio"], base,
             "USD" if usd else "ARS", bruto, _ahora()))
        nuevas += cur.rowcount
    c.commit()
    db.set_estado(k, _ahora())
    db.set_estado("diario_iol_error:" + broker, "")
    _ppc_cache["clave"] = None
    return {"broker": broker, "desde": desde, "operaciones": len(pares), "nuevas": nuevas}


def completar_copias():
    """Copia el stop y objetivo de Gestion como "al entrar" en las compras
    de los ultimos DIAS_COPIA dias que todavia no la tienen."""
    niv = _niveles()
    if not niv:
        return 0
    desde = (date.today() - timedelta(days=DIAS_COPIA)).isoformat()
    n = 0
    for o in _todas():
        if o["lado"] != "compra" or o["fecha"] < desde or o["stop_ent"] is not None or o["obj_ent"] is not None:
            continue
        x = niv.get(o["simbolo"])
        if x and (x.get("stop") is not None or x.get("obj") is not None):
            _anotar(o["ref"], stop_ent=x.get("stop"), obj_ent=x.get("obj"), modo_ent=x.get("modo") or "precio")
            n += 1
    return n


def sincronizar_local(*_args, **_kw):
    """Lo que no pide nada afuera. Ya no copia nada: solo completa la copia
    de los niveles al entrar."""
    try:
        return {"copias": completar_copias()}
    except Exception as e:
        log.warning("diario copias: %s", e)
        return {"copias": 0}


def sincronizar(cuentas, broker_boletos=None, cfg=None):
    """La revision diaria de las 4: IOL por API y la copia de niveles."""
    configurar([n for n, _ in cuentas], broker_boletos, cfg)
    res = []
    for nombre, cli in cuentas:
        try:
            with cli.como("diario"):
                res.append(importar_iol(cli, nombre, cfg))
        except Exception as e:
            db.set_estado("diario_iol_error:" + nombre, str(e)[:300])
            log.warning("diario %s: %s", nombre, e)
            res.append({"broker": nombre, "error": str(e)})
    loc = sincronizar_local()
    db.set_estado("diario_revision", _ahora())
    return {"iol": res, "local": loc}


def motivo_de_boletos(motivos):
    """El motivo elegido al confirmar boletos, en su unico lugar.
    `motivos`: {bol: motivo}."""
    for bol, m in (motivos or {}).items():
        if m in MOTIVOS:
            _anotar("bol:%s" % bol, motivo=m)


# -- posiciones ----------------------------------------------------------

def _ajustar(ops, sim):
    """Cantidad y precio a la escala de hoy si hubo un evento societario
    despues de la operacion. Lo pagado no cambia."""
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
    """Neto en pesos y en dolares de una operacion (lo que salio en una
    compra, lo que entro en una venta)."""
    if o["bruto"] is None:
        return None
    g = o["gastos"] or 0
    neto = o["bruto"] + g if o["lado"] == "compra" else o["bruto"] - g
    mep = o["mep"]
    if o["moneda"] == "USD":
        return {"neto": neto * mep if mep else None, "neto_usd": neto}
    return {"neto": neto, "neto_usd": neto / mep if mep else None}


def _armar(ops, ten=None):
    """Agrupa por broker y especie en posiciones. `ten`: cantidades por
    (broker, simbolo) para marcar historia incompleta y salida sin
    registrar; sin ella no se marca."""
    grupos = {}
    for o in ops:
        grupos.setdefault((o["broker"], o["simbolo"]), []).append(o)
    pos = []
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
                    actual = {"broker": broker, "simbolo": sim, "ops": [], "incompleta": True}
                    pos.append(actual)
                    q = 0.0
                if o["q"] > q + 1e-6:
                    actual["incompleta"] = True
                actual["ops"].append(o)
                q = max(0.0, q - o["q"])
        if actual is not None and ten is not None:
            t = ten.get((broker, sim), 0)
            if q > 1e-9 and t > q * (1 + 2 * TOL_CANT) + 1e-6:
                actual["incompleta"] = True       # empezo antes de lo registrado
            elif q > 1e-9 and t <= 1e-9:
                actual["sin_salida"] = True       # vencimiento, rescate, canje o transferencia
    return pos


def _cantidades():
    ten = {}
    for r in db.conn().execute("SELECT broker, simbolo, cantidad FROM tenencia"):
        ten[(r["broker"], r["simbolo"])] = ten.get((r["broker"], r["simbolo"]), 0) + (r["cantidad"] or 0)
    return ten


def _costos(p):
    """Cantidad, costo y resultado (pesos y dolares) corriendo las
    operaciones contra el PPC con gastos."""
    q = costo = costo_u = res = res_u = 0.0
    costo_tot = costo_u_tot = 0.0
    sin_precio = sin_mep = False
    for o in p["ops"]:
        v = _pesos_dolares(o)
        if v is None or v["neto"] is None:
            sin_precio = True
            if v is not None:
                sin_mep = True
            q = q + o["q"] if o["lado"] == "compra" else max(0.0, q - o["q"])
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
    return {"q": q, "costo": costo, "costo_u": costo_u, "res": res, "res_u": res_u,
            "costo_tot": costo_tot, "costo_u_tot": costo_u_tot,
            "sin_precio": sin_precio, "sin_mep": sin_mep}


def posiciones(precios=None, mep_hoy=None):
    """Las posiciones armadas desde las tres fuentes, con resultado,
    estrategia, R y alertas. `precios` (pesos, en la base en que cotiza) y
    `mep_hoy` para el latente de las abiertas."""
    precios = precios or {}
    ops = _todas()
    pos = _armar(ops, _cantidades())
    estr = {e["id"]: e["nombre"] for e in db.estrategias(incluir_cerradas=True)}
    niv_hoy = _niveles()
    de_ref = {}
    for p in pos:
        for o in p["ops"]:
            de_ref[o["ref"]] = p
    out = []
    for p in pos:
        d = _medir(p, precios, mep_hoy, niv_hoy)
        d["estrategia"] = estr.get(d["estrategia_id"])
        out.append(d)
    por_pos = {id(p): d for p, d in zip(pos, out)}
    for p, d in zip(pos, out):
        for o in p["ops"]:
            if o["lado"] == "venta" and o.get("rot_ref") and o["rot_ref"] in de_ref:
                dst = por_pos[id(de_ref[o["rot_ref"]])]
                d["rot_a"] = {"id": dst["id"], "simbolo": dst["simbolo"], "broker": dst["broker"],
                              "auto": bool(o.get("rot_auto"))}
                dst["rot_de"] = {"id": d["id"], "simbolo": d["simbolo"], "broker": d["broker"]}
    out.sort(key=lambda x: (x["abierta"], x["fecha_fin"] or x["fecha_ini"]), reverse=True)
    return out


def _estrategia(p, abierta, ops):
    """Abierta: la asignacion de la especie. Cerrada: el ledger. Cerrada sin
    ledger: la elegida en el diario. Devuelve (id, fuente)."""
    sim = p["simbolo"]
    if abierta:
        eid = db._estrategia_de(sim)
        return eid, ("asignacion" if eid else None)
    f0 = ops[0]["fecha"][:10]
    try:
        f1 = (date.fromisoformat(ops[-1]["fecha"][:10]) + timedelta(days=DIAS_ROTACION)).isoformat()
    except ValueError:
        f1 = ops[-1]["fecha"][:10]
    r = db.conn().execute(
        "SELECT estrategia_id FROM estrategia_mov WHERE (ticker_de=? OR ticker_a=?) AND ts>=? AND ts<=? "
        "ORDER BY (ticker_de=?) DESC, ts DESC LIMIT 1", (sim, sim, f0, f1 + "T23:59:59", sim)).fetchone()
    if r and r["estrategia_id"]:
        return r["estrategia_id"], "ledger"
    eid = next((o["estrategia_id"] for o in ops if o["estrategia_id"]), None)
    return eid, ("diario" if eid else None)


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


def _medir(p, precios, mep_hoy, niv_hoy):
    ops = p["ops"]
    compras = [o for o in ops if o["lado"] == "compra"]
    ventas = [o for o in ops if o["lado"] == "venta"]
    k = _costos(p)
    q, costo, costo_u = k["q"], k["costo"], k["costo_u"]
    res, res_u, costo_tot, costo_u_tot = k["res"], k["res_u"], k["costo_tot"], k["costo_u_tot"]
    sin_precio, sin_mep = k["sin_precio"], k["sin_mep"]
    sin_salida = bool(p.get("sin_salida"))
    abierta = q > 1e-9 and not sin_salida
    primera = compras[0] if compras else ops[0]
    ultima = ops[-1]
    base = primera.get("base") or 1.0
    fuentes = {o["fuente"] for o in ops}
    fuente = "tenencia" if "tenencia" in fuentes else ("iol" if "iol" in fuentes else "boleto")
    eid, e_fuente = _estrategia(p, abierta, ops)
    motivo = ventas[-1]["motivo"] if ventas and not abierta and not sin_salida else None

    lat = lat_u = None
    if abierta and not sin_precio and not p["incompleta"]:
        px = precios.get(p["simbolo"])
        if px:
            v_act = q * px / (_base(p["simbolo"]) or base)
            lat = v_act - costo
            if mep_hoy and not sin_mep:
                lat_u = v_act / mep_hoy - costo_u
    cambio = (bool(compras) and bool(ventas) and q <= 1e-9
              and len({o["fecha"][:10] for o in ops}) == 1
              and len({o["moneda"] for o in ops}) > 1)
    medible = not sin_precio and not p["incompleta"] and not cambio and not sin_salida

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
        "id": primera["ref"], "broker": p["broker"], "simbolo": p["simbolo"],
        "estrategia_id": eid, "estrategia_fuente": e_fuente, "fuente": fuente, "abierta": abierta,
        "incompleta": p["incompleta"], "cambio": cambio, "sin_salida": sin_salida,
        "sin_precio": sin_precio, "sin_mep": sin_mep,
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
        "ops": [{"id": o["ref"], "fecha": o["fecha"], "lado": o["lado"], "cantidad": o["q"],
                 "precio": o["px"], "moneda": o["moneda"], "fuente": o["fuente"],
                 "gastos": o["gastos"], "gastos_est": bool(o["gastos_est"]),
                 "neto": (_pesos_dolares(o) or {}).get("neto"), "mep": o["mep"],
                 "motivo": o["motivo"]} for o in ops],
    }


# -- PPC de la tenencia ---------------------------------------------------

def _huella():
    """Cambia cuando cambia algo que mueve los costos."""
    c = db.conn()
    partes = [date.today().isoformat()]
    for q in ("SELECT COUNT(*), MAX(creado) FROM diario_op",
              "SELECT COUNT(*), MAX(aplicado), MAX(leido) FROM boleto",
              "SELECT COUNT(*), MAX(id) FROM mov_propuesto WHERE estado='confirmado'",
              "SELECT COUNT(*), MAX(id) FROM evento_societario"):
        try:
            partes.append(tuple(c.execute(q).fetchone()))
        except Exception:
            partes.append(None)
    return tuple(partes)


def ppc_por_posicion():
    """{(broker, simbolo): {ppc, ppc_usd, fecha_alta, cantidad}} de las
    abiertas cuya historia esta completa en el diario con precio real
    (IOL o boletos). Es la fuente del PPC de esas posiciones: la tenencia
    lo toma de aca en vez de guardarlo aparte."""
    _asegurar()
    if not db.get_estado("diario_v3"):
        return {}
    h = _huella()
    if _ppc_cache["clave"] == h:
        return _ppc_cache["datos"]
    datos = {}
    try:
        for p in _armar(_todas()):
            if p["incompleta"] or any(o["fuente"] == "tenencia" for o in p["ops"]):
                continue
            k = _costos(p)
            if k["q"] <= 1e-9 or k["sin_precio"]:
                continue
            datos[(p["broker"], p["simbolo"])] = {
                "ppc": k["costo"] / k["q"],
                "ppc_usd": (k["costo_u"] / k["q"]) if not k["sin_mep"] else None,
                "fecha_alta": next(o for o in p["ops"] if o["lado"] == "compra")["fecha"][:10],
                "cantidad": k["q"]}
    except Exception as e:
        log.warning("ppc del diario: %s", e)
        datos = {}
    _ppc_cache.update(clave=h, datos=datos)
    return datos


def aplicar_ppc(filas, ajustadas=False):
    """Pone en las filas de tenencia el PPC del diario cuando la cantidad
    coincide. `ajustadas`: las filas ya pasaron por el ajuste de eventos
    (el del diario ya esta en la escala de hoy)."""
    try:
        datos = ppc_por_posicion()
    except Exception:
        return filas
    for f in filas:
        d = datos.get((f.get("broker"), f.get("simbolo")))
        cant = f.get("cantidad") or 0
        if not d or not cant or abs(d["cantidad"] - cant) > TOL_CANT * max(abs(cant), 1):
            continue
        f["ppc"], f["ppc_base"] = d["ppc"], 1.0
        if d["ppc_usd"] is not None:
            f["ppc_usd"] = d["ppc_usd"]
        f["fecha_alta"], f["precision"], f["ppc_fuente"] = d["fecha_alta"], "exacta", "diario"
        if ajustadas:
            f["ppc_ajustado"], f["eventos"], f["ajuste_supuesto"] = d["ppc"], [], False
    return filas


# -- para completar y edicion -------------------------------------------

def pendientes(pos=None):
    """Ventas sin motivo y posiciones sin estrategia, desde 2026. "Sin
    motivo" es un motivo: elegirlo la saca de la lista."""
    pos = pos if pos is not None else posiciones()
    archivados = {}
    try:
        import gestion as GE
        for a in GE.archivados():
            archivados.setdefault(a.get("simbolo"), a)
    except Exception:
        pass
    todas = None
    out = []
    for p in pos:
        if p["incompleta"] or p["cambio"] or p["sin_salida"]:
            continue
        reciente = p["abierta"] or (p["fecha_fin"] or "") >= DESDE_PENDIENTES
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
                        "candidatos_rot": []})
            if falta_m:
                todas = todas if todas is not None else _todas()
                out[-1]["candidatos_rot"] = _candidatos(o, p["simbolo"], todas)
    out.sort(key=lambda x: x["fecha"], reverse=True)
    return out


def _candidatos(v, sim, todas):
    """Compras de otra especie en los dias de la venta."""
    f = v["fecha"][:10]
    d0 = (date.fromisoformat(f) - timedelta(days=DIAS_ROTACION)).isoformat()
    d1 = (date.fromisoformat(f) + timedelta(days=DIAS_ROTACION)).isoformat() + "T23:59:59"
    return [{"id": o["ref"], "broker": o["broker"], "simbolo": o["simbolo"], "fecha": o["fecha"],
             "cantidad": o["cantidad"]}
            for o in todas if o["lado"] == "compra" and o["simbolo"] != sim and d0 <= o["fecha"] <= d1]


def _posicion_de(ref):
    for p in posiciones():
        if p["id"] == ref or any(o["id"] == ref for o in p["ops"]):
            return p
    return None


def _fijar_estrategia(p, eid):
    """En su unica fuente. Una cerrada con ledger no se cambia desde aca."""
    if p["abierta"]:
        db.asignar(p["simbolo"], eid)
    elif p.get("estrategia_fuente") == "ledger":
        raise ValueError("La estrategia de %s sale del ledger de la estrategia; se corrige ahí." % p["simbolo"])
    else:
        _anotar(p["id"], estrategia_id=eid)


def _fijar_motivo(p, venta_ref, m, rot_a=None):
    if m and m not in MOTIVOS:
        raise ValueError("motivo inválido")
    v = next((o for o in p["ops"] if o["id"] == venta_ref and o["lado"] == "venta"), None)
    if not v:
        raise ValueError("operación inexistente")
    # El motivo va a todas las ventas de ese dia de la posicion.
    for o in p["ops"]:
        if o["lado"] == "venta" and o["fecha"][:10] == v["fecha"][:10]:
            _anotar(o["id"], motivo=m)
    if m == "rotacion" and rot_a:
        if not any(o["ref"] == rot_a and o["lado"] == "compra" for o in _todas()):
            raise ValueError("la compra de la rotación no existe")
        _anotar(venta_ref, rot_ref=rot_a)
    elif m != "rotacion":
        _anotar(venta_ref, rot_ref=None)


def guardar_op(ref, d):
    """Desde "Para completar": estrategia de la posicion y motivo de la venta."""
    p = _posicion_de(ref)
    if not p:
        raise ValueError("operación inexistente")
    if "estrategia_id" in d:
        eid = int(d["estrategia_id"]) if d.get("estrategia_id") else None
        if eid != p["estrategia_id"]:
            _fijar_estrategia(p, eid)
    if "motivo" in d:
        _fijar_motivo(p, ref, d.get("motivo") or None, d.get("rot_a"))
    return p["id"]


def guardar_pos(ref, d):
    """Desde el detalle: estrategia, motivo de la ultima venta, comentario
    y, si no hay copia, el stop y objetivo al entrar."""
    p = _posicion_de(ref)
    if not p:
        raise ValueError("posición inexistente")
    if "estrategia_id" in d:
        eid = int(d["estrategia_id"]) if d.get("estrategia_id") else None
        if eid != p["estrategia_id"]:
            _fijar_estrategia(p, eid)
    if "nota" in d:
        _anotar(p["id"], nota=(d.get("nota") or "").strip()[:1000] or None)
    if "motivo" in d:
        ventas = [o for o in p["ops"] if o["lado"] == "venta"]
        if ventas:
            _fijar_motivo(p, ventas[-1]["id"], d.get("motivo") or None, d.get("rot_a"))
    if "stop_ent" in d or "obj_ent" in d:
        def num(v):
            try:
                return float(str(v).replace(",", ".")) if v not in (None, "") else None
            except ValueError:
                raise ValueError("número inválido: %s" % v)
        _anotar(p["id"], stop_ent=num(d.get("stop_ent")), obj_ent=num(d.get("obj_ent")), modo_ent="precio")
    return p["id"]


def estado(cuentas_iol, broker_boletos=None):
    return {"revision": db.get_estado("diario_revision"),
            "boletos_revision": db.get_estado("boletos_revision"),
            "broker_boletos": broker_boletos,
            "iol": [{"broker": n, "ultima": db.get_estado("diario_iol:" + n),
                     "corte": db.get_estado("diario_iol_corte:" + n),
                     "error": db.get_estado("diario_iol_error:" + n) or None}
                    for n in cuentas_iol]}
