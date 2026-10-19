"""Publish selected tags using Home Assistant discovery and explicit availability."""

import json
import threading

import paho.mqtt.client as mqtt

FIELDS = {
    "temperature": ("Lämpötila", "temperature", "°C"),
    "humidity": ("Kosteus", "humidity", "%"),
    "pressure": ("Ilmanpaine", "atmospheric_pressure", "hPa"),
    "battery": ("Paristojännite", "voltage", "V"),
    "rssi": ("Signaali", "signal_strength", "dBm"),
}


class Publisher:
    """Own one reconnecting Paho client and per-tag discovery/rate-limit state."""

    def __init__(self, store, status):
        self.store, self.status = store, status
        self.client = None
        self.lock = threading.RLock()
        self.announced = set()
        self.last_sent = {}
        self.online_tags = set()
        self.base = "ruuvi_bridge/" + store.settings()["instance_id"]

    def start(self):
        cfg = self.store.settings()
        if not cfg["mqtt_enabled"]:
            self.status("mqtt", "disabled", "MQTT pois käytöstä")
            return
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=self.base.replace("/", "_")
        )
        client.max_queued_messages_set(100)
        client.reconnect_delay_set(1, 30)
        if cfg["mqtt_username"]:
            client.username_pw_set(cfg["mqtt_username"], cfg["mqtt_password"])
        if cfg["mqtt_tls"]:
            client.tls_set()
        client.will_set(self.base + "/status", "offline", qos=1, retain=True)

        def on_connect(c, userdata, flags, reason, properties):
            if reason.is_failure:
                self.status("mqtt", "error", "MQTT-yhteys hylättiin: " + str(reason))
                return
            with self.lock:
                self.announced.clear()
                self.last_sent.clear()
                self.online_tags.clear()
                # Clear previous tag availability before making the bridge online.
                for tag, info in self.store.settings()["tags"].items():
                    c.publish(f"{self.base}/{tag}/availability", "offline", qos=1, retain=True)
                    if not info["enabled"]:
                        for topic, _ in self.discovery(tag, ""):
                            c.publish(topic, b"", qos=1, retain=True)
                c.subscribe("homeassistant/status", qos=1)
                c.publish(self.base + "/status", "online", qos=1, retain=True)
            self.status("mqtt", "connected", "Yhdistetty: " + cfg["mqtt_host"])

        def on_message(c, userdata, message):
            if message.topic == "homeassistant/status" and message.payload == b"online":
                with self.lock:
                    self.announced.clear()
                    self.last_sent.clear()

        def on_disconnect(c, userdata, flags, reason, properties):
            self.status("mqtt", "disconnected", "MQTT-yhteys katkesi; yhdistetään uudelleen")

        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect
        client.on_connect_fail = lambda c, u: self.status(
            "mqtt", "error", "MQTT ei vastaa; yritetään uudelleen"
        )
        self.client = client
        self.status("mqtt", "connecting", "Yhdistetään MQTT-palvelimeen")
        client.connect_async(cfg["mqtt_host"], cfg["mqtt_port"], keepalive=30)
        client.loop_start()

    def discovery(self, tag, name):
        """Yield stable discovery identities without retaining stale measurements."""
        instance_id = self.store.settings()["instance_id"]
        for key, (label, device_class, unit) in FIELDS.items():
            yield (
                f"homeassistant/sensor/ruuvi_{instance_id}_{tag}/{key}/config",
                {
                    "name": label,
                    "unique_id": f"ruuvi_{instance_id}_{tag}_{key}",
                    "state_topic": f"{self.base}/{tag}/state",
                    "value_template": "{{ value_json." + key + " }}",
                    "unit_of_measurement": unit,
                    "device_class": device_class,
                    "state_class": "measurement",
                    "expire_after": 180,
                    "availability_mode": "all",
                    "availability": [
                        {"topic": self.base + "/status"},
                        {"topic": f"{self.base}/{tag}/availability"},
                    ],
                    "device": {
                        "identifiers": [f"ruuvi_{tag}"],
                        "name": name,
                        "manufacturer": "Ruuvi",
                        "model": "RuuviTag (RAWv2)",
                    },
                    **({"entity_category": "diagnostic"} if key in ("battery", "rssi") else {}),
                },
            )

    def publish(self, reading, name, now):
        with self.lock:
            c = self.client
            if not c or not c.is_connected():
                return
            tag = reading["id"]
            if tag not in self.announced:
                for topic, payload in self.discovery(tag, name):
                    c.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)
                self.announced.add(tag)
            if now - self.last_sent.get(tag, 0) < 10:
                return
            info = c.publish(f"{self.base}/{tag}/state", json.dumps(reading), qos=1, retain=False)
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                c.publish(f"{self.base}/{tag}/availability", "online", qos=1, retain=True)
                self.last_sent[tag] = now
                self.online_tags.add(tag)

    def expire(self, fresh):
        """Mark silent tags offline even while the bridge itself stays connected."""
        with self.lock:
            if not self.client or not self.client.is_connected():
                return
            for tag in self.online_tags - fresh:
                self.client.publish(
                    f"{self.base}/{tag}/availability", "offline", qos=1, retain=True
                )
                self.last_sent.pop(tag, None)
            self.online_tags.intersection_update(fresh)

    def forget(self, tag):
        with self.lock:
            if self.client and self.client.is_connected():
                self.client.publish(
                    f"{self.base}/{tag}/availability", "offline", qos=1, retain=True
                )
                for topic, _ in self.discovery(tag, ""):
                    self.client.publish(topic, b"", qos=1, retain=True)
            self.announced.discard(tag)
            self.last_sent.pop(tag, None)
            self.online_tags.discard(tag)

    def stop(self):
        # Never hold the callback lock while joining the network thread.
        c = self.client
        if c:
            if c.is_connected():
                try:
                    c.publish(
                        self.base + "/status", "offline", qos=1, retain=True
                    ).wait_for_publish(2)
                except RuntimeError:
                    pass
            c.disconnect()
            c.loop_stop()
        self.client = None
