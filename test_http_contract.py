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

    def test_theme_files_api_lists_css_and_javascript_files_from_project_theme_directory(self):
        response = self.client.get("/api/themes/files")
        self.assertEqual(response.status_code, 200)
        themes = response.get_json()["themes"]
        self.assertTrue(themes)
        self.assertIn("style-dos.css", [theme["name"] for theme in themes])
        self.assertIn("analog-gauge-theme.js", [theme["name"] for theme in themes])
        for theme in themes:
            self.assertTrue(theme["name"].lower().endswith((".css", ".js")))
            self.assertTrue(theme["url"].startswith("/static/css/themes/"))

    def test_dashboard_theme_panel_exposes_css_and_javascript_import_sources(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="projectThemeFileSelect"', html)
        self.assertIn('id="importProjectThemeBtn"', html)
        self.assertIn('id="importThemeFolderBtn"', html)
        self.assertIn('id="themeFolderInput" accept=".css,.js,text/css,text/javascript" webkitdirectory directory multiple', html)
        self.assertIn('id="themeFileInput" accept=".css,.js,.json,text/css,text/javascript,application/json"', html)
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
                        'id="importThemeBtn"',
                        'id="mobileQrBtn"',
                        'id="mobileQrPanel"',
                        'id="mobileQrImage"',
                    ):
                        self.assertIn(control, response.get_data(as_text=True))
                    html = response.get_data(as_text=True)
                    self.assertIn(
                        'renderCardIfChanged("smart", [d.smart, addedSensorData("smart")], function () { updateSmart(d); renderAdditionalCardSensors("smart"); });',
                        html,
                    )
                    for smart_display in (
                        'if (isNumber(disk.capacity_bytes) && disk.capacity_bytes > 0)',
                        'title += " · " + (disk.capacity_bytes / 1e9).toLocaleString("ru-RU"',
                        'line("Прошивка", disk.firmware_version || "—")',
                        'line("Серийный номер", disk.serial_number || "—")',
                        'line("Интерфейс", disk.interface || "—")',
                        'line("Режим передачи", disk.transfer_mode || "—")',
                        'line("Буква тома", disk.volume || "—")',
                        'line("Стандарт", disk.standard || "—")',
                        'Array.isArray(disk.capabilities) && disk.capabilities.length ? disk.capabilities.join(", ") : "—"',
                        'isNumber(disk.temperature) ? fmt(disk.temperature, 0, "°C") : "—"',
                        'isNumber(disk.power_on_hours) ? fmtInt(disk.power_on_hours, " ч") : "—"',
                        'isNumber(disk.power_cycles) ? fmtInt(disk.power_cycles) : "—"',
                        'line("Всего хост-чтений"',
                        'line("Всего хост-записей"',
                        'line("Скорость вращения", disk.rotation_label || "—")',
                        'line("Всего хост-записей", isNumber(disk.data_units_written)',
                    ):
                        self.assertIn(smart_display, html)
                    self.assertIn(
                        "startScrollTop = board.scrollTop;",
                        html,
                    )
                    self.assertIn(
                        "board.scrollTop += scrollStep; setDragPosition(e);",
                        html,
                    )
                    self.assertIn(
                        ".board::after { content: \"\"; display: block; height: var(--board-content-height, 0); pointer-events: none; }",
                        html,
                    )
                    self.assertIn(
                        'board.style.setProperty("--board-content-height", contentHeight + "px");',
                        html,
                    )
                    self.assertIn(
                        "else if (cardBottom > visibleBottom) board.scrollTop = cardBottom - board.clientHeight;",
                        html,
                    )
                    self.assertIn(
                        "html.embedded-dashboard .board { scrollbar-gutter: stable; }",
                        html,
                    )
                    self.assertNotIn("scaleCardsToBoardSize", html)
                    self.assertNotIn("layoutEmbeddedCards", html)
                    self.assertIn(
                        "return { rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height } };",
                        html,
                    )
                    self.assertIn(
                        "if (!embeddedMode) {\nsetWindowRect(fullscreenSnapshot.rect.left, fullscreenSnapshot.rect.top, fullscreenSnapshot.rect.width, fullscreenSnapshot.rect.height);\n}",
                        html,
                    )
                    menu_start = html.index('<details id="appearanceMenu"')
                    menu_end = html.index("</details>", menu_start) + len("</details>")
                    appearance_menu = html[menu_start:menu_end]
                    self.assertIn(
                        '<summary aria-controls="appearanceMenuPanel">🎨 Внешний вид',
                        appearance_menu,
                    )
                    self.assertIn("clip-path: inset(0 0 100% 0);", html)
                    self.assertIn("prefers-reduced-motion: reduce", html)
                    self.assertIn(".tools-menu > .tools-menu-panel { left: auto; right: 0; }", html)
                    self.assertIn(".titlebar { justify-content: flex-start; }", html)
                    self.assertIn(".titlebar { padding-right: 72px; }", html)
                    for control in (
                        'id="themeBtn"',
                        'id="themesBtn"',
                        'id="settingsBtn"',
                        'id="snapBtn"',
                        'id="gridSizeSelect"',
                        'id="alignGridBtn"',
                        'id="lockBtn"',
                        'id="resetLayoutBtn"',
                        'id="exportLayoutBtn"',
                        'id="importLayoutBtn"',
                        'id="presetsBtn"',
                        'id="exportAllDashboardsBtn"',
                        'id="importAllDashboardsBtn"',
                        'id="terminalSensorsBtn"',
                    ):
                        self.assertIn(control, appearance_menu)
                    tools_start = html.index('<details id="toolsMenu"')
                    tools_end = html.index("</details>", tools_start) + len("</details>")
                    tools_menu = html[tools_start:tools_end]
                    self.assertIn(
                        '<summary aria-controls="toolsMenuPanel">🧰 Инструменты',
                        tools_menu,
                    )
                    for control in (
                        'id="intervalSelect"',
                        'id="refreshBtn"',
                        'id="fullscreenBtn"',
                        'id="addCustomBtn"',
                        'id="addFpsCardBtn"',
                        'id="addDashboardTabBtn"',
                        'id="manageSourcesBtn"',
                        'id="mobileQrBtn"',
                        'id="logsBtn"',
                        'id="csvBtn"',
                        'id="historyCsvBtn"',
                        'id="sourceHistoryBtn"',
                        'id="temperatureAlertsBtn"',
                        'href="/all-sensors"',
                        'id="dashboardExtensionTools"',
                    ):
                        self.assertIn(control, tools_menu)
                    self.assertIn('toolbarGroup: document.getElementById("dashboardExtensionToolsGroup")', html)
                    self.assertIn('id="toastContainer" role="status" aria-live="polite"', html)
                    self.assertIn('downloadCsv("/export/csv", this', html)
                    self.assertIn('downloadCsv("/export/history-csv", this', html)
                    self.assertIn('Проверьте папку загрузок.', html)
                    self.assertIn('Нет данных для экспорта. Дождитесь обновления показаний.', html)
                    self.assertIn(".fps-panel-hidden { display: none !important; }", html)
                    self.assertIn(".dashboard-compact .fps-panel-heading {\npadding-right: 64px;", html)
                    self.assertIn(".dashboard-compact .dashboard-tabs {\npadding-right: 72px;", html)
                    self.assertIn(".dashboard-compact .source-status {\nflex: 1 1 auto;\nmin-width: 0;", html)
                    self.assertIn('id="fpsStatus"', html)
                    self.assertNotIn('id="fpsPanelCollapseBtn"', html)
                    self.assertIn('createFpsCardMetric("fpsCardCurrent"', response.get_data(as_text=True))
                    self.assertNotIn("scaleCardsToBoardSize", html)
                    self.assertNotIn("layoutEmbeddedCards", html)
                    self.assertIn(
                        "return { rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height } };",
                        html,
                    )
                    self.assertIn(
                        "if (!embeddedMode) {\nsetWindowRect(fullscreenSnapshot.rect.left, fullscreenSnapshot.rect.top, fullscreenSnapshot.rect.width, fullscreenSnapshot.rect.height);\n}",
                        html,
                    )

    def test_analog_gauge_theme_is_a_single_importable_package(self):
        package = self.client.get("/static/css/themes/analog-gauge-theme.js")
        theme_files = self.client.get("/api/themes/files")
        package_text = package.get_data(as_text=True)
        project_themes = theme_files.get_json()["themes"]
        package.close()
        theme_files.close()
        self.assertEqual(package.status_code, 200)
        self.assertIn(".analog-gauge-face", package_text)
        self.assertIn("SystemMonitorThemePackage", package_text)
        self.assertIn("api.toolbarGroup.hidden = false", package_text)
        self.assertIn("api.toolbarGroup.hidden = true", package_text)
        self.assertIn("function createAnalogGaugeTheme(api)", package_text)
        self.assertIn("function saveAnalogGaugeLayout()", package_text)
        self.assertIn("saveLayout: saveLayout", package_text)
        self.assertIn("layout[gauge.id]", package_text)
        self.assertIn(
            {
                "name": "analog-gauge-theme.js",
                "url": "/static/css/themes/analog-gauge-theme.js",
            },
            project_themes,
        )
        self.assertNotIn("analog-gauge-theme.css", [theme["name"] for theme in project_themes])
        self.assertNotIn("/static/js/analog-gauge-theme.js", [theme["url"] for theme in project_themes])
        self.assertEqual(self.client.get("/static/css/themes/analog-gauge-theme.css").status_code, 404)
        self.assertEqual(self.client.get("/static/js/analog-gauge-theme.js").status_code, 404)

        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("analog-gauge-theme.js", html)
        self.assertNotIn('id="dashboardDisplayModeBtn"', html)
        self.assertNotIn('id="analogGaugeThemeModeBtn"', html)
        self.assertNotIn('id="analogGaugePanel"', html)
        self.assertIn('id="importThemeBtn"', html)
        self.assertIn("function createDashboardThemeApi()", html)
        self.assertIn("function saveCurrentBoardLayout()", html)
        self.assertIn("activeBoardView.saveLayout()", html)
        self.assertIn("persistJsThemeImports", html)
        self.assertIn("JavaScript-тема может выполнять произвольный код", html)
        self.assertNotIn('id="themeFileBtn"', html)
        self.assertNotIn("window.SystemMonitorDashboardUI", html)

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
        self.assertIn("value === null || value === undefined || value === '' ? '—' : value", html)
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
