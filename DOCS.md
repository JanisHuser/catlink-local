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
| `endpoints` | `8992→…:8992`, `9992→…:9992` | One entry per device type/port, `"LISTEN:UPSTREAM_HOST:UPSTREAM_PORT"`. The feeder uses 8992, the scooper 9992. `UPSTREAM_HOST` may be an IP or a hostname. |
| `resolver` | `1.1.1.1` | Clean DNS used to resolve upstream **hostnames** (bypasses our own redirect so we reach the real cloud). |
| `dns_port` | `53` | DNS listen port. |
| `dns_upstream` | `1.1.1.1` | Where non-CATLINK lookups are forwarded. |
| `catlink_domains` | `[catlinks.cn]` | Domains to intercept (subdomains included). |
| `redirect_ip` | *(auto)* | The IP devices are redirected to. Auto-detected; pin it if detection is wrong. |
| `mqtt_*` | *(from Mosquitto)* | Overrides if you don't use the Mosquitto add-on. |

### Multiple devices and endpoints

Each CATLINK device type connects to a **different endpoint** — the feeder on
port 8992, the self-cleaning litter box ("scooper") on 9992 — so the add-on
listens on all of them at once and forwards each to its own upstream. Add a line
to `endpoints` for any new port.

If a device's real upstream isn't the default cloud IP, use its hostname and let
the resolver find the real address, e.g. `"9992:devices.catlinks.cn:9992"`. The
add-on log (and dnsmasq's query log) shows which `*.catlinks.cn` hostname each
device looks up, so you can see exactly what to put here.

## Captures

Traffic from **unrecognised** devices is written to
`/share/catlink-captures/unknown-<ip>.txt` (in the same format as the original
`dump.txt`). That's what you use to build a handler for a new device — e.g. the
litter box. Grab it via the Samba share.

Recognised devices are captured too. Their **full** conversation — every frame,
both directions, including the commands the app sends (relayed cloud→device) —
goes to `/share/catlink-captures/traffic-<device_type>-<ip>.txt`, so you can see
exactly what a button in the CATLINK app puts on the wire. Separately, any
command the handler doesn't decode yet (new firmware messages, not-yet-
implemented features like the scooper's `28ff` grid report) is also filed to
`/share/catlink-captures/unhandled-<device_type>-<ip>.txt` as a focused list.
Check there when a supported device does something the dashboard doesn't reflect.

## Troubleshooting

- **Add-on won't start / port 53 in use.** Something else on the host owns DNS.
  Change `dns_port` (e.g. `5353`) and point your router there, or stop the other
  DNS service.
- **No entities in HA.** Confirm the Mosquitto add-on is running and the MQTT
  integration is set up. The add-on log shows `MQTT connected`.
- **App stopped working.** Make sure `mode` is `proxy`, and each `endpoints`
  upstream points at the real cloud (an IP, or a hostname the `resolver` can
  resolve — not one that loops back through this DNS).
- **One device works, another doesn't.** It likely uses a different port; add an
  `endpoints` line for it (the scooper is 9992). Check the add-on log for the
  device connecting and which upstream it was sent to.
- **Wrong redirect IP.** Set `redirect_ip` to this HA box's LAN IP explicitly.
- **Multiple devices share one capture file.** They'd only collide if they share
  a source IP; with host networking each device's real IP is used.
