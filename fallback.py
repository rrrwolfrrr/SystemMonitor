#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Резервные источники данных для SystemMonitor (полная версия).
Стратегия: если основная библиотека вернула None, пробуем резервные источники.
Источники по приоритету:
  - Частота и загрузка CPU  -> psutil -> WMI Win32_Processor
  - Температура CPU         -> psutil.sensors_temperatures -> WMI ThermalZone -> WMI Probe -> OpenHardwareMonitor
  - Память                  -> psutil.virtual_memory -> WMI Win32_OperatingSystem
  - Батарея                 -> psutil.sensors_battery -> WMI Win32_Battery
  - Диски (место)           -> psutil.disk_usage
  - Сеть (скорость)         -> psutil.net_io_counters
"""
import logging
import subprocess
import time
from validator import field_metadata, is_valid_reading, validate_reading
from sensor_resolver import SensorResolver
from providers import get_gpu_memory_metrics, get_nvidia_metrics, get_smart_devices
logger = logging.getLogger(__name__)
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil не установлен — многие резервы недоступны")
try:
    import wmi as wmi_module
    HAS_WMI = True
except ImportError:
    HAS_WMI = False
    logger.info("wmi не установлен — WMI-резервы недоступны")
_TEMP_CACHE = {"value": None, "timestamp": 0.0}
_TEMP_CACHE_TTL = 2.0
_WMI_CACHE = {"instance": None, "timestamp": 0.0}
_WMI_CACHE_TTL = 5.0
_NET_CACHE = {"prev_bytes": None, "prev_time": 0.0}
_CREATE_NO_WINDOW = 0x08000000
_SOURCES_USED = {}
_FAILED_SOURCES = {}
_RETRY_INTERVAL = 60
_RESOLVER = SensorResolver()


def get_sensor_resolver():
    """Return the process-wide resolver used by fallback collection."""
    return _RESOLVER

def _try_source(name, func, field=None):
    now = time.time()
    if name in _FAILED_SOURCES:
        if now - _FAILED_SOURCES[name] < _RETRY_INTERVAL:
            return None
    try:
        result = func()
        if result is not None and (field is None or is_valid_reading(field, result)):
            _FAILED_SOURCES.pop(name, None)
            return result
        else:
            _FAILED_SOURCES[name] = now
    except Exception as e:
        logger.debug(f"Источник '{name}' не сработал: {e}")
        _FAILED_SOURCES[name] = now
    return None

def _get_wmi():
    global _WMI_CACHE
    if not HAS_WMI:
        return None
    now = time.time()
    if _WMI_CACHE["instance"] is not None and (now - _WMI_CACHE["timestamp"]) < _WMI_CACHE_TTL:
        return _WMI_CACHE["instance"]
    try:
        w = wmi_module.WMI()
        _WMI_CACHE["instance"] = w
        _WMI_CACHE["timestamp"] = now
        return w
    except Exception as e:
        logger.debug(f"Ошибка создания WMI клиента: {e}")
        return None

def _get_cpu_freq_psutil():
    if not HAS_PSUTIL:
        return None
    freq = psutil.cpu_freq()
    if freq and freq.current > 0:
        return round(freq.current, 1)
    return None

def _get_cpu_freq_wmi():
    w = _get_wmi()
    if not w:
        return None
    for cpu in w.Win32_Processor():
        if hasattr(cpu, 'CurrentClockSpeed') and cpu.CurrentClockSpeed:
            return float(cpu.CurrentClockSpeed)
    return None

def get_cpu_freq():
    freq = _try_source("cpu.freq.psutil", _get_cpu_freq_psutil, "cpu.frequency")
    if freq is not None:
        _SOURCES_USED["cpu.frequency"] = "psutil"
        return freq
    freq = _try_source("cpu.freq.wmi", _get_cpu_freq_wmi, "cpu.frequency")
    if freq is not None:
        _SOURCES_USED["cpu.frequency"] = "WMI"
        return freq
    return None

def _get_cpu_load_psutil():
    if not HAS_PSUTIL:
        return None
    return round(psutil.cpu_percent(interval=None), 1)

def _get_cpu_load_wmi():
    w = _get_wmi()
    if not w:
        return None
    for cpu in w.Win32_Processor():
        if cpu.LoadPercentage is not None:
            return float(cpu.LoadPercentage)
    return None

def get_cpu_load():
    load = _try_source("cpu.load.psutil", _get_cpu_load_psutil, "cpu.load")
    if load is not None:
        _SOURCES_USED["cpu.load"] = "psutil"
        return load
    load = _try_source("cpu.load.wmi", _get_cpu_load_wmi, "cpu.load")
    if load is not None:
        _SOURCES_USED["cpu.load"] = "WMI"
        return load
    return None

def _get_cpu_temp_psutil():
    if not HAS_PSUTIL:
        return None
    temps = psutil.sensors_temperatures()
    if not temps:
        return None
    for key in ("coretemp", "k10temp", "cpu_thermal", "cpu-thermal", "zenpower"):
        if key in temps and temps[key]:
            values = [t.current for t in temps[key] if t.current is not None]
            if values:
                return round(sum(values) / len(values), 1)
    return None

def _get_cpu_temp_wmi_thermal():
    global _TEMP_CACHE
    now = time.time()
    if _TEMP_CACHE["value"] is not None and (now - _TEMP_CACHE["timestamp"]) < _TEMP_CACHE_TTL:
        return _TEMP_CACHE["value"]
    try:
        output = subprocess.check_output(
            ["wmic", "/namespace:\\root\\wmi", "PATH", "MSAcpi_ThermalZoneTemperature", "get", "CurrentTemperature", "/value"],
            stderr=subprocess.DEVNULL, timeout=3, creationflags=_CREATE_NO_WINDOW
        ).decode("utf-8", errors="ignore")
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("CurrentTemperature="):
                raw = int(line.split("=")[1])
                celsius = round(raw / 10.0 - 273.15, 1)
                if 0 <= celsius <= 150:
                    _TEMP_CACHE["value"] = celsius
                    _TEMP_CACHE["timestamp"] = now
                    return celsius
    except Exception:
        pass
    _TEMP_CACHE["timestamp"] = now
    return _TEMP_CACHE["value"]

def _get_cpu_temp_wmi_probe():
    w = _get_wmi()
    if not w:
        return None
    for probe in w.Win32_TemperatureProbe():
        if probe.CurrentReading is not None and probe.CurrentReading > 0:
            return float(probe.CurrentReading)
    return None

def _get_cpu_temp_openhardwaremonitor():
    try:
        w = wmi_module.WMI(namespace="OpenHardwareMonitor")
        for sensor in w.Sensor():
            if sensor.SensorType == "Temperature" and "CPU" in str(sensor.Name):
                if sensor.Value is not None:
                    return float(sensor.Value)
    except Exception:
        pass
    return None

def get_cpu_temp():
    temp = _try_source("cpu.temp.psutil", _get_cpu_temp_psutil, "cpu.temperature")
    if temp is not None:
        _SOURCES_USED["cpu.temperature"] = "psutil"
        return temp
    temp = _try_source("cpu.temp.wmi_thermal", _get_cpu_temp_wmi_thermal, "cpu.temperature")
    if temp is not None:
        _SOURCES_USED["cpu.temperature"] = "WMI-Thermal"
        return temp
    temp = _try_source("cpu.temp.wmi_probe", _get_cpu_temp_wmi_probe, "cpu.temperature")
    if temp is not None:
        _SOURCES_USED["cpu.temperature"] = "WMI-Probe"
        return temp
    temp = _try_source("cpu.temp.ohm", _get_cpu_temp_openhardwaremonitor, "cpu.temperature")
    if temp is not None:
        _SOURCES_USED["cpu.temperature"] = "OpenHardwareMonitor"
        return temp
    return None

def _get_memory_psutil():
    if not HAS_PSUTIL:
        return None, None
    vm = psutil.virtual_memory()
    return round(vm.used / (1024 ** 3), 1), round(vm.total / (1024 ** 3), 1)

def _get_memory_wmi():
    w = _get_wmi()
    if not w:
        return None, None
    for os in w.Win32_OperatingSystem():
        total_kb = int(os.TotalVisibleMemorySize or 0)
        free_kb = int(os.FreePhysicalMemory or 0)
        if total_kb > 0:
            return round(total_kb / (1024 ** 2), 1), round((total_kb - free_kb) / (1024 ** 2), 1)
    return None, None

def get_memory():
    memory = _try_source("mem.psutil", lambda: _get_memory_psutil())
    if memory is not None:
        used, total = memory
    else:
        used, total = None, None
    if used is not None or total is not None:
        _SOURCES_USED["ram.used"] = "psutil"
        _SOURCES_USED["ram.total"] = "psutil"
        return used, total
    memory = _try_source("mem.wmi", lambda: _get_memory_wmi())
    if memory is not None:
        used, total = memory
    else:
        used, total = None, None
    if used is not None or total is not None:
        _SOURCES_USED["ram.used"] = "WMI"
        _SOURCES_USED["ram.total"] = "WMI"
        return used, total
    return None, None

def _get_battery_psutil():
    if not HAS_PSUTIL:
        return None
    batt = psutil.sensors_battery()
    if batt is None:
        return None
    result = {
        "percent": round(batt.percent, 1) if batt.percent is not None else None,
        "plugged": bool(batt.power_plugged),
        "secsleft": None,
    }
    if batt.secsleft and batt.secsleft > 0 and batt.secsleft < 0xFFFFFFFF:
        result["secsleft"] = int(batt.secsleft)
    result["status"] = "full" if (result["percent"] or 0) >= 99 and batt.power_plugged else ("charging" if batt.power_plugged else "discharging")
    return result


def _get_battery_wmi():
    w = _get_wmi()
    if not w:
        return None
    batteries = []
    battery_status_names = {
        1: "Другое",
        2: "Неизвестно",
        3: "Полностью заряжена",
        4: "Низкий заряд",
        5: "Критически низкий заряд",
        6: "Заряжается",
        7: "Заряжается (заряд высокий)",
        8: "Заряжается (заряд низкий)",
        9: "Заряжается (заряд критически низкий)",
        10: "Состояние не определено",
        11: "Заряжена частично",
        12: "Перезарядка",
        13: "Обучение",
        14: "Заряжается",
        15: "Разряжается",
    }
    properties = {
        "Name": ("name", str),
        "DeviceID": ("device_id", str),
        "EstimatedChargeRemaining": ("percent", int),
        "EstimatedRunTime": ("remaining_minutes", int),
        "BatteryStatus": ("battery_status_code", int),
        "Chemistry": ("chemistry_code", int),
        "DesignCapacity": ("design_capacity_mwh", int),
        "FullChargeCapacity": ("full_charge_capacity_mwh", int),
        "DesignVoltage": ("design_voltage_mv", int),
        "MaxRechargeTime": ("max_recharge_minutes", int),
        "ExpectedBatteryLife": ("expected_life_seconds", int),
        "ExpectedBatteryLifeTime": ("expected_life_minutes", int),
        "TimeOnBattery": ("time_on_battery_seconds", int),
        "TimeToFullCharge": ("time_to_full_charge_seconds", int),
        "Availability": ("availability_code", int),
        "ConfigManagerErrorCode": ("config_manager_error_code", int),
        "PowerManagementSupported": ("power_management_supported", bool),
        "StatusInfo": ("status_info_code", int),
        "Status": ("wmi_status", str),
    }
    for batt in w.Win32_Battery():
        result = {}
        for property_name, (key, convert) in properties.items():
            value = getattr(batt, property_name, None)
            if value is None or value == "":
                continue
            try:
                value = convert(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if isinstance(value, int) and (value < 0 or value >= 0xFFFFFFFF):
                continue
            if key in {"design_capacity_mwh", "full_charge_capacity_mwh", "design_voltage_mv"} and value == 0:
                continue
            result[key] = value
        status_code = result.get("battery_status_code")
        if status_code in battery_status_names:
            result["battery_status"] = battery_status_names[status_code]
        if result.get("design_capacity_mwh") and result.get("full_charge_capacity_mwh"):
            result["health_percent"] = round(
                result["full_charge_capacity_mwh"] * 100 / result["design_capacity_mwh"],
                1,
            )
        if result:
            batteries.append(result)
    if not batteries:
        return None
    result = dict(batteries[0])
    if len(batteries) > 1:
        result["batteries"] = batteries
    return result


def get_battery():
    batt = _try_source("battery.psutil", _get_battery_psutil)
    if batt:
        _SOURCES_USED["battery"] = "psutil"
        wmi_batt = _try_source("battery.wmi", _get_battery_wmi)
        if wmi_batt:
            for k, v in wmi_batt.items():
                if k not in batt:
                    batt[k] = v
    else:
        batt = _try_source("battery.wmi", _get_battery_wmi)
        if batt:
            _SOURCES_USED["battery"] = "WMI"
        else:
            return None

    status_code = batt.get("battery_status_code")
    if "plugged" not in batt and status_code is not None:
        batt["plugged"] = status_code in {3, 6, 7, 8, 9, 14}
    if "status" not in batt and status_code is not None:
        if status_code == 3:
            batt["status"] = "full"
        elif status_code in {6, 7, 8, 9, 14}:
            batt["status"] = "charging"
        elif status_code in {4, 5, 15}:
            batt["status"] = "discharging"
    if "batteries" not in batt:
        batt["batteries"] = [dict(batt)]
    return batt

def get_disks_usage():
    if not HAS_PSUTIL:
        return None
    try:
        result = []
        seen = set()
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                device = part.device.rstrip("\\").rstrip("/")
                if device in seen:
                    continue
                seen.add(device)
                result.append({"mountpoint": part.mountpoint, "device": part.device, "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024 ** 3), 1), "used_gb": round(usage.used / (1024 ** 3), 1),
                    "free_gb": round(usage.free / (1024 ** 3), 1), "percent": round(usage.percent, 1)})
            except (PermissionError, OSError):
                continue
        if result:
            _SOURCES_USED["disks_usage"] = "psutil"
            return result
    except Exception:
        pass
    return None

def get_network_io():
    global _NET_CACHE
    if not HAS_PSUTIL:
        return None
    try:
        net = psutil.net_io_counters()
        if not net:
            return None
        now = time.time()
        pb = _NET_CACHE["prev_bytes"]
        pt = _NET_CACHE["prev_time"]
        ds = up = 0.0
        if pb is not None and pt > 0:
            dt = now - pt
            if dt > 0:
                ds = max(0.0, round((net.bytes_recv - pb["recv"]) / dt / (1024 ** 2), 3))
                up = max(0.0, round((net.bytes_sent - pb["sent"]) / dt / (1024 ** 2), 3))
        _NET_CACHE["prev_bytes"] = {"recv": net.bytes_recv, "sent": net.bytes_sent}
        _NET_CACHE["prev_time"] = now
        _SOURCES_USED["network_io"] = "psutil"
        download_kbps = round(ds * 1024, 1)
        upload_kbps = round(up * 1024, 1)
        # Сохраняем старые имена и одновременно публикуем единый формат.
        return {
            "total_received_mb": round(net.bytes_recv / (1024 ** 2), 1),
            "total_sent_mb": round(net.bytes_sent / (1024 ** 2), 1),
            "download_speed_mbs": ds,
            "upload_speed_mbs": up,
            "received_total_mb": round(net.bytes_recv / (1024 ** 2), 1),
            "sent_total_mb": round(net.bytes_sent / (1024 ** 2), 1),
            "download_speed_kbps": download_kbps,
            "upload_speed_kbps": upload_kbps,
        }
    except Exception:
        return None

def _set_metadata(result, field, source, status, quality, reason=None,
                  stale_age_seconds=None, extra=None):
    metadata = field_metadata(source, status, quality, reason)
    if stale_age_seconds is not None:
        metadata["stale_age_seconds"] = stale_age_seconds
    if extra:
        metadata.update(extra)
    result.setdefault("metadata", {})[field] = metadata


def _ensure_value(result, mapping, key, field, provider):
    """Оставляет валидное native-показание или получает его у провайдера."""
    current = mapping.get(key)
    resolved = _RESOLVER.resolve(field, current, (("fallback", provider),))
    mapping[key] = resolved.value
    if resolved.status == "valid":
        # A fallback may identify a more precise source (psutil/WMI).
        source = "libre" if current is not None and resolved.source == "libre" else _SOURCES_USED.get(field, resolved.source)
        _set_metadata(result, field, source, "valid", "high" if source == "libre" else "medium", resolved.reason)
        return
    if resolved.status == "stale":
        _set_metadata(
            result,
            field,
            resolved.source,
            "stale",
            resolved.quality,
            resolved.reason,
            resolved.stale_age_seconds,
            resolved.metadata,
        )
        return
    logger.debug(
        "Показание %s недоступно: value=%r reason=%s",
        field,
        current,
        resolved.reason,
    )
    if resolved.status != "valid":
        logger.warning(
            "Показание %s недоступно: native_reason=%s",
            field, resolved.reason,
        )
        _set_metadata(result, field, "none", "missing", "unavailable", resolved.reason)


def _normalize_network(result):
    """Публикует единый network-объект, не удаляя прежние ключи."""
    net = result.get("network_io")
    if not isinstance(net, dict):
        return
    received = net.get("received_total_mb", net.get("total_received_mb"))
    sent = net.get("sent_total_mb", net.get("total_sent_mb"))
    download = net.get("download_speed_kbps")
    upload = net.get("upload_speed_kbps")
    if download is None and net.get("download_speed_mbs") is not None:
        download = float(net["download_speed_mbs"]) * 1024
    if upload is None and net.get("upload_speed_mbs") is not None:
        upload = float(net["upload_speed_mbs"]) * 1024
    result["network"] = {
        "received_total_mb": received,
        "sent_total_mb": sent,
        "download_speed_kbps": download,
        "upload_speed_kbps": upload,
    }
    source = _SOURCES_USED.get("network_io", "libre")
    for key in ("received_total_mb", "sent_total_mb"):
        checked = validate_reading("network." + key, result["network"][key])
        if checked.valid:
            result["network"][key] = checked.value
            _set_metadata(result, "network." + key, source, "valid", "high")
        else:
            result["network"][key] = None
            _set_metadata(result, "network." + key, "none", "missing", "unavailable", checked.reason)
    for key in ("download_speed_kbps", "upload_speed_kbps"):
        checked = validate_reading("network." + key, result["network"][key])
        if checked.valid:
            result["network"][key] = checked.value
            _set_metadata(result, "network." + key, source, "valid", "high")
        else:
            result["network"][key] = None
            _set_metadata(result, "network." + key, "none", "missing", "unavailable", checked.reason)


def apply_fallbacks(result):
    global _SOURCES_USED
    if not result or not isinstance(result, dict):
        return result
    _SOURCES_USED = {}
    cpu = result.get("cpu")
    if isinstance(cpu, dict):
        _ensure_value(result, cpu, "frequency", "cpu.frequency", get_cpu_freq)
        _ensure_value(result, cpu, "load", "cpu.load", get_cpu_load)
        _ensure_value(result, cpu, "temperature", "cpu.temperature", get_cpu_temp)
        effective = cpu.get("frequency_effective")
        effective_check = validate_reading("cpu.frequency", effective)
        if not effective_check.valid:
            cpu["frequency_effective"] = cpu.get("frequency")
            if cpu["frequency_effective"] is not None:
                _set_metadata(result, "cpu.frequency_effective", "derived", "valid", "low", effective_check.reason)
            else:
                _set_metadata(result, "cpu.frequency_effective", "none", "missing", "unavailable", effective_check.reason)
        else:
            cpu["frequency_effective"] = effective_check.value
            _set_metadata(result, "cpu.frequency_effective", "libre", "valid", "high")
        result["cpu"] = cpu

    ram = result.get("ram")
    if isinstance(ram, dict):
        used, total = get_memory()
        _ensure_value(result, ram, "used", "ram.used", lambda: used)
        _ensure_value(result, ram, "total", "ram.total", lambda: total)
        result["ram"] = ram

    gpu = result.get("gpu")
    if isinstance(gpu, dict):
        optional_gpu = get_nvidia_metrics()
        for key in (
            "temperature", "hotspot_temperature", "voltage", "power",
            "frequency", "load", "memory_used", "memory_total",
        ):
            field = "gpu." + key
            candidates = ()
            if key in optional_gpu:
                candidates = (("nvidia", lambda key=key: optional_gpu.get(key)),)
            resolved = _RESOLVER.resolve(field, gpu.get(key), candidates)
            gpu[key] = resolved.value
            _set_metadata(
                result,
                field,
                resolved.source,
                resolved.status,
                resolved.quality,
                resolved.reason,
                resolved.stale_age_seconds,
            )
        gpu_memory = get_gpu_memory_metrics()
        gpu["dedicated_memory_used_mb"] = gpu_memory.get(
            "dedicated_memory_used_mb",
            gpu.get("memory_used"),
        )
        gpu["dedicated_memory_total_mb"] = gpu.get("memory_total")
        gpu["shared_memory_used_mb"] = gpu_memory.get("shared_memory_used_mb")
        gpu["shared_memory_total_mb"] = gpu_memory.get("shared_memory_total_mb")

    storage = result.get("storage")
    if isinstance(storage, list):
        valid_storage = []
        for index, disk in enumerate(storage):
            if not isinstance(disk, dict):
                continue
            field = f"storage[{index}].temp"
            # Keep a per-disk cache key so one drive can never inherit another
            # drive's stale temperature.
            resolved = _RESOLVER.resolve("storage.temp", disk.get("temp"))
            if resolved.value is None:
                disk["temp"] = None
                disk["status"] = "temporary_unavailable"
                _set_metadata(
                    result,
                    field,
                    resolved.source,
                    resolved.status,
                    resolved.quality,
                    resolved.reason,
                    resolved.stale_age_seconds,
                )
            else:
                disk["temp"] = resolved.value
                disk["status"] = resolved.status
                _set_metadata(
                    result,
                    field,
                    resolved.source,
                    resolved.status,
                    resolved.quality,
                    resolved.reason,
                    resolved.stale_age_seconds,
                )
            valid_storage.append(disk)
        result["storage"] = valid_storage

    if "battery" not in result:
        battery = get_battery()
        if battery:
            result["battery"] = battery
    if "disks_usage" not in result:
        disks = get_disks_usage()
        if disks:
            result["disks_usage"] = disks
    smart_devices = get_smart_devices()
    if smart_devices:
        result["smart"] = smart_devices
    if "network_io" not in result:
        net = get_network_io()
        if net:
            result["network_io"] = net
            _SOURCES_USED["network_io"] = "psutil"
    _normalize_network(result)
    if _SOURCES_USED:
        result["_sources"] = _SOURCES_USED.copy()
        logger.info(f"Резервные источники: {_SOURCES_USED}")
    return result
