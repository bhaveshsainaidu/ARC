@echo off
setlocal enabledelayedexpansion
title JARVIS — Configure NVIDIA VRAM

cd /d "%~dp0\.."

echo Configuring Python and Servers to run on Dedicated NVIDIA VRAM...
python scripts\set_nvidia_gpu.py

echo.
pause
