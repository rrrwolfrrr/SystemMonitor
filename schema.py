"""Small, dependency-free checks for public sensor JSON formats."""

from __future__ import annotations


RAW_SENSOR_FIELDS = (
    "hardware", "subhardware", "type", "name", "value", "unit", "identifier",
)


def validate_raw_sensor(sensor) -> bool:
    if not isinstance(sensor, dict) or any(key not in sensor for key in RAW_SENSOR_FIELDS):
        return False
    return isinstance(sensor["hardware"], str) and isinstance(sensor["type"], str)


def validate_sensor_payload(payload) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("sensors", []), list)
        and all(validate_raw_sensor(sensor) for sensor in payload.get("sensors", []))
    )
