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

#: How long a device may stay gone before it is reported as disconnected.
#: CATLINK devices don't hold one long-lived TCP connection -- they drop and
#: reconnect every few seconds -- so announcing every close would make the HA
#: entities flap between available and unavailable.  A device that comes back
#: within this window never leaves the hub at all.
OFFLINE_GRACE = 90.0


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
        #: Live connections currently carrying this device (a device may hold
        #: several at once, and reconnects overlap), so the record only goes
        #: away once the last one is gone.
        self.sessions = 0
        #: When the last connection closed, while we wait out OFFLINE_GRACE.
        self.disconnected_at: float | None = None

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
            "online": self.sessions > 0,
        }
        if self.handler is not None:
            base.update(self.handler.snapshot())
        return base


class Hub:
    def __init__(
        self,
        max_log: int = 500,
        capture_dir: Path | None = None,
        offline_grace: float = OFFLINE_GRACE,
    ):
        self.devices: dict[str, DeviceRecord] = {}
        self.offline_grace = offline_grace
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

    def _append_capture(self, name: str, header: str, direction: str, raw: bytes) -> str | None:
        """Append a frame to ``<capture_dir>/<name>.txt``, opening it (with a
        one-line ``header``) the first time ``name`` is seen.  Returns the path.
        """
        if self.capture_dir is None:
            return None
        path = self.capture_dir / f"{name}.txt"
        fp = self._unknown_fps.get(name)
        if fp is None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            fp = path.open("a", buffering=1)
            fp.write(f"# {header} — capture started {datetime.now().isoformat()}\n\n")
            self._unknown_fps[name] = fp
            log.info("capturing -> %s", path)
            self.publish("capture_started", {"name": name, "path": str(path)})
        fp.write(self._frame_block(direction, raw))
        fp.flush()
        return str(path)

    def capture_unknown(self, ip: str, direction: str, raw: bytes) -> str | None:
        """Auto-log traffic from an unidentified device to ``unknown-<ip>.txt``.

        Returns the capture file path (so the device card can show it).  A new
        file is opened the first time an IP is seen.
        """
        return self._append_capture(
            f"unknown-{ip}", f"unidentified device {ip}", direction, raw
        )

    def capture_unhandled(self, ip: str, device_type: str, direction: str, raw: bytes) -> str | None:
        """Log a frame a *recognised* device sent that its handler doesn't decode.

        Written to ``unhandled-<device_type>-<ip>.txt`` so not-yet-implemented
        commands (new firmware, undecoded reports) are kept for reverse
        engineering without polluting the unidentified-device captures.
        """
        return self._append_capture(
            f"unhandled-{device_type}-{ip}",
            f"unhandled frames from {device_type} {ip}",
            direction,
            raw,
        )

    def capture_device(self, ip: str, device_type: str, direction: str, raw: bytes) -> str | None:
        """Log *every* frame of a recognised device, both directions.

        Written to ``traffic-<device_type>-<ip>.txt``.  Unlike the unhandled
        capture this keeps the full app<->device conversation -- including the
        commands the handler already implements -- so app-originated traffic
        (e.g. a button pressed in the CATLINK app, relayed cloud->device) is
        visible even once the device is recognised.
        """
        return self._append_capture(
            f"traffic-{device_type}-{ip}",
            f"all frames for {device_type} {ip}",
            direction,
            raw,
        )

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

    def attach(self, mac: str, addr: str) -> DeviceRecord:
        """Register a new connection for ``mac`` and return its record.

        Reuses the existing record (and its handler state) when the device is
        already connected or is reconnecting inside the grace window.
        """
        rec = self.get_or_create(mac, addr)
        rec.sessions += 1
        rec.disconnected_at = None  # cancels a pending expiry
        rec.addr = addr
        return rec

    def detach(self, mac: str) -> None:
        """One connection for ``mac`` closed.

        The device is only reported as disconnected once its last connection is
        gone *and* it stays gone for ``offline_grace`` seconds -- otherwise the
        constant reconnects would look like the device dropping off.
        """
        rec = self.devices.get(mac)
        if rec is None:
            return
        rec.sessions = max(0, rec.sessions - 1)
        if rec.sessions:
            return  # another connection is still carrying this device
        rec.disconnected_at = time.time()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.remove(mac)  # no event loop (tests): drop straight away
            return
        loop.call_later(self.offline_grace, self._expire, mac, rec)

    def _expire(self, mac: str, rec: DeviceRecord) -> None:
        """Drop a device that never came back within the grace window."""
        if self.devices.get(mac) is not rec:
            return
        if rec.sessions or rec.disconnected_at is None:
            return  # reconnected in the meantime
        self.remove(mac)

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
