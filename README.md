# SystemMonitor

SystemMonitor is a Windows desktop application for monitoring PC hardware and
viewing sensor data in desktop and mobile dashboards. It also provides optional
per-process FPS monitoring through PresentMon and Windows ETW.

## Requirements

- Windows 10/11, 64-bit
- Python and the project dependencies listed in `requirements.txt` to run from
  source
- The pinned runtime DLL dependencies and PresentMon executable used for the
  packaged app. The separate PawnIO setup executable is not included; its
  driver source and license notices are under `third_party/PawnIO/2.1.0`.
  See [BUILD.md](BUILD.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

See [BUILD.md](BUILD.md) for setup, tests, and packaging instructions.

## Project status

This project is being prepared for a private GitHub repository. The project
license has not been selected yet. No license to use, modify, or redistribute
the SystemMonitor project is granted until one is added. Third-party components
retain their own licenses; review
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistribution.
