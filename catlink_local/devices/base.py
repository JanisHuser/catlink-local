"""Base class every device handler extends.

The contract is small on purpose:

* ``claim(frame)``    -- classmethod, decides whether this handler owns a
                         freshly connected device (called once, on the first
                         frame).
* ``on_frame(frame)`` -- called for every device->server frame; return a list
                         of raw byte replies to send back (may be empty).
* ``commands``        -- name -> description map of the actions the dashboard
                         should offer for this device.
* ``run_command()``   -- execute one of those actions.
* ``snapshot()``      -- JSON-serialisable view of the device for the UI.

Handlers get a :class:`Session` giving them the device mac, a logger, and a
``send()`` helper.  Everything device-type specific lives in the subclass, so
adding hardware never touches the server or protocol code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..protocol import Frame, build_frame, build_payload

if TYPE_CHECKING:
    from ..server import Session


class Command:
    """Describes an action the dashboard can trigger on a device."""

    def __init__(self, name: str, label: str, args: dict[str, str] | None = None):
        self.name = name
        self.label = label
        # arg name -> input type hint ("int", "str"); rendered by the dashboard.
        self.args = args or {}

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "args": self.args}


class DeviceHandler:
    #: Stable identifier for the device family (shown in the UI, used in URLs).
    device_type: str = "generic"

    #: Commands this handler exposes.  Subclasses override.
    commands: list[Command] = []

    def __init__(self, session: "Session"):
        self.session = session
        self.sub_type: str = "unknown"
        #: Free-form, JSON-serialisable state the dashboard renders.
        self.state: dict[str, Any] = {}

    # -- classification ---------------------------------------------------
    @classmethod
    def claim(cls, frame: Frame) -> bool:
        """Return True if this handler should own the device that sent ``frame``."""
        return False

    # -- traffic ----------------------------------------------------------
    def on_frame(self, frame: Frame) -> list[bytes]:
        """Local mode: handle one device->server frame; return raw replies."""
        return [self.ack(frame)]

    def observe(self, frame: Frame, direction: str) -> None:
        """Proxy mode: update state from an observed frame; never replies.

        ``direction`` is ``"C→S"`` (device->cloud) or ``"S→C"`` (cloud->device).
        The cloud does the answering in this mode, so handlers only decode.
        """
        return None

    def run_command(self, name: str, args: dict[str, Any]) -> None:
        """Execute a dashboard-triggered command.  Raises on unknown command."""
        raise ValueError(f"{self.device_type} has no command {name!r}")

    # -- helpers for subclasses ------------------------------------------
    def ack(self, frame: Frame) -> bytes:
        """Standard acknowledgement: same subsystem+command, empty body.

        Verified against the capture: a status report (``03 01 0352 ...``) is
        answered by ``02 01 0352 0000`` and a feed report by ``02 52 0252 0000``.
        """
        from ..protocol import MSG_ACK

        payload = build_payload(MSG_ACK, frame.subsystem, frame.command, b"\x00\x00")
        return build_frame(frame.mac, payload)

    def send_command(self, subsystem: int, command: int, body: bytes = b"") -> bytes:
        from ..protocol import MSG_COMMAND

        payload = build_payload(MSG_COMMAND, subsystem, command, body)
        raw = build_frame(self.session.mac, payload)
        self.session.send(raw)
        return raw

    # -- dashboard view ---------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "device_type": self.device_type,
            "sub_type": self.sub_type,
            "state": self.state,
            "commands": [c.to_dict() for c in self.commands],
        }
