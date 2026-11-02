"""Tests for the elevated logon-task autostart integration."""

import unittest
from unittest.mock import patch

import main


class AutostartTests(unittest.TestCase):
    def test_enable_creates_highest_privilege_interactive_logon_task(self):
        exe_path = r"C:\Program Files\SystemMonitor\SystemMonitor.exe"
        with (
            patch.object(main.sys, "platform", "win32"),
            patch.object(main.sys, "frozen", True, create=True),
            patch.object(main.sys, "executable", exe_path),
            patch.object(main, "_legacy_autostart_value", return_value=None),
            patch.object(main, "_run_schtasks", return_value=True) as run_task,
        ):
            self.assertTrue(main.set_autostart(True))

        run_task.assert_called_once_with([
            "/Create",
            "/SC", "ONLOGON",
            "/TN", main.AUTOSTART_TASK_NAME,
            "/TR", f'"{exe_path}"',
            "/RL", "HIGHEST",
            "/F",
            "/IT",
        ])

    def test_enable_uses_python_and_script_when_running_from_source(self):
        with (
            patch.object(main.sys, "platform", "win32"),
            patch.object(main.sys, "frozen", False, create=True),
            patch.object(main.sys, "executable", r"C:\Python\python.exe"),
            patch.object(main.sys, "argv", [r"D:\SystemMonitor\main.py"]),
            patch.object(main, "_legacy_autostart_value", return_value=None),
            patch.object(main, "_run_schtasks", return_value=True) as run_task,
        ):
            self.assertTrue(main.set_autostart(True))

        self.assertEqual(
            run_task.call_args.args[0][run_task.call_args.args[0].index("/TR") + 1],
            '"C:\\Python\\python.exe" "D:\\SystemMonitor\\main.py"',
        )

    def test_enable_rolls_back_task_if_legacy_entry_cannot_be_removed(self):
        with (
            patch.object(main.sys, "platform", "win32"),
            patch.object(main.sys, "frozen", True, create=True),
            patch.object(main, "_legacy_autostart_value", return_value="old.exe"),
            patch.object(main, "_remove_legacy_autostart", return_value=False),
            patch.object(main, "_run_schtasks", return_value=True) as run_task,
        ):
            self.assertFalse(main.set_autostart(True))

        self.assertEqual(run_task.call_count, 2)
        self.assertEqual(
            run_task.call_args_list[1].args[0],
            ["/Delete", "/TN", main.AUTOSTART_TASK_NAME, "/F"],
        )

    def test_disable_removes_task_and_legacy_registry_entry(self):
        with (
            patch.object(main.sys, "platform", "win32"),
            patch.object(main, "_autostart_task_exists", return_value=True),
            patch.object(main, "_run_schtasks", return_value=True) as run_task,
            patch.object(main, "_remove_legacy_autostart", return_value=True) as remove_old,
        ):
            self.assertTrue(main.set_autostart(False))

        run_task.assert_called_once_with(
            ["/Delete", "/TN", main.AUTOSTART_TASK_NAME, "/F"]
        )
        remove_old.assert_called_once_with()

    def test_disabled_task_without_legacy_entry_is_idempotent(self):
        with (
            patch.object(main.sys, "platform", "win32"),
            patch.object(main, "_autostart_task_exists", return_value=False),
            patch.object(main, "_remove_legacy_autostart", return_value=True),
            patch.object(main, "_run_schtasks") as run_task,
        ):
            self.assertTrue(main.set_autostart(False))

        run_task.assert_not_called()

    def test_enabled_state_migrates_legacy_run_entry(self):
        with (
            patch.object(main.sys, "platform", "win32"),
            patch.object(main, "_autostart_task_exists", return_value=False),
            patch.object(main, "_legacy_autostart_value", return_value='"old.exe"'),
        ):
            self.assertTrue(main.is_autostart_enabled())

    def test_failed_toggle_notifies_user(self):
        class FakeIcon:
            def __init__(self):
                self.notifications = []

            def notify(self, message, title):
                self.notifications.append((message, title))

            def update_menu(self):
                pass

        icon = FakeIcon()
        with (
            patch.object(main, "is_autostart_enabled", return_value=False),
            patch.object(main, "set_autostart", return_value=False),
            patch.object(main, "build_tray_menu", return_value=None),
        ):
            main.toggle_autostart(icon, None)

        self.assertEqual(len(icon.notifications), 1)
        self.assertIn("Не удалось изменить автозапуск", icon.notifications[0][0])


if __name__ == "__main__":
    unittest.main()
