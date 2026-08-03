"""Fake CATLINK device for testing the server without hardware.

It replays the device->server frames captured in ``dump.txt`` against a
running server and prints whatever the server sends back, so you can watch the
dashboard react.  Point it at a running ``python -m catlink_local``::

    python -m catlink_local.simulator --dump ../catlink/dump.txt
    python -m catlink_local.simulator --feed          # loop status + ask to feed

It is also handy as a smoke test of the protocol + server end to end.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import time
from pathlib import Path

from .protocol import (
    CMD_STATUS,
    CMD_TIME,
    MSG_QUERY,
    SUB_FEEDER,
    Frame,
    build_frame,
    build_payload,
    iter_frames,
)

# The device's own status frame (from the capture), value byte at body[3].
_STATUS_BODY = bytes.fromhex("000214000000000001000100000208000a0c000a010050")
_MAC = bytes.fromhex("ac0bfbdeff0b")


def _captured_device_frames(dump: Path) -> list[bytes]:
    """Extract just the device->server frames from a capture file."""
    frames: list[bytes] = []
    lines = dump.read_text().splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if not re.fullmatch(r"[0-9a-f]+", s) or len(s) < 16:
            continue
        # A line is device->server if the preceding annotated line says so.
        ctx = " ".join(lines[max(0, i - 1) : i + 1])
        if "C→S" in ctx or "C->S" in ctx:
            buf = bytearray.fromhex(s)
            for f in iter_frames(buf):
                if f.mac == _MAC:
                    frames.append(f.encode())
    return frames


async def _read_replies(reader: asyncio.StreamReader) -> None:
    buf = bytearray()
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            return
        buf.extend(chunk)
        for f in iter_frames(buf):
            print(f"  server -> {f!r}")


def _status_frame(value: int) -> bytes:
    body = bytearray(_STATUS_BODY)
    body[3] = value & 0xFF
    payload = build_payload(0x03, 0x01, CMD_STATUS, bytes(body))
    return build_frame(_MAC, payload, seq=b"\x27\x00")


def _time_query() -> bytes:
    return build_frame(_MAC, build_payload(MSG_QUERY, SUB_FEEDER, CMD_TIME, b"\x00\x00"),
                       seq=b"\x98\x0b")


async def run(host: str, port: int, dump: Path | None, feed_loop: bool) -> None:
    reader, writer = await asyncio.open_connection(host, port)
    print(f"connected to {host}:{port} as device {':'.join(f'{b:02x}' for b in _MAC)}")
    asyncio.create_task(_read_replies(reader))

    async def send(raw: bytes, note: str = "") -> None:
        f, _ = Frame.parse(raw)
        print(f"device -> {f!r} {note}")
        writer.write(raw)
        await writer.drain()

    if dump is not None:
        for raw in _captured_device_frames(dump):
            await send(raw, "(replayed)")
            await asyncio.sleep(0.4)

    if feed_loop:
        await send(_time_query(), "(time?)")
        value = 0
        while True:
            await send(_status_frame(value), "(status)")
            value = (value + 3) % 0x40
            await asyncio.sleep(2)

    await asyncio.sleep(1)
    writer.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8992)
    ap.add_argument("--dump", type=Path, default=None, help="capture file to replay")
    ap.add_argument("--feed", action="store_true", help="loop status frames forever")
    args = ap.parse_args()
    try:
        asyncio.run(run(args.host, args.port, args.dump, args.feed))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
