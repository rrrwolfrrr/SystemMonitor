"""Verify that a PyInstaller one-dir output contains every runtime asset."""

from __future__ import annotations

import argparse
import os
import sys


REQUIRED = (
    "SystemMonitor.exe",
    "LibreHardwareMonitorLib.dll",
    "PresentMon-2.6.0-x64.exe",
    "PRESENTMON_LICENSE.txt",
    "PawnIO_setup.exe",
    "templates/dashboard.html",
    "templates/MobileDashboard.html",
    "templates/all_sensors.html",
    "hardware_test_matrix.json",
    "_internal",
)


def verify_distribution(path: str) -> tuple[bool, list[str]]:
    missing = []
    for relative in REQUIRED:
        direct = os.path.join(path, *relative.split("/"))
        bundled = os.path.join(path, "_internal", *relative.split("/"))
        if not os.path.exists(direct) and not os.path.exists(bundled):
            missing.append(relative)
    return not missing, missing


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=os.path.join("dist", "SystemMonitor"))
    args = parser.parse_args(argv)
    ok, missing = verify_distribution(args.path)
    if not ok:
        print("Missing build assets: " + ", ".join(missing), file=sys.stderr)
        return 1
    print("PyInstaller distribution completeness: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
