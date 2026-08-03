"""Dependency-free dashboard web server.

A minimal HTTP/1.1 server on top of ``asyncio`` streams.  It serves a single
page, a JSON state endpoint, a Server-Sent-Events live stream, and a command
endpoint.  No third-party packages -- everything the browser needs is inlined
in ``index.html``.

Only the handful of methods the dashboard uses are implemented; this is not a
general-purpose web server.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from ..hub import Hub

log = logging.getLogger("catlink.web")

DEFAULT_PORT = 8080
_INDEX = Path(__file__).with_name("index.html")


class Request:
    def __init__(self, method: str, path: str, headers: dict[str, str], body: bytes):
        self.method = method
        parsed = urlparse(path)
        self.path = parsed.path
        self.query = parsed.query
        self.headers = headers
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body or b"{}")


async def _read_request(reader: asyncio.StreamReader) -> Request | None:
    line = await reader.readline()
    if not line:
        return None
    try:
        method, path, _ = line.decode("latin1").split(" ", 2)
    except ValueError:
        return None
    headers: dict[str, str] = {}
    while True:
        h = await reader.readline()
        if h in (b"\r\n", b"\n", b""):
            break
        k, _, v = h.decode("latin1").partition(":")
        headers[k.strip().lower()] = v.strip()
    body = b""
    length = int(headers.get("content-length", 0) or 0)
    if length:
        body = await reader.readexactly(length)
    return Request(method, path, headers, body)


def _response(
    status: str, body: bytes, content_type: str, extra: dict[str, str] | None = None
) -> bytes:
    headers = [
        f"HTTP/1.1 {status}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "Cache-Control: no-store",
    ]
    for k, v in (extra or {}).items():
        headers.append(f"{k}: {v}")
    return ("\r\n".join(headers) + "\r\n\r\n").encode("latin1") + body


class Dashboard:
    def __init__(self, hub: Hub):
        self.hub = hub
        self.routes: dict[tuple[str, str], Callable[[Request], Awaitable[bytes] | bytes]] = {
            ("GET", "/"): self._index,
            ("GET", "/api/state"): self._state,
            ("POST", "/api/command"): self._command,
        }

    # -- handlers ---------------------------------------------------------
    def _index(self, req: Request) -> bytes:
        html = _INDEX.read_bytes()
        return _response("200 OK", html, "text/html; charset=utf-8")

    def _state(self, req: Request) -> bytes:
        body = json.dumps(self.hub.snapshot()).encode()
        return _response("200 OK", body, "application/json")

    def _command(self, req: Request) -> bytes:
        try:
            payload = req.json()
            mac = payload["mac"]
            command = payload["command"]
            args = payload.get("args", {})
        except (KeyError, ValueError):
            return _response("400 Bad Request", b'{"error":"bad request"}', "application/json")

        rec = self.hub.devices.get(mac)
        if rec is None or rec.handler is None:
            return _response("404 Not Found", b'{"error":"unknown device"}', "application/json")
        try:
            rec.handler.run_command(command, args)
        except Exception as exc:  # surface handler errors to the UI
            body = json.dumps({"error": str(exc)}).encode()
            return _response("400 Bad Request", body, "application/json")
        return _response("200 OK", b'{"ok":true}', "application/json")

    # -- SSE (handled specially, streams instead of returning) -----------
    async def _events(self, req: Request, writer: asyncio.StreamWriter) -> None:
        head = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: keep-alive\r\n\r\n"
        ).encode("latin1")
        writer.write(head)
        await writer.drain()
        q = self.hub.subscribe()
        try:
            # Prime the client with a full snapshot.
            await self._send_event(writer, {"kind": "snapshot", "data": self.hub.snapshot()})
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    await self._send_event(writer, event)
                except asyncio.TimeoutError:
                    writer.write(b": ping\r\n\r\n")  # keep the connection alive
                    await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self.hub.unsubscribe(q)

    async def _send_event(self, writer: asyncio.StreamWriter, event: dict) -> None:
        writer.write(f"data: {json.dumps(event)}\n\n".encode())
        await writer.drain()

    # -- dispatch ---------------------------------------------------------
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = await _read_request(reader)
            if req is None:
                return
            if req.method == "GET" and req.path == "/api/events":
                await self._events(req, writer)
                return
            handler = self.routes.get((req.method, req.path))
            if handler is None:
                writer.write(_response("404 Not Found", b"not found", "text/plain"))
            else:
                result = handler(req)
                if asyncio.iscoroutine(result):
                    result = await result
                writer.write(result)
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass


async def start_dashboard(hub: Hub, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
    dash = Dashboard(hub)
    server = await asyncio.start_server(dash.handle, host, port)
    sock = ", ".join(str(s.getsockname()) for s in server.sockets)
    log.info("dashboard listening on %s", sock)
    return server
