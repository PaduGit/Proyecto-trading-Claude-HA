# Monitor de ratios — InvertirOnline

Calcula el ratio de precios entre pares de tickers usando la API de IOL, y lo
compara contra su propia historia (media, rango y z-score de los últimos 90 días)
para saber si el ratio está caro o barato.

Solo lee datos. No ejecuta órdenes.

---

## Instalación

```bash
pip install -r requirements.txt
```

## Configurar los pares

Editá la lista `PARES` arriba de `ratio_monitor.py`. Formato:

```python
PARES = [
    ("bCBA", "GD30", "bCBA", "GD30D", "MEP GD30"),
    ("bCBA", "AL30", "bCBA", "AL30D", "MEP AL30"),
    ("bCBA", "GGAL", "bCBA", "YPFD",  "GGAL vs YPFD"),
]
```

Cada tupla es: `(mercado_A, ticker_A, mercado_B, ticker_B, alias)`.
El ratio se calcula como **precio_A / precio_B**.

Mercados válidos en IOL: `bCBA`, `nYSE`, `nASDAQ`, `aMEX`, `bCS`, `rOFX`.

## Uso

```bash
# Una lectura
python ratio_monitor.py

# Modo continuo (refresca cada 60s)
python ratio_monitor.py --watch
```

Te pide usuario y contraseña de IOL por consola. Las credenciales viven solo en
memoria: el password se descarta apenas se obtiene el token.

Alternativamente, para evitar tipear en el celular, podés exportarlas antes:

```bash
export IOL_USER="tu_usuario"
export IOL_PASS="tu_password"
python ratio_monitor.py
```

⚠️ Si usás variables de entorno, no las pongas en ningún archivo versionado.
El `.gitignore` ya bloquea `.env`, pero la responsabilidad es tuya.

## Parámetros ajustables

En el encabezado del script:

| Variable              | Default | Qué hace                                      |
|-----------------------|---------|-----------------------------------------------|
| `HISTORIAL_DIAS`      | 90      | Ventana para calcular media y desvío          |
| `INTERVALO_SEGUNDOS`  | 60      | Frecuencia de refresco en `--watch`           |
| `UMBRAL_Z`            | 1.5     | Z-score a partir del cual dispara alerta      |

## Cómo leer la salida

```
  MEP GD30
    GD30: 78.450,00   GD30D: 54,80
    Ratio actual: 1431.5693
    Media 90d: 1385.2041  (rango 1290.1122 – 1502.8871, n=61)
    Z-score: +0.87
    ⚪ Dentro del rango normal
```

- **Z-score positivo alto** → el numerador está caro contra el denominador
  respecto de su historia reciente.
- **Z-score negativo alto** → está barato.
- **n** es la cantidad de días con datos en ambas series.

El z-score asume que el ratio revierte a su media, lo cual **no siempre es
cierto**: un ratio puede estar "caro" y seguir subiendo por meses si cambió algo
estructural. Tomalo como contexto, no como señal de entrada.

## Uso desde el celular

Subí este repo a GitHub (privado) y desde la app de Claude:

- **Pestaña Code → New Session** → elegí el repo → pedile que corra el script.
  Corre en la nube, no necesita tu compu prendida.
- **Remote Control** → maneja una sesión que corre en tu propia máquina. Más
  seguro para credenciales, pero la compu tiene que quedar encendida.

Para monitoreo continuo real (alertas 24/7), esto necesita correr en un VPS o
Raspberry con `cron`. Las sesiones de Claude Code son efímeras.

## Limitaciones conocidas

- La API de IOL devuelve precios con delay para algunos instrumentos según tu
  plan de cuenta.
- El histórico usa cierres sin ajustar: splits y dividendos pueden generar
  saltos artificiales en el ratio.
- Fuera del horario de mercado, `ultimoPrecio` es el último cierre.
- El token de IOL dura ~15 min; el script lo renueva solo.
