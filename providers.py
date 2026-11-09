"""Safe provider discovery and self-tests.

The registry deliberately only performs local, bounded checks.  Optional
hardware integrations are never imported at module import time and are
disabled unless explicitly enabled in the configuration.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import ctypes
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional

logger = logging.getLogger(__name__)
_SMART_CACHE = {
    "timestamp": 0.0,
    "value": [],
    "status": "idle",
    "reason": None,
}
_SMART_LOCK = threading.Lock()
_SMART_REFRESH_THREAD = None
_GPU_MEMORY_CACHE = {"timestamp": 0.0, "value": {}}
_GPU_MEMORY_CACHE_TTL = 1.0
_GPU_MEMORY_LOCK = threading.Lock()


def _load_vendor_library(names):
    if os.name != "nt":
        return None
    for name in names:
        try:
            return ctypes.WinDLL(name)
        except OSError:
            continue
    return None


def get_nvapi_status():
    """Detect the vendor NVAPI runtime without loading or installing a driver."""
    library = _load_vendor_library(("nvapi64.dll", "nvapi.dll"))
    return {"available": library is not None,
            "reason": None if library is not None else "nvapi_runtime_not_found"}


def get_amd_adl_status():
    """Detect AMD ADL/ADLX runtime shipped with the display driver."""
    library = _load_vendor_library(("atiadlxx.dll", "atiadlxy.dll", "amdxc64.dll"))
    return {"available": library is not None,
            "reason": None if library is not None else "amd_adl_runtime_not_found"}


def get_acpi_ec_status():
    """Check the safe firmware interfaces used for laptop ACPI/EC readings."""
    if os.name != "nt":
        return {"available": False, "reason": "not_windows"}
    try:
        import wmi
        client = wmi.WMI(namespace=r"root\wmi")
        list(client.MSAcpi_ThermalZoneTemperature())
        return {"available": True, "interface": "WMI/ACPI thermal zone"}
    except Exception:
        return {"available": False, "reason": "acpi_thermal_zone_unavailable"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ProviderStatus:
    """JSON-compatible status of one provider."""

    name: str
    available: bool
    enabled: bool = True
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    self_test: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "enabled": self.enabled,
            "reason": self.reason,
            "details": dict(self.details),
            "self_test": self.self_test,
        }


@dataclass
class _Provider:
    name: str
    checker: Callable[[], Any]
    self_test_callback: Optional[Callable[[], Any]] = None
    enabled: bool = True
    description: str = ""


class ProviderRegistry:
    """Small, thread-safe registry used by diagnostics and resolvers."""

    def __init__(self, providers: Optional[Iterable[_Provider]] = None):
        self._providers: Dict[str, _Provider] = {}
        self._lock = threading.RLock()
        for provider in providers or ():
            self.register(
                provider.name,
                provider.checker,
                provider.self_test_callback,
                provider.enabled,
                provider.description,
            )

    def register(
        self,
        name: str,
        checker: Callable[[], Any],
        self_test: Optional[Callable[[], Any]] = None,
        enabled: bool = True,
        description: str = "",
    ) -> None:
        if not name or not callable(checker):
            raise ValueError("provider name and checker are required")
        with self._lock:
            self._providers[str(name)] = _Provider(
                str(name), checker, self_test, bool(enabled), description
            )

    def names(self):
        with self._lock:
            return tuple(self._providers)

    @staticmethod
    def _normalise_check(value: Any) -> tuple:
        if isinstance(value, tuple) and len(value) == 2:
            return bool(value[0]), value[1]
        if isinstance(value, dict):
            return bool(value.get("available")), value
        return bool(value), None

    def check(self, name: str) -> ProviderStatus:
        with self._lock:
            provider = self._providers.get(name)
        if provider is None:
            return ProviderStatus(name, False, False, "not_registered")
        if not provider.enabled:
            return ProviderStatus(name, False, False, "disabled")
        try:
            available, details = self._normalise_check(provider.checker())
            reason = None if available else "unavailable"
            if isinstance(details, dict):
                return ProviderStatus(
                    name,
                    available,
                    True,
                    details.get("reason", reason),
                    details,
                )
            return ProviderStatus(name, available, True, reason)
        except Exception as exc:
            logger.debug("Проверка провайдера %s не удалась: %s", name, exc)
            return ProviderStatus(name, False, True, "check_error")

    def availability(self) -> Dict[str, Dict[str, Any]]:
        return {name: self.check(name).as_dict() for name in self.names()}

    def self_test(self, name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        names = (name,) if name else self.names()
        results: Dict[str, Dict[str, Any]] = {}
        for provider_name in names:
            status = self.check(provider_name)
            with self._lock:
                provider = self._providers.get(provider_name)
            result = {
                "available": status.available,
                "ok": status.available,
                "reason": status.reason,
            }
            if provider and provider.self_test_callback and status.enabled:
                try:
                    value = provider.self_test_callback()
                    result["ok"] = bool(value) if not isinstance(value, dict) else bool(value.get("ok", value.get("available", False)))
                    if isinstance(value, dict):
                        result.update(value)
                except Exception as exc:
                    result.update({"ok": False, "reason": "self_test_error"})
                    logger.debug("Self-test %s не удался: %s", provider_name, exc)
            results[provider_name] = result
        return results


def _module_checker(module_name: str):
    def check():
        try:
            importlib.import_module(module_name)
            return True
        except Exception:
            return False

    return check


def _command_checker(command: str):
    return lambda: shutil.which(command) is not None


def _nvidia_smi_test():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"ok": False, "reason": "executable_not_found"}
    try:
        completed = subprocess.run(
            [executable, "--query-gpu=name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {"ok": completed.returncode == 0, "gpu_count": len([line for line in completed.stdout.splitlines() if line.strip()])}
    except Exception:
        return {"ok": False, "reason": "command_failed"}


def get_nvidia_metrics() -> Dict[str, Any]:
    """Read optional NVIDIA metrics using NVML or the local nvidia-smi CLI.

    The function is intentionally best-effort and returns an empty mapping
    when the feature is disabled or no optional integration is installed.
    """
    if _env_bool("SYSTEMMONITOR_ENABLE_NVML", False):
        try:
            nvml = importlib.import_module("pynvml")
            nvml.nvmlInit()
            count = int(nvml.nvmlDeviceGetCount())
            if count:
                handle = nvml.nvmlDeviceGetHandleByIndex(0)
                result = {}
                try:
                    result["temperature"] = float(nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU))
                except Exception:
                    pass
                try:
                    result["load"] = float(nvml.nvmlDeviceGetUtilizationRates(handle).gpu)
                except Exception:
                    pass
                try:
                    memory = nvml.nvmlDeviceGetMemoryInfo(handle)
                    result["memory_used"] = float(memory.used) / (1024 ** 2)
                    result["memory_total"] = float(memory.total) / (1024 ** 2)
                except Exception:
                    pass
                try:
                    result["power"] = float(nvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0
                except Exception:
                    pass
                return result
        except Exception as exc:
            logger.debug("NVML недоступен: %s", exc)
    if _env_bool("SYSTEMMONITOR_ENABLE_NVIDIA_SMI", False):
        executable = shutil.which("nvidia-smi")
        if executable:
            try:
                completed = subprocess.run(
                    [
                        executable,
                        "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if completed.returncode == 0 and completed.stdout.strip():
                    values = [item.strip() for item in completed.stdout.splitlines()[0].split(",")]
                    numbers = [float(item) for item in values]
                    return dict(zip(("temperature", "load", "memory_used", "memory_total", "power"), numbers))
            except Exception as exc:
                logger.debug("nvidia-smi недоступен: %s", exc)
    return {}


def get_gpu_memory_metrics() -> Dict[str, float]:
    """Read dedicated/shared GPU memory usage from Windows adapter counters."""
    if os.name != "nt":
        return {}
    now = time.monotonic()
    with _GPU_MEMORY_LOCK:
        if now - _GPU_MEMORY_CACHE["timestamp"] < _GPU_MEMORY_CACHE_TTL:
            return dict(_GPU_MEMORY_CACHE["value"])

        result = {}
        query = None
        pdh_error = OSError
        try:
            pdh = importlib.import_module("win32pdh")
            pywintypes = importlib.import_module("pywintypes")
            pdh_error = pywintypes.error
            _, instances = pdh.EnumObjectItems(
                None,
                None,
                "GPU Adapter Memory",
                pdh.PERF_DETAIL_WIZARD,
            )
            if not instances:
                _GPU_MEMORY_CACHE.update(timestamp=now, value=result)
                return {}

            query = pdh.OpenQuery()
            counters = []
            for instance in instances:
                paths = {}
                for counter_name, key in (
                    ("Dedicated Usage", "dedicated_memory_used_mb"),
                    ("Shared Usage", "shared_memory_used_mb"),
                ):
                    path = "\\GPU Adapter Memory(%s)\\%s" % (instance, counter_name)
                    try:
                        paths[key] = pdh.AddEnglishCounter(query, path)
                    except pywintypes.error as exc:
                        logger.debug("Счётчик GPU %s недоступен: %s", path, exc)
                if paths:
                    counters.append((instance, paths))

            if not counters:
                _GPU_MEMORY_CACHE.update(timestamp=now, value=result)
                return {}
            pdh.CollectQueryData(query)

            adapter_values = []
            for instance, paths in counters:
                values = {}
                for key, handle in paths.items():
                    try:
                        counter_status, counter_value = pdh.GetFormattedCounterValue(
                            handle,
                            pdh.PDH_FMT_LARGE,
                        )
                        if isinstance(counter_value, dict):
                            if counter_value.get("CStatus") == 0:
                                counter_value = counter_value.get("largeValue")
                            else:
                                continue
                        if isinstance(counter_value, (int, float)) and counter_status in (0, 65792):
                            values[key] = float(counter_value) / (1024 ** 2)
                    except (
                        pywintypes.error,
                        KeyError,
                        TypeError,
                        ValueError,
                    ) as exc:
                        logger.debug(
                            "Не удалось прочитать счётчик памяти GPU для %s: %s",
                            instance,
                            exc,
                        )
                if "dedicated_memory_used_mb" in values:
                    adapter_values.append(values)

            if adapter_values:
                primary_adapter = max(
                    adapter_values,
                    key=lambda item: item["dedicated_memory_used_mb"],
                )
                result.update(primary_adapter)

            try:
                psutil = importlib.import_module("psutil")
                result["shared_memory_total_mb"] = (
                    float(psutil.virtual_memory().total) / (1024 ** 2) / 2
                )
            except (ImportError, AttributeError, OSError, TypeError, ValueError) as exc:
                logger.debug("Не удалось определить лимит общей памяти GPU: %s", exc)
        except (ImportError, OSError, ValueError, pdh_error) as exc:
            logger.debug("Счётчики памяти GPU недоступны: %s", exc)
        finally:
            if query is not None:
                try:
                    pdh.CloseQuery(query)
                except (NameError, OSError):
                    pass

        _GPU_MEMORY_CACHE.update(timestamp=now, value=result)
        return dict(result)


def _smart_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 and number != float("inf") else None


def _parse_smartctl_output(payload, device_path):
    """Reduce smartctl JSON to display-ready metrics."""
    device = payload.get("device") if isinstance(payload.get("device"), dict) else {}
    nvme = payload.get("nvme_smart_health_information_log")
    nvme = nvme if isinstance(nvme, dict) else {}
    temperature = payload.get("temperature")
    temperature = temperature if isinstance(temperature, dict) else {}
    power_on_time = payload.get("power_on_time")
    power_on_time = power_on_time if isinstance(power_on_time, dict) else {}
    user_capacity = payload.get("user_capacity")
    user_capacity = user_capacity if isinstance(user_capacity, dict) else {}
    smart_status = payload.get("smart_status")
    smart_status = smart_status if isinstance(smart_status, dict) else {}
    smart_support = payload.get("smart_support")
    smart_support = smart_support if isinstance(smart_support, dict) else {}
    attributes = payload.get("ata_smart_attributes")
    attributes = attributes.get("table", []) if isinstance(attributes, dict) else []
    attribute_values = {}
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        name = str(attribute.get("name", "")).casefold().replace(" ", "_")
        raw = attribute.get("raw")
        value = raw.get("value") if isinstance(raw, dict) else None
        if name and _smart_number(value) is not None:
            attribute_values[name] = _smart_number(value)

    def metric(*names):
        for name in names:
            if name in attribute_values:
                return attribute_values[name]
        return None

    current_temperature = _smart_number(temperature.get("current"))
    if current_temperature is None:
        current_temperature = _smart_number(nvme.get("temperature"))
    if current_temperature is None:
        current_temperature = metric("temperature_celsius", "airflow_temperature_cel")

    health_passed = smart_status.get("passed")
    if not isinstance(health_passed, bool):
        health_passed = None

    percentage_used = _smart_number(nvme.get("percentage_used"))
    health_percent = max(0, 100 - percentage_used) if percentage_used is not None else None
    if health_percent is None:
        remaining_life = metric("percent_lifetime_remain", "remaining_lifetime_percent")
        if remaining_life is not None:
            health_percent = min(100, remaining_life)
    data_units_read = _smart_number(nvme.get("data_units_read"))
    interface_speed = payload.get("interface_speed")
    interface_speed = interface_speed if isinstance(interface_speed, dict) else {}

    def speed_label(key):
        speed = interface_speed.get(key)
        if not isinstance(speed, dict):
            return None
        value = _smart_number(speed.get("value"))
        units = str(speed.get("units") or "").strip()
        return f"{value:g} {units}".strip() if value is not None else None

    protocol = str(device.get("protocol") or "")[:30]
    standard = payload.get("nvme_version") if protocol.casefold() == "nvme" else payload.get("ata_version")
    standard = standard.get("string") if isinstance(standard, dict) else None
    capabilities = []
    if smart_support.get("available") is True or smart_support.get("enabled") is True:
        capabilities.append("S.M.A.R.T.")
    if payload.get("trim_supported") is True:
        capabilities.append("TRIM")
    if payload.get("volatile_write_cache") is True:
        capabilities.append("VolatileWriteCache")
    rotation_rate = _smart_number(payload.get("rotation_rate"))
    if protocol.casefold() == "nvme":
        rotation_label = "SSD"
    elif rotation_rate == 0:
        rotation_label = "SSD"
    elif rotation_rate is not None:
        rotation_label = f"{rotation_rate:g} RPM"
    else:
        rotation_label = None

    result = {
        "device": device_path,
        "model": str(payload.get("model_name") or payload.get("product") or device_path)[:120],
        "capacity_bytes": _smart_number(user_capacity.get("bytes")),
        "protocol": protocol,
        "serial_number": str(payload.get("serial_number") or "").strip()[:80] or None,
        "firmware_version": str(payload.get("firmware_version") or "").strip()[:80] or None,
        "interface": "NVMe Express" if protocol.casefold() == "nvme" else protocol or None,
        "standard": str(standard).strip()[:120] if standard else None,
        "transfer_mode": " / ".join(
            f"{label}: {value}"
            for label, value in (("текущая", speed_label("current")), ("макс.", speed_label("max")))
            if value
        ) or None,
        "capabilities": capabilities,
        "rotation_rate": rotation_rate,
        "rotation_label": rotation_label,
        "health_percent": health_percent,
        "health": "passed" if health_passed is True else "failed" if health_passed is False else "unknown",
        "temperature": current_temperature,
        "power_on_hours": _smart_number(power_on_time.get("hours")),
        "power_cycles": _smart_number(payload.get("power_cycle_count")),
        "percentage_used": percentage_used,
        "available_spare_percent": _smart_number(nvme.get("available_spare")),
        "media_errors": _smart_number(nvme.get("media_errors")),
        "data_units_read": data_units_read,
        "data_units_written": _smart_number(nvme.get("data_units_written")),
        "reallocated_sectors": metric("reallocated_sector_ct"),
        "pending_sectors": metric("current_pending_sector"),
        "uncorrectable_errors": metric("offline_uncorrectable"),
    }
    if result["power_on_hours"] is None:
        result["power_on_hours"] = _smart_number(nvme.get("power_on_hours"))
    if result["power_cycles"] is None:
        result["power_cycles"] = _smart_number(nvme.get("power_cycles"))
    return result


def _smart_windows_volumes():
    """Map physical disk numbers to mounted drive letters on Windows."""
    if os.name != "nt":
        return {}
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-Partition | Where-Object DriveLetter | "
        "Select-Object DiskNumber,DriveLetter | ConvertTo-Json -Compress",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            logger.warning("Could not map SMART devices to Windows volumes: %s", result.stderr.strip())
            return {}
        payload = json.loads(result.stdout) if result.stdout else []
        partitions = payload if isinstance(payload, list) else [payload]
        volumes = {}
        for partition in partitions:
            if not isinstance(partition, dict):
                continue
            number = partition.get("DiskNumber")
            letter = str(partition.get("DriveLetter") or "").strip()
            if isinstance(number, int) and letter:
                volumes.setdefault(number, []).append(f"{letter}:")
        return {number: ", ".join(letters) for number, letters in volumes.items()}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        logger.warning("Could not map SMART devices to Windows volumes: %s", exc)
        return {}


def _smart_scan_devices(output):
    devices = []
    for line in output.splitlines():
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        parts = entry.split()
        path = parts[0].strip('"')
        device_type = None
        if len(parts) >= 3 and parts[1] == "-d":
            device_type = parts[2]
        devices.append((path, device_type))
        if len(devices) >= 12:
            break
    return devices


def _collect_smart_data(executable):
    try:
        scan = subprocess.run(
            [executable, "--scan-open"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        devices = []
        scanned_devices = _smart_scan_devices(scan.stdout or "")
        volume_map = _smart_windows_volumes()
        failed_reads = 0
        for path, device_type in scanned_devices:
            command = [executable, "--json=o", "--all", path]
            if device_type:
                command.extend(["-d", device_type])
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                payload = json.loads(result.stdout) if result.stdout else None
                if isinstance(payload, dict):
                    device = _parse_smartctl_output(payload, path)
                    match = re.search(r"PhysicalDrive(\d+)$", path, re.IGNORECASE)
                    if match:
                        device["volume"] = volume_map.get(int(match.group(1)))
                    devices.append(device)
                else:
                    logger.warning("smartctl returned invalid JSON for device %s", path)
                    failed_reads += 1
            except subprocess.TimeoutExpired:
                logger.warning("smartctl timed out while reading device %s", path)
                failed_reads += 1
            except (OSError, ValueError) as exc:
                logger.warning("Could not read SMART data for device %s: %s", path, exc)
                failed_reads += 1
        with _SMART_LOCK:
            status = "ready" if devices else "error" if scanned_devices and failed_reads else "empty"
            if devices:
                reason = None
            elif scanned_devices and failed_reads:
                reason = "device_read_failed"
            elif scan.returncode != 0:
                status, reason = "error", "scan_failed"
            else:
                reason = "no_devices"
            _SMART_CACHE.update({
                "timestamp": time.time(),
                "value": devices,
                "status": status,
                "reason": reason,
            })
    except subprocess.TimeoutExpired:
        logger.warning("smartctl device scan timed out")
        with _SMART_LOCK:
            _SMART_CACHE.update(timestamp=time.time(), value=[], status="error", reason="scan_timeout")
    except OSError as exc:
        logger.warning("smartctl device scan failed: %s", exc)
        with _SMART_LOCK:
            _SMART_CACHE.update(timestamp=time.time(), value=[], status="error", reason="scan_failed")


def _start_smart_refresh(executable):
    global _SMART_REFRESH_THREAD
    now = time.time()
    with _SMART_LOCK:
        if _SMART_REFRESH_THREAD and _SMART_REFRESH_THREAD.is_alive():
            return
        if now - _SMART_CACHE["timestamp"] < 30:
            return
        _SMART_CACHE.update(status="scanning", reason=None)
        _SMART_REFRESH_THREAD = threading.Thread(
            target=_collect_smart_data,
            args=(executable,),
            name="SystemMonitor-SMART",
            daemon=True,
        )
        _SMART_REFRESH_THREAD.start()


def get_smart_devices():
    """Return cached read-only SMART metrics when smartctl is explicitly enabled."""
    if not _env_bool("SYSTEMMONITOR_ENABLE_SMART", False):
        return []
    executable = shutil.which("smartctl")
    if not executable:
        return []
    _start_smart_refresh(executable)
    with _SMART_LOCK:
        return [dict(device) for device in _SMART_CACHE["value"]]


def get_smart_status():
    """Return SMART provider status and cached metrics for dashboard cards."""
    if not _env_bool("SYSTEMMONITOR_ENABLE_SMART", False):
        return {
            "enabled": False,
            "available": False,
            "status": "disabled",
            "reason": "feature_disabled",
            "devices": [],
        }
    executable = shutil.which("smartctl")
    if not executable:
        return {
            "enabled": True,
            "available": False,
            "status": "unavailable",
            "reason": "smartctl_not_found",
            "devices": [],
        }
    devices = get_smart_devices()
    with _SMART_LOCK:
        status = _SMART_CACHE["status"]
        reason = _SMART_CACHE["reason"]
    return {
        "enabled": True,
        "available": status == "ready",
        "status": status,
        "reason": reason,
        "devices": devices,
    }


def create_default_registry(
    enable_nvml: Optional[bool] = None,
    enable_nvidia_smi: Optional[bool] = None,
    enable_smart: Optional[bool] = None,
    enable_vendor_apis: Optional[bool] = None,
) -> ProviderRegistry:
    """Create the standard registry without requiring optional packages."""
    nvml = _env_bool("SYSTEMMONITOR_ENABLE_NVML", False) if enable_nvml is None else enable_nvml
    smi = _env_bool("SYSTEMMONITOR_ENABLE_NVIDIA_SMI", False) if enable_nvidia_smi is None else enable_nvidia_smi
    smart = _env_bool("SYSTEMMONITOR_ENABLE_SMART", False) if enable_smart is None else enable_smart
    vendor_apis = _env_bool("SYSTEMMONITOR_ENABLE_VENDOR_APIS", True) if enable_vendor_apis is None else enable_vendor_apis
    registry = ProviderRegistry()
    registry.register("psutil", _module_checker("psutil"), description="CPU, RAM, disk and network fallback")
    registry.register("wmi", _module_checker("wmi"), description="Windows firmware and device metadata")
    registry.register("librehardwaremonitor", _module_checker("clr"), description="LibreHardwareMonitor .NET bridge")
    registry.register("nvml", _module_checker("pynvml"), enabled=nvml, description="Optional NVIDIA NVML")
    registry.register("nvidia-smi", _command_checker("nvidia-smi"), _nvidia_smi_test, enabled=smi, description="Optional local NVIDIA CLI")
    registry.register("nvapi", get_nvapi_status, enabled=vendor_apis, description="NVIDIA NVAPI runtime from the display driver")
    registry.register("amd-adl", get_amd_adl_status, enabled=vendor_apis, description="AMD ADL/ADLX runtime from the display driver")
    registry.register("acpi-ec", get_acpi_ec_status, enabled=vendor_apis, description="Windows ACPI/EC firmware interface")
    registry.register("smartctl", _command_checker("smartctl"), enabled=smart, description="Optional local SMART utility")
    return registry


_DEFAULT_REGISTRY: Optional[ProviderRegistry] = None
_DEFAULT_LOCK = threading.Lock()


def get_provider_registry() -> ProviderRegistry:
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        if _DEFAULT_REGISTRY is None:
            _DEFAULT_REGISTRY = create_default_registry()
        return _DEFAULT_REGISTRY


def reset_provider_registry() -> None:
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        _DEFAULT_REGISTRY = None
