#!/usr/bin/env python3
"""
SystemMonitor — утилиты.
Сбор системных данных через psutil.
Парсинг данных LibreHardwareMonitor (для совместимости).
"""

import logging
import re
import time
from datetime import datetime

import psutil

logger = logging.getLogger(__name__)


def parse_libre_data(json_data):
    """
    Парсит данные из формата LibreHardwareMonitor.
    
    В DLL-режиме (версия 6.0) данные уже приходят в нужном формате
    из libre_monitor.py. Эта функция оставлена для совместимости
    и просто проверяет формат данных.
    
    Args:
        json_data: Данные из libre_monitor.py (словарь)
    
    Returns:
        Словарь с данными или пустой словарь, если данные некорректны
    """
    result = {
        "cpu": {
            "temperature": None, "voltage": None, "power": None,
            "frequency": None, "load": None
        },
        "gpu": {
            "temperature": None, "voltage": None, "power": None,
            "frequency": None, "load": None,
            "memory_used": None, "memory_total": None,
            "hotspot_temperature": None
        },
        "ram": {
            "used": None, "total": None, "speed": None, "voltage": None
        },
        "motherboard": {"temperature": [], "voltage": []},
        "storage": [],
        "fans": [],
        "other": [],
    }
    
    if not json_data:
        return result
    
    # В DLL-режиме данные уже приходят в нужном формате из libre_monitor.py
    # Просто проверяем что это словарь и возвращаем
    if isinstance(json_data, dict):
        # Заполняем отсутствующие ключи значениями по умолчанию
        for key in result:
            if key not in json_data:
                json_data[key] = result[key]
        return json_data
    
    return result


def extract_number(text):
    """
    Извлекает число из строки.
    
    Args:
        text: Строка, содержащая число
    
    Returns:
        Число или None, если число не найдено
    """
    if text is None:
        return None
    try:
        match = re.search(r'[-+]?\d*\.?\d+', str(text))
        if match:
            return float(match.group())
    except (ValueError, TypeError):
        pass
    return None


def walk(data, path=""):
    """
    Рекурсивно обходит дерево данных и возвращает все пути к значениям.
    
    Args:
        data: Словарь или список для обхода
        path: Текущий путь (для рекурсии)
    
    Returns:
        Список кортежей (путь, значение)
    """
    result = []
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            result.extend(walk(value, new_path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = f"{path}[{i}]"
            result.extend(walk(item, new_path))
    else:
        result.append((path, data))
    return result


def get_psutil_data():
    """
    Собирает данные через psutil: CPU, RAM, диски, сеть, время работы.
    
    Returns:
        Словарь с системными данными
    """
    result = {
        "cpu_percent": None,
        "cpu_freq_mhz": None,
        "ram_used_mb": None,
        "ram_total_mb": None,
        "ram_percent": None,
        "disks": [],
        "net_sent": 0,
        "net_recv": 0,
        "network": {
            "sent_total_bytes": 0,
            "received_total_bytes": 0,
            "upload_speed_kbps": 0.0,
            "download_speed_kbps": 0.0,
        },
        "boot_time": None,
        "uptime_seconds": 0,
    }
    
    try:
        # Загрузка CPU
        result["cpu_percent"] = psutil.cpu_percent(interval=None)
    except Exception as e:
        logger.debug(f"Ошибка получения загрузки CPU: {e}")
    
    try:
        # Частота CPU
        cpu_freq = psutil.cpu_freq()
        if cpu_freq and cpu_freq.current:
            result["cpu_freq_mhz"] = cpu_freq.current
    except Exception as e:
        logger.debug(f"Ошибка получения частоты CPU: {e}")
    
    try:
        # Память
        mem = psutil.virtual_memory()
        result["ram_used_mb"] = mem.used // (1024 ** 2)
        result["ram_total_mb"] = mem.total // (1024 ** 2)
        result["ram_percent"] = mem.percent
    except Exception as e:
        logger.debug(f"Ошибка получения данных памяти: {e}")
    
    try:
        # Диски
        disks = []
        for part in psutil.disk_partitions():
            if part.fstype:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "mount": part.mountpoint,
                        "total_gb": round(usage.total / (1024 ** 3), 1),
                        "used_gb": round(usage.used / (1024 ** 3), 1),
                        "free_gb": round(usage.free / (1024 ** 3), 1),
                        "percent": usage.percent
                    })
                except PermissionError:
                    continue
                except OSError:
                    continue
        result["disks"] = disks
    except Exception as e:
        logger.debug(f"Ошибка получения данных дисков: {e}")
    
    try:
        # Сеть
        net_io = psutil.net_io_counters()
        result["net_sent"] = net_io.bytes_sent
        result["net_recv"] = net_io.bytes_recv
        result["network"]["sent_total_bytes"] = net_io.bytes_sent
        result["network"]["received_total_bytes"] = net_io.bytes_recv
    except Exception as e:
        logger.debug(f"Ошибка получения данных сети: {e}")
    
    try:
        # Время работы системы
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        result["boot_time"] = boot_time.strftime("%Y-%m-%d %H:%M:%S")
        result["uptime_seconds"] = int(time.time() - psutil.boot_time())
    except Exception as e:
        logger.debug(f"Ошибка получения времени работы: {e}")
    
    return result