"""Bounded, local-only diagnostic snapshot collection."""

from __future__ import annotations

import logging
import os
import hashlib
import platform
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from providers import (
    ProviderRegistry,
    get_acpi_ec_status,
    get_amd_adl_status,
    get_nvapi_status,
    get_nvidia_metrics,
    get_provider_registry,
    get_smart_devices,
)
from system_detect import get_all_diagnostics
from pawnio import get_pawnio_status

logger = logging.getLogger(__name__)


def _dll_inventory() -> list:
    """Return bounded version/hash metadata for shipped DLLs."""
    roots = [os.path.dirname(os.path.abspath(__file__))]
    if getattr(sys, "_MEIPASS", None):
        roots.insert(0, sys._MEIPASS)
    root = next((candidate for candidate in roots if os.path.isdir(candidate)), roots[0])
    result = []
    for name in sorted(os.listdir(root)):
        if not name.lower().endswith(".dll"):
            continue
        path = os.path.join(root, name)
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            version = None
            if os.name == "nt":
                try:
                    import win32api
                    info = win32api.GetFileVersionInfo(path, "\\")
                    ms, ls = info["FileVersionMS"], info["FileVersionLS"]
                    version = "%d.%d.%d.%d" % (
                        ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
                except Exception:
                    pass
            result.append({"name": name, "path": path, "version": version,
                           "sha256": digest.hexdigest(), "size": os.path.getsize(path)})
        except OSError as exc:
            result.append({"name": name, "version": None, "sha256": None,
                           "error": type(exc).__name__})
    return result


def _safe_command(args, timeout=2):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {"available": result.returncode == 0, "returncode": result.returncode, "stdout": result.stdout[:2000]}
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__}


def _hardware_details() -> Dict[str, Any]:
    details = {
        "cpu": {"processor": platform.processor(), "machine": platform.machine()},
        "gpu": {"nvidia_smi": shutil.which("nvidia-smi") is not None},
        "motherboard": {},
        "bios": {},
        "drivers": {},
        "conflicts": [],
    }
    try:
        import wmi  # optional
        client = wmi.WMI()
        for item in client.Win32_BIOS():
            details["bios"] = {
                "manufacturer": str(getattr(item, "Manufacturer", "") or ""),
                "version": str(getattr(item, "SMBIOSBIOSVersion", "") or ""),
                "release_date": str(getattr(item, "ReleaseDate", "") or ""),
            }
            break
        for item in client.Win32_ComputerSystem():
            details["motherboard"] = {
                "manufacturer": str(getattr(item, "Manufacturer", "") or ""),
                "model": str(getattr(item, "Model", "") or ""),
            }
            break
    except Exception:
        pass
    try:
        import psutil  # optional
        names = {str(process.info.get("name") or "").lower() for process in psutil.process_iter(["name"])}
        known = ("hwinfo", "hwmonitor", "openhardwaremonitor", "aida64", "msiafterburner", "rtss")
        details["conflicts"] = sorted(name for name in names if any(token in name for token in known))
    except Exception:
        pass
    details["drivers"]["nvidia_smi"] = _safe_command(["nvidia-smi", "-L"]) if shutil.which("nvidia-smi") else {"available": False, "reason": "not_found"}
    optional_gpu = get_nvidia_metrics()
    if optional_gpu:
        details["gpu"]["optional_metrics"] = optional_gpu
    smart = get_smart_devices()
    details["drivers"]["smartctl"] = {
        "available": bool(smart),
        "devices": smart,
    }
    return details


def collect_snapshot(
    registry: Optional[ProviderRegistry] = None,
    current_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect a JSON-safe snapshot; a single failing probe is isolated."""
    registry = registry or get_provider_registry()
    try:
        environment = get_all_diagnostics()
    except Exception as exc:
        environment = {"warnings": ["environment_diagnostics_failed"], "error": type(exc).__name__}
    raw_sensors = (current_data or {}).get("raw_sensors", [])
    raw_reasons = {}
    for sensor in raw_sensors:
        reason = sensor.get("reason") if isinstance(sensor, dict) else None
        if reason:
            raw_reasons[reason] = raw_reasons.get(reason, 0) + 1
    snapshot = {
        "timestamp": time.time(),
        "environment": environment,
        "providers": registry.availability(),
        "hardware": _hardware_details(),
        "pawnio": get_pawnio_status(),
        "vendor_apis": {
            "nvapi": get_nvapi_status(),
            "amd_adl": get_amd_adl_status(),
            "acpi_ec": get_acpi_ec_status(),
        },
        "sensors": {
            "available": bool(current_data),
            "metadata": (current_data or {}).get("metadata", {}),
            "sources": (current_data or {}).get("_sources", {}),
            "raw_count": len(raw_sensors),
            "unknown_count": len((current_data or {}).get("unknown_sensors", [])),
            "validation_reasons": raw_reasons,
        },
        "dlls": _dll_inventory(),
        "diagnostic_mode": os.environ.get("DIAGNOSTIC", "0") == "1",
    }
    if current_data:
        snapshot["sensor_summary"] = {
            key: current_data.get(key)
            for key in ("cpu", "gpu", "motherboard", "storage")
            if key in current_data
        }
    return snapshot


class DiagnosticSnapshot:
    """Reusable snapshot collector for API handlers and integrations."""

    def __init__(self, registry: Optional[ProviderRegistry] = None):
        self.registry = registry or get_provider_registry()

    def collect(self, current_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return collect_snapshot(self.registry, current_data)

    as_dict = collect


def diagnostics_snapshot(registry=None, current_data=None):
    """Backward-friendly alias used by HTTP routes."""
    return collect_snapshot(registry, current_data)
