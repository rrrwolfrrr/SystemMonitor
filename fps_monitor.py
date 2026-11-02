"""Single-process FPS capture through the PresentMon ETW command-line tool."""

from __future__ import annotations

import csv
import ctypes
import logging
import math
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque

import psutil


logger = logging.getLogger(__name__)
PRESENTMON_NAME = "PresentMon-2.6.0-x64.exe"
CURRENT_SAMPLE_WINDOW_SECONDS = 3.0
IGNORED_FOREGROUND_PROCESSES = {
    "applicationframehost.exe",
    "dwm.exe",
    "explorer.exe",
    "searchhost.exe",
    "shellexperiencehost.exe",
    "systemmonitor.exe",
    "textinputhost.exe",
}


def presentmon_path():
    """Find the bundled PresentMon binary in source and one-dir builds."""
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(os.path.join(sys._MEIPASS, PRESENTMON_NAME))
    candidates.extend((
        os.path.join(os.path.dirname(os.path.abspath(__file__)), PRESENTMON_NAME),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "_internal", PRESENTMON_NAME),
    ))
    return next((path for path in candidates if os.path.isfile(path)), None)


def foreground_process_id():
    """Return the current foreground process on Windows, if it is trackable."""
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        pid = process_id.value
        if not pid or pid == os.getpid():
            return None
        try:
            name = psutil.Process(pid).name().lower()
        except psutil.Error:
            return None
        return None if name in IGNORED_FOREGROUND_PROCESSES else pid
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.debug("Не удалось определить активное окно: %s", exc)
        return None


class FPSMonitor:
    """Capture one selected or foreground process without injecting into it."""

    def __init__(self, executable=None):
        self.executable = executable or presentmon_path()
        self._session_name = "SystemMonitorFPS_%s" % os.getpid()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor_thread = None
        self._capture_thread = None
        self._process = None
        self._generation = 0
        self._mode = "auto"
        self._manual_pid = None
        self._target_pid = None
        self._target_name = None
        self._target_create_time = None
        self._status = "waiting_for_application"
        self._error = None
        self._frames = deque(maxlen=4000)

    def start(self):
        with self._lock:
            if self._monitor_thread and self._monitor_thread.is_alive():
                return
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(
                target=self._initialize_and_monitor,
                name="systemmonitor-fps",
                daemon=True,
            )
            self._monitor_thread.start()

    def stop(self):
        self._stop_event.set()
        self._stop_capture()
        thread = self._monitor_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _initialize_and_monitor(self):
        self._cleanup_orphaned_sessions()
        self._monitor_loop()

    def _cleanup_orphaned_sessions(self):
        if sys.platform != "win32" or not self.executable or not os.path.isfile(self.executable):
            return
        try:
            result = subprocess.run(
                ["logman", "query", "-ets"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Не удалось проверить оставшиеся FPS ETW-сессии: %s", exc)
            return
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "код %s" % result.returncode).strip()
            logger.warning("Не удалось проверить оставшиеся FPS ETW-сессии: %s", message)
            return

        session_pids = {
            int(pid) for pid in re.findall(r"\bSystemMonitorFPS_(\d+)\b", result.stdout)
        }
        for session_pid in sorted(session_pids):
            if psutil.pid_exists(session_pid):
                continue
            session_name = "SystemMonitorFPS_%s" % session_pid
            try:
                result = subprocess.run(
                    [
                        self.executable,
                        "--session_name", session_name,
                        "--terminate_existing_session",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=3,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("Не удалось остановить оставшуюся FPS ETW-сессию %s: %s", session_name, exc)
                continue
            if result.returncode != 0:
                message = (result.stderr or result.stdout or "код %s" % result.returncode).strip()
                logger.warning("Не удалось остановить оставшуюся FPS ETW-сессию %s: %s", session_name, message)
            else:
                logger.info("Остановлена оставшаяся FPS ETW-сессия %s", session_name)

    def list_processes(self):
        """Return bounded process choices without exposing command lines or paths."""
        processes = []
        for process in psutil.process_iter(attrs=["pid", "name"]):
            try:
                info = process.info
                pid = info.get("pid")
                name = info.get("name")
                if not pid or not name or pid == os.getpid():
                    continue
                if name.lower() in IGNORED_FOREGROUND_PROCESSES:
                    continue
                processes.append({"pid": pid, "name": name})
            except (psutil.Error, OSError):
                continue
        processes.sort(key=lambda item: (item["name"].casefold(), item["pid"]))
        return processes[:250]

    def set_target(self, mode, pid=None):
        if mode == "auto":
            with self._lock:
                restart = self._mode != "auto" or self._status in {
                    "capture_error",
                    "presentmon_unavailable",
                }
                self._mode = "auto"
                self._manual_pid = None
                self._error = None
            if restart:
                self._stop_capture()
                with self._lock:
                    self._target_pid = None
                    self._target_name = None
                    self._target_create_time = None
                    self._status = "waiting_for_application"
            return self.get_status()
        if mode != "manual":
            raise ValueError("Режим должен быть auto или manual")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError("Укажите корректный PID процесса")
        if pid == os.getpid():
            raise ValueError("SystemMonitor нельзя выбрать как целевой процесс")
        try:
            process = psutil.Process(pid)
            name = process.name()
            create_time = process.create_time()
            if not name:
                raise ValueError("У выбранного процесса не удалось определить имя")
        except psutil.NoSuchProcess as exc:
            raise ValueError("Выбранный процесс уже завершился") from exc
        except psutil.AccessDenied as exc:
            raise ValueError("Нет доступа к выбранному процессу") from exc
        with self._lock:
            restart = (
                self._mode == "manual"
                and self._manual_pid == pid
                and (
                    self._status in {"capture_error", "presentmon_unavailable", "process_exited"}
                    or self._target_create_time != create_time
                )
            )
            self._mode = "manual"
            self._manual_pid = pid
            self._error = None
        if restart:
            self._stop_capture()
            with self._lock:
                self._target_pid = None
                self._target_name = None
                self._target_create_time = None
                self._status = "waiting_for_frames"
        return self.get_status()

    def get_status(self):
        now = time.monotonic()
        with self._lock:
            mode = self._mode
            pid = self._target_pid
            name = self._target_name
            status = self._status
            error = self._error
            frames = list(self._frames)

        recent = [
            frame_ms for timestamp, frame_ms in frames
            if now - timestamp <= CURRENT_SAMPLE_WINDOW_SECONDS
        ]
        rolling = (
            [frame_ms for timestamp, frame_ms in frames if now - timestamp <= 30]
            if recent else []
        )
        if recent:
            status = "capturing"
        elif status == "capturing":
            status = "waiting_for_frames"

        current_fps = 1000 / (sum(recent) / len(recent)) if recent else None
        average_fps = 1000 / (sum(rolling) / len(rolling)) if rolling else None
        one_percent_low = None
        if rolling:
            slow_count = max(1, math.ceil(len(rolling) * 0.01))
            slowest = sorted(rolling, reverse=True)[:slow_count]
            one_percent_low = 1000 / (sum(slowest) / len(slowest))

        return {
            "mode": mode,
            "target": {"pid": pid, "name": name} if pid and name else None,
            "status": status,
            "error": error,
            "fps": round(current_fps, 1) if current_fps is not None else None,
            "average_fps": round(average_fps, 1) if average_fps is not None else None,
            "one_percent_low_fps": round(one_percent_low, 1) if one_percent_low is not None else None,
            "frame_time_ms": round(recent[-1], 2) if recent else None,
            "sample_count": len(rolling),
        }

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            with self._lock:
                mode = self._mode
                manual_pid = self._manual_pid
                current_pid = self._target_pid
                current_status = self._status
                target_create_time = self._target_create_time

            desired_pid = manual_pid if mode == "manual" else foreground_process_id()
            if desired_pid != current_pid:
                self._stop_capture()
                if desired_pid:
                    self._start_capture(desired_pid)
                else:
                    with self._lock:
                        self._target_pid = None
                        self._target_name = None
                        self._target_create_time = None
                        self._status = "waiting_for_application"
                        self._error = None
                        self._frames.clear()
            elif current_pid and current_status != "process_exited":
                try:
                    process = psutil.Process(current_pid)
                    process_is_same = (
                        target_create_time is None
                        or process.create_time() == target_create_time
                    )
                except psutil.NoSuchProcess:
                    process_is_same = False
                except psutil.AccessDenied:
                    logger.warning("Нет доступа для проверки целевого процесса PID %s", current_pid)
                    process_is_same = True
                if not process_is_same:
                    self._stop_capture()
                    with self._lock:
                        if self._mode == "auto":
                            self._target_pid = None
                            self._target_name = None
                            self._target_create_time = None
                            self._status = "waiting_for_application"
                        else:
                            self._status = "process_exited"
                        self._error = None
                        self._frames.clear()
            self._stop_event.wait(0.5)

    def _start_capture(self, pid):
        try:
            target_process = psutil.Process(pid)
            process_name = target_process.name()
            process_create_time = target_process.create_time()
        except psutil.Error:
            with self._lock:
                self._target_pid = pid
                self._target_name = None
                self._target_create_time = None
                self._status = "process_exited"
                self._error = None
            return

        with self._lock:
            self._target_pid = pid
            self._target_name = process_name
            self._target_create_time = process_create_time
            self._frames.clear()
            self._error = None
            if not self.executable or not os.path.isfile(self.executable):
                self._status = "presentmon_unavailable"
                self._process = None
                return
            self._status = "starting"
            self._generation += 1
            generation = self._generation

        command = [
            self.executable,
            "--session_name", self._session_name,
            "--stop_existing_session",
            "--process_id", str(pid),
            "--output_stdout",
            "--v2_metrics",
            "--no_console_stats",
            "--terminate_on_proc_exit",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8-sig",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            logger.warning("Не удалось запустить PresentMon: %s", exc)
            with self._lock:
                self._status = "capture_error"
                self._error = "Не удалось запустить сбор FPS"
            return

        threading.Thread(
            target=self._read_capture_diagnostics,
            args=(process,),
            name="systemmonitor-fps-diagnostics",
            daemon=True,
        ).start()

        with self._lock:
            cancelled = self._stop_event.is_set() or generation != self._generation
            self._process = process
            if cancelled:
                self._capture_thread = None
                self._status = "waiting_for_application"
            else:
                self._status = "waiting_for_frames"
                self._capture_thread = threading.Thread(
                    target=self._read_capture,
                    args=(process, pid, generation),
                    name="systemmonitor-fps-reader",
                    daemon=True,
                )
                self._capture_thread.start()
        if cancelled:
            self._stop_capture()
            return

    def _stop_capture(self):
        with self._lock:
            process = self._process
            self._process = None
            self._generation += 1
        if process and self.executable and os.path.isfile(self.executable):
            try:
                result = subprocess.run(
                    [
                        self.executable,
                        "--session_name", self._session_name,
                        "--terminate_existing_session",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode != 0:
                    logger.warning(
                        "PresentMon не подтвердил остановку ETW-сессии: %s",
                        (result.stderr or result.stdout or "код %s" % result.returncode).strip(),
                    )
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=1)
                except OSError as exc:
                    logger.debug("Не удалось остановить PresentMon: %s", exc)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except OSError as exc:
                        logger.debug("Не удалось завершить PresentMon: %s", exc)

    def _read_capture(self, process, pid, generation):
        try:
            if process.stdout is None:
                raise OSError("PresentMon не создал поток CSV")
            reader = csv.DictReader(process.stdout)
            for row in reader:
                frame_ms = self._frame_time(row)
                if frame_ms is None:
                    continue
                with self._lock:
                    if generation != self._generation or pid != self._target_pid:
                        return
                    self._frames.append((time.monotonic(), frame_ms))
                    self._status = "capturing"
            return_code = process.poll()
            if return_code not in (None, 0):
                self._set_capture_error(generation, "PresentMon завершил сбор с ошибкой")
            elif not self._stop_event.is_set():
                self._set_capture_error(generation, "Сбор PresentMon неожиданно завершился")
        except (OSError, csv.Error, UnicodeError) as exc:
            logger.warning("Ошибка чтения метрик PresentMon: %s", exc)
            self._set_capture_error(generation, "Не удалось прочитать данные FPS")
        finally:
            try:
                process.stdout.close()
            except (AttributeError, OSError):
                pass

    @staticmethod
    def _read_capture_diagnostics(process):
        if process.stderr is None:
            return
        try:
            for line in process.stderr:
                message = line.strip()
                if message:
                    logger.warning("PresentMon: %s", message)
        except (OSError, UnicodeError) as exc:
            logger.warning("Не удалось прочитать диагностику PresentMon: %s", exc)
        finally:
            try:
                process.stderr.close()
            except OSError:
                pass

    def _set_capture_error(self, generation, message):
        with self._lock:
            if generation == self._generation:
                self._status = "capture_error"
                self._error = message

    @staticmethod
    def _frame_time(row):
        values = {str(key).strip().lower(): value for key, value in row.items() if key}
        for key in (
            "frametime",
            "displayedtime",
            "msbetweendisplaychange",
            "msbetweenpresents",
        ):
            try:
                value = float(values.get(key, ""))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                return value
        return None
