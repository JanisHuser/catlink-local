"""Wire protocol for CATLINK devices.

Reverse-engineered from a MITM capture of the device <-> cloud TCP stream
(port 8992).  Every frame on the wire looks like this::

    fc | len(2, big-endian, = total_len - 4) | seq(2) | mac(6) | payload | xor(1)

    payload = msgtype(1) | subsystem(1) | command(2) | body(...)

Verified facts (see the capture in ../catlink/dump.txt):

* ``xor`` is the XOR of every byte in the frame *except* the leading ``fc``
  and the checksum byte itself.  This held for all 74 frames in the capture.
* ``msgtype``:  0x01 = command (server->device), 0x02 = ack,
  0x03 = report (device->server), 0x04 = query (device->server).
* ``subsystem``: 0x01 = main/status, 0x52 = feeder.
* ``command``:   0x0352 = status, 0x0452 = time-sync, 0x0552 = feed trigger,
  0x0252 = feed report.

Nothing here is feeder specific; device-type behaviour lives in
``catlink_local.devices``.  This module only knows how to frame bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

MAGIC = 0xFC

# msgtype values
MSG_COMMAND = 0x01  # server -> device
MSG_ACK = 0x02
MSG_REPORT = 0x03  # device -> server
MSG_QUERY = 0x04  # device -> server, expects a reply

# subsystem values
SUB_MAIN = 0x01
SUB_FEEDER = 0x52

# command values
CMD_STATUS = 0x0352
CMD_TIME = 0x0452
CMD_FEED = 0x0552
CMD_FEED_REPORT = 0x0252
CMD_VISIT = 0x0052  # periodic pet-visit event report (device -> server)

# The server always answered with this sequence id in the capture.
SERVER_SEQ = b"\x00\x01"


def checksum(frame_without_magic_and_xor: bytes) -> int:
    """XOR checksum over every byte after ``fc`` and before the checksum."""
    x = 0
    for b in frame_without_magic_and_xor:
        x ^= b
    return x


@dataclass
class Frame:
    """A single decoded protocol frame."""

    seq: bytes  # 2 bytes
    mac: bytes  # 6 bytes
    payload: bytes

    # --- framing ---------------------------------------------------------
    @classmethod
    def parse(cls, buf: bytes) -> tuple["Frame | None", bytes]:
        """Pull one frame off the front of ``buf``.

        Returns ``(frame, rest)``.  If ``buf`` does not yet hold a complete
        frame, returns ``(None, buf)`` unchanged so the caller can wait for
        more bytes.  A desynchronised stream (no leading ``fc``) is resynced
        by dropping bytes until the next magic.
        """
        if not buf:
            return None, buf
        if buf[0] != MAGIC:
            nxt = buf.find(bytes([MAGIC]), 1)
            if nxt == -1:
                return None, b""
            return cls.parse(buf[nxt:])
        if len(buf) < 3:
            return None, buf
        length = int.from_bytes(buf[1:3], "big")
        total = length + 4
        if len(buf) < total:
            return None, buf
        frame = buf[:total]
        seq = frame[3:5]
        mac = frame[5:11]
        payload = frame[11:-1]
        return cls(seq=seq, mac=mac, payload=payload), buf[total:]

    def encode(self) -> bytes:
        body = self.seq + self.mac + self.payload
        # len field == total_len - 4 == len(seq + mac + payload); the trailing
        # checksum byte is *not* counted (verified against every captured frame).
        length = len(body).to_bytes(2, "big")
        without_magic = length + body
        return bytes([MAGIC]) + without_magic + bytes([checksum(without_magic)])

    # --- payload accessors ----------------------------------------------
    @property
    def msgtype(self) -> int:
        return self.payload[0] if len(self.payload) >= 1 else -1

    @property
    def subsystem(self) -> int:
        return self.payload[1] if len(self.payload) >= 2 else -1

    @property
    def command(self) -> int:
        if len(self.payload) >= 4:
            return int.from_bytes(self.payload[2:4], "big")
        return -1

    @property
    def body(self) -> bytes:
        """Everything after the 4-byte (msgtype, subsystem, command) header."""
        return self.payload[4:]

    @property
    def mac_str(self) -> str:
        return ":".join(f"{b:02x}" for b in self.mac)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"Frame(mac={self.mac_str} type={self.msgtype:#04x} "
            f"sub={self.subsystem:#04x} cmd={self.command:#06x} "
            f"body={self.body.hex()})"
        )


def build_payload(msgtype: int, subsystem: int, command: int, body: bytes = b"") -> bytes:
    return bytes([msgtype, subsystem]) + command.to_bytes(2, "big") + body


def build_frame(mac: bytes, payload: bytes, seq: bytes = SERVER_SEQ) -> bytes:
    """Convenience: build an outgoing (server->device) frame as raw bytes."""
    return Frame(seq=seq, mac=mac, payload=payload).encode()


def iter_frames(buffer: bytearray) -> list[Frame]:
    """Drain every complete frame from ``buffer`` in place, returning them."""
    frames: list[Frame] = []
    data = bytes(buffer)
    while True:
        frame, rest = Frame.parse(data)
        if frame is None:
            break
        frames.append(frame)
        data = rest
    buffer[:] = data
    return frames
