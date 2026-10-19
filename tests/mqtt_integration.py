"""Run against an isolated MQTT broker on port 18884, never the real HA broker."""

import json
import tempfile
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

from ruuvi_bridge.mqtt import Publisher
from ruuvi_bridge.storage import Store


def wait_for(predicate, description):
    deadline = time.time() + 8
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(description)


def main():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory))
        store.update_settings({"mqtt_port": 18884})
        tag = "020000000001"  # Synthetic address; the test never uses real tag data.
        store.set_tag(tag, "Integration test", True)
        messages = []
        subscribed = threading.Event()
        observer = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        observer.on_connect = lambda c, u, f, r, p: c.subscribe("#", qos=1)
        observer.on_subscribe = lambda *args: subscribed.set()
        observer.on_message = lambda c, u, m: messages.append((m.topic, m.payload.decode()))
        observer.connect("127.0.0.1", 18884)
        observer.loop_start()
        assert subscribed.wait(5)
        publisher = Publisher(store, lambda *args: None)
        try:
            publisher.start()
            wait_for(lambda: publisher.client.is_connected(), "connect")
            reading = {
                "id": tag,
                "temperature": 24.3,
                "humidity": 53.49,
                "pressure": 1000.44,
                "battery": 2.977,
                "rssi": -60,
            }
            publisher.publish(reading, "Integration test", time.time())
            wait_for(lambda: any(t.endswith("/state") for t, p in messages), "state received")
            configs = [(t, json.loads(p)) for t, p in messages if t.endswith("/config") and p]
            assert len(configs) == 5, configs
            assert all(c["expire_after"] == 180 for t, c in configs)
            assert any(
                json.loads(p)["humidity"] == 53.49 for t, p in messages if t.endswith("/state")
            )
            publisher.expire(set())
            wait_for(
                lambda: any(
                    t.endswith(tag + "/availability") and p == "offline" for t, p in messages
                ),
                "stale tag",
            )
            messages.clear()
            observer.publish("homeassistant/status", "online", qos=1).wait_for_publish(2)
            wait_for(lambda: not publisher.announced, "HA restart invalidates discovery cache")
            publisher.publish(reading, "Integration test", time.time() + 11)
            wait_for(
                lambda: len([t for t, p in messages if t.endswith("/config")]) == 5, "rediscovery"
            )
            publisher.stop()
            wait_for(
                lambda: (publisher.base + "/status", "offline") in messages, "graceful offline"
            )
            publisher.start()
            wait_for(lambda: publisher.client.is_connected(), "reconnect")
            publisher.publish(reading, "Integration test", time.time() + 22)
            wait_for(lambda: tag in publisher.announced, "announce after reconnect")
            publisher.forget(tag)
            wait_for(
                lambda: len([t for t, p in messages if t.endswith("/config") and not p]) == 5,
                "discovery removal",
            )
            print(
                "PASS: discovery, real MQTT measurements, stale availability, HA birth, reconnect, removal, shutdown"
            )
        finally:
            publisher.stop()
            observer.disconnect()
            observer.loop_stop()
            store.close()


if __name__ == "__main__":
    main()
