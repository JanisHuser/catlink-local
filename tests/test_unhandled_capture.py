"""Frames a recognised handler doesn't decode are captured as 'unhandled'."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catlink_local.devices.litterbox import LitterBoxHandler  # noqa: E402
from catlink_local.hub import Hub  # noqa: E402
from catlink_local.protocol import Frame, build_payload  # noqa: E402

MAC = bytes.fromhex("3494549db98e")
IDLE = "fc0028e39d3494549db98e02010203093494549db98e0500000101000001001c460004016400000000000062"


class _S:
    mac = MAC


def _grid_frame() -> Frame:
    # 03 50 28ff <body> -- the undecoded 1 KB grid report (CMD_GRID).
    return Frame(seq=b"\x00\x01", mac=MAC, payload=build_payload(0x03, 0x50, 0x28FF, b"\x00" * 8))


def test_known_command_is_handled():
    h = LitterBoxHandler(_S())
    frame, _ = Frame.parse(bytes.fromhex(IDLE))  # heartbeat -> decoded
    assert h.is_unhandled(frame) is False


def test_grid_command_is_unhandled():
    h = LitterBoxHandler(_S())
    assert h.is_unhandled(_grid_frame()) is True


def test_hub_writes_unhandled_file(tmp_path):
    hub = Hub(capture_dir=tmp_path)
    raw = _grid_frame().encode()
    path = hub.capture_unhandled("192.168.1.7", "litterbox", "C→S", raw)
    hub.close()

    expected = tmp_path / "unhandled-litterbox-192.168.1.7.txt"
    assert path == str(expected)
    text = expected.read_text()
    assert "unhandled frames from litterbox" in text
    assert raw.hex() in text


def test_hub_writes_full_device_conversation(tmp_path):
    # Both directions of a recognised device -- including handled commands and
    # app->device (S→C) frames -- land in one traffic-<type>-<ip>.txt file.
    hub = Hub(capture_dir=tmp_path)
    down = bytes.fromhex("fc001b000100163e022c1201500dffff3494549db98e051a080f0607210430")  # S→C app command
    up = _grid_frame().encode()  # C→S device frame
    path = hub.capture_device("192.168.1.7", "litterbox", "S→C", down)
    hub.capture_device("192.168.1.7", "litterbox", "C→S", up)
    hub.close()

    expected = tmp_path / "traffic-litterbox-192.168.1.7.txt"
    assert path == str(expected)
    text = expected.read_text()
    assert "all frames for litterbox" in text
    assert down.hex() in text and up.hex() in text
    assert "S→C" in text and "C→S" in text


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    test_known_command_is_handled()
    test_grid_command_is_unhandled()
    test_hub_writes_unhandled_file(Path(tempfile.mkdtemp()))
    print("all unhandled-capture tests passed")
