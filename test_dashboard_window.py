"""Tests for opening the dashboard in the embedded WebView2 host."""

import os
import tempfile
import unittest
from unittest.mock import patch

import main


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self):
        self.events = type("Events", (), {"closing": FakeEvent()})()
        self.calls = []

    def show(self):
        self.calls.append("show")

    def restore(self):
        self.calls.append("restore")

    def hide(self):
        self.calls.append("hide")


class FakeWebView:
    def __init__(self):
        self.calls = []
        self.window = FakeWindow()

    def create_window(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.window


class DashboardWindowTests(unittest.TestCase):
    def test_webview_window_uses_local_dashboard_and_persistent_profile(self):
        webview = FakeWebView()
        with tempfile.TemporaryDirectory() as data_dir:
            with patch.object(main.Config, "DB_FILE", os.path.join(data_dir, "history.db")):
                profile_dir = main._create_dashboard_window(webview, auto_open=False)
                self.assertTrue(os.path.isdir(profile_dir))

        args, kwargs = webview.calls[0]
        self.assertEqual(args[0], "SystemMonitor — Dashboard")
        self.assertEqual(
            args[1],
            f"http://localhost:{main.Config.SERVER_PORT}/dashboard?embedded=1",
        )
        self.assertTrue(kwargs["hidden"])
        self.assertEqual(profile_dir, os.path.join(data_dir, "WebView2"))

    def test_close_hides_window_when_tray_is_available(self):
        webview = FakeWebView()
        with tempfile.TemporaryDirectory() as data_dir:
            with patch.object(main.Config, "DB_FILE", os.path.join(data_dir, "history.db")):
                main._create_dashboard_window(webview, auto_open=True)

        handler = main.dashboard_window.events.closing.handlers[0]
        with patch.object(main, "tray_available", True):
            self.assertFalse(handler())
        self.assertEqual(webview.window.calls, ["hide"])

    def test_close_is_allowed_without_tray(self):
        webview = FakeWebView()
        with tempfile.TemporaryDirectory() as data_dir:
            with patch.object(main.Config, "DB_FILE", os.path.join(data_dir, "history.db")):
                main._create_dashboard_window(webview, auto_open=True)

        handler = main.dashboard_window.events.closing.handlers[0]
        with patch.object(main, "tray_available", False):
            self.assertIsNone(handler())
        self.assertEqual(webview.window.calls, [])

    def test_open_dashboard_restores_and_shows_embedded_window(self):
        window = FakeWindow()
        with patch.object(main, "dashboard_window", window), patch.object(
            main, "open_dashboard_in_browser"
        ) as open_browser:
            main.open_dashboard()

        self.assertEqual(window.calls, ["restore", "show"])
        open_browser.assert_not_called()

    def test_open_dashboard_reports_error_and_falls_back_to_browser(self):
        class BrokenWindow(FakeWindow):
            def show(self):
                raise RuntimeError("WebView2 unavailable")

        window = BrokenWindow()
        with patch.object(main, "dashboard_window", window), patch.object(
            main, "_show_webview_fallback"
        ) as show_error, patch.object(main, "open_dashboard_in_browser") as open_browser:
            main.open_dashboard()

        show_error.assert_called_once()
        open_browser.assert_called_once()

    def test_open_mobile_uses_selected_lan_address(self):
        with patch.object(main, "get_local_ip", return_value="192.168.0.196"), patch.object(
            main.webbrowser, "open"
        ) as open_browser:
            main.open_mobile()

        open_browser.assert_called_once_with(
            f"http://192.168.0.196:{main.Config.SERVER_PORT}/mobile"
        )


if __name__ == "__main__":
    unittest.main()
