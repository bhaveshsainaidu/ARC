"""
plugins/screen_mirror.py — Real-Time Screen Mirroring Plugin for ARC.

Captures the computer's display using mss (with Pillow fallback) and streams
10-15 FPS JPEG frames over WebSocket to paired mobile devices on the same local
dashboard server (port 8000). View-only (no touch/clicks accepted from phone).

Voice Activation:
  "start screen mirror"  -> starts stream
  "stop screen mirror"   -> stops stream
  "screen mirror status" -> returns current status
"""

from __future__ import annotations

import asyncio
import io
import time
import traceback
from typing import Any, Optional

from PIL import Image

try:
    import mss
    _MSS_AVAILABLE = True
except ImportError:
    _MSS_AVAILABLE = False

try:
    from PIL import ImageGrab
    _PIL_GRAB_AVAILABLE = True
except ImportError:
    _PIL_GRAB_AVAILABLE = False

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import JSONResponse
    from dashboard.server import register_dashboard_route, get_dashboard_server
    _DASHBOARD_OK = True
except ImportError:
    _DASHBOARD_OK = False


# ── Global State ─────────────────────────────────────────────────────────────
_is_active: bool = False
_viewers: set[Any] = set()
_stream_task: Optional[asyncio.Task] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_server_ref: Any = None
_TARGET_FPS = 12
_FRAME_INTERVAL = 1.0 / _TARGET_FPS
_last_frame_hash: int = 0
_last_frame_sent_time: float = 0.0


def _get_stream_params() -> tuple[int, int, int]:
    """
    Returns (fps, jpeg_quality, max_width) adapted to current bandwidth state.
    """
    try:
        from core.bandwidth_monitor import get_bandwidth_state, HIGH, MEDIUM, LOW, CRITICAL
        state = get_bandwidth_state()
        if state == CRITICAL:
            return 1, 20, 640
        elif state == LOW:
            return 3, 35, 800
        elif state == MEDIUM:
            return 8, 60, 1024
        else:
            return 12, 80, 1280
    except Exception:
        return 12, 70, 1280


def _capture_frame() -> bytes | None:
    """Capture current primary screen and return JPEG bytes. Cross-platform & bandwidth adaptive."""
    global _last_frame_hash, _last_frame_sent_time
    img: Optional[Image.Image] = None

    if _MSS_AVAILABLE:
        try:
            with mss.mss() as sct:
                # Use primary monitor (index 1 in mss, index 0 is bounding box of all)
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(mon)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            img = None

    if img is None and _PIL_GRAB_AVAILABLE:
        try:
            img = ImageGrab.grab().convert("RGB")
        except Exception:
            img = None

    if img is None:
        return None

    fps, quality, max_w = _get_stream_params()

    # Fast perceptual delta check (downscaled 32x32)
    now = time.monotonic()
    try:
        small = img.resize((32, 32), Image.Resampling.NEAREST)
        current_hash = hash(small.tobytes())
        # If screen hasn't changed and last frame was sent < 2 seconds ago, skip
        if current_hash == _last_frame_hash and (now - _last_frame_sent_time) < 2.0:
            return None
        _last_frame_hash = current_hash
        _last_frame_sent_time = now
    except Exception:
        pass

    # Scale for mobile responsiveness according to bandwidth tier
    if img.width > max_w:
        ratio = float(max_w) / img.width
        new_size = (max_w, int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.BILINEAR)

    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=quality, optimize=True)
    return bio.getvalue()


async def _broadcast_loop() -> None:
    """Continuous async streaming loop sending frames to all connected viewer WebSockets."""
    global _stream_task
    try:
        while _is_active:
            if not _viewers:
                # No active viewers: wait lightly to avoid burning CPU
                await asyncio.sleep(0.2)
                continue

            fps, _, _ = _get_stream_params()
            target_interval = 1.0 / max(1, fps)

            t0 = time.monotonic()
            frame_bytes = await asyncio.to_thread(_capture_frame)

            if frame_bytes and _viewers:
                dead = set()
                for ws in list(_viewers):
                    try:
                        await ws.send_bytes(frame_bytes)
                    except Exception:
                        dead.add(ws)
                if dead:
                    _viewers.difference_update(dead)

            elapsed = time.monotonic() - t0
            sleep_time = max(0.01, target_interval - elapsed)
            await asyncio.sleep(sleep_time)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[ScreenMirror] Stream loop exception: {e}")
    finally:
        _stream_task = None


def start_mirroring() -> tuple[bool, str]:
    """Activate screen mirroring service."""
    global _is_active, _stream_task, _loop

    if _is_active:
        return True, "Screen mirroring is already active, Sir."

    _is_active = True

    # Start loop in running asyncio event loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = _loop

    if loop and loop.is_running():
        if _stream_task is None or _stream_task.done():
            _stream_task = loop.create_task(_broadcast_loop())

    srv = _server_ref or (get_dashboard_server() if _DASHBOARD_OK else None)
    if srv and hasattr(srv, "broadcast"):
        asyncio.create_task(srv.broadcast({
            "type": "screen_mirror_state",
            "active": True,
            "fps": _TARGET_FPS,
        }))

    return True, "Screen mirroring started, Sir. You can view your screen on the mobile dashboard."


def stop_mirroring() -> tuple[bool, str]:
    """Deactivate screen mirroring service and disconnect viewers."""
    global _is_active, _stream_task

    _is_active = False

    if _stream_task and not _stream_task.done():
        _stream_task.cancel()
        _stream_task = None

    # Disconnect any remaining viewers
    for ws in list(_viewers):
        try:
            asyncio.create_task(ws.close(code=1000, reason="Mirror stopped"))
        except Exception:
            pass
    _viewers.clear()

    srv = _server_ref or (get_dashboard_server() if _DASHBOARD_OK else None)
    if srv and hasattr(srv, "broadcast"):
        asyncio.create_task(srv.broadcast({
            "type": "screen_mirror_state",
            "active": False,
        }))

    return True, "Screen mirroring stopped, Sir."


def get_status() -> dict[str, Any]:
    """Return current mirror state."""
    return {
        "active": _is_active,
        "viewers": len(_viewers),
        "target_fps": _TARGET_FPS,
        "mss_available": _MSS_AVAILABLE,
        "pil_available": _PIL_GRAB_AVAILABLE,
    }


# ── Dashboard Server Extension Route Registration ────────────────────────────

def _register_routes(app: FastAPI, server: Any) -> None:
    """Register WebSocket and control endpoints on the FastAPI server instance."""
    global _server_ref, _loop
    _server_ref = server

    def _auth(req: Request) -> bool:
        tok = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return bool(tok) and tok in server._tokens

    @app.get("/api/screen-mirror/status")
    async def api_status(req: Request):
        return JSONResponse(get_status())

    @app.post("/api/screen-mirror/start")
    async def api_start(req: Request):
        if not _auth(req):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        ok, msg = start_mirroring()
        return JSONResponse({"ok": ok, "message": msg, "active": _is_active})

    @app.post("/api/screen-mirror/stop")
    async def api_stop(req: Request):
        if not _auth(req):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        ok, msg = stop_mirroring()
        return JSONResponse({"ok": ok, "message": msg, "active": _is_active})

    @app.websocket("/ws/screen-mirror")
    async def ws_screen_mirror(websocket: WebSocket, token: str = ""):
        global _loop, _stream_task
        _loop = asyncio.get_running_loop()

        tok = token.strip()
        if not tok or tok not in server._tokens:
            await websocket.close(code=4001, reason="Unauthorized")
            return

        await websocket.accept()
        _viewers.add(websocket)

        # If mirroring is active, make sure stream task is running
        if _is_active:
            if _stream_task is None or _stream_task.done():
                _stream_task = _loop.create_task(_broadcast_loop())

        try:
            while True:
                # View-only: ignore incoming text/control commands, maintain ping-pong
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            _viewers.discard(websocket)


if _DASHBOARD_OK:
    register_dashboard_route(_register_routes)


# ── Plugin Declaration ───────────────────────────────────────────────────────

PLUGIN = {
    "name": "screen_mirror",
    "description": (
        "Controls real-time screen mirroring from the laptop to the paired mobile dashboard. "
        "Call with action='start' when the user asks to start screen mirror, mirror screen, or stream display. "
        "Call with action='stop' when the user asks to stop screen mirror or stop display streaming. "
        "Call with action='status' to check if screen mirror is currently active."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["start", "stop", "status"],
                "description": "Action to perform: 'start' to start mirroring, 'stop' to stop mirroring, or 'status' to check status.",
            }
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Execute the screen_mirror plugin action."""
    action = str(parameters.get("action", "")).strip().lower()

    if action == "start":
        ok, msg = start_mirroring()
        if player and hasattr(player, "write_log"):
            player.write_log("SYS: Screen mirroring activated.")
        return msg
    elif action == "stop":
        ok, msg = stop_mirroring()
        if player and hasattr(player, "write_log"):
            player.write_log("SYS: Screen mirroring stopped.")
        return msg
    elif action == "status":
        st = get_status()
        state_str = "ACTIVE" if st["active"] else "IDLE"
        return f"Screen mirroring is {state_str} with {st['viewers']} connected viewer(s)."
    else:
        return f"Unknown action '{action}'. Supported actions: start, stop, status."
