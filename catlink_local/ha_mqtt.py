"""Home Assistant MQTT-discovery bridge.

Turns the hub's live device state into native HA entities: it publishes MQTT
discovery configs so entities appear automatically, mirrors state to their
topics, and turns HA button/number commands back into ``handler.run_command``
calls.  Used by the HA add-on (``python -m catlink_local --proxy --mqtt ...``).

``paho-mqtt`` is imported lazily (only when the bridge actually runs) so the
core package stays dependency-free for the standalone server.

The pure helpers -- ``discovery_for``, ``state_payload``, ``parse_command`` --
have no MQTT dependency and are unit tested.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger("catlink.mqtt")

DISCOVERY_PREFIX = "homeassistant"
BASE = "catlink"


def macid(mac: str) -> str:
    """`ac:0b:...` -> `ac0bfbdeff0b` (safe for topics and unique_ids)."""
    return mac.replace(":", "").lower()


def state_topic(mid: str) -> str:
    return f"{BASE}/{mid}/state"


def availability_topic(mid: str) -> str:
    return f"{BASE}/{mid}/availability"


def portions_state_topic(mid: str) -> str:
    return f"{BASE}/{mid}/portions"


def _device_block(mid: str, record: Any) -> dict[str, Any]:
    tail = mid[-4:]
    return {
        "identifiers": [f"catlink_{mid}"],
        "name": f"CATLINK {record.device_type.title()} {tail}",
        "manufacturer": "CATLINK",
        "model": record.sub_type or record.device_type,
    }


def _feeder_entities(mid: str, record: Any, dev: dict) -> list[tuple[str, dict]]:
    st = state_topic(mid)
    av = availability_topic(mid)
    out: list[tuple[str, dict]] = []

    out.append(
        (
            f"{DISCOVERY_PREFIX}/sensor/catlink_{mid}/bowl/config",
            {
                "name": "Food in bowl",
                "unique_id": f"catlink_{mid}_bowl",
                "state_topic": st,
                "value_template": "{{ value_json.bowl_grams }}",
                "unit_of_measurement": "g",
                "device_class": "weight",
                "state_class": "measurement",
                "availability_topic": av,
                "device": dev,
            },
        )
    )
    out.append(
        (
            f"{DISCOVERY_PREFIX}/binary_sensor/catlink_{mid}/feeding/config",
            {
                "name": "Feeding",
                "unique_id": f"catlink_{mid}_feeding",
                "state_topic": st,
                "value_template": "{{ 'ON' if value_json.active else 'OFF' }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "device_class": "running",
                "availability_topic": av,
                "device": dev,
            },
        )
    )
    out.append(
        (
            f"{DISCOVERY_PREFIX}/sensor/catlink_{mid}/last_feed/config",
            {
                "name": "Last feed portions",
                "unique_id": f"catlink_{mid}_last_feed",
                "state_topic": st,
                "value_template": "{{ value_json.last_feed_portions }}",
                "icon": "mdi:bowl-mix",
                "availability_topic": av,
                "device": dev,
            },
        )
    )
    out.append(
        (
            f"{DISCOVERY_PREFIX}/number/catlink_{mid}/portions/config",
            {
                "name": "Feed portions",
                "unique_id": f"catlink_{mid}_portions",
                "command_topic": f"{BASE}/{mid}/portions/set",
                "state_topic": portions_state_topic(mid),
                "min": 1,
                "max": 12,
                "step": 1,
                "mode": "box",
                "icon": "mdi:counter",
                "availability_topic": av,
                "device": dev,
            },
        )
    )
    out.append(
        (
            f"{DISCOVERY_PREFIX}/button/catlink_{mid}/feed/config",
            {
                "name": "Feed now",
                "unique_id": f"catlink_{mid}_feed",
                "command_topic": f"{BASE}/{mid}/feed/press",
                "icon": "mdi:silverware-fork",
                "availability_topic": av,
                "device": dev,
            },
        )
    )
    return out


def _generic_entities(mid: str, record: Any, dev: dict) -> list[tuple[str, dict]]:
    st = state_topic(mid)
    av = availability_topic(mid)
    # Unidentified devices get a diagnostic sensor so you can see them in HA
    # while reverse engineering; no controls until a handler exists.
    return [
        (
            f"{DISCOVERY_PREFIX}/sensor/catlink_{mid}/last_command/config",
            {
                "name": "Last command",
                "unique_id": f"catlink_{mid}_last_command",
                "state_topic": st,
                "value_template": "{{ value_json.last_command }}",
                "entity_category": "diagnostic",
                "icon": "mdi:help-network",
                "availability_topic": av,
                "device": dev,
            },
        )
    ]


def _litterbox_entities(mid: str, record: Any, dev: dict) -> list[tuple[str, dict]]:
    st = state_topic(mid)
    av = availability_topic(mid)
    return [
        (
            f"{DISCOVERY_PREFIX}/binary_sensor/catlink_{mid}/working/config",
            {
                "name": "Working",
                "unique_id": f"catlink_{mid}_working",
                "state_topic": st,
                "value_template": "{{ 'ON' if value_json.working else 'OFF' }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "device_class": "running",
                "availability_topic": av,
                "device": dev,
            },
        ),
        (
            f"{DISCOVERY_PREFIX}/sensor/catlink_{mid}/battery/config",
            {
                "name": "Battery",
                "unique_id": f"catlink_{mid}_battery",
                "state_topic": st,
                "value_template": "{{ value_json.battery_percent }}",
                "unit_of_measurement": "%",
                "device_class": "battery",
                "state_class": "measurement",
                "availability_topic": av,
                "device": dev,
            },
        ),
    ]


def discovery_for(record: Any) -> list[tuple[str, dict]]:
    """Return (config_topic, payload) pairs to advertise a device to HA."""
    mid = macid(record.mac)
    dev = _device_block(mid, record)
    if record.device_type == "feeder":
        return _feeder_entities(mid, record, dev)
    if record.device_type == "litterbox":
        return _litterbox_entities(mid, record, dev)
    return _generic_entities(mid, record, dev)


def state_payload(record: Any) -> dict[str, Any]:
    """The value_json a device publishes to its state topic."""
    state = getattr(record.handler, "state", {}) if record.handler else {}
    payload: dict[str, Any] = {
        # feeder
        "bowl_grams": state.get("bowl_grams"),
        "active": bool(state.get("active")),
        "last_feed_portions": state.get("last_feed_portions"),
        # litterbox
        "working": bool(state.get("working")),
        "battery_percent": state.get("battery_percent"),
        "level": state.get("level"),
        # common
        "device_type": record.device_type,
        "sub_type": record.sub_type,
    }
    if record.device_type == "unidentified":
        cmd = state.get("last_command")
        payload["last_command"] = f"{cmd:#06x}" if isinstance(cmd, int) else None
    return payload


def parse_command(topic: str) -> tuple[str, str] | None:
    """`catlink/<mid>/feed/press` -> (mid, 'feed');
    `catlink/<mid>/portions/set` -> (mid, 'portions'). Else None."""
    parts = topic.split("/")
    if len(parts) == 4 and parts[0] == BASE:
        _, mid, kind, action = parts
        if kind == "feed" and action == "press":
            return mid, "feed"
        if kind == "portions" and action == "set":
            return mid, "portions"
    return None


class MqttBridge:
    """Wires paho-mqtt to the hub.  Runs inside the asyncio event loop."""

    def __init__(self, hub, host: str, port: int = 1883, username: str = "", password: str = ""):
        self.hub = hub
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._advertised: set[str] = set()
        self._portions: dict[str, int] = {}

    async def start(self) -> None:
        import paho.mqtt.client as mqtt  # lazy: only needed in the add-on

        self._loop = asyncio.get_running_loop()
        client = mqtt.Client()
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.connect_async(self.host, self.port)
        client.loop_start()
        self._client = client
        log.info("MQTT bridge connecting to %s:%s", self.host, self.port)
        asyncio.create_task(self._consume_events())

    # -- paho callbacks (run in paho's thread) ---------------------------
    def _on_connect(self, client, userdata, flags, rc):
        log.info("MQTT connected (rc=%s)", rc)
        client.subscribe(f"{BASE}/+/feed/press")
        client.subscribe(f"{BASE}/+/portions/set")
        # Re-advertise anything already connected.
        for rec in list(self.hub.devices.values()):
            self._advertise(rec)
            self._publish_state(rec)

    def _on_message(self, client, userdata, msg):
        parsed = parse_command(msg.topic)
        if not parsed or self._loop is None:
            return
        mid, kind = parsed
        payload = msg.payload.decode(errors="replace").strip()
        # Hop back onto the event loop -- run_command touches asyncio writers.
        self._loop.call_soon_threadsafe(self._run_command, mid, kind, payload)

    # -- event loop side --------------------------------------------------
    def _find(self, mid: str):
        for rec in self.hub.devices.values():
            if macid(rec.mac) == mid:
                return rec
        return None

    def _run_command(self, mid: str, kind: str, payload: str) -> None:
        rec = self._find(mid)
        if rec is None or rec.handler is None:
            return
        try:
            if kind == "portions":
                self._portions[mid] = max(1, min(int(payload or "1"), 12))
                self._publish(portions_state_topic(mid), str(self._portions[mid]), retain=True)
            elif kind == "feed":
                portions = self._portions.get(mid, 1)
                rec.handler.run_command("feed", {"portions": portions})
        except Exception:
            log.exception("command %s failed for %s", kind, mid)

    async def _consume_events(self) -> None:
        q = self.hub.subscribe()
        try:
            while True:
                event = await q.get()
                kind = event["kind"]
                data = event["data"]
                if kind in ("device_identified", "device_state"):
                    rec = self.hub.devices.get(data.get("mac"))
                    if rec is not None:
                        self._advertise(rec)
                        self._publish_state(rec)
                elif kind == "device_disconnected":
                    mid = macid(data.get("mac", ""))
                    self._publish(availability_topic(mid), "offline", retain=True)
        finally:
            self.hub.unsubscribe(q)

    # -- publishing -------------------------------------------------------
    def _advertise(self, record) -> None:
        mid = macid(record.mac)
        key = f"{mid}:{record.device_type}"
        if key in self._advertised:
            return
        for topic, payload in discovery_for(record):
            self._publish(topic, json.dumps(payload), retain=True)
        self._publish(availability_topic(mid), "online", retain=True)
        # seed the number entity with a sane default
        self._portions.setdefault(mid, 1)
        self._publish(portions_state_topic(mid), str(self._portions[mid]), retain=True)
        self._advertised.add(key)
        log.info("advertised %s (%s) to HA", record.mac, record.device_type)

    def _publish_state(self, record) -> None:
        mid = macid(record.mac)
        self._publish(availability_topic(mid), "online", retain=True)
        self._publish(state_topic(mid), json.dumps(state_payload(record)), retain=True)

    def _publish(self, topic: str, payload: str, retain: bool = False) -> None:
        if self._client is not None:
            self._client.publish(topic, payload, retain=retain)
