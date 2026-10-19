import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ruuvi_bridge.bridge import Bridge
from ruuvi_bridge.decoder import decode
from ruuvi_bridge.server import create_server
from ruuvi_bridge.storage import Store
from ruuvi_bridge.windows import Tray

# Public Ruuvi RAWv2 specification test vector, not a captured personal device.
# https://docs.ruuvi.com/communication/bluetooth-advertisements/data-format-5-rawv2
VALID = bytes.fromhex("0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F")
TAG = "cbb8334c884f"


class DecoderTests(unittest.TestCase):
    def test_official_ruuvi_vectors(self):
        result = decode(VALID, "00:00:00:00:00:00")
        self.assertEqual(result["id"], TAG)
        self.assertAlmostEqual(result["temperature"], 24.3)
        self.assertAlmostEqual(result["humidity"], 53.49)
        self.assertAlmostEqual(result["pressure"], 1000.44)
        self.assertAlmostEqual(result["battery"], 2.977)
        self.assertEqual(result["sequence"], 205)
        minimum = decode(bytes.fromhex("058001000000008001800180010000000000CBB8334C884F"), "")
        self.assertEqual(minimum["temperature"], -163.835)
        self.assertEqual(minimum["humidity"], 0)
        maximum = decode(bytes.fromhex("057FFFFFFEFFFE7FFF7FFF7FFFFFDEFEFFFECBB8334C884F"), "")
        self.assertEqual(maximum["temperature"], 163.835)
        self.assertEqual(maximum["battery"], 3.646)

    def test_missing_values_and_malformed_data(self):
        invalid = bytes.fromhex("058000FFFFFFFF800080008000FFFFFFFFFFFFFFFFFFFFFF")
        result = decode(invalid, "CB:B8:33:4C:88:4F")
        self.assertEqual(result["id"], TAG)
        for key in ("temperature", "humidity", "pressure", "battery", "sequence", "movement"):
            self.assertIsNone(result[key])
        self.assertIsNone(decode(b"\x05", ""))
        self.assertIsNone(decode(b"\x03" + VALID[1:], ""))
        self.assertIsNone(decode(invalid, "not-a-mac"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = Store(self.directory)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_history_throttle_retention_restart_and_password_redaction(self):
        now = time.time()
        reading = decode(VALID, "")
        self.store.sample(reading, now - 31 * 86400)
        self.store.sample(reading, now - 50)
        self.store.sample(reading, now - 40)  # throttled
        self.store.sample(reading, now - 10)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 2)
        self.assertTrue(self.store.history(TAG, 1))
        self.store.update_settings({"mqtt_password": "test-secret"})
        self.assertNotIn("test-secret", json.dumps(self.store.settings(public=True)))
        self.store.update_settings({"mqtt_password": None})
        self.assertEqual(self.store.settings()["mqtt_password"], "test-secret")
        self.store.set_tag(TAG, "Keittiö", True)
        identity = self.store.settings()["instance_id"]
        self.store.close()
        self.store = Store(self.directory)
        self.assertEqual(self.store.settings()["instance_id"], identity)
        self.assertEqual(self.store.settings()["tags"][TAG]["name"], "Keittiö")
        self.assertEqual(len(self.store.history(TAG, 1)), 2)

    def test_settings_validation_is_atomic(self):
        before = self.store.settings()
        for values in (
            {"mqtt_port": 0},
            {"tray_metric": "invalid"},
            {"mqtt_enabled": "false"},
            {"tags": {}},
            {"mqtt_host": "bad/host"},
            {"tray_tag": []},
        ):
            with self.assertRaises(ValueError):
                self.store.update_settings(values)
            self.assertEqual(before, self.store.settings())

    def test_tray_metric_actions_persist_and_reflect_browser_changes(self):
        # Exercise menu callbacks without requiring a Windows desktop session.
        tray = Tray.__new__(Tray)
        tray.bridge = Bridge(self.store, self.directory, "http://127.0.0.1/", demo=True)
        icon = Mock()
        for metric in ("temperature", "humidity", "temperature"):
            tray.select_metric(metric)(icon, None)
            self.assertTrue(tray.metric_selected(metric)(None))
            other = "humidity" if metric == "temperature" else "temperature"
            self.assertFalse(tray.metric_selected(other)(None))
        self.assertEqual(icon.update_menu.call_count, 3)
        self.store.close()
        self.store = Store(self.directory)
        self.assertEqual(self.store.settings()["tray_metric"], "temperature")
        tray.bridge.store = self.store
        tray.bridge.update_settings({"tray_metric": "humidity"})
        self.assertTrue(tray.metric_selected("humidity")(None))

    def test_only_selected_tags_record_and_old_readings_go_stale(self):
        bridge = Bridge(self.store, self.directory, "http://127.0.0.1:8765/", demo=True)
        reading = decode(VALID, "")
        bridge.receive(reading, -50)
        self.assertFalse(self.store.history(TAG, 1))
        bridge.update_tag(TAG, "Testi", True)
        bridge.receive(reading, -50)
        self.assertTrue(self.store.history(TAG, 1))
        bridge.readings[TAG]["last_seen"] = time.time() - 181
        self.assertFalse(bridge.snapshot()["sensors"][0]["fresh"])

    def test_http_local_only_csrf_history_and_shutdown(self):
        bridge = Bridge(self.store, self.directory, "http://127.0.0.1/", demo=True)
        shutdown = Mock()
        server = create_server(bridge, 0, shutdown)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            response = urlopen(url + "/api/state")
            token = json.load(response)["token"]
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
            for headers in ({"Host": "evil.example"},):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(url + "/api/state", headers=headers))
                self.assertEqual(caught.exception.code, 403)
            for headers in ({}, {"X-Ruuvi-Token": token, "Origin": "http://evil.example"}):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(
                        Request(
                            url + "/api/settings",
                            data=b"{}",
                            headers={"Content-Type": "application/json", **headers},
                        )
                    )
                self.assertEqual(caught.exception.code, 403)
            valid = {"X-Ruuvi-Token": token, "Content-Type": "application/json"}
            urlopen(
                Request(url + "/api/settings", data=b'{"tray_metric":"temperature"}', headers=valid)
            )
            self.assertEqual(self.store.settings()["tray_metric"], "temperature")
            with self.assertRaises(HTTPError) as caught:
                urlopen(url + "/api/history?tag=bad&hours=100000")
            self.assertEqual(caught.exception.code, 400)
            urlopen(Request(url + "/api/shutdown", data=b"{}", headers=valid))
            shutdown.assert_called_once()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
