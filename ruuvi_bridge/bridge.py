"""Coordinate BLE readings, user-selected tags and their presentation state."""

import asyncio
import logging
import threading
import time

from .decoder import COMPANY_ID, decode
from .mqtt import Publisher
from .windows import set_autostart

LOG = logging.getLogger(__name__)
STALE_SECONDS = 180


class Bridge:
    """Own live sensor state; serialize configuration changes with ingestion."""

    def __init__(self, store, directory, url, demo=False):
        self.store, self.directory, self.url, self.demo = store, directory, url, demo
        self.lock = threading.RLock()
        self.settings_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.readings = {}
        self.statuses = {}
        self.unsupported = set()
        self.publisher = Publisher(store, self.status)
        self.thread = None

    def status(self, key, state, message):
        with self.lock:
            self.statuses[key] = {"state": state, "message": message}

    def receive(self, reading, rssi):
        """Expose nearby tags, but persist and publish only selected tags."""
        now = time.time()
        reading = {**reading, "rssi": rssi, "last_seen": now}
        with self.lock:
            self.readings[reading["id"]] = reading
        with self.settings_lock:
            cfg = self.store.settings()
            tag = reading["id"]
            selected = cfg["tags"].get(tag)
            if not selected or not selected["enabled"]:
                return
            self.store.sample(reading, now)
            if not self.demo:
                self.publisher.publish(reading, selected["name"], now)

    def snapshot(self):
        """Return an independent, password-free snapshot for the UI and tray."""
        cfg = self.store.settings(public=True)
        now = time.time()
        with self.lock:
            readings = {k: dict(v) for k, v in self.readings.items()}
            statuses = dict(self.statuses)
            unsupported = sorted(self.unsupported)
        sensors = []
        for tag in sorted(set(cfg["tags"]) | set(readings)):
            info = cfg["tags"].get(tag, {"name": "Ruuvi " + tag[-4:].upper(), "enabled": False})
            reading = readings.get(tag, {})
            age = now - reading["last_seen"] if reading else None
            sensors.append(
                {
                    **reading,
                    **info,
                    "id": tag,
                    "fresh": age is not None and age < STALE_SECONDS,
                    "age": age,
                }
            )
        return {
            "settings": cfg,
            "sensors": sensors,
            "status": statuses,
            "demo": self.demo,
            "unsupported_formats": unsupported,
        }

    def update_settings(self, values):
        """Apply validated settings and reconnect only when MQTT options change."""
        with self.settings_lock:
            old = self.store.settings()
            self.store.update_settings(values)
            cfg = self.store.settings()
            try:
                if cfg["autostart"] != old["autostart"]:
                    if self.demo:
                        raise ValueError("Demossa ei voi muuttaa Windowsin automaattikäynnistystä")
                    set_autostart(cfg["autostart"], self.directory)
            except Exception:
                self.store.update_settings({k: old[k] for k in values})
                raise
            if any(cfg[k] != old[k] for k in cfg if k.startswith("mqtt_")) and not self.demo:
                self.publisher.stop()
                self.publisher.start()

    def update_tag(self, tag, name, enabled):
        with self.settings_lock:
            known = {s["id"] for s in self.snapshot()["sensors"]}
            if tag not in known:
                raise ValueError("Anturia ei ole vielä havaittu")
            self.store.set_tag(tag, name, enabled)
            self.publisher.forget(tag)

    async def scan(self):
        """Keep the Windows scanner on its own asyncio/MTA thread and retry failures."""
        from bleak import BleakScanner

        def callback(device, advertisement):
            data = advertisement.manufacturer_data.get(COMPANY_ID)
            if not data:
                return
            reading = decode(data, device.address)
            if reading:
                try:
                    self.receive(reading, advertisement.rssi)
                except Exception:
                    LOG.exception("Reading processing failed")
                    self.status(
                        "storage", "error", "Mittauksen tallennus epäonnistui; tarkista loki"
                    )
            else:
                with self.lock:
                    self.unsupported.add(data[0])

        while not self.stop_event.is_set():
            try:
                self.status("bluetooth", "starting", "Käynnistetään Bluetooth-kuuntelu")
                async with BleakScanner(detection_callback=callback):
                    self.status("bluetooth", "scanning", "Bluetooth-kuuntelu käynnissä")
                    while not self.stop_event.is_set():
                        await asyncio.sleep(1)
                        with self.lock:
                            fresh = {
                                tag
                                for tag, r in self.readings.items()
                                if time.time() - r["last_seen"] < STALE_SECONDS
                            }
                            # Nearby, unselected tags are ephemeral and never stored in the database.
                            selected = self.store.settings()["tags"]
                            self.readings = {
                                tag: r
                                for tag, r in self.readings.items()
                                if tag in selected or time.time() - r["last_seen"] < 600
                            }
                        self.publisher.expire(fresh)
            except Exception:
                LOG.exception("Bluetooth scan failed")
                self.status(
                    "bluetooth",
                    "error",
                    "Bluetooth ei ole käytettävissä; uusi yritys 10 sekunnin kuluttua",
                )
                for _ in range(10):
                    if self.stop_event.is_set():
                        break
                    await asyncio.sleep(1)

    def start(self):
        if self.demo:
            self.status("mqtt", "disabled", "Demo: MQTT-lähetys pois käytöstä")
            self.thread = threading.Thread(target=self.demo_loop, daemon=True)
        else:
            self.publisher.start()
            self.thread = threading.Thread(target=lambda: asyncio.run(self.scan()), daemon=True)
        self.thread.start()

    def demo_loop(self):
        import math

        # Synthetic locally administered address, never a real user's sensor.
        tag = "020000000001"
        if tag not in self.store.settings()["tags"]:
            self.store.set_tag(tag, "Olohuone (demo)", True)
        now = time.time()
        # Seed only the separate demo database, and only once.
        if not self.store.history(tag, 24):
            for i in range(720):
                self.store.sample(
                    {
                        "id": tag,
                        "temperature": 22 + math.sin(i / 20),
                        "humidity": 46 + 5 * math.cos(i / 30),
                        "pressure": 1013,
                        "battery": 2.98,
                        "rssi": -58,
                    },
                    now - 86400 + i * 120,
                )
        self.status("bluetooth", "demo", "Demo: esimerkkimittauksia, Bluetooth pois käytöstä")
        while not self.stop_event.is_set():
            self.receive(
                {
                    "id": tag,
                    "temperature": round(22 + math.sin(time.time() / 30), 2),
                    "humidity": round(46 + math.cos(time.time() / 60), 2),
                    "pressure": 1013,
                    "battery": 2.98,
                },
                -58,
            )
            self.stop_event.wait(2)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
        self.publisher.stop()
