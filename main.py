#!/usr/bin/env python3
"""
SystemMonitor — точка входа с системным треем.
Запускает сервер в фоне и показывает иконку в трее.
Управляет автозапуском и автооткрытием дашборда через реестр.
"""

import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from logging_setup import configure_logging
from config import Config
from network_utils import get_local_ip

# Настройка логирования
configure_logging(Config.LOG_FILE, Config.DEBUG)
logger = logging.getLogger(__name__)
dashboard_window = None
dashboard_window_error = None
tray_available = False

# Импорт ядра сервера
import server_core

# Путь в реестре для настроек приложения
SETTINGS_REG_PATH = r"Software\SystemMonitor"

# ============================================================
# УНИВЕРСАЛЬНАЯ РАБОТА С РЕЕСТРОМ
# ============================================================

def get_setting(name, default=None):
    """Читает настройку из реестра."""
    if sys.platform != "win32":
        return default
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            SETTINGS_REG_PATH,
            0, winreg.KEY_READ
        )
        value, _ = winreg.QueryValueEx(key, name)
        winreg.CloseKey(key)
        return value
    except FileNotFoundError:
        return default
    except Exception as e:
        logger.error(f"Ошибка чтения настройки {name}: {e}")
        return default


def set_setting(name, value):
    """Записывает настройку в реестр."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            SETTINGS_REG_PATH
        )
        if isinstance(value, bool):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))
        elif isinstance(value, int):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
        else:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
        winreg.CloseKey(key)
        return True
    except Exception as e:
        logger.error(f"Ошибка записи настройки {name}: {e}")
        return False


# ============================================================
# АВТОЗАПУСК (Планировщик заданий)
# ============================================================

AUTOSTART_TASK_NAME = "SystemMonitor-AutoStart"
AUTOSTART_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _schtasks_path():
    windows_dir = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(windows_dir, "System32", "schtasks.exe")


def _run_schtasks(arguments):
    try:
        result = subprocess.run(
            [_schtasks_path(), *arguments],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        logger.error("Не удалось запустить Планировщик заданий: %s", exc)
        return False
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        logger.error(
            "Команда Планировщика заданий завершилась с кодом %s: %s",
            result.returncode,
            details or "подробности не предоставлены",
        )
        return False
    return True


def _autostart_task_exists():
    try:
        result = subprocess.run(
            [_schtasks_path(), "/Query", "/TN", AUTOSTART_TASK_NAME],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        logger.error("Не удалось проверить задание автозапуска: %s", exc)
        return False
    return result.returncode == 0


def _legacy_autostart_value():
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_RUN_KEY,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            return winreg.QueryValueEx(key, "SystemMonitor")[0]
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.error("Не удалось проверить старую запись автозапуска: %s", exc)
        return None


def _remove_legacy_autostart():
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, "SystemMonitor")
            except FileNotFoundError:
                pass
        return True
    except FileNotFoundError:
        return True
    except Exception as exc:
        logger.error("Не удалось удалить старую запись автозапуска: %s", exc)
        return False


def is_autostart_enabled():
    """Проверяет задание автозапуска и совместимую старую запись Run."""
    if sys.platform != "win32":
        return False
    return _autostart_task_exists() or _legacy_autostart_value() is not None


def set_autostart(enabled):
    """Creates or removes an elevated at-logon task for the current user."""
    if sys.platform != "win32":
        return False
    if enabled:
        if getattr(sys, "frozen", False):
            action = f'"{sys.executable}"'
        else:
            script_path = os.path.abspath(sys.argv[0])
            action = f'"{sys.executable}" "{script_path}"'
        legacy_value = _legacy_autostart_value()
        task_created = _run_schtasks([
            "/Create",
            "/SC", "ONLOGON",
            "/TN", AUTOSTART_TASK_NAME,
            "/TR", action,
            "/RL", "HIGHEST",
            "/F",
            "/IT",
        ])
        if not task_created:
            return False
        if legacy_value is not None and not _remove_legacy_autostart():
            _run_schtasks(["/Delete", "/TN", AUTOSTART_TASK_NAME, "/F"])
            return False
        logger.info("Автозапуск включён через Планировщик заданий: %s", action)
        return True

    if _autostart_task_exists() and not _run_schtasks(
        ["/Delete", "/TN", AUTOSTART_TASK_NAME, "/F"]
    ):
        return False
    if not _remove_legacy_autostart():
        return False
    logger.info("Автозапуск выключен")
    return True


def toggle_autostart(icon, item):
    """Переключает автозапуск из меню трея."""
    new_state = not is_autostart_enabled()
    changed = set_autostart(new_state)
    if icon:
        try:
            if changed:
                message = "Автозапуск включён" if new_state else "Автозапуск выключен"
            else:
                message = "Не удалось изменить автозапуск. Подробности — в журнале."
            icon.notify(message, "SystemMonitor")
        except Exception as exc:
            logger.warning("Не удалось показать уведомление об автозапуске: %s", exc)
        icon.menu = build_tray_menu()
        icon.update_menu()


# ============================================================
# АВТООТКРЫТИЕ ДАШБОРДА
# ============================================================

def is_auto_open_dashboard_enabled():
    """Проверяет, включено ли автооткрытие дашборда при старте."""
    value = get_setting("AutoOpenDashboard", 1)  # По умолчанию включено
    return bool(value)


def set_auto_open_dashboard(enabled):
    """Включает/выключает автооткрытие дашборда."""
    result = set_setting("AutoOpenDashboard", int(enabled))
    if result:
        state = "включено" if enabled else "выключено"
        logger.info(f"Автооткрытие дашборда {state}")
    return result


def toggle_auto_open_dashboard(icon, item):
    """Переключает автооткрытие дашборда из меню трея."""
    new_state = not is_auto_open_dashboard_enabled()
    set_auto_open_dashboard(new_state)
    if icon:
        icon.menu = build_tray_menu()
        icon.update_menu()


# ============================================================
# ОТКРЫТИЕ СТРАНИЦ В БРАУЗЕРЕ
# ============================================================

def open_dashboard():
    """Открывает Dashboard в отдельном окне WebView2."""
    global dashboard_window_error
    if dashboard_window is not None:
        try:
            dashboard_window.restore()
            dashboard_window.show()
            return
        except Exception as e:
            dashboard_window_error = str(e)
            logger.exception("Не удалось показать окно Dashboard")
            _show_webview_fallback(e)
            open_dashboard_in_browser()
            return
    if dashboard_window_error:
        _show_webview_fallback(dashboard_window_error)
    open_dashboard_in_browser()


def open_dashboard_in_browser():
    """Открывает Dashboard в браузере по умолчанию."""
    ip = get_local_ip()
    port = Config.SERVER_PORT
    url = f"http://{ip}:{port}/dashboard"
    if not webbrowser.open(url):
        logger.error("Не удалось открыть Dashboard в браузере: %s", url)


def _create_dashboard_window(webview, auto_open):
    """Create the WebView2 host and keep its profile in the user data folder."""
    global dashboard_window
    profile_dir = os.path.join(os.path.dirname(Config.DB_FILE), "WebView2")
    os.makedirs(profile_dir, exist_ok=True)
    dashboard_window = webview.create_window(
        "SystemMonitor — Dashboard",
        f"http://localhost:{Config.SERVER_PORT}/dashboard?embedded=1",
        width=1280,
        height=800,
        min_size=(700, 450),
        hidden=not auto_open,
    )

    def hide_dashboard_on_close():
        if tray_available:
            dashboard_window.hide()
            return False
        return None

    dashboard_window.events.closing += hide_dashboard_on_close
    return profile_dir


def _show_webview_fallback(error):
    """Explains the WebView2 fallback before opening Dashboard in a browser."""
    message = (
        "Не удалось запустить окно Dashboard на WebView2.\n\n"
        f"{error}\n\n"
        "Dashboard будет открыт в браузере. Проверьте установку WebView2 Runtime."
    )
    logger.error(message)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "SystemMonitor", 0x10)
        except Exception:
            logger.exception("Не удалось показать сообщение об ошибке WebView2")


def open_mobile():
    """Открывает мобильную версию."""
    ip = get_local_ip()
    port = Config.SERVER_PORT
    webbrowser.open(f"http://{ip}:{port}/mobile")


def open_history():
    """Открывает страницу истории."""
    ip = get_local_ip()
    port = Config.SERVER_PORT
    webbrowser.open(f"http://{ip}:{port}/history-page")


def open_logs():
    """Открывает страницу логов."""
    ip = get_local_ip()
    port = Config.SERVER_PORT
    webbrowser.open(f"http://{ip}:{port}/logs")


# ============================================================
# МЕНЮ ТРЕЯ
# ============================================================

def build_tray_menu():
    """Создаёт меню трея с пунктами автозапуска и автооткрытия."""
    try:
        import pystray

        # Автозапуск
        autostart_enabled = is_autostart_enabled()
        autostart_label = "✓ Автозапуск при старте ПК" if autostart_enabled else "Автозапуск при старте ПК"

        # Автооткрытие дашборда
        auto_open_enabled = is_auto_open_dashboard_enabled()
        auto_open_label = "✓ Открывать дашборд при запуске" if auto_open_enabled else "Открывать дашборд при запуске"

        menu = pystray.Menu(
            pystray.MenuItem(
                "Открыть Dashboard (окно приложения)",
                lambda icon, item: open_dashboard(),
                default=True
            ),
            pystray.MenuItem(
                "Открыть Dashboard в браузере",
                lambda icon, item: open_dashboard_in_browser()
            ),
            pystray.MenuItem(
                "Мобильная версия",
                lambda icon, item: open_mobile()
            ),
            pystray.MenuItem(
                "История",
                lambda icon, item: open_history()
            ),
            pystray.MenuItem(
                "Логи",
                lambda icon, item: open_logs()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(autostart_label, toggle_autostart),
            pystray.MenuItem(auto_open_label, toggle_auto_open_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Выход",
                lambda icon, item: exit_app(icon, item)
            )
        )
        return menu
    except Exception as e:
        logger.error(f"Ошибка создания меню трея: {e}")
        return None


# ============================================================
# ИКОНКА ТРЕЯ
# ============================================================

def create_tray_icon_image():
    """Создаёт иконку для трея."""
    try:
        from PIL import Image

        # Задания планировщика запускаются из System32; ищем иконку рядом с приложением.
        icon_path = os.path.join(
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)),
            "icon.ico",
        )
        if os.path.exists(icon_path):
            try:
                image = Image.open(icon_path)
                image = image.resize((64, 64))
                return image
            except Exception as e:
                logger.debug(f"Ошибка открытия icon.ico: {e}")

        # Иначе рисуем простую иконку
        from PIL import ImageDraw
        width, height = 64, 64
        image = Image.new('RGB', (width, height), (0, 0, 128))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, width - 8, height - 8), fill=(0, 128, 255))
        return image
    except Exception as e:
        logger.error(f"Ошибка создания иконки: {e}")
        return None


# ============================================================
# ЗАПУСК СЕРВЕРА
# ============================================================

def run_flask_server():
    """Запускает Flask-сервер."""
    try:
        server_core.start_lifecycle()
        server_core.app.run(
            host='0.0.0.0',
            port=Config.SERVER_PORT,
            debug=False,
            use_reloader=False
        )
    except Exception as e:
        logger.error(f"Ошибка Flask-сервера: {e}")


# ============================================================
# ВЫХОД ИЗ ПРОГРАММЫ
# ============================================================

def exit_app(icon, item):
    """Выход из приложения."""
    logger.info("Выход из приложения...")
    try:
        if icon:
            icon.stop()
    except Exception as e:
        logger.debug(f"Ошибка при остановке иконки трея: {e}")
    os._exit(0)


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    """Главная функция запуска."""
    global dashboard_window, dashboard_window_error, tray_available
    logger.info("=" * 50)
    logger.info("SystemMonitor запускается...")
    logger.info("=" * 50)

    # Запускаем сервер в фоновом потоке
    server_thread = threading.Thread(target=run_flask_server, daemon=True)
    server_thread.start()
    logger.info(f"Сервер запущен на порту {Config.SERVER_PORT}")

    # Ждём, пока сервер поднимется
    time.sleep(2)

    auto_open_dashboard = is_auto_open_dashboard_enabled()
    logger.info(
        "Автооткрытие Dashboard %s",
        "включено" if auto_open_dashboard else "отключено"
    )

    # Иконка трея работает отдельно, пока главный поток обслуживает WebView2.
    try:
        import pystray

        icon_image = create_tray_icon_image()
        menu = build_tray_menu()

        if icon_image and menu:
            icon = pystray.Icon(
                "SystemMonitor",
                icon_image,
                "SystemMonitor — Системный монитор",
                menu
            )
            icon.run_detached()
            tray_available = True
            logger.info("Системный трей запущен в отдельном потоке")
        else:
            logger.warning("Не удалось создать трей. Сервер работает в фоне.")

    except Exception:
        logger.exception("Не удалось запустить системный трей")

    if not tray_available:
        auto_open_dashboard = True

    try:
        import webview

        profile_dir = _create_dashboard_window(webview, auto_open_dashboard)
        webview.start(
            gui="edgechromium",
            private_mode=False,
            storage_path=profile_dir,
        )
    except Exception as e:
        dashboard_window = None
        dashboard_window_error = str(e)
        if auto_open_dashboard:
            _show_webview_fallback(e)
            open_dashboard_in_browser()
        logger.exception("Окно Dashboard на WebView2 недоступно")
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
