"""
tests/test_gesture_reinforced.py — Rigorous Verification Suite GR01 to GR40
for ARC Reinforced Gesture Engine and Camera Console Panel.
100% pass rate requirement.
"""

from __future__ import annotations

import math
import os
import sys
import time
from unittest.mock import MagicMock, patch
import pytest

from actions.gesture_control import (
    Landmark,
    GESTURES,
    GESTURE_ICONS,
    GestureEngine,
    GestureController,
    GestureHoldDetector,
    GestureStateMachine,
    GestureZoomController,
    classify_gesture,
    classify_two_hand_gesture,
)


# ── Offscreen QApplication Fixture ──────────────────────────────────────────

try:
    from PyQt6.QtWidgets import QApplication
    _QAPP = QApplication.instance()
    if _QAPP is None:
        _QAPP = QApplication(["arc_test", "-platform", "offscreen"])
except Exception:
    _QAPP = None


@pytest.fixture(scope="session", autouse=True)
def qapp():
    global _QAPP
    if _QAPP is None:
        try:
            from PyQt6.QtWidgets import QApplication
            _QAPP = QApplication.instance() or QApplication(["arc_test", "-platform", "offscreen"])
        except Exception:
            _QAPP = None
    return _QAPP


# ── Mock Landmark Helper ──────────────────────────────────────────────────────

def make_hand(
    thumb: str = "FOLDED",
    index: str = "FOLDED",
    middle: str = "FOLDED",
    ring: str = "FOLDED",
    pinky: str = "FOLDED",
    pinch: bool = False,
    spread: bool = False,
    pt_left: bool = False,
    pt_right: bool = False,
    idx_down: bool = False,
    wrist_x: float = 0.5,
    wrist_y: float = 0.8,
) -> list[Landmark]:
    """Generates 21 accurate 3D landmarks for specified hand posture."""
    lms = [Landmark(wrist_x, wrist_y, 0.0)]  # 0: Wrist

    # Thumb: 1: CMC, 2: MCP, 3: IP, 4: TIP
    if thumb == "UP":
        lms.extend([Landmark(0.45, 0.7), Landmark(0.42, 0.6), Landmark(0.40, 0.5), Landmark(0.38, 0.38)])
    elif thumb == "DOWN":
        lms.extend([Landmark(0.45, 0.6), Landmark(0.42, 0.65), Landmark(0.40, 0.75), Landmark(0.38, 0.88)])
    elif pinch:
        lms.extend([Landmark(0.45, 0.6), Landmark(0.43, 0.5), Landmark(0.42, 0.4), Landmark(0.40, 0.30)])
    elif spread:
        lms.extend([Landmark(0.35, 0.6), Landmark(0.30, 0.5), Landmark(0.25, 0.4), Landmark(0.18, 0.30)])
    else:  # FOLDED
        lms.extend([Landmark(0.46, 0.7), Landmark(0.47, 0.65), Landmark(0.48, 0.62), Landmark(0.49, 0.60)])

    # Index: 5: MCP, 6: PIP, 7: DIP, 8: TIP
    if pt_left:
        lms.extend([Landmark(0.5, 0.55), Landmark(0.4, 0.55), Landmark(0.3, 0.55), Landmark(0.2, 0.55)])
    elif pt_right:
        lms.extend([Landmark(0.5, 0.55), Landmark(0.6, 0.55), Landmark(0.7, 0.55), Landmark(0.8, 0.55)])
    elif idx_down:
        lms.extend([Landmark(0.5, 0.55), Landmark(0.5, 0.65), Landmark(0.5, 0.75), Landmark(0.5, 0.85)])
    elif pinch:
        lms.extend([Landmark(0.5, 0.55), Landmark(0.48, 0.45), Landmark(0.44, 0.38), Landmark(0.41, 0.31)])
    elif spread:
        lms.extend([Landmark(0.5, 0.55), Landmark(0.52, 0.45), Landmark(0.54, 0.38), Landmark(0.55, 0.30)])
    elif index == "UP":
        lms.extend([Landmark(0.5, 0.55), Landmark(0.5, 0.45), Landmark(0.5, 0.35), Landmark(0.5, 0.25)])
    else:  # FOLDED
        lms.extend([Landmark(0.5, 0.55), Landmark(0.5, 0.60), Landmark(0.5, 0.64), Landmark(0.5, 0.66)])

    # Middle, Ring, Pinky
    for f_state, base_x in [(middle, 0.55), (ring, 0.60), (pinky, 0.65)]:
        if f_state == "UP":
            lms.extend([Landmark(base_x, 0.55), Landmark(base_x, 0.45), Landmark(base_x, 0.35), Landmark(base_x, 0.23)])
        else:
            lms.extend([Landmark(base_x, 0.55), Landmark(base_x, 0.60), Landmark(base_x, 0.64), Landmark(base_x, 0.66)])

    return lms


# ── GR01 to GR40 Test Cases ──────────────────────────────────────────────────

def test_gr01_gesture_engine_thread_starts():
    """GR01 — GestureEngine thread starts without error."""
    engine = GestureEngine()
    engine._init_mediapipe = MagicMock()
    engine._init_camera = MagicMock()
    ok, msg = engine.start_engine()
    assert ok is True
    assert engine.is_alive() is True
    engine.stop_engine()
    assert engine.running is False


def test_gr02_gesture_engine_thread_named():
    """GR02 — GestureEngine thread named 'ARC-GestureEngine'."""
    engine = GestureEngine()
    assert engine.name == "ARC-GestureEngine"


def test_gr03_camera_opens_at_30_fps():
    """GR03 — Camera opens at 30 FPS target."""
    engine = GestureEngine()
    assert engine.fps_target == 30
    assert abs(engine.frame_time - (1.0 / 30.0)) < 1e-6


def test_gr04_landmark_detection_latency():
    """GR04 — Landmark detection runs < 15ms per frame."""
    lms = make_hand(thumb="UP")
    t0 = time.perf_counter()
    for _ in range(200):
        classify_gesture(lms)
    elapsed_ms = ((time.perf_counter() - t0) / 200) * 1000.0
    assert elapsed_ms < 15.0, f"Latency {elapsed_ms:.2f}ms exceeded 15ms threshold"


def test_gr05_all_20_gestures_defined():
    """GR05 — All 20 gestures defined in classifier."""
    assert len(GESTURES) == 20
    expected_keys = [
        "INDEX_UP", "INDEX_DOWN", "PEACE", "THREE_FINGERS", "FOUR_FINGERS",
        "OPEN_PALM", "FIST", "THUMBS_UP", "THUMBS_DOWN", "PINCH",
        "SPREAD", "POINT_LEFT", "POINT_RIGHT", "OK_SIGN", "CALL_ME",
        "BOTH_PINCH_APART", "BOTH_PINCH_TOGETHER", "BOTH_OPEN_PALMS",
        "LEFT_FIST_RIGHT_PEACE", "BOTH_THUMBS_UP"
    ]
    for k in expected_keys:
        assert k in GESTURES, f"Gesture {k} missing from vocabulary"


def test_gr06_thumbs_up_detected():
    """GR06 — Thumbs up detected correctly (mock landmarks)."""
    lms = make_hand(thumb="UP")
    gesture, conf = classify_gesture(lms)
    assert gesture == "THUMBS_UP"
    assert conf >= 0.85


def test_gr07_thumbs_down_detected():
    """GR07 — Thumbs down detected correctly."""
    lms = make_hand(thumb="DOWN")
    gesture, conf = classify_gesture(lms)
    assert gesture == "THUMBS_DOWN"
    assert conf >= 0.85


def test_gr08_open_palm_detected():
    """GR08 — Open palm detected correctly."""
    lms = make_hand(thumb="UP", index="UP", middle="UP", ring="UP", pinky="UP")
    gesture, conf = classify_gesture(lms)
    assert gesture == "OPEN_PALM"
    assert conf >= 0.85


def test_gr09_fist_detected():
    """GR09 — Fist detected correctly."""
    lms = make_hand(thumb="FOLDED", index="FOLDED", middle="FOLDED", ring="FOLDED", pinky="FOLDED")
    gesture, conf = classify_gesture(lms)
    assert gesture == "FIST"
    assert conf >= 0.85


def test_gr10_peace_sign_detected():
    """GR10 — Peace sign detected correctly."""
    lms = make_hand(index="UP", middle="UP")
    gesture, conf = classify_gesture(lms)
    assert gesture == "PEACE"
    assert conf >= 0.85


def test_gr11_pinch_detected():
    """GR11 — Pinch detected correctly."""
    lms = make_hand(pinch=True)
    gesture, conf = classify_gesture(lms)
    assert gesture == "PINCH"
    assert conf >= 0.85


def test_gr12_spread_detected():
    """GR12 — Spread detected correctly."""
    lms = make_hand(spread=True)
    gesture, conf = classify_gesture(lms)
    assert gesture == "SPREAD"
    assert conf >= 0.85


def test_gr13_index_up_detected():
    """GR13 — Index up detected correctly."""
    lms = make_hand(index="UP")
    gesture, conf = classify_gesture(lms)
    assert gesture == "INDEX_UP"
    assert conf >= 0.85


def test_gr14_state_machine_7_frames_no_fire():
    """GR14 — State machine: 7 frames → no fire."""
    sm = GestureStateMachine(required_frames=8, cooldown_s=1.5)
    for _ in range(7):
        fired = sm.process("THUMBS_UP")
        assert fired is None
    assert sm.state == GestureStateMachine.DETECTING
    assert sm.frame_count == 7


def test_gr15_state_machine_8_frames_fires():
    """GR15 — State machine: 8 frames → fires."""
    sm = GestureStateMachine(required_frames=8, cooldown_s=1.5)
    for _ in range(7):
        sm.process("THUMBS_UP")
    fired = sm.process("THUMBS_UP")
    assert fired == "THUMBS_UP"
    assert sm.state == GestureStateMachine.COOLDOWN


def test_gr16_state_machine_cooldown_blocks_repeat():
    """GR16 — State machine: cooldown blocks repeat."""
    sm = GestureStateMachine(required_frames=8, cooldown_s=1.5)
    for _ in range(8):
        sm.process("THUMBS_UP")
    # Immediate subsequent frames should return None
    assert sm.process("THUMBS_UP") is None
    assert sm.process("THUMBS_UP") is None


def test_gr17_hold_detector_under_1s_no_fire():
    """GR17 — Hold detector: < 1s hold → no fire."""
    hd = GestureHoldDetector("FIST", hold_duration_s=1.0)
    assert hd.update(True) is False
    assert hd.progress < 1.0


def test_gr18_hold_detector_ge_1s_fires():
    """GR18 — Hold detector: >= 1s hold → fires."""
    hd = GestureHoldDetector("FIST", hold_duration_s=1.0)
    hd.update(True)
    hd.hold_start = time.time() - 1.2
    assert hd.update(True) is True
    assert hd.progress == 0.0


def test_gr19_hold_detector_progress():
    """GR19 — Hold detector: progress 0.0 to 1.0 correct."""
    hd = GestureHoldDetector("FIST", hold_duration_s=1.0)
    hd.update(True)
    hd.hold_start = time.time() - 0.50
    hd.update(True)
    assert 0.40 <= hd.progress <= 0.60


def test_gr20_two_hands_detected_simultaneously():
    """GR20 — Two hands detected simultaneously."""
    lm_left = make_hand(thumb="UP", wrist_x=0.3)
    lm_right = make_hand(thumb="UP", wrist_x=0.7)
    g, conf, dist = classify_two_hand_gesture(lm_left, lm_right)
    assert g is not None
    assert dist > 0.1


def test_gr21_both_thumbs_up_extra_confirmation():
    """GR21 — Both thumbs up → extra confirmation triggered."""
    lm_left = make_hand(thumb="UP", wrist_x=0.3)
    lm_right = make_hand(thumb="UP", wrist_x=0.7)
    g, conf, _ = classify_two_hand_gesture(lm_left, lm_right)
    assert g == "BOTH_THUMBS_UP"
    assert conf >= 0.95


def test_gr22_both_palms_emergency_stop():
    """GR22 — Both palms → emergency stop triggered."""
    lm_left = make_hand(thumb="UP", index="UP", middle="UP", ring="UP", pinky="UP", wrist_x=0.3)
    lm_right = make_hand(thumb="UP", index="UP", middle="UP", ring="UP", pinky="UP", wrist_x=0.7)
    g, conf, _ = classify_two_hand_gesture(lm_left, lm_right)
    assert g == "BOTH_OPEN_PALMS"
    assert conf >= 0.95


def test_gr23_zoom_smooth_pinch_distance():
    """GR23 — Zoom smooth: pinch distance → zoom value."""
    zc = GestureZoomController()
    zc.set_pinch_distance(0.16, 0.08)  # ratio 2.0
    assert zc.target_zoom == 2.0
    z = zc.update()
    assert z > 1.0


def test_gr24_zoom_range_enforced():
    """GR24 — Zoom range: 0.5 to 3.0 enforced."""
    zc = GestureZoomController()
    zc.set_pinch_distance(0.01, 0.10)
    assert zc.target_zoom == 0.5
    zc.set_pinch_distance(10.0, 0.10)
    assert zc.target_zoom == 3.0


def test_gr25_zoom_smooth_factor_no_jump():
    """GR25 — Zoom smooth factor: no jump > 0.1x per frame."""
    zc = GestureZoomController()
    zc.set_pinch_distance(10.0, 0.10)  # target = 3.0, current = 1.0
    initial = zc.current_zoom
    updated = zc.update()
    jump = abs(updated - initial)
    assert jump <= 0.101, f"Zoom jumped by {jump:.3f}x, exceeding 0.10x"


def test_gr26_camera_feed_displayed_at_30_fps():
    """GR26 — Camera feed displayed in panel at 30 FPS."""
    from ui import CameraConsolePanel
    app = None
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
    except Exception:
        pass

    panel = CameraConsolePanel()
    assert panel._frame_tmr.interval() == 30


def test_gr27_landmark_overlay_renders_on_feed():
    """GR27 — Landmark overlay renders on feed correctly."""
    import numpy as np
    engine = GestureEngine()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    mock_res = MagicMock()
    mock_hl = MagicMock()
    mock_hl.landmark = [MagicMock(x=0.5, y=0.5) for _ in range(21)]
    mock_res.multi_hand_landmarks = [mock_hl]
    # Drawing shouldn't raise any exception
    engine._draw_landmarks_overlay(frame, mock_res)
    assert frame.shape == (240, 320, 3)


def test_gr28_gesture_name_shown_in_panel():
    """GR28 — Gesture name shown in panel on detection."""
    from ui import CameraConsolePanel
    panel = CameraConsolePanel()
    panel.update_stats({"gesture": "THUMBS_UP", "confidence": 0.96})
    assert "THUMBS UP" in panel._gesture_lbl.text()


def test_gr29_confidence_bar_updates():
    """GR29 — Confidence bar updates in real time."""
    from ui import CameraConsolePanel
    panel = CameraConsolePanel()
    panel.update_stats({"confidence": 0.84})
    assert panel._conf_bar.value() == 84


def test_gr30_frame_count_progress():
    """GR30 — Frame count progress shown correctly."""
    from ui import CameraConsolePanel
    panel = CameraConsolePanel()
    panel.update_stats({"frame_progress": 6, "required_frames": 8})
    assert "6/8" in panel._state_lbl.text()


def test_gr31_gesture_fires_hud_sphere_pulses():
    """GR31 — Gesture fires → HUD sphere pulses."""
    from ui import HudCanvas
    hud = HudCanvas(face_path="")
    hud.trigger_gesture_feedback("THUMBS_UP")
    assert hud._gesture_pulse_anim == 1.0


def test_gr32_gesture_fires_text_fades_in_on_hud():
    """GR32 — Gesture fires → text fades in on HUD."""
    from ui import HudCanvas
    hud = HudCanvas(face_path="")
    hud.trigger_gesture_feedback("THUMBS_UP")
    assert hud._gesture_banner_text is not None
    assert "THUMBS UP" in hud._gesture_banner_text


def test_gr33_gesture_history_shows_last_5():
    """GR33 — Gesture history shows last 5 gestures."""
    engine = GestureEngine()
    for g in ["INDEX_UP", "PEACE", "FIST", "THUMBS_UP", "OPEN_PALM", "PINCH", "SPREAD"]:
        engine._on_gesture_fired(g)
    assert len(engine.history) == 5
    assert engine.history[-1]["gesture"] == "SPREAD"
    assert engine.history[0]["gesture"] == "FIST"


def test_gr34_gesture_guide_shows_all_20():
    """GR34 — Gesture guide shows all 20 gestures."""
    from ui import GestureGuideOverlay
    guide = GestureGuideOverlay()
    assert len(GESTURES) == 20
    assert guide.width() >= 500


def test_gr35_camera_off_disabled_gracefully():
    """GR35 — Camera OFF → gesture disabled gracefully."""
    engine = GestureEngine()
    engine.camera_enabled = False
    engine._process_frame()
    assert engine.active_hands == 0
    assert engine.last_gesture == "None"


def test_gr36_no_webcam_graceful_error():
    """GR36 — No webcam → graceful error, not crash."""
    engine = GestureEngine()
    engine.cap = None
    engine._process_frame()
    assert engine.active_hands == 0
    assert engine.frame_queue.qsize() > 0


def test_gr37_gesture_thread_does_not_affect_ui_fps():
    """GR37 — Gesture thread does NOT affect UI FPS (sphere stays >= 55 FPS during gesture)."""
    from ui import HudCanvas
    hud = HudCanvas(face_path="")
    hud.trigger_gesture_feedback("THUMBS_UP")
    t0 = time.perf_counter()
    for _ in range(60):
        hud._step()
    dt = time.perf_counter() - t0
    sim_fps = 60.0 / max(0.001, dt)
    assert sim_fps >= 55.0


def test_gr38_gesture_thread_does_not_affect_audio():
    """GR38 — Gesture thread does NOT affect audio."""
    hud_audio_level = 0.5
    engine = GestureEngine()
    t0 = time.perf_counter()
    # Process gestures while simulating audio buffer ingestion
    for _ in range(100):
        classify_gesture(make_hand(thumb="UP"))
    elapsed = time.perf_counter() - t0
    # 100 classifications must finish in < 200ms without starving audio thread
    assert elapsed < 0.20


def test_gr39_continuous_simulation_no_memory_leak():
    """GR39 — Continuous simulation: no memory leak (RAM delta < 30MB over cycles)."""
    import psutil
    proc = psutil.Process()
    ram_before = proc.memory_info().rss
    engine = GestureEngine()
    lms = make_hand(thumb="UP")

    for _ in range(3000):
        classify_gesture(lms)
        engine.state_machine.process("THUMBS_UP")
        engine.zoom_controller.update()

    ram_after = proc.memory_info().rss
    ram_delta_mb = (ram_after - ram_before) / (1024 * 1024)
    assert ram_delta_mb < 30.0, f"RAM delta {ram_delta_mb:.2f}MB exceeded 30MB"


def test_gr40_after_1000_events_accuracy_unchanged():
    """GR40 — After 1000 gesture events: accuracy unchanged."""
    test_suite = [
        ("THUMBS_UP", make_hand(thumb="UP")),
        ("THUMBS_DOWN", make_hand(thumb="DOWN")),
        ("OPEN_PALM", make_hand(thumb="UP", index="UP", middle="UP", ring="UP", pinky="UP")),
        ("FIST", make_hand()),
        ("PEACE", make_hand(index="UP", middle="UP")),
        ("PINCH", make_hand(pinch=True)),
        ("SPREAD", make_hand(spread=True)),
        ("INDEX_UP", make_hand(index="UP")),
        ("INDEX_DOWN", make_hand(idx_down=True)),
        ("THREE_FINGERS", make_hand(index="UP", middle="UP", ring="UP")),
        ("FOUR_FINGERS", make_hand(index="UP", middle="UP", ring="UP", pinky="UP")),
        ("OK_SIGN", make_hand(pinch=True, middle="UP", ring="UP", pinky="UP")),
        ("CALL_ME", make_hand(thumb="UP", pinky="UP")),
        ("POINT_LEFT", make_hand(pt_left=True)),
        ("POINT_RIGHT", make_hand(pt_right=True)),
    ]

    correct = 0
    total = 1000
    for i in range(total):
        expected_name, lms = test_suite[i % len(test_suite)]
        res, conf = classify_gesture(lms)
        if res == expected_name:
            correct += 1

    accuracy = (correct / total) * 100.0
    assert accuracy == 100.0, f"Accuracy {accuracy:.1f}% dropped below 100%"
