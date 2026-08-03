"""Shared runtime state + a tiny pub/sub event bus.

The TCP server writes device state and traffic events here; the dashboard
reads snapshots and subscribes to the live event stream.  Keeping this in one
place means the protocol server and the web server never import each other.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

log = logging.getLogger("catlink.capture")


class DeviceRecord:
    def __init__(self, mac: str, addr: str):
        self.mac = mac
        self.addr = addr
        self.device_type = "unidentified"
        self.sub_type = "unknown"
        self.connected_at = time.time()
        self.last_seen = self.connected_at
        self.packets_in = 0
        self.packets_out = 0
        self.handler: Any = None  # DeviceHandler, set once identified
        self.capture_path: str | None = None  # set while auto-capturing unknowns

    def snapshot(self) -> dict[str, Any]:
        base = {
            "mac": self.mac,
            "addr": self.addr,
            "device_type": self.device_type,
            "sub_type": self.sub_type,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "packets_in": self.packets_in,
            "packets_out": self.packets_out,
            "capture_path": self.capture_path,
            "online": True,
        }
        if self.handler is not None:
            base.update(self.handler.snapshot())
        return base


class Hub:
    def __init__(self, max_log: int = 500, capture_dir: Path | None = None):
        self.devices: dict[str, DeviceRecord] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._log: list[dict[str, Any]] = []
        self._max_log = max_log
        self._capture_fp: TextIO | None = None
        #: When set, traffic from *unidentified* devices is auto-logged here,
        #: one ``unknown-<ip>.txt`` file per source IP.
        self.capture_dir = capture_dir
        self._unknown_fps: dict[str, TextIO] = {}

    # -- raw capture (for reverse engineering new devices) ----------------
    def open_capture(self, fp: TextIO) -> None:
        """Global capture of *all* traffic (the --capture flag)."""
        self._capture_fp = fp

    @staticmethod
    def _frame_block(direction: str, raw: bytes) -> str:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        return f"[{ts}] {direction} ({len(raw)} bytes)\n{raw.hex()}\n\n"

    def write_capture(self, direction: str, raw: bytes) -> None:
        """Append a frame to the global capture file, if one is open."""
        if self._capture_fp is None:
            return
        self._capture_fp.write(self._frame_block(direction, raw))
        self._capture_fp.flush()

    def capture_unknown(self, ip: str, direction: str, raw: bytes) -> str | None:
        """Auto-log traffic from an unidentified device to ``unknown-<ip>.txt``.

        Returns the capture file path (so the device card can show it).  A new
        file is opened the first time an IP is seen.
        """
        if self.capture_dir is None:
            return None
        fp = self._unknown_fps.get(ip)
        if fp is None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            path = self.capture_dir / f"unknown-{ip}.txt"
            fp = path.open("a", buffering=1)
            fp.write(f"# unidentified device {ip} — capture started {datetime.now().isoformat()}\n\n")
            self._unknown_fps[ip] = fp
            log.info("logging unknown device %s -> %s", ip, path)
            self.publish("capture_started", {"ip": ip, "path": str(path)})
        fp.write(self._frame_block(direction, raw))
        fp.flush()
        return str(self.capture_dir / f"unknown-{ip}.txt")

    def close(self) -> None:
        for fp in self._unknown_fps.values():
            try:
                fp.close()
            except Exception:
                pass
        if self._capture_fp is not None:
            try:
                self._capture_fp.close()
            except Exception:
                pass

    # -- devices ----------------------------------------------------------
    def get_or_create(self, mac: str, addr: str) -> DeviceRecord:
        rec = self.devices.get(mac)
        if rec is None:
            rec = DeviceRecord(mac, addr)
            self.devices[mac] = rec
            self.publish("device_connected", rec.snapshot())
        return rec

    def touch(self, rec: DeviceRecord) -> None:
        rec.last_seen = time.time()

    def remove(self, mac: str) -> None:
        rec = self.devices.pop(mac, None)
        if rec is not None:
            self.publish("device_disconnected", {"mac": mac})

    def snapshot(self) -> dict[str, Any]:
        return {
            "devices": [r.snapshot() for r in self.devices.values()],
            "log": self._log[-100:],
        }

    # -- event bus --------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, kind: str, data: Any) -> None:
        event = {"kind": kind, "ts": time.time(), "data": data}
        if kind == "packet":
            self._log.append(event)
            if len(self._log) > self._max_log:
                self._log = self._log[-self._max_log :]
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop rather than block the protocol server.
                pass

    def log_packet(self, direction: str, mac: str, frame: Any) -> None:
        self.publish(
            "packet",
            {
                "direction": direction,  # "in" (device->server) or "out"
                "mac": mac,
                "msgtype": getattr(frame, "msgtype", None),
                "subsystem": getattr(frame, "subsystem", None),
                "command": getattr(frame, "command", None),
                "body": getattr(frame, "body", b"").hex(),
            },
        )
