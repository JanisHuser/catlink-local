"""Run the local CATLINK server + dashboard.

    python -m catlink_local                          # local, device :8992
    python -m catlink_local --proxy                  # proxy feeder to the cloud
    python -m catlink_local --endpoint 8992 --endpoint 9992   # feeder + scooper
    python -m catlink_local --endpoint 9992:devices.catlinks.cn:9992

Each device type uses its own endpoint (the feeder on 8992, the scooper on
9992), so you can listen on several ports at once and forward each to its own
upstream. In local mode, --port may be given several times.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from . import devices  # noqa: F401  registers built-in device handlers
from .dashboard import start_dashboard
from .dashboard.webserver import DEFAULT_PORT as WEB_DEFAULT_PORT
from .hub import Hub
from .proxy import CLOUD, Endpoint, start_proxy_endpoints
from .server import DEFAULT_PORT, start_server


async def _run(
    host: str,
    listen_ports: list[int],
    endpoints: list[Endpoint] | None,
    web_port: int,
    capture: str | None,
    capture_dir: Path | None,
    resolver: str,
    mqtt: dict | None,
) -> None:
    hub = Hub(capture_dir=capture_dir)
    if capture:
        hub.open_capture(open(capture, "a", buffering=1))
        print(f"  capturing ALL traffic -> {capture}")
    if capture_dir is not None:
        print(f"  auto-logging device traffic -> {capture_dir.resolve()}/(unknown|traffic|unhandled)-<ip>.txt")

    servers = []
    if endpoints is not None:
        servers = await start_proxy_endpoints(hub, endpoints, host, resolver)
        mode = "PROXY  " + "  ".join(
            f":{e.listen_port}->{e.upstream_host}:{e.upstream_port}" for e in endpoints
        )
        dev_ports = [e.listen_port for e in endpoints]
    else:
        for p in listen_ports:
            servers.append(await start_server(hub, host, p))
        mode = "LOCAL (cloud replaced)"
        dev_ports = listen_ports

    web = await start_dashboard(hub, host, web_port)
    if mqtt is not None:
        from .ha_mqtt import MqttBridge

        bridge = MqttBridge(hub, **mqtt)
        await bridge.start()
        print(f"  MQTT discovery -> {mqtt['host']}:{mqtt['port']} (Home Assistant entities)")

    print(f"\n  CATLINK Local is running  [{mode}]")
    print(f"    device  -> {host} ports {dev_ports}   (point the device's DNS here)")
    print(f"    browser -> http://localhost:{web_port}\n")
    try:
        await asyncio.gather(
            *(s.serve_forever() for s in servers), web.serve_forever()
        )
    finally:
        for s in servers:
            s.close()
        web.close()
        hub.close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="catlink_local", description=__doc__)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument(
        "--port", type=int, action="append", metavar="PORT",
        help="local-mode device port (repeatable; default 8992)",
    )
    ap.add_argument("--web-port", type=int, default=WEB_DEFAULT_PORT, help="dashboard port")
    ap.add_argument("--capture", metavar="FILE", help="append ALL traffic to FILE (dump.txt format)")
    ap.add_argument(
        "--capture-dir", metavar="DIR", default="captures",
        help="per-device capture folder: unknown-/traffic-/unhandled-<ip>.txt (default: ./captures)",
    )
    ap.add_argument(
        "--no-capture-unknown", action="store_true",
        help="disable automatic per-IP logging of unknown devices",
    )
    ap.add_argument(
        "--proxy", nargs="?", const=f"{CLOUD[0]}:{CLOUD[1]}", metavar="HOST[:PORT]",
        help=f"proxy a single endpoint to the cloud (default {CLOUD[0]}:{CLOUD[1]})",
    )
    ap.add_argument(
        "--endpoint", action="append", metavar="LISTEN[:UPHOST[:UPPORT]]",
        help="proxy endpoint, repeatable, e.g. 8992  or  9992:devices.catlinks.cn:9992",
    )
    ap.add_argument(
        "--resolver", default="1.1.1.1",
        help="clean DNS server used to resolve upstream hostnames (default 1.1.1.1)",
    )
    ap.add_argument("--mqtt", action="store_true", help="publish devices to Home Assistant via MQTT discovery")
    ap.add_argument("--mqtt-host", default="core-mosquitto", help="MQTT broker host")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--mqtt-user", default="")
    ap.add_argument("--mqtt-pass", default="")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    capture_dir = None if args.no_capture_unknown else Path(args.capture_dir)
    listen_ports = args.port or [DEFAULT_PORT]

    endpoints: list[Endpoint] | None = None
    if args.endpoint:
        endpoints = [Endpoint.parse(spec) for spec in args.endpoint]
    elif args.proxy:
        h, _, p = args.proxy.partition(":")
        # keep the listen port(s) from --port (default 8992), forward to the cloud
        up_port = int(p) if p else CLOUD[1]
        endpoints = [Endpoint(lp, h, up_port) for lp in listen_ports]

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
            _run(
                args.host, listen_ports, endpoints, args.web_port,
                args.capture, capture_dir, args.resolver, mqtt,
            )
        )
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
