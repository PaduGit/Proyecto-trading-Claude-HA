# Registro de cambios

## 0.46.0

**Campo nuevo: `opc_histeresis_pct`, en 3.** Home Assistant no aplica
valores por defecto sobre una configuracion existente: hay que cargarlo
a mano.

**Las alertas de opciones avisaban de nuevo sin haber salido del
umbral.** Un mismo BEAR_PUT aviso cuatro veces en dos horas al 26%, 24%,
23% y 24%, todos muy por debajo del 33%. El estado de persistencia se
reconstruia **solo con las combinaciones presentes en ese ciclo**: en
opciones una combinacion se queda sin puntas a cada rato y desaparece de
la lista, se caia del diccionario y al ciclo siguiente volvia en blanco
y avisaba como si fuera un cruce nuevo. Subir la persistencia no
alcanzaba: un solo ciclo ausente rearmaba el aviso.

Ahora el estado de las que no vinieron se arrastra -ausente no es lo
mismo que afuera: no suma ciclos, pero tampoco rearma- y se olvida
recien despues de 40 ciclos sin aparecer. Ademas hay histeresis: una vez
avisada, la combinacion no se rearma hasta superar el umbral mas
`opc_histeresis_pct`. Sobre la secuencia real de hoy, de seis avisos
queda uno, y vuelve a avisar cuando de verdad sale y entra.

**Mapa de combinaciones en OPCIONES.** Cada punto es un spread: el eje
vertical es el riesgo -mas arriba es mejor-, el horizontal la base
comprada o cuanto tiene que moverse el papel para empatar. Vertical
punteada en el spot, horizontal ambar en el umbral de alarma. Verde
alcista, rojo bajista. Al tocar un punto se abre su detalle completo.

Tres selectores: vencimiento -uno a la vez, porque superpuestos los
puntos se pisan-, estructura -un alcista y un bajista en la misma base
son apuestas opuestas- y que mostrar en el eje horizontal. La alerta
pasa a ser la entrada a esta pantalla en vez de la pantalla misma.

**La tabla de tenencias muestra y ordena por rendimiento en dolares.**
Va al lado del de pesos, con `~` cuando el PPC en dolares esta estimado,
para que ordenar por esa columna no mezcle medidos con aproximados sin
que se note. Agrupando por especie se pondera como el de pesos: el
resultado del conjunto, no el promedio de los porcentajes.

Dos ordenes nuevos, **Dolares** y **Contra patron**. Lo que no tiene
dato va al fondo en los dos sentidos: una posicion sin PPC en dolares no
es la peor, es una que no se midio.

**Chip de precio viejo** en la fila. La cartera ya sabia que especies no
operan hace dias y las valuaba igual, pero en la tabla se veian como
cualquier otra.

**El desplegable de una posicion, reordenado.** Arriba la descripcion
del ticker. Los pares alineados: precio con PPC, PPC con resultado, PPC
en dolares con el resultado en dolares. La leyenda de cuatro renglones
del PPC estimado se fue: queda el `~` y la explicacion en el `title`.

Y en renta fija, al desplegar: **TIR, dias al vencimiento, vencimiento,
proximo pago, ajuste, valor tecnico y paridad**. Los dias van al lado de
la TIR a proposito: una TIR de -6,65% a ocho dias del vencimiento es
medio punto de precio anualizado por cuarenta y cinco, y sin el plazo no
se compara con una a tres años. Se piden al abrir la fila y solo para
renta fija.

## 0.45.0

**Reserva de valor mide tenencia por tenencia.** La estrategia pasa a ser
una etiqueta que agrupa. Cada especie se mide contra su propio PPC y con
el patron corrido desde **su propia fecha de alta**; el numero de la
estrategia es el promedio ponderado por costo.

Antes se sumaba todo y se comparaba contra un unico factor del patron
medido desde el alta de la estrategia, que se heredaba de la posicion
desde la que se creo. Un bono comprado en 2024 terminaba comparado contra
un dolar medido desde 2026. Y habia dos mediciones que se contradecian:
la tarjeta decia "sin punto de partida" y el chip de la tenencia daba
-23,1%. Ahora las dos hacen la misma cuenta y dan el mismo numero.

La tarjeta muestra una tabla por especie -alta, cuanto rindio, cuanto
hizo el patron y la diferencia-, que es lo que deja ver cual le gana al
patron y cual no. Una especie sin PPC o sin fecha de alta queda afuera
del promedio y se lista con el motivo, y la tarjeta dice sobre que
porcentaje del costo esta midiendo.

Sin ledger no hay punto de partida que reclamar: para esta familia se
van el cartel de "usar la tenencia actual" y los botones Movimientos y
Cargar uno. Evolucion sigue: sale de la foto diaria, no del ledger.

Las otras cuatro familias no cambian. En par y curva la rotacion es el
punto y las cuotapartes existen para eso.

**El patron dolar es el MEP.** Se mide contra el dolar billete, no
contra el mayorista A3500. Un dolar linked ajusta por el A3500: medirlo
contra el A3500 es compararlo con su propio ajuste, y con brecha el
numero daria ganancia mientras en dolares reales se perdio. El A3500 se
queda donde sirve, en el valor tecnico y la TIR. En pantalla dice "Dolar
MEP" para que no haya dudas de cual es.

**DNC3O figuraba dos veces en `bonos.yaml`**, con distinto emisor. YAML
se quedaba con la segunda en silencio. Se saco la primera, que no se
usaba.

## 0.44.0

**El PPC en dolares tambien respeta `ppc_base`.** Era una sola linea:
el costo en pesos se dividia por la base y el costo en dolares no. Un
bono con el PPC por lamina daba un costo en dolares cien veces mas
grande y el resultado se pegaba a -100%. MR43O pasa de -100% a -47,86%.

La base es una sola y describe a los dos PPC. Se arreglo en los tres
lugares donde se rompia: la valuacion de la cartera, el promediado al
confirmar un aporte -que mezclaba un valor por lamina con uno por
unidad- y la importacion de operaciones, que cuando **no** pisa el PPC
en pesos deja la fila con su base vieja y ahora lleva el PPC en dolares
a esa misma unidad en vez de escribirlo por unidad.

**PPC en dolares estimado para las cuentas que se cargan a mano.** Veta
y ECO se cargan pegando JSON: nunca van a tener operaciones de donde
salga el PPC en dolares medido, asi que su resultado en dolares era
siempre un guion. Ahora se estima con el MEP de la **fecha de alta**,
con la tolerancia de siete dias que ya tenia `mep_al`.

Se calcula al vuelo y **no se guarda**: la columna `ppc_usd` sigue
queriendo decir "medido", una aproximacion no queda congelada en la base
y se recalcula sola si se corrige la fecha de alta.

Va marcado con `~` en el PPC y en el resultado, y la tarjeta explica que
sale del MEP del alta y no del de cada compra. Entra al total en
dolares, que ahora cubre mas cartera, y la leyenda dice que porcentaje
del total es estimado. Sin MEP de esa fecha, o sin fecha de alta, queda
en guion: no se inventa.

## 0.43.0

**El PPC tiene en cuenta la moneda de cada compra.** La API de IOL no
devuelve ningun campo de moneda: lo unico que la indica es el simbolo, y
`montoOperado` viene en la moneda de la operacion. Hasta ahora todo se
sumaba como pesos.

Una compra de QQQD por 2.360 dolares entraba al promedio de QQQ -que es
el mismo CEDEAR, y por eso se pliega- junto a importes en pesos. Y
`ppc_usd` era peor: dividia por el MEP un importe que ya estaba en
dolares, y quedaba unas mil cuatrocientas veces mas chico.

La moneda se decide **antes** de plegar el simbolo, porque despues QQQD
y QQQ son indistinguibles. Tres formas, las tres en los datos reales:
sufijo ` US$`, `D` final con la misma guarda que ya existia -solo si lo
que queda tambien aparece, para no inventar monedas como no se inventan
especies- y una lista explicita para los fondos en dolares, que no
tienen ninguna marca: `IOLDOLD` no termina en D.

Una compra en dolares **es** el costo en dolares y alimenta `ppc_usd`
directo; su PPC en pesos se arma multiplicando por el MEP del dia. Si
falta el MEP de ese dia, la posicion queda **sin PPC en pesos** en vez
de con uno armado con la mitad de las compras, y el informe dice
cuantos nominales quedaron afuera. Las compradas en las dos monedas se
marcan.

QQQ pasa de 15.011,80 a 28.570; AO29, de 1.289,68 a 1.375,09.

**El PPC en dolares se puede editar** en el editor de una posicion, al
lado de la base del PPC. Va por unidad, como el de pesos. La columna ya
existia y el backend ya la aceptaba: faltaba el campo en pantalla.

**Operaciones de IOL, por cuenta y en tabla.** Cada cuenta tiene su
boton de copiar -solo su arreglo, sin el envoltorio ni la otra- y un
"Ver como tabla" que alterna con el JSON. Seis columnas: fecha, simbolo,
tipo, cantidad, precio e importe. Son `cantidadOperada`, `precioOperado`
y `montoOperado`, no las de la orden: verlas al lado invita a
confundirlas. Y el importe es donde se lee la moneda de un vistazo.

## 0.42.0

**Las estrategias salen de TENENCIAS y viven en su pestaña.** El
desplegable era un indice y ademas el formulario de alta, y la tarjeta
estaba en dos lugares. Ahora cada familia se dibuja donde se opera: par
en RATIOS, curva y reserva de valor en BONOS, tecnica en ANALISIS
TECNICO y **opciones en OPCIONES**, que hasta ahora no tenia tarjeta.
Cada una con su boton de alta -la familia la define la pestaña, no un
selector- y su **archivo de cerradas**.

El alta y la edicion pasan por un dialogo, asi no dependen de que
pestaña este abierta. Editar, cerrar, reabrir, borrar y evolucion se
agregaron a la tarjeta: es el unico lugar donde vive la posicion.

**El desplegable de pares tambien sale.** Cada par se edita y se borra
desde su tarjeta en RATIOS, que es donde se lo mira. "+ Nuevo par" y
"Crear desde los grupos" quedan en un desplegable de administracion de
esa misma pestaña; "Borrar sin especies" pasa a Explorar. El respaldo
estaba anidado adentro de pares y queda suelto en TENENCIAS.

**Rotacion asistida.** Los canjes de curva y los pares proponian contra
que rotar y se quedaban en el porcentaje. Ahora arman la orden: cuantos
nominales salen, cuantos entran y a que precios.

La cuenta vive en un modulo nuevo, `rotacion`, porque es la misma para
los dos origenes. Se vende al **bid** de la que sale y se compra al
**ask** de la que entra, las dos llevadas a precio por unidad con su
base antes de dividir. La comision de venta se descuenta y **la de
compra se despeja**, porque se paga sobre lo que se compra. Los
nominales se redondean al mas cercano y el resultado trae el **ratio**,
el mismo numero que muestra el panel.

Por defecto rota toda la tenencia de la especie que sale, sumando
brokers y diciendo en cual esta; la cantidad se puede escribir. Si
alguna punta cotiza en dolares, cruza al MEP.

Avisa sin frenar cuando la punta no tiene volumen para ese tamaño,
cuando se rota mas de lo que hay y cuando el instrumento no tiene
comision configurada. Y **no devuelve orden** si no puede saber si una
especie cotiza por lamina o por unidad: adivinar la base es de donde
salieron los errores por 100 de este proyecto.

## 0.41.1

**El reconstructor aplica los eventos societarios.** Las operaciones
anteriores a la fecha del evento se llevan a la escala de hoy:
multiplicar los nominales por el factor y dividir el precio por el mismo
numero deja el importe pagado igual, que es lo correcto, y el PPC sale en
la escala actual.

Sin esto, una posicion con compras de los dos lados de un canje no cerraba
nunca contra la tenencia. Y el cociente entre lo que hay y lo
reconstruido **no es el factor del evento**: es la mezcla de las dos
partes. Veinte compradas antes de un canje de factor 6 -hoy ciento
veinte- mas ochenta despues dan 200 reales y 100 reconstruidas, o sea 2.

Por eso se saca el cartel "parece un ajuste de N a 1", que afirmaba un
factor inventado. Ahora dice "puede faltar un evento societario: la
diferencia es un multiplo limpio", y solo aparece si la especie no tiene
eventos cargados.

## 0.41.0

**Serie del MEP hacia atras.** Sin ella, una compra anterior al inicio
del historico no tiene tipo de cambio y queda sin PPC en dolares.

`reconstruir` saltea a proposito los hard dollar que cotizan en pesos:
la TIR de AL30 necesita el MEP de cada dia, que es justo lo que no hay
hacia atras. Circular, y por eso la serie de AL30 nunca se llenaba. Pero
**para el MEP no hace falta la TIR, solo el precio de las dos puntas**:
`reconstruir_precios` baja el cierre y guarda el precio, con TIR, MD y
residual en blanco.

No pisa nada: con `INSERT OR IGNORE`, el dia que ya tiene punto completo
-AL30D si se reconstruye, porque es en dolares- se respeta. Solo rellena
lo que falta.

**Boton "Serie del MEP"** en Explorar, con el mismo rango de fechas que
las operaciones. Al terminar dice cuantos puntos bajo de cada punta y
desde que fecha se puede medir en dolares: el primer dia con las dos
puntas, y cuantos dias quedaron cubiertos. Si una punta falla, se muestra
aparte en vez de cortar todo.

El orden para usarlo: primero Serie del MEP con el rango largo, despues
Fechas de alta con el mismo rango.

## 0.40.2

**El PPC en dolares estaba atado al de pesos.** Solo se escribia si
ademas se reemplazaba el PPC en pesos, o sea con "pisar" o en una
posicion sin PPC. Con los PPC ya cargados no se escribia nunca. Va
aparte: es una columna nueva y no hay nada cargado a mano que respetar.

**El informe dice por que no hay PPC en dolares.** El reconstructor exige
que todas las compras tengan MEP de su dia; si a alguna le falta no
devuelve nada, en vez de promediar con la mitad. Ahora, al lado del PPC,
va "US$ 110,0000" si se pudo o "sin MEP para 100 nominales" si no, con la
cantidad exacta que quedo afuera. Casi siempre significa que la serie de
AL30/AL30D no llega tan atras como la compra.

## 0.40.1

**El PPC en dolares no se mostraba en ningun lado.** 0.40.0 agrego el
resultado pero no el PPC. Ahora estan los dos, en la ficha de la
posicion.

**Y los campos vacios no se dibujaban.** `dato()` devuelve cadena vacia
cuando el valor es null, asi que una posicion sin `ppc_usd` no mostraba
ninguna de las dos filas y parecia que la funcion no existia. Van siempre,
con un guion cuando no hay dato y una linea que dice de donde sale: de
confirmar un aporte con su precio, o de Fechas de alta. Lo mismo en el
total de la cartera.

## 0.40.0

**Resultado en dolares, al MEP de cada compra.** Un CEDEAR puede hacer
+60% en pesos y 0% en dolares: esa es la pregunta que antes no se podia
contestar. Va en la ficha de cada posicion y en el total de la cartera.

El costo en dolares es una columna propia, `ppc_usd`, y no el PPC en
pesos dividido por el dolar de hoy: cada compra entro a su tipo de cambio
y esa es justamente la diferencia que se quiere medir. Se promedia igual
que el de pesos, pero al MEP del dia de cada compra.

El MEP historico se reconstruye de `bono_hist`: AL30 y AL30D tienen serie
diaria y las dos cotizan por 100, asi que el cociente sale limpio. Si ese
dia no hay dato se busca hasta siete dias atras; mas lejos no, porque un
tipo de cambio de hace dos semanas aplicado a una compra no mide nada.

Se llena por dos caminos: al confirmar un aporte, con el MEP de esa foto,
y desde el reconstructor de operaciones, compra por compra. Si a alguna
compra le falta el MEP de su dia, el reconstructor **no devuelve**
`ppc_usd` en vez de promediar con la mitad: un promedio a medias no es el
costo en dolares. Lo que no se puede medir queda en guion, y el total
dice sobre que porcion de la cartera esta medido.

**Menos solapas.** TENENCIAS pasa a ser la primera. Registro y Explorar
salen de la fila y se abren desde el menu de tres puntos: son de
diagnostico, se usan cuando algo no cierra, y en la fila obligaban a
arrastrar para llegar a lo que si se usa todos los dias. Quedan siete.

La navegacion pasa a una sola funcion, `irA(vista)`, para que tenga o no
boton propio se decida en un solo lugar.

**`mep_al` no puede cortar una confirmacion.** Si la serie no esta, la
tabla todavia no se creo o la fecha viene mal formada, devuelve None y el
resultado en dolares queda en guion. Antes reventaba y se llevaba puesta
la confirmacion del movimiento, que no tiene nada que ver.

## 0.39.0

**El PPC se promedia al confirmar un aporte.** Cuando el diff detecta que
entraron nominales, la propuesta muestra "Precio al que entró", cargado
con el ultimo precio que tenia la app y editable. Al confirmar:

    ppc = (cant_antes × ppc + cant_entra × precio) / (cant_antes + cant_entra)

Las dos puntas se llevan a **por unidad** antes de promediar. El PPC
guardado puede venir por unidad o por lamina y el precio de mercado viene
siempre en la base en la que cotiza: promediar sin igualarlos da un
numero cien veces mas grande o mas chico.

Sirve igual para el broker que no informa el PPC: se pega el JSON con la
cantidad nueva, sale la propuesta, y ahi se pone el precio al que se
compro. Queda una sola puerta para tocar el PPC de una compra, registrada
en el ledger, en vez de una edicion suelta sin rastro. Si el campo queda
vacio, el PPC no se toca. Un retiro tampoco lo toca: vender no cambia lo
que costo lo que queda.

**El precio actual, en la ficha de la posicion**, al lado del PPC. Es lo
unico que permite ver de un vistazo si un resultado raro viene de un PPC
mal cargado o del mercado.

**El reconstructor muestra el PPC tambien en las que no cierran**, como
referencia, para poder compararlo contra el cargado sin guardar nada.

## 0.38.1

**Guardar una posicion de FCI reventaba.** `fci_nombre` quedo en la
lista de campos permitidos de `actualizar_tenencia` pero no en la de los
que se tratan como texto, asi que caia en el `float(v)` del final. Error
introducido en 0.38.0.

## 0.38.0

**Los FCI dejan de estar sin precio.** Existian como tipo de tenencia y
no cotizan en ningun panel: su posicion quedaba fuera del total de la
cartera. Ahora hay dos fuentes.

Los que comercializa IOL salen de `/api/v2/Titulos/FCI`, donde
`ultimoOperado` es el valor de cuotaparte.

Los que no -un fondo de otro broker no aparece en ese listado- salen de
**ArgentinaDatos**, que republica en JSON la planilla diaria de CAFCI,
sin clave. La API propia de CAFCI se discontinuo en abril de 2026 y
devuelve 403.

**El `vcp` de CAFCI viene por mil** y hay que dividirlo. La ficha lo
aclara al lado: "Valor por cada cuotaparte: 1,040522 (Valor por mil:
1.040,522)". Sin eso la posicion se veia mil veces mas grande, con un
numero que no chirria a simple vista. Es el mismo problema de los bonos
que cotizan por 100, con otro factor.

**CAFCI identifica por nombre, no por ticker.** En el editor de una
posicion de tipo `fci` hay un campo "Fondo en CAFCI": se escriben tres
letras, busca, y se elige de la lista. No se escribe a mano a proposito,
porque un fondo tiene clases A, B, C y Ley 27.743 con precios parecidos y
distintos, y elegir mal da un numero creible y equivocado.

**Una llamada por dia.** La cuotaparte se publica una sola vez al dia.
Se cachea con la fecha y solo se consulta CAFCI para lo que IOL no tiene.
El dato viene con un dia de atraso, asi que la cotizacion se marca vieja
con su fecha y la cartera la lista en el aviso de precios viejos.

**Un fondo en dolares se pasa a pesos al MEP.** La cuotaparte de IOLDOLD
esta en 1,09 dolares y `cartera.valuar` suma todo como pesos: sin
convertir, la posicion entera desaparecia del total. La conversion es
solo para fondos a proposito: un AO28D tambien cotiza en dolares, pero
eso viene funcionando asi desde siempre y cambiarlo de paso moveria el
MEP y la valuacion entera sin haberlo verificado.

## 0.37.1

**`AO29D` cuenta como `AO29` al reconstruir.** La tenencia los muestra en
una sola fila y las operaciones vienen con ticker separado: AO29 daba
5.565 contra 5.471, y la diferencia eran exactamente los 94 nominales de
una compra de AO29D. La `D` final no se corta a ciegas: solo cuando lo
que queda tambien aparece en las operaciones o en la tenencia. `BDED` es
un ticker entero y `BDE` no existe. Si la tenencia tiene las dos filas
separadas, se suman para comparar y el alta se escribe en las dos.

**Las monedas quedan fuera del informe.** ARS y MEP no son titulos y
nunca van a tener operaciones.

**Una diferencia que es un multiplo limpio se nombra como tal.** FSLR con
200 contra 100 dice "parece un ajuste de 2 a 1: split o cambio de ratio
del CEDEAR" en vez de "las operaciones dan menos de lo que hay". Se
detectan factores de 2 a 100. No se aplica nada, solo se nombra.

**Se informa la operacion mas vieja que trajo la consulta**, al lado del
conteo. Si es posterior a lo que se pidio, el rango no llego tan atras y
varias de las que no cierran son solo eso.

## 0.37.0

**Fechas de alta y PPC reconstruidos desde las operaciones de IOL.**
Ninguna de las 43 posiciones tenia fecha de alta, y sin ella el ajuste
por evento societario es un supuesto y una reserva de valor no se puede
medir desde el origen. El portafolio da cantidades y nada mas: la fecha
solo esta en las operaciones.

`operaciones.py` recorre las operaciones hacia adelante por simbolo,
llevando la cantidad. El alta es **el ultimo cruce de cero hacia
arriba**: si vendiste todo en 2020 y volviste a comprar en 2024, la
posicion de hoy empezo en 2024. El PPC promedia solo las compras de la
tenencia vigente.

**Primero muestra, despues escribe.** El boton "Fechas de alta" clasifica
en tres: las que cierran -la cantidad reconstruida es la que figura hoy-,
las que no, con las dos cantidades y el motivo, y las que no tienen
operaciones en el rango. Solo se guarda lo que cierra, y recien al
confirmar. Si la cantidad no coincide, la fecha es de otra posicion.

Las dos que se sabe que no van a cerrar: lo que entro por transferencia
desde otro broker no tiene compra, y donde hubo split el broker ajusto la
cantidad pero las operaciones viejas siguen en la escala anterior.

**El PPC de las operaciones va sin comisiones**, asi que por defecto no
pisa el que este cargado a mano. Hay un boton aparte para pisarlo.

Se usan `cantidadOperada`, `precioOperado` y `montoOperado`, nunca
`cantidad`, `precio` ni `monto`: los primeros son lo ejecutado y los
segundos lo que se pidio, que a veces viene en pesos en vez de nominales.
`montoOperado` ya trae la base de cotizacion aplicada, asi que el
cociente contra cantidad por precio la delata sin tener que deducirla del
tipo de tenencia.

## 0.36.1

**Todo lo de la API de IOL quedo junto**, dentro de "Consultar la API de
IOL", con tres bloques: cuenta, instrumentos y ruta manual. En "Probar
las fuentes" quedan solo BCRA y BYMA, que es lo que corresponde: eso
prueba que la fuente responda, no consulta la API.

**Las operaciones aceptan un rango de fechas.** Vacias, los ultimos
noventa dias; con fechas, lo que se pida. Hace falta para las posiciones
viejas: ninguna de las 43 tiene fecha de alta y la mayoria entro antes de
esos noventa dias.

**Dos botones de copiado.** "Copiar todo" deja el JSON entero; "Copiar
resumen" deja cuantas operaciones hay de cada tipo, con que simbolos, y
un ejemplo completo de cada uno. Pegar un año de operaciones desde el
telefono no es viable, y el resumen alcanza para saber que tipos existen
y como viene cada uno.

## 0.36.0

**El ratio del diff iba al reves.** Era nominales que salen por cada uno
que entra, o sea el inverso del ratio del panel: rotar 1.000 AO28 a 1.047
AO29 con el par AO28/AO29 en 1,047 mostraba 0,955 y no habia forma de
comparar los dos numeros de un vistazo. Ahora es cuantos entran por cada
uno que sale, y la propuesta lo dice con los tickers. Solo afecta
propuestas pendientes: el ledger nunca guardo el ratio.

**Descartar para operar dejo de ser descartar para valuar.** Una especie
que no opera hace mas de `dias_sin_operar` se sigue sacando de las
señales -una punta suelta genera rulos falsos y desvios de curva
falsos-, pero ya no se tira: queda aparte, marcada y con la fecha de su
ultima operacion, y se usa para valuar. Antes esas posiciones no
aparecian en la cartera y el total mentia por omision, que es peor que un
precio de hace diez dias. La cartera avisa cuales y de que dia son.

**Boton "Ver operaciones" en Explorar.** Trae los ultimos noventa dias
crudos de las dos cuentas, contra `/api/v2/operaciones`. De ahi tienen
que salir las fechas de alta -ninguna de las 43 posiciones tiene-, el PPC
exacto, las comisiones reales y las rentas duplicadas. Todavia no importa
nada: primero hay que ver que campos devuelve. Armar el importador contra
un formato supuesto es como se metieron las TIR de 152%.

## 0.35.0

**El diff aprendio a leer cantidades negativas.** Miraba la cantidad y
ahora mira la exposicion: 100 lanzadas exponen tanto como 100 compradas,
solo que en contra. Antes, abrir una lanzada iba de 0 a -100 y se leia
como un retiro de 100 nominales que nunca tuviste; cerrarla se leia como
un aporte. Ahora armar un spread sale como aporte en las dos patas, y
desarmarlo como retiro. Cuando el saldo cambia de signo -de comprado a
lanzado- salen dos movimientos, porque son dos cosas distintas: se cerro
lo que habia y se abrio lo contrario. Sirve igual para un saldo en
descubierto.

`mov_propuesto` y `estrategia_mov` suman `signo`: una lanzada es una
obligacion y resta en el equivalente. Un bull spread de 100 GFGC7000 a
400 contra 100 GFGC8000 a 150 vale 5,714 - 2,143 = 3,571 nominales del
base, que son los 25.000 pesos de debito neto. Sumada como comprada, la
posicion se veia 60% mas grande.

**Los lotes de una posicion de opciones salen de la tenencia**, sumando
brokers y dividiendo por 100. Si las dos patas no coinciden toma la menor
y avisa, que es el caso de un cierre parcial. El boton de editar lotes
queda solo cuando el dato no se pudo resolver.

**El riesgo se puede corregir con el neto ejecutado.** IOL no informa el
PPC de las opciones, asi que el riesgo sigue siendo el de las puntas del
dia en que se cargo la posicion. El boton nuevo pregunta en pesos -lo
que pagaste, o lo que cobraste si es de credito- y saca el riesgo por
accion. Donde el PPC si esta cargado a mano, se rehace solo con la misma
formula del screener.

**Grafico de evolucion en la posicion abierta**, con el % sobre el riesgo
y la linea del umbral de alarma. El grafico existia y solo se usaba en el
screener.

**La serie diaria deja de guardar todo el panel.** Con tres vencimientos
y treinta bases son miles de filas por dia. Se guardan las que tenes
abiertas y las que estan en zona de alerta.

**Las alertas de vigilancia se pueden editar.** Al pasar a vigilancia
desaparecian de la pantalla, y los botones de modificar y borrar viven
ahi. Ahora hay un desplegable Vigilancia en ANALISIS TECNICO, con las
mismas filas y a que estrategia vigila cada una. Ademas, abrir el
formulario de una de ellas antes de que cargaran las estrategias y
guardar sin tocar nada la devolvia a busqueda en silencio.

## 0.34.0

**Las alertas se separan en vigilancia y busqueda.** Una alerta sobre
algo que ya tenes se lee adentro de la tarjeta de su estrategia, con el
saldo y el rendimiento al lado: "AO28 a 145.000" no significa nada sin
saber que tenes 7.059 nominales y que la estrategia viene plana. En
ANALISIS TECNICO quedan las de busqueda, que miran lo que todavia no
tenes.

`alerta_precio` y `alerta_fecha` suman `estrategia_id`, con ALTER para
las bases existentes. El documento de continuidad decia que la columna
estaba desde 0.25.0 y no estaba en ningun lado.

**El formulario suma el campo "Vigila"**, con tres opciones: nada, una
estrategia concreta, o deducirlo de los simbolos, que es lo que viene
elegido al crear. La deduccion resuelve solo si todas las especies de la
alerta caen en la misma estrategia; si mira dos distintas queda de
busqueda. Adivinar cual de las dos seria inventar.

## 0.33.1

**El panel arrancaba sin posicion despues de un reinicio fuera de
rueda.** El snapshot de los pares se guarda en la base y se restaura al
arrancar, y el guardado por una version anterior no traia el `id` del
par, que es con lo que la tarjeta encuentra su estrategia. Habia que
esperar al primer ciclo con mercado abierto para ver el bloque de
posicion. Ahora se repone por alias al restaurar, asi que cubre tambien
cualquier campo que se agregue al estado mas adelante.

**El alias `CO` en `monitor.py` era dos modulos distintos**, `costos` en
dos funciones y `cobros` en una tercera. Son imports locales, asi que no
colisionaba, pero alcanzaba con mover uno al encabezado para romper algo
en silencio. Quedan `CO_COSTOS` y `CO_COBROS`.

## 0.33.0

**La posicion pasa a colgar de la estrategia y no del grupo.** El modelo
viejo tenia dos contabilidades que no se hablaban: `tenencia` por un
lado y un ledger por `grupo_id` por el otro, que solo escribia la carga
manual. Una rotacion confirmada nunca llegaba al ledger, asi que la
tarjeta mostraba la tenencia del dia en que se sembro el grupo y no se
movia mas. Ahora las cantidades salen siempre de `tenencia` y el ledger
de la estrategia se lee unicamente para medir.

**Cada familia se mide contra lo que corresponde.** `par` y `curva` en
nominales del ticker base, `reserva_renta_fija` contra el dolar, el CER,
la BADLAR o el S&P, y `tecnica` contra lo que costo. Regla nueva: una
estrategia sin ticker base se mide en pesos. El rendimiento por
cuotaparte no se diluye cuando entra plata nueva, que es justo lo que
hay que ver para juzgar una rotacion.

**La tarjeta vive en la pestaña de su familia.** RATIOS muestra la
posicion adentro de la tarjeta del par, con el ratio arriba y el saldo,
el rendimiento y el ledger abajo. BONOS abre con dos bloques, curva y
reserva de valor; el de curva trae el z de cada especie contra su propia
historia y los canjes que salen de lo que se tiene. ALERTAS pasa a
llamarse ANALISIS TECNICO y abre con las posiciones tecnicas, con su
stop y su objetivo; abajo quedan las alertas de busqueda.

**El sembrado simula antes de escribir.** Muestra a cuantos nominales
del base equivale cada especie con el precio de ahora, editable, y
recien al confirmar escribe. El anterior escribia de una y sin
`ratio_base`, asi que sembraba y la cuotaparte quedaba en cero igual.

**Transferencias entre cuentas.** Mover la misma especie de un broker a
otro salia como un retiro y un aporte sueltos. Ahora se ofrecen para
unir y confirmarlas no escribe ledger: el capital no cambio, cambio de
cuenta.

**Precios del momento de la foto.** El diff guarda el precio de salida,
el de entrada, el del ticker base y cuanto valia la posicion justo
antes. Sin ese ultimo dato el valor de la cuota quedaba clavado en 1 y
el rendimiento salia siempre cero. Confirmar un movimiento de hace tres
dias ya no lo mide con el precio de hoy.

**Bases de cotizacion en el equivalente.** Un bono cotiza por cada 100
nominales y un CEDEAR por unidad. Sin llevar los dos precios a la misma
base el cociente se iba por un factor de 100: un aporte de 100 GGAL a
7.000 contra base AO28 a 62.000 daba 11,29 nominales en vez de 1.129.

**Arreglos que impedian arrancar el modelo nuevo.** `guardar_estrategia`
y `/api/estrategias` leian una clave de `FAMILIAS` que ya no existe y
reventaban con KeyError en toda alta y en todo listado. `ticker_base` no
se escribia en ningun lado. El alta automatica por grupos usaba la
familia `rotacion`, que se elimino. `CREATE TABLE IF NOT EXISTS` no
agrega columnas a una tabla que ya existe, asi que faltaban las cinco
nuevas de `mov_propuesto` y `ticker_base` en `estrategia`.

**Respaldo version 3.** Suma las estrategias con familia, ticker base,
patron, especies y ledger. El grupo se guarda por nombre porque los id
no sobreviven a una reinstalacion. No incluye la tenencia ni el PPC: para
eso, la app deja una copia de `ratios.db` en su carpeta de configuracion
cada vez que arranca, hecha con la API de backup de SQLite.

**Dos cargas del mismo broker dentro del mismo segundo** compartian
timestamp y la segunda pisaba a la primera, dejando una foto mezclada.
Ahora se corre un segundo hasta encontrar uno libre.

**SPY como patron** no tenia rama y devolvia siempre "sin valor del
patron". No hay serie diaria de un CEDEAR: el valor de entrada se carga
a mano y el de hoy sale del precio vigente.

## 0.32.0

**El costo de los canjes entraba 100 veces chico.** `CO.pct()` devuelve
tanto por uno y `curva.canjes()` trabaja en puntos porcentuales, igual
que el recorrido de cada punta. Le llegaba 0,0032 donde iban 0,32: todos
los canjes salian sobreestimados en su propia comision de ida y vuelta y
pasaban el umbral algunos que no cerraban. Se veia en pantalla, el
detalle decia "costo de ida y vuelta 0,003%". De paso ahora recibe
`derechos_mercado` e `iva_pct`, que no le llegaban, asi que el arancel
iba sin el derecho de mercado.

**BADLAR se devengaba como si fuera un indice.** CER y tipo de cambio
son niveles y el rendimiento es el cociente entre el de hoy y el del
alta. BADLAR es una tasa nominal anual publicada dia por dia: el
cociente de dos tasas no dice nada. Con la tasa plana en 30% durante un
anio el patron informaba 0,00% cuando lo devengado son 34,97%. Nueva
`badlar.devengado()`, que capitaliza diario sobre actual/365 arrastrando
la ultima tasa publicada en los dias sin publicacion, como liquida un
plazo fijo. `medir()` pasa a usar `_factor_patron()`, que separa los
patrones de nivel de los de tasa. Sin fecha de alta o sin serie que
cubra el periodo devuelve nota y no un numero. El campo "Valor del
patron" no aplica a BADLAR y el formulario ahora lo aclara.

**`devengado()` no le pega al BCRA en cada request.** `asegurar_rango()`
controla por tramo anual completo, asi que un alta de hace tres meses
nunca llegaba a los 200 dias que espera y bajaba la serie de nuevo cada
vez que se abria la cartera. Ahora compara contra los habiles del
periodo y solo baja si falta: un anio de serie resuelve en 2 ms sin
salir a la red.

**La TIR saturaba en 500% en silencio.** La biseccion se clavaba contra
el techo y devolvia 5.0 exacto, que la tabla mostraba como "TIR 500%"
igual que si fuera una cuenta hecha. Ahora, si al techo el valor
presente sigue por encima del precio, devuelve `None`.

**El devengamiento se corta solo en fecha de cupon.** Antes cada fecha
de la lista movia el ancla, asi que una amortizacion que cayera lejos de
todo cupon dejaba el cupon siguiente devengado desde esa fecha y no
desde el pago anterior: salia cobrado de menos. Ahora el interes se
acumula por subperiodos, sobre el residual que corresponde a cada uno, y
se paga entero en la fecha de cupon. Cuando amortizacion y cupon
coinciden -los 42 bonos cargados hoy- el resultado es identico.

**Filtro de liquidez** (`monto_min_punta`, 300.000 pesos). Una punta de
dos laminas da un precio que no se puede operar y con el una senal que
no existe. `curva.monto_punta()` lleva la punta a pesos: cantidad x
precio / 100, por MEP si es especie D o C. Se aplica en los canjes -bid
del que sale, ask del que entra-, en el aviso de desvio de curva -ask si
esta barato, bid si esta caro- y en los saltos del Rulo. Si falta el MEP
no descarta: no saber cuanto hay no es lo mismo que saber que hay poco.
Cero apaga el filtro.

El ajuste de la curva **no** se filtra. `reconstruir` trabaja sobre
`bono_hist`, que no guarda cantidades, y un filtro que valga hoy y no en
la historia ensucia el z-score, que es justamente lo que decide el
canje. Lo que se filtra es a quien se le avisa, no quien entra al ajuste.

**`circuitos._costo()`** recibia `moneda` y la ignoraba, que es peor que
no tenerla: el dia que un circuito toque acciones el llamador va a creer
que ya estaba contemplado. Se saco, y las sumas `_costo + _costo`
quedaron como `* 2`.

Numeracion de aca en adelante: el segundo numero sube cuando cambian los
numeros que se leen en pantalla o hay que tocar la configuracion; el
tercero, cuando se arregla algo que no cambia ninguna de las dos cosas.

## 0.31.4

**BYMA respondia 200 y el parseo fallaba** con `'list' object has no
attribute 'get'`. Algunos paneles devuelven la lista pelada y otros la
envuelven en `{content, data}`; se aceptan las dos formas, y cualquier
otra cosa se trata como vacia en vez de reventar.

**Un panel roto abortaba los otros cinco.** Se capturaba solo
`BymaError`, asi que un `AttributeError` subia y cortaba el recorrido.
Ahora cada panel falla por su cuenta y el resto se intenta igual.

**El cartel muestra hasta dos errores** en vez de solo el primero, y dice
cuantos mas hubo.

## 0.31.3

**La URL de BYMA iba sucia.** Se le pegaba `?page=1` solo para que el
registro quedara legible, y eso cambia el pedido: Titulos publicos traia
una fila donde debia traer mas de mil. La direccion va limpia y la
etiqueta del registro por separado.

**La paginacion ya no depende solo de `page_count`.** Si ese campo viene
en cero se cortaba en la primera pagina; ahora corta con la primera
pagina vacia.

**Al fallar un panel se muestra la URL** y se aclara que pegada en el
navegador da 405 porque el endpoint es POST.

**Explorar ordenada** en cuatro bloques: consumo, registro de llamadas
—que no tenia ni titulo—, "Probar las fuentes" con BCRA, IOL y BYMA
juntos, y "Consultar la API de IOL" con el bajador de instrumentos y la
ruta manual.

## 0.31.2

**La pestania Tenencias no dibujaba: `pintarSueltos is not defined`.** La
funcion se perdio al reordenar el bloque de estrategias. El AST y
`node --check` no ven esto: el archivo compila igual y revienta cuando
alguien abre esa pantalla.

Se suma al control previo un chequeo de funciones que se llaman y no
estan definidas. Sobre el codigo roto marca `pintarSueltos`; sobre el
corregido, nada.

**Todas las fuentes quedan en el registro** (`red.py`): CER, BADLAR y
A3500 del BCRA, y BYMA. Antes solo se anotaban las de IOL, asi que el
registro mostraba una parte del consumo y no habia forma de saber si la
fuente alternativa siquiera se habia usado.

El resumen las separa por fuente, con llamadas, errores y demora, y
aclara que solo las de IOL consumen su cupo. No toca el contador de
requests de IOL, que es otra tabla.

**"Sin precios" como estado propio.** Con Orleans caido y BYMA fallando,
la fuente quedaba en "IOL" del ciclo anterior y el menu decia que la
fuente andaba cuando no habia ni un precio. Ahora lo dice, y el cartel
trae el error de BYMA.

## 0.31.1

**Si Orleans cae, solo BYMA.** El pedido especie por especie ya no se
dispara solo: consume el cupo de la cuenta que hace el ciclo y para
valuar alcanza con los paneles. Queda en el menu, como "Precios en vivo,
especie por especie", con aviso de que gasta cupo. Es para cuando hay que
operar y los veinte minutos de retraso no sirven.

**Fuente de precios elegible.** `fuente_precios` en la configuracion
—auto, iol o byma— y una entrada en el menu para cambiarla sin
reiniciar. Forzar BYMA cubre el caso que el automatico no ve: Orleans
respondiendo con datos malos en vez de fallar. Reemplaza a `usar_byma`.

**Si los dos fallan, el cartel lo dice**, con el error de BYMA. Antes el
tablero quedaba vacio sin explicar por que.

## 0.31.0

**El panel Orleans devuelve 500 en los siete instrumentos**, con los dos
filtros. La API de IOL esta bien: la cotizacion por especie responde
normal. Lo que sigue es para poder trabajar mientras ese endpoint no
vuelva, y conviene reportarlo igual.

**Open BYMA Data como fuente alternativa** (`byma.py`). Trae paneles
enteros en una llamada, con puntas, volumen y cantidad de ordenes, sin
credenciales y sin gastar cupo de IOL. Entra sola cuando el panel de IOL
falla del todo y se apaga cuando vuelve. Se apaga con `usar_byma`.

Los precios llegan con veinte minutos de retraso, asi que alcanzan para
valuar y para la curva. En Rulo y Pases el ratio que se ve puede no
existir cuando se manda la orden.

**El `settlementType` de BYMA no es el numero de dias.** Verificado
contra IOL: AL30D con `settlementType` 2 coincide en punta compradora,
vendedora, cierre, volumen y hora con el t1 de IOL. Entonces 1 es contado
inmediato y 2 es 24 horas. Con el mapeo al reves, toda la curva se habria
calculado sobre contado inmediato.

Los dos plazos vienen en la misma respuesta, asi que la pantalla de
plazos toma de ahi el t0 en vez de pedirlo por especie.

**Segundo respaldo, especie por especie.** Si BYMA tampoco responde, se
piden las cotizaciones de a una hasta que la API contesta 429, y se
retoma en el ciclo siguiente desde donde quedo: el limite lo pone la API
y no un numero adivinado. Los pares van primero, que no toleran precios
viejos; la cartera despues, rotando.

**Cartel en el encabezado** cuando los precios no son de IOL. Va arriba
de todo y se ve en cualquier pestania.

**`IOLError` lleva el status.** Un 429 y un 500 no se tratan igual: antes
una cotizacion que fallaba se reintentaba por la ruta alternativa, lo que
ante un 429 gastaba otra llamada al pedo.

**API de BYMA en Explorar**, al lado de la de IOL: panel, plazo y especie
opcional, con la lista de campos y las primeras filas crudas.

**Los canjes se muestran sin recalcular.** El ciclo ya los calcula y ya
los avisa: el titulo trae la cantidad y el desplegable aparece abierto si
hay alguno. Recalcular quedo en un boton.

## 0.30.0

**El bloque de crear estrategia se veia siempre.** `.form` declara
`display:grid` y eso pisa el `hidden` del navegador, que solo estaba
forzado para `section`. Ahora vale para todo.

**Al desplegar un titulo se lee, no se edita.** Dos fichas: los datos
—cantidad, PPC, valor, costo, resultado, alta, exposicion— y la
estrategia con su stop, su take profit, contra que rota, el rango, la
revision, como viene contra el patron y la tesis. El formulario aparece
recien al tocar "Editar datos".

"Editar estrategia" lleva al formulario del bloque de estrategias, con
scroll. No se duplica: dos formularios del mismo dato es la trampa de
siempre.

**Estrategias agrupadas por familia.** Con una estrategia por par la
lista se hacia larguisima, y la pregunta de todos los dias es como viene
cada forma de operar y no cada nombre. Cada familia muestra sus
estrategias, sus especies y el resultado del conjunto, y se despliega.

**"Crear desde los grupos" solo arma las de pares que estan en
cartera.** Un par sin ninguna punta se mira desde Ratios, que es donde se
buscan oportunidades; como estrategia no aportaba nada y alargaba la
lista. Se suma un boton para borrar las que quedaron sin especies, que no
toca las cerradas por venta: esas tienen historia.

**El archivo.** Una estrategia cerrada ya no tiene tenencia, asi que el
rendimiento no se puede recalcular y se perdia. Ahora se guarda una
medicion por dia y al cerrar se congela la ultima: queda el rendimiento,
el resultado contra el patron, el valor y los dias que duro. El archivo
va al final de las familias, con cuantas salieron en verde y el promedio.

**Evolucion.** Un boton dibuja la estrategia contra su patron, las dos
como variacion acumulada desde el alta, que es lo unico que las hace
comparables. La serie arranca el dia que se instala esta version.

## 0.29.0

**El stop y el objetivo pasan al titulo.** Estaban en la estrategia, lo
que obligaba a crear una estrategia por accion para poder ponerle su
propio stop, y a completar tres pantallas distintas para la misma
posicion. El stop de MIRG es de MIRG: se carga y se ve en el mismo
desplegable que el PPC.

**Los campos dependen de la familia.** Trading pide stop y take profit;
rotacion, contra que ticker se rota y el rango de ratio; reserva de valor
y oportunidad cambiaria no piden nada propio, porque se miden contra el
patron. La fecha de revision aparece en todas.

**Una estrategia engloba varias posiciones.** Una sola "Trading" cubre
todas las acciones, cada una con su stop. El nombre pasa a ser opcional:
sin nombre se usa el de la familia, asi que crear una es elegir la
familia y guardar.

**Los parametros se ven en la lista** sin abrir nada: bajo el broker
aparece "SL 1600 · TP 2400", o "↔ PARP 1,2–1,8" en rotacion.

**Migracion.** Al arrancar, lo que ya estaba cargado en una estrategia
baja a sus especies y respeta lo que la tenencia ya tenga. Corre una sola
vez.

## 0.28.0

**La pestania empezaba con seis filas de controles.** Antes del primer
dato habia cuatro filas de filtros, una de orden y una de modo: casi una
pantalla de chips en el celular.

Ahora arranca con el total y la barra de exposicion, despues una linea de
filtros que dice lo que hay puesto —"Veta · CER · Trading"— y se abre al
tocarla, y enseguida las estrategias. La lista de posiciones queda abajo.

**La barra de exposicion es el filtro.** Tocar un tramo deja solo esa
exposicion y tocarlo de nuevo la saca; la leyenda hace lo mismo y marca
cual esta activa. Un adorno pasa a ser un control y se ahorra una fila.
Los tramos llevan seis pixeles de ancho minimo: uno del 1% no se veia ni
se podia tocar.

**"Administrar"** junta traer de IOL, cargar pegando JSON, el historial
de cantidades y los splits. Son tareas de mantenimiento y competian por
espacio con lo que se mira todos los dias.

**Proximos cobros** pasa a desplegable.

**Estrategias recuerda si se dejo cerrado**, incluso despues de
recargar. Arranca abierto la primera vez.

**Chips de exposicion con su color**, el mismo de la barra y el de cada
posicion. Los chips de tipo lo llevan solo donde la exposicion es
univoca: un bono puede ser CER, hard dollar, dolar linked o tasa segun
cual sea, y pintarlos todos igual diria algo falso.

**"Tecnica" pasa a llamarse "Trading".** La clave interna no cambia, asi
que lo ya asignado sigue igual.

**El boton "Opere" sale de Ratios.** Registrar una operacion es
seguimiento, no analisis.

**Alta de estrategia desde la tenencia.** El selector del editor suma
"+ Crear una nueva": nombre, familia, patron, take profit, stop loss y
tesis. Se guarda una sola vez y quedan el PPC, la cantidad, la fecha y la
estrategia ya asociada. La estrategia hereda la fecha de alta de la
tenencia y no la de hoy: con la de hoy, el rendimiento contra el CER
daria siempre cero.

**El valor del patron se busca solo** en la fecha de alta, para los
cuatro patrones. El campo queda por si el tipo de cambio al que se entro
no fue el de mercado de ese dia.

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
