ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8 PYTHONUNBUFFERED=1

RUN apk add --no-cache python3 py3-pip py3-cryptography tzdata \
    && python3 -m pip install --break-system-packages --no-cache-dir \
       requests==2.32.3 flask==3.0.3 waitress==3.0.0 pyyaml==6.0.2 \
    && (python3 -m pip install --break-system-packages --no-cache-dir pypdf==5.1.0 \
        || python3 -m pip install --break-system-packages --no-cache-dir "pypdf>=4,<6")

COPY app /app
COPY config.yaml /config.yaml
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
