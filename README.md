# CATLINK Local

A **local, cloud-free** replacement for the CATLINK cloud server, plus a live
web dashboard. Your device connects to this machine (via DNS) instead of
`47.90.202.93:8992`, and everything — status, feeding, time sync — happens on
your LAN. No account, no internet, no third-party dependencies (standard
library only).

Built by reverse-engineering the device ⇄ cloud TCP protocol from a capture
(`../dump.txt`). The framing and checksum are fully understood and verified;
higher-level semantics (feeding, status decoding) are best-effort and clearly
marked in the code.

## Quick start

```bash
cd catlink-local
python3 -m catlink_local
```

```
  CATLINK Local is running
    device  -> tcp://0.0.0.0:8992   (point the device's DNS here)
    browser -> http://localhost:8080
```

Open <http://localhost:8080> for the dashboard.

### Pointing the device here

This machine is already the device's DNS server, so override the CATLINK
server hostname to resolve to this machine's LAN IP. The device keeps using
port **8992**, so the local server listens there by default. No app change or
firmware flash is needed — just DNS.

> The original cloud IP is `47.90.202.93`. Don't let *this* machine's own
> lookups for that hostname resolve to itself, or the server would talk to
> itself. (The capture's `test-server.py` had the same caveat.)

### Options

```bash
python3 -m catlink_local --port 8992 --web-port 8080 --host 0.0.0.0 -v
python3 -m catlink_local --capture all.txt         # log ALL traffic to one file
python3 -m catlink_local --capture-dir logs        # per-IP unknown logs -> logs/
python3 -m catlink_local --no-capture-unknown      # turn auto-capture off
```

### Two modes: replace the cloud, or proxy it

| Mode | Flag | What it does |
|------|------|--------------|
| **Local** (default) | *(none)* | Terminates the connection and answers locally. No cloud, no account, fully offline. The official app won't work. |
| **Proxy** | `--proxy` | Sits between the device and the real CATLINK cloud, forwarding every byte so **the official app keeps working**, while decoding traffic for the dashboard and still allowing local commands (feed) to be injected. |

```bash
python3 -m catlink_local --proxy                    # -> 47.90.202.93:8992
python3 -m catlink_local --proxy 47.90.202.93:8992  # explicit upstream
```

> The upstream must be an **IP** (or resolved by a clean resolver). If the proxy
> resolved the cloud hostname through the same DNS the device uses, it would
> point back at this machine and talk to itself.

Proxy mode is what a Home Assistant deployment should use: HA gets live local
sensors and a feed button, and the vendor app keeps functioning.

### Automatic capture of unknown devices

Point **any** CATLINK device's DNS here and it just works: a device the server
doesn't recognise is handled by a generic fallback that keeps it online and
**auto-logs its traffic to `captures/unknown-<ip>.txt`** (in `dump.txt`
format), differentiated by source IP. The dashboard flags it as
`unidentified`, shows where it's being logged, and lists the subsystem/command
"fingerprint" it has sent.

The dashboard's **Live traffic** panel is deliberately scoped to unidentified
devices only — recognised devices (the feeder) are kept online but their
chatter is hidden, so the log stays focused on what still needs decoding.

That capture is everything needed to write a real handler for it — so bringing
a new device (e.g. the litter box at `.105`) online is:

1. Run the server; point the device's DNS here.
2. Exercise the device; watch `captures/unknown-192.168.178.105.txt` fill up.
3. Turn that capture into a handler (next section).

## Testing without hardware

A built-in simulator replays the real capture (or loops forever) against a
running server, so you can watch the dashboard react:

```bash
python3 -m catlink_local.simulator --dump ../dump.txt   # replay the capture
python3 -m catlink_local.simulator --feed               # stay connected, loop status
```

Run the protocol tests:

```bash
python3 -m pytest            # or: python3 tests/test_protocol.py
```

## Home Assistant

This repo doubles as a **Home Assistant add-on** (for HA OS / Supervised). It
bundles everything into one install:

- a **DNS server** that intercepts `*.catlinks.cn` and points your devices here,
- the **proxy** (so the vendor app keeps working),
- **MQTT discovery** so each device shows up as native HA entities
  (`sensor.food_in_bowl`, `binary_sensor.feeding`, `number.feed_portions`,
  `button.feed_now`).

Copy this folder into HA's `/addons/`, install "CATLINK Local", point your
router's DNS at the HA box, and you're done. Full instructions and options are
in [DOCS.md](DOCS.md). The add-on manifest is `config.yaml` / `build.yaml` /
`Dockerfile` / `run.sh` at the repo root.

Running the MQTT bridge outside the add-on:

```bash
pip install -e ".[mqtt]"
python3 -m catlink_local --proxy --mqtt --mqtt-host <broker>
```

## The protocol (what we learned from the dump)

Every frame on the wire:

```
fc │ len(2, big-endian = total_len − 4) │ seq(2) │ mac(6) │ payload │ xor(1)

payload = msgtype(1) │ subsystem(1) │ command(2) │ body(…)
```

* **checksum** = XOR of every byte except the leading `fc` and the checksum
  itself. (Held for all 74 frames in the capture.)
* **msgtype**: `01` command (server→device) · `02` ack · `03` report
  (device→server) · `04` query (device→server).
* **subsystem**: `01` main/status · `52` feeder.
* **command**: `0352` status · `0452` time-sync · `0552` feed · `0252`
  feed-report.
* **time-sync** body is `00 1a MM DD WD HH MM SS` — `0e 2e 34` decoded to
  14:46:52, matching the capture's own timestamp.
* Keeping the device happy is just: **ACK every report/query** with
  `02 <sub> <cmd> 0000`, and answer time queries with the current time.

## Architecture

```
catlink_local/
  protocol.py        Frame encode/decode + checksum   (fully verified)
  server.py          asyncio TCP server + per-device Session
  registry.py        device-type registry (the extension point)
  hub.py             shared state + pub/sub event bus
  devices/
    base.py          DeviceHandler contract
    feeder.py        reference device: feeder + sub-types + feed command
  dashboard/
    webserver.py     stdlib HTTP + Server-Sent-Events (no deps)
    index.html       single-page live dashboard
  simulator.py       fake device for testing without hardware
```

The protocol server and the web server never import each other — they only
share the `Hub`.

## Adding a new device (this is the point)

Extending is a single file. To add a **device type**:

1. Create `catlink_local/devices/<mydevice>.py`:

   ```python
   from ..registry import register
   from .base import Command, DeviceHandler
   from ..protocol import Frame

   @register
   class LitterBoxHandler(DeviceHandler):
       device_type = "litterbox"
       commands = [Command("clean", "Clean cycle", args={})]

       @classmethod
       def claim(cls, frame: Frame) -> bool:
           return frame.subsystem == 0x53      # whatever identifies it

       def on_frame(self, frame):
           # decode status, then keep the device online
           return [self.ack(frame)]

       def run_command(self, name, args):
           if name == "clean":
               self.send_command(0x53, 0x0153)  # your command bytes
   ```

2. Import it in `catlink_local/devices/__init__.py`.

That's it — the server auto-detects it (first handler whose `claim()` returns
`True` owns the connection) and the dashboard renders its state and command
buttons automatically.

**Sub-types** (e.g. different feeder models) live *inside* a handler: inspect
the incoming frames and set `self.sub_type`. See `feeder.py`'s
`_sub_type_for()`.

## Status of the reverse engineering

| Area | Confidence |
|------|-----------|
| Frame format + checksum | **Verified** against every captured frame |
| Keep-alive (acks) + time-sync | **Verified** — bytes match the cloud's replies |
| Status value decoding | Partial — the changing byte is surfaced; full meaning TBD |
| Feed command (`0552 00NN`) | **Plausible** — matches the observed pattern; test on hardware carefully |

When you run it against the real device, the live traffic view makes it easy
to fill in the gaps.
