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

**Bonos.** TIR en cada punta de los soberanos con cronograma cargado.

**Posición.** Tu resultado medido en nominales, no en pesos.

**Plazos.** Arbitraje t0/t1 sobre los tickers que configures.

**Registro.** Tus operaciones y el historial de alertas.

**Explorar.** Consumo de la API y consulta libre de endpoints, solo lectura.

---

## Bonos: TIR en cada punta

Cinco columnas — especie, bid, TIR bid, ask, TIR ask — ordenadas por duration
modificada. Tocá el ticker y se abre el detalle: próximo pago con monto,
vencimiento, residual, cupón vigente, paridad, current yield, interés corrido,
duration y el flujo de fondos completo.

### El MEP no es un número

Si comprás dólares pagás un precio y si los vendés cobrás otro, porque el
spread del bono queda adentro. Por eso cada punta se convierte con el tipo de
cambio que le toca:

- **El bid** lo cobrás en pesos, así que para llevarlo a dólares tenés que
  comprarlos: se usa el MEP de compra (ask en pesos / bid de la especie D).
- **El ask** lo pagás en pesos, que conseguiste vendiendo dólares: se usa el
  MEP de venta (bid en pesos / ask de la D).

El resultado es que las especies en pesos muestran spreads de TIR más anchos
que las D. No es un error: es el costo real de entrar y salir pasando por el
cambio.

El par de referencia es configurable (`mep_par_pesos` / `mep_par_usd`).
Por defecto AL30/AL30D, que suele tener el spread más angosto.

### Los cronogramas

Están en `ratios/app/datos/bonos.yaml`, transcritos del archivo "Estructura
financiera de Títulos Públicos" de la Oficina Nacional de Crédito Público
(Ministerio de Economía), con corte al 31/05/2026.

Hoy trae AL30, AE38, GD38, AO28 y AO29, más sus especies D y C. Agregar un
bono es agregar una entrada al YAML.

**AO29 tiene la fecha de emisión estimada**: no figura en ese archivo porque es
posterior al corte. La estructura se dedujo del patrón de AO27/AO28 y de la
descripción que devuelve IOL. El detalle lo marca con un aviso.

### D y C: dos monedas distintas

Las especies D liquidan en dólar MEP y las C en cable. El bono paga donde está
depositado, así que cada TIR es internamente consistente: comprás en cable y
cobrás en cable, o comprás en MEP y cobrás en MEP. No hay que convertir nada.

Pero **las TIR de una D y una C no son comparables entre sí**, porque están
medidas en monedas distintas. Que AL30C rinda más que AL30D no significa que
esté barata: significa que el cable está más caro.

La columna **Cable** muestra cuánto más caro está el cable que el MEP en ese
bono. Eso sí es comparable entre bonos, y la dispersión es la señal: si un bono
muestra 5,7% y el resto 3%, ahí hay algo.

Ojo con la liquidez: las especies C suelen tener spreads anchos, y una punta
mala distorsiona la lectura.

### Verificación

El flujo del AO29 calculado acá coincide con una planilla de referencia
independiente: 39 pagos y TIR de 8,44% al mismo precio y fecha. La duration de
esa planilla no coincide (daba 1,36 contra 2,69), y una tercera fuente daba 2,8,
del lado de este cálculo.

Contrastá los números con bonarg.com antes de operar sobre ellos.

---

## Posición: por qué en nominales

Si rotás entre ALUA y TXAR, contar pesos no sirve: el resultado se mezcla con
lo que hizo el mercado. Lo que importa es **cuántos nominales acumulaste**.

Arrancás con 7.000 ALUA, rotás cuando el ratio está caro, volvés cuando está
barato, terminás con 8.200 ALUA: ganaste, aunque Aluar haya caído 30%.

### Cómo se usa

Creá un grupo con los tickers entre los que rotás y elegí la unidad de medida
(el ticker en el que se expresa todo). Después cargás tres tipos de movimiento:

- **Rotación** — vendo X de uno, compro Y del otro. Es lo que genera resultado.
- **Aporte** — entra capital nuevo. Pide a cuántas unidades base equivale.
- **Retiro** — sale capital.

Los aportes y retiros **no cuentan como ganancia**. La app usa contabilidad por
cuotapartes, igual que un fondo: los aportes emiten cuotas al valor del momento,
así que el porcentaje de rendimiento solo se mueve por tus rotaciones.

Por eso al cargar un aporte hay que indicar el equivalente. Si aportás 3.000
TXAR con el ratio en 1,50, eso equivale a 2.000 ALUA. La app te lo precarga con
el precio del momento y vos lo corregís si hace falta.

### Grupos de más de dos tickers

Están soportados. Todo se convierte a la unidad base con los precios de hoy,
así que podés tener un grupo con varios bonos de la misma curva.

---

## Configuración

### Alertas

| Opción | Qué hace |
|---|---|
| `canal_alertas` | `ha` (notificación al celular), `telegram`, o `ambos` |
| `ha_notify_service` | El servicio de tu dispositivo, ej. `notify.mobile_app_mi_celu` |
| `panel_path` | Ruta del panel en la barra lateral, para que el botón de la notificación abra el screener |
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

## Privacidad

El screener no carga nada de internet: las fuentes son locales, con respaldo a
las del sistema. Si querés el tipo IBM Plex, dejá los `.woff2` en
`ratios/app/static/fonts/` (ver el LEEME de esa carpeta).

Con `canal_alertas: ha` no interviene ningún servicio externo salvo el push de
Google, que es inevitable en Android. Con `telegram` o `ambos`, los mensajes
pasan por los servidores de Telegram.

---

## Datos

SQLite en `/data/ratios.db`, que HA conserva entre reinicios.

- `lecturas` — cada ciclo, con ratio y las cuatro puntas. Se purgan a los 400 días.
- `cierres` — cierres diarios de IOL. No se borran.
- `alertas` y `operaciones` — historial.
- `requests` — consumo de la API por día y tipo.
- `grupos` y `movimientos` — la contabilidad en nominales.

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
- **La curva de posición es aproximada** en los tramos donde no se puede
  reconstruir el precio de todos los tickers. Los puntos que no se pueden
  calcular se omiten; el valor de hoy siempre es exacto.
- **El botón de la notificación necesita WireGuard levantado** si estás fuera
  de casa. La notificación llega igual; lo que no funciona es el link.
- **El menú de tres puntos** abre en pestaña nueva. El screener corre en un
  iframe de Ingress y no puede navegar la ventana principal de HA.
- **El relleno semanal de huecos** usa cierres de IOL, que pueden venir de otro
  plazo. Esos puntos se dibujan punteados en los gráficos.

---

## Si no llegan las notificaciones

Menú ⋮ → **Probar notificación**. Te dice qué falta.

El caso más común es que falte el token del Supervisor. Eso pasa cuando la app
se actualizó desde una versión que no pedía `homeassistant_api`: el permiso se
fija al construir el contenedor. Se arregla desinstalando la app y volviéndola
a instalar (los datos viven en `/data` y no se pierden).

También conviene revisar, en Ajustes → Apps → Ratios IOL:

- **Iniciar en el arranque** — si no, un corte de luz te deja sin monitoreo.
- **Vigilancia** — reinicia la app si se cae.

---

## Roadmap

1. ✅ Ratios, alertas, screener
2. ✅ Paneles, notificaciones nativas, arbitraje de plazos, registro
3. ✅ Posición en nominales, sin dependencias de nube
4. ✅ TIR y duration de bonos, gráficos por período, relleno de huecos
5. Anclajes diarios de TIR: gráfico histórico y alertas sobre rendimiento
6. Curva TIR contra duration, para ver qué bono se despegó
7. Detector de ciclos (rulo) sobre puntas, con costos por pata
8. Estrategias con opciones
9. Evaluar la API de ECO Valores (Primary): tiempo real por websocket
