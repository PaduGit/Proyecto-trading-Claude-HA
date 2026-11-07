# Changelog

## 0.1.0

- Primera versión.
- Lee áreas, pisos, dispositivos, entidades, estados y configuración por la API websocket local.
- Genera el inventario en markdown: por área y dispositivo, sin área, sin registro, automatizaciones y scripts.
- Filtros: diagnóstico, configuración, deshabilitadas u ocultas, y dominios excluidos por opción.
- Botones Copiar (portapapeles con respaldo para Ingress sin HTTPS) y Descargar (blob .md).
- Conexión con token de larga duración y, si falla, con el token del Supervisor.
