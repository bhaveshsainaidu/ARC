@echo off
setlocal enabledelayedexpansion
title ARC

cd /d "%~dp0"

:: Set GPU affinity to Dedicated NVIDIA VRAM
set CUDA_VISIBLE_DEVICES=0
set CUDA_DEVICE_ORDER=PCI_BUS_ID
set SHIM_MCCOMPAT=0x800000001

:: Check for virtual environment python first, then system python
if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

:: Run ARC
"%PY_EXE%" main.py %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ARC] Process exited with error code %ERRORLEVEL%.
    pause
)
