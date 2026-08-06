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
    ts        TEXT NOT NULL,
    alias     TEXT NOT NULL,
    tipo      TEXT NOT NULL,
    ratio     REAL NOT NULL,
    nivel     REAL,
    mensaje   TEXT
);
CREATE INDEX IF NOT EXISTS ix_alertas_ts ON alertas(ts);

CREATE TABLE IF NOT EXISTS estado (
    clave     TEXT PRIMARY KEY,
    valor     TEXT
);
"""


def conn():
    c = getattr(_local, "c", None)
    if c is None:
        os.makedirs(os.path.dirname(RUTA), exist_ok=True)
        c = sqlite3.connect(RUTA, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c


def init():
    c = conn()
    c.executescript(ESQUEMA)
    c.commit()


# -- escritura --------------------------------------------------------

def guardar_lectura(alias, ratio, num, den, ts=None):
    ts = ts or datetime.now().isoformat(timespec="seconds")
    c = conn()
    c.execute(
        "INSERT OR REPLACE INTO lecturas "
        "(ts, alias, ratio, p_num, p_den, c_num, v_num, c_den, v_den) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, alias, ratio, num["ref"], den["ref"],
         num["compra"], num["venta"], den["compra"], den["venta"]),
    )
    c.commit()


def guardar_cierres(simbolo, filas):
    """filas: iterable de (fecha_iso, cierre). Idempotente."""
    c = conn()
    c.executemany(
        "INSERT OR IGNORE INTO cierres (fecha, simbolo, cierre) VALUES (?,?,?)",
        [(f, simbolo, v) for f, v in filas],
    )
    c.commit()


def registrar_alerta(alias, tipo, ratio, nivel, mensaje):
    c = conn()
    c.execute(
        "INSERT INTO alertas (ts, alias, tipo, ratio, nivel, mensaje) "
        "VALUES (?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"),
         alias, tipo, ratio, nivel, mensaje),
    )
    c.commit()


def set_estado(clave, valor):
    c = conn()
    c.execute(
        "INSERT OR REPLACE INTO estado (clave, valor) VALUES (?,?)",
        (clave, str(valor)),
    )
    c.commit()


def get_estado(clave, default=None):
    r = conn().execute(
        "SELECT valor FROM estado WHERE clave=?", (clave,)
    ).fetchone()
    return r["valor"] if r else default


# -- lectura ----------------------------------------------------------

def ultima_lectura(alias):
    return conn().execute(
        "SELECT * FROM lecturas WHERE alias=? ORDER BY ts DESC LIMIT 1",
        (alias,),
    ).fetchone()

def ultimas_lecturas(alias, n):
    return conn().execute(
        "SELECT * FROM lecturas WHERE alias=? ORDER BY ts DESC LIMIT ?",
        (alias, n),
    ).fetchall()


def serie_intradiaria(alias, limite=2000):
    filas = conn().execute(
        "SELECT ts, ratio FROM lecturas WHERE alias=? "
        "ORDER BY ts DESC LIMIT ?",
        (alias, limite),
    ).fetchall()
    return [(f["ts"], f["ratio"]) for f in reversed(filas)]


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
        "SELECT MAX(fecha) f FROM cierres WHERE simbolo=?", (simbolo,)
    ).fetchone()
    return r["f"] if r and r["f"] else None


def serie_ratio_diaria(num, den, desde=None):
    """Ratio de cierres diarios, alineado por fecha."""
    a = {r["fecha"]: r["cierre"] for r in cierres_de(num, desde)}
    b = {r["fecha"]: r["cierre"] for r in cierres_de(den, desde)}
    fechas = sorted(set(a) & set(b))
    return [(f, a[f] / b[f]) for f in fechas if b[f]]


def alertas_recientes(n=50):
    return conn().execute(
        "SELECT * FROM alertas ORDER BY ts DESC LIMIT ?", (n,)
    ).fetchall()


def purgar(dias_intradiario=400):
    """Las lecturas minuto a minuto se acumulan; los cierres no se tocan."""
    c = conn()
    c.execute(
        "DELETE FROM lecturas WHERE ts < date('now', ?)",
        (f"-{dias_intradiario} days",),
    )
    c.commit()
