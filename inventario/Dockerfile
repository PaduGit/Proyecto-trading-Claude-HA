# Sin build.yaml (deprecado). Imagen base multi-arquitectura, versión fija
# igual que Ratios 0.77.0.
ARG BASE_VERSION=3.24
FROM ghcr.io/home-assistant/base:${BASE_VERSION}
LABEL io.hass.type="app" io.hass.arch="aarch64|amd64"

ENV LANG=C.UTF-8 PYTHONUNBUFFERED=1

RUN apk add --no-cache python3 py3-pip tzdata \
    && python3 -m pip install --break-system-packages --no-cache-dir \
       flask==3.0.3 waitress==3.0.0 websocket-client==1.8.0

COPY app /app
COPY config.yaml /config.yaml
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
