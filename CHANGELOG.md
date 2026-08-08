# Changelog

## 0.3.0

- Capture **unhandled frames from recognised devices**. Previously only
  fully-unidentified devices were logged; commands a handler doesn't decode yet
  (new firmware messages, or not-yet-implemented features like the scooper's
  `28ff` grid report) were silently dropped. They're now written to
  `/share/catlink-captures/unhandled-<device_type>-<ip>.txt` in both proxy and
  local modes.

## 0.2.0

- Support multiple devices/endpoints (feeder on 8992, scooper on 9992).
- Scooper (litter box) support: temperature/humidity, keepalive reply, HA sensors.

## 0.1.1

- Initial Home Assistant add-on: local DNS redirect + cloud proxy for CATLINK
  devices, exposed to Home Assistant over MQTT, with a dashboard and automatic
  per-IP capture of unidentified devices.
