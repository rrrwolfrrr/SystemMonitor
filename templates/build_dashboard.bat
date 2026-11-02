@echo off
echo Сборка dashboard.html из частей...
copy /b dashboard_head.html + dashboard_tail.html dashboard.html
echo Готово! dashboard.html создан.
pause