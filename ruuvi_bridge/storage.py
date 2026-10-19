"""Thread-safe settings and a bounded SQLite history outside the source tree."""

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

TAG_ID = re.compile(r"^[0-9a-f]{12}$")
DEFAULTS = {
    "language": "en",
    "mqtt_enabled": True,
    "mqtt_host": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_username": "",
    "mqtt_password": "",
    "mqtt_tls": False,
    "tray_metric": "humidity",
    "tray_tag": "",
    "autostart": False,
}


class Store:
    """Serialize access to the shared SQLite connection and settings snapshot."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "settings.json"
        self.lock = threading.RLock()
        self.config = {**DEFAULTS, "instance_id": uuid.uuid4().hex[:12], "tags": {}}
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.config.update({k: v for k, v in saved.items() if k in self.config})
        self.save()
        self.db = sqlite3.connect(directory / "history.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS samples (
                tag TEXT NOT NULL, time REAL NOT NULL, temperature REAL,
                humidity REAL, pressure REAL, battery REAL, rssi INTEGER,
                PRIMARY KEY(tag,time));
            CREATE INDEX IF NOT EXISTS samples_time ON samples(time);
        """)
        self.last_sample = dict(self.db.execute("SELECT tag, MAX(time) FROM samples GROUP BY tag"))
        self.last_cleanup = 0

    def save(self):
        """Replace the settings atomically so a partial write cannot corrupt them."""
        with self.lock:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if os.name != "nt":
                temporary.chmod(0o600)
            temporary.replace(self.path)

    def settings(self, public=False):
        """Copy settings; never expose the stored MQTT password to browser clients."""
        with self.lock:
            result = json.loads(json.dumps(self.config))
            if public:
                result["has_password"] = bool(result.pop("mqtt_password", ""))
            return result

    def update_settings(self, values):
        """Validate the entire update before committing any of its fields."""
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise ValueError("Tuntematon asetus")
        cfg = self.settings()
        for key, value in values.items():
            if key == "mqtt_password" and value is None:
                continue  # Null preserves the saved password; empty string clears it.
            if isinstance(DEFAULTS[key], bool) and not isinstance(value, bool):
                raise ValueError("Virheellinen valinta")
            cfg[key] = value
        if not isinstance(cfg["mqtt_host"], str) or not re.fullmatch(
            r"[a-zA-Z0-9.:-]{1,253}", cfg["mqtt_host"]
        ):
            raise ValueError("Anna MQTT-palvelimen nimi tai IP-osoite")
        if type(cfg["mqtt_port"]) is not int or not 1 <= cfg["mqtt_port"] <= 65535:
            raise ValueError("Portin on oltava 1–65535")
        if cfg["tray_metric"] not in ("humidity", "temperature"):
            raise ValueError("Virheellinen kuvakkeen mittaus")
        if cfg["language"] not in ("en", "fi"):
            raise ValueError("Valitse tuettu kieli")
        if not isinstance(cfg["tray_tag"], str):
            raise ValueError("Valitse tunnettu anturi")
        if cfg["tray_tag"] and cfg["tray_tag"] not in cfg["tags"]:
            raise ValueError("Valitse tunnettu anturi")
        for key in ("mqtt_username", "mqtt_password"):
            if not isinstance(cfg[key], str) or len(cfg[key]) > 1024:
                raise ValueError("Virheelliset MQTT-tunnukset")
        with self.lock:
            self.config = cfg
            self.save()

    def set_tag(self, tag, name, enabled):
        if not isinstance(tag, str) or not TAG_ID.fullmatch(tag):
            raise ValueError("Virheellinen anturin tunniste")
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 60
            or type(enabled) is not bool
        ):
            raise ValueError("Anna anturille nimi (1–60 merkkiä)")
        with self.lock:
            self.config["tags"][tag] = {"name": name.strip(), "enabled": enabled}
            if enabled and not self.config["tray_tag"]:
                self.config["tray_tag"] = tag
            self.save()

    def sample(self, reading, now=None):
        """Rate-limit history writes independently from BLE packet frequency."""
        now = time.time() if now is None else now
        tag = reading["id"]
        with self.lock:
            if now - self.last_sample.get(tag, 0) < 30:
                return
            self.db.execute(
                "INSERT INTO samples VALUES (?,?,?,?,?,?,?)",
                (
                    tag,
                    now,
                    *(
                        reading.get(k)
                        for k in ("temperature", "humidity", "pressure", "battery", "rssi")
                    ),
                ),
            )
            self.last_sample[tag] = now
            if now - self.last_cleanup > 3600:
                cutoff = now - 30 * 86400
                self.db.execute("DELETE FROM samples WHERE time < ?", (cutoff,))
                self.last_cleanup = now
            self.db.commit()

    def history(self, tag, hours):
        # Bucket long windows, retaining gaps and at most about 1,440 points.
        bucket = max(30, int(hours * 3600 / 1440))
        with self.lock:
            rows = self.db.execute(
                """SELECT MIN(time), AVG(temperature), AVG(humidity),
                AVG(pressure), AVG(battery), AVG(rssi) FROM samples
                WHERE tag=? AND time>=? GROUP BY CAST(time / ? AS INTEGER) ORDER BY MIN(time)
                """,
                (tag, time.time() - hours * 3600, bucket),
            ).fetchall()
        return [
            dict(zip(("time", "temperature", "humidity", "pressure", "battery", "rssi"), row))
            for row in rows
        ]

    def close(self):
        with self.lock:
            self.db.close()
