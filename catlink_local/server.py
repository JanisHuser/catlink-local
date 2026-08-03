"""Asyncio TCP server that speaks the CATLINK protocol.

The device is pointed at this machine via DNS and connects on port 8992 just
as it would to the cloud.  Each connection gets a :class:`Session`; the first
frame is used to pick a device handler from the registry, and from then on
every frame is dispatched to that handler.
"""

from __future__ import annotations

import asyncio
import logging

from . import registry
from .hub import DeviceRecord, Hub
from .protocol import iter_frames

log = logging.getLogger("catlink.server")

DEFAULT_PORT = 8992


class Session:
    """One connected device."""

    def __init__(self, hub: Hub, writer: asyncio.StreamWriter):
        self.hub = hub
        self._writer = writer
        peer = writer.get_extra_info("peername")
        self.ip = peer[0] if peer else "unknown"
        self.addr = f"{peer[0]}:{peer[1]}" if peer else "?"
        self.mac: bytes = b""
        self.mac_str: str = ""
        self.record: DeviceRecord | None = None
        self.handler = None
        #: True once we know no dedicated handler recognised this device.
        self.is_unknown = False

    def send(self, raw: bytes) -> None:
        self._writer.write(raw)
        self.hub.write_capture("S→C", raw)
        if self.is_unknown:
            self.hub.capture_unknown(self.ip, "S→C", raw)
        if self.record is not None:
            self.record.packets_out += 1
        # The live-traffic log is only for unidentified devices (the stuff we
        # still need to reverse-engineer); only decode replies for those.
        if self.is_unknown:
            from .protocol import Frame

            frame, _ = Frame.parse(raw)
            if frame is not None:
                self.hub.log_packet("out", self.mac_str, frame)

    def _identify(self, frame) -> None:
        self.mac = frame.mac
        self.mac_str = frame.mac_str
        self.record = self.hub.get_or_create(self.mac_str, self.addr)
        handler_cls = registry.find_handler(frame)
        if handler_cls is None:
            log.warning("no handler claimed device %s (%r)", self.mac_str, frame)
            return
        self.handler = handler_cls(self)
        self.record.handler = self.handler
        self.record.device_type = self.handler.device_type
        # An "unidentified" device is one only the generic fallback claimed;
        # log its traffic per-IP so it can be reverse-engineered later.
        self.is_unknown = self.handler.device_type == "unidentified"
        log.info("device %s -> %s handler", self.mac_str, self.handler.device_type)
        self.hub.publish("device_identified", self.record.snapshot())

    def dispatch(self, frame) -> None:
        if self.record is None or not self.mac:
            self._identify(frame)
        self.record.packets_in += 1
        self.hub.touch(self.record)
        self.hub.write_capture("C→S", frame.encode())
        if self.is_unknown:
            path = self.hub.capture_unknown(self.ip, "C→S", frame.encode())
            if path and self.record.capture_path != path:
                self.record.capture_path = path
            # Only unidentified-device traffic goes to the live log.
            self.hub.log_packet("in", self.mac_str, frame)
        if self.handler is None:
            return
        try:
            replies = self.handler.on_frame(frame)
        except Exception:
            log.exception("handler error for %s", self.mac_str)
            return
        for raw in replies or []:
            self.send(raw)
        # keep the dashboard's device card fresh
        self.hub.publish("device_state", self.record.snapshot())


async def handle_connection(
    hub: Hub, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    session = Session(hub, writer)
    log.info("connection from %s", session.addr)
    buffer = bytearray()
    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            for frame in iter_frames(buffer):
                session.dispatch(frame)
            await writer.drain()
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        if session.mac_str:
            hub.remove(session.mac_str)
        log.info("disconnected %s", session.addr)


async def start_server(hub: Hub, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
    server = await asyncio.start_server(
        lambda r, w: handle_connection(hub, r, w), host, port
    )
    sock = ", ".join(str(s.getsockname()) for s in server.sockets)
    log.info("protocol server listening on %s", sock)
    return server
