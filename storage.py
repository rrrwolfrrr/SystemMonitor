#!/usr/bin/env python3
"""
SystemMonitor — серверное хранение пользовательских данных.
Хранит темы, пресеты и профили в JSON-файлах в %LOCALAPPDATA%\\SystemMonitor.
Это позволяет синхронизировать настройки между разными устройствами.
"""

import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)

# Папка для хранения данных
def _data_dir():
    """Return a writable per-user directory, with a safe legacy migration."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        target = os.path.join(local_appdata, "SystemMonitor")
    else:
        target = os.path.join(os.path.expanduser("~"), ".systemmonitor")
    legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    if target != legacy and os.path.isdir(legacy) and not os.path.exists(target):
        try:
            os.makedirs(target, exist_ok=True)
            for filename in os.listdir(legacy):
                source = os.path.join(legacy, filename)
                destination = os.path.join(target, filename)
                if os.path.isfile(source) and not os.path.exists(destination):
                    shutil.copy2(source, destination)
        except OSError:
            # A read-only legacy directory must never prevent startup.
            return legacy
    return target


DATA_DIR = _data_dir()


def _ensure_data_dir():
    """Создаёт папку data, если она не существует."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def _read_json(filename, default=None):
    """Читает JSON файл из папки data."""
    _ensure_data_dir()
    filepath = os.path.join(DATA_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else []
    except json.JSONDecodeError as e:
        logger.warning(f"Ошибка чтения JSON файла {filename}: {e}")
        return default if default is not None else []
    except Exception as e:
        logger.error(f"Ошибка чтения файла {filename}: {e}")
        return default if default is not None else []


def _write_json(filename, data):
    """Записывает JSON файл в папку data."""
    _ensure_data_dir()
    filepath = os.path.join(DATA_DIR, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка записи файла {filename}: {e}")


# --- Темы ---

def get_themes():
    """Возвращает список пользовательских тем."""
    return _read_json("themes.json", [])


def save_themes(themes):
    """Сохраняет список пользовательских тем."""
    _write_json("themes.json", themes)


# --- Пресеты ---

def get_presets():
    """Возвращает список пресетов макетов."""
    return _read_json("presets.json", [])


def save_presets(presets):
    """Сохраняет список пресетов макетов."""
    _write_json("presets.json", presets)


# --- Профиль ---

def get_profile():
    """Возвращает профиль пользователя."""
    return _read_json("profile.json", {})


def save_profile(profile):
    """Сохраняет профиль пользователя."""
    _write_json("profile.json", profile)