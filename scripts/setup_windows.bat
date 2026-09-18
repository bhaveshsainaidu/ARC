@echo off
setlocal enabledelayedexpansion
title JARVIS — Windows Setup

cd /d "%~dp0\.."

echo ===============================================================
echo   JARVIS — Automated Windows Setup & Installation
echo ===============================================================
echo Project Directory: %CD%
echo.

:: 1. Check Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [X] Python was not found in your system PATH.
    echo Please install Python 3.12 from https://www.python.org/downloads/
    echo IMPORTANT: Make sure to check 'Add python.exe to PATH' during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set "PY_VER=%%i"
echo [✔] Detected Python: !PY_VER!

:: 2. Create Virtual Environment if not present
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment in .venv...
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [X] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [✔] Virtual environment created.
) else (
    echo [✔] Virtual environment .venv already exists.
)

:: 3. Activate Virtual Environment
call ".venv\Scripts\activate.bat"

:: 4. Upgrade Pip
echo [*] Upgrading pip...
python -m pip install --upgrade pip --quiet

:: 5. Install Dependencies
echo [*] Installing requirements from requirements.txt...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [X] Error occurred while installing dependencies.
    pause
    exit /b 1
)
echo [✔] All Python dependencies installed successfully.

:: 6. Install Playwright Chromium Browser
echo [*] Installing Playwright Chromium browser...
python -m playwright install chromium
if %ERRORLEVEL% neq 0 (
    echo [!] Playwright browser install warning. Web automation will attempt fallback.
) else (
    echo [✔] Playwright Chromium installed.
)

:: 7. Configure Dedicated NVIDIA VRAM
echo.
echo [*] Configuring Dedicated NVIDIA VRAM Acceleration...
python scripts\set_nvidia_gpu.py

:: 8. Run System Self-Check
echo.
echo [*] Running JARVIS System Self-Check...
echo ---------------------------------------------------------------
python main.py --health-check
echo ---------------------------------------------------------------

:: 9. Create Shortcuts
echo.
set /p CREATE_SHORTCUTS="Create Desktop and Start Menu shortcuts? [Y/n]: "
if /i not "!CREATE_SHORTCUTS!"=="n" (
    python scripts\create_shortcut.py
)

echo.
echo ===============================================================
echo   JARVIS Setup Complete!
echo   To start the assistant anytime:
echo     - Double-click the Desktop shortcut 'JARVIS'
echo     - Or run: run.bat
echo ===============================================================
echo.
pause
