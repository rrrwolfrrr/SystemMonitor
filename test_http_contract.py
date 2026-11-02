"""Dependency-light HTTP contract tests for the public Flask endpoints."""

import unittest
from unittest.mock import patch

from flask import Flask

from config import Config
from routes import register_routes


class FakeCache:
    last_update = None

    def get(self):
        return {
            "timestamp": 1,
            "raw_sensors": [{
                "hardware": "CPU",
                "subhardware": None,
                "type": "Load",
                "name": "Load",
                "value": 0.0,
                "unit": "%",
                "identifier": "cpu/load",
            }],
            "unknown_sensors": [],
        }

    def get_history(self):
        return []

    def get_recent_history(self, hours=24):
        return [{"timestamp": "2026-10-20T12:00:00+00:00", "cpu_temp": 52.0}]


class FakeLibre:
    def is_running(self):
        return False


class FakeFPSMonitor:
    def __init__(self):
        self.target = None
        self.mode = "auto"

    def get_status(self):
        return {
            "mode": self.mode,
            "target": self.target,
            "status": "waiting_for_application",
            "error": None,
            "fps": None,
            "average_fps": None,
            "one_percent_low_fps": None,
            "frame_time_ms": None,
            "sample_count": 0,
        }

    def list_processes(self):
        return [{"pid": 123, "name": "game.exe"}]

    def set_target(self, mode, pid=None):
        self.mode = mode
        self.target = {"pid": pid, "name": "game.exe"} if pid else None
        return self.get_status()


class HttpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__, template_folder="templates")
        cls.fps = FakeFPSMonitor()
        register_routes(cls.app, FakeCache(), FakeLibre(), fps_monitor_instance=cls.fps)
        cls.client = cls.app.test_client()

    def test_sensor_api_preserves_raw_payload(self):
        response = self.client.get("/api/sensors")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["sensors"]), 1)
        self.assertEqual(payload["sensors"][0]["identifier"], "cpu/load")

    def test_health_contract(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_fps_api_includes_stats_and_manual_process_controls(self):
        stats = self.client.get("/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.get_json()["fps"]["status"], "waiting_for_application")
        self.assertEqual(self.client.get("/api/fps").get_json()["fps"], None)
        self.assertEqual(
            self.client.get("/api/fps/processes").get_json()["processes"],
            [{"pid": 123, "name": "game.exe"}],
        )

        response = self.client.post("/api/fps/target", json={"mode": "manual", "pid": 123})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["target"], {"pid": 123, "name": "game.exe"})
        response = self.client.post("/api/fps/target", json={"mode": "auto"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mode"], "auto")

    def test_fps_target_rejects_invalid_request(self):
        for payload in (None, {}, {"mode": "other"}, {"mode": "manual", "pid": "bad"}):
            with self.subTest(payload=payload):
                response = self.client.post("/api/fps/target", json=payload)
                self.assertEqual(response.status_code, 400)

    def test_mobile_dashboard_qr_uses_private_lan_address(self):
        with patch("routes.get_local_ip", return_value="192.168.1.25"):
            response = self.client.get("/api/mobile-dashboard-qr")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            payload["url"],
            f"http://192.168.1.25:{Config.SERVER_PORT}/mobile",
        )
        self.assertIn("<svg", payload["svg"])
        self.assertIn("<path", payload["svg"])

    def test_mobile_dashboard_qr_requires_a_private_lan_address(self):
        for address in ("127.0.0.1", "169.254.1.5", "8.8.8.8"):
            with self.subTest(address=address), patch("routes.get_local_ip", return_value=address):
                response = self.client.get("/api/mobile-dashboard-qr")
                self.assertEqual(response.status_code, 503)
                self.assertIn("локальной сети", response.get_json()["error"])

    def test_local_history_data_returns_recent_sensor_rows(self):
        response = self.client.get("/history-data?hours=12")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["cpu_temp"], 52.0)

    def test_remote_stats_only_proxies_private_ipv4_stats(self):
        class RemoteResponse:
            status = 200
            def read(self, _limit):
                return b'{"cpu":{"load":12.5}}'

        class RemoteConnection:
            def __init__(self, host, port, timeout):
                self.host, self.port, self.timeout = host, port, timeout

            def request(self, method, path):
                self.requested = (method, path)

            def getresponse(self):
                return RemoteResponse()

            def close(self):
                pass

        with patch("routes.http.client.HTTPConnection", RemoteConnection):
            response = self.client.post(
                "/api/remote-stats",
                json={"address": "192.168.0.196", "port": 5000},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"cpu": {"load": 12.5}})

    def test_remote_stats_rejects_public_and_non_ip_addresses(self):
        for address in ("8.8.8.8", "localhost", "127.0.0.1", "169.254.1.2"):
            with self.subTest(address=address):
                response = self.client.post(
                    "/api/remote-stats", json={"address": address, "port": 5000}
                )
                self.assertEqual(response.status_code, 400)
        for port in (True, "5000", 0, 65536):
            with self.subTest(port=port):
                response = self.client.post(
                    "/api/remote-stats",
                    json={"address": "192.168.0.196", "port": port},
                )
                self.assertEqual(response.status_code, 400)

    def test_remote_stats_rejects_oversized_response(self):
        class RemoteResponse:
            status = 200

            def read(self, limit):
                self.asserted_limit = limit
                return b"x" * limit

        class RemoteConnection:
            def __init__(self, *_args, **_kwargs):
                pass

            def request(self, *_args, **_kwargs):
                pass

            def getresponse(self):
                return RemoteResponse()

            def close(self):
                pass

        with patch("routes.http.client.HTTPConnection", RemoteConnection):
            response = self.client.post(
                "/api/remote-stats",
                json={"address": "192.168.0.196", "port": 5000},
            )
        self.assertEqual(response.status_code, 502)
        self.assertIn("1 МБ", response.get_json()["error"])

    def test_remote_history_proxies_bounded_history_from_private_ipv4(self):
        class RemoteResponse:
            status = 200

            def read(self, _limit):
                return b'[{"timestamp":"2026-10-20T12:00:00+00:00","gpu_temp":64.5}]'

        class RemoteConnection:
            def __init__(self, host, port, timeout):
                self.host, self.port, self.timeout = host, port, timeout

            def request(self, method, path):
                self.requested = (method, path)

            def getresponse(self):
                return RemoteResponse()

            def close(self):
                pass

        with patch("routes.http.client.HTTPConnection", RemoteConnection):
            response = self.client.post(
                "/api/remote-history",
                json={"address": "192.168.0.196", "port": 5000, "hours": 12},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            [{"timestamp": "2026-10-20T12:00:00+00:00", "gpu_temp": 64.5}],
        )

    def test_remote_history_rejects_oversized_response(self):
        class RemoteResponse:
            status = 200

            def read(self, limit):
                return b"x" * limit

        class RemoteConnection:
            def __init__(self, *_args, **_kwargs):
                pass

            def request(self, *_args, **_kwargs):
                pass

            def getresponse(self):
                return RemoteResponse()

            def close(self):
                pass

        with patch("routes.http.client.HTTPConnection", RemoteConnection):
            response = self.client.post(
                "/api/remote-history",
                json={"address": "192.168.0.196", "port": 5000, "hours": 24},
            )
        self.assertEqual(response.status_code, 502)
        self.assertIn("1 МБ", response.get_json()["error"])

    def test_remote_history_rejects_invalid_targets_and_periods(self):
        for address in ("8.8.8.8", "localhost", "127.0.0.1", "169.254.1.2"):
            with self.subTest(address=address):
                response = self.client.post(
                    "/api/remote-history",
                    json={"address": address, "port": 5000, "hours": 24},
                )
                self.assertEqual(response.status_code, 400)
        for hours in (True, "24", 0, 721):
            with self.subTest(hours=hours):
                response = self.client.post(
                    "/api/remote-history",
                    json={"address": "192.168.0.196", "port": 5000, "hours": hours},
                )
                self.assertEqual(response.status_code, 400)

    def test_dashboard_routes_render(self):
        for path in ("/dashboard", "/all-sensors", "/dashboard/sensors"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                if path == "/dashboard":
                    self.assertIn(
                        'href="https://www.donationalerts.com/r/monsterhairy"',
                        response.get_data(as_text=True),
                    )
                    for control in (
                        'id="dashboardTabs"',
                        'id="addDashboardTabBtn"',
                        'id="manageSourcesBtn"',
                        'id="cardSourceSelect"',
                        'id="customSourceSelect"',
                        'id="customDeviceFilter"',
                        'id="cardDeviceFilter"',
                        'id="sourceHistoryPanel"',
                        'id="temperatureAlertsPanel"',
                        'id="exportAllDashboardsBtn"',
                        'id="importAllDashboardsBtn"',
                        'id="fpsPanel"',
                        'id="fpsPanelCollapseBtn"',
                        'id="addFpsCardBtn"',
                        'id="fpsProcessSelect"',
                        'id="fpsAutoProcess"',
                        'data-card="fps"',
                        'id="mobileQrBtn"',
                        'id="mobileQrPanel"',
                        'id="mobileQrImage"',
                    ):
                        self.assertIn(control, response.get_data(as_text=True))
                    self.assertIn('createFpsCardMetric("fpsCardCurrent"', response.get_data(as_text=True))

    def test_mobile_dashboard_exposes_mobile_controls_and_minimum_refresh_interval(self):
        response = self.client.get("/mobile")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for control in (
            'id="favoritesOverview"',
            'id="sensorOverlay"',
            'id="historyOverlay"',
            'id="presetsOverlay"',
            'id="connectionStatus"',
            'id="cmdTerminal"',
            'id="cmdSensorRows"',
            'id="cmdSensorsToggle"',
            'id="mobileFpsStatus"',
            'id="mobileFpsProcessSelect"',
            'id="mobileFpsAutoProcess"',
        ):
            with self.subTest(control=control):
                self.assertIn(control, html)
        self.assertIn('<option value="1000">1 сек</option>', html)
        self.assertIn('<option value="cmd">CMD (Windows 11)</option>', html)
        self.assertIn(
            'href="https://www.donationalerts.com/r/monsterhairy"', html
        )
        self.assertNotIn('<option value="200">0.2 сек</option>', html)
        self.assertNotIn('<option value="500">0.5 сек</option>', html)
        self.assertNotIn("user-scalable=no", html)

    @patch("routes.get_all_diagnostics", return_value={"status": "ok"})
    def test_diagnostics_contract(self, _diagnostics):
        response = self.client.get("/api/diagnostics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("providers", response.get_json())
