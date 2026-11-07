"""Arma el inventario en markdown a partir de los registros de Home Assistant.

Función pura: recibe los datos ya leídos, así se puede probar sin HA.
"""
from datetime import datetime

DOMINIOS_PROPIOS = ("automation", "script")  # van en su propia sección


def _fecha(iso):
    if not iso:
        return "nunca"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def _nombre_disp(d):
    return d.get("name_by_user") or d.get("name") or d.get("id", "?")


def _nombre_entidad(e, estado, dispositivos):
    if estado and estado.get("attributes", {}).get("friendly_name"):
        return estado["attributes"]["friendly_name"]
    if e.get("name"):
        return e["name"]
    orig = e.get("original_name") or ""
    d = dispositivos.get(e.get("device_id"))
    if e.get("has_entity_name") and d:
        return (_nombre_disp(d) + " " + orig).strip()
    return orig or e["entity_id"]


def _marcas(e):
    m = []
    if e.get("disabled_by"):
        m.append("deshabilitada")
    if e.get("hidden_by"):
        m.append("oculta")
    if e.get("entity_category") == "config":
        m.append("config")
    if e.get("entity_category") == "diagnostic":
        m.append("diagnóstico")
    return (" [" + ", ".join(m) + "]") if m else ""


def _linea_disp(d, plataforma):
    partes = [x for x in (d.get("manufacturer"), d.get("model")) if x]
    txt = "**" + _nombre_disp(d) + "**"
    if partes:
        txt += " — " + " ".join(partes)
    extra = []
    if plataforma:
        extra.append(plataforma)
    if d.get("entry_type") == "service":
        extra.append("servicio")
    if d.get("disabled_by"):
        extra.append("deshabilitado")
    if extra:
        txt += " (" + ", ".join(extra) + ")"
    return txt


def generar(datos, sup=None, diag=False, config=True, deshab=True, excluidos=()):
    sup = sup or {}
    excluidos = set(excluidos)
    areas = {a["area_id"]: a for a in datos.get("areas") or []}
    pisos = {p["floor_id"]: p for p in datos.get("pisos") or []}
    disps = {d["id"]: d for d in datos.get("dispositivos") or []}
    estados = {s["entity_id"]: s for s in datos.get("estados") or []}
    registro = datos.get("entidades") or []

    def incluir(e):
        dom = e["entity_id"].split(".", 1)[0]
        if dom in excluidos or dom in DOMINIOS_PROPIOS:
            return False
        cat = e.get("entity_category")
        if cat == "diagnostic" and not diag:
            return False
        if cat == "config" and not config:
            return False
        if (e.get("disabled_by") or e.get("hidden_by")) and not deshab:
            return False
        return True

    # area -> device_id (o None) -> [lineas]
    arbol = {}
    plataforma_disp = {}
    listadas = 0
    for e in sorted(registro, key=lambda x: x["entity_id"]):
        if not incluir(e):
            continue
        d = disps.get(e.get("device_id"))
        area = e.get("area_id") or (d.get("area_id") if d else None)
        did = e.get("device_id") if d else None
        if did and e.get("platform"):
            plataforma_disp.setdefault(did, e["platform"])
        nombre = _nombre_entidad(e, estados.get(e["entity_id"]), disps)
        arbol.setdefault(area, {}).setdefault(did, []).append(
            "- `%s` — %s%s" % (e["entity_id"], nombre, _marcas(e)))
        listadas += 1

    # Entidades sin registro (YAML sin unique_id, grupos, etc.)
    en_registro = {e["entity_id"] for e in registro}
    sin_registro = []
    for eid in sorted(estados):
        dom = eid.split(".", 1)[0]
        if eid in en_registro or dom in excluidos or dom in DOMINIOS_PROPIOS:
            continue
        s = estados[eid]
        sin_registro.append("- `%s` — %s" % (eid, s.get("attributes", {}).get("friendly_name") or eid))

    def bloque(grupos):
        out = []
        con_disp = [k for k in grupos if k]
        con_disp.sort(key=lambda k: _nombre_disp(disps[k]).lower())
        for k in con_disp:
            out.append("")
            out.append(_linea_disp(disps[k], plataforma_disp.get(k)))
            out.extend(grupos[k])
        if None in grupos:
            out.append("")
            out.append("**Sin dispositivo**")
            out.extend(grupos[None])
        return out

    def clave_area(aid):
        a = areas[aid]
        p = pisos.get(a.get("floor_id"))
        return ((p or {}).get("level") if p and p.get("level") is not None else 999,
                (p or {}).get("name", ""), a.get("name", "").lower())

    ahora = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    cfg = datos.get("config") or {}
    L = ["# Home Assistant — Inventario generado", "",
         "Generado: %s. Fuente: registros de entidades, dispositivos y áreas (app Inventario HA)." % ahora, ""]

    L += ["## Plataforma", "", "| Elemento | Detalle |", "|---|---|"]
    L.append("| Home Assistant | %s |" % (cfg.get("version") or datos.get("ha_version") or "?"))
    if sup.get("supervisor"):
        L.append("| Supervisor | %s |" % sup["supervisor"])
    if sup.get("operating_system") or sup.get("hassos"):
        L.append("| Sistema | %s |" % (sup.get("operating_system") or "HAOS " + str(sup.get("hassos"))))
    if sup.get("machine") or sup.get("arch"):
        L.append("| Máquina | %s |" % " · ".join(str(x) for x in (sup.get("machine"), sup.get("arch")) if x))
    if sup.get("hostname"):
        L.append("| Hostname | %s |" % sup["hostname"])
    if sup.get("kernel"):
        L.append("| Kernel | %s |" % sup["kernel"])
    if cfg.get("time_zone"):
        L.append("| Zona horaria | %s |" % cfg["time_zone"])

    filtros = []
    filtros.append("diagnóstico " + ("incluido" if diag else "excluido"))
    filtros.append("configuración " + ("incluida" if config else "excluida"))
    filtros.append("deshabilitadas/ocultas " + ("incluidas" if deshab else "excluidas"))
    if excluidos:
        filtros.append("dominios excluidos: " + ", ".join(sorted(excluidos)))
    L += ["", "Entidades listadas: %d de %d en el registro, más %d sin registro. Áreas: %d. Dispositivos: %d."
          % (listadas, len(registro), len(sin_registro), len(areas), len(disps)),
          "", "Filtros: " + "; ".join(filtros) + ".", ""]

    L += ["## Inventario por área"]
    for aid in sorted(areas, key=clave_area):
        a = areas[aid]
        p = pisos.get(a.get("floor_id"))
        L += ["", "### " + a.get("name", aid) + ((" (" + p["name"] + ")") if p and p.get("name") else "")]
        if aid in arbol:
            L += bloque(arbol[aid])
        else:
            L += ["", "Sin entidades."]
    # áreas borradas que siguen referenciadas
    for aid in sorted(k for k in arbol if k and k not in areas):
        L += ["", "### Área inexistente `%s`" % aid] + bloque(arbol[aid])

    L += ["", "### Sin área asignada"]
    L += bloque(arbol[None]) if None in arbol else ["", "Ninguna."]

    if sin_registro:
        L += ["", "### Sin registro (YAML sin unique_id)", ""] + sin_registro

    for dom, titulo in (("automation", "Automatizaciones"), ("script", "Scripts")):
        items = [s for eid, s in sorted(estados.items()) if eid.startswith(dom + ".")]
        if not items:
            continue
        L += ["", "## " + titulo, ""]
        for s in items:
            at = s.get("attributes", {})
            if dom == "automation":
                est = {"on": "activa", "off": "desactivada"}.get(s.get("state"), s.get("state"))
            else:
                est = {"off": "inactivo", "on": "en ejecución"}.get(s.get("state"), s.get("state"))
            L.append("- `%s` — %s — %s — último disparo: %s"
                     % (s["entity_id"], at.get("friendly_name") or s["entity_id"], est,
                        _fecha(at.get("last_triggered"))))

    md = "\n".join(L).rstrip() + "\n"
    resumen = "%d entidades · %d áreas · %d dispositivos · vía %s" % (
        listadas + len(sin_registro), len(areas), len(disps), datos.get("via", "?"))
    return md, resumen
