"""
actions/gesture_control.py — ARC Camera Hand Gesture Recognition & Control.

Runs a background thread monitoring webcam feed with MediaPipe (21 landmarks)
to recognize system control gestures:
1. Zoom in/out (pinch thumb 4 + index 8 distance)
2. Scroll up/down (two fingers 8 & 12 extended, vertical motion)
3. Mute/unmute (open palm held 1.5s)
4. Trigger QR code (V / peace sign held 1.0s -> player.open_remote())
5. Swipe left/right (rapid horizontal motion -> switch virtual desktop / tabs)
6. Thumbs up (confirm destructive action / confirm gate -> core.confirm.resolve(True))
7. Fist (cancel action / interrupt -> core.confirm.resolve(False) + player.interrupt())

Adaptive framerate:
- 30 FPS active tracking
- 10 FPS standby after 5s of no hands detected
- Toggles HUD "GESTURE ACTIVE" pill via player.set_gesture_active(True/False)
"""

from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path
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


class GestureController:
    """Manages the background gesture recognition thread and state machine."""

    _instance: Optional["GestureController"] = None
    _lock = threading.Lock()

    def __init__(self, player=None):
        self.player = player
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_hand_time = time.monotonic()
        self._fps = 30.0
        self._last_gesture = "None"
        self._palm_start: Optional[float] = None
        self._v_sign_start: Optional[float] = None
        self._last_scroll_y: Optional[float] = None
        self._last_pinch_dist: Optional[float] = None
        self._prev_wrist_x: Optional[float] = None
        self._prev_wrist_time: float = 0.0
        self._cooldowns: dict[str, float] = {}
        self.on_gesture_callback: Optional[Callable[[str], None]] = None
        self.on_frame_callback: Optional[Callable[[bytes], None]] = None

    @classmethod
    def get_instance(cls, player=None) -> "GestureController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(player)
            elif player is not None:
                cls._instance.player = player
            return cls._instance

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> Tuple[bool, str]:
        if self.is_running():
            return True, "Gesture control is already active."
        if not _CV2_AVAILABLE:
            return False, "OpenCV (cv2) is not installed."

        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="ArcGestureThread")
        self._thread.start()

        self._notify_hud(True, "Gesture Tracking Active")
        return True, "Gesture control active at 30 FPS. Monitoring webcam for hand gestures."

    def stop(self) -> Tuple[bool, str]:
        if not self._running:
            self._notify_hud(False, "None")
            return True, "Gesture control is not running."

        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._notify_hud(False, "None")
        return True, "Gesture control stopped."

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

    def _trigger_cooldown(self, action: str, seconds: float = 1.0) -> bool:
        now = time.monotonic()
        last = self._cooldowns.get(action, 0.0)
        if now - last < seconds:
            return False
        self._cooldowns[action] = now
        return True

    # ── Gesture Actions ──────────────────────────────────────────────────────────

    def _action_zoom(self, delta: float) -> None:
        if not _PYAUTOGUI or not self._trigger_cooldown("zoom", 0.15):
            return
        if delta > 0.03:
            pyautogui.hotkey("ctrl", "+")
            self._last_gesture = "Zoom In"
        elif delta < -0.03:
            pyautogui.hotkey("ctrl", "-")
            self._last_gesture = "Zoom Out"

    def _action_scroll(self, dy: float) -> None:
        if not _PYAUTOGUI or not self._trigger_cooldown("scroll", 0.08):
            return
        if dy < -0.015:
            pyautogui.scroll(120)
            self._last_gesture = "Scroll Up"
        elif dy > 0.015:
            pyautogui.scroll(-120)
            self._last_gesture = "Scroll Down"

    def _action_mute_toggle(self) -> None:
        if not self._trigger_cooldown("mute", 2.0):
            return
        self._last_gesture = "Mute / Unmute"
        try:
            if self.player and hasattr(self.player, "ui") and hasattr(self.player.ui, "_win"):
                win = self.player.ui._win
                if hasattr(win, "_toggle_mute"):
                    win._toggle_mute()
                    return
            if _PYAUTOGUI:
                pyautogui.press("volumemute")
        except Exception:
            pass

    def _action_open_remote(self) -> None:
        if not self._trigger_cooldown("remote", 3.0):
            return
        self._last_gesture = "Open Remote QR"
        try:
            if self.player and hasattr(self.player, "open_remote"):
                self.player.open_remote()
            elif self.player and hasattr(self.player, "ui") and hasattr(self.player.ui, "open_remote"):
                self.player.ui.open_remote()
        except Exception:
            pass

    def _action_swipe(self, direction: str) -> None:
        if not _PYAUTOGUI or not self._trigger_cooldown("swipe", 1.0):
            return
        self._last_gesture = f"Swipe {direction.capitalize()}"
        if direction == "left":
            pyautogui.hotkey("ctrl", "win", "left")
        else:
            pyautogui.hotkey("ctrl", "win", "right")

    def _action_thumbs_up(self) -> None:
        if not self._trigger_cooldown("confirm", 2.5):
            return
        self._last_gesture = "Thumbs Up (Confirm Gate)"
        try:
            from core.confirm import resolve
            resolve(True)
        except Exception:
            pass

    def _action_fist(self) -> None:
        if not self._trigger_cooldown("cancel", 1.5):
            return
        self._last_gesture = "Fist (Cancel / Interrupt)"
        try:
            from core.confirm import resolve
            resolve(False)
        except Exception:
            pass
        try:
            if self.player and hasattr(self.player, "interrupt"):
                self.player.interrupt()
            elif self.player and hasattr(self.player, "on_interrupt"):
                if callable(self.player.on_interrupt):
                    self.player.on_interrupt()
        except Exception:
            pass

    # ── Landmark Analysis ────────────────────────────────────────────────────────

    def _process_landmarks(self, lm: list[Any], now: float) -> None:
        """
        lm is a list of 21 landmarks with .x, .y, .z attributes.
        0: Wrist
        4: Thumb tip, 3: IP, 2: MCP
        8: Index tip, 6: PIP, 5: MCP
        12: Middle tip, 10: PIP, 9: MCP
        16: Ring tip, 14: PIP, 13: MCP
        20: Pinky tip, 18: PIP, 17: MCP
        """
        self._last_hand_time = now

        wrist = lm[0]
        thumb_tip, thumb_mcp = lm[4], lm[2]
        index_tip, index_pip = lm[8], lm[6]
        mid_tip, mid_pip = lm[12], lm[10]
        ring_tip, ring_pip = lm[16], lm[14]
        pinky_tip, pinky_pip = lm[20], lm[18]

        # Finger extended flags (tip higher than pip in image coordinates where y=0 is top)
        index_ext = index_tip.y < index_pip.y
        mid_ext = mid_tip.y < mid_pip.y
        ring_ext = ring_tip.y < ring_pip.y
        pinky_ext = pinky_tip.y < pinky_pip.y
        thumb_up = thumb_tip.y < thumb_mcp.y and thumb_tip.y < index_pip.y

        # Distance function
        def dist(p1, p2):
            return math.hypot(p1.x - p2.x, p1.y - p2.y)

        # 1. Thumbs Up: Thumb pointing upward, other 4 fingers curled
        if thumb_up and not index_ext and not mid_ext and not ring_ext and not pinky_ext:
            self._action_thumbs_up()
            return

        # 2. Fist: All 4 main fingers folded + thumb folded across
        fingers_folded = (not index_ext) and (not mid_ext) and (not ring_ext) and (not pinky_ext)
        if fingers_folded and dist(thumb_tip, index_pip) < 0.12:
            self._action_fist()
            return

        # 3. Mute/Unmute: Open Palm (all 5 fingers extended) held for 1.5s
        all_extended = index_ext and mid_ext and ring_ext and pinky_ext and (thumb_tip.y < thumb_mcp.y or dist(thumb_tip, wrist) > 0.25)
        if all_extended:
            if self._palm_start is None:
                self._palm_start = now
            elif now - self._palm_start >= 1.5:
                self._action_mute_toggle()
                self._palm_start = None
        else:
            self._palm_start = None

        # 4. Trigger QR: Peace / V-sign (Index & Middle extended, Ring & Pinky folded) held for 1.0s
        v_sign = index_ext and mid_ext and (not ring_ext) and (not pinky_ext)
        if v_sign:
            if self._v_sign_start is None:
                self._v_sign_start = now
            elif now - self._v_sign_start >= 1.0:
                self._action_open_remote()
                self._v_sign_start = None
        else:
            self._v_sign_start = None

        # 5. Scroll: Two fingers extended (Index & Middle), tracking vertical motion
        if v_sign:
            avg_y = (index_tip.y + mid_tip.y) / 2.0
            if self._last_scroll_y is not None:
                dy = avg_y - self._last_scroll_y
                if abs(dy) > 0.012:
                    self._action_scroll(dy)
            self._last_scroll_y = avg_y
        else:
            self._last_scroll_y = None

        # 6. Pinch Zoom: Thumb tip and Index tip distance tracking
        pinch_distance = dist(thumb_tip, index_tip)
        if not ring_ext and not pinky_ext:
            if self._last_pinch_dist is not None:
                ddist = pinch_distance - self._last_pinch_dist
                if abs(ddist) > 0.025:
                    self._action_zoom(ddist)
            self._last_pinch_dist = pinch_distance
        else:
            self._last_pinch_dist = None

        # 7. Rapid Swipe Left / Right (wrist horizontal displacement)
        if self._prev_wrist_x is not None:
            dt = now - self._prev_wrist_time
            if 0.02 <= dt <= 0.35:
                dx = wrist.x - self._prev_wrist_x
                vx = dx / dt
                if vx < -1.8:
                    self._action_swipe("left")
                    self._prev_wrist_x = None
                    return
                elif vx > 1.8:
                    self._action_swipe("right")
                    self._prev_wrist_x = None
                    return
        self._prev_wrist_x = wrist.x
        self._prev_wrist_time = now

    # ── Background Worker Loop ───────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        mp_drawing = None

        try:
            import mediapipe as mp
            if hasattr(mp, "solutions"):
                if hasattr(mp.solutions, "hands"):
                    mp_hands = mp.solutions.hands
                    hands_detector = mp_hands.Hands(
                        static_image_mode=False,
                        max_num_hands=1,
                        min_detection_confidence=0.6,
                        min_tracking_confidence=0.5,
                    )
                if hasattr(mp.solutions, "drawing_utils"):
                    mp_drawing = mp.solutions.drawing_utils
        except Exception as e:
            print(f"[GestureControl] MediaPipe initialization note: {e}")

        try:
            from core.device_service import get_active_camera_index
            cam_idx = get_active_camera_index()
            backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened() and backend != cv2.CAP_ANY:
                cap = cv2.VideoCapture(cam_idx)
            if not cap.isOpened():
                print(f"[GestureControl] Webcam {cam_idx} could not be opened. Running in idle state.")
        except Exception as e:
            print(f"[GestureControl] VideoCapture error: {e}")

        while self._running:
            now = time.monotonic()

            # Adaptive FPS: drop to 10 FPS if no hands seen in 5 seconds
            idle = (now - self._last_hand_time) > 5.0
            target_interval = 0.10 if idle else (1.0 / 30.0)
            loop_start = time.monotonic()

            if cap is not None and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    try:
                        from core.gpu_accelerator import get_gpu_accelerator
                        rgb_frame = get_gpu_accelerator().process_frame_gpu(frame, to_rgb=True)
                    except Exception:
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    if hands_detector is not None:
                        try:
                            results = hands_detector.process(rgb_frame)
                            if results and results.multi_hand_landmarks:
                                self._process_landmarks(results.multi_hand_landmarks[0].landmark, now)
                                # Draw futuristic HUD landmarks on frame
                                if mp_drawing is not None and mp_hands is not None:
                                    try:
                                        mp_drawing.draw_landmarks(
                                            frame,
                                            results.multi_hand_landmarks[0],
                                            mp_hands.HAND_CONNECTIONS,
                                            mp_drawing.DrawingSpec(color=(0, 212, 255), thickness=2, circle_radius=2),
                                            mp_drawing.DrawingSpec(color=(255, 215, 0), thickness=2)
                                        )
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                    # Stream annotated frame to UI console if requested
                    if self.on_frame_callback:
                        try:
                            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                            self.on_frame_callback(buf.tobytes())
                        except Exception:
                            pass

            elapsed = time.monotonic() - loop_start
            sleep_time = target_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        if hands_detector is not None:
            try:
                hands_detector.close()
            except Exception:
                pass
        if cap is not None:
            try:
                cap.release()
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
            "Recognized gestures: Zoom (pinch), Scroll (2-fingers), Mute (open palm 1.5s), "
            "Remote QR (V-sign 1.0s), Virtual Desktop (swipe), Confirm (thumbs up), Cancel (fist)."
        )
    return f"Unknown action '{action}'. Options: start, stop, toggle, status."


TOOL = {
    "name": "gesture_control",
    "description": (
        "Start, stop, or query camera-based hand gesture control. Recognizes zoom in/out (pinch), "
        "scroll up/down (two fingers), mute (open palm held 1.5s), open remote QR (peace sign held 1.0s), "
        "switch desktop (horizontal swipe), confirm destructive action (thumbs up), and cancel/interrupt (fist)."
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
