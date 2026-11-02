"""PawnIO driver detection and optional installer support."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _hidden_process_kwargs() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def get_pawnio_status() -> Dict[str, Any]:
    """Return the installed/running state of the PawnIO service."""
    if os.name != "nt":
        return {"available": False, "installed": False, "running": False,
                "reason": "not_windows"}
    try:
        result = subprocess.run(
            ["sc.exe", "query", "PawnIO"],
            capture_output=True,
            text=False,
            timeout=3,
            check=False,
            **_hidden_process_kwargs(),
        )
        output = (result.stdout or b"") + b"\n" + (result.stderr or b"")
        # sc.exe may emit localized labels in the OEM code page; the service
        # exit code and the English state token remain stable.
        installed = result.returncode == 0
        running = b"RUNNING" in output.upper()
        return {
            "available": installed and running,
            "installed": installed,
            "running": running,
            "returncode": result.returncode,
        }
    except Exception as exc:
        logger.debug("Не удалось проверить службу PawnIO: %s", exc)
        return {"available": False, "installed": False, "running": False,
                "reason": type(exc).__name__}


def pawnio_installer_path(base_dir: str) -> str:
    """Return the bundled PawnIO installer path."""
    return os.path.join(base_dir, "PawnIO_setup.exe")
