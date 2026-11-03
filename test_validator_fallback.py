"""Небольшие автономные проверки валидатора и цепочки fallback."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import providers
from fallback import _get_battery_wmi, apply_fallbacks, get_battery
from libre_monitor import LibreMonitorDirect
from providers import ProviderRegistry, create_default_registry, get_gpu_memory_metrics
from sensor_resolver import SensorResolver, StaleValueCache
from validator import is_valid_reading, validate_reading


class ValidatorTests(unittest.TestCase):
    def test_rejects_invalid_numeric_values(self):
        for value in (None, 0.0, float("nan"), float("inf")):
            self.assertFalse(is_valid_reading("cpu.temperature", value))

    def test_accepts_field_range(self):
        self.assertTrue(is_valid_reading("cpu.temperature", 42.5))
        self.assertFalse(is_valid_reading("cpu.temperature", 151))
        self.assertEqual(validate_reading("network.download_speed_kbps", 0).value, 0)
        self.assertTrue(is_valid_reading("cpu.load", 0.0))
        self.assertFalse(is_valid_reading("storage[0].temp", 0.0))

    def test_common_hardware_matrix_rules(self):
        cases = (
            ("amd_ryzen_cpu_temperature", "cpu.temperature", 0.0, False),
            ("intel_cpu_frequency", "cpu.frequency", 0.0, False),
            ("nvidia_gpu_temperature", "gpu.temperature", 0.0, False),
            ("amd_gpu_load_at_idle", "gpu.load", 0.0, True),
            ("motherboard_fan_stopped", "fan.rpm", 0.0, True),
            ("disk_temperature", "storage.temperature", 0.0, False),
            ("network_idle", "network.download_speed_kbps", 0.0, True),
            ("broken_sensor_nan", "cpu.temperature", float("nan"), False),
        )
        for name, field, value, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(is_valid_reading(field, value), expected)


class FallbackTests(unittest.TestCase):
    @patch("fallback._get_wmi")
    def test_wmi_battery_exposes_available_capacity_health_and_status(self, get_wmi):
        battery = SimpleNamespace(
            Name="Laptop Battery",
            DeviceID="BAT0",
            EstimatedChargeRemaining=74,
            EstimatedRunTime=125,
            BatteryStatus=6,
            Chemistry=6,
            DesignCapacity=50000,
            FullChargeCapacity=42000,
            DesignVoltage=11500,
            MaxRechargeTime=180,
            ExpectedBatteryLife=14400,
            ExpectedBatteryLifeTime=240,
            TimeOnBattery=3600,
            TimeToFullCharge=7200,
            Availability=3,
            ConfigManagerErrorCode=0,
            PowerManagementSupported=True,
            StatusInfo=2,
            Status="OK",
        )
        get_wmi.return_value.Win32_Battery.return_value = [battery]

        result = _get_battery_wmi()

        self.assertEqual(result["battery_status"], "Заряжается")
        self.assertEqual(result["design_capacity_mwh"], 50000)
        self.assertEqual(result["full_charge_capacity_mwh"], 42000)
        self.assertEqual(result["health_percent"], 84.0)
        self.assertEqual(result["expected_life_seconds"], 14400)
        self.assertEqual(result["device_id"], "BAT0")
        self.assertTrue(result["power_management_supported"])

    @patch("fallback._get_wmi")
    def test_wmi_battery_omits_unknown_values_and_returns_multiple_packs(self, get_wmi):
        first = SimpleNamespace(
            Name="Battery 1",
            EstimatedChargeRemaining=55,
            EstimatedRunTime=0xFFFFFFFF,
            DesignCapacity=0,
            FullChargeCapacity=None,
            BatteryStatus=15,
        )
        second = SimpleNamespace(Name="Battery 2", EstimatedChargeRemaining=45, BatteryStatus=3)
        get_wmi.return_value.Win32_Battery.return_value = [first, second]

        result = _get_battery_wmi()

        self.assertEqual(len(result["batteries"]), 2)
        self.assertNotIn("remaining_minutes", result)
        self.assertNotIn("design_capacity_mwh", result)
        self.assertEqual(result["batteries"][1]["battery_status"], "Полностью заряжена")

    @patch("fallback._try_source")
    def test_get_battery_preserves_psutil_fields_and_adds_wmi_pack_details(self, try_source):
        try_source.side_effect = [
            {"percent": 74.0, "plugged": True, "status": "charging", "secsleft": None},
            {
                "name": "Laptop Battery",
                "design_capacity_mwh": 50000,
                "batteries": [{"name": "Laptop Battery", "percent": 74}],
            },
        ]

        result = get_battery()

        self.assertEqual(result["percent"], 74.0)
        self.assertEqual(result["status"], "charging")
        self.assertEqual(result["design_capacity_mwh"], 50000)
        self.assertEqual(result["batteries"][0]["name"], "Laptop Battery")

    @patch("fallback._try_source")
    def test_wmi_only_battery_infers_charging_state_and_ac_power(self, try_source):
        try_source.side_effect = [
            None,
            {
                "percent": 44,
                "battery_status_code": 14,
                "battery_status": "Заряжается",
            },
        ]

        result = get_battery()

        self.assertEqual(result["status"], "charging")
        self.assertTrue(result["plugged"])
        self.assertEqual(result["batteries"][0]["battery_status_code"], 14)

    @patch("fallback.get_cpu_freq", return_value=2200.0)
    def test_zero_native_value_uses_fallback(self, get_cpu_freq):
        data = {
            "cpu": {
                "frequency": 0.0,
                "frequency_effective": None,
                "load": None,
                "temperature": None,
            },
            "ram": {},
        }
        result = apply_fallbacks(data)
        self.assertEqual(result["cpu"]["frequency"], 2200.0)
        self.assertEqual(result["metadata"]["cpu.frequency"]["source"], "fallback")
        get_cpu_freq.assert_called_once()

    def test_zero_disk_temperature_keeps_disk_visible(self):
        result = apply_fallbacks({
            "cpu": {},
            "ram": {},
            "storage": [{"name": "NVMe", "temp": 0.0}],
        })
        self.assertEqual(len(result["storage"]), 1)
        self.assertIsNone(result["storage"][0]["temp"])
        self.assertEqual(result["storage"][0]["status"], "temporary_unavailable")
        self.assertEqual(
            result["metadata"]["storage[0].temp"]["reason"],
            "zero",
        )

    @patch("fallback.get_gpu_memory_metrics", return_value={
        "dedicated_memory_used_mb": 3584.0,
        "shared_memory_used_mb": 716.0,
        "shared_memory_total_mb": 24576.0,
    })
    @patch("fallback.get_nvidia_metrics", return_value={})
    def test_gpu_stats_include_dedicated_and_shared_memory(self, get_nvidia_metrics, get_gpu_memory_metrics):
        result = apply_fallbacks({
            "cpu": {},
            "gpu": {"memory_used": 3400.0, "memory_total": 16384.0},
            "ram": {},
        })

        self.assertEqual(result["gpu"]["dedicated_memory_used_mb"], 3584.0)
        self.assertEqual(result["gpu"]["dedicated_memory_total_mb"], 16384.0)
        self.assertEqual(result["gpu"]["shared_memory_used_mb"], 716.0)
        self.assertEqual(result["gpu"]["shared_memory_total_mb"], 24576.0)
        get_gpu_memory_metrics.assert_called_once()
        get_nvidia_metrics.assert_called_once()


class StorageTemperatureTests(unittest.TestCase):
    @staticmethod
    def make_sensor(name, value, identifier):
        return SimpleNamespace(
            SensorType="Temperature",
            Name=name,
            Value=value,
            Identifier=identifier,
        )

    def parse_storage(self, sensors):
        monitor = LibreMonitorDirect.__new__(LibreMonitorDirect)
        hardware = SimpleNamespace(
            HardwareType="Storage",
            Name="Test NVMe",
            Identifier="/nvme/0",
            Sensors=sensors,
            SubHardware=[],
        )
        result = {"storage": []}
        monitor._parse_storage(hardware, result)
        return result["storage"][0]

    def test_composite_temperature_is_preferred_over_nvme_threshold_sensors(self):
        disk = self.parse_storage([
            self.make_sensor("Critical Temperature", 84, "/nvme/0/temperature/11"),
            self.make_sensor("Warning Temperature", 84, "/nvme/0/temperature/10"),
            self.make_sensor("Composite Temperature", 42, "/nvme/0/temperature/0"),
        ])

        self.assertEqual(disk["temp"], 42)
        self.assertEqual(disk["temp_sensor"], "Composite Temperature")
        self.assertEqual(disk["device_id"], "/nvme/0")
        self.assertEqual(disk["identifier"], "/nvme/0/temperature/0")
        self.assertEqual(disk["status"], "valid")

    def test_temperature_fallback_skips_warning_and_critical_limits(self):
        disk = self.parse_storage([
            self.make_sensor("Critical Temperature", 84, "/nvme/0/temperature/11"),
            self.make_sensor("Temperature #1", 43, "/nvme/0/temperature/1"),
            self.make_sensor("Warning Temperature", 70, "/nvme/0/temperature/10"),
        ])

        self.assertEqual(disk["temp"], 43)
        self.assertEqual(disk["temp_sensor"], "Temperature #1")

    def test_only_limit_sensors_do_not_appear_as_current_temperature(self):
        disk = self.parse_storage([
            self.make_sensor("Warning Temperature", 70, "/nvme/0/temperature/10"),
            self.make_sensor("Critical Temperature", 84, "/nvme/0/temperature/11"),
        ])

        self.assertIsNone(disk["temp"])
        self.assertIsNone(disk["temp_sensor"])
        self.assertEqual(disk["status"], "temporary_unavailable")


class ResolverTests(unittest.TestCase):
    def test_resolver_uses_provider_after_invalid_native_value(self):
        resolver = SensorResolver(stale_enabled=False)
        result = resolver.resolve("cpu.frequency", 0, (("mock", lambda: 1234.0),))
        self.assertEqual(result.value, 1234.0)
        self.assertEqual(result.source, "mock")
        self.assertEqual(result.status, "valid")

    def test_resolver_returns_stale_value_when_provider_fails(self):
        now = [100.0]
        cache = StaleValueCache(ttl_seconds=20, clock=lambda: now[0])
        resolver = SensorResolver(stale_cache=cache, stale_enabled=True)
        self.assertEqual(resolver.resolve("cpu.temperature", 42.0).value, 42.0)
        now[0] = 105.0
        stale = resolver.resolve("cpu.temperature", None, (("broken", lambda: None),))
        self.assertEqual(stale.value, 42.0)
        self.assertEqual(stale.status, "stale")
        self.assertEqual(stale.source, "stale-cache")
        now[0] = 130.0
        self.assertIsNone(resolver.resolve("cpu.temperature", None).value)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        from providers import _GPU_MEMORY_CACHE, _GPU_MEMORY_LOCK
        with _GPU_MEMORY_LOCK:
            _GPU_MEMORY_CACHE.update(timestamp=0.0, value={})

    def test_gpu_memory_provider_selects_active_adapter_and_converts_bytes(self):
        pdh = SimpleNamespace(
            PERF_DETAIL_WIZARD=400,
            PDH_FMT_LARGE=4,
            EnumObjectItems=lambda *_: (
                ["Dedicated Usage", "Shared Usage"],
                ["adapter_1", "adapter_2"],
            ),
            OpenQuery=lambda: "query",
            AddEnglishCounter=lambda query, path: path,
            CollectQueryData=lambda query: None,
            CloseQuery=lambda query: None,
        )
        values = {
            "adapter_1": {"Dedicated Usage": 1000, "Shared Usage": 200},
            "adapter_2": {"Dedicated Usage": 3000, "Shared Usage": 500},
        }

        def read_counter(path, _format):
            instance = path.split("(")[1].split(")")[0]
            counter_name = path.rsplit("\\", 1)[1]
            byte_value = values[instance][counter_name] * 1024 ** 2
            return 65792, {"CStatus": 0, "largeValue": byte_value}

        pdh.GetFormattedCounterValue = read_counter
        psutil = SimpleNamespace(virtual_memory=lambda: SimpleNamespace(total=48 * 1024 ** 3))
        pywintypes = SimpleNamespace(error=OSError)
        import_module = unittest.mock.Mock(
            side_effect=lambda name: {
                "win32pdh": pdh,
                "pywintypes": pywintypes,
                "psutil": psutil,
            }[name]
        )
        with (
            patch("providers.os.name", "nt"),
            patch("providers.time.monotonic", return_value=100.0),
            patch.object(providers, "importlib", SimpleNamespace(import_module=import_module)),
        ):
            result = get_gpu_memory_metrics()

        self.assertEqual(result["dedicated_memory_used_mb"], 3000.0)
        self.assertEqual(result["shared_memory_used_mb"], 500.0)
        self.assertEqual(result["shared_memory_total_mb"], 24576.0)
        self.assertEqual(import_module.call_args_list, [unittest.mock.call("win32pdh"), unittest.mock.call("pywintypes"), unittest.mock.call("psutil")])

    def test_gpu_memory_provider_caches_short_interval(self):
        pdh = SimpleNamespace(
            PERF_DETAIL_WIZARD=400,
            EnumObjectItems=lambda *_: ([], []),
        )
        pywintypes = SimpleNamespace(error=OSError)
        import_module = unittest.mock.Mock(
            side_effect=lambda name: {"win32pdh": pdh, "pywintypes": pywintypes}[name]
        )
        with (
            patch("providers.os.name", "nt"),
            patch("providers.time.monotonic", side_effect=[100.0, 100.5]),
            patch.object(providers, "importlib", SimpleNamespace(import_module=import_module)),
        ):
            first = get_gpu_memory_metrics()
            second = get_gpu_memory_metrics()

        self.assertEqual(first, {})
        self.assertEqual(second, {})
        self.assertEqual(
            import_module.call_args_list,
            [unittest.mock.call("win32pdh"), unittest.mock.call("pywintypes")],
        )

    def test_registry_handles_unavailable_provider_without_import_error(self):
        registry = ProviderRegistry()
        registry.register("missing", lambda: False)
        status = registry.check("missing").as_dict()
        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "unavailable")

    def test_default_optional_providers_are_disabled_by_default(self):
        registry = create_default_registry(enable_nvml=False, enable_nvidia_smi=False, enable_smart=False)
        statuses = registry.availability()
        self.assertFalse(statuses["nvml"]["enabled"])
        self.assertFalse(statuses["nvidia-smi"]["enabled"])
        self.assertFalse(statuses["smartctl"]["enabled"])


if __name__ == "__main__":
    unittest.main()
