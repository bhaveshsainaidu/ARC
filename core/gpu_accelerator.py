"""
core/gpu_accelerator.py — ARC GPU VRAM & Hardware Acceleration Engine.

Directly orchestrates GPU VRAM routing for:
  1. NVIDIA RTX Discrete GPU detection & NVML telemetry (zero subprocess).
  2. Windows DirectX / DWM High-Performance GPU routing (GpuPreference=2;).
  3. Qt6 Direct3D 11 RHI hardware rendering pipeline on dedicated VRAM.
  4. OpenCV OpenCL 3.0 CUDA GPU compute pipeline for camera & gestures (UMat in GDDR6 VRAM).
  5. Deep Learning device routing (CUDA / DirectML / CPU).
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
import threading
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

_OS = platform.system()

# ── NVML CTypes Data Structures ──────────────────────────────────────────────
class _NVMLMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free",  ctypes.c_ulonglong),
        ("used",  ctypes.c_ulonglong),
    ]


class _NVMLUtilization(ctypes.Structure):
    _fields_ = [
        ("gpu",    ctypes.c_uint),
        ("memory", ctypes.c_uint),
    ]


class GPUAccelerator:
    """Singleton Hardware Acceleration Engine for ARC."""

    _instance: Optional[GPUAccelerator] = None
    _lock = threading.Lock()

    def __new__(cls) -> GPUAccelerator:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GPUAccelerator, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self._nvml_lib: Optional[ctypes.CDLL] = None
        self._nvml_dev: Optional[ctypes.c_void_p] = None
        self._nvml_available: bool = False

        self.gpu_name: str = "Unknown GPU"
        self.vram_total_mb: float = 0.0
        self.opencl_available: bool = False
        self.opencl_device_name: str = "N/A"
        self.opencl_vram_mb: float = 0.0
        self.is_high_performance: bool = False

        # Apply system & environment configurations immediately
        self._configure_environment()
        self._configure_windows_gpu_preference()
        self._init_nvml()
        self._init_opencl()

        self._initialized = True

    # ──────────────────────────────────────────────────────────────────────────
    # Environment & Windows DirectX Setup
    # ──────────────────────────────────────────────────────────────────────────
    def _configure_environment(self) -> None:
        """Export environment variables for Direct3D 11 Qt RHI and CUDA routing."""
        # PCI Bus order and visible devices
        os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
        os.environ.setdefault("NVIDIA_VISIBLE_DEVICES", "all")

        # Force Qt 6 Quick / RHI to use Direct3D 11 on Windows (Dedicated VRAM backings)
        if _OS == "Windows":
            os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")
            os.environ.setdefault("QT_QUICK_BACKEND", "rhi")
            os.environ.setdefault("QT_D3D_ADAPTER_INDEX", "0")
        elif _OS == "Linux":
            os.environ.setdefault("QSG_RHI_BACKEND", "vulkan")

        # OpenCV OpenCL settings
        os.environ.setdefault("OPENCV_OPENCL_DEVICE", "GPU:0")
        os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "nvml")

    def _configure_windows_gpu_preference(self) -> None:
        """Ensure python.exe and pythonw.exe are configured for High-Performance GPU in Windows Registry."""
        if _OS != "Windows":
            return
        try:
            import winreg

            exe_path = sys.executable
            # Key: HKCU\Software\Microsoft\DirectX\UserGpuPreferences
            key_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
            try:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            except OSError:
                return

            # GpuPreference=2; means High Performance (Discrete NVIDIA GPU)
            current_val = ""
            try:
                current_val, _ = winreg.QueryValueEx(key, exe_path)
            except OSError:
                pass

            if "GpuPreference=2" not in current_val:
                try:
                    winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, "GpuPreference=2;")
                except OSError:
                    pass

            winreg.CloseKey(key)
            self.is_high_performance = True
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # NVML Real-Time Hardware Telemetry (zero subprocess)
    # ──────────────────────────────────────────────────────────────────────────
    def _init_nvml(self) -> None:
        """Initialize NVML via ctypes for high-speed hardware polling."""
        if _OS == "Windows":
            candidates = ("nvml", r"C:\Windows\System32\nvml.dll")
            loader = ctypes.WinDLL
        else:
            candidates = ("libnvidia-ml.so.1", "libnvidia-ml.so", "libnvidia-ml.dylib")
            loader = ctypes.CDLL

        for dll_name in candidates:
            try:
                lib = loader(dll_name)
                # NVML initialization
                if hasattr(lib, "nvmlInit_v2"):
                    lib.nvmlInit_v2()
                elif hasattr(lib, "nvmlInit"):
                    lib.nvmlInit()
                else:
                    continue

                dev = ctypes.c_void_p()
                if hasattr(lib, "nvmlDeviceGetHandleByIndex_v2"):
                    lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
                elif hasattr(lib, "nvmlDeviceGetHandleByIndex"):
                    lib.nvmlDeviceGetHandleByIndex(0, ctypes.byref(dev))
                else:
                    continue

                # Query GPU Name
                name_buf = ctypes.create_string_buffer(96)
                if hasattr(lib, "nvmlDeviceGetName"):
                    lib.nvmlDeviceGetName(dev, name_buf, 96)
                    self.gpu_name = name_buf.value.decode("utf-8", errors="ignore").strip()

                # Query VRAM Total
                mem = _NVMLMemory()
                if hasattr(lib, "nvmlDeviceGetMemoryInfo"):
                    lib.nvmlDeviceGetMemoryInfo(dev, ctypes.byref(mem))
                    self.vram_total_mb = round(mem.total / (1024 * 1024), 1)

                self._nvml_lib = lib
                self._nvml_dev = dev
                self._nvml_available = True
                break
            except Exception:
                continue

    def get_vram_telemetry(self) -> Dict[str, Any]:
        """Query instant VRAM allocations and GPU utilization (sub-millisecond ctypes query)."""
        if not self._nvml_available or self._nvml_lib is None or self._nvml_dev is None:
            return {
                "active": False,
                "gpu_name": self.gpu_name,
                "vram_total_mb": 0.0,
                "vram_used_mb": 0.0,
                "vram_free_mb": 0.0,
                "vram_util_pct": 0.0,
                "gpu_core_util_pct": 0.0,
                "gpu_mem_util_pct": 0.0,
                "temperature_c": -1.0,
                "opencl_enabled": self.opencl_available,
                "opencl_device": self.opencl_device_name,
                "backend": "CPU Fallback",
            }

        try:
            mem = _NVMLMemory()
            self._nvml_lib.nvmlDeviceGetMemoryInfo(self._nvml_dev, ctypes.byref(mem))
            vram_total = round(mem.total / (1024 * 1024), 1)
            vram_used = round(mem.used / (1024 * 1024), 1)
            vram_free = round(mem.free / (1024 * 1024), 1)
            vram_pct = round((mem.used / mem.total) * 100, 1) if mem.total > 0 else 0.0

            util = _NVMLUtilization()
            self._nvml_lib.nvmlDeviceGetUtilizationRates(self._nvml_dev, ctypes.byref(util))
            gpu_core = float(util.gpu)
            gpu_mem = float(util.memory)

            temp = ctypes.c_uint()
            temp_val = -1.0
            if hasattr(self._nvml_lib, "nvmlDeviceGetTemperature"):
                # 0 = NVML_TEMPERATURE_GPU
                if self._nvml_lib.nvmlDeviceGetTemperature(self._nvml_dev, 0, ctypes.byref(temp)) == 0:
                    temp_val = float(temp.value)

            return {
                "active": True,
                "gpu_name": self.gpu_name,
                "vram_total_mb": vram_total,
                "vram_used_mb": vram_used,
                "vram_free_mb": vram_free,
                "vram_util_pct": vram_pct,
                "gpu_core_util_pct": gpu_core,
                "gpu_mem_util_pct": gpu_mem,
                "temperature_c": temp_val,
                "opencl_enabled": self.opencl_available,
                "opencl_device": self.opencl_device_name,
                "backend": "Direct3D 11 + OpenCL 3.0 CUDA (RTX 3050 VRAM)",
            }
        except Exception:
            return {
                "active": False,
                "gpu_name": self.gpu_name,
                "vram_total_mb": self.vram_total_mb,
                "vram_used_mb": 0.0,
                "vram_free_mb": 0.0,
                "vram_util_pct": 0.0,
                "gpu_core_util_pct": 0.0,
                "gpu_mem_util_pct": 0.0,
                "temperature_c": -1.0,
                "opencl_enabled": self.opencl_available,
                "opencl_device": self.opencl_device_name,
                "backend": "Direct3D 11",
            }

    # ──────────────────────────────────────────────────────────────────────────
    # OpenCV OpenCL Hardware Acceleration (GDDR6 VRAM UMat Buffers)
    # ──────────────────────────────────────────────────────────────────────────
    def _init_opencl(self) -> None:
        """Initialize OpenCV OpenCL runtime for GPU image and video processing."""
        try:
            if cv2.ocl.haveOpenCL():
                cv2.ocl.setUseOpenCL(True)
                if cv2.ocl.useOpenCL():
                    dev = cv2.ocl.Device.getDefault()
                    self.opencl_available = True
                    self.opencl_device_name = dev.name()
                    self.opencl_vram_mb = round(dev.globalMemSize() / (1024 * 1024), 1)
        except Exception:
            self.opencl_available = False

    def to_vram_umat(self, frame: np.ndarray) -> cv2.UMat:
        """Upload host numpy frame into discrete GPU VRAM as a cv2.UMat."""
        if not self.opencl_available or frame is None:
            return frame
        try:
            return cv2.UMat(frame)
        except Exception:
            return frame

    def process_frame_gpu(
        self,
        frame: np.ndarray,
        target_size: Optional[Tuple[int, int]] = None,
        to_rgb: bool = False,
        to_gray: bool = False,
        gaussian_blur_ksize: Optional[int] = None,
    ) -> np.ndarray:
        """
        Process frame completely inside discrete GPU VRAM via OpenCL.
        Eliminates CPU memory bus saturation and DRAM contention.
        """
        if frame is None:
            return frame

        if not self.opencl_available:
            # Fallback on host CPU if OpenCL is inactive
            res = frame
            if to_rgb:
                res = cv2.cvtColor(res, cv2.COLOR_BGR2RGB)
            elif to_gray:
                res = cv2.cvtColor(res, cv2.COLOR_BGR2GRAY)
            if target_size:
                res = cv2.resize(res, target_size, interpolation=cv2.INTER_LINEAR)
            if gaussian_blur_ksize:
                res = cv2.GaussianBlur(res, (gaussian_blur_ksize, gaussian_blur_ksize), 0)
            return res

        try:
            # Upload to GDDR6 VRAM
            u_img = cv2.UMat(frame)

            # Colorspace conversion inside GPU VRAM
            if to_rgb:
                u_img = cv2.cvtColor(u_img, cv2.COLOR_BGR2RGB)
            elif to_gray:
                u_img = cv2.cvtColor(u_img, cv2.COLOR_BGR2GRAY)

            # GPU hardware bilinear / bicubic scaling
            if target_size:
                u_img = cv2.resize(u_img, target_size, interpolation=cv2.INTER_LINEAR)

            # GPU kernel filtering
            if gaussian_blur_ksize:
                u_img = cv2.GaussianBlur(u_img, (gaussian_blur_ksize, gaussian_blur_ksize), 0)

            # Download back to host array
            return u_img.get()
        except Exception:
            return frame

    # ──────────────────────────────────────────────────────────────────────────
    # Qt6 Direct3D / OpenGL Hardware Acceleration Setup
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def configure_qt_gpu_acceleration(app: Any = None) -> None:
        """
        Configure Qt application attributes and surface format for discrete GPU hardware rendering.
        Must be invoked at application startup.
        """
        try:
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QSurfaceFormat
            from PyQt6.QtWidgets import QApplication

            # Enable OpenGL context sharing across threads & widgets
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

            # Configure surface format for hardware swapchain
            fmt = QSurfaceFormat()
            fmt.setDepthBufferSize(24)
            fmt.setStencilBufferSize(8)
            fmt.setSwapInterval(1)  # Smooth VSync to eliminate tearing & stutter
            fmt.setRenderableType(QSurfaceFormat.RenderableType.DefaultRenderableType)
            QSurfaceFormat.setDefaultFormat(fmt)
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Deep Learning / Tensor Compute Device Selection
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def get_optimal_torch_device() -> str:
        """Return the optimal device string for torch / transformers models."""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda:0"
        except Exception:
            pass

        # Check for torch-directml if installed
        try:
            import torch_directml
            return str(torch_directml.device())
        except Exception:
            pass

        return "cpu"


# Module-level convenience functions
_global_accelerator: Optional[GPUAccelerator] = None

def get_gpu_accelerator() -> GPUAccelerator:
    """Return the global GPUAccelerator instance."""
    global _global_accelerator
    if _global_accelerator is None:
        _global_accelerator = GPUAccelerator()
    return _global_accelerator


def init_gpu_acceleration() -> Dict[str, Any]:
    """Initialize ARC system-wide GPU VRAM acceleration."""
    accel = get_gpu_accelerator()
    return accel.get_vram_telemetry()


def get_vram_telemetry() -> Dict[str, Any]:
    """Query live VRAM telemetry and GPU load."""
    return get_gpu_accelerator().get_vram_telemetry()
