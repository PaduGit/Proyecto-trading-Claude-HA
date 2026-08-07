# Ratios IOL — app para Home Assistant

Monitorea ratios entre especies, avisa cuando tocan tus niveles, detecta
arbitrajes de plazo y te da un screener dentro de Home Assistant.

Solo lee datos. Nunca ejecuta órdenes.

---

## Instalar

Ajustes → Apps → ⋮ → Repositorios → pegá la URL de este repo → Agregar.
Después instalá "Ratios IOL", cargá la configuración y arrancala.
Activá "Mostrar en la barra lateral" para tenerla a un toque.

---

## Las cinco pestañas

**Panel.** Cada par con su ratio y una banda donde el soporte y la resistencia
son marcas fijas y la aguja es el precio de ahora. Arriba, cuánto hace de la
última lectura y un botón para forzar la actualización.

**Calcular.** Dos tickers cualquiera. Los que ya usaste aparecen como sugerencia
al tipear, y los pares recientes como botones.

**Plazos.** Arbitraje t0/t1 sobre los tickers que configures.

**Registro.** Tus operaciones y el historial de alertas.

**Explorar.** Consumo de la API y consulta libre de endpoints, solo lectura.

---

## Configuración

### Alertas

| Opción | Qué hace |
|---|---|
| `canal_alertas` | `ha` (notificación al celular), `telegram`, o `ambos` |
| `ha_notify_service` | El servicio de tu dispositivo, ej. `notify.mobile_app_mi_celu` |
| `publicar_sensores` | Crea `sensor.ratio_<par>` para dashboards y automatizaciones |

La notificación de HA va con prioridad alta, así que atraviesa el modo No
molestar. Si no querés eso, cambiá `importance` en `notify.py`.

### Ritmo

`poll_seconds` en 600 significa una lectura cada diez minutos, y por lo tanto
alertas que pueden llegar hasta diez minutos tarde. El botón de refrescar del
encabezado sirve para cuando querés el dato ya.

Fuera de horario consulta cada 15 minutos. Si detecta que ningún título del
panel se movió, asume día sin rueda y baja a media hora.

### Pares y niveles

```yaml
pares:
  - alias: ALUA/TXAR
    num: ALUA
    den: TXAR
    resistencia: 1.54   # 0 = sin nivel, cae al z-score
    soporte: 1.36
    alertas: true
```

`histeresis_pct` define cuánto tiene que retroceder el ratio para considerar que
salió de zona. En 0.5 significa medio por ciento. Sirve para que un movimiento
mínimo alrededor del nivel no dispare una alerta nueva.

**La alerta salta al entrar en zona, una sola vez.** No vuelve a avisar hasta
que el ratio salga de verdad y vuelva a entrar.

### Paneles

```yaml
paneles:
  - instrumento: Bonos
    panel: Soberanos en dólares
    pais: argentina
```

Cada panel es **un solo request** que trae decenas de especies con sus puntas.
Agregar pares cuyos símbolos ya estén en un panel no cuesta requests
adicionales. Lo que no aparezca en ningún panel se pide suelto.

Para ver qué paneles hay y qué traen, usá la pestaña Explorar.

### Comisiones y arbitraje de plazos

```yaml
comisiones:
  - instrumento: bonos
    pct: 0.15

tasa_caucion_anual: 40.0

arbitraje_tickers:
  - ticker: AL30
    tipo: bonos
```

La condición es: **punta compradora de t0 por encima de la vendedora de t1**,
con la diferencia neta de comisiones superando lo que rendiría la caución
colocadora por ese día. La columna "Cant." muestra el mínimo entre ambas puntas:
es lo que realmente podrías mover.

Cargá `tasa_caucion_anual` a mano; si queda en 0 la comparación no significa nada.

---

## Sobre el histórico

Hay dos fuentes y no son intercambiables:

- **Propia**: se arma con las lecturas de la app. Siempre el mismo plazo, siempre
  la misma fuente. Es la buena.
- **De IOL**: el endpoint de serie histórica. Puede mezclar plazos, y de hecho
  se ve un escalón donde cambió el estándar de T+2 a T+1.

La app usa la propia apenas junta 15 días. Hasta entonces usa la de IOL y te
avisa en pantalla que esa serie no es comparable con el ratio de hoy.

Por eso las medias y los z-scores de las primeras semanas hay que mirarlos con
desconfianza. Tus niveles manuales no tienen ese problema.

---

## Datos

SQLite en `/data/ratios.db`, que HA conserva entre reinicios.

- `lecturas` — cada ciclo, con ratio y las cuatro puntas. Se purgan a los 400 días.
- `cierres` — cierres diarios de IOL. No se borran.
- `alertas` y `operaciones` — historial.
- `requests` — consumo de la API por día y tipo.

Las puntas se guardan desde el primer día aunque todavía no se usen del todo:
cuando armemos el detector de rulos vas a tener meses de book acumulado.

---

## Limitaciones conocidas

- **El delay de la API no está medido.** Para ratios lentos no importa; para
  arbitrajes de plazo puede ser determinante.
- **IOL es la fuente de datos, no donde operás.** Los precios de tu ALyC pueden
  diferir. El registro de operaciones es manual por eso.
- **La detección de días sin rueda es heurística.** Si el panel abre plano por
  otro motivo, la app va a espaciar las consultas de más.
- **El panel no informa plazo.** Verificá contra la pantalla de IOL a qué plazo
  corresponden esos precios.

---

## Roadmap

1. ✅ Ratios, alertas, screener
2. ✅ Paneles, notificaciones nativas, arbitraje de plazos, registro
3. Detector de ciclos (rulo) sobre puntas, con costos por pata
4. Estrategias con opciones
