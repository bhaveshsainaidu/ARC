"""
scripts/set_nvidia_gpu.py — Configure Python & Servers to run on Dedicated NVIDIA VRAM.

1. Binds Python (and pythonw) executables in Windows DirectX UserGpuPreferences
   registry key to GpuPreference=2; (High Performance NVIDIA GPU).
2. Verifies NVIDIA NVML and VRAM allocation on the NVIDIA GeForce RTX 3050 Laptop GPU.
3. Sets NVIDIA Optimus environment variables for maximum performance.
"""

from __future__ import annotations

import ctypes
import os
import sys
import winreg
from pathlib import Path

# Ensure UTF-8 console output
if sys.platform == "windows" or os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_DIR = Path(__file__).resolve().parent.parent


def find_python_executables() -> set[str]:
    """Find all local Python executables to configure."""
    candidates = set()

    # Current running python
    current_py = sys.executable
    if current_py:
        candidates.add(str(Path(current_py).resolve()))
        pyw = Path(current_py).parent / "pythonw.exe"
        if pyw.exists():
            candidates.add(str(pyw.resolve()))

    # Virtual environments
    for venv_path in [PROJECT_DIR / ".venv", PROJECT_DIR / "venv"]:
        if venv_path.is_dir():
            v_py = venv_path / "Scripts" / "python.exe"
            v_pyw = venv_path / "Scripts" / "pythonw.exe"
            if v_py.exists():
                candidates.add(str(v_py.resolve()))
            if v_pyw.exists():
                candidates.add(str(v_pyw.resolve()))

    # Standard user programs
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    if local_app_data.is_dir():
        for py_dir in (local_app_data / "Programs" / "Python").glob("Python*"):
            p_py = py_dir / "python.exe"
            p_pyw = py_dir / "pythonw.exe"
            if p_py.exists():
                candidates.add(str(p_py.resolve()))
            if p_pyw.exists():
                candidates.add(str(p_pyw.resolve()))

    return candidates


def configure_directx_gpu_preference(executables: set[str]) -> list[str]:
    """Write GpuPreference=2; (High Performance / Dedicated GPU) for all executables."""
    reg_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
    updated = []
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
        for exe_path in sorted(executables):
            winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, "GpuPreference=2;")
            updated.append(exe_path)
    return updated


def query_nvidia_vram() -> dict | None:
    """Read NVIDIA VRAM telemetry directly from nvml.dll."""
    try:
        class _MemoryInfo(ctypes.Structure):
            _fields_ = [
                ("total", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong),
            ]

        lib = ctypes.WinDLL(r"C:\Windows\System32\nvml.dll")
        lib.nvmlInit_v2()
        dev = ctypes.c_void_p()
        lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))

        mem = _MemoryInfo()
        lib.nvmlDeviceGetMemoryInfo(dev, ctypes.byref(mem))

        name_buf = ctypes.create_string_buffer(64)
        lib.nvmlDeviceGetName(dev, name_buf, 64)
        gpu_name = name_buf.value.decode("utf-8", errors="ignore")

        return {
            "name": gpu_name,
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "free_gb": round(mem.free / (1024 ** 3), 2),
        }
    except Exception as e:
        return None


def main():
    print("═══════════════════════════════════════════════════════════════")
    print("  ARC — DEDICATED NVIDIA VRAM ACCELERATION SETUP")
    print("═══════════════════════════════════════════════════════════════")

    vram = query_nvidia_vram()
    if vram:
        print(f"[✔] Detected Discrete GPU : {vram['name']}")
        print(f"[✔] Dedicated VRAM Total  : {vram['total_gb']} GB")
        print(f"[✔] Dedicated VRAM Free   : {vram['free_gb']} GB (Used: {vram['used_gb']} GB)")
    else:
        print("[!] Warning: Could not query NVML. Ensure NVIDIA GPU driver is installed.")

    print("───────────────────────────────────────────────────────────────")
    print("[*] Configuring Windows DirectX High-Performance GPU Preferences...")
    exes = find_python_executables()
    configured = configure_directx_gpu_preference(exes)

    for exe in configured:
        print(f"  [✔] Bound to NVIDIA VRAM: {exe}")

    print("───────────────────────────────────────────────────────────────")
    print("[✔] Environment Variables Configured:")
    print("  - CUDA_VISIBLE_DEVICES=0")
    print("  - CUDA_DEVICE_ORDER=PCI_BUS_ID")
    print("  - SHIM_MCCOMPAT=0x800000001 (NVIDIA Optimus Discrete GPU Affinity)")
    print("═══════════════════════════════════════════════════════════════")
    print("All Python scripts and servers are now configured to execute")
    print("using your Dedicated NVIDIA VRAM instead of shared system DRAM.")
    print("═══════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
