"""CATLINK self-cleaning litter box ("scooper") handler.

Decoded from a capture of the scooper (MAC 34:94:54:9d:b9:8e) which connects on
port **9992** (the feeder uses 8992).  Same frame format and XOR checksum as the
feeder; different command set.

Observed device->server traffic (see captures/capture-192.168.178.105.txt):

* ``02 01 0101``            -- keepalive/ping (no body)
* ``02 01 0203 <body>``     -- heartbeat: body = 09 <MAC:6> 05 00 <working>
                              01 01 00 00 01 00 1c <level> 00 04 01 <battery> ...
    - body[9]  flips 0->1 : a feed/clean/occupied "working" flag
    - body[17] (0x46->0x45): a slowly changing level/counter
    - body[21] (0x64=100) : looks like battery %
* ``03 50 28ff <1024B>``    -- big grid/report (mostly zeros); not decoded yet

We only captured device->server frames, so we don't yet know the cloud's
replies.  This handler therefore *observes* (decodes state) and does not
fabricate responses; run it in **proxy mode** where the real cloud answers.
Capture a proxy session (both directions) to learn the acks, then local mode
can be filled in.
"""

from __future__ import annotations

from typing import Any

from ..protocol import Frame
from ..registry import register
from .base import DeviceHandler

# scooper command ids / subsystem (distinct from the feeder's)
CMD_PING = 0x0101
CMD_HEARTBEAT = 0x0203
CMD_GRID = 0x28FF
SUB_SCOOPER = 0x50


@register
class LitterBoxHandler(DeviceHandler):
    device_type = "litterbox"

    @classmethod
    def claim(cls, frame: Frame) -> bool:
        return frame.command in (CMD_PING, CMD_HEARTBEAT, CMD_GRID) or frame.subsystem == SUB_SCOOPER

    def observe(self, frame: Frame, direction: str = "C→S") -> None:
        if self.sub_type == "unknown":
            self.sub_type = "scooper"
        if frame.command == CMD_HEARTBEAT:
            self._parse_heartbeat(frame)

    def _parse_heartbeat(self, frame: Frame) -> None:
        body = frame.body
        if len(body) < 22:
            return
        self.state.update(
            {
                "working": bool(body[9]),          # 0->1 during a clean/feed cycle
                "level": body[17],                 # slowly-changing counter (inferred)
                "battery_percent": body[21],       # 0x64 = 100 (inferred)
                "last_status_hex": body.hex(),
            }
        )

    def on_frame(self, frame: Frame) -> list[bytes]:
        # Observe only.  We don't know the cloud's replies yet, so in local mode
        # we stay silent rather than send frames the device might reject.
        self.observe(frame, "C→S")
        return []

    def run_command(self, name: str, args: dict[str, Any]) -> None:
        # No confirmed control frames yet; exposed once a proxy capture reveals
        # the clean/scoop command.
        raise ValueError(f"litterbox has no command {name!r} yet")
