"""CATLINK self-cleaning litter box ("scooper") handler.

Decoded from captures of the scooper (MAC 34:94:54:9d:b9:8e) which connects on
port **9992** (the feeder uses 8992).  Same frame format and XOR checksum as the
feeder; different command set.

Device -> server:

* ``02 01 0101``            -- keepalive/ping
* ``02 01 0203 <body>``     -- heartbeat, body =
      09 <MAC:6> 05 00 <working> 01 01 00 00 01 00 <temp> <humidity> 00 04 01 <battery> <weight?> ...
    - body[9]  0/1  : working (clean/occupied) flag
    - body[16]      : temperature in °C   (0x1c = 28, stable across captures)
    - body[17]      : humidity in %       (0x43..0x46 = 67..70, fluctuates)
    - body[21]      : 0x64 = 100 (percentage, treated as battery/level)
    - body[9] rising edge (0->1) is read as a *cat entered* event: we log the
      arrival time and the weighed value.  body[22:24] (grams, big-endian) is
      the plausible weight slot but is unconfirmed -- all-zero in every capture
      so far (no cat was on the scale); verify against a live entry.
* ``03 50 28ff <1024B>``    -- big grid/report (mostly zeros); not decoded yet

Server -> device (from a proxy capture with both directions):

* device ``02 01 0203`` (heartbeat)  ->  server ``01 01 02ff ff <MAC> 08 00 00 00``
  (a constant acknowledgement -- reproduced byte-for-byte, verified against the
  capture, so local mode keeps the scooper online without the cloud)
* server also polls ``01 50 01ff ...`` which the device acks ``02 50 01ff ...``

Decoded from the .105 capture (2026-08-15), on the scooper subsystem (0x50):

* time-sync ``01 50 0dff ff <MAC> 05 1a MM DD WD HH MM SS``  -- server -> device,
  pushed by the cloud right after connect and then every few hours.  The device
  acks it ``02 50 0dff ff <MAC> 05 00``.  ``MM DD WD HH MM SS`` matched the
  capture's wall clock exactly (Sat 2026-08-15 -> ``WD = 06`` = ISO weekday);
  the cloud sent UTC, we send local time.  ``05 1a`` is a constant tag replayed
  verbatim.  Local mode pushes this itself on first contact and on ``sync_time``.
* state event ``03 50 0b03 09 <MAC> 05 00``  -- device -> server, seen once
  (stand-alone, no varying payload); the cloud answered ``01 50 0bff ff <MAC>
  05 00`` (verified).  Meaning TBD, but replying keeps the device happy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..protocol import (
    MSG_COMMAND,
    MSG_REPORT,
    Frame,
    build_frame,
    build_payload,
)
from ..registry import register
from .base import Command, DeviceHandler

# scooper command ids / subsystem (distinct from the feeder's)
CMD_PING = 0x0101
CMD_HEARTBEAT = 0x0203
CMD_HEARTBEAT_ACK = 0x02FF  # server's reply to a heartbeat
CMD_POLL = 0x01FF
CMD_GRID = 0x28FF
CMD_TIME_SET = 0x0DFF  # server -> device clock push (device acks 0x0dff)
CMD_STATE = 0x0B03  # device -> server state event
CMD_STATE_ACK = 0x0BFF  # server's reply to a state event
SUB_SCOOPER = 0x50
SUB_MAIN = 0x01


@register
class LitterBoxHandler(DeviceHandler):
    device_type = "litterbox"

    # Commands we decode/answer.  CMD_GRID (0x28ff) is intentionally *excluded*:
    # the 1 KB grid report isn't decoded yet, so it gets logged as "unhandled"
    # for reverse engineering instead of being silently dropped.
    known_commands = frozenset(
        {
            CMD_PING,
            CMD_HEARTBEAT,
            CMD_HEARTBEAT_ACK,
            CMD_POLL,
            CMD_TIME_SET,
            CMD_STATE,
            CMD_STATE_ACK,
        }
    )

    commands = [Command("sync_time", "Sync time", args={})]

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        # The cloud pushes a clock sync right after the device connects; we do
        # the same, once, the first time we handle a frame from it.
        self._time_pushed = False

    @classmethod
    def claim(cls, frame: Frame) -> bool:
        return frame.command in (CMD_PING, CMD_HEARTBEAT, CMD_GRID) or frame.subsystem == SUB_SCOOPER

    def observe(self, frame: Frame, direction: str = "C→S") -> None:
        if self.sub_type == "unknown":
            self.sub_type = "scooper"
        if frame.command == CMD_HEARTBEAT and frame.msgtype == 0x02:
            self._parse_heartbeat(frame)
        elif frame.command == CMD_STATE and frame.msgtype == MSG_REPORT:
            # Payload carries no varying data (just the MAC); record that an
            # event happened so it shows on the dashboard.  Meaning still TBD.
            self.state["last_event_at"] = datetime.now().isoformat(timespec="seconds")

    def _parse_heartbeat(self, frame: Frame) -> None:
        body = frame.body
        if len(body) < 22:
            return
        was_working = bool(self.state.get("working"))
        working = bool(body[9])           # clean/occupied cycle
        self.state.update(
            {
                "working": working,
                "temperature": body[16],  # °C
                "humidity": body[17],     # %
                "battery_percent": body[21],  # 0x64 = 100 (inferred)
                "last_status_hex": body.hex(),
            }
        )
        # Cat-entry event: the box logs a cat's weight and the time it entered.
        # We take the rising edge of the occupancy flag (body[9] 0->1) as the
        # entry and stamp the arrival time (reliable) plus the weighed value.
        # The weight *offset* is still unconfirmed: body[22:24] big-endian is the
        # plausible grams slot (a 3-6 kg cat fits 16 bits) but was all-zero in
        # every captured frame -- no capture has yet shown a cat actually on the
        # scale.  Surfaced so it can be pinned against a live entry; expect 0 g
        # until then.
        if working and not was_working:
            weight = int.from_bytes(body[22:24], "big") if len(body) >= 24 else None
            self.state["last_entry_weight"] = weight
            self.state["last_entry_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    def on_frame(self, frame: Frame) -> list[bytes]:
        """Local mode: keep the scooper online with the cloud's own replies."""
        self.observe(frame, "C→S")
        replies: list[bytes] = []

        # Push the clock once, up front, exactly as the cloud does on connect.
        if not self._time_pushed:
            self._time_pushed = True
            replies.append(self._time_sync_frame())

        if frame.command == CMD_HEARTBEAT and frame.msgtype == 0x02:
            # Verified byte-for-byte against the capture: 01 01 02ff ff <MAC> 08 00 00 00
            body = b"\xff" + self.session.mac + b"\x08\x00\x00\x00"
            payload = build_payload(MSG_COMMAND, SUB_MAIN, CMD_HEARTBEAT_ACK, body)
            replies.append(build_frame(self.session.mac, payload))
        elif frame.command == CMD_STATE and frame.msgtype == MSG_REPORT:
            # Answer the state event the way the cloud did: 01 50 0bff ff <MAC> 05 00.
            body = b"\xff" + self.session.mac + b"\x05\x00"
            payload = build_payload(MSG_COMMAND, SUB_SCOOPER, CMD_STATE_ACK, body)
            replies.append(build_frame(self.session.mac, payload))
        # The device's own time-sync ack (0x0dff, msgtype 0x02) needs no reply.
        return replies

    def _time_sync_frame(self) -> bytes:
        """Build the clock-push command (0x0dff), verified against the capture.

        Captured shape (scooper subsystem)::

            body = ff <MAC:6> 05 1a MM DD WD HH MM SS

        ``MM DD WD HH MM SS`` matched the wall clock byte-for-byte; ``WD`` is the
        ISO weekday (Sat 2026-08-15 -> ``06``).  The cloud sent UTC; we send
        local time so the device shows the right time without the cloud.  ``05
        1a`` is a constant tag replayed verbatim.
        """
        now = datetime.now()
        body = b"\xff" + self.session.mac + bytes(
            [0x05, 0x1A, now.month, now.day, now.isoweekday(), now.hour, now.minute, now.second]
        )
        payload = build_payload(MSG_COMMAND, SUB_SCOOPER, CMD_TIME_SET, body)
        return build_frame(self.session.mac, payload)

    def run_command(self, name: str, args: dict[str, Any]) -> None:
        if name == "sync_time":
            # Push a clock sync on demand (no wait for a device query).
            self.session.send(self._time_sync_frame())
        else:
            # No confirmed clean/scoop control frame captured yet.
            raise ValueError(f"litterbox has no command {name!r} yet")
