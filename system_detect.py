#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Определение системных параметров и диагностика проблем.

Этот модуль проверяет:
- Запущена ли программа с правами администратора
- Включена ли защита ядра (Core Isolation / Memory Integrity)
- Доступность драйвера LibreHardwareMonitor
- Массу других системных параметров, влияющих на работу датчиков
"""

import logging
import os
import sys
import platform
import ctypes
import subprocess
from pawnio import get_pawnio_status

logger = logging.getLogger(__name__)

# Кэш для результатов проверок
_CHECK_CACHE = {}
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _hidden_process_kwargs():
    """Prevent diagnostic commands from opening a console window on Windows."""
    kwargs = {"creationflags": _CREATE_NO_WINDOW}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _check_admin():
    """Проверяет, запущен ли Python с правами администратора (Windows)."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _check_memory_integrity():
    """Проверяет, включена ли защита ядра (Memory Integrity / Core Isolation)."""
    try:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                              r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity") as key:
                enabled = winreg.QueryValueEx(key, "Enabled")[0]
                if enabled == 1:
                    return True
        except WindowsError:
            pass
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-CimInstance -ClassName Win32_DeviceGuard -Namespace root\\securitycenter2 | Select-Object -ExpandProperty SecurityServicesConfigured"],
                capture_output=True, text=True, timeout=3,
                **_hidden_process_kwargs(),
            )
            if "1" in result.stdout:
                return True
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"Не удалось проверить Memory Integrity: {e}")
    return False


def _check_lhm_driver():
    """Проверяет, доступен ли драйвер LibreHardwareMonitor."""
    try:
        import clr
        clr.AddReference("LibreHardwareMonitorLib")
        from LibreHardwareMonitor.Hardware import Computer
        comp = Computer()
        comp.IsCpuEnabled = True
        comp.Open()
        has_hardware = len(list(comp.Hardware)) > 0
        comp.Close()
        return has_hardware
    except Exception as e:
        logger.debug(f"Драйвер LibreHardwareMonitor не доступен: {e}")
        return False


def _check_antivirus():
    """Проверяет, какой антивирус установлен."""
    try:
        result = subprocess.run(
            ["wmic", "/namespace:\\root\\securitycenter2", "path", "AntivirusProduct",
             "get", "displayName,productState", "/format:csv"],
            capture_output=True, text=True, timeout=3,
            **_hidden_process_kwargs(),
        )
        lines = result.stdout.strip().split('\n')
        antiviruses = []
        for line in lines[1:]:
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2 and parts[0]:
                antiviruses.append(parts[0].strip())
        return antiviruses if antiviruses else None
    except Exception as e:
        logger.debug(f"Не удалось проверить антивирус: {e}")
        return None


def _check_virtual_machine():
    """Проверяет, запущена ли программа в виртуальной машине."""
    try:
        import wmi
        c = wmi.WMI()
        for bios in c.Win32_BIOS():
            manufacturer = str(bios.Manufacturer or "").lower()
            if any(vm in manufacturer for vm in ["vmware", "virtualbox", "qemu", "xen", "hyper-v", "kvm", "parallels"]):
                return True, manufacturer
        for cs in c.Win32_ComputerSystem():
            manufacturer = str(cs.Manufacturer or "").lower()
            model = str(cs.Model or "").lower()
            if any(vm in manufacturer + model for vm in ["vmware", "virtualbox", "qemu", "xen", "hyper-v", "kvm", "parallels", "microsoft kvm"]):
                return True, manufacturer
        try:
            si = subprocess.run(
                ["systeminfo"],
                capture_output=True,
                text=True,
                timeout=5,
                **_hidden_process_kwargs(),
            )
            text = si.stdout.lower()
            if any(vm in text for vm in ["vmware", "virtualbox", "qemu", "xen", "hyper-v", "kvm", "parallels"]):
                return True, "detected via systeminfo"
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"Не удалось проверить виртуальную машину: {e}")
    return False, None


def _check_architecture():
    """Проверяет разрядность Python и системы."""
    return {
        "python": platform.architecture()[0],
        "system": platform.machine(),
        "python_bits": 64 if "64" in platform.architecture()[0] else 32,
        "system_bits": 64 if "64" in platform.machine() else 32,
        "mismatch": "64" not in platform.architecture()[0] or "64" not in platform.machine()
    }


def _check_hyperv():
    """Проверяет, включена ли виртуализация Hyper-V."""
    try:
        import wmi
        c = wmi.WMI(namespace="root\\cimv2\\embedded")
        for hv in c.Win32_Hypervisor():
            return True
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["systeminfo"],
            capture_output=True,
            text=True,
            timeout=5,
            **_hidden_process_kwargs(),
        )
        if "Hyper-V" in result.stdout and "Yes" in result.stdout:
            return True
    except Exception:
        pass
    return False


def _get_system_info():
    """Собирает всю системную информацию."""
    info = {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "platform_release": platform.release(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "hostname": platform.node(),
        "processor": platform.processor(),
    }
    if info["platform"] == "Windows":
        info["windows_version"] = platform.win32_ver()
        info["windows_release"] = platform.win32_release()
        info["windows_edition"] = platform.win32_edition()
        info["windows_service_pack"] = platform.win32_service_pack()
    return info


def is_admin():
    """Возвращает True, если программа запущена с правами администратора."""
    if "is_admin" not in _CHECK_CACHE:
        _CHECK_CACHE["is_admin"] = _check_admin()
    return _CHECK_CACHE["is_admin"]


def is_memory_integrity_enabled():
    """Возвращает True, если включена защита ядра (Memory Integrity)."""
    if "memory_integrity" not in _CHECK_CACHE:
        _CHECK_CACHE["memory_integrity"] = _check_memory_integrity()
    return _CHECK_CACHE["memory_integrity"]


def is_lhm_driver_available():
    """Возвращает True, если драйвер LibreHardwareMonitor доступен."""
    if "lhm_driver" not in _CHECK_CACHE:
        _CHECK_CACHE["lhm_driver"] = _check_lhm_driver()
    return _CHECK_CACHE["lhm_driver"]


def get_antivirus():
    """Возвращает список установленных антивирусов."""
    if "antivirus" not in _CHECK_CACHE:
        _CHECK_CACHE["antivirus"] = _check_antivirus()
    return _CHECK_CACHE["antivirus"]


def is_virtual_machine():
    """Возвращает (is_vm, vm_type), если программа запущена в виртуальной машине."""
    if "virtual_machine" not in _CHECK_CACHE:
        _CHECK_CACHE["virtual_machine"] = _check_virtual_machine()
    return _CHECK_CACHE["virtual_machine"]


def get_architecture_info():
    """Возвращает информацию о разрядности."""
    if "architecture" not in _CHECK_CACHE:
        _CHECK_CACHE["architecture"] = _check_architecture()
    return _CHECK_CACHE["architecture"]


def is_hyperv_enabled():
    """Возвращает True, если включена виртуализация Hyper-V."""
    if "hyperv" not in _CHECK_CACHE:
        _CHECK_CACHE["hyperv"] = _check_hyperv()
    return _CHECK_CACHE["hyperv"]


def get_system_info():
    """Возвращает полную информацию о системе."""
    if "system_info" not in _CHECK_CACHE:
        _CHECK_CACHE["system_info"] = _get_system_info()
    return _CHECK_CACHE["system_info"]


def log_system_warnings():
    """Логирует все системные предупреждения, которые могут влиять на работу датчиков."""
    warnings = []
    if not is_admin():
        warnings.append(
            "⚠️ Программа запущена БЕЗ прав администратора. "
            "Некоторые датчики могут быть недоступны. "
            "Запустите программу от имени администратора."
        )
    if is_memory_integrity_enabled():
        warnings.append(
            "⚠️ Включена защита ядра (Целостность памяти / Core Isolation). "
            "Это БЛОКИРУЕТ драйвер LibreHardwareMonitor. "
            "Решение: Безопасность Windows → Изоляция ядра → Отключить 'Целостность памяти'. "
            "Требуется перезагрузка."
        )
    pawnio = get_pawnio_status()
    if not pawnio.get("installed"):
        warnings.append(
            "⚠️ Драйвер PawnIO не установлен. На современных Intel/AMD и "
            "некоторых ноутбуках из-за этого недоступны температура, напряжение "
            "и мощность CPU. Установите PawnIO из дистрибутива SystemMonitor "
            "и перезапустите программу."
        )
    elif not pawnio.get("running"):
        warnings.append(
            "⚠️ Драйвер PawnIO установлен, но служба не запущена. "
            "Перезапустите SystemMonitor от имени администратора или Windows."
        )
    arch = get_architecture_info()
    if arch.get("mismatch", False):
        warnings.append(
            "⚠️ Разрядность Python ({}) не совпадает с разрядностью системы ({}). "
            "Установите 64-битную версию Python.".format(
                arch.get("python_bits", "?"), arch.get("system_bits", "?")
            )
        )
    is_vm, vm_type = is_virtual_machine()
    if is_vm:
        warnings.append(
            f"ℹ️ Обнаружен запуск в виртуальной машине ({vm_type}). "
            "Некоторые датчики могут быть недоступны."
        )
    if is_hyperv_enabled():
        warnings.append(
            "ℹ️ Обнаружена виртуализация Hyper-V. "
            "Некоторые датчики могут работать некорректно."
        )
    av = get_antivirus()
    if av:
        warnings.append(
            f"ℹ️ Установленные антивирусы: {', '.join(av)}. "
            "Они могут блокировать доступ к драйверам."
        )
    if warnings:
        logger.info("=" * 70)
        logger.info("СИСТЕМНЫЕ ПРЕДУПРЕЖДЕНИЯ:")
        logger.info("=" * 70)
        for warning in warnings:
            logger.info(warning)
        logger.info("=" * 70)
    return warnings


def get_all_diagnostics():
    """Возвращает полный отчёт о диагностике системы."""
    def safe(check, default=None):
        try:
            return check()
        except Exception as exc:
            logger.debug("Диагностика %s недоступна: %s", check.__name__, exc)
            return default

    return {
        "is_admin": safe(is_admin, False),
        "memory_integrity_enabled": safe(is_memory_integrity_enabled, False),
        "lhm_driver_available": safe(is_lhm_driver_available, False),
        "pawnio": safe(get_pawnio_status, {
            "available": False, "installed": False, "running": False,
        }),
        "antivirus": safe(get_antivirus),
        "is_virtual_machine": safe(is_virtual_machine, (False, None)),
        "hyperv_enabled": safe(is_hyperv_enabled, False),
        "architecture": safe(get_architecture_info, {}),
        "system_info": safe(get_system_info, {}),
        "warnings": safe(log_system_warnings, []),
    }
