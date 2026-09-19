"""
actions/gesture_control.py — ARC Camera Hand Gesture Recognition & Control.

Reinforced 30 FPS background engine with MediaPipe hand tracking, 20-gesture vocabulary
(15 single-hand + 5 two-hand), smart state-machine debouncing (8 frames), hold detection
(1.0s hold for fist/palms), smooth zoom interpolation (0.5x–3.0x), and decoupled
thread-safe frame and gesture queues.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from queue import Empty, Queue
from typing import Any, Callable, Optional, Tuple

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False


# ── Landmark & Finger Helpers ──────────────────────────────────────────────────

class Landmark:
    """Represents a 3D normalized hand landmark."""
    __slots__ = ("x", "y", "z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __getitem__(self, item: int) -> float:
        if item == 0:
            return self.x
        elif item == 1:
            return self.y
        elif item == 2:
            return self.z
        raise IndexError(f"Landmark index out of range: {item}")

    def __repr__(self) -> str:
        return f"Landmark(x={self.x:.3f}, y={self.y:.3f}, z={self.z:.3f})"


def _get_xyz(lm: Any) -> Tuple[float, float, float]:
    if hasattr(lm, "x") and hasattr(lm, "y"):
        return float(lm.x), float(lm.y), float(getattr(lm, "z", 0.0))
    if isinstance(lm, dict):
        return float(lm.get("x", 0.0)), float(lm.get("y", 0.0)), float(lm.get("z", 0.0))
    if isinstance(lm, (list, tuple)):
        return float(lm[0]), float(lm[1]), float(lm[2]) if len(lm) > 2 else 0.0
    return 0.0, 0.0, 0.0


def finger_is_up(landmarks: list[Any], finger_tip: int, finger_pip: int) -> bool:
    """In image coordinates (y=0 top, y=1 bottom), tip is higher when y is smaller."""
    _, y_tip, _ = _get_xyz(landmarks[finger_tip])
    _, y_pip, _ = _get_xyz(landmarks[finger_pip])
    return y_tip < y_pip


# ── 20 Gesture Vocabulary Matrix ─────────────────────────────────────────────

GESTURES = {
    # One hand gestures (G01 - G15)
    "INDEX_UP": "scroll activity log up",
    "INDEX_DOWN": "scroll activity log down",
    "PEACE": "screenshot + analyze screen",
    "THREE_FINGERS": "show QR code dashboard",
    "FOUR_FINGERS": "open settings drawer",
    "OPEN_PALM": "pause/resume ARC listening",
    "FIST": "mute/unmute microphone",
    "THUMBS_UP": "confirm pending action",
    "THUMBS_DOWN": "cancel pending action",
    "PINCH": "zoom in on sphere",
    "SPREAD": "zoom out on sphere",
    "POINT_LEFT": "previous panel",
    "POINT_RIGHT": "next panel",
    "OK_SIGN": "acknowledge/OK current notification",
    "CALL_ME": "toggle voice listening mode",
    # Two hand gestures (G16 - G20)
    "BOTH_PINCH_APART": "zoom in HUD",
    "BOTH_PINCH_TOGETHER": "zoom out HUD",
    "BOTH_OPEN_PALMS": "emergency stop all active tools",
    "LEFT_FIST_RIGHT_PEACE": "generate security report",
    "BOTH_THUMBS_UP": "extra confirmation for critical actions",
}

GESTURE_ICONS = {
    "INDEX_UP": "☝️",
    "INDEX_DOWN": "👇",
    "PEACE": "✌️",
    "THREE_FINGERS": "🤟",
    "FOUR_FINGERS": "🖖",
    "OPEN_PALM": "✋",
    "FIST": "✊",
    "THUMBS_UP": "👍",
    "THUMBS_DOWN": "👎",
    "PINCH": "🤏",
    "SPREAD": "👐",
    "POINT_LEFT": "👈",
    "POINT_RIGHT": "👉",
    "OK_SIGN": "👌",
    "CALL_ME": "🤙",
    "BOTH_PINCH_APART": "🔍+",
    "BOTH_PINCH_TOGETHER": "🔍-",
    "BOTH_OPEN_PALMS": "🛑",
    "LEFT_FIST_RIGHT_PEACE": "🛡️",
    "BOTH_THUMBS_UP": "🙌",
}


# ── Gesture Classifier ───────────────────────────────────────────────────────

def classify_gesture(landmarks: list[Any], hand_label: str = "Right") -> Tuple[Optional[str], float]:
    """
    Classifies a 21-landmark hand configuration into one of the recognized gestures.
    Returns (gesture_name, confidence). Returns (None, 0.0) if no match.
    """
    if len(landmarks) < 21:
        return None, 0.0

    wx, wy, _ = _get_xyz(landmarks[0])
    tx, ty, _ = _get_xyz(landmarks[4])
    t_ip_x, t_ip_y, _ = _get_xyz(landmarks[3])
    t_mcp_x, t_mcp_y, _ = _get_xyz(landmarks[2])
    ix, iy, _ = _get_xyz(landmarks[8])
    i_pip_x, i_pip_y, _ = _get_xyz(landmarks[6])
    i_mcp_x, i_mcp_y, _ = _get_xyz(landmarks[5])
    mx, my, _ = _get_xyz(landmarks[12])
    m_pip_x, m_pip_y, _ = _get_xyz(landmarks[10])
    rx, ry, _ = _get_xyz(landmarks[16])
    r_pip_x, r_pip_y, _ = _get_xyz(landmarks[14])
    px, py, _ = _get_xyz(landmarks[20])
    p_pip_x, p_pip_y, _ = _get_xyz(landmarks[18])

    index_up = iy < i_pip_y
    middle_up = my < m_pip_y
    ring_up = ry < r_pip_y
    pinky_up = py < p_pip_y

    # Distance functions
    def dist_pts(x1, y1, x2, y2):
        return math.hypot(x1 - x2, y1 - y2)

    pinch_dist = dist_pts(tx, ty, ix, iy)
    thumb_dist_wrist = dist_pts(tx, ty, wx, wy)
    index_ext_dist = dist_pts(ix, iy, i_mcp_x, i_mcp_y)

    thumb_up = ty < t_ip_y - 0.04 and ty < t_mcp_y - 0.06 and ty < i_mcp_y
    thumb_down = ty > t_ip_y + 0.04 and ty > t_mcp_y + 0.06 and ty > wy + 0.02

    pointing_left = (ix < i_pip_x - 0.08) and (ix < i_mcp_x - 0.08) and abs(iy - i_pip_y) < 0.12
    pointing_right = (ix > i_pip_x + 0.08) and (ix > i_mcp_x + 0.08) and abs(iy - i_pip_y) < 0.12
    index_down = (iy > i_pip_y + 0.05) and (iy > i_mcp_y + 0.05) and (index_ext_dist > 0.18)

    # 1. G14 - OK SIGN (Thumb + Index touch forming circle, middle, ring, pinky up)
    if pinch_dist < 0.08 and middle_up and ring_up and pinky_up:
        return "OK_SIGN", 0.93

    # 2. G06 - OPEN PALM / G05 - FOUR FINGERS
    if index_up and middle_up and ring_up and pinky_up:
        if thumb_up or thumb_dist_wrist > 0.22:
            return "OPEN_PALM", 0.95
        else:
            return "FOUR_FINGERS", 0.92

    # 3. G04 - THREE FINGERS (Index, Middle, Ring up, Pinky curled)
    if index_up and middle_up and ring_up and (not pinky_up) and (not thumb_up):
        return "THREE_FINGERS", 0.93

    # 4. G03 - PEACE / V SIGN (Index & Middle up, Ring & Pinky curled)
    if index_up and middle_up and (not ring_up) and (not pinky_up) and not thumb_up and pinch_dist > 0.07:
        return "PEACE", 0.94

    # 5. G15 - CALL ME (Thumb & Pinky extended, middle three curled)
    if (thumb_up or thumb_dist_wrist > 0.20) and pinky_up and (not index_up) and (not middle_up) and (not ring_up):
        return "CALL_ME", 0.93

    # 6. G12 - POINT LEFT / G13 - POINT RIGHT
    if pointing_left and (not middle_up) and (not ring_up) and (not pinky_up):
        return "POINT_LEFT", 0.92

    if pointing_right and (not middle_up) and (not ring_up) and (not pinky_up):
        return "POINT_RIGHT", 0.92

    # 7. G08 - THUMBS UP / G09 - THUMBS DOWN
    if thumb_up and (not index_up) and (not middle_up) and (not ring_up) and (not pinky_up):
        return "THUMBS_UP", 0.96

    if thumb_down and (not index_up) and (not middle_up) and (not ring_up) and (not pinky_up):
        return "THUMBS_DOWN", 0.96

    # 8. G02 - INDEX DOWN / G01 - INDEX UP
    if index_down and (not middle_up) and (not ring_up) and (not pinky_up) and (not thumb_up) and (not thumb_down):
        return "INDEX_DOWN", 0.93

    if index_up and (not middle_up) and (not ring_up) and (not pinky_up) and (not thumb_up) and (not pointing_left) and (not pointing_right):
        return "INDEX_UP", 0.95

    # 9. G10 - PINCH / G11 - SPREAD
    if pinch_dist < 0.07 and (not middle_up) and (not ring_up) and (not pinky_up) and (index_ext_dist > 0.14):
        return "PINCH", 0.90

    if pinch_dist > 0.28 and (not middle_up) and (not ring_up) and (not pinky_up):
        return "SPREAD", 0.89

    # 10. G07 - FIST (all fingers curled)
    all_curled = (not index_up) and (not middle_up) and (not ring_up) and (not pinky_up)
    if all_curled and (not thumb_up) and (not thumb_down):
        return "FIST", 0.94

    return None, 0.0



def classify_two_hand_gesture(
    landmarks_left: list[Any],
    landmarks_right: list[Any],
    prev_hand_dist: Optional[float] = None,
) -> Tuple[Optional[str], float, float]:
    """
    Classifies dual-hand interactions G16 to G20.
    Returns (gesture_name, confidence, current_hand_dist).
    """
    g_left, conf_l = classify_gesture(landmarks_left, "Left")
    g_right, conf_r = classify_gesture(landmarks_right, "Right")

    # Measure distance between wrists or palms
    w_lx, w_ly, _ = _get_xyz(landmarks_left[0])
    w_rx, w_ry, _ = _get_xyz(landmarks_right[0])
    cur_dist = math.hypot(w_lx - w_rx, w_ly - w_ry)

    # G20 - BOTH THUMBS UP
    if g_left == "THUMBS_UP" and g_right == "THUMBS_UP":
        return "BOTH_THUMBS_UP", 0.98, cur_dist

    # G18 - BOTH OPEN PALMS
    if g_left == "OPEN_PALM" and g_right == "OPEN_PALM":
        return "BOTH_OPEN_PALMS", 0.98, cur_dist

    # G19 - LEFT FIST + RIGHT PEACE
    if g_left == "FIST" and g_right == "PEACE":
        return "LEFT_FIST_RIGHT_PEACE", 0.95, cur_dist

    # G16 & G17 - Dual Pinch Apart / Together
    if (g_left in ("PINCH", "SPREAD")) and (g_right in ("PINCH", "SPREAD")):
        if prev_hand_dist is not None:
            delta = cur_dist - prev_hand_dist
            if delta > 0.03:
                return "BOTH_PINCH_APART", 0.92, cur_dist
            elif delta < -0.03:
                return "BOTH_PINCH_TOGETHER", 0.92, cur_dist

    return None, 0.0, cur_dist


# ── Hold Detector ────────────────────────────────────────────────────────────

class GestureHoldDetector:
    """Tracks continuous gesture hold time with normalized progress 0.0 to 1.0."""

    def __init__(self, gesture_name: str, hold_duration_s: float = 1.0):
        self.gesture_name = gesture_name
        self.hold_duration = float(hold_duration_s)
        self.hold_start: Optional[float] = None
        self.progress: float = 0.0

    def update(self, gesture_detected: bool) -> bool:
        now = time.time()
        if gesture_detected:
            if self.hold_start is None:
                self.hold_start = now
            elapsed = now - self.hold_start
            self.progress = min(elapsed / max(0.001, self.hold_duration), 1.0)
            if self.progress >= 1.0:
                self.hold_start = None
                self.progress = 0.0
                return True
        else:
            self.hold_start = None
            self.progress = 0.0
        return False


# ── State Machine Debouncer ──────────────────────────────────────────────────

class GestureStateMachine:
    """Smart state machine debouncer: 8 frame confirmation window + 1.5s cooldown."""

    IDLE = "IDLE"
    DETECTING = "DETECTING"
    CONFIRMED = "CONFIRMED"
    COOLDOWN = "COOLDOWN"

    def __init__(self, required_frames: int = 8, cooldown_s: float = 1.5):
        self.state = self.IDLE
        self.current_gesture: Optional[str] = None
        self.frame_count = 0
        self.required_frames = required_frames
        self.cooldown_s = cooldown_s
        self.cooldown_until: float = 0.0
        self.last_fired: Optional[str] = None

    def process(self, detected_gesture: Optional[str]) -> Optional[str]:
        now = time.time()

        if self.state == self.COOLDOWN:
            if now >= self.cooldown_until:
                self.state = self.IDLE
                self.current_gesture = None
                self.frame_count = 0
            else:
                return None

        if detected_gesture is None:
            self.state = self.IDLE
            self.current_gesture = None
            self.frame_count = 0
            return None

        if detected_gesture != self.current_gesture:
            self.current_gesture = detected_gesture
            self.frame_count = 1
            self.state = self.DETECTING
            return None

        if self.state == self.DETECTING:
            self.frame_count += 1
            if self.frame_count >= self.required_frames:
                self.state = self.COOLDOWN
                self.cooldown_until = now + self.cooldown_s
                self.last_fired = detected_gesture
                return detected_gesture

        return None


# ── Smooth Zoom Controller ───────────────────────────────────────────────────

class GestureZoomController:
    """Smooth zoom controller with range 0.5x–3.0x and clamped per-frame step."""

    def __init__(self):
        self.current_zoom = 1.0
        self.target_zoom = 1.0
        self.min_zoom = 0.5
        self.max_zoom = 3.0
        self.smooth_factor = 0.15

    def set_pinch_distance(self, distance: float, reference_distance: float) -> None:
        if reference_distance <= 0.0:
            reference_distance = 0.1
        ratio = distance / reference_distance
        self.target_zoom = max(self.min_zoom, min(self.max_zoom, ratio))

    def update(self) -> float:
        delta = (self.target_zoom - self.current_zoom) * self.smooth_factor
        # Clamp per-frame delta to ensure smooth visual transition (no jump > 0.10x)
        delta = max(-0.095, min(0.095, delta))
        self.current_zoom += delta
        return self.current_zoom


# ── Dedicated Gesture Engine Thread ──────────────────────────────────────────

class GestureEngine(threading.Thread):
    """
    Dedicated 30 FPS background engine for webcam acquisition and hand gesture recognition.
    Decoupled via queues from UI and audio threads.
    """

    def __init__(self, player=None):
        super().__init__(daemon=True, name="ARC-GestureEngine")
        self.player = player
        self.cap = None
        self.hands = None
        self.mp_drawing = None
        self.mp_hands = None
        self.tasks_landmarker = None
        self.running = False
        self.camera_enabled = True
        self.flip_horizontal = True
        self.brightness_offset = 0

        self.gesture_queue: Queue[str] = Queue(maxsize=10)
        self.frame_queue: Queue[Any] = Queue(maxsize=3)

        self.fps_target = 30
        self.frame_time = 1.0 / float(self.fps_target)

        self.state_machine = GestureStateMachine(required_frames=8, cooldown_s=1.5)
        self.hold_detector = GestureHoldDetector("FIST", hold_duration_s=1.0)
        self.zoom_controller = GestureZoomController()

        self.last_gesture = "None"
        self.last_confidence = 0.0
        self.last_latency_ms = 0.0
        self.active_hands = 0
        self.active_landmarks = 0
        self.history: list[dict] = []  # last 5 gestures
        self.current_fps = 30.0
        self._prev_hand_dist: Optional[float] = None
        self._prev_frame_t = time.time()

        self.on_gesture_callback: Optional[Callable[[str], None]] = None
        self.on_frame_callback: Optional[Callable[[bytes], None]] = None
        self.on_stats_callback: Optional[Callable[[dict], None]] = None
        self._latest_jpeg: Optional[bytes] = None
        self._last_frame: Any = None
        self._has_started = False

    def get_snapshot_jpeg(self) -> Optional[bytes]:
        """Returns the latest pre-encoded 30 FPS JPEG frame without re-querying camera."""
        return self._latest_jpeg

    def start_engine(self) -> Tuple[bool, str]:
        if self.running and self.is_alive():
            return True, "GestureEngine is already active."
        self.running = True
        self._has_started = True
        self.start()
        return True, "GestureEngine active at 30 FPS."

    def stop_engine(self) -> Tuple[bool, str]:
        self.running = False
        if self.is_alive() and threading.current_thread() != self:
            self.join(timeout=2.0)
        return True, "GestureEngine stopped."

    def run(self) -> None:
        self._init_mediapipe()
        self._init_camera()

        while self.running:
            t0 = time.time()
            self._process_frame()
            elapsed = time.time() - t0
            sleep_time = self.frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        self._cleanup()

    def _init_mediapipe(self) -> None:
        # 1. Try legacy mp.solutions.hands (MediaPipe <= 0.10.14)
        try:
            import mediapipe as mp
            if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
                self.mp_hands = mp.solutions.hands
                self.hands = self.mp_hands.Hands(
                    static_image_mode=False,
                    max_num_hands=2,
                    min_detection_confidence=0.7,
                    min_tracking_confidence=0.7,
                    model_complexity=0,  # Fastest model
                )
            if hasattr(mp, "solutions") and hasattr(mp.solutions, "drawing_utils"):
                self.mp_drawing = mp.solutions.drawing_utils
        except Exception as e:
            print(f"[GestureEngine] MediaPipe legacy init note: {e}")

        # 2. Try MediaPipe Tasks HandLandmarker (MediaPipe 1.0+ / modern API)
        if self.hands is None:
            try:
                import mediapipe as mp
                from mediapipe.tasks import python as mp_python
                from mediapipe.tasks.python import vision
                from pathlib import Path
                import urllib.request

                if getattr(sys, "frozen", False):
                    base_dir = Path(sys.executable).parent
                else:
                    base_dir = Path(__file__).resolve().parent.parent

                model_dir = base_dir / "models"
                model_path = model_dir / "hand_landmarker.task"
                if not model_path.exists() and hasattr(sys, "_MEIPASS"):
                    mei_path = Path(sys._MEIPASS) / "models" / "hand_landmarker.task"
                    if mei_path.exists():
                        model_path = mei_path
                else:
                    model_dir.mkdir(parents=True, exist_ok=True)

                if not model_path.exists() or model_path.stat().st_size < 1000000:
                    url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
                    urllib.request.urlretrieve(url, model_path)

                base_options = mp_python.BaseOptions(model_asset_path=str(model_path))
                options = vision.HandLandmarkerOptions(
                    base_options=base_options,
                    running_mode=vision.RunningMode.IMAGE,
                    num_hands=2,
                    min_hand_detection_confidence=0.55,
                    min_tracking_confidence=0.55,
                )
                self.tasks_landmarker = vision.HandLandmarker.create_from_options(options)
                print("[GestureEngine] MediaPipe Tasks HandLandmarker initialized successfully.")
            except Exception as e:
                print(f"[GestureEngine] MediaPipe Tasks init note: {e}")

    _CAM_LOCK = threading.Lock()

    def _init_camera(self) -> None:
        if not self.camera_enabled:
            return

        cam_idx = 0
        try:
            from core.device_service import get_selected_camera
            cam_idx = get_selected_camera()
        except Exception:
            cam_idx = 0

        with GestureEngine._CAM_LOCK:
            try:
                backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
                self.cap = cv2.VideoCapture(cam_idx, backend)
                if not self.cap.isOpened() and backend != cv2.CAP_ANY:
                    self.cap = cv2.VideoCapture(cam_idx)
                if self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_FPS, 30)
            except Exception as e:
                print(f"[GestureEngine] Camera open note: {e}")

    def _cleanup(self) -> None:
        if self.hands is not None:
            try:
                self.hands.close()
            except Exception:
                pass
            self.hands = None
        if getattr(self, "tasks_landmarker", None) is not None:
            try:
                self.tasks_landmarker.close()
            except Exception:
                pass
            self.tasks_landmarker = None
        with GestureEngine._CAM_LOCK:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None

    def _process_frame(self) -> None:
        now = time.time()
        dt = now - self._prev_frame_t
        if dt > 0:
            self.current_fps = round(1.0 / dt, 1)
        self._prev_frame_t = now

        frame = None
        if self.cap is not None and self.cap.isOpened() and self.camera_enabled:
            try:
                ret, raw = self.cap.read()
                if ret and raw is not None:
                    frame = raw
            except Exception:
                frame = None

        if frame is None:
            # Fallback black canvas with status overlay
            if _CV2_AVAILABLE:
                import numpy as np
                frame = np.zeros((240, 320, 3), dtype=np.uint8)
                cv2.putText(
                    frame,
                    "CAMERA STANDBY" if not self.camera_enabled else "NO FEED",
                    (60, 120),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 180, 255),
                    2,
                )
            self.active_hands = 0
            self.active_landmarks = 0
            self._update_queues(frame, "None", 0.0, 0.0)
            return

        # Pre-process frame
        if self.flip_horizontal:
            frame = cv2.flip(frame, 1)
        if self.brightness_offset != 0:
            frame = cv2.convertScaleAbs(frame, alpha=1.0, beta=self.brightness_offset)

        # Scale off-thread before queue or UI transfer
        frame = cv2.resize(frame, (320, 240))

        # MediaPipe landmark detection
        t_detect = time.perf_counter()
        detected_gesture: Optional[str] = None
        confidence: float = 0.0

        if self.hands is not None or getattr(self, "tasks_landmarker", None) is not None:
            try:
                try:
                    from core.gpu_accelerator import get_gpu_accelerator
                    rgb_frame = get_gpu_accelerator().process_frame_gpu(frame, to_rgb=True)
                except Exception:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                hands_list = []
                results_obj = None

                if self.hands is not None:
                    results = self.hands.process(rgb_frame)
                    results_obj = results
                    if results and getattr(results, "multi_hand_landmarks", None):
                        hands_list = [h.landmark for h in results.multi_hand_landmarks]
                elif getattr(self, "tasks_landmarker", None) is not None:
                    import mediapipe as mp
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    res = self.tasks_landmarker.detect(mp_image)
                    results_obj = res
                    if res and getattr(res, "hand_landmarks", None):
                        hands_list = res.hand_landmarks

                detect_lat = (time.perf_counter() - t_detect) * 1000.0
                self.last_latency_ms = round(detect_lat, 1)

                if hands_list:
                    num_hands = len(hands_list)
                    self.active_hands = num_hands
                    self.active_landmarks = num_hands * 21

                    # Two hand classification
                    if num_hands >= 2:
                        lm_left = hands_list[0]
                        lm_right = hands_list[1]
                        g_two, conf_two, dist = classify_two_hand_gesture(
                            lm_left, lm_right, self._prev_hand_dist
                        )
                        self._prev_hand_dist = dist
                        if g_two:
                            detected_gesture = g_two
                            confidence = conf_two
                        else:
                            detected_gesture, confidence = classify_gesture(lm_left)

                    elif num_hands == 1:
                        lm_single = hands_list[0]
                        detected_gesture, confidence = classify_gesture(lm_single)

                    # Draw green futuristic landmarks, connections and bounding boxes
                    if results_obj is not None:
                        self._draw_landmarks_overlay(frame, results_obj)

                else:
                    self.active_hands = 0
                    self.active_landmarks = 0
                    self._prev_hand_dist = None

            except Exception as e:
                self.active_hands = 0
                self.active_landmarks = 0

        # Debounce and State Machine
        fired_gesture = self.state_machine.process(detected_gesture)

        # Hold detector for FIST (1.0s hold)
        if detected_gesture == "FIST":
            if self.hold_detector.update(True):
                fired_gesture = "FIST"
        else:
            self.hold_detector.update(False)

        # Pinch Zoom update
        if detected_gesture == "PINCH":
            self.zoom_controller.set_pinch_distance(0.04, 0.08)
        elif detected_gesture == "SPREAD":
            self.zoom_controller.set_pinch_distance(0.20, 0.08)
        self.zoom_controller.update()

        # Execute gesture if confirmed
        if fired_gesture:
            self._on_gesture_fired(fired_gesture)

        self._update_queues(frame, detected_gesture or "None", confidence, self.last_latency_ms)

    HAND_CONNECTIONS = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
        (5, 9), (9, 13), (13, 17),
    ]

    def _draw_landmarks_overlay(self, frame: Any, results: Any) -> None:
        """Renders green futuristic landmark dots, connections, and labels on frame."""
        h, w, _ = frame.shape

        if self.mp_drawing is not None and self.mp_hands is not None and hasattr(results, "multi_hand_landmarks") and results.multi_hand_landmarks:
            for hand_lms in results.multi_hand_landmarks:
                self.mp_drawing.draw_landmarks(
                    frame,
                    hand_lms,
                    self.mp_hands.HAND_CONNECTIONS,
                    self.mp_drawing.DrawingSpec(color=(0, 255, 128), thickness=2, circle_radius=2),
                    self.mp_drawing.DrawingSpec(color=(0, 220, 100), thickness=2),
                )
                xs = [int(getattr(pt, "x", 0.0) * w) for pt in hand_lms.landmark]
                ys = [int(getattr(pt, "y", 0.0) * h) for pt in hand_lms.landmark]
                min_x, max_x = max(0, min(xs) - 8), min(w - 1, max(xs) + 8)
                min_y, max_y = max(0, min(ys) - 8), min(h - 1, max(ys) + 8)
                cv2.rectangle(frame, (min_x, min_y), (max_x, max_y), (0, 255, 100), 1)
            return

        # Direct OpenCV rendering compatible with MediaPipe Tasks and custom landmarks
        hands_list = []
        if hasattr(results, "multi_hand_landmarks") and results.multi_hand_landmarks:
            hands_list = results.multi_hand_landmarks
        elif hasattr(results, "hand_landmarks") and results.hand_landmarks:
            hands_list = results.hand_landmarks
        elif isinstance(results, (list, tuple)):
            hands_list = results

        for hand in hands_list:
            lms = hand.landmark if hasattr(hand, "landmark") else hand
            if not lms or len(lms) < 21:
                continue

            pts = []
            xs = []
            ys = []
            for lm in lms:
                x, y, _ = _get_xyz(lm)
                px = max(0, min(w - 1, int(x * w)))
                py = max(0, min(h - 1, int(y * h)))
                pts.append((px, py))
                xs.append(px)
                ys.append(py)

            for p1, p2 in self.HAND_CONNECTIONS:
                if p1 < len(pts) and p2 < len(pts):
                    cv2.line(frame, pts[p1], pts[p2], (0, 255, 128), 2)

            for px, py in pts:
                cv2.circle(frame, (px, py), 3, (0, 220, 100), -1)

            if xs and ys:
                min_x, max_x = max(0, min(xs) - 8), min(w - 1, max(xs) + 8)
                min_y, max_y = max(0, min(ys) - 8), min(h - 1, max(ys) + 8)
                cv2.rectangle(frame, (min_x, min_y), (max_x, max_y), (0, 255, 100), 1)

    def _update_queues(self, frame: Any, gesture: str, confidence: float, latency: float) -> None:
        self.last_gesture = gesture
        self.last_confidence = confidence

        # Push frame to queue, dropping old if full
        if self.frame_queue.full():
            try:
                self.frame_queue.get_nowait()
            except Empty:
                pass
        try:
            self.frame_queue.put_nowait(frame)
        except Exception:
            pass

        self._last_frame = frame

        # Encode and cache latest JPEG frame for callbacks and remote snapshot endpoint
        if frame is not None and _CV2_AVAILABLE:
            try:
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                self._latest_jpeg = buf.tobytes()
                if self.on_frame_callback:
                    self.on_frame_callback(self._latest_jpeg)
            except Exception:
                pass

        if self.on_stats_callback:
            try:
                self.on_stats_callback({
                    "fps": self.current_fps,
                    "latency_ms": latency,
                    "hands": self.active_hands,
                    "landmarks": self.active_landmarks,
                    "gesture": gesture,
                    "confidence": confidence,
                    "frame_progress": self.state_machine.frame_count,
                    "required_frames": self.state_machine.required_frames,
                    "hold_progress": self.hold_detector.progress,
                    "zoom": round(self.zoom_controller.current_zoom, 2),
                })
            except Exception:
                pass

    def _on_gesture_fired(self, gesture: str) -> None:
        """Dispatches fired gesture action and logs to history."""
        now_str = time.strftime("%H:%M:%S")
        action_desc = GESTURES.get(gesture, "Triggered gesture")
        self.history.append({
            "time": now_str,
            "gesture": gesture,
            "action": action_desc,
        })
        if len(self.history) > 5:
            self.history.pop(0)

        # Push to gesture queue
        if self.gesture_queue.full():
            try:
                self.gesture_queue.get_nowait()
            except Empty:
                pass
        try:
            self.gesture_queue.put_nowait(gesture)
        except Exception:
            pass

        if self.on_gesture_callback:
            try:
                self.on_gesture_callback(gesture)
            except Exception:
                pass

        self._execute_action(gesture)

    def _get_ui_window(self) -> Optional[Any]:
        """Resolves active Qt MainWindow instance from player reference."""
        if not self.player:
            return None
        if hasattr(self.player, "_toggle_mute") or hasattr(self.player, "_open_remote"):
            return self.player
        if hasattr(self.player, "ui"):
            ui = self.player.ui
            if hasattr(ui, "_win") and ui._win is not None:
                return ui._win
            if hasattr(ui, "_toggle_mute") or hasattr(ui, "_open_remote"):
                return ui
        return None

    def _dispatch_ui(self, fn: Callable[[], None]) -> None:
        """Dispatches widget modification to Qt main thread safely."""
        try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, fn)
        except Exception:
            try:
                fn()
            except Exception:
                pass

    def _execute_action(self, gesture: str) -> None:
        """Executes corresponding system action for the fired gesture."""
        try:
            win = self._get_ui_window()

            # G08: THUMBS_UP / G20: BOTH_THUMBS_UP -> Confirm action
            if gesture in ("THUMBS_UP", "BOTH_THUMBS_UP"):
                from core.confirm import resolve
                resolve(True)
                return

            # G09: THUMBS_DOWN -> Cancel pending action
            if gesture == "THUMBS_DOWN":
                from core.confirm import resolve
                resolve(False)
                return

            # G07: FIST -> Mute/Unmute microphone
            if gesture == "FIST":
                if win and hasattr(win, "_toggle_mute"):
                    self._dispatch_ui(win._toggle_mute)
                    return
                if _PYAUTOGUI:
                    pyautogui.press("volumemute")
                return

            # G18: BOTH_OPEN_PALMS -> Emergency stop all active tools
            if gesture == "BOTH_OPEN_PALMS":
                if self.player and hasattr(self.player, "interrupt"):
                    self.player.interrupt()
                elif self.player and hasattr(self.player, "on_interrupt"):
                    if callable(self.player.on_interrupt):
                        self.player.on_interrupt()
                from core.confirm import resolve
                resolve(False)
                return

            # G06: OPEN_PALM -> Pause/Resume listening
            if gesture == "OPEN_PALM":
                if win and hasattr(win, "_tap_wake_manual"):
                    self._dispatch_ui(win._tap_wake_manual)
                    return

            # G03: PEACE / G04: THREE_FINGERS -> Open remote dashboard / QR code
            if gesture in ("PEACE", "THREE_FINGERS"):
                if win:
                    if hasattr(win, "_open_remote"):
                        self._dispatch_ui(win._open_remote)
                        return
                    elif hasattr(win, "open_remote"):
                        self._dispatch_ui(win.open_remote)
                        return
                if self.player and hasattr(self.player, "open_remote"):
                    self.player.open_remote()
                return

            # G05: FOUR_FINGERS -> Open settings drawer
            if gesture == "FOUR_FINGERS":
                if win and hasattr(win, "_toggle_drawer"):
                    self._dispatch_ui(lambda: win._toggle_drawer(True))
                    return

            # G01 / G02: Activity scroll
            if gesture == "INDEX_UP" and _PYAUTOGUI:
                pyautogui.scroll(120)
            elif gesture == "INDEX_DOWN" and _PYAUTOGUI:
                pyautogui.scroll(-120)

            # G12 / G13: Navigation
            if gesture == "POINT_LEFT" and _PYAUTOGUI:
                pyautogui.hotkey("ctrl", "win", "left")
            elif gesture == "POINT_RIGHT" and _PYAUTOGUI:
                pyautogui.hotkey("ctrl", "win", "right")

        except Exception as e:
            print(f"[GestureEngine] Execution error for {gesture}: {e}")


# ── Gesture Controller Singleton ─────────────────────────────────────────────

class GestureController:
    """Manages the gesture recognition engine and state machine."""

    _instance: Optional["GestureController"] = None
    _lock = threading.Lock()

    def __init__(self, player=None):
        self.player = player
        self.engine = GestureEngine(player)
        self.on_gesture_callback: Optional[Callable[[str], None]] = None
        self.on_frame_callback: Optional[Callable[[bytes], None]] = None
        self.on_stats_callback: Optional[Callable[[dict], None]] = None

    @classmethod
    def get_instance(cls, player=None) -> "GestureController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(player)
            elif player is not None:
                cls._instance.player = player
                cls._instance.engine.player = player
            return cls._instance

    def is_running(self) -> bool:
        return self.engine.running and self.engine.is_alive()

    @property
    def _last_gesture(self) -> str:
        return self.engine.last_gesture

    @property
    def history(self) -> list[dict]:
        return self.engine.history

    def get_snapshot_jpeg(self) -> Optional[bytes]:
        """Return the latest frame JPEG from the engine, or None."""
        if self.engine:
            return self.engine.get_snapshot_jpeg()
        return None

    def start(self) -> Tuple[bool, str]:
        if self.is_running():
            return True, "Gesture control is already active."
        if not _CV2_AVAILABLE:
            return False, "OpenCV (cv2) is not installed."

        if getattr(self.engine, "_has_started", False) or getattr(self.engine, "ident", None) is not None:
            prev = self.engine
            if prev.is_alive():
                prev.stop_engine()
            self.engine = GestureEngine(self.player)
            self.engine.camera_enabled = prev.camera_enabled
            self.engine.flip_horizontal = prev.flip_horizontal
            self.engine.brightness_offset = prev.brightness_offset
            self.engine.on_gesture_callback = self.on_gesture_callback or prev.on_gesture_callback
            self.engine.on_frame_callback = self.on_frame_callback or prev.on_frame_callback
            self.engine.on_stats_callback = self.on_stats_callback or prev.on_stats_callback
            self.engine.history = list(prev.history)
            self.engine._latest_jpeg = prev._latest_jpeg
            self.engine._last_frame = prev._last_frame
        else:
            if self.on_gesture_callback:
                self.engine.on_gesture_callback = self.on_gesture_callback
            if self.on_frame_callback:
                self.engine.on_frame_callback = self.on_frame_callback
            if self.on_stats_callback:
                self.engine.on_stats_callback = self.on_stats_callback

        self.engine.start_engine()
        self._notify_hud(True, "Gesture Tracking Active")
        return True, "Gesture control active at 30 FPS. Monitoring webcam for hand gestures."

    def stop(self) -> Tuple[bool, str]:
        if not self.engine.running:
            self._notify_hud(False, "None")
            return True, "Gesture control is not running."

        self.engine.stop_engine()
        self._notify_hud(False, "None")
        return True, "Gesture control stopped."

    def toggle_camera(self) -> bool:
        self.engine.camera_enabled = not self.engine.camera_enabled
        return self.engine.camera_enabled

    def toggle_flip(self) -> bool:
        self.engine.flip_horizontal = not self.engine.flip_horizontal
        return self.engine.flip_horizontal

    def adjust_brightness(self, delta: int) -> int:
        self.engine.brightness_offset = max(-100, min(100, self.engine.brightness_offset + delta))
        return self.engine.brightness_offset

    def _notify_hud(self, active: bool, gesture: str = "") -> None:
        g = gesture or self._last_gesture
        if self.on_gesture_callback:
            try:
                self.on_gesture_callback(g)
            except Exception:
                pass
        if not self.player:
            return
        try:
            if hasattr(self.player, "set_gesture_active"):
                try:
                    self.player.set_gesture_active(active, g)
                except TypeError:
                    self.player.set_gesture_active(active)
            elif hasattr(self.player, "ui") and hasattr(self.player.ui, "set_gesture_active"):
                try:
                    self.player.ui.set_gesture_active(active, g)
                except TypeError:
                    self.player.ui.set_gesture_active(active)
        except Exception:
            pass


def gesture_control(parameters: dict, player=None, **_context) -> str:
    """Action handler for controlling camera-based gesture recognition."""
    action = str(parameters.get("action", "status")).strip().lower()
    ctrl = GestureController.get_instance(player)

    if action in ("start", "enable", "on"):
        ok, msg = ctrl.start()
        return msg if ok else f"Failed to start gesture control: {msg}"
    elif action in ("stop", "disable", "off"):
        ok, msg = ctrl.stop()
        return msg
    elif action in ("toggle",):
        if ctrl.is_running():
            _, msg = ctrl.stop()
        else:
            _, msg = ctrl.start()
        return msg
    elif action in ("status", "info"):
        state = "ACTIVE (30 FPS)" if ctrl.is_running() else "STOPPED"
        last = ctrl._last_gesture
        return (
            f"Gesture Control Status: {state}.\n"
            f"Last recognized gesture: {last}.\n"
            f"Active vocabulary: 20 gestures (G01–G20) with 8-frame smart debounce and 1.5s cooldown."
        )
    return f"Unknown action '{action}'. Options: start, stop, toggle, status."


TOOL = {
    "name": "gesture_control",
    "description": (
        "Start, stop, or query camera-based hand gesture control. Recognizes 20 gestures: "
        "thumbs up/down, open palm, fist (1s hold), peace, pinch, spread, index up/down, "
        "three/four fingers, OK sign, call me, pointing left/right, and two-hand interactions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Operation to perform: 'start', 'stop', 'toggle', or 'status'",
            }
        },
        "required": ["action"],
    },
    "handler": gesture_control,
}
