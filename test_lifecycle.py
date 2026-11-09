"""Checks that importing the server does not start background services."""

import logging
import pathlib
import unittest
from unittest.mock import patch


class LifecycleTests(unittest.TestCase):
    def test_import_has_no_running_threads(self):
        import server_core

        self.assertIsNone(server_core.ws_thread)
        self.assertIsNone(server_core.updater_thread)

    def test_background_refresh_wait_uses_only_remaining_interval(self):
        import server_core

        with patch("server_core.time.monotonic", return_value=10.4):
            self.assertAlmostEqual(server_core._remaining_update_wait(10.0, 1.0), 0.6)
        with patch("server_core.time.monotonic", return_value=11.2):
            self.assertEqual(server_core._remaining_update_wait(10.0, 1.0), 0.0)

    def test_websocket_protocol_debug_logging_is_disabled(self):
        import server_core

        self.assertEqual(
            logging.getLogger("websockets").getEffectiveLevel(),
            logging.WARNING,
        )

    def test_lhm_updates_devices_independently_with_a_bounded_wait(self):
        project_root = pathlib.Path(__file__).resolve().parent
        adapter = (project_root / "LhmVisitorAdapter.cs").read_text(encoding="utf-8")
        self.assertIn("ConcurrentDictionary<IHardware, Stopwatch>", adapter)
        self.assertIn("Task.Factory.StartNew", adapter)
        self.assertIn("Task.WaitAll(tasks.ToArray(), UpdateWaitMilliseconds)", adapter)
        self.assertIn("private const int UpdateWaitMilliseconds = 750;", adapter)
        self.assertIn("if (!ActiveUpdates.TryAdd(hardware, stopwatch))", adapter)
        loader = (project_root / "libre_monitor.py").read_text(encoding="utf-8")
        self.assertIn('adapter_path = os.path.join(adapter_dir, "LhmVisitorAdapter.PerDevice.dll")', loader)

    def test_slow_lhm_hardware_is_reported_once_and_then_on_recovery(self):
        import libre_monitor

        monitor = libre_monitor.LibreMonitorDirect.__new__(libre_monitor.LibreMonitorDirect)
        monitor._pending_hardware_updates = set()
        with self.assertLogs("libre_monitor", level="WARNING") as first:
            monitor._report_update_status(["pending:AMD Radeon RX 9070 XT"])
        self.assertIn("AMD Radeon RX 9070 XT", first.output[0])

        with self.assertLogs("libre_monitor", level="INFO") as recovered:
            monitor._report_update_status([])
        self.assertIn("Опрос оборудования LHM завершён", recovered.output[0])
