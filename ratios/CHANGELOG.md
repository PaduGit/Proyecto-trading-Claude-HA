# Registro de cambios

## 0.17.0

**El AO29 vuelve a la lista de Rulo.** El desplegable de "qué tengo" solo
ofrecía bonos con las tres especies —pesos, D y C—, así que el AO29, el AO28,
el AO27 y todos los CER quedaban afuera. Ese filtro no tenía sentido para
declarar una tenencia: un bono sirve de origen aunque no cotice en las tres.
Ahora ofrece los 34 bonos con cronograma.

**Los mismos bonos entran como puente.** Un salto es comprar una especie y
vender otra del mismo bono, así que alcanza con dos. El AO29 no cotiza en
cable, pero con AO29 y AO29D convierte pesos en MEP igual. El universo de
intermediarios pasa de 11 bonos a 14. Los saltos que necesiten la especie que
falta se descartan solos al no haber punta.

## 0.16.1

- Los ids de la solapa Rulo colisionaban con los de Calcular: `c-btn` era el
  mismo en las dos, así que el botón "Buscar circuitos" enganchaba el evento
  del botón equivocado y no hacía nada. Ahora van prefijados con `cir-`.

## 0.16.0

**Rulo pasa a buscar circuitos completos.**

Antes mostraba los tipos de cambio implícitos de cada bono y había que
deducir a mano si cerraba algo. Ahora busca circuitos que vuelven al punto de
partida:

- **Desde una moneda** —pesos, MEP o cable—: se pasa por dos bonos y se
  vuelve a la misma moneda. Lo que se gana es un porcentaje.
- **Desde un bono**: se vende, se pasa por otro, y se recompra el original.
  Lo que se gana son nominales de ese mismo bono, que es como conviene medir
  la posición.

Se declara arriba qué hay disponible y solo se buscan los circuitos
ejecutables con eso. No hacen falta cantidades: una oportunidad de 40
nominales sigue siendo una oportunidad.

Cada circuito informa el **máximo ejecutable** —calculado arrastrando la
cantidad de una pata a la siguiente, porque cada una está limitada por lo que
salió de la anterior— y **qué punta es el cuello de botella**.

Todo neto de comisiones, tomadas de la configuración. Si están en cero, avisa
que los resultados son brutos: con cuatro patas eso cambia el signo.

**Arreglo**

- El id `r-out` estaba duplicado entre las solapas Rulo y Registro, así que
  el Registro escribía dentro de una solapa oculta. Por eso se veía en blanco
  aunque las alertas estuvieran guardadas.

## 0.15.6

**Arreglos**

- **El Registro no mostraba nada.** Un `Promise.all` mal armado esperaba las
  respuestas de a una: si la primera fallaba, la solapa entera quedaba en
  blanco. Las alertas estaban guardadas todo este tiempo.
- Las alertas de curva ahora tienen su propio ícono en el Registro; antes
  caían en el caso "baja" y mostraban una flecha equivocada.
- **El token de IOL se renovaba mal.** Usaba 12 minutos fijos en vez del
  `expires_in` que informa la API, y como el refresh vencía antes, cada ciclo
  terminaba reautenticando desde cero con un request extra.

**Cambios**

- **Columna z separada** del desvío, ordenable por su cuenta. Es la que
  importa para buscar señales: un bono puede tener desvío chico y z alto.
- **Gráficos con máximo y mínimo marcados**, con su valor y fecha, más
  referencias temporales intermedias y un resumen de amplitud al pie.

## 0.15.5

Ajustes sobre la tabla de bonos:

- **Columna MD** con la duration modificada. Es ordenable, así que ahora se
  puede volver al orden por duration después de haber ordenado por otra
  columna.
- **Recalcular desvíos** en el menú ⋮. El z-score necesita historia de
  residuos, y hasta ahora solo se calculaba cuando el histórico traía puntos
  nuevos. Este botón lo fuerza.
- **Menos requests.** La tabla se cachea 20 segundos y deja de insistir con
  las especies que IOL no cotiza (TX28, X30S6 y PBA28 no están en ningún
  panel). Antes cada apertura de la solapa disparaba pedidos que fallaban.

## 0.15.0

- Ordenar la tabla tocando cualquier encabezado.

## 0.14.0

- **Desvío de curva**: cuánto rinde cada bono por encima o por debajo de lo
  que su duration justifica, con z-score contra su propia historia.
- Alertas cuando un bono cruza 2,5 desvíos, con el vecino contra el que
  conviene rotar.
- Umbrales validados con un backtest sobre 22.000 puntos: 2,84% neto con 77%
  de acierto a 42 días.

## 0.13.0

- `nominal_base` para los bonos del canje 2005: el CUAP arranca de 138,92 por
  la capitalización hasta 2013 y el DICP de 127,09. Sin eso sus TIR daban
  1,70% y 5,68%.
- Descarga del histórico en CSV desde el menú.

## 0.12.0

- 16 especies CER nuevas: los nueve cupón cero, TX28, X30S6, los cinco del
  canje 2005 y el PBA28.
- Filtros por ley, tipo y moneda de cotización.
- Columna Last con el precio del último operado.
- Exportar la posición al portapapeles.

## 0.11.0

- Histórico de TIR y duration por bono desde 2023, reconstruido con los
  cierres de IOL. Gráfico en el panel emergente.
