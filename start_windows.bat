@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The virtual environment is missing. Run setup_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" elm327_portable.py
if errorlevel 1 pause
