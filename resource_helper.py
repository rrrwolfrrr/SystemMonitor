#!/usr/bin/env python3
"""
SystemMonitor — пути к ресурсам.
Возвращает абсолютный путь к ресурсам (templates, static, DLL).
Работает как в режиме разработки, так и в собранном .exe (PyInstaller).
"""

import os
import sys


def resource_path(relative_path):
    """
    Получить абсолютный путь к ресурсу.
    
    В режиме разработки: возвращает путь относительно текущей папки.
    В режиме .exe (PyInstaller): возвращает путь относительно временной папки _MEIPASS.
    
    Args:
        relative_path: Относительный путь к ресурсу (например, 'templates')
    
    Returns:
        Абсолютный путь к ресурсу
    """
    try:
        # PyInstaller создаёт временную папку _MEIPASS при запуске .exe
        base_path = sys._MEIPASS
    except Exception:
        # В режиме разработки используем текущую папку
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_project_dir():
    """
    Получить абсолютный путь к папке проекта.
    
    В режиме разработки: папка, где лежит этот файл.
    В режиме .exe: папка, где лежит .exe файл.
    
    Returns:
        Абсолютный путь к папке проекта
    """
    if getattr(sys, 'frozen', False):
        # Запущено как .exe
        return os.path.dirname(sys.executable)
    else:
        # Запущено как .py
        return os.path.dirname(os.path.abspath(__file__))


def get_dll_path(dll_name="LibreHardwareMonitorLib.dll"):
    """
    Получить абсолютный путь к DLL-файлу.
    
    Args:
        dll_name: Имя DLL-файла
    
    Returns:
        Абсолютный путь к DLL-файлу
    """
    return os.path.join(get_project_dir(), dll_name)