# CATLINK Local — Home Assistant add-on

Runs the CATLINK local server **and** a DNS redirect in one add-on, and exposes
your devices to Home Assistant as native entities over MQTT. In the default
**proxy** mode the official CATLINK app keeps working — HA just rides along.

## What you get

- A **DNS server** that intercepts `*.catlinks.cn` and points your devices at
  this HA box (nothing else is affected).
- A **proxy** that forwards each device to the real CATLINK cloud, so the app
  keeps working, while decoding the traffic.
- **HA entities** (auto-discovered via MQTT):
  - `sensor.food_in_bowl` (grams)
  - `binary_sensor.feeding`
  - `sensor.last_feed_portions`
  - `number.feed_portions` + `button.feed_now`
  - Unknown devices show up as a diagnostic sensor while you reverse-engineer them.

## Prerequisites

1. **Mosquitto broker** add-on installed and started (Settings → Add-ons).
2. The **MQTT integration** configured in HA (it's auto-suggested once Mosquitto
   is running).

## Install

1. Settings → Add-ons → Add-on Store → **⋮ → Repositories**, add
   `https://github.com/JanisHuser/catlink-local`.
2. Find **CATLINK Local** in the store and **Install**.
3. Start it. Check the **Log** tab — it prints the redirect IP and the
   intercepted domains.

## Point your devices' DNS here

The add-on only *serves* DNS; your devices still have to *use* it. Easiest and
most future-proof: set your **router's DHCP DNS server** to this HA box's IP.
Every device (feeder, litter box, future ones) is then handled automatically.
Prefer not to touch the whole network? Set the DNS server on each CATLINK device
individually (in your router's client settings) to the HA IP.

## Options

| Option | Default | Meaning |
|--------|---------|---------|
| `mode` | `proxy` | `proxy` (app keeps working) or `local` (fully offline, app stops working). |
| `cloud_ip` / `cloud_port` | `47.90.202.93` / `8992` | Real CATLINK cloud to proxy to. Must be an **IP** (avoids a DNS loop). |
| `device_port` | `8992` | Port devices connect on. |
| `dns_port` | `53` | DNS listen port. |
| `dns_upstream` | `1.1.1.1` | Where non-CATLINK lookups are forwarded. |
| `catlink_domains` | `[catlinks.cn]` | Domains to intercept (subdomains included). |
| `redirect_ip` | *(auto)* | The IP devices are redirected to. Auto-detected; pin it if detection is wrong. |
| `mqtt_*` | *(from Mosquitto)* | Overrides if you don't use the Mosquitto add-on. |

## Captures

Traffic from **unrecognised** devices is written to
`/share/catlink-captures/unknown-<ip>.txt` (in the same format as the original
`dump.txt`). That's what you use to build a handler for a new device — e.g. the
litter box. Grab it via the Samba share.

## Troubleshooting

- **Add-on won't start / port 53 in use.** Something else on the host owns DNS.
  Change `dns_port` (e.g. `5353`) and point your router there, or stop the other
  DNS service.
- **No entities in HA.** Confirm the Mosquitto add-on is running and the MQTT
  integration is set up. The add-on log shows `MQTT connected`.
- **App stopped working.** Make sure `mode` is `proxy`, and `cloud_ip` is the
  real cloud IP (not a hostname that resolves back through this DNS).
- **Wrong redirect IP.** Set `redirect_ip` to this HA box's LAN IP explicitly.
- **Multiple devices share one capture file.** They'd only collide if they share
  a source IP; with host networking each device's real IP is used.
