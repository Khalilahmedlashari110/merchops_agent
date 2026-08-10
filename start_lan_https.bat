@echo off
setlocal
cd /d "%~dp0"

set LAN_HTTPS=1
if "%LAN_PORT%"=="" set LAN_PORT=5443

echo Starting MerchOps Agent HTTPS LAN server for camera login...
echo.
echo Open the HTTPS LAN URL printed below on the other device.
echo If the browser shows a certificate warning, choose Advanced/Continue.
echo.

if exist "..\.venv311\Scripts\python.exe" (
    "..\.venv311\Scripts\python.exe" run_lan.py
) else (
    py -3.11 run_lan.py
)

pause
