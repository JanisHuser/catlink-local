"""Scooper/litter-box decoding, pinned to real frames from the .105 capture."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catlink_local.devices.litterbox import LitterBoxHandler  # noqa: E402
from catlink_local.protocol import Frame  # noqa: E402

IDLE = "fc0028e39d3494549db98e02010203093494549db98e0500000101000001001c460004016400000000000062"
WORKING = "fc0028e39d3494549db98e02010203093494549db98e0500010101000001001c430004016400000000000066"
HB_REPLY = "fc001700013494549db98e010102ffff3494549db98e080000001c"
FEEDER_STATUS = "fc00232700ac0bfbdeff0b03010352000214000000000001000100000208000a0c000a01005060"
# Real frames from the .105 capture (2026-08-15):
TIME_ACK = "fc00150e463494549db98e02500dffff3494549db98e050007"  # device -> server, 0x0dff ack
STATE = "fc0015517a3494549db98e03500b03093494549db98e050069"  # device -> server, 0x0b03 event
STATE_REPLY = "fc001500013494549db98e01500bffff3494549db98e05004b"  # our verified 0x0bff reply


class _S:
    mac = bytes.fromhex("3494549db98e")

    def __init__(self):
        self.sent = []

    def send(self, raw):
        self.sent.append(raw)


def _decode(hexs):
    h = LitterBoxHandler(_S())
    frame, _ = Frame.parse(bytes.fromhex(hexs))
    h.on_frame(frame)
    return h


def test_claims_scooper_heartbeat():
    frame, _ = Frame.parse(bytes.fromhex(IDLE))
    assert LitterBoxHandler.claim(frame) is True


def test_heartbeat_idle():
    h = _decode(IDLE)
    assert h.state["working"] is False
    assert h.state["temperature"] == 28  # 0x1c
    assert h.state["humidity"] == 70  # 0x46
    assert h.state["battery_percent"] == 100
    assert h.sub_type == "scooper"


def test_heartbeat_working():
    h = _decode(WORKING)
    assert h.state["working"] is True
    assert h.state["temperature"] == 28
    assert h.state["humidity"] == 67  # 0x43


def test_cat_entry_records_weight_and_time():
    # Occupancy 0->1 is a cat-entry event: it stamps a time and a weight.
    # The weight slot is unconfirmed, so it's 0 here (no cat on the scale), but
    # the entry must still be recorded with a timestamp.
    h = LitterBoxHandler(_S())
    idle, _ = Frame.parse(bytes.fromhex(IDLE))
    working, _ = Frame.parse(bytes.fromhex(WORKING))
    h.on_frame(idle)
    assert "last_entry_at" not in h.state  # no entry while idle
    h.on_frame(working)
    assert h.state["last_entry_weight"] == 0
    assert "T" in h.state["last_entry_at"]  # ISO timestamp recorded


def test_does_not_claim_feeder():
    frame, _ = Frame.parse(bytes.fromhex(FEEDER_STATUS))
    assert LitterBoxHandler.claim(frame) is False


def test_local_mode_keepalive_reply():
    # A heartbeat must be answered with the cloud's exact ack (verified frame).
    h = _decode(IDLE)
    frame, _ = Frame.parse(bytes.fromhex(IDLE))
    replies = h.on_frame(frame)
    assert len(replies) == 1
    assert replies[0].hex() == HB_REPLY


def test_time_sync_pushed_on_first_frame():
    # Like the cloud, we push a clock sync (0x0dff) once, on first contact.
    h = LitterBoxHandler(_S())
    frame, _ = Frame.parse(bytes.fromhex(IDLE))
    first = h.on_frame(frame)
    assert len(first) == 2
    pushed, _ = Frame.parse(first[0])
    assert pushed.command == 0x0DFF and pushed.subsystem == 0x50
    assert first[1].hex() == HB_REPLY
    # and never again
    assert len(h.on_frame(frame)) == 1


def test_time_sync_frame_shape():
    from datetime import datetime

    h = LitterBoxHandler(_S())
    frame, _ = Frame.parse(h._time_sync_frame())
    body = frame.body
    now = datetime.now()
    assert body[:9] == bytes.fromhex("ff3494549db98e051a")  # ff <MAC> 05 1a
    assert body[9] == now.month and body[10] == now.day
    assert body[11] == now.isoweekday()  # Sat 2026-08-15 verified as 0x06


def test_state_event_is_acked():
    # 0x0b03 event -> the cloud's verified 0x0bff reply; no longer "unhandled".
    h = LitterBoxHandler(_S())
    h._time_pushed = True  # isolate the event reply from the first-contact push
    frame, _ = Frame.parse(bytes.fromhex(STATE))
    assert h.is_unhandled(frame) is False
    replies = h.on_frame(frame)
    assert len(replies) == 1
    assert replies[0].hex() == STATE_REPLY
    assert "last_event_at" in h.state


def test_time_ack_is_known_and_silent():
    # The device's own 0x0dff ack is recognised and needs no reply.
    h = LitterBoxHandler(_S())
    h._time_pushed = True
    frame, _ = Frame.parse(bytes.fromhex(TIME_ACK))
    assert h.is_unhandled(frame) is False
    assert h.on_frame(frame) == []


def test_sync_time_command():
    s = _S()
    h = LitterBoxHandler(s)
    h.run_command("sync_time", {})
    assert len(s.sent) == 1
    frame, _ = Frame.parse(s.sent[0])
    assert frame.command == 0x0DFF


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all litterbox tests passed")
