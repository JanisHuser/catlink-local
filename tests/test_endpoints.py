"""Endpoint parsing and clean-resolver logic (no network)."""

import asyncio
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catlink_local import resolve  # noqa: E402
from catlink_local.proxy import CLOUD, Endpoint  # noqa: E402


def test_endpoint_parse_forms():
    assert Endpoint.parse("8992") == Endpoint(8992, CLOUD[0], 8992)
    assert Endpoint.parse("9992:devices.catlinks.cn") == Endpoint(9992, "devices.catlinks.cn", 9992)
    assert Endpoint.parse("9992:1.2.3.4:9993") == Endpoint(9992, "1.2.3.4", 9993)


def test_resolver_ip_passthrough():
    # IP literals never hit the network.
    assert asyncio.run(resolve.resolve("10.20.30.40")) == "10.20.30.40"


def test_resolver_parses_a_record():
    host = "feeder.catlinks.cn"
    qname = b"".join(bytes([len(p)]) + p.encode() for p in host.split(".")) + b"\x00"
    header = struct.pack(">HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
    question = qname + struct.pack(">HH", 1, 1)
    answer = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + bytes([47, 90, 202, 93])
    assert resolve._parse_answer(header + question + answer) == "47.90.202.93"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all endpoint tests passed")
