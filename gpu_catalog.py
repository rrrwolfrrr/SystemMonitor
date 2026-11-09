"""Build per-adapter GPU data from the unfiltered LibreHardwareMonitor sensors."""

from __future__ import annotations

from collections import OrderedDict
from math import isfinite


GPU_HARDWARE_TYPES = frozenset({"GpuNvidia", "GpuAmd", "GpuIntel"})


def classify_gpu_temperature(name: str) -> str:
    """Classify a temperature sensor so VRAM readings are not used as GPU core."""
    name_lower = str(name or "").lower()
    if any(marker in name_lower for marker in ("memory", "vram")):
        return "memory"
    if any(marker in name_lower for marker in ("hotspot", "hot spot", "junction")):
        return "hotspot"
    if any(marker in name_lower for marker in ("core", "edge", "die")):
        return "core"
    return "other"


def build_gpu_devices(raw_sensors: list[dict]) -> list[dict]:
    devices = OrderedDict()
    for sensor in raw_sensors:
        if not isinstance(sensor, dict):
            continue
        identifier = sensor.get("gpu_identifier")
        if not isinstance(identifier, str) or not identifier:
            continue

        device = devices.get(identifier)
        if device is None:
            device = {
                "identifier": identifier,
                "name": sensor.get("gpu_name") or sensor.get("hardware") or "GPU",
                "hardware_type": sensor.get("gpu_hardware_type") or "unknown",
                "sensors": [],
                "temperature": None,
                "hotspot_temperature": None,
                "load": None,
                "frequency": None,
                "voltage": None,
                "power": None,
                "memory_used": None,
                "memory_total": None,
                "_temperature_priority": 0,
            }
            devices[identifier] = device

        device["sensors"].append(sensor)
        value = sensor.get("value")
        if not sensor.get("valid") or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if not isfinite(value):
            continue

        sensor_type = str(sensor.get("type") or "")
        name = str(sensor.get("name") or "")
        name_lower = name.lower()
        if sensor_type == "Temperature":
            temperature_kind = classify_gpu_temperature(name)
            if temperature_kind == "hotspot":
                key = "hotspot_temperature"
                device[key] = max(device[key], value) if device[key] is not None else value
            elif temperature_kind != "memory":
                priority = 2 if temperature_kind == "core" else 1
                if (
                    priority > device["_temperature_priority"]
                    or (
                        priority == device["_temperature_priority"]
                        and (device["temperature"] is None or value > device["temperature"])
                    )
                ):
                    device["temperature"] = value
                    device["_temperature_priority"] = priority
        elif sensor_type == "Load":
            device["load"] = max(device["load"], value) if device["load"] is not None else value
        elif sensor_type == "Clock" and ("core" in name_lower or "gpu" in name_lower):
            device["frequency"] = max(device["frequency"], value) if device["frequency"] is not None else value
        elif sensor_type == "Voltage":
            device["voltage"] = max(device["voltage"], value) if device["voltage"] is not None else value
        elif sensor_type == "Power":
            device["power"] = max(device["power"], value) if device["power"] is not None else value
        elif sensor_type in {"SmallData", "Data"}:
            if "used" in name_lower:
                device["memory_used"] = value
            elif "total" in name_lower or "dedicated" in name_lower:
                device["memory_total"] = value

    result = list(devices.values())
    for device in result:
        device.pop("_temperature_priority", None)
    return result
