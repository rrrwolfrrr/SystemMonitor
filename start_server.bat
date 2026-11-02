@echo off
chcp 65001 >nul
title SystemMonitor - Управление сервером
cd /d "D:\Проекты\LibreHardwareMonitor2\SystemMonitor"

:menu
cls
echo ========================================
echo    SystemMonitor - Управление сервером
echo ========================================
echo.
echo  [1] Запустить сервер (с треем)
echo  [2] Запустить сервер (без трея)
echo  [3] Перезапустить сервер
echo  [4] Остановить сервер
echo  [5] Открыть дашборд в браузере
echo  [6] Открыть логи в браузере
echo  [7] Выйти
echo.
echo ========================================
set /p choice="Выберите действие (1-7): "

if "%choice%"=="1" goto start_tray
if "%choice%"=="2" goto start_notray
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto stop
if "%choice%"=="5" goto open_dashboard
if "%choice%"=="6" goto open_logs
if "%choice%"=="7" goto exit
echo Неверный выбор. Попробуйте снова.
timeout /t 2 >nul
goto menu

:start_tray
echo.
echo Запуск сервера с системным треем...
start "SystemMonitor" python main.py
echo Сервер запущен. Откройте http://localhost:5000/dashboard
echo Иконка трея появится в системном трее.
echo.
pause
goto menu

:start_notray
echo.
echo Запуск сервера без трея...
start "SystemMonitor Server" python server_core.py
echo Сервер запущен. Откройте http://localhost:5000/dashboard
echo.
pause
goto menu

:restart
echo.
echo Остановка сервера...
taskkill /f /im python.exe >nul 2>&1
timeout /t 2 >nul
echo Запуск сервера с системным треем...
start "SystemMonitor" python main.py
echo Сервер перезапущен.
echo.
pause
goto menu

:stop
echo.
echo Остановка сервера...
taskkill /f /im python.exe >nul 2>&1
echo Сервер остановлен.
echo.
pause
goto menu

:open_dashboard
echo.
echo Открываю дашборд...
start http://localhost:5000/dashboard
timeout /t 2 >nul
goto menu

:open_logs
echo.
echo Открываю логи...
start http://localhost:5000/logs
timeout /t 2 >nul
goto menu

:exit
echo.
echo Выход...
exit