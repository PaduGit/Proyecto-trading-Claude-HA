# Registro de cambios

## 0.20.1

**El desplegable de Opciones no abria.** Copie el marcado de Rulo pero no
el toggle: el listener atendia los botones y salia antes de llegar al
despliegue.

**Derechos de mercado por instrumento.** Estaban como un valor unico que
aplicaba a todo, y no lo son: el tarifario de BYMA cobra 0,20% sobre la
prima en opciones de acciones privadas, 0,05% en acciones, 0,01% en
titulos publicos, 0,001% en letras y 0,045% en cauciones. Cargar el 0,20%
de opciones en un campo comun hubiera cobrado el doble de lo debido en
cada pata del Rulo.

Tambien el IVA es selectivo: no se aplica a valores negociables publicos
ni a obligaciones negociables. Un mismo circuito puede tocar bonos
soberanos exentos y acciones que no lo estan, asi que el calculo se
unifico en un modulo propio en vez de repetirse en cada pantalla.

**Fuera de rueda se usa la ultima punta conocida, en toda la app.** IOL
manda el ultimo precio pero no las puntas, y sin puntas no se puede
valuar nada. Ahora se guarda la ultima punta valida de cada simbolo por
separado, no un snapshot del ultimo ciclo entero: las especies iliquidas
pierden punta mucho antes del cierre, y un snapshot unico dejaria a las
liquidas al dia y a las demas con datos de horas antes sin que se note.

Lo repuesto queda marcado como viejo y **ninguna alerta dispara sobre
eso**, ni en pares, ni en curva, ni en opciones. En Rulo es donde mas
engana: un circuito con puntas de ayer se ve rentable y no lo es.

## 0.20.0

**Posiciones de opciones.** Se arman desde el boton de cada combinacion,
que guarda las patas, el riesgo, el ancho y el spot del momento. Ese spot
queda como referencia: es contra el que se mide si el papel se movio en
contra. Se editan los lotes y se cierran a mano, pidiendo el precio de
salida y precargando el valor de recompra vigente por si ejecutaste a otro
precio. El resultado queda registrado.

**Alerta de armado.** Dispara cuando una combinacion cruza hacia abajo el
umbral de riesgo, no mientras se mantiene: si se queda barata toda la
rueda avisa una vez. Vuelve a armarse cuando sale y entra de nuevo. Pide
un minimo de lotes en punta y, si se configura, que el cruce se sostenga
varios ciclos.

**Alerta de desarme.** Tres condiciones en OR, todas configurables:
ganancia sobre el capital en riesgo mayor al 100%, menos de 10 dias al
vencimiento, o el papel movido 4% en contra respecto del spot al armar.
Se valua contra las puntas contrarias, que es como se sale de verdad: la
pata comprada se vende a su bid y la vendida se recompra a su ask. No
avisa si no hay punta para salir.

**Un aviso por ciclo, no uno por spread.** Con tres vencimientos y treinta
bases, un mismo movimiento del papel mete decenas de combinaciones adentro
del umbral a la vez. Llegaban todas juntas y no se leia ninguna. Ahora va
una sola notificacion, ordenada de menor a mayor riesgo, con las ocho
mejores y el resto contado. Lo mismo para el desarme.

**Histórico de costo por combinacion.** Un cierre por dia. El boton "Ver
histórico" del desplegable lo grafica contra el umbral de alarma, que es
lo que dice si un 33% es barato para ese spread o es su nivel de siempre.
La serie es corta por naturaleza: una combinacion vive unos pocos meses
dentro de la ventana de dias.

**Seguir y silenciar.** Por combinacion. Silenciar la saca de las alertas
sin sacarla de la tabla.

**La tabla vacia ahora dice por que.** Eran tres situaciones distintas con
el mismo mensaje: que IOL no mande puntas y no haya nada guardado, que
esten las de la rueda anterior, o que haya puntas frescas y ninguna
combinacion pase el filtro. Confundirlas hacia buscar un problema que no
existia.

## 0.19.1

**La TIR historica del DICP estaba mal desde 2023.** Toda la serie se
calculo con una base CER de 1,8494 cuando la correcta es 1,4552, el CER
del 17-12-2003, diez habiles antes de la emision. El motivo: cuando se
armo la serie, la descarga del CER todavia no llegaba hasta 2003. El 13
de agosto se completo y desde ahi calcula bien, pero los puntos viejos
quedaron congelados con la base equivocada.

Se veia como una TIR plana alrededor del 1% durante tres anios y un salto
a 9,27% en el ultimo dia. No era el mercado: eran dos calculos distintos
pegados. Afecta a todos los bonos del canje 2005, que comparten emision:
DICP, DIPO, PARP, PAPO y CUAP.

**Recalcular histórico entero.** Opcion nueva en el menu. "Reconstruir
histórico" solo agrega hacia adelante, asi que no servia para esto: los
puntos malos quedaban intactos. La nueva rehace el calculo desde 2023,
para una especie o para todas, pisando lo que haya. Hace falta cada vez
que cambia un insumo del calculo y no solo los datos.

Despues de recalcular conviene correr "Recalcular desvios", que se
alimenta de esta serie.

**Volvio el numero de version en el encabezado.** El backend lo inyectaba
en el body y el span estaba puesto, pero nadie los conectaba.

## 0.19.0

**Pestana nueva: Opciones.** Spreads verticales de riesgo acotado sobre
acciones, valuados contra puntas. Tres estructuras: bull con calls y bear
con puts, que son de debito, y bear con calls, que es de credito e
inmoviliza la diferencia de bases como garantia.

Las tres se leen con la misma escala, el riesgo sobre el ancho de bases.
En los debitos el riesgo es lo que se paga; en el credito es el ancho menos
la prima cobrada. Un riesgo del 33% es el ratio 1 a 3: se arriesga 1 para
que la posicion valga 3 al vencimiento. La tabla muestra hasta 45% para que
se vea la curva de costos entera.

La base comprada tiene que caer dentro del 5% del spot: para arriba en el
bull, para abajo en el bear. Los saltos de bases estan limitados a 3, porque
el filtro de costo por si solo premia siempre al spread mas ancho, que es el
que menos chance tiene de llegar a la ganancia maxima.

**El desplegable trae el payoff.** Al tocar una fila se dibuja el resultado
al vencimiento, con el quiebre en cada base, la linea del spot y el punto de
equilibrio. Debajo van las dos patas con su punta, el riesgo y la ganancia en
pesos, cuanto tiene que moverse el papel para llegar a cada uno, y la
garantia cuando corresponde. Hay un boton para copiar las ordenes, con la
compra primero: si se llena sola queda una posicion larga acotada, al reves
queda un lanzamiento sin cobertura.

**La cadena baja en dos requests.** Uno al panel De Acciones, que trae las
puntas de las 1100 series, y uno por subyacente para saber cuales le
pertenecen. Ese segundo request hace falta porque el simbolo de la opcion no
arranca con el del subyacente: las de GGAL empiezan con GFG.

**Fuera de rueda IOL no manda puntas.** No las manda viejas, no las manda.
Asi que la ultima cadena con puntas se guarda y se sirve marcada, aclarando
que no es ejecutable. Los dias al vencimiento se recalculan igual contra la
fecha de hoy.

**Derechos de mercado e IVA salen del hardcodeo.** Ahora son dos campos de
configuracion que aplican a todos los instrumentos. Hacia falta para
opciones, que no estan exentas de IVA como los bonos soberanos: sobre dos
patas, el 21% sobre el arancel pesa.

La tendencia del subyacente se muestra al lado de cada fila, por cruce de
medias de 9 y 21 ruedas, sin filtrar nada.

## 0.18.1

**Los importes del detalle estaban 100 veces arriba.** Los bonos cotizan por
lamina de 100 nominales y el desglose multiplicaba la cantidad por el precio
sin dividir. Comprar 200 nominales de AL30 a 86.500 mueve 173.000 pesos, no
17.300.000. La cadena de cantidades entre patas arrastraba el mismo error.

Los porcentajes nunca estuvieron afectados: salen de cocientes entre precios,
donde la lamina se cancela.

## 0.18.0

**Cada circuito se despliega.** Al tocarlo muestra las cuatro ordenes en
orden: comprar o vender, que especie, cuantos nominales, a que precio y por
cuanta plata. El desglose va sobre el maximo ejecutable, que es el techo del
circuito, y arrastra la cantidad de una pata a la siguiente. Las cantidades
se redondean hacia abajo porque el mercado no admite fracciones, asi que la
ultima linea difiere un poco del porcentaje del encabezado.

**Rulo solo trabaja con bonos que coticen en pesos y en MEP.** La 0.17.0 abrio
el desplegable a los 34 bonos con cronograma y eso metio ruido: el PARP, que
solo cotiza en pesos, arrojaba -6,49% porque venderlo y recomprarlo paga su
propio spread sin convertir moneda. Sin dos puntas no hay salto. Quedan los 14
que sirven, el AO27, el AO28 y el AO29 entre ellos.

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
