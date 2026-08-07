ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8 PYTHONUNBUFFERED=1

RUN apk add --no-cache python3 py3-pip tzdata \
    && python3 -m pip install --break-system-packages --no-cache-dir \
       requests==2.32.3 flask==3.0.3 waitress==3.0.0

COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
