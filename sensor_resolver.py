"""Validation, provider selection and stale-value handling for sensors."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from validator import suspicious_jump, validate_reading


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ResolvedValue:
    value: Optional[float]
    source: str
    status: str
    quality: str
    reason: Optional[str] = None
    stale_age_seconds: Optional[float] = None
    suspicious: bool = False
    metadata: Optional[dict] = None

    def as_metadata(self):
        result = {
            "source": self.source,
            "status": self.status,
            "quality": self.quality,
            "reason": self.reason,
            "stale_age_seconds": self.stale_age_seconds,
            "suspicious": self.suspicious,
        }
        if self.metadata:
            result.update(self.metadata)
        return result


class StaleValueCache:
    """Thread-safe cache containing only values accepted by validator.py."""

    def __init__(self, ttl_seconds: float = 30.0, clock: Callable[[], float] = time.time):
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._values = {}
        self._lock = threading.RLock()

    def put(self, field: str, value: Any, source: str = "native", timestamp: Optional[float] = None) -> bool:
        checked = validate_reading(field, value)
        if not checked.valid:
            self.mark_failed(field, checked.reason)
            return False
        with self._lock:
            now = self._clock() if timestamp is None else timestamp
            old = self._values.get(field)
            suspicious = suspicious_jump(old["value"], checked.value) if old else None
            self._values[field] = {
                "value": checked.value,
                "source": source,
                "timestamp": now,
                "last_valid_at": now,
                "failed_reads": old.get("failed_reads", 0) if old else 0,
                "last_failure_reason": None,
                "suspicious": suspicious,
            }
        return True

    def mark_failed(self, field: str, reason: Optional[str] = None) -> None:
        with self._lock:
            item = self._values.get(field)
            if item is None:
                self._values[field] = {
                    "value": None, "source": "none", "timestamp": 0.0,
                    "last_valid_at": None, "failed_reads": 1,
                    "last_failure_reason": reason or "temporary_unavailable",
                    "suspicious": False,
                }
            else:
                item["failed_reads"] = int(item.get("failed_reads", 0)) + 1
                item["last_failure_reason"] = reason or "temporary_unavailable"

    def get(self, field: str, now: Optional[float] = None):
        with self._lock:
            item = self._values.get(field)
        if item is None:
            return None
        value, source, timestamp = item["value"], item["source"], item["timestamp"]
        if value is None or not timestamp:
            return None
        age = max(0.0, (self._clock() if now is None else now) - timestamp)
        if age > self.ttl_seconds:
            return None
        result = dict(item)
        result["age_seconds"] = age
        return result

    def clear(self):
        with self._lock:
            self._values.clear()

    def snapshot(self):
        with self._lock:
            return {field: dict(item) for field, item in self._values.items()}


class SensorResolver:
    """Resolve native readings, fallback callbacks and finally stale cache."""

    def __init__(
        self,
        stale_cache: Optional[StaleValueCache] = None,
        stale_enabled: Optional[bool] = None,
        stale_ttl_seconds: Optional[float] = None,
    ):
        ttl = stale_ttl_seconds
        if ttl is None:
            try:
                ttl = float(os.getenv("SYSTEMMONITOR_STALE_CACHE_TTL", "30"))
            except ValueError:
                ttl = 30.0
        self.stale_enabled = _env_bool("SYSTEMMONITOR_STALE_CACHE_ENABLED", True) if stale_enabled is None else bool(stale_enabled)
        self.stale_cache = stale_cache or StaleValueCache(ttl)

    @staticmethod
    def _candidate(candidate):
        if isinstance(candidate, tuple) and len(candidate) == 2:
            return str(candidate[0]), candidate[1]
        return getattr(candidate, "__name__", "fallback"), candidate

    def resolve(
        self,
        field: str,
        native_value: Any,
        providers: Optional[Iterable] = None,
    ) -> ResolvedValue:
        native = validate_reading(field, native_value)
        if native.valid:
            self.stale_cache.put(field, native.value, "libre")
            cached = self.stale_cache.get(field)
            suspicious = bool(cached and cached.get("suspicious"))
            return ResolvedValue(
                native.value, "libre", "valid", "high",
                "suspicious_jump" if suspicious else None,
                suspicious=suspicious,
            )

        candidates = providers.items() if isinstance(providers, dict) else (providers or ())
        provider_attempted = False
        for item in candidates:
            name, callback = self._candidate(item)
            if not callable(callback):
                continue
            provider_attempted = True
            try:
                result = validate_reading(field, callback())
            except Exception:
                self.stale_cache.mark_failed(field, "provider_error")
                continue
            if result.valid:
                self.stale_cache.put(field, result.value, name)
                return ResolvedValue(result.value, name, "valid", "medium", native.reason)
            self.stale_cache.mark_failed(field, result.reason)

        if self.stale_enabled:
            cached = self.stale_cache.get(field)
            if cached is not None:
                return ResolvedValue(
                    cached["value"],
                    "stale-cache",
                    "stale",
                    "low",
                    "stale_cache",
                    cached["age_seconds"],
                    bool(cached.get("suspicious")),
                    {"failed_reads": cached.get("failed_reads", 0), "last_valid_at": cached.get("last_valid_at")},
                )
        reason = native.reason or "missing"
        if provider_attempted and reason == "missing":
            reason = "temporary_unavailable"
        return ResolvedValue(None, "none", "missing", "unavailable", reason)

    def snapshot(self):
        return self.stale_cache.snapshot()
