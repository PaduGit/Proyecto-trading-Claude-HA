"""Respaldo de configuración y posición en /data.

Home Assistant borra el volumen /data al desinstalar una app, así que
esto no protege contra eso; lo que sí hace es sobrevivir a los cambios
de configuración y permitir exportar la posición a un texto que puedas
guardar afuera.
"""

import json
import logging
import os
from datetime import datetime

import db

log = logging.getLogger("respaldo")

RUTA = os.environ.get("RATIOS_RESPALDO", "/data/respaldo.json")

# nunca se guardan credenciales en el archivo
SECRETOS = ("iol_pass", "ha_token", "telegram_token", "iol_user",
            "telegram_chat_id", "iol2_user", "iol2_pass")


def guardar_config(cfg):
    """Copia lo que cuesta recargar a mano. Sin credenciales."""
    datos = {k: v for k, v in (cfg or {}).items() if k not in SECRETOS}
    datos["_guardado"] = datetime.now().isoformat(timespec="seconds")
    try:
        with open(RUTA, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        return True
    except Exception as e:
        log.warning("no se pudo guardar el respaldo: %s", e)
        return False


def leer_config():
    try:
        with open(RUTA, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        log.warning("respaldo ilegible: %s", e)
        return None


def restaurar_si_vacio(cfg):
    """Si una lista viene vacía, la toma del respaldo.

    Solo actúa cuando la lista está vacía: si borraste un par a
    propósito, no lo resucita.
    """
    prev = leer_config()
    if not prev:
        return cfg, []

    repuestos = []
    # "pares" y "paneles" ya no se usan: los pares viven en la base y la
    # bajada la hace orleans. Reponerlos solo generaba ruido en el log.
    for clave in ("arbitraje_tickers", "comisiones"):
        if not cfg.get(clave) and prev.get(clave):
            cfg[clave] = prev[clave]
            repuestos.append(clave)
    if repuestos:
        log.info("restaurado del respaldo: %s (guardado el %s)",
                 ", ".join(repuestos), prev.get("_guardado", "?"))
    return cfg, repuestos


# -- posición ---------------------------------------------------------

def exportar_posicion():
    """Pares, estrategias y sus ledgers, en un JSON para guardar afuera.

    Los `movimientos` de cada grupo son los del modelo viejo y se
    conservan por compatibilidad con los export ya guardados. Lo que hoy
    mide es `estrategias`, con sus especies y su ledger propio.
    """
    # version 2 sumo los datos del par; la 3, las estrategias con su
    # ledger propio. Un export viejo se sigue importando: lo que no
    # trae, no se toca.
    salida = {"version": 3,
              "exportado": datetime.now().isoformat(timespec="seconds"),
              "grupos": [], "estrategias": []}
    for g in db.listar_grupos():
        movs = []
        for m in db.movimientos_de(g["id"]):
            movs.append({
                "ts": m["ts"], "tipo": m["tipo"],
                "ticker_de": m["ticker_de"], "cant_de": m["cant_de"],
                "ticker_a": m["ticker_a"], "cant_a": m["cant_a"],
                "ratio_base": m["ratio_base"],
                "equiv_antes": (m["equiv_antes"]
                                if "equiv_antes" in m.keys() else None),
                "nota": m["nota"],
            })
        # los datos del par van en el export: es lo que permite
        # recuperarlos despues de una reinstalacion
        salida["grupos"].append({
            "nombre": g["nombre"], "base": g["base"],
            "tickers": g["tickers"], "mercado": g["mercado"],
            "num": g.get("num"), "den": g.get("den"),
            "plazo": g.get("plazo"), "resistencia": g.get("resistencia"),
            "soporte": g.get("soporte"),
            "alertas": g.get("alertas", 1), "factor": g.get("factor"),
            "movimientos": movs,
        })
    salida["estrategias"] = _estrategias_export()
    return salida


def _estrategias_export():
    """Cada estrategia con sus especies y su ledger."""
    out = []
    for e in db.estrategias(incluir_cerradas=True):
        out.append({
            "nombre": e["nombre"], "familia": e["familia"],
            "tesis": e["tesis"], "origen": e["origen"],
            "patron": e["patron"], "patron_valor": e["patron_valor"],
            "ticker_base": e["ticker_base"],
            "objetivo": e["objetivo"], "stop": e["stop"],
            "revisar": e["revisar"], "alta": e["alta"],
            "cierre": e["cierre"], "motivo_cierre": e["motivo_cierre"],
            "grupo": _nombre_grupo(e["grupo_id"]),
            "especies": db.especies_de(e["id"]),
            "movimientos": [{
                "ts": m["ts"], "tipo": m["tipo"],
                "ticker_de": m["ticker_de"], "cant_de": m["cant_de"],
                "ticker_a": m["ticker_a"], "cant_a": m["cant_a"],
                "ratio_base": m["ratio_base"],
                "equiv_antes": m["equiv_antes"], "nota": m["nota"],
            } for m in db.movimientos_estrategia(e["id"])],
        })
    return out


def _nombre_grupo(gid):
    """El grupo va por nombre: los id cambian al reimportar."""
    if not gid:
        return None
    g = db.grupo_por_id(gid)
    return g["nombre"] if g else None


def importar_posicion(datos, reemplazar=False):
    """Carga grupos y movimientos desde un export.

    Por defecto no toca lo que ya existe: un grupo con el mismo nombre
    se saltea. Con reemplazar=True se borra y se vuelve a crear.
    """
    if isinstance(datos, str):
        datos = json.loads(datos)
    if not isinstance(datos, dict) or "grupos" not in datos:
        raise ValueError("El texto no tiene el formato de un export.")

    existentes = {g["nombre"]: g["id"] for g in db.listar_grupos()}
    creados, salteados, movs = 0, 0, 0

    for g in datos["grupos"]:
        nombre = (g.get("nombre") or "").strip()
        base = (g.get("base") or "").strip().upper()
        tickers = [t.strip().upper() for t in (g.get("tickers") or []) if t]
        if not nombre or len(tickers) < 2 or base not in tickers:
            salteados += 1
            continue

        if nombre in existentes:
            if not reemplazar:
                salteados += 1
                continue
            db.borrar_grupo(existentes[nombre])

        gid = db.crear_grupo(nombre, base, tickers,
                             (g.get("mercado") or "bCBA"))
        # los export version 1 no traen los datos del par; si estan, se
        # restauran para no tener que volver a cargarlos a mano
        campos = {k: g[k] for k in ("num", "den", "plazo", "resistencia",
                                    "soporte", "alertas", "factor")
                  if g.get(k) is not None}
        if campos:
            db.actualizar_par(gid, campos)
        creados += 1
        for m in g.get("movimientos") or []:
            db.registrar_movimiento(
                gid, m.get("tipo") or "rotacion",
                ticker_de=m.get("ticker_de"), cant_de=m.get("cant_de"),
                ticker_a=m.get("ticker_a"), cant_a=m.get("cant_a"),
                ratio_base=m.get("ratio_base"), nota=m.get("nota"),
                ts=m.get("ts"), equiv_antes=m.get("equiv_antes"))
            movs += 1

    est = _importar_estrategias(datos.get("estrategias"), reemplazar)
    return {"grupos_creados": creados, "grupos_salteados": salteados,
            "movimientos": movs, "estrategias": est["creadas"],
            "estrategias_salteadas": est["salteadas"],
            "movimientos_estrategia": est["movimientos"]}


def _importar_estrategias(lista, reemplazar):
    """Recrea las estrategias con sus especies y su ledger.

    Una estrategia con el mismo nombre se saltea salvo que se pida
    reemplazar. El grupo se busca por nombre porque los id no sobreviven
    a una reinstalacion.
    """
    creadas, salteadas, movs = 0, 0, 0
    if not lista:
        return {"creadas": 0, "salteadas": 0, "movimientos": 0}
    ya = {e["nombre"]: e["id"] for e in db.estrategias(incluir_cerradas=True)}
    grupos = {g["nombre"]: g["id"] for g in db.listar_grupos()}
    for e in lista:
        nombre = (e.get("nombre") or "").strip()
        if not nombre:
            salteadas += 1
            continue
        if nombre in ya:
            if not reemplazar:
                salteadas += 1
                continue
            db.borrar_estrategia(ya[nombre])
        datos = {k: e.get(k) for k in (
            "nombre", "familia", "tesis", "origen", "patron", "patron_valor",
            "ticker_base", "objetivo", "stop", "revisar")}
        datos["grupo_id"] = grupos.get(e.get("grupo"))
        try:
            eid = db.guardar_estrategia(datos)
        except (TypeError, ValueError) as err:
            log.warning("estrategia %s: %s", nombre, err)
            salteadas += 1
            continue
        if e.get("alta"):
            db.fijar_alta(eid, e["alta"])
        for sim in e.get("especies") or []:
            db.asignar(sim, eid)
        for m in e.get("movimientos") or []:
            db.registrar_mov_manual(eid, m)
            movs += 1
        if e.get("cierre"):
            db.cerrar_estrategia(eid, e.get("motivo_cierre") or "importada")
        creadas += 1
    return {"creadas": creadas, "salteadas": salteadas, "movimientos": movs}
