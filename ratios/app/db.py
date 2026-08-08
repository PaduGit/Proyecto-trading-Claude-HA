"""Persistencia en SQLite. Vive en /data, que HA conserva entre reinicios."""

import os
import sqlite3
import threading
from datetime import datetime

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

def ultima_lectura(alias):
    return conn().execute(
        "SELECT * FROM lecturas WHERE alias=? ORDER BY ts DESC LIMIT 1",
        (alias,)).fetchone()


def serie_intradiaria(alias, limite=600, solo_hoy=True):
    q = "SELECT ts, ratio FROM lecturas WHERE alias=?"
    args = [alias]
    if solo_hoy:
        q += " AND ts >= ?"
        args.append(datetime.now().date().isoformat())
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limite)
    filas = conn().execute(q, args).fetchall()
    return [(f["ts"], f["ratio"]) for f in reversed(filas)]


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


def alerta_por_id(aid):
    return conn().execute("SELECT * FROM alertas WHERE id=?", (aid,)).fetchone()


def operaciones_recientes(n=60):
    return conn().execute(
        "SELECT * FROM operaciones ORDER BY ts DESC LIMIT ?", (n,)).fetchall()


def resumen_requests(dias=30):
    c = conn()
    por_dia = c.execute(
        "SELECT fecha, SUM(n) n FROM requests "
        "WHERE fecha >= date('now', ?) GROUP BY fecha ORDER BY fecha",
        ("-%d days" % dias,)).fetchall()
    por_tipo = c.execute(
        "SELECT tipo, SUM(n) n FROM requests "
        "WHERE substr(fecha,1,7) = strftime('%Y-%m','now') "
        "GROUP BY tipo ORDER BY n DESC").fetchall()
    mes = c.execute(
        "SELECT COALESCE(SUM(n),0) n FROM requests "
        "WHERE substr(fecha,1,7) = strftime('%Y-%m','now')").fetchone()["n"]
    hoy = c.execute(
        "SELECT COALESCE(SUM(n),0) n FROM requests "
        "WHERE fecha = date('now')").fetchone()["n"]
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
    creado    TEXT NOT NULL
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


def init_posicion():
    c = conn()
    c.executescript(ESQUEMA_POSICION)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(movimientos)")}
    if "equiv_antes" not in cols:
        c.execute("ALTER TABLE movimientos ADD COLUMN equiv_antes REAL")
    c.commit()


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
        out.append({"id": f["id"], "nombre": f["nombre"], "base": f["base"],
                    "tickers": tickers, "mercado": f["mercado"],
                    "creado": f["creado"]})
    return out


def grupo_por_id(gid):
    for g in listar_grupos():
        if g["id"] == gid:
            return g
    return None


def actualizar_grupo(gid, nombre=None, base=None, tickers=None):
    import json as _json
    g = grupo_por_id(gid)
    if not g:
        return False
    c = conn()
    c.execute("UPDATE grupos SET nombre=?, base=?, tickers=? WHERE id=?",
              (nombre or g["nombre"], base or g["base"],
               _json.dumps(tickers if tickers is not None else g["tickers"]),
               gid))
    c.commit()
    return True


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
