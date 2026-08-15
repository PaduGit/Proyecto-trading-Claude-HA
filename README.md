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

**Rulo.** El tipo de cambio implícito en cada bono, en las dos direcciones.

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

### De dónde salen los datos

El archivo "Estructura financiera de Títulos Públicos" del Ministerio sale una
vez por mes y a veces trae errores. Para los instrumentos nuevos conviene el
**llamado a licitación**, que se publica en argentina.gob.ar con las
condiciones completas: emisión, vencimiento, amortización y ajuste.

Ojo con una limitación: cada llamado detalla solo los instrumentos **nuevos**.
Las reaperturas se mencionan sin condiciones, porque ya se publicaron cuando el
bono nació.

### Los cronogramas

Están en `ratios/app/datos/bonos.yaml`, transcritos del archivo "Estructura
financiera de Títulos Públicos" de la Oficina Nacional de Crédito Público
(Ministerio de Economía), con corte al 31/05/2026.

Los soberanos en dólares están completos: los diez del canje 2020 (AL29, AL30,
AL35, AE38, AL41 y sus pares GD29, GD30, GD35, GD38, GD41, GD46) más los
Bonares del Tesoro 2026 (AO27, AO28, AO29). Con sus especies D y C son 39.

Agregar un bono es agregar una entrada al YAML.

**Dos avisos que la app marca en el detalle:**

*AO29* tiene la fecha de emisión estimada: es posterior al corte del archivo.
La estructura se dedujo del patrón de AO27 y AO28.

*GD35* está descrito en el archivo oficial con la amortización del 2030 (13
cuotas de 4%+8%), que parece un error de copiado: su par por ley argentina, el
AL35, dice 10 cuotas iguales desde enero de 2031. Se usa esa.

### Bonos CER

El capital se ajusta por el CER de diez días hábiles antes de cada fecha. La
app calcula la **TIR real**: convierte el precio en pesos a unidades CER y
descuenta ahí, así que el resultado es la tasa por encima de la inflación —
la X de "CER + X%". No hace falta proyectar inflación.

**El CER lo trae del BCRA solo.** Serie 30 de estadísticas monetarias, que es
pública y no necesita credenciales. Con la fecha de emisión que ya está en el
YAML, la app calcula el coeficiente base de cada bono. Se cachea en la base:
el CER de una fecha pasada no cambia, así que se consulta una vez.

Respeta el rezago de diez días hábiles con que ajusta el capital, **contando
los feriados nacionales**. Eso importa más de lo que parece: sin descontarlos,
la fecha base del TX31 se corría cuatro días y el factor daba 17,21 en vez de
17,36, con casi medio punto de diferencia en la TIR.

La lista de feriados está en `cer.py` y va hasta 2026. Hay que extenderla cada
año; si no, los bonos emitidos en el año nuevo van a tomar una base corrida.

Si el BCRA no responde, esos bonos aparecen atenuados y sin TIR. Como respaldo
se puede cargar `cer_actual` en la configuración y `cer_base` de cada bono en
el YAML; si están, mandan sobre lo que traiga la API.

El estado del CER se puede consultar en `/api/cer`, y el menú ⋮ tiene
**Probar CER (BCRA)**, que fuerza una consulta y devuelve el error exacto si
falla.

Si el BCRA no responde, la app espera cinco minutos antes de reintentar para
no golpearlo en cada consulta.

**La serie se descarga por tramos anuales.** El BCRA acota cuántos días
devuelve por pedido, así que pedirle cuatro años de una no funciona. Al
arrancar cubre desde la emisión más vieja de los bonos cargados hasta hoy, y
después solo agrega lo que falte.

Si para una fecha el CER más cercano quedó a más de quince días, la app no
calcula la TIR de ese bono. Un coeficiente viejo daría un número disparatado
sin que se note.

**Cupón cero:** TZXD6, TZXM7, TZXY7, TZX27, TZXS7, TZXO7, TZXD7, TZXM8,
TZX28, TZXA7, TZXS8, TZXM9, TZXD8.

**Con cupón:** TX28, TX31.

**Canje 2005:** DICP y DIPO (Discount 5,83% 2033), PARP y PAPO (Par step-up
2038), CUAP (Cuasipar 3,31% 2045).

**Letras:** X30S6.

**Provinciales:** PBA28, de la Provincia de Buenos Aires, cupón 9% con
garantía de coparticipación. Las condiciones salen del Boletín Oficial
provincial del 30/07/2026. La reapertura de julio no mueve la fecha base del
ajuste: corre desde la emisión original del 30 de abril.

**El nominal de partida no siempre es 100.** El CUAP capitalizó intereses
hasta 2013 y arranca de 138,92; el DICP del canje arranca de 127,09. Ese
número va en `nominal_base` y se deduce de la paridad de mercado. Con eso las
paridades coinciden con una fuente externa en centésimas.

El del DICP depende del residual que calcula la app: si algún día se corrige
su cronograma de amortización, hay que recalcularlo.

**Dos correcciones sobre el archivo del Ministerio:**

*TX31* figura como "integra al vencimiento", pero el flujo real muestra diez
cuotas iguales desde mayo de 2027, con la renta decreciendo sobre el residual.
Con bullet la renta sería constante. Se usa el cronograma real.

*TZXD8* no está en el archivo al 31/05/2026 porque se emitió después. Las
fechas —emisión 30/06/2026, vencimiento 15/12/2028— salen del llamado a
licitación del 24 de junio.

### Verificado contra una fuente independiente

| | app | referencia |
|---|---|---|
| TX31 TIR real | 9,22% | 9,22% |
| TX31 duration mod. | 2,55 | 2,55 |
| TX31 valor técnico | 1.736,09 | 1.736,08 |
| TZXD8 TIR real | 8,60% | 8,60% |
| TZXD8 duration mod. | 2,16 | 2,16 |

Y a otro precio, para verificar que la sensibilidad también coincide:
TX31 a 1.464 da 9,01% en los dos lados.

El valor técnico es la prueba más exigente: valida el cronograma, el CER base
y el rezago de diez días hábiles a la vez.

### Filtros

Arriba de la tabla hay tres filtros independientes:

**Ley** — todas, argentina, Nueva York.
**Tipo** — todos, hard dollar, CER, tasa fija en pesos, duales.
**Moneda de cotización** — todas, pesos, D (MEP), C (cable).

Se combinan: podés ver, por ejemplo, todos los hard dollar ley argentina sin
importar en qué moneda coticen. Solo aparecen las opciones que tienen bonos
cargados, así que no hay chips muertos.

El resumen debajo dice cuántas especies quedaron de cuántas.

Los filtros mandan sobre la tabla y sobre el gráfico a la vez.

**Por qué importa separar:** la diferencia entre un AL41 y un GD41 —misma
duration, distinto rendimiento— es riesgo legal, no pendiente de curva. Y una
especie C liquida en cable, que es otra moneda que el MEP de las D.

### La curva

El botón "Ver curva" dibuja TIR contra duration modificada.

Con una familia elegida, cada punto lleva su ticker y se colorea según se
despegue del ajuste: verde si rinde más de lo que su plazo justifica, rojo si
rinde menos.

**Si la selección deja más de una moneda de cotización**, cada una se ajusta
por separado y el gráfico lo avisa: una TIR en pesos y una en MEP no son
comparables. Para ver quién se despega hay que elegir una sola moneda.

Con pocos bonos en pantalla se muestran los tickers; con muchos se omiten para
que se lea en el celular.

### La TIR del último operado

La primera columna es la TIR calculada sobre el último precio. Sirve fuera de
rueda, cuando no hay puntas. Si ese precio no es de hoy, la columna aparece
atenuada: el bono no operó y el número puede estar viejo.

### Rulo: circuitos que vuelven al punto de partida

Cada bono implica su propio tipo de cambio: comprar en pesos y vender en su
especie D convierte pesos en dólares MEP a una tasa, y con la C a otra. Como
esas tasas difieren entre bonos, se puede armar un circuito que vuelva al
origen con más de lo que salió.

**Desde una moneda** —pesos, MEP o cable— se pasa por dos bonos y se vuelve a
la misma moneda. Lo que se gana es un porcentaje.

**Desde un bono** se lo vende, se pasa por otro, y se lo recompra. Lo que se
gana son nominales de ese mismo bono. Es la misma lógica de la solapa
Posición: lo que importa no es cuántos pesos tenés sino cuántos nominales.

Hay seis circuitos posibles según de qué moneda salgas, y cada uno se recorre
eligiendo el mejor bono para cada tramo. No hace falta evaluar todas las
combinaciones: para un circuito de dos saltos, el óptimo siempre usa el
extremo de cada tramo.

#### Qué tengo

Arriba se marca qué hay disponible: monedas, bonos o ambos. Solo se buscan los
circuitos ejecutables con eso — un circuito que arranca en cable no sirve si
solo tenés pesos.

**No hacen falta cantidades.** Una oportunidad de 40 nominales sigue siendo
una oportunidad; el ejecutable lo determina la punta, no el saldo.

#### El ejecutable

Cada circuito informa cuántos nominales admite **el circuito entero**, no cada
pata por separado. Cada pata opera con lo que salió de la anterior, así que
hay que arrastrar la cantidad: si la tercera pata solo admite 300, eso limita
cuánto se puede poner al principio.

También dice **qué punta es el cuello de botella**, por si conviene empezar
por ahí.

Todo neto de comisiones, tomadas de la configuración. Si están en cero, avisa
que los resultados son brutos: con cuatro patas eso puede cambiar el signo.

#### Lo que falta

Las puntas se mueven mientras se opera. Con cuatro operaciones, para cuando
llegás a la última puede haber cambiado, así que conviene ir por debajo del
máximo.

Fuera de la rueda las puntas quedan vacías o rotas y no se puede saber qué es
ejecutable. La solapa lo dice en vez de mostrar números falsos.

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

`factor` normaliza pares con láminas distintas: si un nominal de uno equivale
a tres del otro, poné 3. Si no lo cargás, se deduce de los nominales por lámina
que informe la API. **Al cambiarlo, la serie histórica de ese par queda
calculada con el factor viejo.**

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

- **El límite de IOL son 25.000 llamadas al mes bonificadas.** Con paneles y
  refresco de 300 segundos el consumo ronda las 3.500, así que hay margen de
  sobra. Pasado el límite el excedente cuesta poco y se acredita contra
  comisiones. El contador está en la solapa Explorar.
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
- **No se puede navegar desde el screener.** El iframe de Ingress lo bloquea,
  así que el menú solo tiene la prueba de notificación. La configuración y el
  registro están en Ajustes → Apps → Ratios IOL.
- **El relleno semanal de huecos** usa cierres de IOL, que pueden venir de otro
  plazo. Esos puntos se dibujan punteados en los gráficos.

---

## Histórico de TIR

Cada bono guarda una serie diaria con precio, TIR, duration modificada,
residual y CER de esa fecha. Se ve en el panel emergente al tocar el ticker,
con selector de período de tres meses a máximo.

**El punto clave es que cada día se calcula con los datos de ese día**: el
residual que tenía entonces, el flujo que le quedaba por delante y el CER
vigente en esa fecha. No es la TIR de hoy proyectada hacia atrás.

### Cómo se arma

Al arrancar, la app reconstruye desde enero de 2023 con los cierres de IOL.
Corre en segundo plano y tarda algunos minutos. Después agrega un punto por día
al cerrar la rueda.

**La marca de "ya reconstruido" es por bono, no global.** Si agregás uno nuevo
al YAML, se reconstruye solo ese en el próximo arranque sin rehacer los que ya
están.

También se puede forzar desde el menú ⋮ → **Reconstruir histórico**, que
primero muestra cuántas especies están sin serie.

Y **Descargar histórico (CSV)** baja la serie completa —símbolo, fecha,
precio, TIR, duration, residual y CER de cada día— para analizarla afuera.

### Qué queda afuera

Los bonos hard dollar que cotizan **en pesos** no se reconstruyen: para
convertir el precio de una fecha pasada haría falta el MEP de ese día, que no
tenemos hacia atrás. Sí se reconstruyen las especies D y C, y todas las CER.

De ahí en adelante sí se guardan todas, porque el MEP del día está disponible.

### Si se pierde

La serie vive en `/data/ratios.db`, que se borra al desinstalar la app. Pero
es **reconstruible**: se arma con precios de IOL y cronogramas del repositorio,
así que la app la vuelve a generar sola. Lo irrecuperable sigue siendo la
posición, y para eso está el exportar.

---

## Desvío de curva

La columna **Desvío** dice cuánto rinde cada bono por encima o por debajo de
lo que su duration justifica. Se ajusta una curva con los demás bonos de la
misma familia —**excluyendo el que se está midiendo**, para que un bono muy
barato no tire la curva hacia abajo y subestime su propia baratura— y se mide
la distancia en puntos básicos.

El ajuste es sobre el logaritmo de la duration: la curva real es cóncava y en
lineal los extremos quedan siempre mal medidos.

### El z importa más que el desvío

Hay bonos estructuralmente baratos: menos líquidos, menos demanda
institucional. Esos aparecerían en verde todos los días sin que haya nada que
hacer. Lo que importa es si está **más barato que lo habitual para él**, y eso
es el z-score del desvío contra su propia historia de 120 días.

La tabla tiene las dos columnas por separado: **Desvío** en puntos básicos y
**z** contra la propia historia. Ambas ordenables. La segunda es la que sirve
para buscar señales — un bono puede tener desvío chico y z alto, o al revés.

Verde a partir de +2,5 desvíos, rojo a partir de −2,5. Ámbar entre 2 y 2,5.

### De dónde salen esos umbrales

De un backtest sobre 22.000 puntos de 30 especies entre 2023 y 2026:

| umbral | horizonte | casos | ganancia neta | acierto |
|---|---|---|---|---|
| 2,0 | 42 días | 297 | 1,29% | 65% |
| 2,5 | 42 días | 145 | 2,84% | 77% |
| 2,5 | 63 días | 134 | 3,15% | 73% |

La ganancia es de rotar al bono barato contra su vecino de duration similar,
neta de 0,8% de costos por las cuatro patas. Al azar el acierto es 51%, así
que la señal no es un artefacto.

**Tres advertencias.** Por debajo de 2 desvíos los costos se comen todo. Las
especies C ensucian la señal —son ilíquidas y sus cierres no reflejan
operaciones reales—: sacándolas el acierto sube de 64% a 77%. Y el backtest
usa precios de cierre, no puntas: un bono puede verse barato en el last y
tener el ask 2% arriba. Por eso la alerta solo se dispara si hay punta
vendedora.

### Ordenar la tabla

Tocá cualquier encabezado para ordenar por esa columna; tocalo de nuevo para
invertir. Arranca por **MD** ascendente, que es como se lee la curva, y esa
columna sigue ahí para volver a ese orden cuando quieras.

Ordenar por **Desvío** descendente pone arriba los más baratos; por **TIR
Last** descendente, los que más rinden en términos absolutos. Los bonos sin
dato quedan siempre al final, ordene como ordene.

### Alertas

Cuando un bono cruza el umbral, llega una notificación con el desvío, el
z-score, la TIR contra la curva y el vecino contra el que conviene rotar.
Avisa una sola vez al cruzar, igual que las de ratios.

`curva_umbral_z` en la configuración lo ajusta. En 0 se apaga.

Si la columna Desvío muestra los puntos básicos pero no el **z**, faltan los
residuos históricos: menú ⋮ → **Recalcular desvíos**. Necesita al menos 40
días de historia por bono, así que los recién emitidos van a tardar.

---

## Respaldo

**La configuración** se copia a `/data/respaldo.json` cada vez que la app
arranca, sin credenciales. Si en un arranque los pares o los paneles vienen
vacíos, los repone de ahí y lo avisa en el registro. Solo actúa cuando la lista
está vacía: si borrás un par a propósito, no lo resucita.

**La posición** se exporta desde la propia solapa: Posición → Respaldo →
Exportar. Copia el texto al portapapeles directamente; si el navegador lo
bloquea, queda seleccionado abajo para copiar a mano. Para restaurarlo, lo pegás en el mismo
cuadro y tocás Importar.

Al importar pregunta qué hacer con los grupos que ya existan con el mismo
nombre: reemplazarlos o dejarlos y agregar solo los nuevos.

Vale la pena exportar de vez en cuando y guardar el texto afuera de Home
Assistant. Desinstalar la app puede borrar el volumen `/data`, y con él la
base entera.

---

## Si no llegan las notificaciones

Menú ⋮ → **Probar notificación**. Te dice qué falta.

Hay dos caminos para hablarle a Home Assistant, y la app usa el que esté.

**Por el Supervisor (automático).** Requiere `homeassistant_api`, que la app ya
declara. Si el diagnóstico dice que no llega el token, probá desinstalar y
reinstalar: el permiso se fija al construir el contenedor.

**Con un token propio (respaldo).** No depende de los permisos del add-on.
En Home Assistant: tocá tu usuario abajo a la izquierda → pestaña Seguridad →
al final, **Tokens de acceso de larga duración** → Crear. Copiá el token y
pegalo en `ha_token` en la configuración de la app.

Si el add-on no resuelve el nombre `homeassistant`, cargá también `ha_url` con
la dirección de tu instalación, por ejemplo `http://192.168.1.10:8123`.

Este camino tiene una ventaja: el token es tuyo y lo podés revocar cuando
quieras desde la misma pantalla.

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
7. Rulo: sumar comisiones por pata, volumen ejecutable y ciclos de cuatro patas
8. Estrategias con opciones
9. Evaluar la API de ECO Valores (Primary): tiempo real por websocket
