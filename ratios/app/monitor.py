"""Motor de monitoreo: paneles, ratios, niveles y alertas."""

import logging
import statistics
import threading
import time
from datetime import date, datetime, timedelta

import db
from iol import IOLError

log = logging.getLogger("monitor")

# Simbolos que en tenencias representan efectivo, no un titulo.
MONEDAS_TENENCIA = {"ARS", "$", "MEP", "D", "CABLE", "C", "USD"}

VENTANA_DIAS = 90
MIN_MUESTRA_Z = 20
MIN_MUESTRA_PROPIA = 15
BACKFILL_DIAS = 400


class Monitor:
    def __init__(self, cfg, iol, notif):
        self.cfg = cfg
        self.iol = iol
        self.notif = notif
        # Los pares viven en la base, no en la configuracion: se crean y
        # editan desde la app y sobreviven a una reinstalacion via el
        # respaldo. La lista de cfg solo sirvio para migrarlos.
        self._pares_cache = []
        self._pares_ts = None

        self.snapshot = {}
        self.plazos = {}
        self.lock = threading.Lock()
        self.ultimo_ciclo = None
        self.ultimo_error = None
        self.hay_rueda = None
        self.cotizaciones = {}      # simbolo -> dict, del ultimo ciclo
        self.origen = {}            # simbolo -> "panel" | "individual"

        self._zona_actual = self._cargar_zonas()
        self._zonas_curva = self._cargar_zonas_curva()
        self._pidiendo = threading.Lock()
        self._ultimo_manual = datetime.min
        self._opc_estado = None     # persistencia del cruce, por combinacion
        self._opc_desarme = set()   # posiciones ya avisadas
        self._rulo_avisado = set()   # circuitos ya avisados
        self.orleans_fallas = []
        self.orleans_descartados = []
        self.sin_cotizacion = []
        self._plazos_avisado = set()
        self._precio_avisado = set()
        self.plazos = []
        self.circuitos = {}         # ultimo resultado del Rulo
        self.snapshot_desde = None

    # -- estado persistente -------------------------------------------

    def _cargar_zonas(self):
        """La zona vive en la base: si no, cada reinicio repite las alertas."""
        import json
        try:
            return json.loads(db.get_estado("zonas") or "{}")
        except (ValueError, TypeError):
            return {}

    def _cargar_zonas_curva(self):
        import json
        try:
            return json.loads(db.get_estado("zonas_curva") or "{}")
        except (ValueError, TypeError):
            return {}

    def _guardar_zonas_curva(self):
        import json
        try:
            db.set_estado("zonas_curva", json.dumps(self._zonas_curva))
        except Exception as e:
            log.debug("zonas de curva: %s", e)

    def _guardar_zonas(self):
        import json
        try:
            db.set_estado("zonas", json.dumps(self._zona_actual))
        except Exception as e:
            log.debug("no se pudo guardar el estado de zonas: %s", e)

    # -- helpers ------------------------------------------------------

    def _factor(self, par, num, den):
        """Normaliza pares con láminas distintas.

        Si el par declara 'factor', manda ese. Si no, se deduce de los
        nominales por lámina que informa la API, cuando ambos los traen.
        """
        f = par.get("factor")
        if f:
            try:
                return float(f)
            except (TypeError, ValueError):
                return 1.0
        ln, ld = num.get("lote") or 0, den.get("lote") or 0
        if ln and ld and ln != ld:
            return ld / ln
        return 1.0

    def par_por_alias(self, alias):
        for p in self.pares:
            if p["alias"] == alias:
                return p
        return None

    def _en_horario(self):
        """Si hay rueda ahora mismo, por calendario.

        Incluye los feriados argentinos, que ya estaban cargados para el
        calculo del CER. Sin esto, un feriado se trataba como dia habil y
        se le seguia pidiendo datos a IOL toda la jornada.
        """
        try:
            ini = datetime.strptime(self.cfg["market_open"], "%H:%M").time()
            fin = datetime.strptime(self.cfg["market_close"], "%H:%M").time()
        except ValueError:
            return True
        ahora = datetime.now()
        try:
            import cer as CER
            if not CER.es_habil(ahora.date()):
                return False
        except Exception:
            if ahora.weekday() >= 5:
                return False
        return ini <= ahora.time() <= fin

    def segundos_desde_ciclo(self):
        if not self.ultimo_ciclo:
            return None
        return int((datetime.now() - self.ultimo_ciclo).total_seconds())

    # -- obtencion de precios ----------------------------------------

    @property
    def pares(self):
        """Se relee de la base cada pocos segundos: se editan en vivo."""
        ahora = datetime.now()
        if (self._pares_ts is None
                or (ahora - self._pares_ts).total_seconds() > 5):
            try:
                self._pares_cache = db.pares_guardados()
                self._pares_ts = ahora
            except Exception as e:
                log.debug("pares: %s", e)
        return self._pares_cache

    def simbolos_necesarios(self):
        """Todo lo que el ciclo tiene que traer.

        Incluye las especies con cronograma: antes las pedian las
        pestanias de Bonos y Rulo al abrirlas, asi que el mismo dato se
        bajaba una y otra vez. Pidiendolo una vez por ciclo, navegar no
        consume nada.
        """
        s = set()
        for p in self.pares:
            s.add(p["num"])
            s.add(p["den"])
        for t in self.cfg.get("arbitraje_tickers") or []:
            s.add((t.get("ticker") or "").upper())
        try:
            import bonos as BO
            s |= set(BO.especies())
        except Exception as e:
            log.debug("especies de bonos: %s", e)
        # los simbolos de las alertas de precio: sin cotizacion no hay
        # forma de evaluarlas
        try:
            for a in db.alertas_precio(solo_activas=True):
                for c in a.get("condiciones") or []:
                    s.add(c["simbolo"])
        except Exception as e:
            log.debug("simbolos de alertas: %s", e)
        s.discard("")
        return s

    def bajar_paneles(self):
        """Un request por panel de los viejos.

        Ya no se usa en el ciclo: orleans cubre mas y trae puntas. Queda
        por si hace falta comparar una fuente con la otra.
        """
        from iol import normalizar
        mapa = {}
        planos = 0
        total = 0

        for pan in self.cfg.get("paneles") or []:
            inst = pan.get("instrumento") or "Bonos"
            nombre = pan.get("panel") or ""
            pais = pan.get("pais") or "argentina"
            if not nombre:
                continue
            try:
                d = self.iol.cotizacion_panel(inst, nombre, pais)
            except IOLError as e:
                log.warning("panel %s/%s: %s", inst, nombre, e)
                continue

            for t in (d or {}).get("titulos") or []:
                sim = (t.get("simbolo") or "").upper()
                if not sim:
                    continue
                c = normalizar(t, sim)
                if not c["ref"]:
                    continue
                mapa[sim] = c
                self.origen[sim] = "panel"
                total += 1
                if not c["variacion"] and not c.get("volumen"):
                    planos += 1

        # deteccion de dia sin rueda: nada se movio en todo el panel
        if total >= 10:
            self.hay_rueda = planos < total
        return mapa

    def cotizaciones_del_ciclo(self):
        """Un request por instrumento, y nada mas.

        Antes eran cinco paneles mas un pedido suelto por cada especie
        que no estuviera en ninguno. Orleans cubre mas y trae puntas, asi
        que lo que falte es porque no cotiza: se avisa en pantalla en vez
        de pedirlo de a uno sin que se note.
        """
        mapa = self.bajar_orleans()
        for sim in mapa:
            self.origen[sim] = "orleans"
        self.sin_cotizacion = sorted(self.simbolos_necesarios() - set(mapa))
        if self.sin_cotizacion:
            log.info("sin cotizacion: %s", ", ".join(self.sin_cotizacion))
        return self.rellenar_puntas(mapa)

    # -- panel orleans ------------------------------------------------

    # Un instrumento por request, con puntas. Reemplaza a los paneles
    # viejos y a los pedidos sueltos.
    INSTRUMENTOS = ("titulosPublicos", "letras", "acciones", "cedears",
                    "opciones", "cauciones")

    def instrumentos_orleans(self):
        txt = self.cfg.get("instrumentos_orleans")
        if txt is None:
            return list(self.INSTRUMENTOS)
        return [i.strip() for i in str(txt).split(",") if i.strip()]

    def _vencido(self, fecha_txt, dias_habiles):
        """True si la ultima operacion es demasiado vieja.

        La API deja pasar especies muertas aunque se le pida Operables:
        una letra vencida en abril seguia apareciendo. Se descartan por
        fecha de ultima operacion, que es lo unico confiable.
        """
        if not dias_habiles:
            return False
        try:
            f = date.fromisoformat(str(fecha_txt)[:10])
        except Exception:
            return True         # sin fecha no se puede confiar
        import cer as CER
        habiles, d = 0, date.today()
        while d > f and habiles <= dias_habiles:
            d -= timedelta(days=1)
            if CER.es_habil(d):
                habiles += 1
        return habiles > dias_habiles

    def bajar_orleans(self):
        """Todos los instrumentos configurados. Devuelve simbolo -> cotizacion."""
        from iol import normalizar
        mapa, planos, total, fallas = {}, 0, 0, []
        dias = self.cfg.get("dias_sin_operar")
        dias = 7 if dias is None else int(dias)
        descartados = []

        for inst in self.instrumentos_orleans():
            try:
                d = self.iol.panel_orleans(inst)
            except IOLError as e:
                log.warning("panel orleans %s: %s", inst, e)
                fallas.append(inst)
                continue
            for t in (d or {}).get("titulos") or []:
                sim = str((t or {}).get("simbolo") or "").strip().upper()
                if not sim:
                    continue
                if self._vencido(t.get("fecha"), dias):
                    descartados.append(sim)
                    continue
                c = normalizar(t, sim)
                c["instrumento"] = inst
                c["descripcion"] = t.get("descripcion") or ""
                c["plazo_panel"] = t.get("plazo")
                c["lote"] = t.get("lote")
                total += 1
                if not (c.get("compra") or c.get("venta")):
                    planos += 1
                mapa[sim] = c
        if total:
            self.hay_rueda = planos < total
        self.orleans_fallas = fallas
        self.orleans_descartados = sorted(set(descartados))
        return mapa

    def tasa_caucion(self, mapa=None):
        """Tasa colocadora del dia, de la punta compradora.

        Reemplaza al numero fijo de la configuracion cuando hay dato en
        vivo; si no lo hay, se usa el configurado.
        """
        mapa = mapa if mapa is not None else self.cotizaciones
        for sim, c in mapa.items():
            if c.get("instrumento") != "cauciones":
                continue
            # la de pesos: el simbolo es descriptivo, no un ticker
            texto = ("%s %s" % (sim, c.get("descripcion") or "")).lower()
            if "peso" in texto and c.get("compra"):
                return float(c["compra"]), "mercado"
        return float(self.cfg.get("tasa_caucion_anual") or 0), "configurada"


    # -- ultima punta conocida ----------------------------------------

    CLAVE_PUNTAS = "ultimas_puntas"

    def _cargar_puntas(self):
        import json
        try:
            return json.loads(db.get_estado(self.CLAVE_PUNTAS) or "{}")
        except Exception:
            return {}

    def rellenar_puntas(self, mapa):
        """Conserva la ultima punta valida de cada simbolo.

        Fuera de rueda IOL manda el ultimo precio pero no las puntas, y
        sin puntas no se puede valuar nada. Se guarda la ultima buena por
        simbolo, no por ciclo: las especies iliquidas pierden punta
        mucho antes del cierre, asi que un unico snapshot del ultimo
        ciclo "bueno" dejaria a las liquidas al dia y a las demas con
        datos de horas antes sin que se note.

        Lo que se rellena queda marcado como viejo. Ningun modulo debe
        alertar sobre esto.
        """
        import json
        guardadas = self._cargar_puntas()
        ahora = datetime.now().isoformat(timespec="seconds")
        cambio = False

        for sim, c in mapa.items():
            guardado = guardadas.get(sim) or {}
            if c.get("compra") and c.get("venta"):
                guardadas[sim] = {
                    "compra": c["compra"], "venta": c["venta"],
                    "vol_compra": c.get("vol_compra") or 0,
                    "vol_venta": c.get("vol_venta") or 0,
                    "ultimo": c.get("ultimo") or guardado.get("ultimo") or 0,
                    "moneda": c.get("moneda") or guardado.get("moneda") or "",
                    "ts": ahora}
                c["punta_vieja"] = False
                c["punta_ts"] = ahora
                cambio = True
                continue

            # Sin puntas igual se guarda el ultimo operado: hay especies
            # que cierran sin punta y solo con ultimo, y si no se guardan
            # desaparecen de la tabla en vez de mostrarse atenuadas.
            if c.get("ultimo"):
                g = dict(guardado)
                g.update({"ultimo": c["ultimo"], "ts_ultimo": ahora,
                          "moneda": c.get("moneda") or g.get("moneda") or ""})
                guardadas[sim] = g
                cambio = True

            if not guardado.get("compra"):
                c["punta_vieja"] = False    # nunca hubo, no hay que marcar
                continue
            c["compra"] = guardado["compra"]
            c["venta"] = guardado["venta"]
            c["vol_compra"] = guardado.get("vol_compra") or 0
            c["vol_venta"] = guardado.get("vol_venta") or 0
            c["medio"] = (c["compra"] + c["venta"]) / 2
            c["ref"] = c["medio"] or c.get("ultimo") or 0
            c["punta_vieja"] = True
            c["punta_ts"] = guardado.get("ts")

        if cambio:
            db.set_estado(self.CLAVE_PUNTAS, json.dumps(guardadas))
        return mapa

    def mapa_guardado(self):
        """Cotizaciones armadas con la ultima punta conocida de cada
        simbolo. Sirve para responder con la rueda cerrada sin tocar la
        API: los datos ya los tenemos, pedirlos de nuevo no cambia nada
        y consume cupo."""
        out = {}
        for sim, v in self._cargar_puntas().items():
            compra = v.get("compra") or 0
            venta = v.get("venta") or 0
            ultimo = v.get("ultimo") or 0
            medio = (compra + venta) / 2 if compra and venta else 0
            if not (medio or ultimo):
                continue
            out[sim] = {"simbolo": sim, "compra": compra, "venta": venta,
                        "vol_compra": v.get("vol_compra") or 0,
                        "vol_venta": v.get("vol_venta") or 0,
                        "medio": medio, "ref": medio or ultimo,
                        "ultimo": ultimo or medio,
                        "moneda": v.get("moneda") or "",
                        "punta_vieja": bool(medio),
                        "punta_ts": v.get("ts")}
        return out

    def cotizaciones_vigentes(self):
        """Lo que hay que mostrar ahora: en rueda, lo del ciclo; fuera,
        lo ultimo guardado. Nunca dispara un request."""
        with self.lock:
            mapa = dict(self.cotizaciones)
        if mapa:
            return mapa
        return self.mapa_guardado()


    def puntas_frescas(self, mapa=None):
        """True si al menos un simbolo trajo punta propia este ciclo."""
        mapa = mapa if mapa is not None else self.cotizaciones
        return any(not c.get("punta_vieja")
                   and c.get("compra") and c.get("venta")
                   for c in mapa.values())


    # -- estadistica --------------------------------------------------

    def estadistica(self, par):
        """Prefiere nuestras propias lecturas; el historico de IOL es respaldo."""
        desde = (datetime.now().date() - timedelta(days=VENTANA_DIAS)).isoformat()
        propia = db.serie_propia_diaria(par["alias"], desde)
        if len(propia) >= MIN_MUESTRA_PROPIA:
            return _stats([v for _, v in propia], "propia")

        serie = db.serie_ratio_diaria(par["num"], par["den"], desde)
        st = _stats([v for _, v in serie], "iol")
        st["aviso"] = ("El histórico viene de IOL y puede mezclar plazos. "
                       "Se reemplaza solo cuando junte %d días propios."
                       % MIN_MUESTRA_PROPIA)
        return st

    # -- zonas y alertas ---------------------------------------------

    def _zona(self, par, ratio, est):
        """Zona con histeresis: salir cuesta mas que entrar."""
        res = par.get("resistencia") or 0
        sop = par.get("soporte") or 0
        margen = float(self.cfg.get("histeresis_pct", 0.5)) / 100.0
        actual = self._zona_actual.get(par["alias"], "normal")

        if res > 0 or sop > 0:
            if actual == "alta":
                # sigue en alta hasta que baje del nivel menos el margen
                if res and ratio >= res * (1 - margen):
                    return "alta", res
            elif actual == "baja":
                if sop and ratio <= sop * (1 + margen):
                    return "baja", sop
            if res > 0 and ratio >= res:
                return "alta", res
            if sop > 0 and ratio <= sop:
                return "baja", sop
            return "normal", None

        # sin niveles: z-score
        if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
            z = (ratio - est["media"]) / est["desvio"]
            umbral = 2.0 if actual == "normal" else 1.6
            if z >= umbral:
                return "alta", est["media"] + 2 * est["desvio"]
            if z <= -umbral:
                return "baja", est["media"] - 2 * est["desvio"]
        return "normal", None

    def _mensaje(self, par, ratio, zona, nivel, est, num, den):
        icono = "🔴" if zona == "alta" else "🟢"
        que = "tocó resistencia" if zona == "alta" else "tocó soporte"
        L = [
            "%s <b>%s</b> %s" % (icono, par["alias"], que),
            "Ratio <b>%.4f</b>  (nivel %.4f)" % (ratio, nivel or 0),
            "",
        ]
        for etq, sim, c in (("", par["num"], num), ("", par["den"], den)):
            linea = "%s: %s" % (sim, _n(c["ref"]))
            if c["compra"] or c["venta"]:
                linea += "   %s / %s" % (_n(c["compra"]), _n(c["venta"]))
            if c.get("vol_compra") or c.get("vol_venta"):
                linea += "   [%s / %s]" % (
                    _e(c.get("vol_compra")), _e(c.get("vol_venta")))
            L.append(linea)

        if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
            z = (ratio - est["media"]) / est["desvio"]
            L += ["",
                  "Media: %.4f   z: %+.2f" % (est["media"], z),
                  "Rango: %.4f – %.4f  (n=%d, %s)" % (
                      est["min"], est["max"], est["n"], est.get("fuente", ""))]
        ten = self._tenencia_del_par(par, ratio)
        if ten:
            L += [""] + ten
        L += ["", "<i>%s</i>" % datetime.now().strftime("%H:%M:%S")]
        return "\n".join(L)

    def _tenencia_del_par(self, par, ratio):
        """Si el par pertenece a un grupo, cuanto tenes y cuanto obtendrias."""
        try:
            import posicion as P
            for g in db.listar_grupos():
                tks = set(g["tickers"])
                if par["num"] not in tks or par["den"] not in tks:
                    continue
                saldos = P.tenencia(g["id"])
                lineas = []
                cn = saldos.get(par["num"], 0)
                cd = saldos.get(par["den"], 0)
                if cn > 0:
                    lineas.append("Tenés %s %s → %s %s si rotás"
                                  % (_e(cn), par["num"],
                                     _e(cn * ratio), par["den"]))
                if cd > 0:
                    lineas.append("Tenés %s %s → %s %s si rotás"
                                  % (_e(cd), par["den"],
                                     _e(cd / ratio if ratio else 0), par["num"]))
                return lineas
        except Exception as e:
            log.debug("tenencia en alerta: %s", e)
        return []

    # -- evaluacion ---------------------------------------------------

    def evaluar_par(self, par, mapa):
        num = mapa.get(par["num"])
        den = mapa.get(par["den"])
        if not num or not den or not num["ref"] or not den["ref"]:
            raise IOLError("sin precio para %s o %s" % (par["num"], par["den"]))

        ratio = num["ref"] / den["ref"] * self._factor(par, num, den)
        est = self.estadistica(par)
        previa = self._zona_actual.get(par["alias"], "normal")
        zona, nivel = self._zona(par, ratio, est)
        if zona != previa:
            self._zona_actual[par["alias"]] = zona
            self._guardar_zonas()

        db.guardar_lectura(par["alias"], ratio, num, den)

        z = None
        if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
            z = (ratio - est["media"]) / est["desvio"]

        alerta_id = None
        # con punta repuesta de antes del cierre el ratio no es ejecutable
        viejas = any((mapa.get(par[lado]) or {}).get("punta_vieja")
                     for lado in ("num", "den"))
        # avisa solo al ENTRAR en zona, no mientras se queda
        if par.get("alertas") and zona != "normal" and previa != zona \
                and not viejas:
            msg = self._mensaje(par, ratio, zona, nivel, est, num, den)
            alerta_id = db.registrar_alerta(
                par["alias"], zona, ratio, nivel, msg, num, den)
            self.notif.enviar(
                "%s %s" % (par["alias"], "▲" if zona == "alta" else "▼"),
                msg, urgente=True)
            log.info("alerta %s %s @ %.4f", par["alias"], zona, ratio)

        estado = {
            "alias": par["alias"], "num": par["num"], "den": par["den"],
            "cerca": _cerca_del_borde(par, ratio, est),
            "factor": self._factor(par, num, den),
            "ratio": ratio, "zona": zona, "zona_previa": previa,
            "resistencia": par.get("resistencia") or 0,
            "soporte": par.get("soporte") or 0,
            "z": z, "est": est, "p_num": num, "p_den": den,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "alertas": bool(par.get("alertas")),
            "alerta_id": alerta_id,
            "origen": self.origen.get(par["num"], "?"),
            "error": None,
        }

        if self.cfg.get("publicar_sensores"):
            self.notif.publicar_sensor(par["alias"], ratio, {
                "friendly_name": "Ratio " + par["alias"],
                "zona": zona,
                "resistencia": par.get("resistencia") or 0,
                "soporte": par.get("soporte") or 0,
                "z_score": round(z, 3) if z is not None else None,
                "numerador": par["num"], "denominador": par["den"],
                "precio_numerador": num["ref"], "precio_denominador": den["ref"],
                "unit_of_measurement": "ratio",
                "icon": "mdi:swap-horizontal",
            })
        return estado

    # -- desvíos de curva ---------------------------------------------

    def revisar_curva(self, cot=None):
        """Avisa cuando un bono se despega de su curva más de lo habitual.

        El umbral por defecto sale del backtest: 2,5 desvíos sobre
        especies líquidas dio 77% de acierto a 42 días. Por debajo de 2
        los costos se comen la ganancia, así que no vale avisar.
        """
        import bonos as BO
        import curva as CU

        umbral = float(self.cfg.get("curva_umbral_z") or 2.5)
        if not umbral:
            return 0

        with self.lock:
            cot = cot or dict(self.cotizaciones)
        if not cot:
            return 0

        cer_act = float(self.cfg.get("cer_actual") or 0)
        t = BO.tabla(cot, cer_actual=cer_act)
        an = CU.analizar(t["filas"])
        por_sim = {f["simbolo"]: f for f in t["filas"]}

        avisadas = self._zonas_curva
        enviadas = 0

        for sim, d in an.items():
            z = d.get("z")
            if z is None:
                continue
            zona = "barato" if z >= umbral else "caro" if z <= -umbral else None
            previa = avisadas.get(sim)
            if zona != previa:
                avisadas[sim] = zona
                self._guardar_zonas_curva()
            if not zona or zona == previa:
                continue

            f = por_sim.get(sim) or {}
            # sin punta ejecutable la señal no sirve
            if zona == "barato" and not f.get("ask"):
                continue
            if (cot.get(sim) or {}).get("punta_vieja"):
                continue    # punta de antes del cierre: no es operable

            icono = "🟢" if zona == "barato" else "🔴"
            que = "barato" if zona == "barato" else "caro"
            L = ["%s <b>%s</b> %s contra su curva" % (icono, sim, que),
                 "Desvío %+.0f pb  ·  z %+.2f" % (d["residuo"], z),
                 ""]
            if f.get("tir_last") is not None:
                L.append("TIR %.2f%%  ·  curva %.2f%%" % (
                    f["tir_last"], d["curva"]))
            if f.get("ask"):
                L.append("Ask %s  ·  TIR ask %.2f%%" % (
                    _n(f["ask"]), f.get("tir_ask") or 0))
            if d.get("vecino"):
                v = por_sim.get(d["vecino"]) or {}
                L += ["", "Vecino de duration parecida: %s (TIR %.2f%%)" % (
                    d["vecino"], v.get("tir_last") or 0)]
            L += ["", "<i>%s · %d bonos en la familia</i>" % (
                datetime.now().strftime("%H:%M"), d["n_familia"])]

            msg = "\n".join(L)
            self.notif.enviar("%s %s contra su curva" % (sim, que), msg,
                              urgente=(zona == "barato"))
            db.registrar_alerta(sim, "curva_" + zona, d["residuo"], umbral, msg)
            log.info("curva: %s %s z=%+.2f", sim, zona, z)
            enviadas += 1

        return enviadas

    # -- arbitraje de plazos t0 / t1 ---------------------------------

    def comision(self, tipo):
        tabla = self.cfg.get("comisiones") or {}
        try:
            return float(tabla.get(tipo, tabla.get("acciones", 0.15))) / 100.0
        except (TypeError, ValueError):
            return 0.0015

    def dias_liquidacion(self, hoy=None):
        """Dias corridos entre la liquidacion de t0 y la de t1.

        Un viernes son tres: t0 liquida el viernes y t1 el lunes. Tomar
        siempre uno triplicaba la TNA implicita de los viernes.
        """
        import cer as CER
        d = hoy or date.today()
        prox = d + timedelta(days=1)
        while not CER.es_habil(prox):
            prox += timedelta(days=1)
        return max(1, (prox - d).days)

    def evaluar_arbitraje(self, cot=None):
        """Vender en t0 y recomprar en t1.

        Se cobra hoy y se paga manana, asi que la diferencia de precios es
        una tasa implicita. Conviene cuando esa TNA, neta de comisiones,
        le gana a la caucion colocadora.

        El t1 sale del panel del ciclo cuando esta: los paneles cotizan a
        t1, asi que solo hace falta pedir el t0 de cada simbolo. Antes se
        pedian los dos y era el doble de requests.
        """
        filas = []
        cot = cot if cot is not None else dict(self.cotizaciones)
        tasa_anual, origen_tasa = self.tasa_caucion(cot)
        dias = self.dias_liquidacion()
        tasa_dia = tasa_anual / 365.0 / 100.0 * dias
        com_caucion = self.comision("cauciones")

        for t in self.cfg.get("arbitraje_tickers") or []:
            sim = (t.get("ticker") or "").upper()
            if not sim:
                continue
            mercado = t.get("mercado") or "bCBA"
            tipo = t.get("tipo") or "bonos"
            fila = {"ticker": sim, "tipo": tipo, "dias": dias,
                    "tasa_origen": origen_tasa, "tasa_anual": tasa_anual}
            try:
                c0 = self.iol.cotizacion(mercado, sim, "t0")
                c1 = cot.get(sim)
                if not c1 or not c1.get("venta"):
                    c1 = self.iol.cotizacion(mercado, sim, "t1")
                elif c1.get("punta_vieja"):
                    fila["punta_vieja"] = True
            except IOLError as e:
                fila["error"] = str(e)
                filas.append(fila)
                continue

            fila.update({
                "compra_t0": c0["compra"], "venta_t0": c0["venta"],
                "q_compra_t0": c0.get("vol_compra"),
                "compra_t1": c1["compra"], "venta_t1": c1["venta"],
                "q_venta_t1": c1.get("vol_venta"),
            })

            if not c0["compra"] or not c1["venta"]:
                fila["error"] = "faltan puntas"
                filas.append(fila)
                continue

            bruto = (c0["compra"] - c1["venta"]) / c1["venta"]
            costo = self.comision(tipo) * 2
            neto = bruto - costo
            referencia = tasa_dia - com_caucion / 365.0 * dias

            fila.update({
                "bruto_pct": bruto * 100,
                "costo_pct": costo * 100,
                "neto_pct": neto * 100,
                "tna_pct": neto * 365.0 / dias * 100,
                "tna_caucion_pct": referencia * 365.0 / dias * 100,
                "caucion_dia_pct": referencia * 100,
                "conviene": bool(c0["compra"] > c1["venta"] and neto > referencia),
                "ejecutable": min(c0.get("vol_compra") or 0,
                                  c1.get("vol_venta") or 0),
            })
            filas.append(fila)

        filas.sort(key=lambda f: f.get("neto_pct") or -999, reverse=True)
        return filas

    # -- ciclo --------------------------------------------------------

    def ciclo(self, manual=False):
        if not self._pidiendo.acquire(blocking=False):
            return False
        try:
            mapa = self.cotizaciones_del_ciclo()
            with self.lock:
                self.cotizaciones = mapa
            for par in self.pares:
                try:
                    estado = self.evaluar_par(par, mapa)
                    with self.lock:
                        self.snapshot[par["alias"]] = estado
                except Exception as e:
                    log.warning("%s: %s", par["alias"], e)
                    with self.lock:
                        prev = self.snapshot.get(par["alias"]) or {
                            "alias": par["alias"], "num": par["num"],
                            "den": par["den"]}
                        prev["error"] = str(e)
                        self.snapshot[par["alias"]] = prev
            try:
                self.revisar_curva(mapa)
            except Exception as e:
                log.debug("revisar curva: %s", e)
            try:
                self.revisar_opciones(mapa)
            except Exception as e:
                log.debug("revisar opciones: %s", e)
            try:
                self.revisar_rulo(mapa)
            except Exception as e:
                log.debug("revisar rulo: %s", e)
            try:
                self.revisar_plazos(mapa)
            except Exception as e:
                log.debug("revisar plazos: %s", e)
            try:
                self.revisar_alertas_precio(mapa)
            except Exception as e:
                log.debug("revisar alertas de precio: %s", e)
            try:
                self._guardar_snapshot()
            except Exception as e:
                log.debug("guardar snapshot: %s", e)
            self.ultimo_ciclo = datetime.now()
            if manual:
                self._ultimo_manual = datetime.now()
            return True
        finally:
            self._pidiendo.release()

    def ciclo_manual(self):
        """Refresco a pedido, con un minimo entre disparos."""
        minimo = int(self.cfg.get("min_segundos_manual", 20))
        falta = minimo - (datetime.now() - self._ultimo_manual).total_seconds()
        if falta > 0:
            return False, int(falta) + 1
        ok = self.ciclo(manual=True)
        return ok, 0

    # -- opciones -----------------------------------------------------

    def parametros_opciones(self):
        c = self.cfg
        return {
            "dias_min": c.get("opc_dias_min", 15),
            "dias_max": c.get("opc_dias_max", 80),
            "saltos": c.get("opc_saltos", 3),
            "limite_base_pct": c.get("opc_limite_base_pct", 5),
            "riesgo_max_tabla_pct": c.get("opc_riesgo_tabla_pct", 45),
            "riesgo_max_alarma_pct": c.get("opc_riesgo_alarma_pct", 33),
            "bear_instrumento": c.get("opc_bear_instrumento", "ambos"),
            "lotes_min": c.get("opc_lotes_min", 2),
            "ciclos_persistencia": c.get("opc_ciclos_persistencia", 1),
            "ganancia_min_pct": c.get("opc_ganancia_min_pct", 100),
            "dias_min_desarme": c.get("opc_dias_min_desarme", 10),
            "mov_contrario_pct": c.get("opc_mov_contrario_pct", 4),
        }

    def cadena_opciones(self, cot=None):
        """Cadena con puntas. Fuera de rueda IOL no manda ninguna, asi que
        se guarda la ultima buena y se devuelve marcada."""
        import json
        import opciones as OP
        subs = [s.strip().upper()
                for s in (self.cfg.get("opc_subyacentes") or "GGAL").split(",")
                if s.strip()]

        # Fuera de rueda no se baja la cadena: son dos requests que
        # devuelven series sin puntas, y ya tenemos la ultima buena.
        if not self._en_horario():
            guardado = db.get_estado("opc_ultima_cadena")
            if guardado:
                d = json.loads(guardado)
                series = d.get("series") or []
                hoy = date.today()
                for x in series:
                    try:
                        x["dias"] = (date.fromisoformat(x["vencimiento"])
                                     - hoy).days
                    except Exception:
                        pass
                diag = {"en_panel": 0, "mapeadas": 0,
                        "parseadas": len(series), "con_puntas": 0,
                        "vencimientos": sorted({x["vencimiento"]
                                                for x in series}),
                        "campos": [], "sin_pedir": True}
                return series, d.get("spots") or {}, diag, True, d.get("ts")
            return [], {}, {"en_panel": 0, "mapeadas": 0, "parseadas": 0,
                            "con_puntas": 0, "vencimientos": [],
                            "campos": [], "sin_pedir": True}, False, None

        series, diag = OP.cadena(
            self.iol, subs, panel=self.cfg.get("opc_panel") or "De Acciones")

        cot = cot if cot is not None else dict(self.cotizaciones)
        spots = {}
        for s in subs:
            c = cot.get(s) or {}
            spots[s] = c.get("ref") or c.get("ultimo") or 0

        viejo, desde = False, None
        if diag["con_puntas"] > 0 and any(spots.values()):
            db.set_estado("opc_ultima_cadena", json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "series": series, "spots": spots}))
        else:
            guardado = db.get_estado("opc_ultima_cadena")
            if guardado:
                d = json.loads(guardado)
                series = d.get("series") or []
                spots = {k: v for k, v in (d.get("spots") or spots).items()}
                desde, viejo = d.get("ts"), True
                hoy = date.today()
                for s in series:
                    try:
                        s["dias"] = (date.fromisoformat(s["vencimiento"])
                                     - hoy).days
                    except Exception:
                        pass
        return series, spots, diag, viejo, desde

    def revisar_opciones(self, cot=None):
        """Alertas de armado y de desarme, y el cierre diario."""
        import opciones as OP
        if not (self.cfg.get("opc_subyacentes") or "GGAL").strip():
            return 0

        series, spots, diag, viejo, _ = self.cadena_opciones(cot)
        if viejo or not series:
            return 0        # con puntas de ayer no se avisa nada

        par = self.parametros_opciones()
        r = OP.analizar(series, spots, par, self.cfg.get("comisiones") or {},
                        None, self.cfg.get("derechos_mercado") or {},
                        self.cfg.get("iva_pct") or 0)
        filas = r["filas"]
        marcas = db.opc_marcas()

        # armado: solo el cruce hacia adentro del umbral
        candidatas = [f for f in filas
                      if not (marcas.get(f["id"]) or {}).get("silenciada")]
        avisos, self._opc_estado = OP.cruces(
            candidatas, getattr(self, "_opc_estado", None), par)
        if avisos:
            self._avisar_opciones(avisos)

        # desarme
        salidas = []
        for pos in db.opc_posiciones(abiertas=True):
            val = OP.valuar(pos, series)
            motivos = OP.motivos_desarme(pos, val, spots.get(pos["subyacente"]),
                                         par)
            if not motivos:
                self._opc_desarme.discard(pos["id"])
                continue
            if pos["id"] in self._opc_desarme:
                continue
            if val and val["lotes_salida"] < int(par.get("lotes_min") or 2):
                continue    # avisar sin punta para salir no sirve de nada
            self._opc_desarme.add(pos["id"])
            salidas.append((pos, val, motivos))
        if salidas:
            self._avisar_desarme(salidas)

        # cierre diario por combinacion
        hoy = date.today().isoformat()
        db.opc_guardar_cierres([
            (f["id"], hoy, f["riesgo_pct"], f["riesgo"], f["lotes"],
             f["spot"]) for f in filas])
        return len(avisos)

    NOMBRE_ESTRUCTURA = {"BULL_CALL": "Bull con calls",
                         "BEAR_PUT": "Bear con puts",
                         "BEAR_CALL": "Bear con calls"}

    def _avisar_opciones(self, avisos):
        """Un solo aviso por ciclo con todo lo que cruzo el umbral.

        Con tres vencimientos y treinta bases, un mismo movimiento del
        papel puede meter decenas de combinaciones adentro del umbral a la
        vez. Mandar una notificacion por cada una es inservible: llegan
        todas juntas y no se lee ninguna.
        """
        avisos = sorted(avisos, key=lambda f: f["riesgo_pct"])
        n = len(avisos)
        mejor = avisos[0]

        if n == 1:
            titulo = "%s %s %s/%s al %.1f%%" % (
                mejor["subyacente"],
                self.NOMBRE_ESTRUCTURA.get(mejor["estructura"],
                                           mejor["estructura"]),
                _n(mejor["base_compra"]), _n(mejor["base_venta"]),
                mejor["riesgo_pct"])
        else:
            subs = sorted({f["subyacente"] for f in avisos})
            titulo = "%d spreads en %s, el mejor al %.1f%%" % (
                n, ", ".join(subs), mejor["riesgo_pct"])

        TOPE = 8
        lineas = []
        for f in avisos[:TOPE]:
            favor = (" a favor" if f.get("a_favor") is True
                     else " en contra" if f.get("a_favor") is False else "")
            lineas.append(
                "<b>%.1f%%</b> · %s %s/%s · 1 a %.2f · %d dias · %d lotes%s"
                % (f["riesgo_pct"],
                   self.NOMBRE_ESTRUCTURA.get(f["estructura"],
                                              f["estructura"]),
                   _n(f["base_compra"]), _n(f["base_venta"]), f["ratio"],
                   f["dias"], f["lotes"], favor))
        if n > TOPE:
            lineas.append("y %d mas en la pestana." % (n - TOPE))
        lineas.append("Equilibrio del mejor en %s (%+.1f%%)."
                      % (_n(mejor["equilibrio"]), mejor["var_equilibrio_pct"]))

        self.notif.enviar(titulo, "<br>".join(lineas))
        for f in avisos:
            db.registrar_alerta(f["id"], "opcion_armado", f["riesgo_pct"],
                                f["ratio"], titulo)

    def _avisar_desarme(self, salidas):
        """Tambien en un solo aviso, por la misma razon que el armado."""
        if len(salidas) == 1:
            pos = salidas[0][0]
            titulo = "Desarmar %s %s/%s" % (
                pos["subyacente"], _n(pos["base_compra"]),
                _n(pos["base_venta"]))
        else:
            titulo = "%d posiciones para desarmar" % len(salidas)

        lineas = []
        for pos, val, motivos in salidas:
            plata = ("vale %s por lote, %s en total"
                     % (_n(val["salida"]), _n(val["ganancia_total"]))
                     if val else "sin puntas para valuar")
            lineas.append("<b>%s %s/%s</b> · %s · %s" % (
                pos["subyacente"], _n(pos["base_compra"]),
                _n(pos["base_venta"]), "; ".join(motivos), plata))
        self.notif.enviar(titulo, "<br>".join(lineas))
        for pos, val, _m in salidas:
            db.registrar_alerta(pos["combo"], "opcion_desarme",
                                (val or {}).get("ganancia_pct"), None, titulo)


    def brokers_extranjeros(self):
        return {b.strip().upper()
                for b in (self.cfg.get("brokers_extranjeros") or "").split(",")
                if b.strip()}

    def tengo_actual(self):
        """Que hay para armar circuitos.

        Los bonos salen de las tenencias, y solo las de brokers locales:
        un titulo en una cuenta del exterior no liquida contra el mercado
        local, asi que no puede ser una pata del rulo. Las monedas salen
        de la configuracion, que es donde se elige en cuales se opera.
        """
        fuera = self.brokers_extranjeros()
        monedas = [m.strip().upper()
                   for m in (self.cfg.get("monedas_rulo") or "ARS,MEP").split(",")
                   if m.strip()]
        try:
            import bonos as BO
            con_cronograma = set(BO.cargar()[0])
        except Exception:
            con_cronograma = set()

        # Solo bonos con cronograma cargado: una accion o un CEDEAR no
        # tiene especie D ni C, asi que no puede cruzar de moneda y solo
        # ensuciaria el universo de circuitos.
        bonos = sorted({t["simbolo"] for t in db.tenencias()
                        if t["broker"].upper() not in fuera
                        and t["cantidad"]
                        and t["simbolo"] not in MONEDAS_TENENCIA
                        and (t.get("tipo") or "") in ("bonos", "letras", "")
                        and (not con_cronograma
                             or t["simbolo"] in con_cronograma)})
        return {"monedas": monedas, "bonos": bonos}


    # -- alertas de precio --------------------------------------------

    def evaluar_alerta(self, alerta, cot):
        """Estado de una alerta y de cada una de sus condiciones.

        Comprar mira la punta vendedora y vender la compradora: es contra
        la que se ejecuta. Con puntas repuestas de antes del cierre no se
        da por cumplida ninguna.
        """
        detalle, cumplen, hay_vieja, falta = [], 0, False, False
        for cond in alerta.get("condiciones") or []:
            c = cot.get(cond["simbolo"]) or {}
            if c.get("punta_vieja"):
                hay_vieja = True
            if cond["operacion"] == "comprar":
                actual = c.get("venta") or 0        # pago el ask
                ok = bool(actual) and actual <= cond["precio"]
            else:
                actual = c.get("compra") or 0       # cobro el bid
                ok = bool(actual) and actual >= cond["precio"]
            if not actual:
                falta = True
            cumplen += 1 if ok else 0
            detalle.append({"simbolo": cond["simbolo"],
                            "operacion": cond["operacion"],
                            "precio": cond["precio"], "actual": actual,
                            "cumple": ok})
        total = len(detalle)
        if not total:
            return {"cumple": False, "detalle": detalle}
        cumple = cumplen == total if alerta["modo"] == "todas" else cumplen > 0
        return {"cumple": cumple and not hay_vieja and not falta,
                "cumplen": cumplen, "total": total,
                "punta_vieja": hay_vieja, "sin_precio": falta,
                "detalle": detalle}

    def revisar_alertas_precio(self, cot=None):
        """Avisa cuando una alerta pasa a cumplirse, no mientras se
        mantiene: vuelve a armarse cuando deja de cumplirse."""
        cot = cot if cot is not None else dict(self.cotizaciones)
        if not cot:
            return 0
        avisos = []
        for a in db.alertas_precio(solo_activas=True):
            r = self.evaluar_alerta(a, cot)
            if not r["cumple"]:
                self._precio_avisado.discard(a["id"])
                continue
            if a["id"] in self._precio_avisado:
                continue
            self._precio_avisado.add(a["id"])
            avisos.append((a, r))
        if avisos:
            self._avisar_precio(avisos)
        return len(avisos)

    def _avisar_precio(self, avisos):
        if len(avisos) == 1:
            titulo = avisos[0][0]["titulo"]
        else:
            titulo = "%d alertas de precio" % len(avisos)
        lineas = []
        for a, r in avisos:
            partes = ["%s %s a %s (esta %s)" % (
                d["operacion"], d["simbolo"], _n(d["precio"]), _n(d["actual"]))
                for d in r["detalle"]]
            union = " y " if a["modo"] == "todas" else " o "
            lineas.append("<b>%s</b>: %s" % (a["titulo"], union.join(partes)))
        self.notif.enviar(titulo, "<br>".join(lineas))
        for a, r in avisos:
            db.registrar_alerta(str(a["id"]), "precio", None, None,
                                a["titulo"])


    # -- plazos -------------------------------------------------------

    def revisar_plazos(self, cot=None):
        """Avisa cuando vender en t0 y recomprar en t1 le gana a la
        caucion colocadora, neto de comisiones.

        Antes solo se calculaba al abrir la pestania, asi que una
        oportunidad que duraba media rueda podia no verse nunca.
        """
        if not (self.cfg.get("arbitraje_tickers") or []):
            return 0
        filas = self.evaluar_arbitraje(cot)
        with self.lock:
            self.plazos = filas

        avisos = []
        for f in filas:
            if f.get("error") or not f.get("conviene"):
                self._plazos_avisado.discard(f["ticker"])
                continue
            if f.get("punta_vieja"):
                continue        # el t1 es de antes del cierre
            if not f.get("ejecutable"):
                continue        # sin punta de los dos lados no se ejecuta
            if f["ticker"] in self._plazos_avisado:
                continue
            self._plazos_avisado.add(f["ticker"])
            avisos.append(f)

        if avisos:
            self._avisar_plazos(avisos)
        return len(avisos)

    def _avisar_plazos(self, avisos):
        """Un solo aviso por ciclo, como en rulo y opciones."""
        avisos.sort(key=lambda f: -(f.get("tna_pct") or 0))
        m = avisos[0]
        if len(avisos) == 1:
            titulo = "%s: t0/t1 al %.1f%% TNA" % (m["ticker"], m["tna_pct"])
        else:
            titulo = "%d plazos, el mejor %s al %.1f%% TNA" % (
                len(avisos), m["ticker"], m["tna_pct"])
        lineas = []
        for f in avisos[:8]:
            lineas.append(
                "<b>%s</b> %.1f%% TNA contra %.1f%% de caucion · vender t0 a "
                "%s, recomprar t1 a %s · %s nominales" % (
                    f["ticker"], f["tna_pct"], f.get("tna_caucion_pct") or 0,
                    _n(f["compra_t0"]), _n(f["venta_t1"]),
                    _n(f.get("ejecutable") or 0)))
        if len(avisos) > 8:
            lineas.append("y %d mas en la pestania." % (len(avisos) - 8))
        lineas.append("Plazo de %d dia%s entre liquidaciones." % (
            m.get("dias") or 1, "" if (m.get("dias") or 1) == 1 else "s"))
        self.notif.enviar(titulo, "<br>".join(lineas))
        for f in avisos:
            db.registrar_alerta(f["ticker"], "plazos", f.get("tna_pct"),
                                None, titulo)


    # -- rulo ---------------------------------------------------------

    def revisar_rulo(self, cot=None):
        """Circuitos del ciclo, y aviso cuando alguno supera el umbral.

        Antes solo se calculaban al abrir la pestania, asi que un rulo
        que aparecia y se cerraba entre dos miradas no se veia nunca.
        """
        import json
        import circuitos as CI
        import costos as CO
        cot = cot if cot is not None else dict(self.cotizaciones)
        if not cot:
            return 0
        tengo = self.tengo_actual()

        puentes = [t["ticker"] for t in (self.cfg.get("arbitraje_tickers") or [])
                   if t.get("ticker")]
        universo = sorted(set(puentes) | set(tengo.get("bonos") or []))
        if not universo:
            return 0

        r = CI.analizar(cot, universo, tengo,
                        self.cfg.get("comisiones") or {},
                        float(self.cfg.get("rulo_umbral_pct") or 0),
                        self.cfg.get("derechos_mercado") or {},
                        self.cfg.get("iva_pct") or 0,
                        CO.esquema(self.cfg))
        with self.lock:
            self.circuitos = r

        umbral = float(self.cfg.get("rulo_umbral_pct") or 0)
        if not umbral:
            return 0
        avisos = []
        for g in r.get("grupos") or []:
            for x in (g.get("circuitos") or [])[:1]:
                if x.get("resultado_pct", 0) < umbral:
                    continue
                # con puntas repuestas de antes del cierre no es ejecutable
                if any((cot.get(p.get("especie")) or {}).get("punta_vieja")
                       for p in x.get("pasos") or []):
                    continue
                clave = "%s|%s" % (g.get("clave"), x.get("clave") or
                                   "->".join(p.get("especie") or ""
                                             for p in x.get("pasos") or []))
                if clave in self._rulo_avisado:
                    continue
                self._rulo_avisado.add(clave)
                avisos.append((g, x))
        vivos = set()
        for g in r.get("grupos") or []:
            for x in (g.get("circuitos") or [])[:1]:
                if x.get("resultado_pct", 0) >= umbral:
                    vivos.add("%s|%s" % (g.get("clave"), x.get("clave") or
                              "->".join(p.get("especie") or ""
                                        for p in x.get("pasos") or [])))
        self._rulo_avisado &= vivos

        if avisos:
            self._avisar_rulo(avisos)
        return len(avisos)

    def _avisar_rulo(self, avisos):
        """Un solo aviso por ciclo, como en opciones."""
        avisos.sort(key=lambda t: -t[1].get("resultado_pct", 0))
        g0, x0 = avisos[0]
        if len(avisos) == 1:
            titulo = "Rulo %+.2f%% desde %s" % (
                x0["resultado_pct"], g0.get("desde") or "")
        else:
            titulo = "%d rulos, el mejor %+.2f%%" % (
                len(avisos), x0["resultado_pct"])
        lineas = []
        for g, x in avisos[:6]:
            ruta = " -> ".join(p.get("especie") or "" for p in x.get("pasos") or [])
            lineas.append("<b>%+.2f%%</b> desde %s · %s" % (
                x["resultado_pct"], g.get("desde") or "", ruta))
        self.notif.enviar(titulo, "<br>".join(lineas))
        for g, x in avisos:
            db.registrar_alerta(str(g.get("clave")), "rulo",
                                x.get("resultado_pct"), None, titulo)

    # -- snapshot persistente -----------------------------------------

    def _guardar_snapshot(self):
        """El Panel se alimenta de memoria y quedaba vacio tras cada
        reinicio fuera de rueda. Guardarlo permite mostrar el ultimo
        estado conocido sin pedir nada.

        Se poda antes de guardar: el snapshot se indexa por alias y, al
        renombrar o borrar un par, el alias viejo quedaba adentro para
        siempre y seguia dibujando una tarjeta fantasma.
        """
        import json
        vigentes = {p["alias"] for p in self.pares}
        with self.lock:
            for alias in [a for a in self.snapshot if a not in vigentes]:
                del self.snapshot[alias]
            datos = dict(self.snapshot)
        if datos:
            db.set_estado("snapshot_pares", json.dumps(
                {"ts": datetime.now().isoformat(timespec="seconds"),
                 "pares": datos}))

    def _cargar_snapshot(self):
        import json
        try:
            d = json.loads(db.get_estado("snapshot_pares") or "null") or {}
        except Exception:
            return
        pares = d.get("pares") or {}
        if not pares:
            return
        vigentes = {p["alias"] for p in self.pares}
        pares = {k: v for k, v in pares.items() if k in vigentes}
        if not pares:
            return
        for v in pares.values():
            v["viejo"] = True
        with self.lock:
            if not self.snapshot:
                self.snapshot = pares
        self.snapshot_desde = d.get("ts")


    # -- historico de bonos -------------------------------------------

    def cerrar_dia_bonos(self):
        """Un punto de TIR y duration por bono, con el cierre de hoy."""
        try:
            import historico as H
            import bonos as BO
            with self.lock:
                cot = dict(self.cotizaciones)
            if not cot:
                return 0
            mep = (BO.calcular_mep(cot).get("medio") or 0) or None
            n = H.agregar_hoy(cot, mep)
            if n:
                log.info("histórico de bonos: +%d puntos", n)
            try:
                import curva as CU
                cer_act = float(self.cfg.get("cer_actual") or 0)
                t = BO.tabla(cot, cer_actual=cer_act)
                CU.guardar(CU.residuos(t["filas"]))
            except Exception as e:
                log.debug("residuos del día: %s", e)
            return n
        except Exception as e:
            log.warning("no se pudo cerrar el día de bonos: %s", e)
            return 0

    def reconstruir_historico(self):
        """Completa el histórico de las especies que no lo tengan.

        No es global: si agregás un bono nuevo, se reconstruye solo ese
        en el próximo arranque sin rehacer los que ya están.
        """
        try:
            import historico as H
            H.init()
            faltan = H.sin_serie()
            if not faltan:
                return 0
            log.info("reconstruyendo el histórico de %d especie(s) desde %s: "
                     "%s", len(faltan), H.DESDE, ", ".join(faltan[:8]) +
                     (" y otras" if len(faltan) > 8 else ""))
            total = 0
            for sim in faltan:
                total += H.reconstruir(self.iol, sim)
            log.info("histórico de bonos: %d puntos calculados", total)
            if total:
                try:
                    import curva as CU
                    CU.reconstruir()
                except Exception as e:
                    log.warning("residuos: %s", e)
            return total
        except Exception as e:
            log.warning("no se pudo reconstruir el histórico: %s", e)
            return 0

    # -- relleno de huecos --------------------------------------------

    def rellenar_huecos(self):
        """Días laborables sin lecturas propias se completan con cierres de IOL.

        Pasa cuando se cae internet o la máquina queda apagada. Corre una vez
        por semana: los cierres de la semana ya están consolidados.
        """
        from datetime import date as _date
        desde = (datetime.now().date() - timedelta(days=180)).isoformat()
        rellenados = 0

        for par in self.pares:
            propios = {f for f, _ in db.serie_propia_diaria(par["alias"], desde)}
            serie = db.serie_ratio_diaria(par["num"], par["den"], desde)
            for fecha, ratio in serie:
                if fecha in propios:
                    continue
                try:
                    d = _date.fromisoformat(fecha)
                except ValueError:
                    continue
                if d.weekday() >= 5:
                    continue
                vacio = {"ref": 0, "compra": 0, "venta": 0,
                         "vol_compra": 0, "vol_venta": 0}
                db.guardar_lectura(par["alias"], ratio, vacio, vacio,
                                   ts=fecha + "T23:59:00")
                rellenados += 1

        if rellenados:
            log.info("relleno semanal: %d días completados con cierres de IOL",
                     rellenados)
        db.set_estado("ultimo_relleno", datetime.now().date().isoformat())
        return rellenados

    # -- historico ----------------------------------------------------

    def backfill(self):
        """Cierres historicos de los tickers de cada par.

        Llega hasta ayer y no hasta hoy: el cierre del dia en curso lo
        guarda el cierre diario cuando termina la rueda. Pidiendolo aca
        se gastaba una llamada por ticker en cada arranque para traer un
        dato que iba a llegar igual, o que todavia no existe.
        """
        simbolos = set()
        for p in self.pares:
            simbolos.add((p["mercado"], p["num"]))
            simbolos.add((p["mercado"], p["den"]))
        hasta = datetime.now().date() - timedelta(days=1)

        for mercado, sim in sorted(simbolos):
            ultimo = db.ultimo_cierre_guardado(sim)
            if ultimo:
                desde = datetime.fromisoformat(ultimo).date() + timedelta(days=1)
                if desde > hasta:
                    continue
            else:
                desde = hasta - timedelta(days=BACKFILL_DIAS)
            try:
                datos = self.iol.serie(mercado, sim, desde.isoformat(),
                                       hasta.isoformat())
            except IOLError as e:
                log.warning("historico %s: %s", sim, e)
                continue
            filas = []
            for punto in datos or []:
                fecha = str(punto.get("fechaHora") or "")[:10]
                cierre = punto.get("ultimoPrecio") or punto.get("cierreAnterior")
                try:
                    cierre = float(cierre)
                except (TypeError, ValueError):
                    continue
                if fecha and cierre > 0:
                    filas.append((fecha, cierre))
            if filas:
                db.guardar_cierres(sim, filas)
                log.info("historico %s: +%d cierres", sim, len(filas))
            time.sleep(0.4)

    # -- loop ---------------------------------------------------------

    def loop(self):
        db.init()
        try:
            self._cargar_snapshot()
        except Exception as e:
            log.debug("snapshot guardado: %s", e)
        try:
            self.iol.login()
        except Exception as e:
            self.ultimo_error = str(e)
            log.error("no se pudo autenticar: %s", e)
            return

        try:
            self.backfill()
        except Exception as e:
            log.warning("backfill incompleto: %s", e)

        threading.Thread(target=self.reconstruir_historico,
                         daemon=True, name="hist-bonos").start()

        ultimo_backfill = datetime.now().date()
        espera = int(self.cfg.get("poll_seconds", 600))

        while True:
            try:
                if self._en_horario():
                    self.ciclo()
                    self.ultimo_error = None
                # Fuera de rueda no se pide nada. Antes, si el snapshot
                # estaba vacio se ciclaba igual, pero IOL no manda puntas
                # con el mercado cerrado: el ciclo no lograba llenarlo y
                # se repetia cada diez minutos gastando cupo.

                hoy = datetime.now().date()
                if hoy != ultimo_backfill and datetime.now().hour >= 18:
                    self.backfill()
                    self.cerrar_dia_bonos()
                    db.purgar()
                    db.purgar_api_log()
                    ultimo_backfill = hoy
                    # domingos: completar los días que faltaron
                    if hoy.weekday() == 6:
                        try:
                            self.rellenar_huecos()
                        except Exception as e:
                            log.warning("relleno semanal: %s", e)
            except Exception as e:
                self.ultimo_error = str(e)
                log.error("ciclo fallo: %s", e)

            if not self._en_horario():
                dormir = max(espera, 900)
            elif self.hay_rueda is False:
                dormir = max(espera, 1800)   # feriado: casi no consultamos
            else:
                dormir = espera
            time.sleep(dormir)


def _cerca_del_borde(par, ratio, est, umbral=0.15):
    """Devuelve 'alta', 'baja' o None si el ratio entró en el tramo final."""
    res = par.get("resistencia") or 0
    sop = par.get("soporte") or 0
    if res > 0 and sop > 0 and res > sop:
        ancho = res - sop
        if ratio >= res - ancho * umbral:
            return "alta"
        if ratio <= sop + ancho * umbral:
            return "baja"
        return None
    if est.get("n", 0) >= MIN_MUESTRA_Z and est.get("desvio"):
        z = (ratio - est["media"]) / est["desvio"]
        if z >= 1.5:
            return "alta"
        if z <= -1.5:
            return "baja"
    return None


def _stats(valores, fuente):
    if len(valores) < 5:
        return {"n": len(valores), "fuente": fuente}
    media = statistics.mean(valores)
    return {
        "n": len(valores),
        "fuente": fuente,
        "media": media,
        "desvio": statistics.pstdev(valores) if len(valores) > 1 else 0.0,
        "min": min(valores),
        "max": max(valores),
    }


def _n(v):
    try:
        return "{:,.2f}".format(float(v)).replace(",", "@").replace(
            ".", ",").replace("@", ".")
    except (TypeError, ValueError):
        return "—"


def _e(v):
    try:
        return "{:,.0f}".format(float(v or 0)).replace(",", ".")
    except (TypeError, ValueError):
        return "—"
