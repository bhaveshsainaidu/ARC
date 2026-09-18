"""
actions/device_manager.py — ARC Hardware Peripheral & Camera Controller.

Enables ARC to discover, list, and switch between connected hardware peripherals:
  - External webcams (e.g. OsmoAction4) vs Integrated laptop webcams
  - Microphone and Speaker audio endpoints
  - Connected USB hardware devices
  - Active display monitors
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from core.device_service import (
    get_active_camera_index,
    list_audio_endpoints,
    list_connected_cameras,
    list_usb_devices,
    set_active_camera,
)


def device_manager(parameters: dict, player=None, **_context) -> str:
    """List connected hardware devices or switch active camera / audio endpoints."""
    action = parameters.get("action", "list_cameras").lower().strip()
    target_camera = parameters.get("camera", parameters.get("target", "")).strip()

    # ── Action: Switch Active Camera ─────────────────────────────────────────
    if action in ("switch_camera", "set_camera", "select_camera", "use_camera"):
        if not target_camera:
            return "Sir, please specify which camera to use (e.g. 'OsmoAction4', 'external', or camera index '1')."

        ok, msg = set_active_camera(target_camera)
        if ok:
            return f"✅ {msg}\nAll vision and screen perception subsystems will now capture from this camera."
        return f"⚠️ {msg}"

    # ── Action: List Cameras ─────────────────────────────────────────────────
    elif action in ("list_cameras", "cameras", "webcams"):
        cameras = list_connected_cameras()
        if not cameras:
            return "No functional video capture devices were detected."

        active_idx = get_active_camera_index()
        lines = []
        for c in cameras:
            active_badge = " [ACTIVE ✅]" if c["index"] == active_idx else ""
            lines.append(
                f"• **Index {c['index']}**: {c['name']} ({c['resolution']} - {c['type'].capitalize()}){active_badge}"
            )

        return (
            f"📷 Connected Video Cameras ({len(cameras)} found):\n\n"
            + "\n".join(lines)
            + "\n\nTo switch cameras, say 'switch camera to OsmoAction4' or 'use camera 1'."
        )

    # ── Action: List All Hardware Devices ────────────────────────────────────
    elif action in ("list", "list_devices", "all", "peripherals"):
        cameras = list_connected_cameras()
        audio = list_audio_endpoints()
        usbs = list_usb_devices()

        cam_lines = [f"  • [{c['index']}] {c['name']} ({c['type']})" for c in cameras] or ["  • None detected"]
        mic_lines = [f"  • {m}" for m in audio.get("inputs", [])[:4]] or ["  • System default mic"]
        spk_lines = [f"  • {s}" for s in audio.get("outputs", [])[:4]] or ["  • System default speaker"]
        usb_lines = [f"  • {u}" for u in usbs[:6]] or ["  • Standard USB root hub"]

        return (
            "🔌 ARC Connected Hardware Peripherals Inventory:\n\n"
            "📷 Cameras & Video Capture:\n" + "\n".join(cam_lines) + "\n\n"
            "🎤 Audio Input (Microphones):\n" + "\n".join(mic_lines) + "\n\n"
            "🔊 Audio Output (Speakers / Headsets):\n" + "\n".join(spk_lines) + "\n\n"
            "💻 USB Peripherals:\n" + "\n".join(usb_lines) + "\n\n"
            "You can switch video capture by saying: 'switch camera to external'."
        )

    return (
        f"Unknown device action '{action}'. Supported actions: list_cameras, switch_camera, list_devices."
    )


TOOL = {
    "name": "device_manager",
    "description": (
        "ARC Hardware Peripheral & Camera Controller. Lists all connected webcams (Integrated vs "
        "External such as OsmoAction4), microphones, speakers, and USB devices. Allows dynamically "
        "switching the active camera used for vision, gestures, and object detection."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'list_cameras', 'switch_camera', 'list_devices'",
            },
            "camera": {
                "type": "STRING",
                "description": "Target camera to select by name ('OsmoAction4', 'external', 'integrated') or index ('0', '1')",
            },
        },
        "required": ["action"],
    },
    "handler": device_manager,
}
