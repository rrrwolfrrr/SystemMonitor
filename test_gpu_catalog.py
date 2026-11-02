import unittest

from gpu_catalog import build_gpu_devices
from libre_monitor import LibreMonitorDirect


class FakeSensor:
    def __init__(self, identifier, name, value):
        self.Identifier = identifier
        self.Name = name
        self.SensorType = "Temperature"
        self.Value = value


class FakeHardware:
    def __init__(self, name, hardware_type, identifier=None, sensors=None, children=None):
        self.Name = name
        self.HardwareType = hardware_type
        self.Identifier = identifier
        self.Sensors = sensors or []
        self.SubHardware = children or []


class GpuCatalogTests(unittest.TestCase):
    def test_builds_separate_devices_with_duplicate_sensor_names(self):
        sensors = [
            {
                "gpu_identifier": "/gpu-nvidia/0",
                "gpu_name": "Same GPU",
                "gpu_hardware_type": "GpuNvidia",
                "hardware": "Same GPU",
                "name": "GPU Core",
                "type": "Temperature",
                "value": 55.0,
                "valid": True,
            },
            {
                "gpu_identifier": "/gpu-nvidia/0",
                "gpu_name": "Same GPU",
                "gpu_hardware_type": "GpuNvidia",
                "hardware": "Same GPU",
                "name": "GPU Core",
                "type": "Load",
                "value": 25.0,
                "valid": True,
            },
            {
                "gpu_identifier": "/gpu-nvidia/1",
                "gpu_name": "Same GPU",
                "gpu_hardware_type": "GpuNvidia",
                "hardware": "Same GPU",
                "name": "GPU Core",
                "type": "Temperature",
                "value": 72.0,
                "valid": True,
            },
            {
                "gpu_identifier": "/gpu-nvidia/1",
                "gpu_name": "Same GPU",
                "gpu_hardware_type": "GpuNvidia",
                "hardware": "Same GPU",
                "name": "GPU Core",
                "type": "Load",
                "value": 90.0,
                "valid": True,
            },
        ]

        devices = build_gpu_devices(sensors)

        self.assertEqual(
            [device["identifier"] for device in devices],
            ["/gpu-nvidia/0", "/gpu-nvidia/1"],
        )
        self.assertEqual(devices[0]["temperature"], 55.0)
        self.assertEqual(devices[0]["load"], 25.0)
        self.assertEqual(devices[1]["temperature"], 72.0)
        self.assertEqual(devices[1]["load"], 90.0)
        self.assertEqual(len(devices[0]["sensors"]), 2)
        self.assertEqual(len(devices[1]["sensors"]), 2)

    def test_ignores_invalid_values_but_keeps_sensor_in_device_catalog(self):
        sensors = [{
            "gpu_identifier": "/gpu-intel/0",
            "gpu_name": "Integrated GPU",
            "gpu_hardware_type": "GpuIntel",
            "hardware": "Integrated GPU",
            "name": "Temperature",
            "type": "Temperature",
            "value": 1500.0,
            "valid": False,
        }]

        devices = build_gpu_devices(sensors)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["sensors"], sensors)
        self.assertIsNone(devices[0]["temperature"])

    def test_ignores_sensors_without_gpu_identity(self):
        self.assertEqual(build_gpu_devices([{
            "hardware": "CPU",
            "name": "Temperature",
            "type": "Temperature",
            "value": 50.0,
            "valid": True,
        }]), [])

    def test_raw_collector_inherits_gpu_identity_for_subhardware(self):
        monitor = LibreMonitorDirect.__new__(LibreMonitorDirect)
        raw_sensors = []
        devices = [
            FakeHardware(
                "GPU A",
                "GpuNvidia",
                "/gpu-nvidia/0",
                children=[FakeHardware(
                    "GPU A Sensors",
                    "Unknown",
                    sensors=[FakeSensor("sensor-a", "Core", 60.0)],
                )],
            ),
            FakeHardware(
                "GPU B",
                "GpuNvidia",
                "/gpu-nvidia/1",
                sensors=[FakeSensor("sensor-b", "Core", 70.0)],
            ),
        ]

        for device in devices:
            monitor._collect_raw(device, raw_sensors)

        self.assertEqual(
            [sensor["gpu_identifier"] for sensor in raw_sensors],
            ["/gpu-nvidia/0", "/gpu-nvidia/1"],
        )
        self.assertEqual(
            [sensor["gpu_name"] for sensor in raw_sensors],
            ["GPU A", "GPU B"],
        )


if __name__ == "__main__":
    unittest.main()
