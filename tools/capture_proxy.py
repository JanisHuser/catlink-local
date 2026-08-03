"""Logging MITM proxy for reverse-engineering CATLINK devices.

An improved version of the original ``test-server.py``: it forwards every
device on port 8992 to the real cloud (so the device keeps working) and writes
a **separate, timestamped capture file per client IP** in the same format as
``dump.txt``.  Point a new device's DNS here, let it run for a while, and hand
the resulting ``capture-<ip>.txt`` to whoever is writing the device handler.

    python3 tools/capture_proxy.py --out captures/

Then, e.g., the litter box at .105 lands in ``captures/capture-192.168.178.105.txt``.

This is a *reverse-engineering* tool and lives outside the local server on
purpose -- the server itself never talks to the cloud.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

CLOUD = ("47.90.202.93", 8992)  # do NOT let this resolve through your own DNS


class Capture:
    def __init__(self, out_dir: Path, client_ip: str):
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / f"capture-{client_ip}.txt"
        self.fp = self.path.open("a", buffering=1)
        self.fp.write(f"# capture for {client_ip} started {datetime.now().isoformat()}\n\n")

    def log(self, direction: str, data: bytes) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.fp.write(f"[{ts}] {direction} ({len(data)} bytes)\n{data.hex()}\n\n")
        self.fp.flush()


async def _pump(reader, writer, direction, cap: Capture):
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            cap.log(direction, data)
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def _handle(client_reader, client_writer, out_dir: Path):
    peer = client_writer.get_extra_info("peername")
    client_ip = peer[0] if peer else "unknown"
    cap = Capture(out_dir, client_ip)
    print(f"[+] {client_ip} connected -> logging to {cap.path}")
    try:
        server_reader, server_writer = await asyncio.open_connection(*CLOUD)
    except OSError as exc:
        print(f"[!] cannot reach cloud for {client_ip}: {exc}")
        client_writer.close()
        return
    await asyncio.gather(
        _pump(client_reader, server_writer, "C→S", cap),
        _pump(server_reader, client_writer, "S→C", cap),
    )
    print(f"[-] {client_ip} disconnected")


async def main(host: str, port: int, out_dir: Path):
    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, out_dir), host, port
    )
    print(f"capture proxy on {host}:{port} -> cloud {CLOUD[0]}:{CLOUD[1]}")
    print(f"captures -> {out_dir.resolve()}/capture-<client-ip>.txt")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8992)
    ap.add_argument("--out", type=Path, default=Path("captures"))
    args = ap.parse_args()
    try:
        asyncio.run(main(args.host, args.port, args.out))
    except KeyboardInterrupt:
        print("\nbye")
