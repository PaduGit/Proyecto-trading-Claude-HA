"""Medicion de señales: si las alertas aciertan.

Cada aviso de canje, de curva o de par se guarda con lo que se sabia en
ese momento, y a las 5, 20 y 60 ruedas se mide que paso, se haya operado
o no. Es la forma de saber si vale la pena hacerles caso y de calibrar
los umbrales con datos propios y no con simulaciones.

Que se mide, en % de la posicion:

- **curva**: lo que convergio el desvio contra la curva.
  Barato: `MD × (desvio_0 − desvio_h) / 100`; caro, al reves.
- **canje**: lo mismo en las dos puntas, menos el costo de la rotacion:
  `MD_entra × (r_entra_0 − r_entra_h)/100 − MD_sale × (r_sale_0 − r_sale_h)/100 − costo`.
- **par**: lo que gano la punta donde la señal decia estar contra la
  otra. Con ratio = num/den: en el numerador, `ratio_h/ratio_0 − 1`; en
  el denominador, `ratio_0/ratio_h − 1`.

Curva y canje miden con el mismo modelo que da la señal: es convergencia
del desvio, no el resultado con precios, que ademas lleva cupones y
devengamiento. Sirve para saber si la señal se cumple; no es un P&L.

Las señales de curva y canje se pueden reconstruir hacia atras con
`residuo_hist` (origen "simulada"), con la tenencia de hoy y sin el
filtro de monto. Las de par solo existen desde que se guardan.
"""

import logging
import statistics as st
from datetime import date, datetime

import db

log = logging.getLogger("ratios.senales")

HORIZONTES = (5, 20, 60)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS senal (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT NOT NULL,
  fecha     TEXT NOT NULL,
  tipo      TEXT NOT NULL,          -- canje | curva | par
  origen    TEXT NOT NULL,          -- aviso | simulada
  clave     TEXT NOT NULL,          -- canje "SALE>ENTRA", curva el bono, par el alias
  sale      TEXT,
  entra     TEXT,
  direccion TEXT,                   -- curva: barato | caro; par: alta | baja
  z         REAL,                   -- curva y par: z; canje: z del que entra
  dz        REAL,                   -- canje: z(entra) - z(sale)
  esperado  REAL,                   -- canje: ganancia esperada %
  costo     REAL,
  md_sale   REAL,
  md_entra  REAL,
  r_sale    REAL,
  r_entra   REAL,
  valor0    REAL,                   -- par: ratio al momento de la señal
  res5      REAL,
  res20     REAL,
  res60     REAL,
  UNIQUE (tipo, clave, fecha, origen)
);
CREATE INDEX IF NOT EXISTS ix_senal_pend ON senal(res60, fecha);
"""


def init():
    c = db.conn()
    c.executescript(ESQUEMA)
    c.commit()


def registrar(tipo, clave, fecha=None, origen="aviso", **campos):
    """Guarda una señal. La misma señal el mismo dia se guarda una vez."""
    f = (fecha or date.today()).isoformat() if not isinstance(fecha, str) \
        else fecha
    cols = ["ts", "fecha", "tipo", "origen", "clave"]
    vals = [datetime.now().isoformat(timespec="seconds"), f, tipo, origen,
            clave]
    for k in ("sale", "entra", "direccion", "z", "dz", "esperado", "costo",
              "md_sale", "md_entra", "r_sale", "r_entra", "valor0"):
        if campos.get(k) is not None:
            cols.append(k)
            vals.append(campos[k])
    try:
        c = db.conn()
        c.execute("INSERT OR IGNORE INTO senal (%s) VALUES (%s)"
                  % (",".join(cols), ",".join("?" * len(cols))), vals)
        c.commit()
    except Exception as e:
        log.warning("señal %s %s: %s", tipo, clave, e)


# -- medicion ----------------------------------------------------------

def _residuos(c, sim, desde):
    return [(r["fecha"], r["residuo"]) for r in c.execute(
        "SELECT fecha, residuo FROM residuo_hist WHERE simbolo=? AND "
        "fecha > ? ORDER BY fecha", (sim, desde))]


def _r_en(c, sim, fecha):
    r = c.execute("SELECT residuo FROM residuo_hist WHERE simbolo=? AND "
                  "fecha=?", (sim, fecha)).fetchone()
    return r["residuo"] if r else None


def _estar_en_num(direccion, num, den):
    """Si la señal de par decia estar en el numerador."""
    try:
        from monitor import sugerencia_par
        s = sugerencia_par(num, den, direccion)
        return (s.get("estar_en") if isinstance(s, dict) else None) == num
    except Exception:
        return direccion == "baja"


def medir(horario=None):
    """Completa los resultados que ya se pueden medir. Corre a diario."""
    c = db.conn()
    pares = {}
    try:
        for g in c.execute("SELECT nombre, num, den FROM grupos"):
            pares[g["nombre"]] = (g["num"], g["den"])
    except Exception:
        pass
    n = 0
    pend = c.execute("SELECT * FROM senal WHERE res60 IS NULL").fetchall()
    for s in pend:
        res = {}
        if s["tipo"] == "curva":
            sim = s["entra"] or s["sale"]
            r0 = s["r_entra"] if s["entra"] else s["r_sale"]
            md = s["md_entra"] if s["entra"] else s["md_sale"]
            serie = _residuos(c, sim, s["fecha"])
            for h in HORIZONTES:
                if r0 is not None and md is not None and len(serie) >= h:
                    rh = serie[h - 1][1]
                    v = md * (r0 - rh) / 100.0
                    res[h] = v if s["direccion"] == "barato" else -v
        elif s["tipo"] == "canje":
            sa = _residuos(c, s["sale"], s["fecha"])
            en = dict(_residuos(c, s["entra"], s["fecha"]))
            for h in HORIZONTES:
                if len(sa) < h or None in (s["r_sale"], s["r_entra"],
                                           s["md_sale"], s["md_entra"]):
                    continue
                fh = sa[h - 1][0]
                if fh not in en:
                    continue
                res[h] = (s["md_entra"] * (s["r_entra"] - en[fh]) / 100.0
                          - s["md_sale"] * (s["r_sale"] - sa[h - 1][1]) / 100.0
                          - (s["costo"] or 0))
        elif s["tipo"] == "par" and s["valor0"]:
            serie = [x for x in db.serie_propia_diaria(
                s["clave"], s["fecha"], horario) if x[0] > s["fecha"]]
            num, den = pares.get(s["clave"], (None, None))
            en_num = _estar_en_num(s["direccion"], num, den) if num else \
                s["direccion"] == "baja"
            for h in HORIZONTES:
                if len(serie) >= h and serie[h - 1][1]:
                    rh = serie[h - 1][1]
                    res[h] = (rh / s["valor0"] - 1) * 100 if en_num else \
                        (s["valor0"] / rh - 1) * 100
        sets = {"res%d" % h: v for h, v in res.items()
                if s["res%d" % h] is None}
        if sets:
            c.execute("UPDATE senal SET %s WHERE id=?" % ", ".join(
                "%s=?" % k for k in sets), list(sets.values()) + [s["id"]])
            n += 1
    c.commit()
    return n


# -- reconstruccion hacia atras ----------------------------------------

def _historia():
    c = db.conn()
    R = {}
    for r in c.execute("SELECT simbolo, fecha, residuo FROM residuo_hist "
                       "ORDER BY simbolo, fecha"):
        R.setdefault(r["simbolo"], []).append((r["fecha"], r["residuo"]))
    md = {(r["simbolo"], r["fecha"]): r["md"] for r in c.execute(
        "SELECT simbolo, fecha, md FROM bono_hist WHERE md IS NOT NULL")}
    return R, md


def _z_rodante(serie, ventana, minimo):
    """{fecha: (z, residuo - media)} con la ventana que termina ese dia."""
    out = {}
    vals = []
    for f, r in serie:
        vals.append(r)
        h = vals[-ventana:]
        if len(h) < minimo:
            continue
        sd = st.pstdev(h)
        if sd < 1e-9:
            continue
        m = st.mean(h)
        out[f] = ((r - m) / sd, r - m)
    return out


def reconstruir(umbral_z=2.5, histeresis=0.5, canje_min_pct=1.0,
                canje_min_dz=1.0, costo_pct=0.32, max_dif_md=0.35,
                tenidos=None):
    """Señales simuladas de curva y canje con la historia guardada.

    Usa la misma regla que los avisos: curva con histeresis, canje con
    MD ±35%, z del que entra ≥ 1, margen de z y ganancia minima. No usa
    el filtro de monto (no hay volumen historico) y los tenidos son los
    de hoy. Se borra lo simulado antes y se vuelve a armar.
    """
    import bonos as BO
    import curva as CU
    c = db.conn()
    c.execute("DELETE FROM senal WHERE origen='simulada'")
    c.commit()
    R, MD = _historia()
    RD = {s_: dict(v) for s_, v in R.items()}
    Z = {s: _z_rodante(v, CU.VENTANA, CU.MIN_HISTORIA) for s, v in R.items()}
    fam = {}
    try:
        cfg, _ = BO.cargar()
        for s, info in BO.especies().items():
            cr = cfg.get(info.get("cronograma"))
            if cr:
                fam[s] = BO._familia(cr, info, s)
    except Exception as e:
        log.warning("familias: %s", e)
    fechas = sorted({f for serie_z in Z.values() for f in serie_z})
    n = 0

    # curva
    for s, zs in Z.items():
        zona = None
        for f in sorted(zs):
            z, _ = zs[f]
            nueva = _zona(z, umbral_z, histeresis, zona)
            if nueva and nueva != zona and (s, f) in MD:
                registrar("curva", s, f, "simulada", direccion=nueva, z=z,
                          entra=s if nueva == "barato" else None,
                          sale=s if nueva == "caro" else None,
                          md_entra=MD[(s, f)] if nueva == "barato" else None,
                          md_sale=MD[(s, f)] if nueva == "caro" else None,
                          r_entra=RD[s][f] if nueva == "barato" else None,
                          r_sale=RD[s][f] if nueva == "caro" else None)
                n += 1
            zona = nueva

    # canje
    if tenidos is None:
        tenidos = {r["simbolo"] for r in c.execute(
            "SELECT DISTINCT simbolo FROM tenencia WHERE cantidad > 0")}
    tenidos = [t for t in tenidos if t in Z and t in fam]
    vigentes = set()
    for f in fechas:
        hoy = set()
        for a in tenidos:
            if f not in Z[a] or (a, f) not in MD:
                continue
            za, da = Z[a][f]
            mda = MD[(a, f)]
            rec_a = mda * da / 100.0
            mejor = None
            for b, zb_ in Z.items():
                if b == a or fam.get(b) != fam[a] or f not in zb_ or \
                        (b, f) not in MD:
                    continue
                zb, db_ = zb_[f]
                mdb = MD[(b, f)]
                if abs(mdb - mda) > max_dif_md * max(mda, 0.5) or zb < 1:
                    continue
                if canje_min_dz and zb - za < canje_min_dz:
                    continue
                g = mdb * db_ / 100.0 - rec_a - costo_pct
                if g >= canje_min_pct and (not mejor or g > mejor[1]):
                    mejor = (b, g, zb, mdb)
            if not mejor:
                continue
            b, g, zb, mdb = mejor
            hoy.add(a)
            # Igual que los avisos: una vez por especie que sale, hasta
            # que pase una rueda entera sin señal.
            if a in vigentes:
                continue
            registrar("canje", "%s>%s" % (a, b), f, "simulada", sale=a,
                      entra=b, z=zb, dz=zb - za, esperado=g, costo=costo_pct,
                      md_sale=mda, md_entra=mdb, r_sale=RD[a][f],
                      r_entra=RD[b][f])
            n += 1
        vigentes = hoy
    return n


def _zona(z, umbral, h, previa):
    if previa == "barato" and z >= umbral - h:
        return "barato"
    if previa == "caro" and z <= -(umbral - h):
        return "caro"
    if z >= umbral:
        return "barato"
    if z <= -umbral:
        return "caro"
    return None


# -- resumen -----------------------------------------------------------

def _tramo(s):
    if s["tipo"] == "canje":
        d = s["dz"]
        if d is None:
            return "—"
        return ("dz < 1" if d < 1 else "dz 1–1,5" if d < 1.5 else
                "dz 1,5–2" if d < 2 else "dz ≥ 2")
    z = abs(s["z"] or 0)
    return ("|z| < 3" if z < 3 else "|z| 3–3,5" if z < 3.5 else "|z| ≥ 3,5")


def resumen(simuladas=True):
    """Aciertos por tipo y por tramo de umbral, a cada horizonte."""
    c = db.conn()
    q = "SELECT * FROM senal"
    if not simuladas:
        q += " WHERE origen='aviso'"
    filas = c.execute(q).fetchall()
    grupos = {}
    for s in filas:
        for clave in ((s["tipo"], "todas"), (s["tipo"], _tramo(s))):
            g = grupos.setdefault(clave, {h: [] for h in HORIZONTES})
            g["n"] = g.get("n", 0) + 1
            for h in HORIZONTES:
                v = s["res%d" % h]
                if v is not None:
                    g[h].append(v)
    out = []
    for (tipo, tramo), g in sorted(grupos.items()):
        fila = {"tipo": tipo, "tramo": tramo, "n": g["n"]}
        for h in HORIZONTES:
            v = g[h]
            fila["h%d" % h] = ({"n": len(v), "media": st.mean(v),
                                "positivas": sum(1 for x in v if x > 0) / len(v)}
                               if v else None)
        out.append(fila)
    ult = c.execute("SELECT tipo, origen, COUNT(*) n, MAX(fecha) f FROM senal "
                    "GROUP BY tipo, origen").fetchall()
    return {"grupos": out, "conteo": [dict(r) for r in ult],
            "horizontes": list(HORIZONTES)}
