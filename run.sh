#!/usr/bin/with-contenv bashio
# Start the *.catlinks.cn DNS redirect + the CATLINK server (proxy + MQTT).
set -e

MODE=$(bashio::config 'mode')
CLOUD_IP=$(bashio::config 'cloud_ip')
CLOUD_PORT=$(bashio::config 'cloud_port')
DEVICE_PORT=$(bashio::config 'device_port')
DNS_PORT=$(bashio::config 'dns_port')
DNS_UPSTREAM=$(bashio::config 'dns_upstream')
REDIRECT_IP=$(bashio::config 'redirect_ip')

# Where devices should be sent for *.catlinks.cn: this HA box.  Auto-detect the
# LAN IP if not pinned in the options.
if bashio::var.is_empty "${REDIRECT_IP}"; then
  REDIRECT_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
fi
bashio::log.info "Redirecting *.catlinks.cn -> ${REDIRECT_IP} (device port ${DEVICE_PORT})"

# MQTT: use the Mosquitto add-on service if present, else the options.
if bashio::services.available "mqtt"; then
  MQTT_HOST=$(bashio::services "mqtt" "host")
  MQTT_PORT=$(bashio::services "mqtt" "port")
  MQTT_USER=$(bashio::services "mqtt" "username")
  MQTT_PASS=$(bashio::services "mqtt" "password")
else
  MQTT_HOST=$(bashio::config 'mqtt_host')
  MQTT_PORT=$(bashio::config 'mqtt_port')
  MQTT_USER=$(bashio::config 'mqtt_user')
  MQTT_PASS=$(bashio::config 'mqtt_pass')
fi
# On host networking the internal "core-mosquitto" name isn't resolvable; fall
# back to the host itself, where the Mosquitto add-on maps port 1883.
if [ "${MQTT_HOST}" = "core-mosquitto" ]; then
  MQTT_HOST="127.0.0.1"
fi
bashio::log.info "MQTT broker: ${MQTT_HOST}:${MQTT_PORT}"

# Build the dnsmasq config: redirect each configured domain, forward the rest.
DNSMASQ_CONF=/tmp/dnsmasq.conf
{
  echo "port=${DNS_PORT}"
  echo "no-resolv"
  echo "server=${DNS_UPSTREAM}"
  echo "cache-size=200"
  echo "log-queries"
  for d in $(bashio::config 'catlink_domains'); do
    echo "address=/${d}/${REDIRECT_IP}"
    bashio::log.info "  intercepting *.${d}"
  done
} > "${DNSMASQ_CONF}"

dnsmasq --keep-in-foreground --conf-file="${DNSMASQ_CONF}" &

PROXY_ARGS=""
if [ "${MODE}" = "proxy" ]; then
  PROXY_ARGS="--proxy ${CLOUD_IP}:${CLOUD_PORT}"
  bashio::log.info "Proxy mode: forwarding to cloud ${CLOUD_IP}:${CLOUD_PORT} (app keeps working)"
else
  bashio::log.info "Local mode: cloud replaced (app will not work)"
fi

exec python3 -m catlink_local \
  ${PROXY_ARGS} \
  --host 0.0.0.0 \
  --port "${DEVICE_PORT}" \
  --mqtt \
  --mqtt-host "${MQTT_HOST}" --mqtt-port "${MQTT_PORT}" \
  --mqtt-user "${MQTT_USER}" --mqtt-pass "${MQTT_PASS}" \
  --capture-dir /share/catlink-captures
