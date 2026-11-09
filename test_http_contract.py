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

    def test_theme_files_api_lists_css_files_from_project_theme_directory(self):
        response = self.client.get("/api/themes/files")
        self.assertEqual(response.status_code, 200)
        themes = response.get_json()["themes"]
        self.assertTrue(themes)
        self.assertIn("style-dos.css", [theme["name"] for theme in themes])
        for theme in themes:
            self.assertTrue(theme["name"].lower().endswith(".css"))
            self.assertTrue(theme["url"].startswith("/static/css/themes/"))

    def test_dashboard_theme_panel_exposes_css_import_sources(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="projectThemeFileSelect"', html)
        self.assertIn('id="importProjectThemeBtn"', html)
        self.assertIn('id="importThemeFolderBtn"', html)
        self.assertIn('id="themeFolderInput" accept=".css,text/css" webkitdirectory directory multiple', html)
        self.assertIn('id="themeFileInput" accept=".css,.json,text/css,application/json"', html)
        self.assertIn('function importCssThemeFiles(fileList)', html)
        self.assertIn('function importSelectedProjectTheme()', html)
        self.assertIn("function exportThemeObject(theme, fn)", html)
        self.assertIn("window.showSaveFilePicker({", html)
        self.assertIn('suggestedName: filename', html)
        self.assertIn('if (error && error.name === "AbortError") return false;', html)
        self.assertIn("Чтобы выбирать папку, включите запрос места сохранения", html)
        self.assertIn('eb.addEventListener("click", function () { exportThemeObject(t,', html)

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

    def test_stats_includes_smart_status(self):
        smart_status = {
            "enabled": True,
            "available": True,
            "status": "ready",
            "reason": None,
            "devices": [],
        }
        with patch("routes.get_smart_status", return_value=smart_status):
            response = self.client.get("/stats")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["smart"], smart_status)

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
                        'href="https://dalink.to/monsterhairy"',
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
                        'id="fpsPanelCompactBtn"',
                        'id="addFpsCardBtn"',
                        'id="fpsProcessSelect"',
                        'id="fpsAutoProcess"',
                        'data-card="fps"',
                        'id="mobileQrBtn"',
                        'id="mobileQrPanel"',
                        'id="mobileQrImage"',
                    ):
                        self.assertIn(control, response.get_data(as_text=True))
                    html = response.get_data(as_text=True)
                    self.assertIn(".fps-panel-hidden { display: none !important; }", html)
                    self.assertIn(".dashboard-compact .fps-panel-heading {\npadding-right: 64px;", html)
                    self.assertIn(".dashboard-compact .dashboard-tabs {\npadding-right: 72px;", html)
                    self.assertIn(".dashboard-compact .source-status {\nflex: 1 1 auto;\nmin-width: 0;", html)
                    self.assertIn('id="fpsStatus"', html)
                    self.assertNotIn('id="fpsPanelCollapseBtn"', html)
                    self.assertIn('createFpsCardMetric("fpsCardCurrent"', response.get_data(as_text=True))

    def test_desktop_analog_gauge_theme_exposes_sensor_picker_and_saved_gauge_controls(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for control in (
            'id="dashboardDisplayModeBtn"',
            'id="addAnalogGaugeBtn"',
            'id="analogGaugePanel"',
            "analog-gauge-resize-hint",
            'id="analogGaugeSource"',
            'id="analogGaugeTypeFilter"',
            'id="analogGaugeSensor"',
            'id="analogGaugeName"',
            'id="analogGaugeMin"',
            'id="analogGaugeMax"',
            'id="analogGaugeSize"',
            'id="analogGaugeSizeValue"',
            'id="analogGaugeSaveBtn"',
            'id="analogGaugeDeleteBtn"',
        ):
            with self.subTest(control=control):
                self.assertIn(control, html)
        self.assertIn('type="range" min="240" max="640" step="20" value="360"', html)
        self.assertIn('displayMode: "cards", analogGauges: []', html)
        self.assertIn("normalizeAnalogGaugeSettings", html)
        self.assertIn("selectableSensorEntries(sourceData[sourceId])", html)
        self.assertIn("rawByIdentifier = new Map(), rawByKey = new Map()", html)
        self.assertIn('var identifierKey = (sensor.gpu_identifier || "") + "||" + sensor.identifier', html)
        self.assertIn('rawByKey.get(key) || (typeof sensor.identifier === "string" && sensor.identifier ? rawByIdentifier.get((sensor.gpu_identifier || "") + "||" + sensor.identifier) : null)', html)
        self.assertIn("Object.assign({}, sensor, rawSensor)", html)
        self.assertIn("sensor.valid !== false && isValidAnalogGaugeReading(sensor.value)", html)
        self.assertIn("function analogGaugeUnavailableStatus(sensor)", html)
        self.assertIn('sensor.reason === "zero") return "CPU-сенсор вернул 0;', html)
        self.assertIn('sensor.reason === "zero" ? " · источник вернул 0"', html)
        self.assertIn('sensor.hardware_type !== "Cpu" || sensor.type !== "Clock"', html)
        self.assertIn('metadata["cpu.frequency"]', html)
        self.assertIn('"Резервный источник: " + sensor.fallbackSource', html)
        self.assertIn('<option value="Temperature">🌡️ Температура</option>', html)
        self.assertIn("analogGaugeTypeFilter.appendChild(option.cloneNode(true))", html)
        self.assertIn('groups.get(groupKey).appendChild(option)', html)
        self.assertIn('group.label = typeLabels.get(type) || (type || "Без типа")', html)
        self.assertIn('document.getElementById("analogGaugeTypeFilter").addEventListener("change"', html)
        self.assertIn("if (name && entry) name.value = analogGaugeSensorLabel", html)
        self.assertNotIn("if (name && !name.value.trim() && entry)", html)
        self.assertIn("body.analog-gauge-mode #addCustomBtn", html)
        self.assertNotIn("body.analog-gauge-mode #snapBtn", html)
        self.assertNotIn("body.analog-gauge-mode #gridSizeSelect", html)
        self.assertNotIn("body.analog-gauge-mode #alignGridBtn", html)
        self.assertIn('var analogMode = state.displayMode === "analog-gauges"', html)
        self.assertIn('selector = analogMode ? ".analog-gauge" : ".card"', html)
        scheduler_start = html.index("function scheduleWebSocketData(data)")
        scheduler_end = html.index("function rescheduleWebSocketData()", scheduler_start)
        scheduler = html[scheduler_start:scheduler_end]
        self.assertIn('if (state.displayMode === "analog-gauges") {', scheduler)
        self.assertIn("lastWebSocketRenderAt = Date.now();\nonData(data);\nreturn;", scheduler)
        self.assertIn("var remaining = state.interval - (Date.now() - lastWebSocketRenderAt);", scheduler)
        self.assertIn("function getAnalogGaugePositions()", html)
        self.assertIn('var visibilityChanged = state.displayMode !== "analog-gauges" && state.customCards.some(function (card)', html)
        self.assertIn('if (added || visibilityChanged) { if (added) saveState(); if (state.displayMode !== "analog-gauges") createCards(); }', html)
        self.assertIn("function makeDraggable(card, handle)", html)
        self.assertIn("makeDraggable(card, face)", html)
        self.assertIn('board.querySelectorAll(".card, .analog-gauge")', html)
        self.assertIn("function deleteCurrentAnalogGauge()", html)
        self.assertIn("function removeAnalogGauge(id)", html)
        self.assertNotIn("Переместить выше:", html)
        self.assertNotIn('createAnalogGaugeControl("×"', html)
        self.assertIn("resize: both;", html)
        self.assertIn(".analog-gauge-panel #analogGaugeSensor { flex: 1 1 240px;", html)
        self.assertIn("ANALOG_GAUGE_SENTINELS", html)
        self.assertIn("data-gauge-needle", html)
        self.assertIn("data-gauge-meter", html)
        self.assertIn("face.appendChild(settingsButton)", html)
        self.assertIn('settingsButton.className = "analog-gauge-settings"', html)
        self.assertIn('card.setAttribute("aria-label", gauge.name)', html)
        self.assertIn('var gaugeName = el("div", "analog-gauge-name", gauge.name)', html)
        self.assertIn("face.appendChild(gaugeName)", html)
        self.assertNotIn("analog-gauge-sensor", html)
        self.assertNotIn("ТЕКУЩЕЕ ПОКАЗАНИЕ", html)
        self.assertIn('value < gauge.min ? "Ниже диапазона" : value > gauge.max ? "Выше диапазона" : ""', html)
        self.assertIn(".analog-gauge-settings {", html)
        self.assertIn("background: rgba(221, 240, 238, .08);", html)
        self.assertIn("color: rgba(221, 240, 238, .48);", html)
        self.assertIn("opacity: .68;", html)
        self.assertIn("border: 0;\nbackground: transparent;\ncolor: #e2f0ef;", html)
        self.assertIn("border: 1px solid #294044;", html)
        self.assertIn("saveButton.disabled = !sensorSelect.value", html)
        self.assertIn("value < gauge.min ? \"Ниже диапазона\"", html)
        self.assertIn("size: size", html)
        self.assertIn('card.style.setProperty("--analog-gauge-width", gauge.size + "px")', html)
        self.assertIn("Math.round(size / 20) * 20", html)
        self.assertIn('document.getElementById("analogGaugeSizeValue").value = this.value + " px"', html)
        self.assertIn("display: block;\noverflow: auto;\nmin-height: min(60vh, 560px);", html)
        self.assertIn(".analog-gauge.dragging { cursor: grabbing; }", html)
        self.assertIn(".analog-gauge.locked { cursor: default; }", html)
        self.assertIn("state.analogGauges", html)
        self.assertIn("Пока нет приборов", html)

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
            'id="mobileControlPanel"',
            'id="mobileControlHandle"',
            'id="lockToggle"',
            'id="themeToggle"',
            'id="settingsToggle"',
            'id="historyToggle"',
            'id="presetsToggle"',
            'id="mobileFpsPanel"',
            'id="fpsPanelToggle"',
            'id="addFpsCardBtn"',
            'id="mobileFpsCard"',
            'id="removeFpsCardBtn"',
            'id="mobileFpsCardCurrent"',
            'id="mobileFpsStatus"',
            'id="mobileFpsProcessSelect"',
            'id="mobileFpsAutoProcess"',
            'id="dashboardScale"',
            'id="dashboardScaleValue"',
            'id="dashboardScaleReset"',
        ):
            with self.subTest(control=control):
                self.assertIn(control, html)
        self.assertIn(
            ".container { width: 100%; max-width: none; margin: 0 auto; }",
            html,
        )
        self.assertIn(
            ".fps-panel[hidden], .fps-custom-card[hidden] { display: none !important; }",
            html,
        )
        panel_start = html.index('<div class="mobile-control-panel"')
        panel_end = html.index('</div>\n        <button type="button" class="mobile-control-handle"', panel_start)
        for control in (
            'id="compactModeToggle"',
            'id="settingsToggle"',
            'id="lockToggle"',
            'id="themeToggle"',
            'id="historyToggle"',
            'id="presetsToggle"',
            'id="cmdSensorsToggle"',
            'id="fpsPanelToggle"',
            'id="addFpsCardBtn"',
        ):
            with self.subTest(side_menu_control=control):
                position = html.index(control)
                self.assertGreater(position, panel_start)
                self.assertLess(position, panel_end)
        self.assertNotIn('class="mobile-toolbar"', html)
        self.assertNotIn('id="cmdSettingsToggle"', html)
        self.assertNotIn('id="cmdHistoryToggle"', html)
        self.assertIn("max-height: min(82vh, 640px);", html)
        self.assertIn("overflow-y: auto;", html)
        self.assertIn("function setFpsPanelVisible(visible, persist)", html)
        self.assertIn("function setFpsCardVisible(visible, persist)", html)
        self.assertIn("function setFpsStatusMessage(message)", html)
        self.assertIn("function syncFpsControls()", html)
        self.assertIn("querySelectorAll('[data-fps-panel-toggle]')", html)
        self.assertIn("querySelectorAll('[data-fps-card-toggle]')", html)
        self.assertIn("parsed.showFpsCard === true", html)
        self.assertIn(
            'id="dashboardScale" type="range" min="75" max="150" step="5"',
            html,
        )
        self.assertIn(
            "const DASHBOARD_SCALE_KEY = 'systemMonitorDashboardScale.v1';",
            html,
        )
        self.assertIn("applyDashboardScale(this.value, true);", html)
        self.assertIn("applyDashboardScale(100, true);", html)
        self.assertIn(
            ".dashboard-scale-control input { flex: 1; min-width: 100px; "
            "min-height: 44px;",
            html,
        )
        self.assertIn(".dashboard-scale-control button { min-height: 44px;", html)
        self.assertIn('<option value="1000">1 сек</option>', html)
        self.assertIn('<option value="cmd">CMD (Windows 11)</option>', html)
        self.assertIn(
            'href="https://dalink.to/monsterhairy"', html
        )
        self.assertNotIn('<option value="200">0.2 сек</option>', html)
        self.assertNotIn('<option value="500">0.5 сек</option>', html)
        self.assertNotIn("user-scalable=no", html)

    def test_mobile_gpu_card_includes_desktop_standard_electrical_metrics(self):
        response = self.client.get("/mobile")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            "{ label: 'Напряжение', value: formatValue(gpu.voltage, 3, ' В') }",
            html,
        )
        self.assertIn(
            "{ label: 'Мощность', value: formatValue(gpu.power, 1, ' Вт') }",
            html,
        )
        self.assertIn("function getGpuStandardLines(gpu)", html)
        self.assertIn("const deviceKeys = devices.map(getGpuDeviceCardKey);", html)
        self.assertIn("result.lines = getGpuStandardLines(gpuMetrics);", html)
        self.assertIn("if (gpuDevices.length === 1)", html)
        self.assertNotIn(
            "result.lines = (Array.isArray(device.sensors) ? device.sensors : []).map",
            html,
        )
        self.assertIn("const extraRows = buildAdditionalSensorRows(cardKey);", html)

    def test_mobile_smart_card_supports_additional_sensors(self):
        response = self.client.get("/mobile")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            '<p id="smartSensorHint" class="sensor-context-hint" hidden>',
            html,
        )
        self.assertIn(
            "document.getElementById('smartSensorHint').hidden = cardKey !== 'smart';",
            html,
        )
        self.assertIn(
            'data-card-action="sensors" data-card-key="${cardKey}"',
            html,
        )
        self.assertIn(
            "const rows = (settings.cardSensors[cardKey] || []).map(key => {",
            html,
        )
        self.assertIn(
            '<div class="card-extra-heading" role="heading" aria-level="3">Дополнительные датчики</div>',
            html,
        )
        self.assertIn(
            "const heading = cardKey === 'smart' && rows.length",
            html,
        )

    def test_mobile_smart_health_state_is_visually_distinguished(self):
        response = self.client.get("/mobile")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(".value.ok { color: #51cf66; }", html)
        self.assertIn(
            "value: disk.health === 'passed' ? 'Исправен' : disk.health === 'failed' ? 'Есть предупреждение' : 'Неизвестно'",
            html,
        )
        self.assertIn(
            "cls: disk.health === 'failed' ? 'danger' : disk.health === 'passed' ? 'ok' : ''",
            html,
        )

    def test_mobile_smart_card_renders_reference_drive_summary_and_details(self):
        response = self.client.get("/mobile")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for marker in (
            'function buildSmartDriveHTML(disk)',
            'disk.capacity_bytes / 1e9).toLocaleString(\'ru-RU\'',
            'disk.device && !disk.volume',
            'Хорошо',
            'Техсостояние',
            'smart-drive-temperature',
            'smart-drive-details',
            "['Всего хост-чтений'",
            "['Всего хост-записей'",
            "['Часы работы'",
            "['Включения'",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_mobile_sensor_picker_keeps_touch_scroll_stable_during_updates(self):
        response = self.client.get("/mobile")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            ".modal-overlay { display: none; position: fixed; inset: 0; "
            "z-index: 1000; align-items: flex-start; justify-content: center; "
            "overflow-y: auto; overscroll-behavior-y: contain; "
            "-webkit-overflow-scrolling: touch; touch-action: pan-y;",
            html,
        )
        self.assertIn(
            ".mobile-modal { width: min(620px, 100%); margin: auto; "
            "overflow: visible; touch-action: pan-y;",
            html,
        )
        self.assertIn(".sensor-list { overflow: visible; touch-action: pan-y; }", html)
        self.assertIn('id="sensorScrollIndicator" role="scrollbar"', html)
        self.assertIn('id="sensorScrollThumb"', html)
        self.assertIn(
            ".modal-scrollbar { display: none; position: fixed; z-index: 1002; "
            "top: 12px; right: 12px; "
            "bottom: 12px; width: 8px; touch-action: none; }",
            html,
        )
        self.assertIn("background: rgba(205, 215, 235, .42); cursor: grab;", html)
        self.assertIn(".modal-scrollbar:hover .modal-scrollbar-thumb", html)
        self.assertIn("window.innerWidth - modalRight + 6", html)
        self.assertIn("function syncSensorScrollIndicator()", html)
        self.assertIn("setPointerCapture(event.pointerId)", html)
        self.assertIn("event.key === 'PageDown'", html)
        render_cards_start = html.index("function renderCards(data) {")
        render_cards_end = html.index("function renderFpsStatus(data)", render_cards_start)
        self.assertNotIn("renderSensorList();", html[render_cards_start:render_cards_end])
        self.assertIn("openModal('sensorOverlay');\n            renderSensorList();", html)

    @patch("routes.get_all_diagnostics", return_value={"status": "ok"})
    def test_diagnostics_contract(self, _diagnostics):
        response = self.client.get("/api/diagnostics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("providers", response.get_json())
