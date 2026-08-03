"""Transparent MITM proxy mode.

Instead of *replacing* the cloud (see ``server.py``), this forwards every byte
between the device and the real CATLINK cloud so the official app keeps
working, while we parse the traffic for the dashboard and can still inject our
own commands (e.g. feed).

The upstream address must be given as an **IP** (or resolved by a resolver that
is *not* the poisoned one), otherwise the proxy would resolve the cloud
hostname back to this machine and talk to itself.
"""

from __future__ import annotations

import asyncio
import logging

from . import registry
from .hub import Hub
from .protocol import Frame, iter_frames

log = logging.getLogger("catlink.proxy")

CLOUD = ("47.90.202.93", 8992)


class ProxySession:
    """One device<->cloud conversation we are sitting inside of."""

    def __init__(self, hub: Hub, client_writer: asyncio.StreamWriter):
        self.hub = hub
        self._client_writer = client_writer
        peer = client_writer.get_extra_info("peername")
        self.ip = peer[0] if peer else "unknown"
        self.addr = f"{peer[0]}:{peer[1]}" if peer else "?"
        self.mac: bytes = b""
        self.mac_str: str = ""
        self.record = None
        self.handler = None
        self.is_unknown = False

    # -- injection (dashboard commands) -----------------------------------
    def send(self, raw: bytes) -> None:
        """Inject a frame toward the device (the cloud won't know about it)."""
        self._client_writer.write(raw)
        self.hub.write_capture("S→C", raw)
        if self.is_unknown:
            self.hub.capture_unknown(self.ip, "S→C", raw)
        if self.record is not None:
            self.record.packets_out += 1
            frame, _ = Frame.parse(raw)
            if frame is not None and self.is_unknown:
                self.hub.log_packet("out", self.mac_str, frame)

    # -- classification ---------------------------------------------------
    def _identify(self, frame: Frame) -> None:
        self.mac = frame.mac
        self.mac_str = frame.mac_str
        self.record = self.hub.get_or_create(self.mac_str, self.addr)
        handler_cls = registry.find_handler(frame)
        if handler_cls is None:
            return
        self.handler = handler_cls(self)
        self.record.handler = self.handler
        self.record.device_type = self.handler.device_type
        self.is_unknown = self.handler.device_type == "unidentified"
        log.info("device %s -> %s handler (proxy)", self.mac_str, self.handler.device_type)
        self.hub.publish("device_identified", self.record.snapshot())

    # -- observation ------------------------------------------------------
    def observe(self, direction: str, frame: Frame) -> None:
        if direction == "C→S" and (self.record is None or not self.mac):
            self._identify(frame)
        if self.record is None:
            return
        if direction == "C→S":
            self.record.packets_in += 1
        else:
            self.record.packets_out += 1
        self.hub.touch(self.record)

        raw = frame.encode()
        self.hub.write_capture(direction, raw)
        if self.is_unknown:
            path = self.hub.capture_unknown(self.ip, direction, raw)
            if path and self.record.capture_path != path:
                self.record.capture_path = path
            # Live log stays scoped to unidentified devices, both directions.
            self.hub.log_packet("in" if direction == "C→S" else "out", self.mac_str, frame)

        if self.handler is not None:
            try:
                self.handler.observe(frame, direction)
            except Exception:
                log.exception("observe error for %s", self.mac_str)
        self.hub.publish("device_state", self.record.snapshot())


async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter, direction: str, session: ProxySession) -> None:
    """Forward bytes src->dst verbatim, parsing a copy for observation."""
    buf = bytearray()
    try:
        while True:
            chunk = await src.read(4096)
            if not chunk:
                break
            # Forward raw bytes exactly as received (never re-encode the stream).
            dst.write(chunk)
            await dst.drain()
            buf.extend(chunk)
            for frame in iter_frames(buf):
                session.observe(direction, frame)
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass


async def handle_proxy_connection(
    hub: Hub,
    upstream: tuple[str, int],
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    session = ProxySession(hub, writer)
    log.info("device %s connected (proxy -> %s:%s)", session.addr, *upstream)
    try:
        up_reader, up_writer = await asyncio.open_connection(*upstream)
    except OSError as exc:
        log.error("cannot reach cloud %s:%s: %s", upstream[0], upstream[1], exc)
        writer.close()
        return
    await asyncio.gather(
        _pump(reader, up_writer, "C→S", session),
        _pump(up_reader, writer, "S→C", session),
    )
    if session.mac_str:
        hub.remove(session.mac_str)
    log.info("device %s disconnected (proxy)", session.addr)


async def start_proxy(hub: Hub, upstream: tuple[str, int], host: str = "0.0.0.0", port: int = 8992):
    server = await asyncio.start_server(
        lambda r, w: handle_proxy_connection(hub, upstream, r, w), host, port
    )
    sock = ", ".join(str(s.getsockname()) for s in server.sockets)
    log.info("PROXY server listening on %s -> cloud %s:%s", sock, upstream[0], upstream[1])
    return server
