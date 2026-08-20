# Registro de cambios

## 0.20.8

**Las especies sin punta desaparecian de la tabla.** El snapshot guardaba
solo los simbolos que tenian bid y ask, asi que los CER que cierran sin
punta y solo con ultimo operado —los TZX, TX28, TX31, X30S6— se perdian
al cerrar el mercado y la tabla mostraba tres bonos en vez de trece. Ahora
tambien se guarda el ultimo, y esas especies vuelven a verse atenuadas,
como dice el texto de ayuda de esa misma pantalla.

**Plazos pedia a IOL con el mercado cerrado.** La condicion exigia que
hubiera un calculo previo del ciclo para servirlo, y fuera de rueda no lo
hay, asi que caia en la rama que pide. Ahora no pide nunca fuera de
horario.

**Plazos carga sola.** Ahora que se calcula en cada ciclo no tiene sentido
que dependa de un boton; se muestra al entrar y el boton queda para
forzar. La tabla pasa a mostrar TNA y TNA de caucion en vez de la tasa
diaria, que es como se compara de verdad, y marca cuando el t1 viene de
antes del cierre.

**Panel y Calcular son una sola pestania, Ratios.** El panel de pares
queda arriba y el calculador debajo, en un desplegable: lo que se mira
seguido primero y lo ocasional sin estorbar. Plazos pasa antes de
Posicion.

**Tocar una linea del registro copia su direccion.** En las dos vistas.

**El cierre de mercado por defecto pasa a las 17:00.** Estaba en 17:15, y
esos quince minutos hacian que la ultima foto guardada fuera de la
subasta de cierre en vez de la rueda plena.

## 0.20.7

**Alertas de Plazos.** Vender en t0 y recomprar en t1 es cobrar hoy y
pagar manana: la diferencia de precios es una tasa implicita. Se avisa
cuando esa TNA, neta de comisiones, le gana a la caucion colocadora.
Antes solo se calculaba al abrir la pestania, asi que una oportunidad que
duraba media rueda podia no verse nunca. Un aviso agrupado por ciclo, sin
repetir hasta que la oportunidad desaparece, y no dispara con puntas de
antes del cierre ni sin nominales ejecutables.

**La TNA se anualiza por dias corridos entre liquidaciones.** Un viernes
son tres dias, porque t0 liquida el viernes y t1 el lunes; con feriado de
por medio, cuatro. Tomar siempre uno inflaba por tres las oportunidades
de los viernes: una diferencia de 0,15% da 54,8% de TNA a un dia y 18,2%
a tres. Se muestra junto a la TNA de caucion para poder compararlas.

**El t1 sale del panel.** Los paneles de acciones cotizan a t1, asi que
solo hace falta pedir el t0 de cada ticker de arbitraje. Antes se pedian
los dos y era el doble de requests.

**Tres paneles nuevos:** Merval, Panel General y CEDEARs. Cada panel que
se agrega saca especies de la lista de pedidos sueltos, que son la mayor
parte del consumo.

**La pestania Plazos lee del ciclo** y fuera de rueda no pide nada, como
el resto.

## 0.20.7

**Alertas de Plazos.** Vender en t0 y recomprar en t1 deja plata hoy y la
paga manana, asi que la diferencia de precios es una tasa implicita.
Ahora se evalua en cada ciclo y avisa cuando esa TNA, neta de comisiones,
le gana a la caucion colocadora. Antes solo se calculaba al abrir la
pestania, asi que una oportunidad que duraba media rueda podia no verse
nunca. Un aviso agrupado por ciclo, sin repetir hasta que desaparece.

**La TNA se anualiza por dias corridos entre liquidaciones.** Un viernes
son tres dias, y con feriado de por medio cuatro. Tomar siempre uno
triplicaba la TNA implicita de los viernes: la misma diferencia de 0,15%
da 54,8% de TNA un miercoles y 18,2% un viernes.

**El t1 sale del panel.** Los paneles cotizan a t1, asi que solo hace
falta pedir el t0 de cada ticker de arbitraje. Antes se pedian los dos y
era el doble de requests. La pestania Plazos lee del ciclo y fuera de
rueda no pide nada.

**Tres paneles mas de Acciones:** Merval, Panel General y CEDEARs. Cada
panel que se agrega borra pedidos sueltos del ciclo, que son la mayor
parte del consumo: LOMA, HARG y los CEDEAR se pedian de a uno.

## 0.20.6

**Posicion y Opciones seguian pidiendo con el mercado cerrado.** Posicion
consultaba la cotizacion de cada ticker que no estuviera en el mapa del
ciclo, uno por uno, en cada visita; fuera de rueda el mapa esta vacio,
asi que los pedia todos cada vez. Opciones hacia lo mismo con los cierres
del subyacente para las medias. Ahora ninguna pestania llama a IOL fuera
de horario.

**El origen del registro decia "ciclo" para todo.** Solo estaban
etiquetados el boton de refrescar y Explorar; el resto quedaba con el
valor por defecto, asi que el log mostraba como ciclo lo que en realidad
disparaba una pestania. Era el peor error posible en una herramienta cuya
razon de ser es decir de donde sale el consumo.

**Copiar y borrar el registro.** Copiar saca lo que se este mostrando en
texto separado por tabulaciones, listo para pegar en una planilla. Borrar
lo vacia: sirve para medir desde cero, se limpia, se hace algo, y lo que
aparece es exactamente eso.

## 0.20.5

**Bonificacion intradiaria por broker.** Se elige el broker en la
configuracion y el Rulo calcula con su esquema. No son la misma regla:
IOL exige que se repita el mismo simbolo de negociacion, Eco bonifica el
lado menor entre especies distintas mientras coincidan moneda y plazo, y
Veta Flat no cobra arancel marginal porque va por abono. El porcentaje es
configurable, con 100% por defecto. Solo alcanza al arancel del agente:
los derechos de mercado son de BYMA y se pagan igual.

Una consecuencia que conviene tener presente: **con el circuito de cuatro
patas, IOL no bonifica nada**. Sus cuatro patas son simbolos distintos.
La excepcion que valia antes —el circuito desde un bono propio recompraba
la especie vendida— existia por las dos patas de mas que tenia la version
de seis, y desaparecio al corregirlo. Las cuatro patas siguen siendo lo
correcto, pero por las operaciones que ahorran, no por la bonificacion.

Costo de un circuito de cuatro patas sobre bonos, con arancel 0,15% y
derechos 0,01%: IOL 0,640%, Eco 0,340%, Veta 0,040%.

**El catalogo deja de pedirse en cada visita.** La lista de instrumentos y
la de paneles cambian cuando BYMA agrega o saca uno, no todos los dias, y
se pedian dos requests cada vez que se entraba a Explorar. Ahora se
guardan una semana, con una opcion para forzar la recarga.

Lo mismo con las series que pertenecen a cada subyacente: cambian cuando
se listan vencimientos nuevos, no cada diez minutos. Cacheadas medio dia,
el modulo de Opciones baja de dos requests por ciclo a uno.

**Las dos vistas del registro de llamadas eran la misma.** "Ver detalle"
mostraba el resumen y ademas el log, asi que la parte de arriba era
identica a la del otro boton. Ahora "Ver llamadas" es el log crudo, una
linea por request con fecha y hora, y "Ver resumen" es solo el agrupado.
Se saco el tiempo de respuesta de la vista; se sigue guardando.

**DICP y CUAP: de que sale el nominal de partida.** La nota decia que se
habia deducido de la paridad de mercado, que es circular y hacia dudar
del numero. Se reemplazo por la derivacion real. El DICP capitalizo en
dos tramos step-up y encadenandolos se llega a 127,0 por cada 100
nominales; el CUAP capitalizo el 100% de los intereses y da 138,82. Los
valores cargados difieren menos de una decima de punto por convencion de
dias. Contrastado ademas contra la curva CER.

## 0.20.4

**Cero llamadas a IOL con la rueda cerrada.** El ciclo de fondo respetaba
el horario, pero las pestanias no: cada vez que se tocaba Bonos, Rulo u
Opciones se disparaban requests que devolvian precios sin puntas, o sea
nada nuevo, y consumian cupo. Antes, ademas, si el snapshot estaba vacio
se ciclaba igual fuera de horario, y como IOL no manda puntas con el
mercado cerrado el ciclo nunca lograba llenarlo: se repetia cada diez
minutos sin resultado.

**El ciclo trae todo y las pestanias leen de memoria.** Las especies con
cronograma se suman a los simbolos del ciclo, asi que Bonos y Rulo dejan
de pedir al abrirlos. Navegar no consume nada y el mismo dato deja de
bajarse una y otra vez. El boton de actualizar sigue pidiendo aunque este
cerrado, para emergencias.

**Alertas de Rulo.** No existian: los circuitos solo se calculaban al
abrir la pestania, asi que uno que aparecia y se cerraba entre dos
miradas no se veia nunca. Ahora se evaluan en cada ciclo, con un aviso
agrupado por ciclo y sin repetir hasta que el circuito deja de cumplir.
No dispara sobre puntas repuestas de antes del cierre.

**El Panel ya no queda vacio tras un reinicio.** Los ratios vivian solo
en memoria; al reiniciar fuera de rueda no habia forma de recuperarlos.
Ahora el estado se guarda al cierre de cada ciclo.

**El horario contempla los feriados.** Miraba solo el dia de la semana,
asi que un feriado se trataba como jornada habil.

**Registro de llamadas a la API.** Cada request queda anotado con su
direccion completa, el tipo, el estado, cuanto tardo y quien lo pidio:
ciclo, boton o pestania. El contador por tipo dice cuantas llamadas hubo,
no cuales; esto dice de donde sale el consumo. Se ve en Explorar, debajo
del consumo mensual, y se guardan 7 dias.

**El contador de requests de hoy daba cero.** Las llamadas se registraban
con la fecha local y el resumen las buscaba con date('now'), que en
SQLite es UTC: pasadas las 21 hora argentina ya era el dia siguiente y no
encontraba nada. Tambien afectaba al total del mes en el cambio de mes.

## 0.20.3

**TX28 rendia -37,6%.** La fecha de emision cargada era la del canje de
2022 y la real es la emision original, 4 de septiembre de 2020. Con la
base CER corrida casi dos anios, el factor quedaba a la mitad y el precio
normalizado salia el doble del que corresponde.

El cronograma si estaba bien: diez cuotas semestrales iguales el 9 de
mayo y el 9 de noviembre, la primera el 9 de mayo de 2024, y el residual
del 50% que muestra la app es correcto.

**X30S6 rendia 203%.** La fecha de emision estaba marcada como estimada
en el propio archivo, y lo estaba mal: la letra se anuncio como nueva en
la licitacion del 12 de marzo de 2026, no en septiembre de 2025. Queda
cargada la liquidacion a T+2 de esa licitacion.

Los dos cambian la base CER, asi que su serie historica quedo mal
calculada y hay que rehacerla con "Recalcular histórico entero".

## 0.20.2

**Los circuitos desde un bono eran de seis patas y deben ser de cuatro.**
Vender el bono en pesos para comprar otro en pesos es pasar por liquidez:
las dos patas no aportan nada y solo suman comisiones. Cada especie
cotiza en una sola moneda, asi que el propio bono tiene que ser uno de
los dos puentes, no algo que se liquida primero.

La forma correcta: vender AO29D contra dolares, comprar AL30D, vender
AL30 en pesos, recomprar AO29 en pesos. Cuatro operaciones, y lo que se
gana son nominales de AO29.

Tiene ademas efecto de costos: en IOL la recompra de la especie vendida
califica como intradiaria y se bonifica. En la version de seis patas, no.

**Panel de bonos en pesos.** Estaba configurado solo el de soberanos en
dolares, asi que los CER se pedian de a uno. Ahora tambien baja
"Soberanos en pesos mas CER", que trae CUAP, DICP, DIPO, PAPO y PARP en
un request.

**Reintentar especies sin precio.** La opcion existia en el backend pero
nunca tuvo entrada en el menu. Una especie que falla una vez queda
apartada para no repetir el pedido en cada refresco, y sin esta opcion no
habia forma de volver a intentarlo. Por eso TX28 y TZX28 no aparecian.

El tope de pedidos sueltos por consulta subio de 12 a 30: los BONCER
(TZX*, TX28, TX31, X30S6, PBA28) no estan en ningun panel y son mas de
doce, asi que los ultimos de la lista nunca llegaban a pedirse.

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
