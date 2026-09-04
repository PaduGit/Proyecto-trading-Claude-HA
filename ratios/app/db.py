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


# Carpeta que Home Assistant mapea como `addon_config`: del lado del host
# es /addon_configs/<slug>, que si se ve desde el add-on de SSH. `/data`
# no: vive en el volumen del Supervisor y se pierde al desinstalar.
RUTA_COPIA = os.environ.get("RATIOS_COPIA", "/config/ratios.db")


def copia_de_seguridad(destino=None):
    """Deja una copia de la base donde se pueda bajar por SSH.

    Se hace al arrancar y con la API de backup de SQLite, que copia una
    base consistente aunque haya escrituras en curso: copiar el archivo
    con `cp` puede dejar una base rota.
    """
    destino = destino or RUTA_COPIA
    carpeta = os.path.dirname(destino)
    if carpeta and not os.path.isdir(carpeta):
        log.debug("sin carpeta para la copia: %s", carpeta)
        return None
    try:
        dst = sqlite3.connect(destino)
        try:
            conn().backup(dst)
        finally:
            dst.close()
        log.info("copia de la base en %s", destino)
        return destino
    except Exception as e:
        log.warning("copia de seguridad: %s", e)
        return None


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
  -- En que nominales se mide la cuotaparte. Uno por estrategia: si vas
  -- TX28 -> TZXD8 -> TX31, la vara sigue siendo el que elegiste al
  -- crearla, aunque ya no lo tengas.
  ticker_base TEXT,
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

-- Una especie pertenece a una sola estrategia, en todos los brokers.
-- Antes la clave incluia el broker: la misma especie en dos cuentas
-- podia colgar de dos estrategias distintas, que no es como se opera.
CREATE TABLE IF NOT EXISTS estrategia_especie (
  estrategia_id INTEGER NOT NULL,
  simbolo       TEXT NOT NULL PRIMARY KEY
);
CREATE INDEX IF NOT EXISTS ix_ee_estr ON estrategia_especie(estrategia_id);

-- El libro de movimientos de la estrategia. Cada fila es un hecho y el
-- aportado sale de sumarlas, no de un campo guardado. Las cantidades de
-- la pantalla NO salen de aca: salen de `tenencia`, para que la tarjeta
-- no pueda quedar vieja. El ledger sirve para medir.
CREATE TABLE IF NOT EXISTS estrategia_mov (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  estrategia_id INTEGER NOT NULL,
  ts            TEXT NOT NULL,      -- el de la foto, no el de la confirmacion
  tipo          TEXT NOT NULL,      -- rotacion | aporte | retiro
  ticker_de     TEXT,
  cant_de       REAL,
  ticker_a      TEXT,
  cant_a        REAL,
  ratio_base    REAL,               -- equivalente en el ticker base
  equiv_antes   REAL,               -- valor de la posicion antes, para la cuota
  propuesto_id  INTEGER,            -- de que propuesta salio
  nota          TEXT
);
CREATE INDEX IF NOT EXISTS ix_em_estr ON estrategia_mov(estrategia_id, ts, id);

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
  desde     TEXT NOT NULL,          -- timestamp de la foto anterior
  hasta     TEXT NOT NULL,          -- timestamp de la foto nueva
  tipo      TEXT NOT NULL,          -- rotacion | aporte | retiro
  sale      TEXT,
  cant_sale REAL,
  entra     TEXT,
  cant_entra REAL,
  ratio     REAL,
  grupo_id  INTEGER,
  -- A que estrategia le pega. Se resuelve al detectar, por simbolo.
  estrategia_id INTEGER,
  -- Con que otra propuesta se unio para armar una rotacion entre
  -- brokers. Vendo AO28 en IOL y compro AO29 en ECO: son dos fotos de
  -- dos brokers distintos y una sola rotacion.
  unido_a   INTEGER,
  -- Precio del simbolo al momento de la foto, en la moneda de la
  -- estrategia. Se guarda al detectar: si confirmas tres dias despues,
  -- el ledger tiene que registrar el precio del hecho, no el de hoy.
  precio_sale  REAL,
  precio_entra REAL,
  -- Precio del ticker base de la estrategia, del mismo momento. La
  -- cuotaparte se mide en nominales del base: sin este precio el aporte
  -- entra al ledger sin `ratio_base` y no se puede medir.
  precio_base  REAL,
  -- Cuanto valia la posicion de la estrategia justo antes, en nominales
  -- del ticker base. Es el valor al que se emiten o rescatan las cuotas:
  -- sin esto el valor de la cuota queda clavado en 1 y el rendimiento
  -- por cuotaparte sale siempre cero.
  equiv_antes  REAL,
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
    "par": {
        "nombre": "Rotación de par", "pestana": "ratios",
        "tenencia": True, "tipos": ("bonos", "letras", "on", "acciones",
                                    "cedears"),
        "campos": ("ratio_min", "ratio_max"),
    },
    "curva": {
        "nombre": "Curva de bonos", "pestana": "bonos",
        "tenencia": True, "tipos": ("bonos", "letras", "on"),
        "campos": (),
    },
    "reserva_renta_fija": {
        "nombre": "Reserva de valor renta fija", "pestana": "bonos",
        "tenencia": True, "tipos": ("bonos", "letras", "on", "moneda",
                                    "fci"),
        "campos": (),
    },
    "tecnica": {
        "nombre": "Análisis técnico", "pestana": "tecnica",
        "tenencia": True, "tipos": ("acciones", "cedears"),
        "campos": ("stop", "objetivo"),
    },
    "opciones": {
        "nombre": "Opciones", "pestana": "opc",
        "tenencia": True, "tipos": ("opciones", "acciones", "cedears"),
        "campos": ("stop", "objetivo"),
    },
}

# La fecha de revision aplica a cualquier familia.
CAMPOS_POSICION = ("stop", "objetivo", "ratio_min", "ratio_max", "revisar")

# El patron es la vara externa y es opcional en TODAS las familias.
# Antes solo lo admitian reserva y cambiaria, lo que mezclaba como se
# opera con contra que se mide, que son cosas independientes.
PATRONES = ("dolar", "cer", "badlar", "spy")


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
                    "valor_final REAL", "dias_final INTEGER",
                    "ticker_base TEXT"):
            if col.split()[0] not in ce:
                c.execute("ALTER TABLE estrategia ADD COLUMN " + col)
    except Exception as e:
        log.warning("migrar estrategia: %s", e)
    _migrar_parametros(c)
    _migrar_modelo_estrategias(c)
    c.commit()


MIGRACION = "modelo_estrategias_v2"


def _migrar_modelo_estrategias(c):
    """Pasa al modelo nuevo de estrategias. Corre una sola vez.

    Tres cambios que no se pueden hacer con ALTER TABLE:

    1. `tenencia_hist` pasa de una foto por dia a una por carga. Con la
       clave por fecha, dos cargas del mismo dia con operaciones
       distintas en el medio se pisaban y el diff comparaba contra ayer:
       las dos rotaciones se veian como una sola.
    2. `estrategia_especie` pierde el broker. Una especie pertenece a una
       sola estrategia en todos lados.
    3. Las familias viejas -rotacion, intradiaria, cambiaria, reserva- ya
       no existen. `rotacion` tapaba dos tarjetas distintas, `cambiaria`
       y `reserva` eran la misma con distinta vara, e `intradiaria` no
       aparece nunca en el diff porque vuelve a la misma especie.

    Las estrategias cargadas se pierden. Es a proposito y esta
    acordado: no hay forma honesta de adivinar cual de las dos familias
    nuevas le corresponde a cada `rotacion` vieja.

    `movimientos` NO se borra. Queda sin que nadie la lea, para tener a
    donde mirar si algo del modelo nuevo no cierra.
    """
    if get_estado(MIGRACION):
        return
    log.warning("migrando al modelo nuevo de estrategias")

    # -- 1. tenencia_hist por timestamp -------------------------------
    cols = {r["name"] for r in c.execute("PRAGMA table_info(tenencia_hist)")}
    if cols and "ts" not in cols:
        c.executescript("""
        ALTER TABLE tenencia_hist RENAME TO tenencia_hist_viejo;
        CREATE TABLE tenencia_hist (
          ts       TEXT NOT NULL,
          fecha    TEXT NOT NULL,
          broker   TEXT NOT NULL,
          simbolo  TEXT NOT NULL,
          cantidad REAL NOT NULL,
          tipo     TEXT,
          PRIMARY KEY (ts, broker, simbolo)
        );
        CREATE INDEX ix_th_broker ON tenencia_hist(broker, ts);
        """)
        # La foto vieja no tiene hora: se le pone el cierre del dia, que
        # conserva el orden y no inventa una precision que no habia.
        c.execute(
            "INSERT INTO tenencia_hist (ts, fecha, broker, simbolo, "
            "cantidad, tipo) SELECT fecha || 'T23:59:59', fecha, broker, "
            "simbolo, cantidad, tipo FROM tenencia_hist_viejo")
        c.execute("DROP TABLE tenencia_hist_viejo")

    # -- 2. estrategia_especie sin broker ------------------------------
    ee = {r["name"] for r in c.execute("PRAGMA table_info(estrategia_especie)")}
    if "broker" in ee:
        c.execute("DROP TABLE estrategia_especie")
        c.executescript("""
        CREATE TABLE estrategia_especie (
          estrategia_id INTEGER NOT NULL,
          simbolo       TEXT NOT NULL PRIMARY KEY
        );
        CREATE INDEX ix_ee_estr ON estrategia_especie(estrategia_id);
        """)

    # -- 3. las estrategias viejas se van ------------------------------
    for t in ("estrategia", "estrategia_especie", "estrategia_hist"):
        try:
            c.execute("DELETE FROM %s" % t)
        except Exception as e:
            log.warning("limpiar %s: %s", t, e)

    # -- 4. mov_propuesto se recrea ------------------------------------
    # No alcanza con vaciarla: `desde` y `hasta` pasaron de fecha a
    # timestamp, y con eso cambia la clave unica que evita proponer dos
    # veces lo mismo. Ademas suma estrategia_id, unido_a y los tres
    # precios, y CREATE TABLE IF NOT EXISTS no agrega columnas a una
    # tabla que ya existe: la base venia de 0.32.0 sin ninguna de las
    # cinco y el INSERT del diff reventaba.
    try:
        c.execute("DROP TABLE IF EXISTS mov_propuesto")
        c.executescript(ESQUEMA_ALERTAS)
    except Exception as e:
        log.warning("recrear mov_propuesto: %s", e)

    # Las alertas dejan de tener estrategia: la vigilancia vive dentro de
    # la tarjeta, no es una fila en alerta_precio.
    for t in ("alerta_precio", "alerta_fecha"):
        try:
            c.execute("UPDATE %s SET estrategia_id = NULL" % t)
        except Exception:
            pass

    set_estado(MIGRACION, datetime.now().isoformat(timespec="seconds"))
    c.commit()
    log.warning("modelo nuevo listo")


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
        for esp in c.execute("SELECT simbolo FROM estrategia_especie "
                             "WHERE estrategia_id = ?", (e["id"],)):
            c.execute(
                "UPDATE tenencia SET stop = COALESCE(stop, ?), "
                "objetivo = COALESCE(objetivo, ?), "
                "revisar = COALESCE(revisar, ?) "
                "WHERE simbolo = ?",
                (e["stop"], e["objetivo"], e["revisar"], esp["simbolo"]))


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
        eid = asig.get(f["simbolo"])
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


def guardar_tenencias(filas, reemplazar="todo", precios=None):
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
    # Una sola marca de tiempo para toda la carga: si se cargan dos
    # brokers de un saque, las dos fotos son del mismo momento.
    for br in brokers:
        if snapshot(br, ahora):
            try:
                detectar_movimientos(br, precios)
            except Exception as e:
                log.warning("diff de %s: %s", br, e)
    # El cierre ya no se aplica solo: se propone y espera confirmacion.
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
            "SELECT simbolo FROM estrategia_especie "
            "WHERE estrategia_id = ? ORDER BY simbolo", (f["id"],))]
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
    # El patron es opcional en todas las familias: exigirlo en algunas
    # mezclaba como se opera con contra que se mide. FAMILIAS ya no tiene
    # la clave y el chequeo viejo reventaba con KeyError.
    base = (datos.get("ticker_base") or "").strip().upper() or None

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
              datos.get("grupo_id") or None, base)
    c = conn()
    if eid:
        c.execute("UPDATE estrategia SET nombre=?, familia=?, tesis=?, "
                  "origen=?, patron=?, patron_valor=?, objetivo=?, stop=?, "
                  "revisar=?, grupo_id=?, ticker_base=? WHERE id=?",
                  campos + (eid,))
    else:
        cur = c.execute(
            "INSERT INTO estrategia (nombre, familia, tesis, origen, patron, "
            "patron_valor, objetivo, stop, revisar, grupo_id, ticker_base, "
            "alta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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


def asignar(simbolo, eid):
    """Ata una especie a una estrategia, o la desata si eid es None.

    La clave es el simbolo solo. La tenencia de una especie obedece a una
    estrategia sin importar en cuantos brokers este: antes la clave
    incluia el broker y la misma especie podia colgar de dos estrategias
    distintas, que no es como se opera.
    """
    c = conn()
    sim = simbolo.upper()
    if eid:
        c.execute("INSERT OR REPLACE INTO estrategia_especie "
                  "(estrategia_id, simbolo) VALUES (?,?)", (eid, sim))
    else:
        c.execute("DELETE FROM estrategia_especie WHERE simbolo=?", (sim,))
    c.commit()


def asignaciones():
    return {r["simbolo"]: r["estrategia_id"]
            for r in conn().execute("SELECT * FROM estrategia_especie")}


def especies_de(eid):
    """Las especies asignadas a una estrategia, tenga saldo o no.

    Una que se vendio entera sigue asignada hasta que se confirme la
    rotacion o el cierre: es lo que permite medir la secuencia completa.
    """
    return [r["simbolo"] for r in conn().execute(
        "SELECT simbolo FROM estrategia_especie WHERE estrategia_id=? "
        "ORDER BY simbolo", (eid,))]


def especies_cruzadas():
    """Especies asignadas a una familia que no las espera.

    No bloquea nada: marca. Si metes un CEDEAR en una reserva de valor de
    renta fija, probablemente sea otra estrategia, pero eso lo decidis
    vos y no la app.
    """
    c = conn()
    tipos = {r["simbolo"]: r["tipo"] for r in c.execute(
        "SELECT simbolo, tipo FROM tenencia")}
    out = []
    for r in c.execute(
            "SELECT s.simbolo, s.estrategia_id, e.familia, e.nombre "
            "FROM estrategia_especie s JOIN estrategia e "
            "ON e.id = s.estrategia_id WHERE e.cierre IS NULL"):
        esperados = (FAMILIAS.get(r["familia"]) or {}).get("tipos") or ()
        t = tipos.get(r["simbolo"])
        if t and esperados and t not in esperados:
            out.append({"simbolo": r["simbolo"], "tipo": t,
                        "estrategia_id": r["estrategia_id"],
                        "estrategia": r["nombre"], "familia": r["familia"],
                        "esperados": list(esperados)})
    return out


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
                # Un grupo es un par: num contra den. La familia vieja
                # `rotacion` ya no existe y esto reventaba con
                # ValueError en cada alta automatica.
                "nombre": g["nombre"], "familia": "par",
                "ticker_base": g["base"],
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
            if sim in ya:
                continue        # nunca pisa una asignacion existente
            if not c.execute("SELECT 1 FROM tenencia WHERE simbolo=? LIMIT 1",
                             (sim,)).fetchone():
                continue
            asignar(sim, eid)
            ya[sim] = eid
            hechas.append("%s → %s" % (sim, g["nombre"]))
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


def cierres_sugeridos():
    """Estrategias cuyas especies ya no estan en cartera.

    NO cierra nada. Antes se cerraba en la misma carga que corria la
    deteccion, asi que la estrategia quedaba cerrada por "sin tenencia"
    antes de que llegaras a confirmar la rotacion que la mantenia viva.
    Ahora el cierre se propone junto con el movimiento y espera.

    Una estrategia sin especies asignadas no se toca: recien creada
    todavia no tiene ninguna y cerrarla seria absurdo.
    """
    c = conn()
    cerradas = []
    for e in c.execute("SELECT id, nombre FROM estrategia WHERE cierre IS NULL"):
        esp = c.execute("SELECT simbolo FROM estrategia_especie "
                        "WHERE estrategia_id=?", (e["id"],)).fetchall()
        if not esp:
            continue
        vivas = 0
        for s in esp:
            r = c.execute("SELECT SUM(cantidad) t FROM tenencia WHERE "
                          "simbolo=?", (s["simbolo"],)).fetchone()
            if r and r["t"]:
                vivas += 1
        if not vivas:
            cerradas.append({"id": e["id"], "nombre": e["nombre"]})
    return cerradas


def _estrategia_de(simbolo):
    r = conn().execute("SELECT estrategia_id FROM estrategia_especie "
                       "WHERE simbolo=?", (simbolo,)).fetchone()
    return r["estrategia_id"] if r else None


def detectar_movimientos(broker, precios=None):
    """Compara las dos ultimas fotos de un broker y propone que paso.

    No aplica nada: entre dos fotos, dos operaciones sueltas del mismo
    dia se ven igual que una rotacion, y esa diferencia la sabe el que
    opero, no la base.

    Guarda el precio de cada simbolo al momento de la foto. Si confirmas
    tres dias despues, el ledger tiene que registrar el precio del hecho
    y no el de hoy.
    """
    import json as _json
    c = conn()
    precios = precios or {}
    tss = [r["ts"] for r in c.execute(
        "SELECT DISTINCT ts FROM tenencia_hist WHERE broker=? "
        "ORDER BY ts DESC LIMIT 2", (broker,))]
    if len(tss) < 2:
        return []
    hasta, desde = tss[0], tss[1]

    def foto(t):
        return {r["simbolo"]: r["cantidad"] for r in c.execute(
            "SELECT simbolo, cantidad FROM tenencia_hist "
            "WHERE broker=? AND ts=?", (broker, t))}

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
                        and s not in usados), key=lambda s: difs[s])
        suben = sorted((s for s in difs if s in tk and difs[s] > 0
                        and s not in usados), key=lambda s: -difs[s])
        for sale, entra in zip(bajan, suben):
            cs, ce = -difs[sale], difs[entra]
            props.append({
                "broker": broker, "desde": desde, "hasta": hasta,
                "tipo": "rotacion", "sale": sale, "cant_sale": cs,
                "entra": entra, "cant_entra": ce,
                "ratio": (cs / ce) if ce else None, "grupo_id": gid,
                "grupo": gnom,
                "estrategia_id": _estrategia_de(sale) or _estrategia_de(entra),
                "precio_sale": precios.get(sale),
                "precio_entra": precios.get(entra)})
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
            "ratio": None, "grupo_id": None, "grupo": None,
            "estrategia_id": _estrategia_de(sim),
            "precio_sale": None if d > 0 else precios.get(sim),
            "precio_entra": precios.get(sim) if d > 0 else None})

    # El precio del ticker base va junto con los otros dos y por el mismo
    # motivo: la cuotaparte de un aporte se emite al valor del base en el
    # momento del hecho. Resolverlo al confirmar mediria un aporte de
    # hace tres dias con el precio de hoy.
    bases = {r["id"]: r["ticker_base"] for r in c.execute(
        "SELECT id, ticker_base FROM estrategia WHERE ticker_base IS NOT NULL")}
    equivs = {}
    for p in props:
        eid = p["estrategia_id"]
        base = bases.get(eid)
        p["precio_base"] = precios.get(base) if base else None
        if eid not in equivs:
            equivs[eid] = _equiv_en_base(eid, base, broker, desde, hasta,
                                         precios) if eid else None
        p["equiv_antes"] = equivs[eid]

    for p in props:
        c.execute(
            "INSERT OR IGNORE INTO mov_propuesto (detectado, broker, desde, "
            "hasta, tipo, sale, cant_sale, entra, cant_entra, ratio, "
            "grupo_id, estrategia_id, precio_sale, precio_entra, "
            "precio_base, equiv_antes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ahora, broker, desde, hasta, p["tipo"], p["sale"],
             p["cant_sale"], p["entra"], p["cant_entra"], p["ratio"],
             p["grupo_id"], p["estrategia_id"], p["precio_sale"],
             p["precio_entra"], p["precio_base"], p["equiv_antes"]))
    c.commit()
    return props


def candidatos_a_unir(mid):
    """Propuestas pendientes que podrian ser la contraparte de esta.

    Vendes AO28 en IOL y compras AO29 en ECO: son dos fotos de dos
    brokers distintos y una sola rotacion. La app NO une sola. Ofrece, y
    la union la confirma el que opero.

    Dos formas validas, las dos en otro broker y en sentido contrario:

    - **rotacion entre cuentas**: simbolos distintos del mismo grupo.
    - **transferencia**: el mismo simbolo. No es una operacion: la plata
      no entro ni salio, cambio de cuenta. Confirmarla no escribe ledger.
    """
    import json as _json
    c = conn()
    p = c.execute("SELECT * FROM mov_propuesto WHERE id=? AND estado="
                  "'pendiente' AND unido_a IS NULL", (mid,)).fetchone()
    if not p or p["tipo"] not in ("aporte", "retiro"):
        return []
    mio = p["entra"] if p["tipo"] == "aporte" else p["sale"]
    busco = "retiro" if p["tipo"] == "aporte" else "aporte"

    juntos = set()
    for g in c.execute("SELECT tickers FROM grupos"):
        try:
            tk = {t.strip().upper() for t in _json.loads(g["tickers"] or "[]")}
        except ValueError:
            continue
        if mio in tk:
            juntos |= tk

    out = []
    for o in c.execute("SELECT * FROM mov_propuesto WHERE estado='pendiente' "
                       "AND unido_a IS NULL AND tipo=? AND broker<>? "
                       "ORDER BY detectado DESC", (busco, p["broker"])):
        suyo = o["entra"] if o["tipo"] == "aporte" else o["sale"]
        if suyo == mio:
            union = "transferencia"
        elif suyo in juntos:
            union = "rotacion"
        else:
            continue
        d = dict(o)
        d["union"] = union
        out.append(d)
    return out


def movimientos_propuestos(estado="pendiente", eid=None):
    q = "SELECT * FROM mov_propuesto"
    cond, args = [], []
    if estado:
        cond.append("estado = ?")
        args.append(estado)
    if eid:
        cond.append("estrategia_id = ?")
        args.append(eid)
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY hasta DESC, id DESC"
    return [dict(r) for r in conn().execute(q, args)]


def resolver_propuesto(mid, accion, editado=None, unir_con=None):
    """Confirma, edita o descarta una propuesta.

    Confirmar es lo unico que escribe el ledger de la estrategia. Antes
    solo movia la asignacion de especie y el ledger del grupo quedaba
    congelado donde lo habia dejado la ultima carga manual: la tarjeta
    mostraba la tenencia del dia en que se sembro el grupo y nunca mas.

    `editado` permite corregir tipo, cantidades, precios o la estrategia
    antes de aplicar. `unir_con` consolida esta propuesta con la de otro
    broker para armar una rotacion entre cuentas.
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

    d = dict(p)
    d.update({k: v for k, v in (editado or {}).items() if k in (
        "tipo", "sale", "cant_sale", "entra", "cant_entra",
        "precio_sale", "precio_entra", "precio_base", "estrategia_id",
        "nota")})

    otro = None
    if unir_con:
        otro = c.execute("SELECT * FROM mov_propuesto WHERE id=? AND "
                         "estado='pendiente'", (unir_con,)).fetchone()
        if not otro:
            return "contraparte no disponible"
        # De un retiro en un broker y un aporte en otro sale una sola
        # rotacion. El ratio va por nominales, que es exacto y no
        # necesita ni precios ni la hora de la operacion.
        a, b = (d, dict(otro)) if d["tipo"] == "retiro" else (dict(otro), d)
        # Si es la misma especie no hubo operacion: es una transferencia
        # entre cuentas. El capital no cambio, asi que no va al ledger.
        # Confirmadas por separado dejarian un retiro y un aporte falsos
        # y la tarjeta avisaria pendientes por algo que no movio nada.
        if a["sale"] and a["sale"] == b["entra"]:
            c.execute("UPDATE mov_propuesto SET estado='transferido' "
                      "WHERE id=?", (mid,))
            c.execute("UPDATE mov_propuesto SET estado='transferido', "
                      "unido_a=? WHERE id=?", (mid, otro["id"]))
            c.commit()
            return "transferencia"
        d = dict(d)
        d.update({
            "tipo": "rotacion",
            "sale": a["sale"], "cant_sale": a["cant_sale"],
            "precio_sale": a["precio_sale"],
            "entra": b["entra"], "cant_entra": b["cant_entra"],
            "precio_entra": b["precio_entra"],
            "ratio": ((a["cant_sale"] / b["cant_entra"])
                      if b["cant_entra"] else None),
            "estrategia_id": (d.get("estrategia_id")
                              or otro["estrategia_id"]),
        })

    eid = d.get("estrategia_id")
    if d["tipo"] == "rotacion" and d["sale"] and d["entra"]:
        eid = eid or _estrategia_de(d["sale"]) or _estrategia_de(d["entra"])
        if eid:
            asignar(d["entra"], eid)
            # La que sale solo se desasigna si ya no queda en ningun
            # broker: se puede rotar de a partes.
            r = c.execute("SELECT SUM(cantidad) t FROM tenencia WHERE "
                          "simbolo=?", (d["sale"],)).fetchone()
            if not (r and r["t"]):
                c.execute("DELETE FROM estrategia_especie WHERE simbolo=?",
                          (d["sale"],))
            e = c.execute("SELECT cierre, motivo_cierre FROM estrategia "
                          "WHERE id=?", (eid,)).fetchone()
            if e and e["cierre"] and e["motivo_cierre"] == "sin tenencia":
                reabrir_estrategia(eid)

    if eid:
        registrar_mov_estrategia(eid, d, propuesto_id=mid)

    c.execute("UPDATE mov_propuesto SET estado='confirmado' WHERE id=?",
              (mid,))
    if otro:
        c.execute("UPDATE mov_propuesto SET estado='confirmado', unido_a=? "
                  "WHERE id=?", (mid, otro["id"]))
    c.commit()
    return "confirmado"


def registrar_mov_estrategia(eid, d, propuesto_id=None):
    """Escribe la fila del ledger y calcula lo que hace falta para medir.

    `ratio_base` es el equivalente del movimiento en el ticker base de la
    estrategia, con el precio de la foto. Solo lo llevan aportes y
    retiros: son los unicos que mueven la cuotaparte. Una rotacion cambia
    la composicion, no el capital.

    `equiv_antes` es cuanto valia la posicion justo antes, que es lo que
    determina a que valor se emiten o rescatan las cuotas.
    """
    c = conn()
    e = c.execute("SELECT ticker_base FROM estrategia WHERE id=?",
                  (eid,)).fetchone()
    base = e["ticker_base"] if e else None

    ratio_base = None
    if d["tipo"] in ("aporte", "retiro"):
        tk = d["entra"] if d["tipo"] == "aporte" else d["sale"]
        cant = d["cant_entra"] if d["tipo"] == "aporte" else d["cant_sale"]
        pr = d["precio_entra"] if d["tipo"] == "aporte" else d["precio_sale"]
        ratio_base = _a_base(tk, cant, pr, base, d)

    c.execute(
        "INSERT INTO estrategia_mov (estrategia_id, ts, tipo, ticker_de, "
        "cant_de, ticker_a, cant_a, ratio_base, equiv_antes, propuesto_id, "
        "nota) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (eid, d.get("hasta") or datetime.now().isoformat(timespec="seconds"),
         d["tipo"], d.get("sale"), d.get("cant_sale"), d.get("entra"),
         d.get("cant_entra"), ratio_base, d.get("equiv_antes"),
         propuesto_id, d.get("nota")))
    c.commit()


def _a_base(tk, cant, precio, base, d=None):
    """Nominales de `tk` llevados al ticker base con el precio de la foto.

    Si el ticker ES la base, no hace falta precio. Si falta el precio de
    alguno de los dos, devuelve None: la fila queda sin ratio_base y la
    tarjeta avisa que ese movimiento no se pudo medir, que es mejor que
    inventar un numero.
    """
    if not cant:
        return None
    ts = (d or {}).get("hasta")
    if not base:
        # Sin ticker base la vara es el peso: la estrategia no rota entre
        # especies equivalentes, se mide contra un indice o contra lo que
        # costo.
        if not precio:
            return None
        return cant * precio / (base_cotizacion(tk, ts) or 1.0)
    if tk == base:
        return cant
    p_base = (d or {}).get("precio_base")
    if not (precio and p_base):
        return None
    # Un bono cotiza por cada 100 nominales y un CEDEAR por unidad. Si el
    # ticker del movimiento y el base no cotizan en la misma, el cociente
    # de precios se va por un factor de 100. Si de alguno de los dos no
    # se conoce el tipo se los deja iguales: el factor se cancela, que es
    # lo que venia haciendo.
    b1, b2 = base_cotizacion(tk, ts), base_cotizacion(base, ts)
    if b1 and b2:
        precio, p_base = precio / b1, p_base / b2
    return cant * precio / p_base


def _equiv_en_base(eid, base, broker, desde, hasta, precios):
    """Cuanto valia la posicion de la estrategia, en nominales del base.

    Se mide sobre la foto anterior -las cantidades de antes del
    movimiento- y con los precios de ese momento. Es el valor al que se
    emiten o rescatan las cuotas.

    Del broker que se acaba de cargar se toma la foto anterior, que es
    justo la de antes del movimiento. De los demas, la ultima que
    tengan: no cambiaron, asi que su estado de ahora es tambien el de
    antes. Tomarles la foto vieja mediria el aporte contra una posicion
    que ya no existia.

    Si a alguna especie le falta el precio devuelve None. Un equivalente
    a medias emitiria cuotas a un valor mas bajo que el real y la
    medicion quedaria inflada para siempre: es mejor no medir ese
    movimiento y que la tarjeta lo avise.
    """
    # Sin ticker base se mide en pesos: precio 1 y base 1 dejan la cuenta
    # en el valor de mercado, que es lo que la vara del indice compara.
    p_base = precios.get(base) if base else 1.0
    if not p_base:
        return None
    b_base = (base_cotizacion(base, hasta) or 1.0) if base else 1.0
    filas = conn().execute(
        "SELECT h.simbolo, SUM(h.cantidad) cant FROM tenencia_hist h "
        "JOIN estrategia_especie e ON e.simbolo = h.simbolo "
        "JOIN (SELECT broker, MAX(ts) ts FROM tenencia_hist WHERE ts <= "
        "      CASE WHEN broker = ? THEN ? ELSE ? END GROUP BY broker) u "
        "  ON u.broker = h.broker AND u.ts = h.ts "
        "WHERE e.estrategia_id = ? GROUP BY h.simbolo",
        (broker, desde, hasta, eid)).fetchall()
    total = 0.0
    for f in filas:
        cant = f["cant"] or 0
        if not cant:
            continue
        if base and f["simbolo"] == base:
            total += cant
            continue
        p = precios.get(f["simbolo"])
        if not p:
            return None
        b = base_cotizacion(f["simbolo"], hasta) or 1.0
        total += cant * (p / b) / (p_base / b_base)
    return total


def tenencia_de_estrategia(eid):
    """Las posiciones de una estrategia, una fila por broker y especie.

    Las cantidades de la tarjeta salen de aca y no del ledger: el ledger
    solo se lee para medir. Es lo que evita que la tarjeta muestre la
    tenencia del dia en que se sembro el grupo y nunca mas.
    """
    return [dict(r) for r in conn().execute(
        "SELECT t.broker, t.simbolo, t.cantidad, t.tipo, t.ppc, t.ppc_base "
        "FROM tenencia t JOIN estrategia_especie e ON e.simbolo = t.simbolo "
        "WHERE e.estrategia_id = ? ORDER BY t.simbolo, t.broker", (eid,))]


def base_cotizacion(simbolo, ts=None):
    """100 si cotiza por lamina, 1 si por unidad, None si no se sabe.

    El tipo sale de la foto vigente al momento del movimiento y no de la
    tenencia de hoy: la especie que salio puede no estar mas.
    """
    from cartera import BASE_100
    c = conn()
    r = None
    if ts:
        r = c.execute("SELECT tipo FROM tenencia_hist WHERE simbolo=? AND "
                      "ts<=? AND tipo IS NOT NULL ORDER BY ts DESC LIMIT 1",
                      (simbolo, ts)).fetchone()
    if not r:
        r = c.execute("SELECT tipo FROM tenencia WHERE simbolo=? AND "
                      "tipo IS NOT NULL LIMIT 1", (simbolo,)).fetchone()
    if not r:
        return None
    return 100.0 if (r["tipo"] or "").lower() in BASE_100 else 1.0


def registrar_mov_manual(eid, d):
    """Escribe en el ledger un movimiento cargado a mano.

    Es el camino del punto de partida: la primera vez no hay dos fotos
    que comparar, asi que el aporte inicial se carga y de ahi sale la
    cuota. Valida `posicion.validar_movimiento`, que ya trae calculados
    `ratio_base` y `equiv_antes`.
    """
    c = conn()
    cur = c.execute(
        "INSERT INTO estrategia_mov (estrategia_id, ts, tipo, ticker_de, "
        "cant_de, ticker_a, cant_a, ratio_base, equiv_antes, nota) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (eid, d.get("ts") or datetime.now().isoformat(timespec="seconds"),
         d["tipo"], d.get("ticker_de"), d.get("cant_de"), d.get("ticker_a"),
         d.get("cant_a"), d.get("ratio_base"), d.get("equiv_antes"),
         d.get("nota")))
    c.commit()
    return cur.lastrowid


def movimientos_estrategia(eid):
    return [dict(r) for r in conn().execute(
        "SELECT * FROM estrategia_mov WHERE estrategia_id=? ORDER BY ts, id",
        (eid,))]


def borrar_mov_estrategia(mid):
    c = conn()
    c.execute("DELETE FROM estrategia_mov WHERE id=?", (mid,))
    c.commit()


def snapshot(broker, ts=None):
    """Guarda una foto del broker, si cambio algo.

    Una foto por carga, no por dia. Con la clave por fecha, dos cargas
    del mismo dia con operaciones distintas en el medio se pisaban: la
    segunda borraba la primera y el diff terminaba comparando contra
    ayer, asi que dos rotaciones se leian como una sola.

    Se compara contra la ultima foto de ese broker y no se escribe nada
    si las cantidades son las mismas: actualizar tres veces sin operar no
    tiene que dejar tres fotos iguales.
    """
    c = conn()
    ts = ts or datetime.now().isoformat(timespec="seconds")
    # La clave es (ts, broker, simbolo). Dos cargas del mismo broker
    # dentro del mismo segundo comparten `ts` y la segunda pisaba a la
    # primera: quedaba una foto mezclada, con las especies viejas que ya
    # no estaban conviviendo con las nuevas. Se corre un segundo hasta
    # encontrar uno libre.
    while c.execute("SELECT 1 FROM tenencia_hist WHERE broker=? AND ts=? "
                    "LIMIT 1", (broker, ts)).fetchone():
        ts = (datetime.fromisoformat(ts)
              + timedelta(seconds=1)).isoformat(timespec="seconds")
    actual = {r["simbolo"]: (r["cantidad"], r["tipo"]) for r in c.execute(
        "SELECT simbolo, cantidad, tipo FROM tenencia WHERE broker = ?",
        (broker,))}
    ult = c.execute("SELECT MAX(ts) t FROM tenencia_hist WHERE broker = ?",
                    (broker,)).fetchone()
    if ult and ult["t"]:
        previo = {r["simbolo"]: r["cantidad"] for r in c.execute(
            "SELECT simbolo, cantidad FROM tenencia_hist "
            "WHERE broker = ? AND ts = ?", (broker, ult["t"]))}
        if previo == {k: v[0] for k, v in actual.items()}:
            return 0
    for sim, (cant, tipo) in actual.items():
        c.execute("INSERT OR REPLACE INTO tenencia_hist "
                  "(ts, fecha, broker, simbolo, cantidad, tipo) "
                  "VALUES (?,?,?,?,?,?)",
                  (ts, ts[:10], broker, sim, cant, tipo))
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
