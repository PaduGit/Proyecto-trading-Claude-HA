"""Persistencia en SQLite. Vive en /data, que HA conserva entre reinicios."""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta

log = logging.getLogger("ratios.db")

RUTA = os.environ.get("RATIOS_DB", "/data/ratios.db")
_local = threading.local()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS lecturas (
    ts        TEXT NOT NULL,
    alias     TEXT NOT NULL,
    ratio     REAL NOT NULL,
    p_num     REAL,
    p_den     REAL,
    c_num     REAL,
    v_num     REAL,
    c_den     REAL,
    v_den     REAL,
    qc_num    REAL,
    qv_num    REAL,
    qc_den    REAL,
    qv_den    REAL,
    PRIMARY KEY (alias, ts)
);
CREATE INDEX IF NOT EXISTS ix_lecturas_alias_ts ON lecturas(alias, ts);

CREATE TABLE IF NOT EXISTS cierres (
    fecha     TEXT NOT NULL,
    simbolo   TEXT NOT NULL,
    cierre    REAL NOT NULL,
    PRIMARY KEY (simbolo, fecha)
);

CREATE TABLE IF NOT EXISTS alertas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    alias     TEXT NOT NULL,
    tipo      TEXT NOT NULL,
    ratio     REAL NOT NULL,
    nivel     REAL,
    mensaje   TEXT,
    p_num     REAL,
    p_den     REAL,
    qc_num    REAL,
    qv_num    REAL,
    qc_den    REAL,
    qv_den    REAL
);
CREATE INDEX IF NOT EXISTS ix_alertas_ts ON alertas(ts);

CREATE TABLE IF NOT EXISTS operaciones (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    alias        TEXT NOT NULL,
    alerta_id    INTEGER,
    lado         TEXT NOT NULL,
    cantidad     REAL,
    precio_num   REAL,
    precio_den   REAL,
    ratio        REAL,
    nota         TEXT
);
CREATE INDEX IF NOT EXISTS ix_oper_alias ON operaciones(alias, ts);

CREATE TABLE IF NOT EXISTS requests (
    fecha     TEXT NOT NULL,
    tipo      TEXT NOT NULL,
    n         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (fecha, tipo)
);

CREATE TABLE IF NOT EXISTS estado (
    clave     TEXT PRIMARY KEY,
    valor     TEXT
);
"""


def conn():
    c = getattr(_local, "c", None)
    if c is None:
        d = os.path.dirname(RUTA)
        if d:
            os.makedirs(d, exist_ok=True)
        c = sqlite3.connect(RUTA, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c


def init():
    c = conn()
    c.executescript(ESQUEMA)
    # migracion desde 0.1.x
    cols = {r["name"] for r in c.execute("PRAGMA table_info(lecturas)")}
    for col in ("qc_num", "qv_num", "qc_den", "qv_den"):
        if col not in cols:
            c.execute("ALTER TABLE lecturas ADD COLUMN %s REAL" % col)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(alertas)")}
    if cols and "id" not in cols:
        # la tabla de 0.1.x no tenia clave primaria; hay que rehacerla
        c.execute("ALTER TABLE alertas RENAME TO alertas_v1")
        c.executescript(ESQUEMA)
        c.execute(
            "INSERT INTO alertas (ts, alias, tipo, ratio, nivel, mensaje) "
            "SELECT ts, alias, tipo, ratio, nivel, mensaje FROM alertas_v1")
        c.execute("DROP TABLE alertas_v1")
        c.commit()
        cols = {r["name"] for r in c.execute("PRAGMA table_info(alertas)")}
    for col in ("p_num", "p_den", "qc_num", "qv_num", "qc_den", "qv_den"):
        if col not in cols:
            c.execute("ALTER TABLE alertas ADD COLUMN %s REAL" % col)
    c.commit()


# -- escritura --------------------------------------------------------

def guardar_lectura(alias, ratio, num, den, ts=None):
    ts = ts or datetime.now().isoformat(timespec="seconds")
    c = conn()
    c.execute(
        "INSERT OR REPLACE INTO lecturas "
        "(ts, alias, ratio, p_num, p_den, c_num, v_num, c_den, v_den,"
        " qc_num, qv_num, qc_den, qv_den) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, alias, ratio, num["ref"], den["ref"],
         num["compra"], num["venta"], den["compra"], den["venta"],
         num.get("vol_compra"), num.get("vol_venta"),
         den.get("vol_compra"), den.get("vol_venta")))
    c.commit()


def guardar_cierres(simbolo, filas):
    c = conn()
    c.executemany(
        "INSERT OR IGNORE INTO cierres (fecha, simbolo, cierre) VALUES (?,?,?)",
        [(f, simbolo, v) for f, v in filas])
    c.commit()


def registrar_alerta(alias, tipo, ratio, nivel, mensaje, num=None, den=None):
    num = num or {}
    den = den or {}
    c = conn()
    cur = c.execute(
        "INSERT INTO alertas (ts, alias, tipo, ratio, nivel, mensaje,"
        " p_num, p_den, qc_num, qv_num, qc_den, qv_den) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), alias, tipo, ratio,
         nivel, mensaje, num.get("ref"), den.get("ref"),
         num.get("vol_compra"), num.get("vol_venta"),
         den.get("vol_compra"), den.get("vol_venta")))
    c.commit()
    return cur.lastrowid


def registrar_operacion(alias, lado, cantidad, precio_num, precio_den,
                        alerta_id=None, nota=None):
    ratio = (precio_num / precio_den) if precio_den else None
    c = conn()
    cur = c.execute(
        "INSERT INTO operaciones "
        "(ts, alias, alerta_id, lado, cantidad, precio_num, precio_den, ratio, nota) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), alias, alerta_id,
         lado, cantidad, precio_num, precio_den, ratio, nota))
    c.commit()
    return cur.lastrowid


def contar_request(tipo):
    hoy = datetime.now().date().isoformat()
    c = conn()
    c.execute(
        "INSERT INTO requests (fecha, tipo, n) VALUES (?,?,1) "
        "ON CONFLICT(fecha, tipo) DO UPDATE SET n = n + 1", (hoy, tipo))
    c.commit()


def set_estado(clave, valor):
    c = conn()
    c.execute("INSERT OR REPLACE INTO estado (clave, valor) VALUES (?,?)",
              (clave, str(valor)))
    c.commit()


def get_estado(clave, default=None):
    r = conn().execute(
        "SELECT valor FROM estado WHERE clave=?", (clave,)).fetchone()
    return r["valor"] if r else default


# -- lectura ----------------------------------------------------------


def serie_propia_diaria(alias, desde=None):
    """Cierre diario del ratio segun nuestras propias lecturas.

    Es la serie consistente: siempre el mismo plazo y la misma fuente.
    """
    q = "SELECT substr(ts,1,10) f, ratio FROM lecturas WHERE alias=?"
    args = [alias]
    if desde:
        q += " AND ts >= ?"
        args.append(desde)
    q += " ORDER BY ts"
    ultimo = {}
    for r in conn().execute(q, args):
        ultimo[r["f"]] = r["ratio"]
    return sorted(ultimo.items())


def cierres_de(simbolo, desde=None):
    q = "SELECT fecha, cierre FROM cierres WHERE simbolo=?"
    args = [simbolo]
    if desde:
        q += " AND fecha >= ?"
        args.append(desde)
    q += " ORDER BY fecha"
    return conn().execute(q, args).fetchall()


def ultimo_cierre_guardado(simbolo):
    r = conn().execute(
        "SELECT MAX(fecha) f FROM cierres WHERE simbolo=?", (simbolo,)).fetchone()
    return r["f"] if r and r["f"] else None


def serie_ratio_diaria(num, den, desde=None):
    """Ratio de cierres historicos de IOL. Puede mezclar plazos."""
    a = {r["fecha"]: r["cierre"] for r in cierres_de(num, desde)}
    b = {r["fecha"]: r["cierre"] for r in cierres_de(den, desde)}
    fechas = sorted(set(a) & set(b))
    return [(f, a[f] / b[f]) for f in fechas if b[f]]


def alertas_recientes(n=40):
    return conn().execute(
        "SELECT * FROM alertas ORDER BY ts DESC LIMIT ?", (n,)).fetchall()



def operaciones_recientes(n=60):
    return conn().execute(
        "SELECT * FROM operaciones ORDER BY ts DESC LIMIT ?", (n,)).fetchall()


def resumen_requests(dias=30):
    """Consumo de la API.

    Las fechas se calculan en Python y no con date('now'), que en SQLite
    es UTC: despues de las 21 hora argentina ya es el dia siguiente en
    UTC y el contador de hoy daba cero.
    """
    c = conn()
    hoy_str = datetime.now().date().isoformat()
    desde = (datetime.now().date() - timedelta(days=dias)).isoformat()
    mes_str = hoy_str[:7]

    por_dia = c.execute(
        "SELECT fecha, SUM(n) n FROM requests "
        "WHERE fecha >= ? GROUP BY fecha ORDER BY fecha", (desde,)).fetchall()
    por_tipo = c.execute(
        "SELECT tipo, SUM(n) n FROM requests "
        "WHERE substr(fecha,1,7) = ? GROUP BY tipo ORDER BY n DESC",
        (mes_str,)).fetchall()
    mes = c.execute(
        "SELECT COALESCE(SUM(n),0) n FROM requests "
        "WHERE substr(fecha,1,7) = ?", (mes_str,)).fetchone()["n"]
    hoy = c.execute(
        "SELECT COALESCE(SUM(n),0) n FROM requests "
        "WHERE fecha = ?", (hoy_str,)).fetchone()["n"]
    return {
        "mes": mes,
        "hoy": hoy,
        "por_dia": [{"fecha": r["fecha"], "n": r["n"]} for r in por_dia],
        "por_tipo": [{"tipo": r["tipo"], "n": r["n"]} for r in por_tipo],
    }


def purgar(dias=400):
    c = conn()
    c.execute("DELETE FROM lecturas WHERE ts < date('now', ?)", ("-%d days" % dias,))
    c.execute("DELETE FROM requests WHERE fecha < date('now', ?)", ("-%d days" % dias,))
    c.commit()


# =====================================================================
#  Posición: grupos de tickers rotables y sus movimientos
# =====================================================================

ESQUEMA_POSICION = """
CREATE TABLE IF NOT EXISTS grupos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL UNIQUE,
    base      TEXT NOT NULL,          -- ticker en el que se mide todo
    tickers   TEXT NOT NULL,          -- JSON: lista de tickers del grupo
    mercado   TEXT DEFAULT 'bCBA',
    creado    TEXT NOT NULL,
    -- Lo que antes vivia en la configuracion como "par". Un grupo de dos
    -- tickers ES un par: tenerlo en dos lados los desincronizaba.
    num       TEXT,                   -- numerador del ratio
    den       TEXT,                   -- denominador
    plazo     TEXT DEFAULT 't1',
    resistencia REAL,
    soporte     REAL,
    alertas   INTEGER NOT NULL DEFAULT 1,
    factor    REAL
);

CREATE TABLE IF NOT EXISTS movimientos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    grupo_id   INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    tipo       TEXT NOT NULL,         -- rotacion | aporte | retiro
    ticker_de  TEXT,                  -- rotacion: de donde sale
    cant_de    REAL,
    ticker_a   TEXT,                  -- rotacion: a donde va / aporte-retiro: el ticker
    cant_a     REAL,
    ratio_base REAL,                  -- equivalente en la unidad base al momento
    equiv_antes REAL,                 -- equivalente total justo antes del movimiento
    nota       TEXT
);
CREATE INDEX IF NOT EXISTS ix_mov_grupo ON movimientos(grupo_id, ts);
"""


COLS_GRUPO_NUEVAS = (("num", "TEXT"), ("den", "TEXT"),
                     ("plazo", "TEXT DEFAULT 't1'"),
                     ("resistencia", "REAL"), ("soporte", "REAL"),
                     ("alertas", "INTEGER NOT NULL DEFAULT 1"),
                     ("factor", "REAL"))


def init_posicion():
    c = conn()
    c.executescript(ESQUEMA_POSICION)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(movimientos)")}
    if "equiv_antes" not in cols:
        c.execute("ALTER TABLE movimientos ADD COLUMN equiv_antes REAL")
    # bases de versiones anteriores no tienen los campos del par
    cols = {r["name"] for r in c.execute("PRAGMA table_info(grupos)")}
    for nombre, tipo in COLS_GRUPO_NUEVAS:
        if nombre not in cols:
            c.execute("ALTER TABLE grupos ADD COLUMN %s %s" % (nombre, tipo))
    c.commit()


def actualizar_tickers(gid, tickers):
    import json as _json
    c = conn()
    c.execute("UPDATE grupos SET tickers=? WHERE id=?",
              (_json.dumps([t.upper() for t in tickers]), gid))
    c.commit()


def actualizar_par(gid, campos):
    """Los datos del ratio: numerador, denominador y zonas."""
    permitidos = ("num", "den", "plazo", "resistencia", "soporte",
                  "alertas", "factor", "nombre", "base", "mercado")
    sets, args = [], []
    for k, v in (campos or {}).items():
        if k in permitidos:
            sets.append("%s=?" % k)
            args.append(int(v) if k == "alertas" else v)
    if not sets:
        return 0
    args.append(gid)
    c = conn()
    cur = c.execute("UPDATE grupos SET %s WHERE id=?" % ",".join(sets), args)
    c.commit()
    return cur.rowcount


def pares_guardados(solo_completos=True):
    """Los grupos, en la forma que espera el monitor.

    Un grupo con numerador y denominador es un par: se le calcula ratio,
    zona y alertas. Los que no los tienen se saltean.
    """
    out = []
    for g in listar_grupos():
        tickers = g.get("tickers") or []
        num = g["num"] or (tickers[0] if tickers else "")
        den = g["den"] or (tickers[1] if len(tickers) > 1 else "")
        if solo_completos and not (num and den):
            continue
        out.append({
            "id": g["id"], "alias": g["nombre"], "num": num, "den": den,
            "mercado": g["mercado"] or "bCBA", "plazo": g["plazo"] or "t1",
            "resistencia": g["resistencia"], "soporte": g["soporte"],
            "alertas": bool(g["alertas"]) if g["alertas"] is not None else True,
            "factor": g["factor"], "base": g["base"], "tickers": tickers,
        })
    return out


def crear_grupo(nombre, base, tickers, mercado="bCBA"):
    import json as _json
    c = conn()
    cur = c.execute(
        "INSERT INTO grupos (nombre, base, tickers, mercado, creado) "
        "VALUES (?,?,?,?,?)",
        (nombre, base, _json.dumps(tickers), mercado,
         datetime.now().isoformat(timespec="seconds")))
    c.commit()
    return cur.lastrowid


def listar_grupos():
    import json as _json
    filas = conn().execute("SELECT * FROM grupos ORDER BY nombre").fetchall()
    out = []
    for f in filas:
        try:
            tickers = _json.loads(f["tickers"])
        except ValueError:
            tickers = []
        g = {"id": f["id"], "nombre": f["nombre"], "base": f["base"],
             "tickers": tickers, "mercado": f["mercado"],
             "creado": f["creado"]}
        # los campos del par, si la base ya los tiene
        for k in ("num", "den", "plazo", "resistencia", "soporte",
                  "alertas", "factor"):
            g[k] = f[k] if k in f.keys() else None
        out.append(g)
    return out


def grupo_por_id(gid):
    for g in listar_grupos():
        if g["id"] == gid:
            return g
    return None



def borrar_grupo(gid):
    c = conn()
    c.execute("DELETE FROM movimientos WHERE grupo_id=?", (gid,))
    c.execute("DELETE FROM grupos WHERE id=?", (gid,))
    c.commit()


def registrar_movimiento(grupo_id, tipo, ticker_de=None, cant_de=None,
                         ticker_a=None, cant_a=None, ratio_base=None,
                         nota=None, ts=None, equiv_antes=None):
    c = conn()
    cur = c.execute(
        "INSERT INTO movimientos "
        "(grupo_id, ts, tipo, ticker_de, cant_de, ticker_a, cant_a,"
        " ratio_base, equiv_antes, nota) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (grupo_id, ts or datetime.now().isoformat(timespec="seconds"), tipo,
         ticker_de, cant_de, ticker_a, cant_a, ratio_base, equiv_antes, nota))
    c.commit()
    return cur.lastrowid


def movimientos_de(grupo_id):
    return conn().execute(
        "SELECT * FROM movimientos WHERE grupo_id=? ORDER BY ts, id",
        (grupo_id,)).fetchall()


def borrar_movimiento(mid):
    c = conn()
    c.execute("DELETE FROM movimientos WHERE id=?", (mid,))
    c.commit()


def borrar_operacion(oid):
    c = conn()
    c.execute("DELETE FROM operaciones WHERE id=?", (oid,))
    c.commit()


# -- opciones ---------------------------------------------------------

ESQUEMA_OPCIONES = """
CREATE TABLE IF NOT EXISTS opc_posiciones (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  combo       TEXT NOT NULL,
  subyacente  TEXT NOT NULL,
  estructura  TEXT NOT NULL,
  vencimiento TEXT NOT NULL,
  base_compra REAL NOT NULL,
  base_venta  REAL NOT NULL,
  sim_compra  TEXT,
  sim_venta   TEXT,
  lotes       INTEGER NOT NULL DEFAULT 1,
  riesgo      REAL NOT NULL,
  ancho       REAL NOT NULL,
  spot_alta   REAL,
  abierta_el  TEXT NOT NULL,
  cerrada_el  TEXT,
  precio_salida REAL,
  resultado   REAL,
  nota        TEXT
);
CREATE TABLE IF NOT EXISTS opc_hist (
  combo   TEXT NOT NULL,
  fecha   TEXT NOT NULL,
  riesgo_pct REAL,
  riesgo  REAL,
  lotes   INTEGER,
  spot    REAL,
  PRIMARY KEY (combo, fecha)
);
CREATE TABLE IF NOT EXISTS opc_seguidas (
  combo   TEXT PRIMARY KEY,
  desde   TEXT NOT NULL,
  silenciada INTEGER NOT NULL DEFAULT 0
);
"""


def init_opciones():
    c = conn()
    c.executescript(ESQUEMA_OPCIONES)
    c.commit()


def opc_guardar_cierres(filas):
    """Un punto por dia y combinacion. Se pisa si ya existe."""
    if not filas:
        return 0
    c = conn()
    c.executemany(
        "INSERT OR REPLACE INTO opc_hist "
        "(combo, fecha, riesgo_pct, riesgo, lotes, spot) VALUES (?,?,?,?,?,?)",
        filas)
    c.commit()
    return len(filas)


def opc_serie(combo, desde=None):
    q = "SELECT fecha, riesgo_pct, riesgo, lotes, spot FROM opc_hist WHERE combo=?"
    args = [combo]
    if desde:
        q += " AND fecha >= ?"
        args.append(desde)
    q += " ORDER BY fecha"
    return [dict(r) for r in conn().execute(q, args)]


def opc_crear_posicion(d):
    c = conn()
    cur = c.execute(
        "INSERT INTO opc_posiciones (combo, subyacente, estructura, "
        "vencimiento, base_compra, base_venta, sim_compra, sim_venta, lotes, "
        "riesgo, ancho, spot_alta, abierta_el, nota) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d["combo"], d["subyacente"], d["estructura"], d["vencimiento"],
         d["base_compra"], d["base_venta"], d.get("sim_compra"),
         d.get("sim_venta"), int(d.get("lotes") or 1), d["riesgo"],
         d["ancho"], d.get("spot_alta"),
         d.get("abierta_el") or datetime.now().isoformat(timespec="seconds"),
         d.get("nota")))
    c.commit()
    return cur.lastrowid


def opc_posiciones(abiertas=None):
    q = "SELECT * FROM opc_posiciones"
    if abiertas is True:
        q += " WHERE cerrada_el IS NULL"
    elif abiertas is False:
        q += " WHERE cerrada_el IS NOT NULL"
    q += " ORDER BY abierta_el DESC"
    return [dict(r) for r in conn().execute(q)]


def opc_actualizar_posicion(pid, campos):
    permitidos = ("lotes", "riesgo", "ancho", "spot_alta", "nota",
                  "base_compra", "base_venta", "sim_compra", "sim_venta")
    sets, args = [], []
    for k, v in (campos or {}).items():
        if k in permitidos:
            sets.append("%s=?" % k)
            args.append(v)
    if not sets:
        return 0
    args.append(pid)
    c = conn()
    cur = c.execute("UPDATE opc_posiciones SET %s WHERE id=?" % ",".join(sets),
                    args)
    c.commit()
    return cur.rowcount


def opc_cerrar_posicion(pid, precio_salida, resultado=None):
    c = conn()
    cur = c.execute(
        "UPDATE opc_posiciones SET cerrada_el=?, precio_salida=?, resultado=? "
        "WHERE id=? AND cerrada_el IS NULL",
        (datetime.now().isoformat(timespec="seconds"), precio_salida,
         resultado, pid))
    c.commit()
    return cur.rowcount


def opc_borrar_posicion(pid):
    c = conn()
    cur = c.execute("DELETE FROM opc_posiciones WHERE id=?", (pid,))
    c.commit()
    return cur.rowcount


def opc_seguir(combo, seguir=True):
    c = conn()
    if seguir:
        c.execute("INSERT OR IGNORE INTO opc_seguidas (combo, desde) "
                  "VALUES (?,?)",
                  (combo, datetime.now().isoformat(timespec="seconds")))
    else:
        c.execute("DELETE FROM opc_seguidas WHERE combo=?", (combo,))
    c.commit()


def opc_silenciar(combo, silenciar=True):
    c = conn()
    c.execute("INSERT OR IGNORE INTO opc_seguidas (combo, desde) VALUES (?,?)",
              (combo, datetime.now().isoformat(timespec="seconds")))
    c.execute("UPDATE opc_seguidas SET silenciada=? WHERE combo=?",
              (1 if silenciar else 0, combo))
    c.commit()


def opc_marcas():
    return {r["combo"]: dict(r)
            for r in conn().execute("SELECT * FROM opc_seguidas")}


# -- registro de llamadas a la API ------------------------------------

ESQUEMA_API_LOG = """
CREATE TABLE IF NOT EXISTS api_log (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ts     TEXT NOT NULL,
  ruta   TEXT NOT NULL,
  tipo   TEXT,
  status INTEGER,
  ms     INTEGER,
  origen TEXT
);
CREATE INDEX IF NOT EXISTS ix_api_log_ts ON api_log(ts);
"""

RETENCION_API_LOG = 7      # dias


def init_api_log():
    c = conn()
    c.executescript(ESQUEMA_API_LOG)
    c.commit()


def registrar_llamada(ruta, tipo=None, status=None, ms=None, origen=None):
    """Una fila por request a IOL, con la direccion completa.

    Es lo unico que permite ver de donde sale el consumo: el contador por
    tipo dice cuantas, no cuales.
    """
    try:
        c = conn()
        c.execute(
            "INSERT INTO api_log (ts, ruta, tipo, status, ms, origen) "
            "VALUES (?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), ruta, tipo,
             status, ms, origen))
        c.commit()
    except Exception:
        pass       # el log nunca debe romper una consulta


def api_log(limite=300, desde=None, ruta=None):
    q = "SELECT * FROM api_log WHERE 1=1"
    args = []
    if desde:
        q += " AND ts >= ?"
        args.append(desde)
    if ruta:
        q += " AND ruta LIKE ?"
        args.append("%" + ruta + "%")
    q += " ORDER BY id DESC LIMIT ?"
    args.append(int(limite))
    return [dict(r) for r in conn().execute(q, args)]


def api_log_resumen(dias=7):
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    c = conn()
    por_ruta = c.execute(
        "SELECT ruta, tipo, COUNT(*) n, MAX(ts) ultima, "
        "       CAST(AVG(ms) AS INTEGER) ms "
        "FROM api_log WHERE ts >= ? GROUP BY ruta ORDER BY n DESC LIMIT 60",
        (desde,)).fetchall()
    por_origen = c.execute(
        "SELECT COALESCE(origen,'?') origen, COUNT(*) n FROM api_log "
        "WHERE ts >= ? GROUP BY origen ORDER BY n DESC", (desde,)).fetchall()
    # Por fuente: el cupo que hay que cuidar es el de IOL, y mezclarlo
    # con el BCRA y BYMA hacia ilegible el total.
    por_fuente = c.execute(
        "SELECT CASE "
        "         WHEN tipo LIKE 'bcra%' THEN 'BCRA' "
        "         WHEN tipo = 'byma' THEN 'BYMA' "
        "         ELSE 'IOL' END fuente, "
        "       COUNT(*) n, SUM(status >= 400 OR status IS NULL) errores, "
        "       CAST(AVG(ms) AS INTEGER) ms, MAX(ts) ultima "
        "FROM api_log WHERE ts >= ? GROUP BY fuente ORDER BY n DESC",
        (desde,)).fetchall()
    total = c.execute("SELECT COUNT(*) n FROM api_log WHERE ts >= ?",
                      (desde,)).fetchone()["n"]
    return {"dias": dias, "total": total,
            "por_fuente": [dict(r) for r in por_fuente],
            "por_ruta": [dict(r) for r in por_ruta],
            "por_origen": [dict(r) for r in por_origen]}


def borrar_api_log():
    """Vacia el registro entero. Util para medir desde cero: se limpia,
    se hace algo, y lo que aparece es exactamente eso."""
    c = conn()
    n = c.execute("SELECT COUNT(*) n FROM api_log").fetchone()["n"]
    c.execute("DELETE FROM api_log")
    c.commit()
    return n


def purgar_api_log(dias=RETENCION_API_LOG):
    c = conn()
    c.execute("DELETE FROM api_log WHERE ts < ?",
              ((datetime.now() - timedelta(days=dias)).isoformat(),))
    c.commit()


# -- cache de catalogo ------------------------------------------------

def cache_get(clave, horas):
    """Valor cacheado si no vencio, o None.

    Para datos que no cambian todos los dias: la lista de instrumentos,
    los paneles de cada instrumento, las series que pertenecen a un
    subyacente. Pedirlos en cada visita gasta cupo sin traer nada nuevo.
    """
    r = conn().execute(
        "SELECT valor FROM estado WHERE clave = ?", ("cache:" + clave,)
    ).fetchone()
    if not r:
        return None
    try:
        d = json.loads(r["valor"])
        puesto = datetime.fromisoformat(d["ts"])
    except Exception:
        return None
    if (datetime.now() - puesto).total_seconds() > horas * 3600:
        return None
    return d.get("v")


def cache_set(clave, valor):
    set_estado("cache:" + clave, json.dumps(
        {"ts": datetime.now().isoformat(timespec="seconds"), "v": valor}))


def cache_borrar(prefijo=""):
    c = conn()
    cur = c.execute("DELETE FROM estado WHERE clave LIKE ?",
                    ("cache:" + prefijo + "%",))
    c.commit()
    return cur.rowcount


# -- alertas de precio y tenencias ------------------------------------

ESQUEMA_ALERTAS = """
CREATE TABLE IF NOT EXISTS alerta_precio (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  titulo TEXT NOT NULL,
  modo   TEXT NOT NULL DEFAULT 'todas',
  activa INTEGER NOT NULL DEFAULT 1,
  creada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerta_cond (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  alerta_id INTEGER NOT NULL,
  simbolo   TEXT NOT NULL,
  operacion TEXT NOT NULL,
  precio    REAL NOT NULL,
  orden     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_cond_alerta ON alerta_cond(alerta_id);
CREATE TABLE IF NOT EXISTS alerta_fecha (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  titulo     TEXT NOT NULL,
  fecha      TEXT NOT NULL,
  dias_antes INTEGER NOT NULL DEFAULT 0,
  nota       TEXT,
  activa     INTEGER NOT NULL DEFAULT 1,
  avisada    TEXT,
  creada     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenencia (
  broker   TEXT NOT NULL,
  simbolo  TEXT NOT NULL,
  cantidad REAL NOT NULL,
  tipo     TEXT,
  ts       TEXT NOT NULL,
  PRIMARY KEY (broker, simbolo)
);

-- Foto de la tenencia cada vez que se actualiza. Una fila por especie y
-- fecha: es lo que despues permite ver como evoluciono una posicion y
-- deducir los movimientos que no se cargaron a mano.
CREATE TABLE IF NOT EXISTS tenencia_hist (
  fecha    TEXT NOT NULL,
  broker   TEXT NOT NULL,
  simbolo  TEXT NOT NULL,
  cantidad REAL NOT NULL,
  tipo     TEXT,
  PRIMARY KEY (fecha, broker, simbolo)
);
CREATE INDEX IF NOT EXISTS ix_tenhist ON tenencia_hist(broker, simbolo, fecha);

-- Splits, canjes y cambios de lamina. El factor es cuantas unidades
-- nuevas salen de cada vieja: un split 1 a 10 va con factor 10. Las
-- cantidades ya llegan ajustadas desde el broker, pero el PPC no
-- siempre, y la serie de precios tampoco.
CREATE TABLE IF NOT EXISTS evento_societario (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  simbolo TEXT NOT NULL,
  fecha   TEXT NOT NULL,
  factor  REAL NOT NULL,
  nota    TEXT,
  creado  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evento_sim ON evento_societario(simbolo, fecha);

-- Por que se tiene cada cosa. No guarda cantidades: esas salen de la
-- tenencia y se actualizan solas. `grupo_id` la ata a un grupo de
-- rotacion existente en lugar de duplicarlo.
CREATE TABLE IF NOT EXISTS estrategia (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre   TEXT NOT NULL,
  familia  TEXT NOT NULL,
  tesis    TEXT,
  origen   TEXT,
  -- Contra que se mide. En reserva de valor es el patron (dolar, CER o
  -- BADLAR); en oportunidad cambiaria, el tipo de cambio de entrada.
  patron   TEXT,
  patron_valor REAL,
  objetivo REAL,
  stop     REAL,
  revisar  TEXT,                     -- fecha para volver a mirarla
  grupo_id INTEGER,
  alta     TEXT NOT NULL,
  cierre   TEXT,
  motivo_cierre TEXT,
  -- Copiados de la ultima medicion al cerrar.
  res_final REAL,
  res_patron_final REAL,
  valor_final REAL,
  dias_final INTEGER
);
CREATE INDEX IF NOT EXISTS ix_estr_familia ON estrategia(familia, cierre);

-- Una especie de un broker pertenece a una sola estrategia.
CREATE TABLE IF NOT EXISTS estrategia_especie (
  estrategia_id INTEGER NOT NULL,
  broker        TEXT NOT NULL,
  simbolo       TEXT NOT NULL,
  PRIMARY KEY (broker, simbolo)
);
CREATE INDEX IF NOT EXISTS ix_ee_estr ON estrategia_especie(estrategia_id);

-- Como venia cada estrategia dia a dia. Sirve para ver la evolucion y,
-- sobre todo, para congelar el resultado al cerrarla: cuando se cierra
-- ya no hay tenencia y no habria con que calcularlo.
CREATE TABLE IF NOT EXISTS estrategia_hist (
  estrategia_id INTEGER NOT NULL,
  fecha         TEXT NOT NULL,
  valor         REAL,
  costo         REAL,
  rendimiento_pct REAL,
  patron_pct    REAL,
  contra_patron_pct REAL,
  PRIMARY KEY (estrategia_id, fecha)
);

-- Lo que el diff entre dos fotos deduce que paso. No se aplica solo:
-- queda pendiente hasta que se confirma, porque una foto no distingue
-- una rotacion de dos operaciones sueltas del mismo dia.
CREATE TABLE IF NOT EXISTS mov_propuesto (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  detectado TEXT NOT NULL,
  broker    TEXT NOT NULL,
  desde     TEXT NOT NULL,          -- fecha de la foto anterior
  hasta     TEXT NOT NULL,          -- fecha de la foto nueva
  tipo      TEXT NOT NULL,          -- rotacion | aporte | retiro
  sale      TEXT,
  cant_sale REAL,
  entra     TEXT,
  cant_entra REAL,
  ratio     REAL,
  grupo_id  INTEGER,
  estado    TEXT NOT NULL DEFAULT 'pendiente',
  UNIQUE (broker, desde, hasta, tipo, sale, entra)
);
CREATE INDEX IF NOT EXISTS ix_mp_estado ON mov_propuesto(estado, detectado);
"""

# Como se mide cada una y que campos le sirven. El patron no es un
# adorno: una reserva de valor que sube 40% en pesos con el dolar 60%
# arriba es una estrategia que fallo, y sin declarar contra que se mide
# eso se lee como ganancia.
# `campos` es lo que se carga en cada titulo y no en la estrategia: el
# stop de MIRG es de MIRG, y el ticker contra el que se rota tambien. La
# estrategia agrupa y mide; los parametros son de la posicion.
FAMILIAS = {
    "rotacion":   {"nombre": "Rotación", "patron": False,
                   "campos": ("par_ticker", "ratio_min", "ratio_max")},
    "intradiaria": {"nombre": "Intradiaria", "patron": False,
                    "campos": ("par_ticker",)},
    "tecnica":    {"nombre": "Trading", "patron": False,
                   "campos": ("stop", "objetivo")},
    "opciones":   {"nombre": "Opciones", "patron": False,
                   "campos": ("stop", "objetivo")},
    "reserva":    {"nombre": "Reserva de valor", "patron": True,
                   "campos": ()},
    "cambiaria":  {"nombre": "Oportunidad cambiaria", "patron": True,
                   "campos": ()},
}
# La fecha de revision aplica a cualquier familia.
CAMPOS_POSICION = ("stop", "objetivo", "par_ticker", "ratio_min",
                   "ratio_max", "revisar")
PATRONES = ("dolar", "cer", "badlar", "tc_entrada")


# Los que puede tener una tenencia. Salen de como agrupa el broker.
TIPOS_TENENCIA = ("moneda", "bonos", "letras", "bcra", "on", "cedears",
                  "acciones", "fci", "otros")


def init_alertas():
    c = conn()
    c.executescript(ESQUEMA_ALERTAS)
    # bases de versiones anteriores no tienen la columna
    cols = {r["name"] for r in c.execute("PRAGMA table_info(tenencia)")}
    if "tipo" not in cols:
        c.execute("ALTER TABLE tenencia ADD COLUMN tipo TEXT")
    # Costo de entrada. Se carga a mano o pegando el JSON: ningun broker
    # lo devuelve por API. "precision" dice si la fecha es exacta, si
    # solo se sabe el mes o si es un "antes de".
    for tabla in ("alerta_precio", "alerta_fecha"):
        try:
            hay = {r["name"] for r in c.execute("PRAGMA table_info(%s)" % tabla)}
        except Exception:
            continue
        # Con estrategia son de vigilancia, sin ella de busqueda: es la
        # unica diferencia, no hacen falta tablas nuevas.
        if hay and "estrategia_id" not in hay:
            c.execute("ALTER TABLE %s ADD COLUMN estrategia_id INTEGER" % tabla)
    for col in ("ppc REAL", "fecha_alta TEXT", "precision TEXT",
                "ppc_base REAL", "stop REAL", "objetivo REAL",
                "par_ticker TEXT", "ratio_min REAL", "ratio_max REAL",
                "revisar TEXT"):
        if col.split()[0] not in cols:
            c.execute("ALTER TABLE tenencia ADD COLUMN " + col)
    try:
        ce = {r["name"] for r in c.execute("PRAGMA table_info(estrategia)")}
        for col in ("res_final REAL", "res_patron_final REAL",
                    "valor_final REAL", "dias_final INTEGER"):
            if col.split()[0] not in ce:
                c.execute("ALTER TABLE estrategia ADD COLUMN " + col)
    except Exception as e:
        log.warning("migrar estrategia: %s", e)
    _migrar_parametros(c)
    c.commit()


def _migrar_parametros(c):
    """Baja stop, objetivo y revisar de la estrategia a sus especies.

    Estaban en la estrategia, lo que obligaba a crear una por accion para
    poder ponerle su propio stop. Son de la posicion: el stop de MIRG es
    de MIRG. Se copia una sola vez y respeta lo que la tenencia ya tenga.
    """
    try:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(estrategia)")}
    except Exception:
        return
    if not {"stop", "objetivo"} <= cols:
        return
    if c.execute("SELECT 1 FROM tenencia WHERE stop IS NOT NULL "
                 "OR objetivo IS NOT NULL LIMIT 1").fetchone():
        return          # ya se hizo
    for e in c.execute("SELECT id, stop, objetivo, revisar FROM estrategia "
                       "WHERE stop IS NOT NULL OR objetivo IS NOT NULL "
                       "OR revisar IS NOT NULL"):
        for esp in c.execute("SELECT broker, simbolo FROM estrategia_especie "
                             "WHERE estrategia_id = ?", (e["id"],)):
            c.execute(
                "UPDATE tenencia SET stop = COALESCE(stop, ?), "
                "objetivo = COALESCE(objetivo, ?), "
                "revisar = COALESCE(revisar, ?) "
                "WHERE broker = ? AND simbolo = ?",
                (e["stop"], e["objetivo"], e["revisar"],
                 esp["broker"], esp["simbolo"]))


def alertas_fecha(solo_activas=False):
    q = "SELECT * FROM alerta_fecha"
    if solo_activas:
        q += " WHERE activa = 1"
    q += " ORDER BY fecha"
    return [dict(r) for r in conn().execute(q)]


def guardar_alerta_fecha(d, aid=None):
    c = conn()
    titulo = (d.get("titulo") or "").strip() or "Sin titulo"
    fecha = str(d.get("fecha") or "")[:10]
    try:
        dias = max(0, int(d.get("dias_antes") or 0))
    except (TypeError, ValueError):
        dias = 0
    nota = (d.get("nota") or "").strip() or None
    if aid:
        # al cambiar la fecha se vuelve a habilitar el aviso
        c.execute("UPDATE alerta_fecha SET titulo=?, fecha=?, dias_antes=?, "
                  "nota=?, avisada=NULL WHERE id=?",
                  (titulo, fecha, dias, nota, aid))
    else:
        cur = c.execute(
            "INSERT INTO alerta_fecha (titulo, fecha, dias_antes, nota, creada)"
            " VALUES (?,?,?,?,?)",
            (titulo, fecha, dias, nota,
             datetime.now().isoformat(timespec="seconds")))
        aid = cur.lastrowid
    c.commit()
    return aid


def marcar_alerta_fecha(aid):
    c = conn()
    c.execute("UPDATE alerta_fecha SET avisada=? WHERE id=?",
              (datetime.now().isoformat(timespec="seconds"), aid))
    c.commit()


def activar_alerta_fecha(aid, activa):
    c = conn()
    c.execute("UPDATE alerta_fecha SET activa=? WHERE id=?",
              (1 if activa else 0, aid))
    c.commit()


def borrar_alerta_fecha(aid):
    c = conn()
    cur = c.execute("DELETE FROM alerta_fecha WHERE id=?", (aid,))
    c.commit()
    return cur.rowcount


def alertas_precio(solo_activas=False):
    c = conn()
    q = "SELECT * FROM alerta_precio"
    if solo_activas:
        q += " WHERE activa = 1"
    q += " ORDER BY id"
    out = []
    for a in c.execute(q):
        d = dict(a)
        d["condiciones"] = [dict(r) for r in c.execute(
            "SELECT * FROM alerta_cond WHERE alerta_id=? ORDER BY orden, id",
            (a["id"],))]
        out.append(d)
    return out


def guardar_alerta_precio(d, alerta_id=None):
    """Crea o reescribe una alerta con sus condiciones."""
    c = conn()
    titulo = (d.get("titulo") or "").strip() or "Sin titulo"
    modo = "alguna" if (d.get("modo") or "todas") == "alguna" else "todas"
    if alerta_id:
        c.execute("UPDATE alerta_precio SET titulo=?, modo=? WHERE id=?",
                  (titulo, modo, alerta_id))
        c.execute("DELETE FROM alerta_cond WHERE alerta_id=?", (alerta_id,))
    else:
        cur = c.execute(
            "INSERT INTO alerta_precio (titulo, modo, creada) VALUES (?,?,?)",
            (titulo, modo, datetime.now().isoformat(timespec="seconds")))
        alerta_id = cur.lastrowid
    for i, cond in enumerate(d.get("condiciones") or []):
        sim = (cond.get("simbolo") or "").strip().upper()
        op = "comprar" if (cond.get("operacion") or "").lower().startswith("c") \
            else "vender"
        try:
            precio = float(cond.get("precio"))
        except (TypeError, ValueError):
            continue
        if not sim or precio <= 0:
            continue
        c.execute(
            "INSERT INTO alerta_cond (alerta_id, simbolo, operacion, precio, "
            "orden) VALUES (?,?,?,?,?)", (alerta_id, sim, op, precio, i))
    c.commit()
    return alerta_id


def activar_alerta_precio(alerta_id, activa):
    c = conn()
    c.execute("UPDATE alerta_precio SET activa=? WHERE id=?",
              (1 if activa else 0, alerta_id))
    c.commit()


def borrar_alerta_precio(alerta_id):
    c = conn()
    c.execute("DELETE FROM alerta_cond WHERE alerta_id=?", (alerta_id,))
    cur = c.execute("DELETE FROM alerta_precio WHERE id=?", (alerta_id,))
    c.commit()
    return cur.rowcount


def tenencias(broker=None):
    q = "SELECT * FROM tenencia"
    args = []
    if broker:
        q += " WHERE broker = ?"
        args.append(broker)
    q += " ORDER BY broker, simbolo"
    filas = [dict(r) for r in conn().execute(q, args)]
    asig = asignaciones()
    est = {e["id"]: e for e in estrategias(incluir_cerradas=True)}
    for f in filas:
        eid = asig.get((f["broker"], f["simbolo"]))
        f["estrategia_id"] = eid
        e = est.get(eid) if eid else None
        f["estrategia"] = e["nombre"] if e else None
        f["familia"] = e["familia"] if e else None
    return [_con_eventos(f) for f in filas]


def _con_eventos(f):
    """Ajusta el PPC por los splits posteriores a la compra.

    El broker informa la cantidad ya ajustada pero no siempre el PPC, asi
    que el costo queda multiplicado por el factor y el resultado sale al
    reves. Se corrige al leer y no al guardar: el valor original se
    conserva por si el evento se carga mal.
    """
    ppc = f.get("ppc")
    if ppc is None:
        f["ppc_ajustado"] = None
        return f
    alta = f.get("fecha_alta") or ""
    factor, aplicados, supuesto = 1.0, [], False
    for e in eventos(f.get("simbolo")):
        if not e["factor"]:
            continue
        # Sin fecha de compra no se sabe de que lado del evento cae. Se
        # ajusta igual, porque es lo mas probable en una posicion vieja,
        # pero queda marcado para que no se lea como un dato firme.
        if not alta:
            supuesto = True
        elif alta >= e["fecha"]:
            continue
        factor *= float(e["factor"])
        aplicados.append(e["fecha"] + " ×" + ("%g" % e["factor"]))
    f["ppc_ajustado"] = round(ppc / factor, 6) if factor != 1 else ppc
    f["eventos"] = aplicados
    f["ajuste_supuesto"] = supuesto and bool(aplicados)
    return f


def guardar_tenencias(filas, reemplazar="todo"):
    """Pisa la lista entera o la de un broker.

    Reemplazar por broker permite actualizar una cuenta sin tocar la otra,
    que es lo habitual: se mira el saldo de un broker por vez.

    El PPC y la fecha de alta se conservan si la carga nueva no los trae:
    el boton que baja de IOL solo devuelve cantidades, y de otro modo
    borraria el costo cargado a mano en cada actualizacion.
    """
    c = conn()
    previo = {}
    for r in c.execute("SELECT broker, simbolo, ppc, fecha_alta, precision, "
                       "ppc_base FROM tenencia"):
        previo[(r["broker"], r["simbolo"])] = r
    if reemplazar == "todo":
        c.execute("DELETE FROM tenencia")
    elif reemplazar:
        c.execute("DELETE FROM tenencia WHERE broker = ?", (reemplazar,))
    ahora = datetime.now().isoformat(timespec="seconds")
    n, brokers = 0, set()
    for f in filas or []:
        br = (f.get("broker") or "").strip()
        sim = (f.get("simbolo") or "").strip().upper()
        try:
            cant = float(f.get("cantidad"))
        except (TypeError, ValueError):
            continue
        if not br or not sim:
            continue
        tipo = (f.get("tipo") or "").strip().lower()
        if tipo not in TIPOS_TENENCIA:
            tipo = "otros"
        antes = previo.get((br, sim))
        try:
            ppc = float(f["ppc"]) if f.get("ppc") is not None else None
        except (TypeError, ValueError):
            ppc = None
        if ppc is None and antes:
            ppc = antes["ppc"]
        alta = (f.get("fecha_alta") or "").strip() or (
            antes["fecha_alta"] if antes else None)
        prec = (f.get("precision") or "").strip().lower()
        if prec not in ("exacta", "mes", "antes"):
            prec = antes["precision"] if antes else None
        try:
            pbase = float(f["ppc_base"]) if f.get("ppc_base") else None
        except (TypeError, ValueError):
            pbase = None
        if pbase is None and antes:
            pbase = antes["ppc_base"]
        c.execute(
            "INSERT OR REPLACE INTO tenencia "
            "(broker, simbolo, cantidad, tipo, ts, ppc, fecha_alta, "
            "precision, ppc_base) VALUES (?,?,?,?,?,?,?,?,?)",
            (br, sim, cant, tipo, ahora, ppc, alta, prec, pbase))
        brokers.add(br)
        n += 1
    c.commit()
    for br in brokers:
        snapshot(br)
        try:
            detectar_movimientos(br)
        except Exception as e:
            log.warning("diff de %s: %s", br, e)
    cerrar_sin_tenencia()
    return n


def actualizar_tenencia(broker, simbolo, campos):
    """Edita una sola posicion sin tocar el resto.

    La carga por JSON reemplaza el broker entero, que sirve para
    actualizar contra el saldo real pero obliga a mandar todo para
    corregir un dato. Aca se cambia lo que se pasa y nada mas.
    """
    permitidos = ("cantidad", "tipo", "ppc", "ppc_base", "fecha_alta",
                  "precision") + CAMPOS_POSICION
    sets, args = [], []
    for k in permitidos:
        if k not in campos:
            continue
        v = campos[k]
        if k == "tipo":
            v = (v or "").strip().lower()
            if v not in TIPOS_TENENCIA:
                raise ValueError("tipo inválido: %s" % v)
        elif k == "precision":
            v = (v or "").strip().lower() or None
            if v and v not in ("exacta", "mes", "antes"):
                raise ValueError("precisión inválida: %s" % v)
        elif k in ("fecha_alta", "revisar"):
            v = (v or "").strip() or None
        elif k == "par_ticker":
            v = (v or "").strip().upper() or None
        else:
            v = float(v) if v not in (None, "") else None
            if k == "cantidad" and v is None:
                raise ValueError("la cantidad no puede quedar vacía")
        sets.append("%s = ?" % k)
        args.append(v)
    if not sets:
        return 0
    c = conn()
    args += [broker, simbolo.upper()]
    cur = c.execute("UPDATE tenencia SET " + ", ".join(sets) +
                    " WHERE broker = ? AND simbolo = ?", args)
    c.commit()
    if cur.rowcount:
        snapshot(broker)
    return cur.rowcount


def borrar_tenencia(broker, simbolo):
    c = conn()
    cur = c.execute("DELETE FROM tenencia WHERE broker = ? AND simbolo = ?",
                    (broker, simbolo.upper()))
    c.commit()
    if cur.rowcount:
        snapshot(broker)
    return cur.rowcount


def estrategias(incluir_cerradas=False, familia=None):
    q = "SELECT * FROM estrategia WHERE 1=1"
    args = []
    if not incluir_cerradas:
        q += " AND cierre IS NULL"
    if familia:
        q += " AND familia = ?"
        args.append(familia)
    q += " ORDER BY cierre IS NOT NULL, familia, nombre"
    filas = [dict(r) for r in conn().execute(q, args)]
    for f in filas:
        f["especies"] = [dict(r) for r in conn().execute(
            "SELECT broker, simbolo FROM estrategia_especie "
            "WHERE estrategia_id = ? ORDER BY broker, simbolo", (f["id"],))]
    return filas


def guardar_estrategia(datos, eid=None):
    familia = (datos.get("familia") or "").strip().lower()
    if familia not in FAMILIAS:
        raise ValueError("familia inválida: %s" % familia)
    # Sin nombre se usa el de la familia: obligar a inventar uno por cada
    # posicion era lo que hacia crecer la lista sin motivo.
    nombre = (datos.get("nombre") or "").strip() or FAMILIAS[familia]["nombre"]
    patron = (datos.get("patron") or "").strip().lower() or None
    if patron and patron not in PATRONES:
        raise ValueError("patrón inválido: %s" % patron)
    if FAMILIAS[familia]["patron"] and not patron:
        raise ValueError("%s necesita declarar contra qué se mide"
                         % FAMILIAS[familia]["nombre"])

    def num(k):
        v = datos.get(k)
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    campos = (nombre, familia, (datos.get("tesis") or "").strip() or None,
              (datos.get("origen") or "").strip() or None, patron,
              num("patron_valor"), num("objetivo"), num("stop"),
              (datos.get("revisar") or "").strip() or None,
              datos.get("grupo_id") or None)
    c = conn()
    if eid:
        c.execute("UPDATE estrategia SET nombre=?, familia=?, tesis=?, "
                  "origen=?, patron=?, patron_valor=?, objetivo=?, stop=?, "
                  "revisar=?, grupo_id=? WHERE id=?", campos + (eid,))
    else:
        cur = c.execute(
            "INSERT INTO estrategia (nombre, familia, tesis, origen, patron, "
            "patron_valor, objetivo, stop, revisar, grupo_id, alta) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            campos + (datetime.now().date().isoformat(),))
        eid = cur.lastrowid
    c.commit()
    return eid


def fijar_alta(eid, fecha):
    """La estrategia empieza cuando se compró, no cuando se la cargó.

    Importa porque el valor del patrón contra el que se mide sale de esa
    fecha: con la de hoy, el rendimiento contra el CER daría cero.
    """
    c = conn()
    c.execute("UPDATE estrategia SET alta=? WHERE id=?", (fecha, eid))
    c.commit()


def cerrar_estrategia(eid, motivo="manual"):
    """Cierra y congela el resultado.

    Al cerrar ya no queda tenencia, asi que el rendimiento no se puede
    recalcular despues: se copia de la ultima medicion guardada. Sin
    esto, una estrategia archivada no se puede evaluar.
    """
    c = conn()
    hoy = datetime.now().date().isoformat()
    e = c.execute("SELECT alta FROM estrategia WHERE id=?", (eid,)).fetchone()
    ult = c.execute("SELECT * FROM estrategia_hist WHERE estrategia_id=? "
                    "ORDER BY fecha DESC LIMIT 1", (eid,)).fetchone()
    dias = None
    if e and e["alta"]:
        try:
            dias = (datetime.now().date()
                    - datetime.fromisoformat(e["alta"]).date()).days
        except ValueError:
            dias = None
    c.execute(
        "UPDATE estrategia SET cierre=?, motivo_cierre=?, res_final=?, "
        "res_patron_final=?, valor_final=?, dias_final=? "
        "WHERE id=? AND cierre IS NULL",
        (hoy, motivo,
         ult["rendimiento_pct"] if ult else None,
         ult["contra_patron_pct"] if ult else None,
         ult["valor"] if ult else None, dias, eid))
    c.commit()


def reabrir_estrategia(eid):
    c = conn()
    c.execute("UPDATE estrategia SET cierre=NULL, motivo_cierre=NULL "
              "WHERE id=?", (eid,))
    c.commit()


def borrar_estrategia(eid):
    c = conn()
    c.execute("DELETE FROM estrategia_especie WHERE estrategia_id=?", (eid,))
    cur = c.execute("DELETE FROM estrategia WHERE id=?", (eid,))
    c.commit()
    return cur.rowcount


def asignar(broker, simbolo, eid):
    """Ata una especie a una estrategia, o la desata si eid es None.

    La clave primaria es broker mas simbolo, asi que reasignar pisa la
    anterior sin dejar la especie en dos lados.
    """
    c = conn()
    sim = simbolo.upper()
    if eid:
        c.execute("INSERT OR REPLACE INTO estrategia_especie "
                  "(estrategia_id, broker, simbolo) VALUES (?,?,?)",
                  (eid, broker, sim))
    else:
        c.execute("DELETE FROM estrategia_especie WHERE broker=? AND simbolo=?",
                  (broker, sim))
    c.commit()


def asignaciones():
    return {(r["broker"], r["simbolo"]): r["estrategia_id"]
            for r in conn().execute("SELECT * FROM estrategia_especie")}


def asignar_por_grupos():
    """Asigna sola las especies que ya estan en un grupo de rotacion.

    Solo toca las que no tienen estrategia: una asignacion hecha a mano
    nunca se pisa. Devuelve lo que asigno para poder mostrarlo.
    """
    import json as _json
    c = conn()
    ya = asignaciones()
    hechas = []
    for g in c.execute("SELECT * FROM grupos"):
        try:
            tk_todos = [(t or "").strip().upper()
                        for t in _json.loads(g["tickers"] or "[]")]
        except ValueError:
            tk_todos = []
        # Sin ninguna de sus puntas en cartera no hay nada que seguir: el
        # par se mira desde Ratios, que es donde se buscan oportunidades.
        hay = any(c.execute("SELECT 1 FROM tenencia WHERE simbolo=? "
                            "AND cantidad <> 0 LIMIT 1", (t,)).fetchone()
                  for t in tk_todos if t)
        if not hay:
            continue
        est = c.execute("SELECT id FROM estrategia WHERE grupo_id=? "
                        "AND cierre IS NULL", (g["id"],)).fetchone()
        if est:
            eid = est["id"]
        else:
            eid = guardar_estrategia({
                "nombre": g["nombre"], "familia": "rotacion",
                "origen": "grupo de rotación",
                "tesis": "Rotar entre %s manteniendo o subiendo los "
                         "nominales medidos en %s." % (
                             ", ".join(_json.loads(g["tickers"] or "[]"))
                             or "el grupo", g["base"]),
                "grupo_id": g["id"]})
        try:
            tickers = _json.loads(g["tickers"] or "[]")
        except ValueError:
            tickers = []
        for t in tickers:
            sim = (t or "").strip().upper()
            if not sim:
                continue
            for r in c.execute("SELECT broker FROM tenencia WHERE simbolo=?",
                               (sim,)):
                clave = (r["broker"], sim)
                if clave in ya:
                    continue
                asignar(r["broker"], sim, eid)
                ya[clave] = eid
                hechas.append("%s · %s → %s" % (r["broker"], sim, g["nombre"]))
    return hechas


def guardar_medicion(mediciones):
    """Una foto por dia de como viene cada estrategia.

    Se pisa dentro del mismo dia: la ultima del dia es la que vale. De
    aca sale el resultado que se congela al cerrar.
    """
    c = conn()
    hoy = datetime.now().date().isoformat()
    for m in mediciones or []:
        if m.get("rendimiento_pct") is None:
            continue
        c.execute(
            "INSERT OR REPLACE INTO estrategia_hist (estrategia_id, fecha, "
            "valor, costo, rendimiento_pct, patron_pct, contra_patron_pct) "
            "VALUES (?,?,?,?,?,?,?)",
            (m["id"], hoy, m.get("valor"), m.get("costo"),
             m.get("rendimiento_pct"), m.get("patron_pct"),
             m.get("contra_patron_pct")))
    c.commit()


def evolucion(eid, desde=None):
    q = "SELECT * FROM estrategia_hist WHERE estrategia_id = ?"
    args = [eid]
    if desde:
        q += " AND fecha >= ?"
        args.append(desde)
    return [dict(r) for r in conn().execute(q + " ORDER BY fecha", args)]


def borrar_vacias():
    """Borra las estrategias que nunca tuvieron especies asignadas.

    Salen del alta automatica por grupos cuando el par existe pero no se
    tiene ninguna de sus puntas. No toca las que quedaron sin especies
    despues de vender: esas se cierran, que conserva la historia.
    """
    c = conn()
    ids = [r["id"] for r in c.execute(
        "SELECT e.id FROM estrategia e LEFT JOIN estrategia_especie s "
        "ON s.estrategia_id = e.id WHERE s.estrategia_id IS NULL "
        "AND e.cierre IS NULL")]
    nombres = []
    for eid in ids:
        r = c.execute("SELECT nombre FROM estrategia WHERE id=?",
                      (eid,)).fetchone()
        if r:
            nombres.append(r["nombre"])
        c.execute("DELETE FROM estrategia WHERE id=?", (eid,))
    c.commit()
    return nombres


def cerrar_sin_tenencia():
    """Cierra las estrategias cuyas especies ya no estan en cartera.

    Se corre despues de cargar tenencias. Una estrategia sin especies
    asignadas no se toca: recien creada todavia no tiene ninguna y
    cerrarla seria absurdo.
    """
    c = conn()
    cerradas = []
    for e in c.execute("SELECT id, nombre FROM estrategia WHERE cierre IS NULL"):
        esp = c.execute("SELECT broker, simbolo FROM estrategia_especie "
                        "WHERE estrategia_id=?", (e["id"],)).fetchall()
        if not esp:
            continue
        vivas = 0
        for s in esp:
            r = c.execute("SELECT cantidad FROM tenencia WHERE broker=? "
                          "AND simbolo=?", (s["broker"], s["simbolo"])).fetchone()
            if r and r["cantidad"]:
                vivas += 1
        if not vivas:
            cerrar_estrategia(e["id"], "sin tenencia")
            cerradas.append(e["nombre"])
    return cerradas


def detectar_movimientos(broker):
    """Compara las dos ultimas fotos de un broker y propone que paso.

    Una rotacion solo se propone si las dos especies estan en el mismo
    grupo declarado y se movieron en sentido contrario. El ratio sale de
    la relacion de nominales, que es exacta y no necesita precios ni la
    hora de la operacion. Todo lo demas queda como aporte o retiro.

    No aplica nada: entre dos fotos, dos operaciones sueltas del mismo
    dia se ven igual que una rotacion, y esa diferencia la sabe el que
    opero, no la base.
    """
    import json as _json
    c = conn()
    fechas = [r["fecha"] for r in c.execute(
        "SELECT DISTINCT fecha FROM tenencia_hist WHERE broker=? "
        "ORDER BY fecha DESC LIMIT 2", (broker,))]
    if len(fechas) < 2:
        return []
    hasta, desde = fechas[0], fechas[1]

    def foto(f):
        return {r["simbolo"]: r["cantidad"] for r in c.execute(
            "SELECT simbolo, cantidad FROM tenencia_hist "
            "WHERE broker=? AND fecha=?", (broker, f))}

    a, b = foto(desde), foto(hasta)
    difs = {}
    for sim in set(a) | set(b):
        d = (b.get(sim) or 0) - (a.get(sim) or 0)
        if abs(d) > 1e-9:
            difs[sim] = d

    # Los grupos dicen que especies son intercambiables entre si.
    grupos = []
    for g in c.execute("SELECT id, nombre, tickers FROM grupos"):
        try:
            tk = {t.strip().upper() for t in _json.loads(g["tickers"] or "[]")}
        except ValueError:
            tk = set()
        if tk:
            grupos.append((g["id"], g["nombre"], tk))

    ahora = datetime.now().isoformat(timespec="seconds")
    props, usados = [], set()
    for gid, gnom, tk in grupos:
        bajan = sorted((s for s in difs if s in tk and difs[s] < 0
                        and s not in usados),
                       key=lambda s: difs[s])
        suben = sorted((s for s in difs if s in tk and difs[s] > 0
                        and s not in usados),
                       key=lambda s: -difs[s])
        for sale, entra in zip(bajan, suben):
            cs, ce = -difs[sale], difs[entra]
            props.append({
                "broker": broker, "desde": desde, "hasta": hasta,
                "tipo": "rotacion", "sale": sale, "cant_sale": cs,
                "entra": entra, "cant_entra": ce,
                "ratio": (cs / ce) if ce else None, "grupo_id": gid,
                "grupo": gnom})
            usados.update((sale, entra))

    for sim, d in sorted(difs.items()):
        if sim in usados:
            continue
        props.append({
            "broker": broker, "desde": desde, "hasta": hasta,
            "tipo": "aporte" if d > 0 else "retiro",
            "sale": None if d > 0 else sim,
            "cant_sale": None if d > 0 else -d,
            "entra": sim if d > 0 else None,
            "cant_entra": d if d > 0 else None,
            "ratio": None, "grupo_id": None, "grupo": None})

    for p in props:
        c.execute(
            "INSERT OR IGNORE INTO mov_propuesto (detectado, broker, desde, "
            "hasta, tipo, sale, cant_sale, entra, cant_entra, ratio, grupo_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ahora, broker, desde, hasta, p["tipo"], p["sale"],
             p["cant_sale"], p["entra"], p["cant_entra"], p["ratio"],
             p["grupo_id"]))
    c.commit()
    return props


def movimientos_propuestos(estado="pendiente"):
    q = "SELECT * FROM mov_propuesto"
    args = []
    if estado:
        q += " WHERE estado = ?"
        args.append(estado)
    q += " ORDER BY hasta DESC, id DESC"
    return [dict(r) for r in conn().execute(q, args)]


def resolver_propuesto(mid, accion):
    """Confirma o descarta uno.

    Al confirmar una rotacion se mueve la asignacion de estrategia de la
    especie que sale a la que entra: si no, la estrategia se cerraria
    sola justo cuando se la esta ejecutando bien.
    """
    c = conn()
    p = c.execute("SELECT * FROM mov_propuesto WHERE id=?", (mid,)).fetchone()
    if not p:
        return None
    if accion == "descartar":
        c.execute("UPDATE mov_propuesto SET estado='descartado' WHERE id=?",
                  (mid,))
        c.commit()
        return "descartado"

    if p["tipo"] == "rotacion" and p["sale"] and p["entra"]:
        eid = c.execute("SELECT estrategia_id FROM estrategia_especie "
                        "WHERE broker=? AND simbolo=?",
                        (p["broker"], p["sale"])).fetchone()
        if eid:
            asignar(p["broker"], p["entra"], eid["estrategia_id"])
            c.execute("DELETE FROM estrategia_especie WHERE broker=? "
                      "AND simbolo=?", (p["broker"], p["sale"]))
            # La estrategia recupera una especie viva, asi que si se
            # habia cerrado por quedarse sin tenencia hay que reabrirla.
            e = c.execute("SELECT cierre, motivo_cierre FROM estrategia "
                          "WHERE id=?", (eid["estrategia_id"],)).fetchone()
            if e and e["cierre"] and e["motivo_cierre"] == "sin tenencia":
                reabrir_estrategia(eid["estrategia_id"])
    c.execute("UPDATE mov_propuesto SET estado='confirmado' WHERE id=?", (mid,))
    c.commit()
    return "confirmado"


def snapshot(broker, fecha=None):
    """Guarda la foto del dia para un broker, si cambio.

    Se compara contra el ultimo snapshot de ese broker y no se escribe
    nada si las cantidades son las mismas: actualizar tres veces en un
    dia sin operar no tiene que dejar tres filas iguales.
    """
    c = conn()
    fecha = fecha or datetime.now().date().isoformat()
    actual = {r["simbolo"]: (r["cantidad"], r["tipo"]) for r in c.execute(
        "SELECT simbolo, cantidad, tipo FROM tenencia WHERE broker = ?",
        (broker,))}
    ult = c.execute("SELECT MAX(fecha) f FROM tenencia_hist WHERE broker = ? "
                    "AND fecha < ?", (broker, fecha)).fetchone()
    if ult and ult["f"]:
        previo = {r["simbolo"]: r["cantidad"] for r in c.execute(
            "SELECT simbolo, cantidad FROM tenencia_hist "
            "WHERE broker = ? AND fecha = ?", (broker, ult["f"]))}
        if previo == {k: v[0] for k, v in actual.items()}:
            return 0
    c.execute("DELETE FROM tenencia_hist WHERE broker = ? AND fecha = ?",
              (broker, fecha))
    for sim, (cant, tipo) in actual.items():
        c.execute("INSERT INTO tenencia_hist "
                  "(fecha, broker, simbolo, cantidad, tipo) VALUES (?,?,?,?,?)",
                  (fecha, broker, sim, cant, tipo))
    c.commit()
    return len(actual)


def historial_tenencia(broker=None, simbolo=None, desde=None):
    q = "SELECT * FROM tenencia_hist WHERE 1=1"
    args = []
    for campo, valor in (("broker", broker), ("simbolo", simbolo)):
        if valor:
            q += " AND %s = ?" % campo
            args.append(valor)
    if desde:
        q += " AND fecha >= ?"
        args.append(desde)
    q += " ORDER BY fecha DESC, broker, simbolo"
    return [dict(r) for r in conn().execute(q, args)]


def fechas_snapshot(broker=None):
    q = "SELECT DISTINCT fecha FROM tenencia_hist"
    args = []
    if broker:
        q += " WHERE broker = ?"
        args.append(broker)
    q += " ORDER BY fecha DESC"
    return [r["fecha"] for r in conn().execute(q, args)]


def eventos(simbolo=None):
    q = "SELECT * FROM evento_societario"
    args = []
    if simbolo:
        q += " WHERE simbolo = ?"
        args.append(simbolo.upper())
    q += " ORDER BY fecha"
    return [dict(r) for r in conn().execute(q, args)]


def guardar_evento(simbolo, fecha, factor, nota=None):
    sim = (simbolo or "").strip().upper()
    fecha = (fecha or "").strip()
    factor = float(factor)
    if not sim or not fecha:
        raise ValueError("faltan el símbolo o la fecha")
    if factor <= 0:
        raise ValueError("el factor tiene que ser mayor que cero")
    c = conn()
    cur = c.execute(
        "INSERT INTO evento_societario (simbolo, fecha, factor, nota, creado) "
        "VALUES (?,?,?,?,?)",
        (sim, fecha, factor, (nota or "").strip() or None,
         datetime.now().isoformat(timespec="seconds")))
    c.commit()
    return cur.lastrowid


def borrar_evento(eid):
    c = conn()
    cur = c.execute("DELETE FROM evento_societario WHERE id=?", (eid,))
    c.commit()
    return cur.rowcount


def migrar_pares(pares_cfg):
    """Pasa los pares de la configuracion a la base, una sola vez.

    Si ya existe un grupo con los mismos dos tickers, se completa con los
    datos del par en vez de duplicarlo: el grupo trae los movimientos y
    seria una lastima perderlos.
    """
    import json as _json
    if get_estado("pares_migrados"):
        return {"migrados": 0, "ya_estaba": True}

    existentes = []
    for g in listar_grupos():
        tk = [str(t).upper() for t in (g.get("tickers") or [])]
        existentes.append((set(tk), g))

    creados, completados = [], []
    for p in pares_cfg or []:
        num = (p.get("num") or "").upper()
        den = (p.get("den") or "").upper()
        if not (num and den):
            continue
        campos = {"num": num, "den": den,
                  "plazo": p.get("plazo") or "t1",
                  "resistencia": p.get("resistencia"),
                  "soporte": p.get("soporte"),
                  "alertas": 1 if p.get("alertas", True) else 0,
                  "factor": p.get("factor"),
                  "mercado": p.get("mercado") or "bCBA"}
        par = {num, den}
        g = next((g for tk, g in existentes if tk == par), None)
        if g:
            actualizar_par(g["id"], campos)
            completados.append(g["nombre"])
            continue
        nombre = (p.get("alias") or "%s/%s" % (num, den)).strip()
        base = nombre
        n = 2
        while any(x["nombre"] == base for _, x in existentes):
            base = "%s (%d)" % (nombre, n)
            n += 1
        gid = crear_grupo(base, num, [num, den], campos["mercado"])
        actualizar_par(gid, campos)
        creados.append(base)
        existentes.append(({num, den}, {"id": gid, "nombre": base,
                                        "tickers": [num, den]}))

    set_estado("pares_migrados", datetime.now().isoformat(timespec="seconds"))
    return {"creados": creados, "completados": completados,
            "migrados": len(creados) + len(completados)}
