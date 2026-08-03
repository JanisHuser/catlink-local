ARG BUILD_FROM
FROM ${BUILD_FROM}

# dnsmasq for the *.catlinks.cn redirect; python + paho for the server + MQTT.
RUN apk add --no-cache dnsmasq python3 py3-pip

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# The server package (run as `python -m catlink_local` from /opt/catlink).
COPY catlink_local /opt/catlink/catlink_local
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/catlink
CMD [ "/run.sh" ]
