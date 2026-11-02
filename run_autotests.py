"""Run the complete SystemMonitor verification suite.

Use --live to collect sensors from the current PC. Hardware cases that do not
exist on the current PC are reported as skipped, not treated as failures.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unittest

from schema import validate_raw_sensor
from verify_build import verify_distribution


ROOT = os.path.dirname(os.path.abspath(__file__))


def run_unit_tests():
    suite = unittest.defaultTestLoader.discover(ROOT, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def run_live_probe():
    from libre_monitor import LibreMonitor, LHM_AVAILABLE

    report = {"available": bool(LHM_AVAILABLE), "sensors": 0, "cases": []}
    if not LHM_AVAILABLE:
        report["status"] = "skipped"
        report["reason"] = "LibreHardwareMonitor DLL/pythonnet unavailable"
        return report

    monitor = LibreMonitor()
    try:
        if not monitor.start():
            return {
                **report,
                "status": "skipped",
                "reason": "LibreHardwareMonitor could not initialize on this PC",
            }
        data = monitor.fetch_data() or {}
        sensors = data.get("raw_sensors", [])
        valid = [sensor for sensor in sensors if validate_raw_sensor(sensor)]
        report["sensors"] = len(valid)
        report["invalid_sensors"] = len(sensors) - len(valid)
        report["hardware_types"] = sorted({
            str(sensor.get("hardware_type") or sensor.get("hardware", "unknown"))
            for sensor in valid
        })
        report["status"] = "ok" if len(sensors) == len(valid) else "failed"

        with open(os.path.join(ROOT, "hardware_test_matrix.json"), encoding="utf-8") as stream:
            matrix = json.load(stream)
        for case in matrix["cases"]:
            hardware = case["hardware"].lower()
            matches = [
                sensor for sensor in valid
                if hardware == "any"
                or hardware in str(sensor.get("hardware_type", "")).lower()
                or hardware in str(sensor.get("hardware", "")).lower()
            ]
            report["cases"].append({
                "id": case["id"],
                "status": "ok" if matches else "skipped",
                "sensor_count": len(matches),
            })
        return report
    finally:
        monitor.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="probe sensors on this physical PC")
    parser.add_argument("--build", metavar="PATH",
                        help="verify a PyInstaller one-dir output")
    args = parser.parse_args(argv)

    success = run_unit_tests()
    if args.build:
        build_ok, missing = verify_distribution(args.build)
        print("Build verification:", "OK" if build_ok else "FAILED")
        if missing:
            print("Missing:", ", ".join(missing))
        success = success and build_ok
    if args.live:
        live = run_live_probe()
        print(json.dumps(live, ensure_ascii=False, indent=2))
        success = success and live["status"] in {"ok", "skipped"}
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
