"""Fallback handler for devices we don't understand yet.

When a new device (e.g. the litter box) first connects we have no decoder for
it.  This handler claims anything no specific handler wanted, keeps the device
online by acknowledging its reports/queries, and surfaces the raw
subsystem/command bytes in the dashboard so you can see what it speaks.

Pair it with ``--capture`` (see ``__main__``) to record the traffic, then
promote what you learn into a real handler (copy ``feeder.py``).

IMPORTANT: this must be registered *last* so specific handlers win.  See
``devices/__init__.py``.
"""

from __future__ import annotations

from collections import Counter

from ..protocol import MSG_QUERY, MSG_REPORT, Frame
from ..registry import register
from .base import DeviceHandler


@register
class GenericHandler(DeviceHandler):
    device_type = "unidentified"

    @classmethod
    def claim(cls, frame: Frame) -> bool:
        # Last resort: take anything nothing else claimed.
        return True

    def __init__(self, session):
        super().__init__(session)
        self._commands_seen: Counter = Counter()

    def observe(self, frame: Frame, direction: str = "C→S") -> None:
        key = f"{direction} {frame.subsystem:#04x}/{frame.command:#06x}"
        self._commands_seen[key] += 1
        self.state.update(
            {
                "last_direction": direction,
                "last_msgtype": frame.msgtype,
                "last_subsystem": frame.subsystem,
                "last_command": frame.command,
                "last_body_hex": frame.body.hex(),
                # sorted so the dashboard shows a stable "fingerprint"
                "commands_seen": dict(sorted(self._commands_seen.items())),
                "note": "unrecognised device — capturing for reverse engineering",
            }
        )

    def on_frame(self, frame: Frame) -> list[bytes]:
        self.observe(frame, "C→S")
        # Blindly ACK reports/queries; this is what kept the feeder happy and is
        # the safest default until we know the device's real expectations.
        if frame.msgtype in (MSG_REPORT, MSG_QUERY):
            return [self.ack(frame)]
        return []
