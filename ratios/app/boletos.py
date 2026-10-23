"""Boletos de Veta: de un PDF a la tenencia y a las estrategias.

Los boletos llegan por mail; un script de Google (Apps Script, en la
cuenta del usuario) copia los PDF a una carpeta de Drive. A las 4 la app
lee esa carpeta con una cuenta de servicio que solo ve esa carpeta, lee
cada PDF y deja los boletos **pendientes**. Nada se aplica solo: se
confirma desde TENENCIAS, y mientras tanto los pendientes figuran en
oportunidades (Inicio y el resumen de las 12).

Al confirmar, cada especie va a su estrategia: una venta es un retiro
(con motivo: stop, objetivo o decision propia) y una compra un aporte.
Una venta y una compra del mismo dia no se unen solas; solo si se marca
que es una rotacion. El PPC de las compras va con gastos (lo debitado
sobre los nominales) y el PPC en dolares con el MEP del dia de la
operacion. Los pesos del broker se mueven por el neto de cada boleto.

Lo que este modulo NO cubre: cobros de renta y amortizacion,
transferencias y operaciones en dolares. El JSON de tenencia sigue
siendo el control.
"""

import base64
import io
import json
import logging
import re
import time
from datetime import datetime

import db

log = logging.getLogger("boletos")

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE = "https://www.googleapis.com/drive/v3/files"
MOTIVOS = ("stop", "objetivo", "propio", "sin motivo")

_listo = False


def _asegurar():
    global _listo
    if _listo:
        return
    c = db.conn()
    c.executescript("""
CREATE TABLE IF NOT EXISTS boleto (
  bol        TEXT PRIMARY KEY,
  broker     TEXT NOT NULL,
  fecha      TEXT,            -- dia y hora de la orden
  liquida    TEXT,
  tipo       TEXT,            -- compra | venta
  simbolo    TEXT,
  codigo     TEXT,
  descripcion TEXT,
  cantidad   REAL,
  precio     REAL,            -- el del boleto, en la base en que cotiza
  neto       REAL,            -- lo debitado o acreditado, con gastos
  gastos     REAL,
  iva        REAL,
  moneda     TEXT,
  orden      TEXT,
  archivo    TEXT,
  estado     TEXT NOT NULL DEFAULT 'pendiente',
  leido      TEXT,
  aplicado   TEXT,
  nota       TEXT
);
CREATE INDEX IF NOT EXISTS ix_boleto_estado ON boleto(estado, broker);
CREATE TABLE IF NOT EXISTS boleto_archivo (
  id       TEXT PRIMARY KEY,   -- id de Drive, o "manual:<nombre>:<ts>"
  nombre   TEXT,
  leido    TEXT,
  boletos  INTEGER,
  error    TEXT
);
""")
    c.commit()
    _listo = True


# -- lectura del PDF ----------------------------------------------------

def _num(s):
    return float(s.replace(".", "").replace(",", "."))


def texto_pdf(datos):
    import pypdf
    r = pypdf.PdfReader(io.BytesIO(datos))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def parsear(texto):
    """Los boletos de un PDF de Veta. Cada boleto viene dos veces
    (ORIGINAL y DUPLICADO): se queda el primero por numero."""
    out, vistos = [], set()
    # Un boleto con muchas ejecuciones ocupa varias paginas, y cada pagina
    # repite el encabezado "BOL n": la linea del total y los gastos estan
    # en la ultima (NFLX del 21/10, 8 registros en 3 paginas). Se juntan
    # las paginas del ORIGINAL de cada numero; el DUPLICADO se descarta.
    bloques = {}
    for b in re.split(r"(?=BOL \d{6,})", texto):
        m = re.match(r"BOL (\d+)", b)
        if m:
            bloques.setdefault(m.group(1), []).append(b)
    partes = []
    for num, bs in bloques.items():
        orig = [b for b in bs if "DUPLICADO" not in b]
        partes.append("\n".join(orig or bs[:1]))
    for b in partes:
        m = re.match(r"BOL (\d+)", b)
        if not m or m.group(1) in vistos:
            continue
        ins = re.search(r"Instr\.:\s*\[(\w+)\]\s*([A-Za-z0-9]+)\s*-?\s*([^\n]*)", b)
        res = re.search(r"Result\.:\s*(Compra|Venta)\s+([\d\.,]+)@([\d\.,]+)\s*\((\w+)", b)
        tot = re.search(r"Se (debitar|acreditar)[áa].*?(ARS|USD|U\$S)\s*([\d\.,]+)\s*([AD])\b", b, re.S)
        orden = re.search(r"Orden (\d+) del (\d{2})/(\d{2})/(\d{4}) (\d{2}:\d{2}:\d{2})", b)
        liq = re.search(r"Liquidaci[óo]n del d[íi]a (\d{2})/(\d{2})/(\d{4})", b)
        fecha = None
        if orden:
            fecha = "%s-%s-%sT%s" % (orden.group(4), orden.group(3), orden.group(2), orden.group(5))
        cau = re.search(r"Operaci[óo]n de (apertura|cierre) de cauci[óo]n (colocadora|tomadora)", b)
        cres = re.search(r"Result\.:\s*Cauci[óo]n \w+\s+([\d\.,]+)@([\d\.,]+)%\s*\((\w+)\s+(\d+)", b)
        if cau and cres and tot:
            # Caucion: es moneda. La apertura saca pesos y los deja en la
            # linea CAUCION; el cierre los devuelve con el interes.
            recs = re.findall(r"(?:Rec\.|Arancel)\s*([^\n]*?)\s+(?:ARS|USD|U\$S)\s*([\d\.,]+)\s*D\b", b)
            vistos.add(m.group(1))
            out.append({
                "bol": m.group(1), "tipo": "caucion_" + cau.group(1).lower(),
                "simbolo": "CAUCION", "codigo": cau.group(2).lower(),
                "descripcion": "Caución %s %s al %s%% · %s día%s" % (
                    cau.group(2).lower(), cres.group(1), cres.group(2), cres.group(4),
                    "" if cres.group(4) == "1" else "s"),
                "cantidad": _num(cres.group(1)), "precio": _num(cres.group(2)),
                "moneda": "ARS" if cres.group(3).upper() == "ARS" else "USD",
                "neto": _num(tot.group(3)),
                "gastos": round(sum(_num(v) for n, v in recs if "IVA" not in n), 2),
                "iva": round(sum(_num(v) for n, v in recs if "IVA" in n), 2),
                "orden": orden.group(1) if orden else None, "fecha": fecha,
                "liquida": ("%s-%s-%s" % (liq.group(3), liq.group(2), liq.group(1))) if liq else None,
            })
            continue
        if not (ins and res and tot):
            # Cobro u otra cosa que no es compra ni venta: se
            # guarda como informativa para que no se pierda en silencio.
            r2 = re.search(r"Result\.:\s*([^\n]+)", b)
            if not r2:
                continue
            vistos.add(m.group(1))
            txt = re.sub(r"\s+", " ", r2.group(1)).strip()
            out.append({
                "bol": m.group(1), "tipo": "caucion" if "auci" in txt else "otro",
                "simbolo": None, "codigo": ins.group(1) if ins else None,
                "descripcion": txt, "cantidad": None, "precio": None,
                "moneda": None, "neto": _num(tot.group(3)) * (1 if tot.group(4) == "A" else -1) if tot else None,
                "gastos": 0.0, "iva": 0.0, "orden": orden.group(1) if orden else None,
                "fecha": fecha,
                "liquida": ("%s-%s-%s" % (liq.group(3), liq.group(2), liq.group(1))) if liq else None,
            })
            continue
        # Los gastos son las lineas "Rec." (aranceles, derechos e IVA): el
        # renglon de total "Gastos" no siempre viene.
        recs = re.findall(r"(?:Rec\.|Arancel)\s*([^\n]*?)\s+(?:ARS|USD|U\$S)\s*([\d\.,]+)\s*D\b", b)
        iva_v = sum(_num(v) for n, v in recs if "IVA" in n)
        gas_v = sum(_num(v) for n, v in recs if "IVA" not in n)
        vistos.add(m.group(1))
        out.append({
            "bol": m.group(1),
            "tipo": res.group(1).lower(),
            "simbolo": ins.group(2).upper(),
            "codigo": ins.group(1),
            "descripcion": re.sub(r"\s+", " ", ins.group(3)).strip(),
            "cantidad": _num(res.group(2)),
            "precio": _num(res.group(3)),
            "moneda": "ARS" if res.group(4).upper() == "ARS" else "USD",
            "neto": _num(tot.group(3)),
            "gastos": round(gas_v, 2),
            "iva": round(iva_v, 2),
            "orden": orden.group(1) if orden else None,
            "fecha": fecha,
            "liquida": ("%s-%s-%s" % (liq.group(3), liq.group(2), liq.group(1))) if liq else None,
        })
    return out


def guardar(boletos, broker, archivo):
    """Los nuevos quedan pendientes; los que ya estaban no se tocan."""
    _asegurar()
    c = db.conn()
    ahora = datetime.now().isoformat(timespec="seconds")
    nuevos = 0
    for b in boletos:
        estado = "pendiente" if (b["tipo"] in ("compra", "venta")
                                 or b["tipo"].startswith("caucion_")) else "informativo"
        # Un boleto que antes quedo como informativo porque no se pudo leer
        # entero (las paginas de un boleto largo) se completa al releerlo.
        if estado == "pendiente":
            c.execute("DELETE FROM boleto WHERE bol=? AND estado='informativo'", (b["bol"],))
        cur = c.execute(
            "INSERT OR IGNORE INTO boleto (bol, broker, fecha, liquida, tipo, "
            "simbolo, codigo, descripcion, cantidad, precio, neto, gastos, iva, "
            "moneda, orden, archivo, leido, estado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (b["bol"], broker, b["fecha"], b["liquida"], b["tipo"], b["simbolo"],
             b["codigo"], b["descripcion"], b["cantidad"], b["precio"], b["neto"],
             b["gastos"], b["iva"], b["moneda"], b["orden"], archivo, ahora, estado))
        nuevos += cur.rowcount if estado == "pendiente" else 0
    c.commit()
    return nuevos


def cargar_pdf(datos, nombre, broker, archivo_id=None):
    """Lee un PDF y guarda sus boletos. Devuelve (leidos, nuevos)."""
    _asegurar()
    archivo_id = archivo_id or "manual:%s:%s" % (nombre, datetime.now().isoformat(timespec="seconds"))
    c = db.conn()
    try:
        bols = parsear(texto_pdf(datos))
        n = guardar(bols, broker, nombre)
        c.execute("INSERT OR REPLACE INTO boleto_archivo (id, nombre, leido, boletos, error) "
                  "VALUES (?,?,?,?,NULL)", (archivo_id, nombre,
                                            datetime.now().isoformat(timespec="seconds"), len(bols)))
        c.commit()
        return len(bols), n
    except Exception as e:
        c.execute("INSERT OR REPLACE INTO boleto_archivo (id, nombre, leido, boletos, error) "
                  "VALUES (?,?,?,0,?)", (archivo_id, nombre,
                                         datetime.now().isoformat(timespec="seconds"), str(e)[:300]))
        c.commit()
        raise


# -- Google Drive -------------------------------------------------------

def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _token(clave):
    """Token de la cuenta de servicio (JWT firmado con su clave)."""
    import requests
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    info = json.loads(clave) if isinstance(clave, str) else clave
    uri = info.get("token_uri") or "https://oauth2.googleapis.com/token"
    ahora = int(time.time())
    cab = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    cue = _b64(json.dumps({"iss": info["client_email"], "scope": SCOPE, "aud": uri,
                           "iat": ahora, "exp": ahora + 3600}).encode())
    llave = serialization.load_pem_private_key(info["private_key"].encode(), password=None)
    firma = llave.sign(("%s.%s" % (cab, cue)).encode(), padding.PKCS1v15(), hashes.SHA256())
    r = requests.post(uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                 "assertion": "%s.%s.%s" % (cab, cue, _b64(firma))}, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError("Google rechazó la clave: HTTP %s %s" % (r.status_code, r.text[:160]))
    return r.json()["access_token"]


def revisar_drive(clave, carpeta, broker):
    """Baja los PDF nuevos de la carpeta y guarda sus boletos.

    Devuelve {"archivos": n, "boletos": nuevos}. Un archivo ya leido no
    se vuelve a bajar; uno que fallo se reintenta en la proxima revision.
    """
    import requests
    _asegurar()
    if not clave or not carpeta:
        raise RuntimeError("Falta configurar la clave de Google o la carpeta de Drive.")
    tok = _token(clave)
    cab = {"Authorization": "Bearer " + tok}
    q = "'%s' in parents and trashed=false and mimeType='application/pdf'" % carpeta
    archivos, pagina = [], None
    while True:
        params = {"q": q, "fields": "nextPageToken,files(id,name,createdTime)",
                  "orderBy": "createdTime", "pageSize": 100}
        if pagina:
            params["pageToken"] = pagina
        r = requests.get(DRIVE, headers=cab, params=params, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError("Drive: HTTP %s %s" % (r.status_code, r.text[:160]))
        d = r.json()
        archivos += d.get("files") or []
        pagina = d.get("nextPageToken")
        if not pagina:
            break
    c = db.conn()
    # Los archivos con una compra o venta que quedo como informativa se
    # vuelven a leer: es el caso de los boletos de varias paginas que el
    # lector anterior no juntaba.
    c.execute("DELETE FROM boleto_archivo WHERE nombre IN (SELECT archivo FROM boleto WHERE "
              "estado='informativo' AND (descripcion LIKE 'Compra %' OR descripcion LIKE 'Venta %'))")
    c.commit()
    leidos = {r["id"] for r in c.execute(
        "SELECT id FROM boleto_archivo WHERE error IS NULL")}
    n_arch, n_bol = 0, 0
    for a in archivos:
        if a["id"] in leidos:
            continue
        r = requests.get("%s/%s" % (DRIVE, a["id"]), headers=cab,
                         params={"alt": "media"}, timeout=60)
        if r.status_code >= 300:
            log.warning("boletos: no se pudo bajar %s: HTTP %s", a["name"], r.status_code)
            continue
        try:
            _l, nuevos = cargar_pdf(r.content, a["name"], broker, archivo_id=a["id"])
            n_arch += 1
            n_bol += nuevos
        except Exception as e:
            log.warning("boletos: %s: %s", a["name"], e)
    return {"archivos": n_arch, "boletos": n_bol, "en_carpeta": len(archivos)}


# -- vista previa y aplicacion -------------------------------------------

def pendientes(broker=None):
    _asegurar()
    q = "SELECT * FROM boleto WHERE estado='pendiente'"
    args = []
    if broker:
        q += " AND broker=?"
        args.append(broker)
    return [dict(r) for r in db.conn().execute(q + " ORDER BY fecha, bol", args)]


def corte(broker):
    """Hasta cuando la tenencia del broker ya refleja las operaciones: la
    ultima carga por JSON (o por API). Un boleto anterior probablemente ya
    esta incluido y aplicarlo lo contaria dos veces.

    Lo marca `db.guardar_tenencias`. Si nunca se marco (cargas anteriores
    a esta funcion), se toma la ultima foto del broker y se deja fijado:
    las fotos que despues saque la aplicacion de boletos no lo mueven.
    """
    k = "carga_tenencia:" + broker
    v = db.get_estado(k)
    if not v:
        r = db.conn().execute("SELECT MAX(ts) t FROM tenencia_hist WHERE broker=?",
                              (broker,)).fetchone()
        v = r["t"] if r and r["t"] else ""
        if v:
            db.set_estado(k, v)
    return v or None


def _tenencia(broker):
    return {t["simbolo"]: t for t in db.tenencias(broker)}


def _tipo_de(sim):
    """El tipo de una especie que entra nueva: el de otra cuenta, el del
    catalogo de bonos, o acciones."""
    for t in db.tenencias():
        if t["simbolo"] == sim and t.get("tipo"):
            return t["tipo"]
    try:
        import bonos as BO
        if sim in BO.especies():
            return "bonos"
    except Exception:
        pass
    return None


def _base(sim, tipo=None):
    b = db.base_cotizacion(sim)
    if b:
        return b
    return 100.0 if tipo in ("bonos", "letras", "on", "bcra") else 1.0


def preparar(broker):
    """Los pendientes agrupados por dia, especie y sentido, con lo que
    cambiaria en la tenencia. No escribe nada."""
    import gestion as GE
    bols = pendientes(broker)
    ten = _tenencia(broker)
    tocados = {}
    try:
        tocados = GE.tocados()
    except Exception:
        pass
    grupos, cauciones = {}, {}
    for b in bols:
        if (b["tipo"] or "").startswith("caucion_"):
            k = "%s|caucion|%s" % ((b["fecha"] or "")[:10], b["orden"] or b["bol"])
            g = cauciones.setdefault(k, {"clave": k, "fecha": (b["fecha"] or "")[:10],
                                         "tipo": "caucion", "simbolo": "CAUCION",
                                         "lado": b["codigo"], "descripcion": b["descripcion"],
                                         "moneda": b["moneda"], "capital": b["cantidad"],
                                         "tasa": b["precio"], "boletos": [], "apertura": None,
                                         "cierre": None, "gastos": 0.0, "avisos": []})
            g["boletos"].append({k2: b[k2] for k2 in ("bol", "orden", "fecha", "cantidad", "precio", "neto", "tipo", "liquida")})
            g["apertura" if b["tipo"] == "caucion_apertura" else "cierre"] = b["neto"]
            g["gastos"] += (b["gastos"] or 0) + (b["iva"] or 0)
            continue
        k = "%s|%s|%s" % ((b["fecha"] or "")[:10], b["tipo"], b["simbolo"])
        g = grupos.setdefault(k, {"clave": k, "fecha": (b["fecha"] or "")[:10],
                                  "tipo": b["tipo"], "simbolo": b["simbolo"],
                                  "descripcion": b["descripcion"], "moneda": b["moneda"],
                                  "boletos": [], "cantidad": 0.0, "neto": 0.0,
                                  "gastos": 0.0, "bruto": 0.0})
        g["boletos"].append({k2: b[k2] for k2 in ("bol", "orden", "fecha", "cantidad", "precio", "neto")})
        g["cantidad"] += b["cantidad"]
        g["neto"] += b["neto"]
        g["gastos"] += (b["gastos"] or 0) + (b["iva"] or 0)
    ars = ten.get("ARS")
    hasta = corte(broker)
    lista = sorted(grupos.values(), key=lambda x: (x["fecha"], x["tipo"] != "venta", x["simbolo"]))
    # Cantidad y PPC corridos en orden: dos compras de la misma especie en
    # dias distintos se suman una sobre la otra. Lo que ya estaba incluido
    # en la ultima carga no mueve nada.
    run = {}
    for g in lista:
        sim = g["simbolo"]
        t = ten.get(sim)
        if sim not in run:
            run[sim] = {"cant": (t or {}).get("cantidad") or 0.0,
                        "ppc_u": (((t or {}).get("ppc") or 0) / ((t or {}).get("ppc_base") or 1)) if t else 0.0}
        tipo = (t or {}).get("tipo") or _tipo_de(sim)
        base = _base(sim, tipo)
        g["tipo_tenencia"] = tipo or "acciones"
        g["tipo_conocido"] = bool(tipo)
        g["base"] = base
        g["precio_bol"] = sum(x["cantidad"] * x["precio"] for x in g["boletos"]) / g["cantidad"]
        g["precio_ef"] = g["neto"] / g["cantidad"] * base
        g["avisos"] = []
        ult = max((x["fecha"] or "") for x in g["boletos"])
        g["ya_incluido"] = bool(hasta and ult and ult < hasta)
        if g["ya_incluido"]:
            g["avisos"].append("Es anterior a la última carga de la tenencia de %s (%s/%s %s): "
                               "probablemente ya esté incluida." % (
                                   broker, hasta[8:10], hasta[5:7], hasta[11:16]))
        if g["moneda"] != "ARS":
            g["avisos"].append("Operación en dólares: todavía no se aplica sola.")
        antes, ppc_u = run[sim]["cant"], run[sim]["ppc_u"]
        g["antes"] = antes
        g["ppc_antes"] = ppc_u * base if ppc_u else None
        if g["tipo"] == "compra":
            despues = antes + g["cantidad"]
            nu = g["precio_ef"] / base
            nuevo_u = (antes * ppc_u + g["cantidad"] * nu) / despues if (antes > 1e-9 and ppc_u) else nu
            g["ppc_despues"] = nuevo_u * base
            g["resultado"] = None
        else:
            despues = antes - g["cantidad"]
            nuevo_u = ppc_u
            g["ppc_despues"] = g["ppc_antes"] if despues > 1e-9 else None
            g["resultado"] = (g["neto"] - g["cantidad"] * ppc_u) if ppc_u else None
            if g["cantidad"] > antes + 1e-6 and not g["ya_incluido"]:
                g["avisos"].append("%s tiene %s en %s y el boleto vende %s." % (
                    sim, _fmt(antes), broker, _fmt(g["cantidad"])))
        g["despues"] = despues
        if not g["ya_incluido"]:
            run[sim] = {"cant": despues, "ppc_u": nuevo_u}
        g["estrategia_id"] = db._estrategia_de(sim)
        g["motivo"] = None
        if g["tipo"] == "venta":
            que = tocados.get(sim)
            g["motivo"] = "stop" if que == "stop" else "objetivo" if que == "objetivo" else "sin motivo"

    # Cauciones: colocadora saca pesos en la apertura y los devuelve con
    # el interes en el cierre; tomadora al reves. Mientras esta abierta,
    # el capital vive en la linea de moneda CAUCION.
    cau = ten.get("CAUCION")
    cau_run = (cau or {}).get("cantidad") or 0.0
    for g in sorted(cauciones.values(), key=lambda x: x["fecha"]):
        sg = 1 if g["lado"] == "colocadora" else -1
        ars_d, cau_d = 0.0, 0.0
        if g["apertura"] is not None:
            ars_d -= sg * g["apertura"]
            cau_d += sg * g["capital"]
        if g["cierre"] is not None:
            ars_d += sg * g["cierre"]
            cau_d -= sg * g["capital"]
        g["efecto_ars"], g["efecto_caucion"] = ars_d, cau_d
        g["interes_neto"] = (sg * (g["cierre"] - g["apertura"])
                             if g["apertura"] is not None and g["cierre"] is not None else None)
        ult = max((x["fecha"] or "") for x in g["boletos"])
        g["ya_incluido"] = bool(hasta and ult and ult < hasta)
        if g["ya_incluido"]:
            g["avisos"].append("Es anterior a la última carga de la tenencia de %s (%s/%s %s): "
                               "probablemente ya esté incluida." % (
                                   broker, hasta[8:10], hasta[5:7], hasta[11:16]))
        if g["cierre"] is None:
            g["avisos"].append("Falta el boleto de cierre: el capital queda en la línea CAUCION hasta que llegue.")
        g["antes"] = cau_run
        g["despues"] = cau_run + (cau_d if not g["ya_incluido"] else 0)
        if not g["ya_incluido"]:
            cau_run = g["despues"]
    lista += sorted(cauciones.values(), key=lambda x: x["fecha"])
    neto = sum((g["neto"] if g["tipo"] == "venta" else -g["neto"]) if g["tipo"] != "caucion" else g["efecto_ars"]
               for g in lista if g["moneda"] == "ARS" and not g["ya_incluido"])
    return {"broker": broker, "grupos": lista,
            "pesos": {"tiene": bool(ars), "antes": (ars or {}).get("cantidad"),
                      "despues": ((ars or {}).get("cantidad") or 0) + neto if ars else None,
                      "neto": neto}}


def _fmt(v):
    return ("{:,.2f}".format(v)).replace(",", "X").replace(".", ",").replace("X", ".")


def descartar(broker, claves=None):
    _asegurar()
    c = db.conn()
    n = 0
    for b in pendientes(broker):
        k = "%s|%s|%s" % ((b["fecha"] or "")[:10], b["tipo"], b["simbolo"])
        if claves is None or k in claves:
            c.execute("UPDATE boleto SET estado='descartado', aplicado=? WHERE bol=?",
                      (datetime.now().isoformat(timespec="seconds"), b["bol"]))
            n += 1
    c.commit()
    return n


def aplicar(broker, decisiones, precios=None, rotacion=None):
    """Aplica los grupos confirmados.

    `decisiones`: {clave: {"estrategia_id", "motivo", "tipo_tenencia"}}.
    `rotacion`: {"venta": clave, "compra": clave, "estrategia_id"} para
    unir una venta y una compra en una sola rotacion.
    `precios`: precios de ahora por simbolo, para medir la cuotaparte de
    las estrategias (equiv_antes).
    """
    import gestion as GE
    _asegurar()
    prev = preparar(broker)
    decisiones = decisiones or {}
    omitir = [g for g in prev["grupos"]
              if g["clave"] in decisiones and decisiones[g["clave"]].get("aplicar") is False]
    grupos = {g["clave"]: g for g in prev["grupos"]
              if g["clave"] in decisiones and decisiones[g["clave"]].get("aplicar") is not False}
    c0 = db.conn()
    for g in omitir:
        for x in g["boletos"]:
            c0.execute("UPDATE boleto SET estado='omitido', aplicado=? WHERE bol=?",
                       (datetime.now().isoformat(timespec="seconds"), x["bol"]))
    c0.commit()
    if not grupos:
        return {"aplicados": 0, "omitidos": sum(len(g["boletos"]) for g in omitir)}
    caus = {k: g for k, g in grupos.items() if g["tipo"] == "caucion"}
    grupos = {k: g for k, g in grupos.items() if g["tipo"] != "caucion"}
    cant = {t["simbolo"]: t["cantidad"] or 0 for t in db.tenencias(broker)}
    for g in sorted(grupos.values(), key=lambda x: (x["fecha"], x["tipo"] != "venta")):
        if g["moneda"] != "ARS":
            raise ValueError("%s: operación en dólares, no se aplica sola." % g["simbolo"])
        q = cant.get(g["simbolo"], 0)
        if g["tipo"] == "venta" and g["cantidad"] > q + 1e-6:
            raise ValueError("%s tiene %s en %s y el boleto vende %s." % (
                g["simbolo"], _fmt(q), broker, _fmt(g["cantidad"])))
        cant[g["simbolo"]] = q + (g["cantidad"] if g["tipo"] == "compra" else -g["cantidad"])
    c = db.conn()
    precios = dict(precios or {})
    ahora = datetime.now().isoformat(timespec="seconds")

    # foto de antes: si la tenencia cambio sin foto, la toma ahora
    db.snapshot(broker)
    r = c.execute("SELECT MAX(ts) t FROM tenencia_hist WHERE broker=?", (broker,)).fetchone()
    desde = r["t"] if r else ahora

    ten = _tenencia(broker)
    neto_ars = 0.0
    for g in sorted(grupos.values(), key=lambda x: (x["fecha"], x["tipo"] != "venta")):
        sim, t = g["simbolo"], _tenencia(broker).get(g["simbolo"])
        precios[sim] = g["precio_ef"]
        if g["tipo"] == "compra":
            neto_ars -= g["neto"]
            if t:
                c.execute("UPDATE tenencia SET cantidad=cantidad+? WHERE broker=? AND simbolo=?",
                          (g["cantidad"], broker, sim))
            else:
                tipo = (decisiones[g["clave"]] or {}).get("tipo_tenencia") or g["tipo_tenencia"]
                c.execute("INSERT INTO tenencia (broker, simbolo, cantidad, tipo, ts, fecha_alta, "
                          "precision) VALUES (?,?,?,?,?,?,?)",
                          (broker, sim, g["cantidad"], tipo, ahora, g["fecha"], "exacta"))
            c.commit()
            # PPC con gastos y al MEP del dia de la operacion, en orden:
            # cada compra promedia contra lo que habia justo antes.
            db._promediar_ppc(broker, sim, g["cantidad"], g["precio_ef"], ts=g["fecha"])
        else:
            neto_ars += g["neto"]
            if (t or {}).get("cantidad", 0) - g["cantidad"] <= 1e-9:
                c.execute("DELETE FROM tenencia WHERE broker=? AND simbolo=?", (broker, sim))
            else:
                c.execute("UPDATE tenencia SET cantidad=cantidad-? WHERE broker=? AND simbolo=?",
                          (g["cantidad"], broker, sim))
        c.commit()
    cau_d = 0.0
    for g in caus.values():
        neto_ars += g["efecto_ars"]
        cau_d += g["efecto_caucion"]
    if abs(cau_d) > 1e-9:
        t = _tenencia(broker).get("CAUCION")
        nueva = ((t or {}).get("cantidad") or 0) + cau_d
        if t and abs(nueva) <= 1e-6:
            c.execute("DELETE FROM tenencia WHERE broker=? AND simbolo='CAUCION'", (broker,))
        elif t:
            c.execute("UPDATE tenencia SET cantidad=? WHERE broker=? AND simbolo='CAUCION'",
                      (nueva, broker))
        else:
            c.execute("INSERT INTO tenencia (broker, simbolo, cantidad, tipo, ts) "
                      "VALUES (?,?,?,?,?)", (broker, "CAUCION", nueva, "moneda", ahora))
    if "ARS" in ten:
        c.execute("UPDATE tenencia SET cantidad=cantidad+? WHERE broker=? AND simbolo='ARS'",
                  (neto_ars, broker))
    c.commit()
    db.snapshot(broker)
    r = c.execute("SELECT MAX(ts) t FROM tenencia_hist WHERE broker=?", (broker,)).fetchone()
    hasta = r["t"] if r else ahora

    def base_de(eid):
        e = c.execute("SELECT ticker_base FROM estrategia WHERE id=?", (eid,)).fetchone()
        return e["ticker_base"] if e else None

    def nota_de(g, motivo=None):
        bols = ", ".join(x["bol"] for x in g["boletos"])
        n = "Boletos %s" % bols
        if g["tipo"] == "venta":
            n = "Venta%s · %s" % ((" por " + motivo) if motivo and motivo != "sin motivo" else "", n)
            if g.get("resultado") is not None:
                n += " · resultado $ %s" % _fmt(g["resultado"])
        return n

    usados = set()
    if rotacion and rotacion.get("venta") in grupos and rotacion.get("compra") in grupos:
        v, k = grupos[rotacion["venta"]], grupos[rotacion["compra"]]
        eid = rotacion.get("estrategia_id") or (decisiones.get(v["clave"]) or {}).get("estrategia_id")
        if eid:
            eid = int(eid)
            d = {"tipo": "rotacion", "sale": v["simbolo"], "cant_sale": v["cantidad"],
                 "precio_sale": v["precio_ef"], "entra": k["simbolo"],
                 "cant_entra": k["cantidad"], "precio_entra": k["precio_ef"],
                 "ratio": k["cantidad"] / v["cantidad"] if v["cantidad"] else None,
                 "hasta": k["boletos"][-1]["fecha"] or hasta, "signo": 1,
                 "nota": "Rotación · " + nota_de(v, (decisiones.get(v["clave"]) or {}).get("motivo"))}
            db.registrar_mov_estrategia(eid, d)
            db.asignar(k["simbolo"], eid)
            usados |= {v["clave"], k["clave"]}

    for g in grupos.values():
        if g["clave"] in usados:
            continue
        dec = decisiones.get(g["clave"]) or {}
        eid = dec.get("estrategia_id")
        motivo = dec.get("motivo") if dec.get("motivo") in MOTIVOS else g.get("motivo")
        g["motivo_final"] = motivo
        if not eid:
            continue
        eid = int(eid)
        base = base_de(eid)
        if base and base not in precios:
            precios[base] = None
        d = {"tipo": "aporte" if g["tipo"] == "compra" else "retiro", "signo": 1,
             "hasta": g["boletos"][-1]["fecha"] or hasta,
             "precio_base": precios.get(base) if base else None,
             "nota": nota_de(g, motivo)}
        if g["tipo"] == "compra":
            d.update(entra=g["simbolo"], cant_entra=g["cantidad"], precio_entra=g["precio_ef"])
        else:
            d.update(sale=g["simbolo"], cant_sale=g["cantidad"], precio_sale=g["precio_ef"])
        try:
            d["equiv_antes"] = db._equiv_en_base(eid, base, broker, desde, hasta,
                                                 {k2: v2 for k2, v2 in precios.items() if v2})
        except Exception as e:
            log.info("equiv_antes de %s: %s", eid, e)
            d["equiv_antes"] = None
        db.registrar_mov_estrategia(eid, d)
        if g["tipo"] == "compra" and not db._estrategia_de(g["simbolo"]):
            db.asignar(g["simbolo"], eid)

    # Una especie que quedo en cero en todas las cuentas: sus niveles de
    # Gestion se archivan con el resultado y el motivo, y dejan de avisar.
    archivados = []
    for g in grupos.values():
        if g["tipo"] != "venta":
            continue
        r = c.execute("SELECT SUM(cantidad) t FROM tenencia WHERE simbolo=?",
                      (g["simbolo"],)).fetchone()
        if r and (r["t"] or 0) > 1e-9:
            continue
        try:
            if GE.archivar_nivel(g["simbolo"], g.get("motivo_final"), g.get("resultado"),
                                 g["fecha"], g["precio_ef"]):
                archivados.append(g["simbolo"])
        except Exception as e:
            log.info("archivar nivel %s: %s", g["simbolo"], e)

    for g in list(grupos.values()) + list(caus.values()):
        for x in g["boletos"]:
            c.execute("UPDATE boleto SET estado='aplicado', aplicado=?, nota=? WHERE bol=?",
                      (ahora, g.get("motivo_final"), x["bol"]))
    c.commit()
    return {"aplicados": sum(len(g["boletos"]) for g in list(grupos.values()) + list(caus.values())),
            "omitidos": sum(len(g["boletos"]) for g in omitir),
            "grupos": len(grupos), "archivados": archivados,
            "pesos": neto_ars if "ARS" in ten else None}


def informativos(broker, dias=10):
    _asegurar()
    from datetime import timedelta
    desde = (datetime.now() - timedelta(days=dias)).isoformat()
    return [dict(r) for r in db.conn().execute(
        "SELECT bol, fecha, tipo, descripcion, neto FROM boleto WHERE broker=? AND "
        "estado='informativo' AND leido >= ? ORDER BY fecha", (broker, desde))]


def estado_fuente():
    _asegurar()
    c = db.conn()
    ult = c.execute("SELECT * FROM boleto_archivo ORDER BY leido DESC LIMIT 1").fetchone()
    return {"ultima_revision": db.get_estado("boletos_revision"),
            "ultimo_error": db.get_estado("boletos_error"),
            "ultimo_archivo": dict(ult) if ult else None,
            "archivos": c.execute("SELECT COUNT(*) n FROM boleto_archivo").fetchone()["n"]}
