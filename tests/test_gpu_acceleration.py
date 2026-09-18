"""
tests/test_gpu_acceleration.py — Test Suite for GPU VRAM & Hardware Acceleration.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.gpu_accelerator import (
    GPUAccelerator,
    get_gpu_accelerator,
    get_vram_telemetry,
    init_gpu_acceleration,
)


def test_gpu_accelerator_singleton():
    """Verify GPUAccelerator is a singleton and initializes without error."""
    accel1 = get_gpu_accelerator()
    accel2 = get_gpu_accelerator()
    assert accel1 is accel2
    assert isinstance(accel1, GPUAccelerator)


def test_init_gpu_acceleration():
    """Verify init_gpu_acceleration returns valid telemetry."""
    status = init_gpu_acceleration()
    assert isinstance(status, dict)
    assert "active" in status
    assert "gpu_name" in status
    assert "vram_total_mb" in status
    assert "vram_used_mb" in status
    assert "vram_free_mb" in status
    assert "vram_util_pct" in status
    assert "opencl_enabled" in status
    assert "backend" in status


def test_vram_telemetry_fields():
    """Ensure all required telemetry metrics have appropriate types."""
    tel = get_vram_telemetry()
    assert isinstance(tel["active"], bool)
    assert isinstance(tel["gpu_name"], str)
    assert isinstance(tel["vram_total_mb"], (int, float))
    assert isinstance(tel["vram_used_mb"], (int, float))
    assert isinstance(tel["vram_free_mb"], (int, float))
    assert isinstance(tel["vram_util_pct"], (int, float))
    assert isinstance(tel["gpu_core_util_pct"], (int, float))
    assert isinstance(tel["temperature_c"], (int, float))
    assert 0.0 <= tel["vram_util_pct"] <= 100.0


def test_gpu_process_frame():
    """Test GPU VRAM accelerated frame processing with color conversions and scaling."""
    accel = get_gpu_accelerator()
    # Create test 720p frame
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[100:200, 100:200] = [255, 0, 0]  # Blue patch

    # Process to RGB: Blue channel (index 0 in BGR) becomes index 2 in RGB
    rgb = accel.process_frame_gpu(frame, to_rgb=True)
    assert rgb.shape == (720, 1280, 3)
    assert rgb[150, 150, 2] == 255  # Blue channel moved to index 2 in RGB

    # Process to Grayscale & Resized
    gray_scaled = accel.process_frame_gpu(frame, target_size=(640, 360), to_gray=True)
    assert gray_scaled.shape == (360, 640)

    # Gaussian blur inside VRAM
    blurred = accel.process_frame_gpu(frame, gaussian_blur_ksize=15)
    assert blurred.shape == frame.shape


def test_configure_qt_gpu_acceleration():
    """Ensure configure_qt_gpu_acceleration executes safely."""
    # Should run without throwing any exceptions
    GPUAccelerator.configure_qt_gpu_acceleration()


def test_get_optimal_torch_device():
    """Verify compute device string is valid."""
    device = GPUAccelerator.get_optimal_torch_device()
    assert isinstance(device, str)
    assert device.startswith("cuda") or device.startswith("directml") or device == "cpu"
