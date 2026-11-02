@echo off
setlocal EnableExtensions

rem Keep this script ASCII-only for reliable execution in cmd.exe.
cd /d "%~dp0"
if errorlevel 1 (
    echo ERROR: Cannot change to the project directory.
    pause
    exit /b 1
)

echo === Building SystemMonitor ===
echo.

echo [1/4] Checking Python and PyInstaller...
set "PYTHON_CMD="
set "PYTHON_ARGS="
if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"
if not defined PYTHON_CMD if exist "venv\Scripts\python.exe" set "PYTHON_CMD=venv\Scripts\python.exe"
if not defined PYTHON_CMD (
    where py.exe >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py.exe"
        set "PYTHON_ARGS=-3"
    )
)
if not defined PYTHON_CMD (
    where python.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python.exe"
)
if not defined PYTHON_CMD (
    echo ERROR: Python was not found.
    echo Install Python 3.10 or newer and try again.
    pause
    exit /b 1
)

echo Project source: %CD%
echo Selected Python: %PYTHON_CMD% %PYTHON_ARGS%
%PYTHON_CMD% %PYTHON_ARGS% -c "import struct,sys; print('Python executable:', sys.executable); print('Python version:', sys.version.split()[0]); print('Architecture:', struct.calcsize('P')*8, 'bit'); sys.exit(0 if sys.version_info >= (3,10) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo ERROR: SystemMonitor requires 64-bit Python 3.10 or newer.
    pause
    exit /b 1
)

%PYTHON_CMD% %PYTHON_ARGS% -m PyInstaller --version
if errorlevel 1 (
    echo ERROR: PyInstaller was not found for the selected Python.
    echo Install it with:
    echo %PYTHON_CMD% %PYTHON_ARGS% -m pip install -r requirements.txt pyinstaller pywebview
    pause
    exit /b 1
)

echo [2/4] Removing previous build...
if exist "dist\SystemMonitor" rmdir /s /q "dist\SystemMonitor"
if exist "dist\SystemMonitor" (
    echo ERROR: Close SystemMonitor.exe and try again.
    echo The previous distribution folder is locked by a running process.
    pause
    exit /b 1
)
if exist "build" rmdir /s /q "build"
if exist "build" (
    echo ERROR: The build folder is locked. Close related tools and try again.
    pause
    exit /b 1
)

echo [3/4] Building EXE...
if exist "LhmVisitorAdapter.cs" (
    echo Building native LibreHardwareMonitor visitor adapter...
    if exist "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" (
        "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:library /optimize+ /out:"LhmVisitorAdapter.dll" /reference:"LibreHardwareMonitorLib.dll" "LhmVisitorAdapter.cs"
        if errorlevel 1 (
            echo ERROR: Failed to build LhmVisitorAdapter.dll.
            pause
            exit /b 1
        )
    ) else (
        echo ERROR: C# compiler was not found.
        pause
        exit /b 1
    )
)
%PYTHON_CMD% %PYTHON_ARGS% -m PyInstaller "build.spec" --clean --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: Build failed.
    pause
    exit /b 1
)

echo.
echo [4/4] Checking result...
if not exist "dist\SystemMonitor\SystemMonitor.exe" (
    echo ERROR: SystemMonitor.exe was not created.
    pause
    exit /b 1
)

%PYTHON_CMD% %PYTHON_ARGS% verify_build.py "dist\SystemMonitor" --source-root "%CD%"
if errorlevel 1 (
    echo ERROR: Distribution completeness check failed.
    pause
    exit /b 1
)

echo EXE created:
echo %CD%\dist\SystemMonitor\SystemMonitor.exe
echo.
echo This updates only the dist folder. It does not update an installed copy
echo or rebuild the Setup installer. Run the EXE above or build Setup separately
echo with Inno Setup after confirming the distribution is correct.
echo.
echo === BUILD COMPLETE ===
echo Output folder:
echo %CD%\dist\SystemMonitor\
echo.
pause
exit /b 0
