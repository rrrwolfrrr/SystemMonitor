@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_CMD="
where py.exe >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py.exe -3"
if not defined PYTHON_CMD (
    where python.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python.exe"
)
if not defined PYTHON_CMD (
    echo ERROR: Python was not found.
    pause
    exit /b 1
)

echo === SystemMonitor automated tests ===
%PYTHON_CMD% run_autotests.py %*
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
    echo === TESTS PASSED ===
) else (
    echo === TESTS FAILED ===
)
pause
exit /b %RESULT%
