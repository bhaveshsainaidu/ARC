"""
actions/remote_control.py — ARC Phone Remote Dashboard & Mobile Integration.
Allows ARC to be fully aware of its mobile control features, trigger the on-screen
pairing QR code modal, query connection status, and explain mobile capabilities.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from dashboard.server import get_dashboard_server, PORT


def _get_local_ip() -> str:
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def remote_control(parameters: dict, player=None, **_context) -> str:
    """Manage and query the Phone Remote Dashboard and mobile connection."""
    raw_action = str(parameters.get("action", "info")).strip().lower()
    srv = get_dashboard_server()

    # 1. Trigger QR code modal on screen
    if any(k in raw_action for k in ("show", "qr", "open", "connect", "pair")):
        if player and hasattr(player, "open_remote"):
            try:
                player.open_remote()
            except Exception as e:
                print(f"[RemoteControl] Could not open remote overlay: {e}")

        key = ""
        url = f"http://{_get_local_ip()}:{PORT}"
        if srv:
            try:
                key = srv.new_key()
                url = srv.get_url()
            except Exception:
                pass

        return (
            f"Sir, I have displayed the Remote Control QR code on your HUD screen. "
            f"You can scan it with your phone's camera to connect immediately. "
            f"Alternatively, you can open {url} in your mobile browser and enter the PIN: {key or 'displayed on screen'}."
        )

    # 2. Check connection status
    if any(k in raw_action for k in ("status", "connected", "check")):
        if not srv:
            return "Sir, the Remote Dashboard server is currently offline or not initialized."
        client_count = len(srv._clients)
        if client_count > 0:
            return f"Sir, the Remote Dashboard is active. There is currently {client_count} mobile device connected."
        else:
            return (
                f"Sir, the Remote Dashboard server is running on {srv.get_url()}, "
                "but no phone is currently connected. You can ask me to 'show remote control' to display the pairing QR code."
            )

    # 3. Get connection URL and key
    if any(k in raw_action for k in ("url", "ip", "address", "key", "pin")):
        if not srv:
            return f"Sir, the dashboard server is configured for http://{_get_local_ip()}:{PORT}."
        key = srv.new_key()
        return (
            f"Sir, the Remote Dashboard is accessible on your local Wi-Fi at: {srv.get_url()}. "
            f"A fresh one-time access PIN is: {key}."
        )

    # 4. Features & Self-awareness explanation
    return (
        "Sir, you have a complete Phone Remote Dashboard system built into ARC. "
        "Here are its main capabilities:\n"
        "1. Live Two-Way Voice: Speak with me directly through your phone's microphone and hear my voice in real-time.\n"
        "2. Screen Mirroring: Stream your laptop screen directly to your phone browser at 10-15 FPS.\n"
        "3. Mobile Terminal: Send text commands and view the live conversation feed from anywhere on your Wi-Fi.\n"
        "4. File Transfer: Upload photos and files from your phone directly to your computer's Downloads folder.\n"
        "5. System Telemetry: Monitor CPU, RAM, and battery metrics remotely.\n"
        "6. Secure Access: Protected by one-time QR code pairing and AES-256-CBC encryption.\n"
        "Just say 'open remote control' or 'show QR code' whenever you want to connect your phone."
    )


TOOL = {
    "name": "remote_control",
    "description": (
        "Controls and queries the ARC Phone Remote Dashboard and mobile connection. "
        "Use when the user asks about remote control features, wants to connect their phone, "
        "asks to show or get the QR code / pairing URL / PIN, or asks what features the remote dashboard has. "
        "Actions: 'show_qr' (displays pairing QR code overlay on HUD), 'get_url' (returns IP/port and PIN), "
        "'status' (checks if phone is connected), 'features' (explains all phone dashboard features)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'show_qr' | 'get_url' | 'status' | 'features'",
            }
        },
        "required": [],
    },
    "handler": remote_control,
}
