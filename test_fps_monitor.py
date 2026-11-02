import io
import os
import subprocess
import time
import unittest
from unittest.mock import Mock, patch

from fps_monitor import FPSMonitor


class FPSMonitorTests(unittest.TestCase):
    def test_startup_cleanup_stops_only_orphaned_systemmonitor_sessions(self):
        monitor = FPSMonitor(executable=__file__)
        query_result = subprocess.CompletedProcess(
            args=["logman", "query", "-ets"],
            returncode=0,
            stdout=(
                "Name: SystemMonitorFPS_123\n"
                "Name: SystemMonitorFPS_456\n"
            ),
            stderr="",
        )
        stop_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("fps_monitor.sys.platform", "win32"),
            patch("fps_monitor.psutil.pid_exists", side_effect=lambda pid: pid == 456),
            patch("fps_monitor.subprocess.run", side_effect=[query_result, stop_result]) as run,
        ):
            monitor._cleanup_orphaned_sessions()

        self.assertEqual(run.call_count, 2)
        self.assertIn("SystemMonitorFPS_123", run.call_args_list[1].args[0])
        self.assertNotIn("SystemMonitorFPS_456", run.call_args_list[1].args[0])

    def test_capture_diagnostics_are_written_to_application_log(self):
        process = Mock(stderr=io.StringIO("warning: 12 ETW events were lost.\n"))

        with self.assertLogs("fps_monitor", level="WARNING") as captured:
            FPSMonitor._read_capture_diagnostics(process)

        self.assertIn("PresentMon: warning: 12 ETW events were lost.", captured.output[0])

    def test_v2_csv_row_uses_application_frame_time_for_uncapped_fps(self):
        self.assertEqual(
            FPSMonitor._frame_time({
                "Application": "quake_x64_steam.exe",
                "ProcessID": "4272",
                "PresentRuntime": "DXGI",
                "FrameTime": "16.8363",
                "DisplayedTime": "16.4106",
            }),
            16.8363,
        )

    def test_v2_csv_row_falls_back_to_frame_time_when_not_displayed(self):
        self.assertEqual(
            FPSMonitor._frame_time({
                "FrameTime": "16.8363",
                "DisplayedTime": "NA",
            }),
            16.8363,
        )

    def test_frame_time_prefers_displayed_frame_interval(self):
        self.assertEqual(
            FPSMonitor._frame_time({
                "MsBetweenDisplayChange": "16.67",
                "MsBetweenPresents": "8.33",
            }),
            16.67,
        )

    def test_frame_time_falls_back_to_present_interval_and_rejects_invalid_values(self):
        self.assertEqual(FPSMonitor._frame_time({"MsBetweenPresents": "10"}), 10.0)
        self.assertIsNone(FPSMonitor._frame_time({"MsBetweenPresents": "nan"}))
        self.assertIsNone(FPSMonitor._frame_time({"MsBetweenPresents": "0"}))

    def test_frame_time_does_not_cap_very_high_fps(self):
        frame_time_ms = 0.001
        self.assertEqual(FPSMonitor._frame_time({"FrameTime": str(frame_time_ms)}), frame_time_ms)
        self.assertGreater(1000 / frame_time_ms, 100000)

    def test_recent_metrics_are_computed_without_zero_fps_fallback(self):
        monitor = FPSMonitor(executable="missing-presentmon.exe")
        now = time.monotonic()
        monitor._target_pid = 123
        monitor._target_name = "game.exe"
        monitor._status = "capturing"
        monitor._frames.extend([
            (now - 0.4, 16.0),
            (now - 0.2, 16.0),
            (now - 0.1, 32.0),
        ])

        status = monitor.get_status()

        self.assertEqual(status["status"], "capturing")
        self.assertEqual(status["fps"], 46.9)
        self.assertEqual(status["average_fps"], 46.9)
        self.assertEqual(status["one_percent_low_fps"], 31.2)
        self.assertEqual(status["frame_time_ms"], 32.0)
        self.assertEqual(status["target"], {"pid": 123, "name": "game.exe"})

    def test_stale_samples_return_waiting_status_and_empty_metrics(self):
        monitor = FPSMonitor(executable="missing-presentmon.exe")
        now = time.monotonic()
        monitor._status = "capturing"
        monitor._frames.append((now - 5, 16.0))

        status = monitor.get_status()

        self.assertEqual(status["status"], "waiting_for_frames")
        self.assertIsNone(status["fps"])
        self.assertIsNone(status["average_fps"])
        self.assertIsNone(status["one_percent_low_fps"])

    def test_recent_frame_is_not_dropped_during_short_capture_jitter(self):
        monitor = FPSMonitor(executable="missing-presentmon.exe")
        monitor._status = "capturing"
        monitor._frames.append((time.monotonic() - 2, 16.0))

        status = monitor.get_status()

        self.assertEqual(status["status"], "capturing")
        self.assertEqual(status["fps"], 62.5)

    def test_manual_target_rejects_systemmonitor_process(self):
        monitor = FPSMonitor()
        with self.assertRaises(ValueError):
            monitor.set_target("manual", os.getpid())

    def test_manual_target_accepts_an_existing_process(self):
        process = Mock()
        process.name.return_value = "game.exe"
        monitor = FPSMonitor()

        with patch("fps_monitor.psutil.Process", return_value=process):
            status = monitor.set_target("manual", 12345)

        self.assertEqual(status["mode"], "manual")
        self.assertIsNone(status["target"])

    def test_missing_presentmon_is_explicit_and_does_not_claim_zero_fps(self):
        process = Mock()
        process.name.return_value = "game.exe"
        monitor = FPSMonitor(executable="missing-presentmon.exe")

        with patch("fps_monitor.psutil.Process", return_value=process):
            monitor._start_capture(12345)

        status = monitor.get_status()
        self.assertEqual(status["status"], "presentmon_unavailable")
        self.assertIsNone(status["fps"])
        self.assertEqual(status["target"], {"pid": 12345, "name": "game.exe"})


if __name__ == "__main__":
    unittest.main()
