"""Tests for the MQTT-discovery bridge's pure logic (no broker needed)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catlink_local import ha_mqtt  # noqa: E402


class _Handler:
    def __init__(self, state):
        self.state = state


class _Record:
    def __init__(self, mac, device_type, sub_type, state=None):
        self.mac = mac
        self.device_type = device_type
        self.sub_type = sub_type
        self.handler = _Handler(state or {})


def test_macid():
    assert ha_mqtt.macid("ac:0b:fb:de:ff:0b") == "ac0bfbdeff0b"


def test_feeder_discovery_has_expected_entities():
    rec = _Record("ac:0b:fb:de:ff:0b", "feeder", "one-fountain")
    topics = {t: p for t, p in ha_mqtt.discovery_for(rec)}
    # one config per entity, all valid JSON-able dicts with unique_ids
    kinds = [t.split("/")[1] for t in topics]
    assert "sensor" in kinds and "binary_sensor" in kinds
    assert "number" in kinds and "button" in kinds
    for topic, payload in topics.items():
        json.dumps(payload)  # serialisable
        assert payload["unique_id"].startswith("catlink_ac0bfbdeff0b")
        assert payload["device"]["identifiers"] == ["catlink_ac0bfbdeff0b"]
    # the feed button points at a command topic the bridge listens on
    btn = next(p for t, p in topics.items() if t.split("/")[1] == "button")
    assert ha_mqtt.parse_command(btn["command_topic"]) == ("ac0bfbdeff0b", "feed")


def test_state_payload_maps_bowl_grams():
    rec = _Record("ac:0b:fb:de:ff:0b", "feeder", "one-fountain",
                  {"bowl_grams": 45, "active": True, "last_feed_portions": 5})
    p = ha_mqtt.state_payload(rec)
    assert p["bowl_grams"] == 45 and p["active"] is True and p["last_feed_portions"] == 5


def test_litterbox_discovery_has_climate_and_weight():
    rec = _Record("34:94:54:9d:b9:8e", "litterbox", "scooper")
    names = {p["name"] for _, p in ha_mqtt.discovery_for(rec)}
    assert {"Temperature", "Humidity", "Weight"} <= names


def test_state_payload_maps_litterbox_climate():
    rec = _Record("34:94:54:9d:b9:8e", "litterbox", "scooper",
                  {"temperature": 28, "humidity": 70, "weight": 4200})
    p = ha_mqtt.state_payload(rec)
    assert p["temperature"] == 28 and p["humidity"] == 70 and p["weight"] == 4200


def test_parse_command():
    assert ha_mqtt.parse_command("catlink/ac0bfbdeff0b/feed/press") == ("ac0bfbdeff0b", "feed")
    assert ha_mqtt.parse_command("catlink/ac0bfbdeff0b/portions/set") == ("ac0bfbdeff0b", "portions")
    assert ha_mqtt.parse_command("catlink/x/other/set") is None
    assert ha_mqtt.parse_command("nope") is None


def test_generic_device_gets_diagnostic_only():
    rec = _Record("11:22:33:44:55:66", "unidentified", "unknown", {"last_command": 0x0153})
    topics = [t for t, _ in ha_mqtt.discovery_for(rec)]
    assert all(t.split("/")[1] == "sensor" for t in topics)
    assert ha_mqtt.state_payload(rec)["last_command"] == "0x0153"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all ha_mqtt tests passed")
