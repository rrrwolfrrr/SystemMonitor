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


def _find_asset(path: str, relative: str) -> str | None:
    direct = os.path.join(path, *relative.split("/"))
    bundled = os.path.join(path, "_internal", *relative.split("/"))
    if os.path.exists(direct):
        return direct
    if os.path.exists(bundled):
        return bundled
    return None


def verify_distribution(
    path: str,
    source_root: str | None = None,
) -> tuple[bool, list[str]]:
    missing = []
    for relative in REQUIRED:
        if _find_asset(path, relative) is None:
            missing.append(relative)

    if source_root is not None:
        source_dashboard = os.path.join(source_root, "templates", "dashboard.html")
        bundled_dashboard = _find_asset(path, "templates/dashboard.html")
        if not os.path.isfile(source_dashboard):
            missing.append("source templates/dashboard.html")
        elif bundled_dashboard is not None:
            with open(source_dashboard, "rb") as source_file:
                source_content = source_file.read()
            with open(bundled_dashboard, "rb") as bundled_file:
                bundled_content = bundled_file.read()
            if source_content != bundled_content:
                missing.append("templates/dashboard.html (out of date)")

    return not missing, missing


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=os.path.join("dist", "SystemMonitor"))
    parser.add_argument(
        "--source-root",
        help="Project root to compare packaged Dashboard templates against",
    )
    args = parser.parse_args(argv)
    ok, missing = verify_distribution(args.path, args.source_root)
    if not ok:
        print("Missing build assets: " + ", ".join(missing), file=sys.stderr)
        return 1
    print("PyInstaller distribution completeness and source freshness: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
