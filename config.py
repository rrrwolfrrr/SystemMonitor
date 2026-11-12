#!/usr/bin/env python3
"""
SystemMonitor — конфигурация.
Создаёт env.env с дефолтными значениями, если его нет.
Загружает настройки из env.env.
"""

import os

from dotenv import load_dotenv

# Путь к файлу env.env в корне проекта
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'env.env')

# Если env.env не существует — создаём его с дефолтными значениями
if not os.path.exists(ENV_PATH):
    default_env = """# Настройки SystemMonitor
LIBRE_DLL=LibreHardwareMonitorLib.dll
SERVER_PORT=5000
UPDATE_INTERVAL=1
LOG_FILE=server.log
DEBUG=False
HISTORY_SIZE=60
HISTORY_FILE=history.json
MAX_HISTORY_ENTRIES=1000
DB_WRITE_INTERVAL=5
DB_BATCH_SIZE=10
SYSTEMMONITOR_STALE_CACHE_ENABLED=True
SYSTEMMONITOR_STALE_CACHE_TTL=30
SYSTEMMONITOR_ENABLE_DIAGNOSTICS=True
SYSTEMMONITOR_ENABLE_PROVIDER_SELF_TEST=True
SYSTEMMONITOR_ENABLE_NVML=False
SYSTEMMONITOR_ENABLE_NVIDIA_SMI=False
SYSTEMMONITOR_ENABLE_SMART=True
SYSTEMMONITOR_ENABLE_VENDOR_APIS=True
"""
    with open(ENV_PATH, 'w', encoding='utf-8') as f:
        f.write(default_env)
    print(f"[config] Создан файл настроек: {ENV_PATH}")

# Загружаем переменные из env.env
load_dotenv(ENV_PATH)

def _user_data_path(filename):
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".systemmonitor")
    directory = os.path.join(base, "SystemMonitor")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, filename)


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # DLL-режим LibreHardwareMonitor (EXE больше не используется)
    LIBRE_DLL = os.getenv("LIBRE_DLL", "LibreHardwareMonitorLib.dll")

    # Порт HTTP-сервера Flask
    SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))

    # Интервал обновления данных (секунды)
    UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "1"))

    # Файл логов
    LOG_FILE = os.getenv("LOG_FILE", "server.log")
    if not os.path.isabs(LOG_FILE):
        LOG_FILE = _user_data_path(LOG_FILE)

    # Режим отладки
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"

    # Размер короткой истории (deque)
    HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "60"))

    # Файл долгосрочной истории
    HISTORY_FILE = os.getenv("HISTORY_FILE", "history.json")
    if not os.path.isabs(HISTORY_FILE):
        HISTORY_FILE = _user_data_path(HISTORY_FILE)
    DB_FILE = _user_data_path("history.db")

    # Максимум записей в долгосрочной истории
    MAX_HISTORY_ENTRIES = int(os.getenv("MAX_HISTORY_ENTRIES", "1000"))
    DB_WRITE_INTERVAL = _env_float("DB_WRITE_INTERVAL", 5)
    DB_BATCH_SIZE = int(os.getenv("DB_BATCH_SIZE", "10"))

    # Новые функции по умолчанию безопасны и не требуют дополнительных пакетов.
    STALE_CACHE_ENABLED = _env_bool("SYSTEMMONITOR_STALE_CACHE_ENABLED", True)
    STALE_CACHE_TTL = _env_float("SYSTEMMONITOR_STALE_CACHE_TTL", 30)
    ENABLE_DIAGNOSTICS = _env_bool("SYSTEMMONITOR_ENABLE_DIAGNOSTICS", True)
    ENABLE_PROVIDER_SELF_TEST = _env_bool("SYSTEMMONITOR_ENABLE_PROVIDER_SELF_TEST", True)
    ENABLE_NVML = _env_bool("SYSTEMMONITOR_ENABLE_NVML", False)
    ENABLE_NVIDIA_SMI = _env_bool("SYSTEMMONITOR_ENABLE_NVIDIA_SMI", False)
    ENABLE_SMART = _env_bool("SYSTEMMONITOR_ENABLE_SMART", True)
    ENABLE_VENDOR_APIS = _env_bool("SYSTEMMONITOR_ENABLE_VENDOR_APIS", True)

    @classmethod
    def get_all(cls):
        """Возвращает все настройки в виде словаря."""
        return {
            k: v for k, v in cls.__dict__.items()
            if not k.startswith('_') and not callable(v)
        }