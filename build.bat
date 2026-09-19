@echo off
setlocal enabledelayedexpansion
title ARC - Release Executable Builder

cd /d "%~dp0"

echo ======================================================================
echo   ARC (Adaptive Real-Time Cognitive Agent) - Executable Builder
echo ======================================================================
echo.

:: Detect Python
if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

:: Check PyInstaller
"%PY_EXE%" -m PyInstaller --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] PyInstaller not found. Installing PyInstaller...
    "%PY_EXE%" -m pip install pyinstaller
)

:: Run the release packaging script
"%PY_EXE%" scripts/build_release.py

if %ERRORLEVEL% equ 0 (
    echo.
    echo [✓] Build completed successfully!
    echo [✓] Standalone package ready at: dist\ARC-Windows-x64.zip
) else (
    echo.
    echo [X] Build failed with error code %ERRORLEVEL%.
)

echo.
pause
