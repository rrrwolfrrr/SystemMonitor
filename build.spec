# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 1. Данные (шаблоны, конфиги, иконки)
datas = [
    ('templates', 'templates'),
    ('icon.ico', '.'),
    ('env.env', '.'),
    ('hardware_test_matrix.json', '.'),
    ('PRESENTMON_LICENSE.txt', '.'),
]

if os.path.exists('static'):
    datas.append(('static', 'static'))

binaries = [
    ('LibreHardwareMonitorLib.dll', '.'),
    ('PresentMon-2.6.0-x64.exe', '.'),
    ('PawnIO_setup.exe', '.'),
    ('Aga.Controls.dll', '.'),
    ('BlackSharp.Core.dll', '.'),
    ('DiskInfoToolkit.dll', '.'),
    ('HidSharp.dll', '.'),
    ('Microsoft.Bcl.AsyncInterfaces.dll', '.'),
    ('Microsoft.Bcl.HashCode.dll', '.'),
    ('Microsoft.Win32.TaskScheduler.dll', '.'),
    ('OxyPlot.dll', '.'),
    ('OxyPlot.WindowsForms.dll', '.'),
    ('RAMSPDToolkit-NDD.dll', '.'),
    ('System.Buffers.dll', '.'),
    ('System.CodeDom.dll', '.'),
    ('System.Collections.Immutable.dll', '.'),
    ('System.Formats.Nrbf.dll', '.'),
    ('System.IO.Pipelines.dll', '.'),
    ('System.Memory.dll', '.'),
    ('System.Numerics.Vectors.dll', '.'),
    ('System.Reflection.Metadata.dll', '.'),
    ('System.Resources.Extensions.dll', '.'),
    ('System.Runtime.CompilerServices.Unsafe.dll', '.'),
    ('System.Security.AccessControl.dll', '.'),
    ('System.Security.Principal.Windows.dll', '.'),
    ('System.Text.Encodings.Web.dll', '.'),
    ('System.Text.Json.dll', '.'),
    ('System.Threading.AccessControl.dll', '.'),
    ('System.Threading.Tasks.Extensions.dll', '.'),
]
if os.path.exists('LhmVisitorAdapter.dll'):
    binaries.append(('LhmVisitorAdapter.dll', '.'))

# 2. Скрытые импорты (КРИТИЧНО добавлены pythonnet, clr, flask_cors, websockets)
hiddenimports = [
    'wmi', 'win32com.client', 'win32service', 'win32serviceutil', 'win32pdh',
    'pywintypes', 'pythoncom', 'winreg', 'pystray', 'pystray._win32',
    'webview', 'webview.platforms.winforms', 'webview.platforms.edgechromium',
    # --- КРИТИЧНО ДЛЯ DLL-РЕЖИМА ---
    'pythonnet', 'clr', 'pythonnet.runtime', 'System',
    # --- СЕТЕВЫЕ И ВЕБ ---
    'flask', 'flask_cors', 'websockets', 'dotenv',
    # --- ВНУТРЕННИЕ МОДУЛИ ---
    'server_core', 'config', 'libre_monitor', 'cache', 'utils', 'routes', 'resource_helper', 'storage',
    'fallback', 'system_detect', 'validator', 'logging_setup',
    'providers', 'sensor_resolver', 'diagnostic_snapshot', 'pawnio', 'fps_monitor',
    'update_visitor', 'schema', 'verify_build',
    'pawnio',
]

# Include QR generation and its SVG image factory in frozen builds.
qrcode_datas, qrcode_binaries, qrcode_hiddenimports = collect_all('qrcode')
hiddenimports += qrcode_hiddenimports
datas += qrcode_datas
binaries += qrcode_binaries

# 3. Автоматический сбор зависимостей библиотек
psutil_datas, psutil_binaries, psutil_hiddenimports = collect_all('psutil')
hiddenimports += psutil_hiddenimports
datas += psutil_datas

pil_datas, pil_binaries, pil_hiddenimports = collect_all('PIL')
hiddenimports += pil_hiddenimports
datas += pil_datas

# Include pywebview and its platform modules for the embedded WebView2 window.
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')
hiddenimports += webview_hiddenimports
datas += webview_datas
binaries += webview_binaries

# ВАЖНО: Собираем сам pythonnet, чтобы все его внутренние DLL попали в сборку
py_net_datas, py_net_binaries, py_net_hiddenimports = collect_all('pythonnet')
datas += py_net_datas
hiddenimports += py_net_hiddenimports

# 4. Анализ
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 5. Создание EXE (ВАЖНО: exclude_binaries=True для режима папки!)
exe = EXE(
    pyz,
    a.scripts,
    [],  # Пусто! Бинарники уйдут в COLLECT
    exclude_binaries=True,  # <- ГЛАВНОЕ ИЗМЕНЕНИЕ ДЛЯ ONE-DIR
    name='SystemMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # GUI-subsystem: запуск EXE не открывает консольное окно.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon='icon.ico',
)

# 6. Сборка всего в папку dist\SystemMonitor\
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SystemMonitor',  # Имя папки будет dist\SystemMonitor
)