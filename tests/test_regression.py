"""
tests/test_regression.py — Master ARC Regression Test Suite v4.0.

Comprehensive end-to-end regression testing across:
  - Bandwidth Monitor & Adaptive WebSocket Telemetry
  - Track 2: Generative AI (Content Studio, Meeting Summarizer, Presentation Builder, Image Generator)
  - Track 3: Healthcare (Symptom Checker, Document Analyzer, Medication Manager, Health Monitor, Prior Auth)
  - Track 4: Ethical AI (Ethical Framework, Consent Manager, Transparency Report, Bias Detector, Data Sovereignty)
  - Cybersecurity & Windows Defender Full Control
  - Action Loader Completeness
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

# ── R01: Bandwidth Monitor ───────────────────────────────────────────────────
def test_r01_bandwidth_monitor():
    import core.bandwidth_monitor as bm
    state = bm.get_bandwidth_state()
    assert state in ("HIGH", "MEDIUM", "LOW", "CRITICAL")
    metrics = bm.get_metrics()
    assert "rtt_ms" in metrics
    assert "packet_loss" in metrics

    # Test forced state override
    bm.set_forced_state("LOW")
    assert bm.get_bandwidth_state() == "LOW"
    bm.set_forced_state(None)


# ── R02: Screen Mirror Adaptive Scaling ──────────────────────────────────────
def test_r02_screen_mirror_adaptive():
    from plugins.screen_mirror import _get_stream_params
    import core.bandwidth_monitor as bm

    bm.set_forced_state("CRITICAL")
    fps, q, w = _get_stream_params()
    assert fps <= 2
    assert q <= 30
    assert w <= 640

    bm.set_forced_state("HIGH")
    fps, q, w = _get_stream_params()
    assert fps >= 10
    assert q >= 70
    assert w >= 1200
    bm.set_forced_state(None)


# ── R03: Content Studio Generative AI ────────────────────────────────────────
def test_r03_content_studio():
    from actions.content_studio import content_studio
    res = content_studio({
        "content_type": "report",
        "topic": "Autonomous AI Swarms",
        "save_file": False,
    })
    assert "Strategic Report" in res or "Report" in res
    assert "Executive Summary" in res

    res_email = content_studio({
        "content_type": "email",
        "topic": "Quarterly Performance",
        "save_file": False,
    })
    assert "Subject:" in res_email


# ── R04: Meeting Summarizer ──────────────────────────────────────────────────
def test_r04_meeting_summarizer():
    from actions.meeting_summarizer import meeting_summarizer
    notes = (
        "Project Alignment Sync. "
        "Alice will deliver API integration by Thursday. "
        "Decided to approve budget for cloud migration. "
        "Next sprint starts next week."
    )
    res = meeting_summarizer({
        "meeting_text": notes,
        "meeting_title": "Cloud Strategy Sync",
        "save_to_notes": False,
        "create_reminders": False,
    })
    assert "Meeting minutes" in res.lower() or "summary" in res.lower()
    assert "Executive Summary" in res
    assert "Decisions" in res


# ── R05: Presentation Builder (.pptx) ────────────────────────────────────────
def test_r05_presentation_builder(tmp_path):
    from actions.presentation_builder import presentation_builder
    res = presentation_builder({
        "topic": "Enterprise Neural Systems",
        "slide_count": 4,
        "theme": "tech",
    })
    assert ".pptx" in res
    assert "Presentation deck created" in res


# ── R06: Image Generator (Visual Assets) ─────────────────────────────────────
def test_r06_image_generator():
    from actions.image_generator import image_generator
    res = image_generator({
        "prompt": "Deep space quantum processor core",
        "style": "schematic",
        "aspect_ratio": "16:9",
    })
    assert ".png" in res
    assert "Visual asset generated" in res


# ── R07: Symptom Checker (Red Flag & Triage) ─────────────────────────────────
def test_r07_symptom_checker():
    from actions.symptom_checker import symptom_checker

    # Critical Red Flag
    res_crit = symptom_checker({
        "symptoms": "Sudden severe chest pain radiating to jaw and arm with breathlessness",
        "severity": 10,
    })
    assert "CRITICAL RED FLAG WARNING" in res_crit
    assert "911" in res_crit
    assert "MEDICAL DISCLAIMER" in res_crit

    # Routine
    res_routine = symptom_checker({
        "symptoms": "Mild congestion and dry throat for 2 days",
        "severity": 2,
    })
    assert "Clinical Triage Assessment" in res_routine
    assert "MEDICAL DISCLAIMER" in res_routine


# ── R08: Medical Document Analyzer ───────────────────────────────────────────
def test_r08_medical_document_analyzer():
    from actions.medical_document_analyzer import medical_document_analyzer
    doc = (
        "Comprehensive Metabolic Panel:\n"
        "Glucose: 145 mg/dL (High)\n"
        "Cholesterol: 240 mg/dL\n"
        "Hemoglobin: 14.5 g/dL\n"
        "Rx: Atorvastatin 20mg daily PO"
    )
    res = medical_document_analyzer({"document_text": doc})
    assert "Biomarkers & Test Results" in res
    assert "Glucose" in res
    assert "HIGH" in res
    assert "MEDICAL DISCLAIMER" in res


# ── R09: Medication Manager & Interactions ───────────────────────────────────
def test_r09_medication_manager():
    from actions.medication_manager import medication_manager

    # Add medication
    res_add = medication_manager({
        "action": "add",
        "medication_name": "Warfarin",
        "dosage": "5mg",
        "schedule": "18:00",
    })
    assert "recorded" in res_add.lower() or "warfarin" in res_add.lower()
    assert "MEDICAL DISCLAIMER" in res_add

    # Check drug interaction
    res_check = medication_manager({
        "action": "check_interactions",
        "medication_name": "Aspirin",
    })
    assert "INTERACTION" in res_check
    assert "MEDICAL DISCLAIMER" in res_check


# ── R10: Health Monitor (Vitals & Alerts) ─────────────────────────────────────
def test_r10_health_monitor():
    from actions.health_monitor import health_monitor

    # Log hypertensive reading
    res_log = health_monitor({
        "action": "log",
        "metric": "blood_pressure",
        "value": "150/95",
    })
    assert "Logged" in res_log
    assert "Hypertension" in res_log
    assert "MEDICAL DISCLAIMER" in res_log

    # Summary
    res_sum = health_monitor({"action": "summary"})
    assert "Patient Vitals Trend" in res_sum
    assert "MEDICAL DISCLAIMER" in res_sum


# ── R11: Prior Authorization Agent ───────────────────────────────────────────
def test_r11_prior_auth_agent():
    from actions.prior_auth_agent import prior_auth_agent
    res = prior_auth_agent({
        "treatment_requested": "Dupixent 300mg",
        "diagnosis": "Severe Atopic Dermatitis",
        "icd10_code": "L20.9",
    })
    assert "AUTONOMOUS SUBMISSION PROHIBITED" in res
    assert "MEDICAL DISCLAIMER" in res


# ── R12: Ethical Framework Harm & Privacy Checks ─────────────────────────────
def test_r12_ethical_framework():
    from core.ethical_framework import (
        check_harm_prevention,
        check_privacy_boundary,
        is_action_permissible,
    )

    # Harm check
    safe, reason = check_harm_prevention("rm -rf /")
    assert not safe
    assert "prohibited" in reason.lower()

    safe_normal, _ = check_harm_prevention("echo 'Hello World'")
    assert safe_normal

    # Privacy boundary check
    clean, pii = check_privacy_boundary("User SSN is 000-12-3456")
    assert not clean
    assert any("SSN" in p for p in pii)

    # Permissibility
    perm, reason = is_action_permissible("computer_control", {"command": "format c:"})
    assert not perm
    assert "ETHICAL BLOCK" in reason


# ── R13: Consent Manager ─────────────────────────────────────────────────────
def test_r13_consent_manager():
    from actions.consent_manager import consent_manager
    res_list = consent_manager({"action": "list"})
    assert "Privacy & Permission Consent Matrix" in res_list

    res_grant = consent_manager({"action": "grant", "permission": "camera_access"})
    assert "GRANTED" in res_grant


# ── R14: Transparency Report ─────────────────────────────────────────────────
def test_r14_transparency_report():
    from actions.transparency_report import transparency_report
    res = transparency_report({"timeframe": "recent", "save_file": False})
    assert "Transparency & Explainability Report" in res
    assert "Audited Actions:" in res


# ── R15: Bias Detector ───────────────────────────────────────────────────────
def test_r15_bias_detector():
    from actions.bias_detector import bias_detector
    biased_text = "The female engineer was surprisingly calm, not hysterical like usual."
    res = bias_detector({"content": biased_text})
    assert "Bias Score:" in res
    assert "Gender Stereotyping" in res

    neutral_text = "The engineering team reviewed system latency benchmarks and approved the release."
    res_neutral = bias_detector({"content": neutral_text})
    assert "Objective & Neutral" in res_neutral


# ── R16: Sovereign Data Control ──────────────────────────────────────────────
def test_r16_data_sovereignty():
    from actions.data_sovereignty import data_sovereignty
    res_inv = data_sovereignty({"action": "enumerate"})
    assert "Sovereign Data Inventory" in res_inv

    res_exp = data_sovereignty({"action": "export"})
    assert "Archive Created Successfully" in res_exp


# ── R17: Windows Defender Control Full Integration ───────────────────────────
def test_r17_defender_control():
    from actions.defender_control import defender_control
    res = defender_control({"action": "status"})
    assert "Windows Defender Status" in res or "Protection" in res


# ── R18: Cyber Shield Telemetry ──────────────────────────────────────────────
def test_r18_cyber_shield():
    from actions.cyber_shield import cyber_shield
    res = cyber_shield({"action": "status"})
    assert "Shield" in res or "Security" in res or "Active" in res


# ── R19: Master Action Loader Completeness ───────────────────────────────────
def test_r19_action_loader_all_actions():
    from pathlib import Path
    from core.action_loader import discover_actions

    base = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(base, logger=lambda m: None)

    # Must discover all 53 actions
    assert len(registry._actions) >= 53

    # Ensure required tracks are loaded
    expected_actions = [
        "content_studio",
        "meeting_summarizer",
        "presentation_builder",
        "image_generator",
        "symptom_checker",
        "medical_document_analyzer",
        "medication_manager",
        "health_monitor",
        "prior_auth_agent",
        "consent_manager",
        "transparency_report",
        "bias_detector",
        "data_sovereignty",
        "defender_control",
        "cyber_shield",
        "device_manager",
        "team_intelligence",
        "vision_intelligence",
    ]
    for act in expected_actions:
        assert act in registry._actions, f"Action {act} missing from registry!"


# ── R20: Device Manager & Hardware Camera Selection ──────────────────────────
def test_r20_device_manager():
    from actions.device_manager import device_manager
    from core.device_service import get_active_camera_index, get_active_camera_name

    res = device_manager({"action": "list_cameras"})
    assert "Video Cameras" in res
    assert "ACTIVE" in res

    # Verify active camera name and index are valid
    idx = get_active_camera_index()
    assert isinstance(idx, int)
    name = get_active_camera_name()
    assert isinstance(name, str) and len(name) > 0


# ── R21: Team Intelligence & Personality Profiles ───────────────────────────
def test_r21_team_intelligence():
    from actions.team_intelligence import team_intelligence
    res_list = team_intelligence({"action": "list_team"})
    assert "ARC Team Profile Roster" in res_list
    assert "Bhavesh" in res_list

    res_get = team_intelligence({"action": "get_profile", "name": "Bhavesh"})
    assert "Role:" in res_get
    assert "Personality Traits:" in res_get


# ── R22: Vision Intelligence & Object Recognition ────────────────────────────
def test_r22_vision_intelligence():
    from actions.vision_intelligence import vision_intelligence
    res = vision_intelligence({"action": "detect_objects", "confidence_threshold": 0.3})
    assert "ARC Vision Intelligence" in res
    assert "Camera" in res or "OsmoAction4" in res


# ── R23: Medical Document Analyzer MRI Scan Analysis ─────────────────────────
def test_r23_medical_document_analyzer_mri(tmp_path):
    import cv2
    import numpy as np
    from actions.medical_document_analyzer import medical_document_analyzer

    # Generate synthetic brain MRI slice
    mri_file = tmp_path / "brain_mri_slice.png"
    img = np.zeros((256, 256), dtype=np.uint8)
    cv2.ellipse(img, (128, 128), (90, 110), 0, 0, 360, 160, -1)
    cv2.circle(img, (110, 120), 12, 40, -1) # Ventricle left
    cv2.circle(img, (146, 120), 12, 40, -1) # Ventricle right
    cv2.imwrite(str(mri_file), img)

    res = medical_document_analyzer({
        "document_path": str(mri_file),
        "document_type": "mri_scan"
    })
    assert "ARC Clinical Neuroimaging" in res or "Neuroimaging" in res
    assert "DISCLAIMER" in res


# ── R24: Discrete GPU VRAM & Hardware Acceleration ───────────────────────────
def test_r24_gpu_vram_acceleration():
    from core.gpu_accelerator import init_gpu_acceleration, get_vram_telemetry, get_gpu_accelerator
    import numpy as np

    status = init_gpu_acceleration()
    assert isinstance(status, dict)
    assert "vram_total_mb" in status
    assert "vram_used_mb" in status
    assert "backend" in status

    tel = get_vram_telemetry()
    assert "gpu_core_util_pct" in tel
    assert "vram_util_pct" in tel

    # Test GPU VRAM frame processor
    accel = get_gpu_accelerator()
    dummy = np.zeros((480, 640, 3), dtype=np.uint8)
    processed = accel.process_frame_gpu(dummy, target_size=(320, 240), to_rgb=True)
    assert processed.shape == (240, 320, 3)



