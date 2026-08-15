# Changelog

## 0.3.3

- Capture the **full conversation of recognised devices**, both directions, to
  `captures/traffic-<device_type>-<ip>.txt`. Previously only *unidentified*
  devices were logged in full while recognised ones logged just their undecoded
  commands, so **app→device** traffic (a button pressed in the CATLINK app,
  relayed cloud→device) never showed up in the capture folder. The focused
  `unhandled-*` log stays as-is. Also: S→C frames arriving before a device
  identifies itself are no longer dropped from the `--capture` dump.

## 0.3.2

- Decode more previously-unhandled frames captured from real devices:
  - **Feeder** pet-visit event (`0052`): a per-visit report (duration + count,
    units unconfirmed) surfaced as HA diagnostic sensors; acked as before.
  - **Litter box** clock push (`0dff`): local mode now pushes a time-sync on
    first contact and on demand (a new `sync_time` command), matching the cloud.
  - **Litter box** state event (`0b03`): answered with the cloud's verified
    `0bff` reply instead of being dropped.
- Litter box **cat-entry event**: the occupancy flag's rising edge is logged as
  a cat entering, exposing the cat's **weight** and the **entry time** as HA
  sensors (next to temperature and humidity). The weight byte offset is a
  best-effort guess — all-zero in captures so far (no cat was on the scale), so
  verify the value against a live entry; the timestamp is reliable.

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
