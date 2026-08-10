@echo off
setlocal
cd /d "%~dp0"

echo Starting MerchOps Agent for LAN access...
echo.
if exist "..\.venv311\Scripts\python.exe" (
    "..\.venv311\Scripts\python.exe" run_lan.py
) else (
    py -3.11 run_lan.py
)

pause
