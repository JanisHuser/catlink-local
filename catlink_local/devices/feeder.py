"""CATLINK feeder handler.

This is the reference device implementation and the template for adding new
hardware.  It shows the whole extension pattern:

* ``device_type`` names the family ("feeder").
* ``claim()`` recognises the device from its first frame.
* sub-types are resolved at runtime into ``self.sub_type``.
* ``on_frame()`` keeps the device happy (acks + time-sync) and decodes status.
* ``commands`` / ``run_command()`` expose actions to the dashboard.

Everything below the framing layer is best-effort reverse engineering from the
capture; each non-obvious byte is commented with what the capture showed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..protocol import (
    CMD_FEED,
    CMD_FEED_REPORT,
    CMD_STATUS,
    CMD_TIME,
    MSG_QUERY,
    MSG_REPORT,
    SUB_FEEDER,
    Frame,
    build_frame,
    build_payload,
)
from ..registry import register
from .base import Command, DeviceHandler


def _sub_type_for(frame: Frame) -> str:
    """Resolve the feeder sub-type from the status frame.

    We only captured one model, so this maps the observed signature to a name
    and leaves an obvious place to add more.  The status body starts with a
    fixed signature (``00 02 14 ...`` in the capture); different models are
    expected to differ here.
    """
    sig = frame.body[:3]
    if sig == b"\x00\x02\x14":
        return "one-fountain"  # the captured model's signature
    return "generic"


@register
class FeederHandler(DeviceHandler):
    device_type = "feeder"

    commands = [
        Command("feed", "Feed", args={"portions": "int"}),
        Command("sync_time", "Sync time", args={}),
    ]

    @classmethod
    def claim(cls, frame: Frame) -> bool:
        # The feeder identifies itself by its status command (0x0352 on the
        # main subsystem) or by any traffic on the feeder subsystem (0x52).
        return frame.command == CMD_STATUS or frame.subsystem == SUB_FEEDER

    # -- traffic ----------------------------------------------------------
    def observe(self, frame: Frame, direction: str = "C→S") -> None:
        """Decode state from a frame (used in both local and proxy modes).

        Only *reports* (msgtype 0x03) carry data.  In proxy mode we also see the
        cloud's acks, which reuse the same command ids with an empty body -- so
        the msgtype guard is essential to avoid clobbering decoded state.
        """
        if frame.msgtype != MSG_REPORT:
            return
        if frame.command == CMD_STATUS:
            self._parse_status(frame)
        elif frame.command == CMD_FEED_REPORT:
            self._parse_feed_report(frame)

    def on_frame(self, frame: Frame) -> list[bytes]:
        self.observe(frame, "C→S")
        replies: list[bytes] = []

        # A time query wants the current time back, not a bare ack.
        if frame.command == CMD_TIME and frame.msgtype == MSG_QUERY:
            replies.append(self._time_reply(frame))
            return replies

        # Everything the device reports or queries gets acknowledged so it
        # stays online (verified against the capture).
        if frame.msgtype in (MSG_REPORT, MSG_QUERY):
            replies.append(self.ack(frame))
        return replies

    def _parse_status(self, frame: Frame) -> None:
        if self.sub_type == "unknown":
            self.sub_type = _sub_type_for(frame)
        body = frame.body
        # body = 00 02 14 <bowl_grams:2> <feeding> 00 00 01 ...
        # body[3:5] is a 16-bit big-endian weight of food in the bowl, in grams.
        # In the capture it traced a clean feed-and-eat curve: 0 g -> climbing
        # while feeding (flag byte body[5] = 0x01) -> 54 g peak -> settling to
        # 45 g as the cat ate.  body[5] is 0x01 during a feed, 0x00 at rest.
        bowl_grams = int.from_bytes(body[3:5], "big") if len(body) >= 5 else None
        feeding = body[5] if len(body) > 5 else None
        self.state.update(
            {
                "bowl_grams": bowl_grams,
                "active": bool(feeding),
                "last_status_hex": body.hex(),
            }
        )

    def _parse_feed_report(self, frame: Frame) -> None:
        body = frame.body  # e.g. 00 01 04  ->  portions in the last byte
        portions = body[2] if len(body) > 2 else None
        self.state["last_feed_portions"] = portions
        self.state["last_feed_at"] = datetime.now().isoformat(timespec="seconds")

    def _time_reply(self, frame: Frame) -> bytes:
        """Build the time-sync response.

        Captured shape (command 0x0452, feeder subsystem)::

            body = 00 1a MM DD WD HH MM SS

        ``0e 2e 34`` decoded to 14:46:52 exactly matching the capture's
        timestamp, and ``08 03`` matched the capture date (Aug 3).  The leading
        ``00 1a`` was constant, so we replay it verbatim.
        """
        now = datetime.now()
        weekday = (now.isoweekday() % 7) + 1  # capture had Sunday -> 0x01
        body = bytes(
            [0x00, 0x1A, now.month, now.day, weekday, now.hour, now.minute, now.second]
        )
        payload = build_payload(0x01, SUB_FEEDER, CMD_TIME, body)
        return build_frame(frame.mac, payload)

    # -- commands ---------------------------------------------------------
    def run_command(self, name: str, args: dict[str, Any]) -> None:
        if name == "feed":
            portions = int(args.get("portions", 1))
            portions = max(1, min(portions, 12))  # sane bound
            # Feed trigger observed as  01 52 0552 00 NN  (server -> device).
            self.send_command(SUB_FEEDER, CMD_FEED, portions.to_bytes(2, "big"))
            self.state["last_feed_command"] = {
                "portions": portions,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        elif name == "sync_time":
            # Push a time-sync without waiting for the device to ask.
            fake = Frame(seq=b"\x00\x01", mac=self.session.mac, payload=b"")
            self.session.send(self._time_reply(fake))
        else:
            raise ValueError(f"feeder has no command {name!r}")
