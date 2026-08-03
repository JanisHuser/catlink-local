"""Feeder decoding tests, pinned to real frames from dump.txt."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catlink_local.devices.feeder import FeederHandler  # noqa: E402
from catlink_local.protocol import Frame  # noqa: E402


class _FakeSession:
    mac = bytes.fromhex("ac0bfbdeff0b")


def _decode(hexs: str) -> dict:
    h = FeederHandler(_FakeSession())
    frame, _ = Frame.parse(bytes.fromhex(hexs))
    h.on_frame(frame)
    return h.state


def test_bowl_grams_settled():
    # real "settled" status frame: 0x002d = 45 g, feeding flag 0
    st = _decode("fc00232700ac0bfbdeff0b03010352000214002d00000001000100000208000a0c000a0100504d")
    assert st["bowl_grams"] == 45
    assert st["active"] is False


def test_bowl_grams_empty_and_feeding():
    # real early-feed frame: 0x0005 = 5 g, feeding flag 1
    st = _decode("fc00232700ac0bfbdeff0b03010352000214000501000001000100000208000a0c000a01005064")
    assert st["bowl_grams"] == 5
    assert st["active"] is True


def test_feeder_claims_status_frame():
    frame, _ = Frame.parse(
        bytes.fromhex("fc00232700ac0bfbdeff0b03010352000214000000000001000100000208000a0c000a01005060")
    )
    assert FeederHandler.claim(frame) is True


if __name__ == "__main__":
    test_bowl_grams_settled()
    test_bowl_grams_empty_and_feeding()
    test_feeder_claims_status_frame()
    print("all feeder tests passed")
