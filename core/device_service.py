"""
core/device_service.py — Hardware Device Discovery & Camera Routing for ARC.

Detects, enumerates, and manages all connected hardware peripherals:
  - Cameras & Webcams (Integrated vs External e.g. OsmoAction4, USB webcams)
  - Audio Input & Output Devices (Microphones, Speakers, Headsets)
  - USB Peripherals (Controllers, External media, Capture devices)
  - Displays & Monitors
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_SETTINGS_FILE = _get_base_dir() / "config" / "settings.json"


def _load_settings() -> dict:
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_setting(key: str, val: Any) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg = _load_settings()
    cfg[key] = val
    try:
        _SETTINGS_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def list_connected_cameras() -> List[Dict[str, Any]]:
    """
    Probes all available camera indices via OpenCV and correlates with
    operating system device names (e.g. OsmoAction4, Integrated Webcam).
    """
    cameras = []
    if not _CV2_AVAILABLE:
        return cameras

    # Query friendly camera names on Windows via PowerShell
    known_names = []
    if sys.platform == "win32":
        try:
            cmd = "powershell -NoProfile -Command \"Get-PnpDevice | ? { $_.Class -eq 'Camera' -or $_.FriendlyName -like '*Camera*' -or $_.FriendlyName -like '*Osmo*' -or $_.FriendlyName -like '*Webcam*' } | Select-Object -ExpandProperty FriendlyName\""
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=4)
            for line in res.stdout.splitlines():
                cl = line.strip()
                if cl and cl not in known_names:
                    known_names.append(cl)
        except Exception:
            pass

    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY

    active_idx = get_active_camera_index()

    for idx in range(3):
        cap = cv2.VideoCapture(idx, backend)
        if cap.isOpened():
            ret, frame = cap.read()
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
            cap.release()

            # Determine appropriate friendly name
            name = f"Camera {idx}"
            cam_type = "integrated" if idx == 0 else "external"

            if known_names:
                # If index 1 and OsmoAction exists
                for kn in known_names:
                    if "osmo" in kn.lower() and idx == 1:
                        name = kn
                        cam_type = "external"
                        break
                    elif "integrated" in kn.lower() and idx == 0:
                        name = kn
                        cam_type = "integrated"
                        break
                else:
                    if idx < len(known_names):
                        name = known_names[idx]
            else:
                if idx == 0:
                    name = "Integrated Webcam"
                elif idx == 1:
                    name = "External Camera (OsmoAction4 / USB)"

            cameras.append({
                "index": idx,
                "name": name,
                "type": cam_type,
                "resolution": f"{w}x{h}",
                "active": (idx == active_idx),
            })

    return cameras


def get_active_camera_index() -> int:
    """Returns the user-selected or auto-preferred camera index."""
    cfg = _load_settings()
    if "camera_index" in cfg:
        try:
            return int(cfg["camera_index"])
        except Exception:
            pass

    # Default logic: if an external camera (e.g. index 1) exists, prefer it!
    if _CV2_AVAILABLE:
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap1 = cv2.VideoCapture(1, backend)
        if cap1.isOpened():
            cap1.release()
            return 1

    return 0


def get_active_camera_name() -> str:
    """Returns the friendly name of the currently active camera."""
    active_idx = get_active_camera_index()
    if active_idx == 1:
        return "OsmoAction4 (External)"
    elif active_idx == 0:
        return "Integrated Webcam"
    return f"Camera {active_idx}"


def set_active_camera(target: Any) -> tuple[bool, str]:
    """Sets active camera by index or name (e.g. 'external', 'osmo', 1)."""
    cameras = list_connected_cameras()
    if not cameras:
        return False, "No connected cameras detected on this system."

    chosen_idx = None
    chosen_name = None

    if isinstance(target, int):
        for cam in cameras:
            if cam["index"] == target:
                chosen_idx = cam["index"]
                chosen_name = cam["name"]
                break
    else:
        target_str = str(target).lower().strip()
        if target_str.isdigit():
            idx_int = int(target_str)
            for cam in cameras:
                if cam["index"] == idx_int:
                    chosen_idx = cam["index"]
                    chosen_name = cam["name"]
                    break
        elif "ext" in target_str or "osmo" in target_str:
            for cam in cameras:
                if cam["type"] == "external" or "osmo" in cam["name"].lower():
                    chosen_idx = cam["index"]
                    chosen_name = cam["name"]
                    break
        elif "int" in target_str or "laptop" in target_str or "webcam" in target_str:
            for cam in cameras:
                if cam["type"] == "integrated":
                    chosen_idx = cam["index"]
                    chosen_name = cam["name"]
                    break
        else:
            for cam in cameras:
                if target_str in cam["name"].lower():
                    chosen_idx = cam["index"]
                    chosen_name = cam["name"]
                    break

    if chosen_idx is None:
        # Fallback to first camera
        chosen_idx = cameras[0]["index"]
        chosen_name = cameras[0]["name"]

    _save_setting("camera_index", chosen_idx)
    _save_setting("camera_name", chosen_name)

    # Also update memory config if present
    try:
        from memory.config_manager import set_key
        set_key("camera_index", chosen_idx)
    except Exception:
        pass

    return True, f"Active camera switched to Index {chosen_idx}: **{chosen_name}**"


def list_audio_endpoints() -> Dict[str, List[str]]:
    """Queries microphones and speakers."""
    endpoints = {"inputs": [], "outputs": []}
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for d in devices:
            name = d.get("name", "")
            if d.get("max_input_channels", 0) > 0 and name not in endpoints["inputs"]:
                endpoints["inputs"].append(name)
            if d.get("max_output_channels", 0) > 0 and name not in endpoints["outputs"]:
                endpoints["outputs"].append(name)
    except Exception:
        pass
    return endpoints


def list_usb_devices() -> List[str]:
    """Queries connected USB devices via PowerShell on Windows."""
    usb_devs = []
    if sys.platform == "win32":
        try:
            cmd = "powershell -NoProfile -Command \"Get-PnpDevice -Class USB -Status OK | Select-Object -ExpandProperty FriendlyName\""
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=4)
            for line in res.stdout.splitlines():
                cl = line.strip()
                if cl and cl not in usb_devs:
                    usb_devs.append(cl)
        except Exception:
            pass
    return usb_devs[:15]
