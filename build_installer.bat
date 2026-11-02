@echo off
setlocal EnableExtensions

cd /d "%~dp0"
if errorlevel 1 goto :directory_error

if not exist "installer.iss" goto :script_missing
if not exist "dist\SystemMonitor\SystemMonitor.exe" goto :distribution_missing

set "ISCC="
where ISCC.exe >nul 2>&1
if not errorlevel 1 set "ISCC=ISCC.exe"

if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC goto :compiler_missing

echo === Building SystemMonitor installer ===
echo Project: %CD%
echo Inno Setup Compiler: %ISCC%
echo.

"%ISCC%" "installer.iss"
if errorlevel 1 goto :compile_error

if not exist "installer_output\SystemMonitor_Setup_*.exe" goto :output_missing

echo.
echo === INSTALLER BUILD COMPLETE ===
echo Output folder: "%CD%\installer_output"
goto :finish

:directory_error
echo ERROR: Cannot change to the directory containing this script.
goto :failure

:script_missing
echo ERROR: installer.iss was not found beside this script.
goto :failure

:distribution_missing
echo ERROR: The PyInstaller distribution was not found.
echo Build it first by running build.bat.
goto :failure

:compiler_missing
echo ERROR: Inno Setup Compiler was not found.
echo Install Inno Setup 6 or 7, or add ISCC.exe to PATH.
goto :failure

:compile_error
echo ERROR: Inno Setup failed to compile installer.iss.
goto :failure

:output_missing
echo ERROR: Compiler returned success but no installer EXE was found.
goto :failure

:failure
echo.
pause
exit /b 1

:finish
echo.
pause
exit /b 0
