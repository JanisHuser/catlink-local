"""Device-type registry.

This is the extension point of the whole server.  To support a new device
you write a :class:`~catlink_local.devices.base.DeviceHandler` subclass and
decorate it with :func:`register`.  On the first frame from a device the
server asks every registered handler ``claim(frame)`` and the first one to
say "yes" owns that connection.

Sub-types (e.g. different feeder models) live *inside* a handler: the handler
inspects later frames and sets ``self.sub_type``.  See ``devices/feeder.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .devices.base import DeviceHandler
    from .protocol import Frame

_handlers: list[type["DeviceHandler"]] = []


def register(cls: type["DeviceHandler"]) -> type["DeviceHandler"]:
    """Class decorator that adds a handler to the registry."""
    if cls not in _handlers:
        _handlers.append(cls)
    return cls


def handlers() -> list[type["DeviceHandler"]]:
    return list(_handlers)


def find_handler(frame: "Frame") -> type["DeviceHandler"] | None:
    """Return the first handler that claims ``frame`` (or ``None``)."""
    for cls in _handlers:
        try:
            if cls.claim(frame):
                return cls
        except Exception:
            # A broken claim() must never take the server down.
            continue
    return None
