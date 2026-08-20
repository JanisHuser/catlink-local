"""Device availability: overlapping connections and reconnect grace.

CATLINK devices reconnect constantly; the hub must not report every closed
socket as the device going away (that made the HA entities flap).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catlink_local.hub import Hub  # noqa: E402

MAC = "ac:0b:fb:de:ff:0b"


def _kinds(hub, q):
    out = []
    while not q.empty():
        out.append(q.get_nowait()["kind"])
    return out


def test_second_connection_keeps_device_online():
    async def run():
        hub = Hub(offline_grace=0.05)
        hub.attach(MAC, "1.2.3.4:1")
        q = hub.subscribe()
        hub.attach(MAC, "1.2.3.4:2")  # device opened a second connection
        hub.detach(MAC)  # the first one closes
        await asyncio.sleep(0.1)
        assert MAC in hub.devices
        assert hub.devices[MAC].snapshot()["online"] is True
        assert "device_disconnected" not in _kinds(hub, q)

    asyncio.run(run())


def test_reconnect_inside_grace_never_reports_a_disconnect():
    async def run():
        hub = Hub(offline_grace=0.1)
        rec = hub.attach(MAC, "1.2.3.4:1")
        rec.device_type = "feeder"
        q = hub.subscribe()
        hub.detach(MAC)
        await asyncio.sleep(0.02)
        again = hub.attach(MAC, "1.2.3.4:2")  # back before the grace expires
        await asyncio.sleep(0.15)
        assert again is rec  # same record -> decoded state survives
        assert MAC in hub.devices
        assert "device_disconnected" not in _kinds(hub, q)

    asyncio.run(run())


def test_device_gone_past_the_grace_is_reported():
    async def run():
        hub = Hub(offline_grace=0.05)
        hub.attach(MAC, "1.2.3.4:1")
        q = hub.subscribe()
        hub.detach(MAC)
        await asyncio.sleep(0.1)
        assert MAC not in hub.devices
        assert "device_disconnected" in _kinds(hub, q)

    asyncio.run(run())


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all hub session tests passed")
