@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher "py" was not found.
    echo Install Python 3.11 or 3.12 with the Python Launcher enabled.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating local Python environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

echo Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Installation completed.
echo Run start_windows.bat to launch the application.
pause
exit /b 0

:error
echo.
echo Installation failed.
pause
exit /b 1
