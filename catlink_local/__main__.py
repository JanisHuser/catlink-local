"""Run the local CATLINK server + dashboard.

    python -m catlink_local                 # protocol :8992, dashboard :8080
    python -m catlink_local --port 8992 --web-port 8080 --host 0.0.0.0

The protocol server is what the device connects to (point its DNS here); the
dashboard is what you open in a browser.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from . import devices  # noqa: F401  registers built-in device handlers
from .dashboard import start_dashboard
from .hub import Hub
from .proxy import CLOUD, start_proxy
from .server import DEFAULT_PORT, start_server
from .dashboard.webserver import DEFAULT_PORT as WEB_DEFAULT_PORT


async def _run(
    host: str,
    port: int,
    web_port: int,
    capture: str | None,
    capture_dir: Path | None,
    upstream: tuple[str, int] | None,
    mqtt: dict | None,
) -> None:
    hub = Hub(capture_dir=capture_dir)
    if capture:
        hub.open_capture(open(capture, "a", buffering=1))
        print(f"  capturing ALL traffic -> {capture}")
    if capture_dir is not None:
        print(f"  auto-logging unknown devices -> {capture_dir.resolve()}/unknown-<ip>.txt")
    if upstream is not None:
        proto = await start_proxy(hub, upstream, host, port)
        mode = f"PROXY -> {upstream[0]}:{upstream[1]} (app keeps working)"
    else:
        proto = await start_server(hub, host, port)
        mode = "LOCAL (cloud replaced)"
    web = await start_dashboard(hub, host, web_port)
    if mqtt is not None:
        from .ha_mqtt import MqttBridge

        bridge = MqttBridge(hub, **mqtt)
        await bridge.start()
        print(f"  MQTT discovery -> {mqtt['host']}:{mqtt['port']} (Home Assistant entities)")
    print(f"\n  CATLINK Local is running  [{mode}]")
    print(f"    device  -> tcp://{host}:{port}   (point the device's DNS here)")
    print(f"    browser -> http://localhost:{web_port}\n")
    try:
        async with proto, web:
            await asyncio.gather(proto.serve_forever(), web.serve_forever())
    finally:
        hub.close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="catlink_local", description=__doc__)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="device TCP port")
    ap.add_argument("--web-port", type=int, default=WEB_DEFAULT_PORT, help="dashboard port")
    ap.add_argument("--capture", metavar="FILE", help="append ALL traffic to FILE (dump.txt format)")
    ap.add_argument(
        "--capture-dir",
        metavar="DIR",
        default="captures",
        help="per-IP folder for unidentified-device logs (default: ./captures)",
    )
    ap.add_argument(
        "--no-capture-unknown",
        action="store_true",
        help="disable automatic per-IP logging of unknown devices",
    )
    ap.add_argument(
        "--proxy",
        nargs="?",
        const=f"{CLOUD[0]}:{CLOUD[1]}",
        metavar="HOST[:PORT]",
        help="forward to the real CATLINK cloud so the app keeps working "
        f"(default {CLOUD[0]}:{CLOUD[1]}; must be an IP to avoid a DNS loop)",
    )
    ap.add_argument("--mqtt", action="store_true", help="publish devices to Home Assistant via MQTT discovery")
    ap.add_argument("--mqtt-host", default="core-mosquitto", help="MQTT broker host")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--mqtt-user", default="")
    ap.add_argument("--mqtt-pass", default="")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    capture_dir = None if args.no_capture_unknown else Path(args.capture_dir)

    upstream = None
    if args.proxy:
        h, _, p = args.proxy.partition(":")
        upstream = (h, int(p) if p else CLOUD[1])

    mqtt = None
    if args.mqtt:
        mqtt = {
            "host": args.mqtt_host,
            "port": args.mqtt_port,
            "username": args.mqtt_user,
            "password": args.mqtt_pass,
        }

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        asyncio.run(
            _run(args.host, args.port, args.web_port, args.capture, capture_dir, upstream, mqtt)
        )
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
