"""Scooper/litter-box decoding, pinned to real frames from the .105 capture."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catlink_local.devices.litterbox import LitterBoxHandler  # noqa: E402
from catlink_local.protocol import Frame  # noqa: E402

IDLE = "fc0028e39d3494549db98e02010203093494549db98e0500000101000001001c460004016400000000000062"
WORKING = "fc0028e39d3494549db98e02010203093494549db98e0500010101000001001c450004016400000000000060"
FEEDER_STATUS = "fc00232700ac0bfbdeff0b03010352000214000000000001000100000208000a0c000a01005060"


class _S:
    mac = bytes.fromhex("3494549db98e")


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
    assert h.state["battery_percent"] == 100
    assert h.state["level"] == 70
    assert h.sub_type == "scooper"


def test_heartbeat_working():
    h = _decode(WORKING)
    assert h.state["working"] is True
    assert h.state["level"] == 69


def test_does_not_claim_feeder():
    frame, _ = Frame.parse(bytes.fromhex(FEEDER_STATUS))
    assert LitterBoxHandler.claim(frame) is False


def test_local_mode_is_silent():
    # No confirmed replies yet -> on_frame must not fabricate frames.
    h = _decode(IDLE)
    frame, _ = Frame.parse(bytes.fromhex(IDLE))
    assert h.on_frame(frame) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all litterbox tests passed")
