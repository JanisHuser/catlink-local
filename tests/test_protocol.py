"""Protocol round-trip tests against real captured frames.

Run with:  python -m pytest   (or)   python tests/test_protocol.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catlink_local.protocol import Frame, checksum, iter_frames  # noqa: E402

# (hex, msgtype, subsystem, command) tuples straight from dump.txt
CAPTURED = [
    ("fc00232700ac0bfbdeff0b03010352000214000000000001000100000208000a0c000a01005060", 0x03, 0x01, 0x0352),
    ("fc000e0001ac0bfbdeff0b0201035200002b", 0x02, 0x01, 0x0352),
    ("fc00140001ac0bfbdeff0b01520452001a0803010e2e3462", 0x01, 0x52, 0x0452),
    ("fc000fb203ac0bfbdeff0b03520252000104cc", 0x03, 0x52, 0x0252),
    ("fc000e0001ac0bfbdeff0b0152055200007d", 0x01, 0x52, 0x0552),
    ("fc000e980bac0bfbdeff0b045204520000eb", 0x04, 0x52, 0x0452),
]


def test_roundtrip_and_fields():
    for hexs, mtype, sub, cmd in CAPTURED:
        raw = bytes.fromhex(hexs)
        frame, rest = Frame.parse(raw)
        assert rest == b"", hexs
        assert frame.encode() == raw, (hexs, frame.encode().hex())
        assert frame.msgtype == mtype
        assert frame.subsystem == sub
        assert frame.command == cmd


def test_checksum_is_xor_without_magic():
    for hexs, *_ in CAPTURED:
        raw = bytes.fromhex(hexs)
        assert checksum(raw[1:-1]) == raw[-1], hexs


def test_concatenated_frames_split():
    combo = (
        "fc00140001ac0bfbdeff0b01520452001a0803010e2e3462"
        "fc000e0001ac0bfbdeff0b0201035200002b"
    )
    buf = bytearray.fromhex(combo)
    frames = iter_frames(buf)
    assert len(frames) == 2
    assert buf == b""  # fully drained


def test_partial_frame_waits():
    raw = bytes.fromhex("fc000e0001ac0bfbdeff0b0201035200002b")
    frame, rest = Frame.parse(raw[:10])  # truncated
    assert frame is None
    assert rest == raw[:10]  # left intact for more bytes


if __name__ == "__main__":
    test_roundtrip_and_fields()
    test_checksum_is_xor_without_magic()
    test_concatenated_frames_split()
    test_partial_frame_waits()
    print("all protocol tests passed")
