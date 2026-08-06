# Ratios IOL — add-on para Home Assistant

Monitorea ratios de precios entre especies de IOL, avisa por Telegram cuando
tocan tus niveles, y te da un screener web dentro de Home Assistant.

Solo lee datos. No ejecuta órdenes.

---

## Instalar

**1. Subí este repo a GitHub** (privado está bien).

**2. Agregalo en Home Assistant:**
Ajustes → Complementos → Tienda de complementos → menú ⋮ (arriba a la derecha)
→ Repositorios → pegá la URL de tu repo → Agregar.

**3. Instalá "Ratios IOL"** desde la tienda. La primera compilación tarda unos
minutos porque arma la imagen Docker en tu equipo.

**4. Cargá la configuración** (pestaña Configuración del add-on) y arrancalo.

**5. Activá "Mostrar en la barra lateral"** para tener el screener a un toque.

---

## Configuración

| Opción | Qué es |
|---|---|
| `iol_user` / `iol_pass` | Credenciales de InvertirOnline. Quedan en el almacén del add-on, no en el repo. |
| `telegram_token` | Token que te da @BotFather al crear el bot. |
| `telegram_chat_id` | Tu chat ID. Escribile algo al bot y abrí `https://api.telegram.org/bot<TOKEN>/getUpdates` para verlo. |
| `poll_seconds` | Cada cuánto consulta durante la rueda. 180 es un buen punto de partida. |
| `market_open` / `market_close` | Fuera de ese rango consulta cada 10 min, para no gastar llamadas. |
| `alert_cooldown_minutes` | Tiempo mínimo entre dos avisos del mismo par en la misma zona. Evita el spam cuando un ratio queda pegado al nivel. |
| `confirm_readings` | Lecturas seguidas en zona antes de avisar. En 2 filtra los picos de un solo tick. |

### Pares

```yaml
pares:
  - alias: "ALUA/TXAR"
    num: "ALUA"          # numerador
    den: "TXAR"          # denominador
    mercado: "bCBA"
    plazo: "t2"
    resistencia: 1.54    # 0 = sin nivel
    soporte: 1.36        # 0 = sin nivel
    alertas: true
```

El ratio es **num / den**.

- **Con niveles cargados** → la alerta salta al cruzar resistencia o soporte.
- **Sin niveles** (ambos en 0) → cae al z-score, y solo avisa si hay al menos
  25 días de histórico. Sirve para pares nuevos hasta que definas los tuyos
  mirando el gráfico.
- `alertas: false` → lo ves en el screener pero nunca te escribe.

---

## El screener

Tres pestañas:

**Panel.** Cada par con su ratio actual y una banda donde el soporte y la
resistencia son marcas fijas y la aguja es el precio de ahora. De un vistazo ves
si está cerca del borde. Los botones abren el gráfico de 90 días o el de hoy.

**Calcular.** Dos tickers cualquiera y te da el ratio al toque, con su media,
rango y gráfico. La primera consulta de un símbolo nuevo descarga el histórico y
lo guarda, así que la segunda vez es instantánea.

**Alertas.** Las últimas 40 que se dispararon.

---

## Datos

Todo va a SQLite en `/data/ratios.db`, que Home Assistant conserva entre
reinicios y actualizaciones.

- **`lecturas`** — cada ciclo guarda ratio y ambas puntas. Se purgan a los 400 días.
- **`cierres`** — cierres diarios por símbolo. No se borran nunca.
- **`alertas`** — historial de disparos.

El histórico se descarga una sola vez por símbolo; después solo agrega los días
nuevos. Una rueda entera de 5 pares son unas 800 filas: con 120 GB de disco no
es un tema.

Las puntas se guardan desde el primer día aunque todavía no se usen. Cuando
quieras armar el detector de rulos vas a tener meses de book acumulado en vez de
empezar de cero.

---

## Antes de confiar en los números

**Verificá el delay.** Comparé nada contra la API real — no tengo acceso a
internet desde donde escribí esto. Abrí el panel al lado de la pantalla de IOL y
fijate que los precios coincidan y con cuánto retraso. Para arbitrajes eso
define si el sistema te sirve.

**Revisá el parseo.** La forma de la respuesta de IOL varía entre instrumentos.
Si un par muestra precio 0 o el gráfico sale vacío, mirá los logs del add-on:
ahí queda el error concreto.

**GD30/AL30 tiene banda angosta.** 1,00–1,03 es 3%, mucho más estrecho que los
otros pares. Si te satura, subí `confirm_readings` a 3 antes de mover el nivel.

---

## Roadmap

1. ✅ Ratios, alertas, screener
2. Publicar los ratios como sensores de HA, para usar automatizaciones nativas
3. Detector de ciclos (rulo) sobre puntas, con costos por pata
4. Estrategias con opciones

El paso 3 necesita book completo y cálculo de comisiones; la base de datos ya
está guardando lo que hace falta.
