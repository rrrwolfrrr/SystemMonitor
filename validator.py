"""Единая валидация показаний датчиков.

Модуль намеренно не зависит от psutil или LibreHardwareMonitor, поэтому его
можно использовать как для драйверных, так и для резервных провайдеров.
"""

import math
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ValidationResult:
    """Результат проверки одного показания."""

    value: Optional[float]
    valid: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class SensorContext:
    """Context used to distinguish a legitimate zero from an empty reading."""

    sensor_type: str = ""
    unit: str = ""
    hardware: str = ""
    name: str = ""


# Ноль для этих величин обычно означает «датчик не прочитан», а не реальное
# показание. Для загрузки это также позволяет переключиться на рабочий
# провайдер, если драйвер вернул заглушку 0.0.
FIELD_RULES = {
    "temperature": (-50.0, 150.0, True),
    "voltage": (0.001, 20.0, True),
    "power": (0.001, 2000.0, True),
    "frequency": (0.001, 100000.0, True),
    # Zero load is a valid idle reading; unlike temperature/frequency it must
    # not trigger a fallback provider.
    "load": (0.0, 100.0, False),
    "memory_used": (0.001, 1000000.0, True),
    "memory_total": (0.001, 1000000.0, True),
    "storage.temperature": (-50.0, 150.0, True),
    "storage.temp": (-50.0, 150.0, True),
    "ram.used": (0.001, 1000000.0, True),
    "ram.total": (0.001, 1000000.0, True),
    "network.download_speed_kbps": (0.0, 10**12, False),
    "network.upload_speed_kbps": (0.0, 10**12, False),
}


def _rule_for(field: str):
    """Возвращает наиболее специфичное правило для имени поля."""
    if field in FIELD_RULES:
        return FIELD_RULES[field]
    if field.startswith("storage[") and field.endswith("].temp"):
        return FIELD_RULES["storage.temp"]
    short_name = field.rsplit(".", 1)[-1]
    return FIELD_RULES.get(short_name)


def _normalise_context(sensor_type="", unit="", hardware="", name=""):
    return SensorContext(
        str(sensor_type or ""),
        str(unit or ""),
        str(hardware or ""),
        str(name or ""),
    )


def validate_reading(
    field: str,
    value: Any,
    *,
    sensor_type: str = "",
    unit: str = "",
    hardware: str = "",
    name: str = "",
) -> ValidationResult:
    """Типизированно проверяет показание и возвращает нормализованный float.

    ``None``, bool, нечисловые значения, NaN и бесконечности всегда
    отбрасываются. Для известных полей дополнительно применяются диапазоны и
    проверка нулевого значения.
    """
    if value is None:
        return ValidationResult(None, False, "missing")
    if isinstance(value, bool):
        return ValidationResult(None, False, "not_numeric")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ValidationResult(None, False, "not_numeric")
    if not math.isfinite(number):
        return ValidationResult(None, False, "non_finite")

    context = _normalise_context(sensor_type, unit, hardware, name)
    rule = _rule_for(field)
    # LHM occasionally reports zero for a missing temperature/voltage.  Do
    # not reject a real zero for load, fan duty, throughput, or an explicitly
    # unknown sensor.  Context wins over the broad field-name rule.
    context_type = context.sensor_type.lower()
    context_unit = context.unit.lower()
    if number == 0.0 and (
        context_type in {"load", "fan", "throughput", "level"}
        or context_unit in {"%", "rpm", "kb/s", "mb/s"}
    ):
        if context_type not in {"temperature", "voltage", "power", "clock"}:
            return ValidationResult(0.0, True)
    if rule is None:
        return ValidationResult(number, True)
    minimum, maximum, reject_zero = rule
    if reject_zero and number == 0.0:
        return ValidationResult(None, False, "zero")
    if number < minimum or number > maximum:
        return ValidationResult(None, False, "out_of_range")
    return ValidationResult(number, True)


def is_valid_reading(field: str, value: Any) -> bool:
    """Короткая форма проверки, удобная для условий fallback."""
    return validate_reading(field, value).valid


def validate_sensor_value(value: Any) -> Optional[float]:
    """Проверяет неизвестный тип сенсора (только число и finite)."""
    result = validate_reading("sensor", value)
    return result.value if result.valid else None


def validate_sensor_reading(
    value: Any,
    sensor_type: str = "",
    unit: str = "",
    hardware: str = "",
    name: str = "",
    field: str = "sensor",
) -> ValidationResult:
    """Validate a raw LHM value with sensor/hardware context."""
    return validate_reading(
        field,
        value,
        sensor_type=sensor_type,
        unit=unit,
        hardware=hardware,
        name=name,
    )


def suspicious_jump(previous: Any, current: Any, sensor_type: str = "") -> Optional[str]:
    """Return a reason for an implausible abrupt change, if any.

    This is intentionally conservative: it is metadata only and never drops
    a value.  Percentages use an absolute threshold, while other readings use
    a relative threshold.
    """
    if previous is None or current is None:
        return None
    try:
        old, new = float(previous), float(current)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(old) or not math.isfinite(new):
        return "non_finite_jump"
    kind = str(sensor_type or "").lower()
    if kind == "load":
        return "abrupt_change" if abs(new - old) > 75 else None
    if abs(old) < 1e-9:
        return "abrupt_change" if abs(new) > 100 else None
    return "abrupt_change" if abs(new - old) / abs(old) > 3.0 else None


# Короткие имена оставлены для провайдеров, которым нужна функция без
# привязки к конкретной структуре ValidationResult.
validate_value = validate_reading
is_valid_value = is_valid_reading
VALIDATION_RULES = FIELD_RULES


def field_metadata(
    source: str,
    status: str,
    quality: str,
    reason: Optional[str] = None,
) -> dict:
    """Создаёт совместимую с JSON метаинформацию поля."""
    return {
        "source": source,
        "status": status,
        "quality": quality,
        "reason": reason,
    }
