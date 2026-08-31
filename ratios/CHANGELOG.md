# Registro de cambios

## 0.27.1

**Los brokers por nombre al agrupar.** Decia "2 brokers"; ahora dice
"Veta · IOL-SOL", que es justamente el dato que se perdia al juntar las
lineas.

**Ratios pierde la tenencia y los movimientos.** El panel de pares
seguia mostrando lo que se tiene, el rendimiento y el boton de
movimientos. Queda el ratio, el grafico, "Opere" y la edicion del par:
lo que se tiene y como viene rindiendo esta en la estrategia.

**"Usar la tenencia actual".** Un grupo sin movimientos no tiene contra
que medir la rotacion y pedia cargar el aporte inicial a mano, en todas
las estrategias creadas desde los grupos. El boton lo siembra con lo que
ya figura en la tenencia, sumando los brokers, porque el grupo mide
nominales y no donde estan.

**El desplegable de grupos no quedaba en blanco.** Se dibujaba solo si
los grupos ya estaban cargados, asi que segun el orden en que llegaban
las respuestas podia no mostrar nada. Ahora se dibuja siempre y dice
cuando todos los grupos ya tienen estrategia.

## 0.27.0

**La barra de peso salia siempre al 100%.** El ancho se armaba con
`num()`, que formatea en es-AR y devuelve coma decimal: `width:34,4%` no
es CSS valido y el navegador lo descarta. El tablero viejo usaba
`toFixed`, que da punto, y se colo al reescribir la lista.

**Agrupar por especie.** Un chip nuevo junta la misma especie de varios
brokers en una linea: repartida en tres no se ve cuanto pesa de verdad.
Suma valor, costo y peso, y el resultado se calcula sobre los totales y
no como promedio de porcentajes, para que una posicion chica con +80% no
pese igual que una grande. En ese modo no se abre el editor: no hay una
sola fila que editar.

**Cada pestania hace una cosa.** Tenencias es el seguimiento de lo que se
tiene y por que; Ratios, Bonos, Rulo y Pases son para buscar
oportunidades. Los canjes pasan a Bonos, que es donde estan la curva y
los desvios.

**El bloque de grupos sale de Ratios.** La contabilidad por cuotapartes
es seguimiento, no analisis. Un grupo con estrategia se ve adentro de
ella; los que todavia no tienen quedan en un desplegable aparte, con el
boton de crear y el respaldo.

**La estrategia se expande con todo junto**: tesis y origen, cuanto
rindio y cuanto rindio su patron, cada especie con su broker y su
resultado, el aviso de que hay un canje esperando en alguna de sus
puntas, y la tarjeta del grupo con sus movimientos.

## 0.26.1

**La pestania Posicion no cargaba.** Al agregar los filtros quedo
`completa = CA.valuar(filas, precios, mep, bonos_cfg)` arriba de las
lineas que definen esas tres variables, asi que `/api/cartera` moria con
`UnboundLocalError` en cada request. El AST compila igual y el add-on
arranca sin quejarse: el error aparece recien al pedir la pestania.

Se agrega al control previo un chequeo de variables usadas antes de su
primera asignacion, que respeta el scope propio de comprehensions y
funciones anidadas para no llenarse de falsos positivos. Sobre el codigo
roto marca las tres variables; sobre el corregido no marca nada.

## 0.26.0

**El `<br>` se veia escrito en las notificaciones.** `_sin_html` limpiaba
negritas y cursivas pero no los saltos de linea, asi que Home Assistant
mostraba la etiqueta como texto. Afectaba a todas las alertas, no solo a
las nuevas.

**Canjes por curva.** Contra que bono conviene rotar cada uno de los que
se tienen. La cuenta no es cual rinde mas, que llevaria siempre al mas
largo y cambiaria la cartera, sino cuanto se espera que recorra cada
punta hasta su propio residuo medio: con el residuo en puntos basicos y
la duration en anios, el precio se mueve MD x (residuo - media) / 100 por
ciento. La ganancia es la diferencia entre las dos puntas menos una
comision de salida y una de entrada.

Tres filtros: misma familia de curva, duration dentro del 35% de la del
bono que se tiene, y la punta de destino barata contra su propia
historia y no solo contra la curva. Sin lo ultimo entrarian los bonos
estructuralmente baratos, que estan baratos todos los dias y no
convergen.

Se ve en un desplegable y avisa en el ciclo cuando aparece uno nuevo,
rearmandose al desaparecer. Umbral en `canje_min_pct`, 1% por defecto.

**Estrategias medidas contra su patron.** Cuanto rindio y cuanto le gano
o le perdio a su vara. El costo sale del PPC de las especies asignadas y
la fecha de referencia del patron es el alta de la estrategia y no la de
la especie: si se roto, la especie nueva tiene fecha reciente pero la
apuesta empezo antes. La medicion va siempre sobre la cartera entera
aunque haya filtros: media estrategia no significa nada.

**Diff de tenencias.** Al cargar se comparan las dos ultimas fotos de
cada broker y quedan movimientos propuestos. Una rotacion solo se propone
si las dos especies estan en el mismo grupo y se movieron en sentido
contrario; el ratio sale de la relacion de nominales, que es exacta y no
necesita precios. El resto queda como aporte o retiro.

No se aplica nada solo: entre dos fotos, dos operaciones sueltas del
mismo dia se ven igual que una rotacion, y esa diferencia la sabe el que
opero. Al confirmar una rotacion, la estrategia pasa de la especie que
sale a la que entra, y si se habia cerrado por quedarse sin tenencia se
reabre. Solo si ese fue el motivo del cierre.

**Una sola lista de posiciones.** El tablero y la tabla mostraban lo
mismo con criterios distintos y podian desincronizarse. Ahora hay una
lista de tarjetas: simbolo y valor arriba, barra del color de su
exposicion, y abajo la estrategia, el broker y el resultado contra el
PPC. Al tocarla se abre el editor.

Orden por chips: valor, resultado, especie o estrategia, invirtiendo al
tocar el mismo. La cantidad, el PPC y el alta se ven al abrir cada
posicion. Las posiciones sin precio ya no desaparecen de la vista. Con el
total tapado, toda la pantalla muestra pesos en vez de montos.

## 0.25.0

**Estrategias.** Tabla `estrategia` con nombre, familia, tesis, origen,
patron, objetivo, stop, fecha de revision y un `grupo_id` opcional que la
ata a un grupo de rotacion en lugar de duplicarlo. No guarda cantidades:
esas salen de la tenencia y se actualizan solas.

Seis familias: rotacion, intradiaria, tecnica, opciones, reserva de valor
y oportunidad cambiaria. Las dos ultimas exigen declarar contra que se
miden y se rechazan sin patron. Un activo que sube 40% en pesos con el
dolar 60% arriba es una estrategia que fallo, y sin patron eso se lee
como ganancia.

**Una especie de un broker pertenece a una sola estrategia.** Es la clave
primaria de `estrategia_especie`, asi que reasignar pisa la anterior en
vez de dejarla en dos lados.

**Asignacion automatica desde los grupos.** Un boton crea una estrategia
de rotacion por grupo y le asigna sus tickers en todos los brokers donde
esten. Nunca pisa una asignacion hecha a mano.

**Asignacion manual** desde el editor de tenencia, con un selector al
final del formulario.

**Cierre automatico.** Al cargar tenencias, una estrategia cuyas especies
quedaron todas en cero se cierra sola. Una recien creada, sin especies
asignadas todavia, no se toca.

**Filtro por estrategia** como tercera fila de chips, con las familias en
uso y "Sin asignar". Filtra la tabla y el tablero de valuacion a la vez,
asi que se ve que parte de la cartera esta sin justificar. La tabla suma
una columna con la estrategia de cada posicion.

**`estrategia_id` en las alertas de precio y de fecha.** Con estrategia
son de vigilancia, sin ella de busqueda: es toda la diferencia, no hacen
falta tablas nuevas. Las columnas quedan cargadas; la pantalla de alertas
todavia no las usa.

**El tablero de valuacion pasa abajo de los filtros** y responde a los
tres: el total, los pesos y la barra de exposicion se recalculan sobre lo
que se esta mirando.

## 0.24.3

**El efectivo salia negativo con dinero en la cuenta.** Se tomaba el
campo `disponible` de la cuenta, que netea lo comprometido de una compra
sin liquidar contra el saldo inmediato: con 24.405,92 en el dia y
6.064.407,55 comprometidos por una compra que se paga con una venta del
mismo dia, daba -6.040.001,63.

Ahora se suman los disponibles de `saldos`, plazo por plazo, que para ese
mismo caso da los 24.897,33 que muestra IOL. El desglose aparece en el
aviso cuando hay mas de un plazo, asi que se ve de donde sale el numero.
Si la respuesta no trae el desglose se cae al campo anterior.

**El saldo negativo ya no se descarta.** La version anterior lo dejaba
afuera de la tenencia para que el Rulo no calculara una cantidad maxima
negativa. Con el campo correcto no deberia aparecer nunca, y si aparece
conviene verlo: se carga igual y el aviso pide revisarlo.

**Estado de cuenta crudo en Explorar.** Un boton que devuelve la
respuesta de cada cuenta configurada sin interpretarla. El registro de
llamadas guarda ruta, estado y demora, pero nunca el cuerpo, asi que
hasta ahora no habia donde mirar cuando un saldo no cerraba.

## 0.24.2

**Efectivo negativo.** Una cuenta en descubierto entraba como tenencia
de moneda con cantidad negativa, y de ahi salia una cantidad maxima
negativa en el Rulo. El saldo se informa al traer y no se guarda: la
deuda es real, pero no es algo con lo que se pueda arrancar un circuito.

**El total de la cartera arranca tapado.** Se destapa con un boton. El
porcentaje de resultado se muestra igual, porque no dice cuanto hay, y
con el total oculto cada posicion figura por su peso en vez de por su
monto.

**La lista muestra tres posiciones.** El boton abre el resto.

**"Dolar" pasa a "Hard dollar"** en la barra de exposicion.

**Edicion de una tenencia.** Al tocar una fila se despliega el editor:
cantidad, tipo, PPC, base del PPC, fecha de alta y precision. Guarda solo
esa posicion, sin reemplazar el broker entero, que era la unica forma de
corregir un dato hasta ahora. Tambien permite borrarla.

## 0.24.1

**Segunda cuenta de IOL.** `iol2_user`, `iol2_pass` y `broker2_nombre`,
los tres opcionales y fuera del respaldo. El cliente se crea solo si hay
credenciales y se usa unicamente para bajar la tenencia cuando se aprieta
el boton: no entra en el ciclo ni pide precios, porque los datos de
mercado son los mismos y serian llamadas de mas.

El endpoint recorre las cuentas y guarda cada una por separado, asi que
si una falla la otra se carga igual y el error se informa aparte. Cada
cuenta reemplaza solo su propio broker.

**Cartera valuada.** Modulo `cartera.py` y endpoint `/api/cartera`.
Valua a precio de mercado usando lo que ya esta en cache, sin disparar
requests: lo que falte se lista aparte y no entra en el total.

Arriba el total, el equivalente en dolares al MEP y el resultado contra
el PPC. El resultado dice sobre que porcion de la cartera se midio:
mezclar posiciones con costo cargado y sin el daria un porcentaje que no
significa nada.

Abajo una barra apilada por moneda de rendimiento y la lista de
posiciones ordenada por valor, cada una con su peso y su resultado. La
barra agrupa por donde rinde el bono y no por donde cotiza, asi que un
hard dollar que cotiza en pesos cuenta como dolar.

**`ppc_base` en la tenencia.** El PPC de una planilla suele venir por
unidad y el mercado cotiza por cada 100: sin declararlo, el resultado de
los titulos de deuda salia cien veces mal. Si no se carga, se asume la
misma base que el precio.

## 0.24.0

**Costo de entrada en la tenencia.** La tabla suma `ppc`, `fecha_alta` y
`precision`. Ningun broker devuelve el PPC por API: se carga pegando el
JSON, con los mismos campos que ya se usaban para la cantidad. La fecha
admite tres grados de certeza —`exacta`, `mes` o `antes`— para no dar
por firme algo que se recuerda a medias.

El PPC y la fecha se conservan cuando la carga nueva no los trae. El
boton que baja de IOL devuelve solo cantidades, y sin esto borraba el
costo cargado a mano en cada actualizacion.

**Historial de cantidades.** Cada actualizacion guarda una foto en
`tenencia_hist`, y solo si algo cambio: actualizar tres veces en un dia
sin operar no deja tres filas iguales. La foto se toma por broker y
solamente de los brokers que vinieron en la carga, asi que una carga
parcial no se lee como si se hubiera vendido todo lo que falta.

Se ve por especie, con la diferencia contra la foto anterior del mismo
broker.

**Splits y canjes.** Tabla `evento_societario` con especie, fecha y
factor: un split de 1 a 10 va con factor 10. El broker ajusta la
cantidad pero no siempre el PPC, y entonces el resultado sale al reves.
MIRG figuraba con PPC 9609,87 contra un precio de 1795 y una perdida del
81% que en realidad era una ganancia del 87%.

El ajuste se aplica al leer y no al guardar, para que el valor original
del broker no se pierda si el evento se carga mal. Solo alcanza a las
compras anteriores al evento. Si la tenencia no tiene fecha de alta no
hay forma de saber de que lado cae, asi que se ajusta igual pero la
columna lo marca con un signo de pregunta.

## 0.23.6

**El grafico historico de un bono en pesos salia vacio.** `reconstruir`
solo dejaba pasar las especies en dolares y las CER, porque un hard
dollar que cotiza en pesos necesita el MEP de cada dia y no lo tenemos
hacia atras. Un bono que rinde en pesos no necesita MEP, asi que ahora
entra igual y se le calcula la serie.

**La BADLAR historica se baja antes de reconstruir.** Sin eso solo habia
tasa de los ultimos dias y la serie salia igual de corta. Se pide desde
la emision del bono, no desde 1999, para no traer veinte años al pedo.

**`asegurar_rango` pedia rangos que terminaban en el futuro**, porque
cortaba los tramos al 31 de diciembre del año en curso. El BCRA responde
500 con cuerpo vacio ante eso. Ahora el tope es la fecha de hoy.

## 0.23.5

**Filtro por tipo "Tasa $"**, para los bonos en pesos a tasa variable.
Es lo que correspondia: en 0.23.3 se habia agregado un simbolo `$` al
lado de la TIR en vez del filtro.

**PR17 mostraba un desvio de curva absurdo.** `_familia` agrupaba por la
moneda de cotizacion, no por la moneda en que rinde el bono, asi que un
bono en pesos caia junto a los hard dollar que cotizan en pesos: se
comparaba una TIR en pesos contra una curva en dolares y el residuo daba
miles de puntos basicos. Los bonos en pesos van ahora a su propia
familia, y mientras sean menos de cinco no se les calcula desvio, que es
lo correcto cuando no hay curva contra la cual medirlos.

## 0.23.4

**Las pruebas del BCRA se mudan a Explorar.** Estaban escondidas en el
menu de tres puntos, que es donde uno no las busca cuando algo falla.
Ahora hay tres botones juntos -CER, A3500 y BADLAR- arriba del registro
de llamadas, que es lo que se mira para diagnosticar.

**El error de BADLAR no decia que rango se pidio.** Guardaba la URL base
pero no el desde/hasta, asi que un HTTP 500 no se podia reproducir con
curl. Ahora el mensaje trae el rango completo y hasta 200 caracteres del
cuerpo, o la marca de que vino vacio.

## 0.23.3

**El Rulo estaba caido.** `pct_circuito` usaba una constante
`FACTOR_ARANCEL` que nunca se habia definido: cualquier evaluacion de
circuito moria con NameError. Queda cargada con la fraccion de arancel
que sobrevive a la bonificacion en cada esquema: IOL paga entero porque
en un rulo las cuatro patas son simbolos distintos, Eco bonifica el lado
menor de cada par y Veta no tiene arancel marginal. Sobre cuatro patas da
2,04%, 1,04% y 0,04%.

**Los pagos del 31 se corrian al 30 y no volvian.** `fechas_interes`
encadenaba las fechas sumando meses sobre la anterior, y como sumar seis
meses a un 31 de diciembre da 30 de junio, el dia 31 se perdia para
siempre. Ahora se cuenta desde el primer pago, como ya hacia la
amortizacion. Afectaba a MR43O, CLSIO y PARP, y adelantaba un dia la
alarma de cobro.

**Step-up de MR43O, otra vez.** Los tramos arrancaban en el pago anterior
para compensar el bug de fechas, con lo cual el cupon de diciembre de
2026 cobraba 8,5% cuando le corresponde 7%. Ahora las fechas de corte son
las del calendario: 7% hasta el cupon del 31/12/2026, 8,5% para los
abonados entre 2027 y 2029, y 9,5% desde 2030.

**Cupon variable.** El motor solo sabia de tasas fijas. Se agrega
`badlar.py`, que cachea la serie 7 del BCRA igual que el CER y reusa su
calendario de feriados para el rezago de diez habiles. Un bono con
`interes.variable` toma la BADLAR de la fecha de valuacion, ya rezagada,
y la proyecta constante hasta el vencimiento: asi un punto historico no
cambia cuando el BCRA publica tasas nuevas. La tasa usada se guarda en
`bono_hist` para que el numero sea reproducible.

**Base actual/365**, que faltaba junto a 30/360 y actual/360.

**`nominal_base` fuera de los CER.** Estaba confinado a la rama del
coeficiente, asi que una lamina que no arranca de 100 solo funcionaba si
ademas ajustaba por CER.

**TIR en pesos.** Todos los bonos en pesos cargados hasta ahora ajustaban
por CER o por A3500, y los que no, pasaban por el MEP: correcto para un
hard dollar que cotiza en pesos, sin sentido para un bono que paga en
pesos. Ahora hay una rama propia y el campo `tir_moneda` para
distinguirlas; en la tabla las TIR en pesos llevan un `$`.

**PR17.** Bocon de la decima serie, trece cuotas trimestrales de capital
-doce del 7,69% y la ultima del 7,72%- los 2 de febrero, mayo, agosto y
noviembre, que devenga BADLAR de bancos privados sin spread sobre base
actual/365. El capital de origen es 833,20 por cada 100 nominales: sale
de 705,05, que es lo que quedaba vivo tras las cuotas de mayo y agosto de
2026, dividido por el 84,62% que restaba amortizar.

**Un bono sin tasa ya no devenga cero.** Si el BCRA no responde, la tasa
variable quedaba en None, el flujo caia a la lista vacia de tramos y la
TIR salia calculada sobre cupones de 0%: un numero creible y falso. Ahora
se marca `falta_tasa` y no se publica TIR, igual que con `falta_cer`.
Ademas el detalle de un bono resolvia la tasa por separado del flujo, asi
que podia mostrar el corrido con una BADLAR y el flujo con otra si la
descarga caia entre medio.

**El filtro activo no se veia en Tenencias.** Los chips se pintaban con
`class="activo"`, que no tiene ninguna regla CSS: el filtro se aplicaba
bien pero nada indicaba cual estaba puesto. Pasan a `aria-pressed`, que
es lo que usa Bonos, y quedan rotulados "Broker" y "Tipo". El mismo bug
estaba en el rango de Proximos cobros.

## 0.22.2

**Las opciones se bajaban dos veces por ciclo.** El instrumento
"opciones" ya venia en la bajada de orleans y el modulo pedia ademas el
panel viejo "De Acciones": dos requests para lo mismo. Ahora reusa lo que
el ciclo ya trajo, y el parametro opc_panel deja de existir.

**Las obligaciones negociables entran a la bajada.** Estaban cargadas en
el cronograma pero el instrumento no se pedia, asi que quedaban sin
precio y no aparecian en la tabla. Van en la lista por defecto, aunque
en una instalacion existente hay que agregarlas a mano porque Home
Assistant conserva la configuracion guardada.

**Step-up completo de MR43O**: 7% hasta los cupones de 2026, 8,5% para
los de 2027 a 2029 y 9,5% desde 2030 hasta el vencimiento. La tasa es la
del cupon que se paga y no la del periodo en que se devenga, asi que cada
tramo arranca en el pago anterior.

**Titulos de deuda del Banco Nacion**: NZC2O al 5,50% con vencimiento
11/05/2029 y NZC5O al 6,00% al 14/07/2029, ambos bullet y semestrales.

**Limpieza.** Trece funciones sin uso: los metodos de instrumentos y
paneles del cliente de IOL, la bajada de paneles vieja del monitor, tres
de costos que quedaron al elegir otro enfoque para la bonificacion,
cuatro de la base y el proximo pago de renta fija.

## 0.22.1

**La serie del A3500 se busca por nombre.** El numero de variable del
BCRA estaba puesto a mano y era el equivocado: devolvia el limite
superior de la banda cambiaria en vez del mayorista de referencia, y con
eso la TIR de un dolar linked salia cuatro veces mas alta. Ahora se pide
el catalogo y se busca la serie cuya descripcion dice mayorista y 3500,
asi que si el BCRA reordena las variables se vuelve a encontrar sola. El
menu muestra las series de tipo de cambio con su valor actual para poder
confirmarla o elegir otra.

Al fijar la serie por primera vez, o al cambiarla, se descarta lo bajado
antes: la tabla se indexa por fecha, asi que valores de dos series
distintas quedarian mezclados sin que se note.

**Las obligaciones negociables entran a la tabla.** DNC3O de Edenor,
DEC2O de Edesa, CLSIO de CLISA y MR43O de Generacion Mediterranea, con
sus cupones y amortizaciones. Van en emisor corporativo, que es una
categoria nueva: cinco ON rindiendo 30% dentro de la curva soberana la
deformarian entera, igual que pasaba con PBA28.

CLI1O queda fuera a proposito. Es un titulo contingente cuyos pagos
dependen del EBITDA de CLISA y de una decision del directorio, asi que no
tiene cronograma: figura en tenencias pero sin calendario ni TIR, porque
cualquier flujo que se le cargara seria inventado.

MR43O y CLSIO quedan marcadas para verificar. A la primera le falta el
anio de cada salto del step-up: cargada con 7% para todo el plazo, los
cobros del proximo anio salen bien y la TIR queda mal desde 2028.

## 0.22.1

**La serie del A3500 se busca por nombre.** Estaba fija en un numero que
no pude confirmar, y era el equivocado: devolvia el limite superior de la
banda cambiaria en vez del mayorista de referencia, con lo que la TIR de
un dolar linked salia muy alta. Ahora se pide el catalogo del BCRA y se
busca la serie que dice "mayorista" y "3500" en la descripcion, asi que
si el BCRA reordena las series se vuelve a encontrar sola.

El menu muestra el catalogo con el valor actual de cada serie y deja
confirmar o elegir otra. Al fijarla, o al detectarla por primera vez, se
descarta lo que se hubiera bajado antes: la tabla se indexa por fecha, y
valores de dos series distintas conviviendo dan un resultado que no es
ninguna de las dos.

**Cuatro obligaciones negociables cargadas**: Edenor Clase 3, Edesa Clase
2, CLISA garantizada y Generacion Mediterranea Clase 43, esta ultima
dolar linked. Van en emisor corporativo, que es una categoria nueva con
su filtro: cinco ON rindiendo 30% deformarian la curva soberana.

CLI1O queda deliberadamente afuera. Es un titulo contingente cuyos pagos
dependen del EBITDA de CLISA y de una decision del directorio: no tiene
cronograma, y cualquier flujo que se le cargara seria inventado. Sigue en
tenencias, sin calendario ni TIR.

MR43O quedo con el cupon del primer tramo para todo el plazo, porque el
escalonamiento posterior a 2027 no esta confirmado. Los cobros del
proximo anio son correctos; la TIR queda mal desde 2028. Esta marcado en
el archivo.

## 0.22.0

**Calendario de cobros.** En Tenencias, agrupado por mes y con el total
de cada moneda. Los cronogramas ya estaban cargados para calcular TIR;
solo faltaba multiplicarlos por lo que hay en cada cuenta. Los importes
ajustables van marcados como estimados, porque se liquidan con el
coeficiente del dia de pago, que todavia no existe.

**Aviso antes de cada pago**, dos dias por defecto y configurable. No
depende de puntas ni de que haya rueda: sale del cronograma y de la
tenencia. El aviso queda guardado en la base, asi que reiniciar no lo
repite.

**Bonos dolar linked.** Estan denominados en dolares pero cotizan y pagan
en pesos al tipo de cambio mayorista A3500, asi que sin esa serie no se
podia calcular ni el valor tecnico ni la TIR. Se baja del BCRA con la
misma mecanica que el CER: por tramos, con reintentos y enfriamiento tras
un fallo.

Van en familia propia: un dolar linked paga al oficial y un hard dollar
al MEP, asi que aunque las dos TIR esten en dolares no se comparan y no
comparten curva.

**D30S6 cargado**: LELINK cero cupon, un solo pago del 100% del nominal
el 30 de septiembre de 2026.

El numero de serie del A3500 en la API del BCRA no lo pude confirmar
contra la documentacion, asi que quedo en 4 y hay una opcion en el menu
para probar ese numero u otro y ver que valor devuelve.

**Alarma por fecha.** Recordatorios sueltos con titulo, fecha, dias de
anticipacion y una nota. Avisan una vez; cambiar la fecha los rehabilita,
que es lo que se quiere al patear una revision.

## 0.21.7

**El Rulo no calculaba nada.** Al sacar el editor de "que tengo" se borro
la lista de nombres de monedas, pero quedo una funcion usandola para
armar cada circuito. Reventaba al dibujar la primera tarjeta, y por eso
el encabezado aparecia y el listado no. La verificacion de sintaxis no lo
detecta: un identificador borrado pasa el chequeo y falla recien al
ejecutarse.

**Tarjetas fantasma en Ratios.** El panel se indexa por alias y ahora se
guarda entre reinicios, asi que al renombrar los pares en la migracion
los alias viejos quedaron adentro para siempre y seguian dibujando una
tarjeta sin posicion. Se poda el snapshot al guardarlo y al cargarlo,
dejando solo los alias vigentes.

**El backfill de cierres llega hasta ayer.** Pedia hasta hoy, asi que en
cada arranque gastaba una llamada por ticker preguntando por el dia en
curso: un dato que el cierre diario guarda igual al terminar la rueda, o
que todavia no existe. Con diez tickers eran diez llamadas por reinicio.

**El respaldo deja de reponer pares y paneles.** Los pares viven en la
base desde la version anterior y los paneles ya no se usan, asi que
reponerlos solo dejaba un aviso en el log en cada arranque.

## 0.21.6

**DIP0 y PAP0 estaban escritos con la letra O.** Son las especies en
dolares del Discount y del Par en pesos, y terminan en cero. Con la O no
las encontraba ningun instrumento y aparecian en "Sin cotizacion", que es
justamente el aviso que se habia agregado en la version anterior.

Su serie historica quedo guardada bajo el nombre viejo, asi que arrancan
sin historia hasta que se recalcule por especie.

## 0.21.5

**El par y el grupo son la misma cosa.** Un par se configuraba en el
add-on y un grupo se creaba en la app, pero sobre los mismos dos tickers
eran dos vistas de la misma estrategia: el ratio por un lado y la
posicion por el otro, en dos tarjetas separadas. Ahora es una sola, con
el ratio, la banda de zona, en que ticker se esta parado y el rendimiento
de la rotacion.

Los pares pasan a vivir en la base y se crean y editan desde la app, con
numerador, denominador, soporte, resistencia y alertas. La lista `pares`
de la configuracion queda solo para la migracion inicial y la app ya
arranca sin ella.

**La migracion corre una sola vez y no duplica.** Si ya existia un grupo
con los mismos dos tickers, se le completan los datos del par en vez de
crear uno nuevo: el grupo trae los movimientos y perderlos seria caro.
Los pares que no tenian grupo se crean.

El respaldo incluye ahora los datos del par, asi que sobreviven a una
reinstalacion. Paso a version 2 y sigue leyendo los de version 1.

**Explorar mira la misma fuente que el ciclo.** El selector ofrece los
diez instrumentos de orleans, el panel pasa a ser un filtro de Operables
o Todos, y el resumen suma fecha, lote y descripcion, que es lo que
permite ver por que una especie se descarta por antiguedad. De paso
desaparecen dos llamadas: las listas de instrumentos y paneles ya no se
piden, son fijas.

**Los botones del registro pliegan.** Tocar el mismo de nuevo cierra el
listado, que tapaba el resto de la pestania y no habia forma de sacarlo.

## 0.21.4

**Orleans reemplaza a los paneles.** Un request por instrumento, con
puntas, y cubre mas especies que los cinco paneles juntos. Antes eran
esos cinco mas un pedido suelto por cada especie que no estuviera en
ninguno: los BONCER, LOMA, HARG, y los CEDEARs pedidos en T0 y T1 por
separado, cuarenta veces por dia cada uno.

Ahora se bajan seis instrumentos por ciclo: titulos publicos, letras,
acciones, cedears, opciones y cauciones. La lista es configurable.

Como no queda pedido suelto de respaldo, lo que no aparezca se avisa en
el encabezado de Ratios, separando dos casos: un instrumento que fallo al
bajar y un simbolo configurado que no aparecio en ninguno.

**Se descartan las especies que no operan.** La API deja pasar cosas
muertas aunque se le pida Operables: una letra de Neuquen vencida en
abril seguia figurando. Se descartan por fecha de ultima operacion, con
un umbral configurable de dias habiles.

**La cauci0n sale del mercado.** El endpoint la trae en vivo con sus
puntas, asi que la tasa colocadora ya no es un numero fijo de la
configuracion: se toma la punta compradora del dia. Si no hay dato en
vivo se usa la configurada, y la pantalla de Pases dice cual esta usando.

**El boton de copiar no copiaba.** Buscaba el bloque de texto adentro del
contenedor de los botones, pero es hermano de ese contenedor. Ademas
ahora prueba primero el portapapeles moderno y cae al metodo viejo, que
por Ingress no siempre hay contexto seguro.

## 0.21.3

**Los tipos de IOL no se traducian.** La tabla de traduccion usaba los
nombres que devuelve el conector MCP, pero la API cruda los escribe
distinto: "TIT. PUBLICOS", "TitulosPublicos" y "titulos publicos" son el
mismo tipo. Todo caia en Otros, y un bono en Otros no entra al Rulo.
Ahora se compara sin puntos, espacios ni acentos, buscando la raiz
adentro del texto. El boton avisa que simbolos quedaron sin clasificar,
para no tener que descubrirlo mirando la tabla.

**El boton trae tambien el efectivo.** El portafolio devuelve solo
titulos; el disponible por moneda sale de estadocuenta. Los pesos de la
cuenta argentina se cargan como ARS, los dolares de esa misma cuenta como
MEP, y los de la cuenta de Estados Unidos como cable, que es donde
liquida cada uno. Se toma el disponible total de la cuenta y no el del
plazo inmediato: lo que liquida en 24 o 48 horas igual se puede operar.
Los saldos en cero se omiten.

Con esto ya no queda nada por cargar a mano de IOL.

**FCI pasa a ser un tipo propio**, con su filtro en el tablero, en vez de
caer en Otros.

**Boton para copiar la respuesta cruda** en Explorar, en la ruta manual y
en la muestra del panel. Copia el JSON entero y no lo que se ve, porque
el bloque viene recortado en alto y seleccionarlo a mano en el telefono
es imposible.

## 0.21.2

**Traer la tenencia de IOL por API.** Boton en la pestania Tenencias que
baja las posiciones de la cuenta configurada, traduce los tipos de IOL a
los de la app y pisa solo ese broker: la cuenta del exterior y las
cargadas a mano quedan intactas. El nombre sale de `broker_propio`, con
IOL-ALE por defecto.

IOL no informa el efectivo disponible, asi que los pesos y dolares hay
que seguir agregandolos a mano con tipo moneda. El boton lo avisa, porque
sin eso el Rulo no sabe con que se cuenta para partir desde una moneda.

**La curva del grafico ya no contradice a la tabla.** El grafico ajustaba
una recta lineal sobre la duration y el desvio del backend una recta
sobre su logaritmo: eran dos curvas distintas, asi que un bono podia
salir verde en el grafico y con desvio negativo en la tabla. Ahora las
dos usan el mismo ajuste, y la curva se dibuja por tramos en vez de como
una recta, que es lo que dejaba el tramo corto siempre por debajo.

**Se nombran los mas despegados.** Antes aparecian los nombres solo si
habia catorce bonos o menos, asi que con la tabla completa no se veia
ninguno. Ahora se etiquetan los dos de arriba y los dos de abajo de cada
familia.

**El grafico agrupa por familia, no por moneda.** Ahora que la curva
separa por emisor, el grafico respeta lo mismo: un provincial ya no se
ajusta junto a los nacionales.

## 0.21.1

**Tenencias pasa a ser un tablero.** Pestania propia, con filtros por
broker y por tipo y ordenamiento por cualquier columna. El JSON acepta
ahora un campo `tipo`: moneda, bonos, letras, bcra, on, cedears, acciones
u otros.

Con el tipo cargado, el Rulo toma solo bonos con cronograma: una accion o
un CEDEAR no tiene especie D ni C, asi que no puede cruzar de moneda y
solo ensuciaba el universo de circuitos.

**Posicion se mudo a Ratios**, debajo del panel de pares. Tenerla junto a
las tenencias confundia dos cosas distintas: una es el seguimiento de la
estrategia de ratios y la otra es que hay en cada cuenta.

**La curva se ajusta por emisor.** Un provincial rinde por encima de la
curva nacional por su propio riesgo de credito, y mezclarlos hacia dos
danios a la vez: el provincial se mostraba barato cuando solo reflejaba
su spread, y de paso empujaba la curva dejando a los nacionales caros.
PBA28 queda en su propia familia y, al ser el unico, sin desvio hasta que
haya mas de su clase. Hay un filtro de emisor en la tabla, que arranca
mostrando todos.

Despues de actualizar conviene correr "Recalcular desvios": los z-score
guardados se calcularon con PBA28 dentro de la curva nacional.

**La pestania Plazos pasa a llamarse Pases.** Y en Ratios el calculador
va arriba.

## 0.21.0

**Alertas de precio.** Pestania nueva. Una alerta es un titulo, un modo y
una o mas condiciones de tres datos: simbolo, operacion y precio limite.
Comprar mira la punta vendedora y vender la compradora, que es contra la
que se ejecuta, asi que no hace falta aclarar el sentido: vender a 89 se
cumple cuando la punta compradora llega a 89.

Con modo "todas" sirve para armar un cambio entre dos titulos: vender
TZXM9 arriba de 89 y comprar DICP abajo de 47.000, avisando solo cuando
las dos se dan a la vez. Con modo "alguna" y dos condiciones sobre el
mismo simbolo queda una alerta de rango, sin necesidad de un tipo aparte.

Cada alerta se pausa, se modifica y se elimina. La pantalla muestra el
precio actual de cada condicion y cuales se cumplen. Avisa al cruzar, no
mientras se mantiene, y no dispara con puntas de antes del cierre. Los
simbolos de las alertas activas entran solos al ciclo.

**Tenencias, con pestania propia.** Titulo, cantidad, broker y tipo,
cargados pegando JSON. Con "reemplazar" en "todo" se pisa la lista
entera; con el nombre de un broker, solo esa cuenta, que es lo habitual
porque se mira un broker por vez. La pantalla filtra por broker y por
tipo y ordena por cualquier columna.

Reemplazan al "tengo" del Rulo, y solo entran los bonos con cronograma
cargado y de brokers locales: una accion o un CEDEAR no tiene especie D
ni C, asi que no puede cruzar de moneda, y un titulo en una cuenta del
exterior no liquida contra el mercado local. Los brokers extranjeros y
las monedas del Rulo pasan a la configuracion.

Por eso el Rulo pierde los botones de monedas y bonos: mantener dos
lugares para declarar lo mismo era pedir que se desincronizaran.

**La curva se ajusta por emisor.** Un provincial rinde por encima de la
curva nacional por su propio riesgo de credito, y mezclarlos hacia dos
danios a la vez: el provincial se mostraba barato cuando solo reflejaba
su spread, y de paso empujaba la curva dejando a los nacionales caros.
PBA28 queda en su propia familia y, al ser el unico, sin desvio hasta que
haya mas de su clase. Hay un filtro de emisor en la tabla, que arranca
mostrando todos.

Despues de actualizar conviene correr "Recalcular desvios": los z-score
guardados se calcularon con PBA28 dentro de la curva nacional.

**Posicion se mudo a Ratios**, debajo del panel de pares, que es donde
tiene sentido leerla. En Ratios el calculador va arriba. Y la pestania
Plazos pasa a llamarse Pases.

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
