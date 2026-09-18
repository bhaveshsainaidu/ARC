"""
Screen & webcam capture for ARC vision.

Provides the two capture entry points main.py uses — `_capture_screen()` and
`_capture_camera()` — plus their helpers (compression, camera auto-detection,
config access). main.py grabs a frame here on demand, then injects it into the
main Gemini Live session; there is no separate vision session here.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        from memory.config_manager import load_api_keys
        return load_api_keys()
    except Exception:
        return {}


def _save_config_key(key: str, value) -> None:
    try:
        from memory.config_manager import set_key
        set_key(key, value)
    except Exception as e:
        print(f"[Vision] [!] Could not save config key '{key}': {e}")


def _get_os() -> str:
    return _load_config().get("os_system", "windows").lower()


_IMG_MAX_W = 1280
_IMG_MAX_H = 720
_JPEG_Q    = 82


def _compress(img_bytes: bytes, source_format: str = "PNG") -> tuple[bytes, str]:
    if not _PIL:
        return img_bytes, f"image/{source_format.lower()}"

    try:
        img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q, optimize=False)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[Vision] ⚠️  Image compress failed: {e}")
        return img_bytes, f"image/{source_format.lower()}"


def _capture_screen() -> tuple[bytes, str]:

    if not _MSS:
        raise RuntimeError("mss is not installed. Run: pip install mss")

    with mss.mss() as sct:
        monitors = sct.monitors          # [0] = all combined, [1..n] = real screens
        target   = monitors[1] if len(monitors) > 1 else monitors[0]
        shot     = sct.grab(target)
        png      = mss.tools.to_png(shot.rgb, shot.size)

    return _compress(png, "PNG")


def _cv2_backend() -> int:
    """Return the best OpenCV camera backend for the current OS."""
    if not _CV2:
        return 0
    os_name = _get_os()
    if os_name == "windows":
        return cv2.CAP_DSHOW
    if os_name == "mac":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def _probe_camera(index: int, backend: int, warmup: int = 5) -> bool:

    if not _CV2:
        return False
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return False
    for _ in range(warmup):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return False
    return bool(np.mean(frame) > 8)


def _detect_camera_index() -> int:

    backend = _cv2_backend()
    print("[Vision] 🔍 Auto-detecting camera...")
    for idx in range(6):
        if _probe_camera(idx, backend):
            print(f"[Vision] ✅ Camera found at index {idx}")
            _save_config_key("camera_index", idx)
            return idx
        print(f"[Vision] ⚠️  Camera index {idx}: no usable frame")

    print("[Vision] ⚠️  No camera found — defaulting to index 0")
    _save_config_key("camera_index", 0)
    return 0


def _get_camera_index() -> int:
    try:
        from core.device_service import get_active_camera_index
        return get_active_camera_index()
    except Exception:
        cfg = _load_config()
        if "camera_index" in cfg:
            return int(cfg["camera_index"])
        return 0


def _capture_camera() -> tuple[bytes, str]:
    if not _CV2:
        raise RuntimeError("OpenCV (cv2) is not installed. Run: pip install opencv-python")

    index   = _get_camera_index()
    backend = _cv2_backend()
    cap     = cv2.VideoCapture(index, backend)

    if not cap.isOpened():
        raise RuntimeError(f"Camera index {index} could not be opened.")

    for _ in range(10):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Camera returned no frame.")

    try:
        from core.gpu_accelerator import get_gpu_accelerator
        accel = get_gpu_accelerator()
        h, w = frame.shape[:2]
        if w > _IMG_MAX_W or h > _IMG_MAX_H:
            scale = min(_IMG_MAX_W / w, _IMG_MAX_H / h)
            target = (int(w * scale), int(h * scale))
            proc = accel.process_frame_gpu(frame, target_size=target)
        else:
            proc = frame
        _, buf = cv2.imencode(".jpg", proc, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
        return buf.tobytes(), "image/jpeg"
    except Exception:
        pass

    if _PIL:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q)
        return buf.getvalue(), "image/jpeg"

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
    return buf.tobytes(), "image/jpeg"


# ==============================================================================
# ── Continuous Screen OCR Buffer (Feature 10) ─────────────────────────────────
# ==============================================================================

import threading
import time
from datetime import datetime

_screen_buffer: list[dict] = []
_buffer_lock = threading.Lock()
_ocr_thread: threading.Thread | None = None
_ocr_running = False
_TESSERACT_INITIALIZED = False


def _setup_tesseract():
    global _TESSERACT_INITIALIZED
    if _TESSERACT_INITIALIZED:
        return
    try:
        import os
        import pytesseract
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                pytesseract.pytesseract.tesseract_cmd = c
                break
        _TESSERACT_INITIALIZED = True
    except Exception:
        pass


def _run_ocr_on_bytes(img_bytes: bytes) -> str:
    """Run pytesseract OCR on image bytes if available."""
    if not _PIL:
        return ""
    _setup_tesseract()
    try:
        import pytesseract
        image = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception:
        return ""


def _screen_ocr_loop(interval: float = 30.0):
    global _ocr_running
    while _ocr_running:
        try:
            img_bytes, _ = _capture_screen()
            ocr_text = _run_ocr_on_bytes(img_bytes)
            now = datetime.now()
            entry = {
                "timestamp": now.isoformat(),
                "time_str": now.strftime("%H:%M:%S"),
                "text": ocr_text,
                "preview": ocr_text[:200] if ocr_text else "(No text detected)",
            }
            with _buffer_lock:
                _screen_buffer.append(entry)
                if len(_screen_buffer) > 5:
                    _screen_buffer.pop(0)
        except Exception:
            pass
        time.sleep(interval)


def start_screen_ocr_buffer(interval: float = 30.0):
    global _ocr_thread, _ocr_running
    if _ocr_running:
        return
    _ocr_running = True
    _ocr_thread = threading.Thread(
        target=_screen_ocr_loop,
        args=(interval,),
        daemon=True,
        name="ScreenOCRThread",
    )
    _ocr_thread.start()
    print("[Vision] Continuous 30s screen OCR buffer started.")


def stop_screen_ocr_buffer():
    global _ocr_running
    _ocr_running = False


def get_recent_screen_context(query: str = "") -> str:
    """Return recent screen OCR captures from the rolling buffer."""
    with _buffer_lock:
        buffer_copy = list(_screen_buffer)

    if not buffer_copy:
        return "No recent screen captures stored in buffer yet."

    lines = [f"Recent Screen Context (last {len(buffer_copy)} captures):"]
    q = (query or "").lower().strip()
    matches = 0

    for i, item in enumerate(buffer_copy, 1):
        text = item.get("text", "")
        ts = item.get("time_str", "")
        if q:
            if q in text.lower():
                matches += 1
                lines.append(f"[{ts}] Match: {text[:350]}...")
        else:
            matches += 1
            lines.append(f"[{ts}]: {item.get('preview', '')}")

    if q and matches == 0:
        return f"No mentions of '{query}' found across recent screen captures (checked {len(buffer_copy)} frames)."

    return "\n".join(lines)


def screen_context_query(parameters: dict, **_context) -> str:
    """Query recently captured screen content."""
    query = parameters.get("query", "").strip()
    return get_recent_screen_context(query=query)


TOOL = {
    "name": "screen_context",
    "description": (
        "Inspect recent screen content and text captured in the background 30-second rolling buffer "
        "(last 5 captures). Use when the user asks what was on their screen or refers to past screen state."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Keyword or topic to look for in past screen states (empty to list recent captures)",
            }
        },
    },
    "handler": screen_context_query,
}

