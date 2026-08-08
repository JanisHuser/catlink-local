"""CATLINK self-cleaning litter box ("scooper") handler.

Decoded from captures of the scooper (MAC 34:94:54:9d:b9:8e) which connects on
port **9992** (the feeder uses 8992).  Same frame format and XOR checksum as the
feeder; different command set.

Device -> server:

* ``02 01 0101``            -- keepalive/ping
* ``02 01 0203 <body>``     -- heartbeat, body =
      09 <MAC:6> 05 00 <working> 01 01 00 00 01 00 <temp> <humidity> 00 04 01 <battery> ...
    - body[9]  0/1  : working (clean/occupied) flag
    - body[16]      : temperature in °C   (0x1c = 28, stable across captures)
    - body[17]      : humidity in %       (0x43..0x46 = 67..70, fluctuates)
    - body[21]      : 0x64 = 100 (percentage, treated as battery/level)
* ``03 50 28ff <1024B>``    -- big grid/report (mostly zeros); not decoded yet

Server -> device (from a proxy capture with both directions):

* device ``02 01 0203`` (heartbeat)  ->  server ``01 01 02ff ff <MAC> 08 00 00 00``
  (a constant acknowledgement -- reproduced byte-for-byte, verified against the
  capture, so local mode keeps the scooper online without the cloud)
* server also polls ``01 50 01ff ...`` which the device acks ``02 50 01ff ...``
"""

from __future__ import annotations

from typing import Any

from ..protocol import Frame, build_frame, build_payload
from ..registry import register
from .base import DeviceHandler

# scooper command ids / subsystem (distinct from the feeder's)
CMD_PING = 0x0101
CMD_HEARTBEAT = 0x0203
CMD_HEARTBEAT_ACK = 0x02FF  # server's reply to a heartbeat
CMD_POLL = 0x01FF
CMD_GRID = 0x28FF
SUB_SCOOPER = 0x50
SUB_MAIN = 0x01


@register
class LitterBoxHandler(DeviceHandler):
    device_type = "litterbox"

    # Commands we decode/answer.  CMD_GRID (0x28ff) is intentionally *excluded*:
    # the 1 KB grid report isn't decoded yet, so it gets logged as "unhandled"
    # for reverse engineering instead of being silently dropped.
    known_commands = frozenset({CMD_PING, CMD_HEARTBEAT, CMD_HEARTBEAT_ACK, CMD_POLL})

    @classmethod
    def claim(cls, frame: Frame) -> bool:
        return frame.command in (CMD_PING, CMD_HEARTBEAT, CMD_GRID) or frame.subsystem == SUB_SCOOPER

    def observe(self, frame: Frame, direction: str = "C→S") -> None:
        if self.sub_type == "unknown":
            self.sub_type = "scooper"
        if frame.command == CMD_HEARTBEAT and frame.msgtype == 0x02:
            self._parse_heartbeat(frame)

    def _parse_heartbeat(self, frame: Frame) -> None:
        body = frame.body
        if len(body) < 22:
            return
        self.state.update(
            {
                "working": bool(body[9]),        # clean/occupied cycle
                "temperature": body[16],         # °C
                "humidity": body[17],            # %
                "battery_percent": body[21],     # 0x64 = 100 (inferred)
                "last_status_hex": body.hex(),
            }
        )

    def on_frame(self, frame: Frame) -> list[bytes]:
        """Local mode: keep the scooper online with the cloud's own replies."""
        self.observe(frame, "C→S")
        if frame.command == CMD_HEARTBEAT and frame.msgtype == 0x02:
            # Verified byte-for-byte against the capture: 01 01 02ff ff <MAC> 08 00 00 00
            body = b"\xff" + self.session.mac + b"\x08\x00\x00\x00"
            payload = build_payload(0x01, SUB_MAIN, CMD_HEARTBEAT_ACK, body)
            return [build_frame(self.session.mac, payload)]
        return []

    def run_command(self, name: str, args: dict[str, Any]) -> None:
        # No confirmed clean/scoop control frame captured yet.
        raise ValueError(f"litterbox has no command {name!r} yet")
