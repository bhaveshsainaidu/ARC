"""
core/emotion_detector.py — Voice Emotion & Tone Analysis via Librosa.

Analyzes raw speech PCM / numpy audio arrays to detect the user's emotional state:
- neutral: Balanced energy, standard pitch variation
- frustrated: High energy, strained / elevated pitch variance, sharp acoustic attacks
- excited: High energy, high pitch dynamic range, elevated speech rate
- tired: Low energy, low pitch variance, slow speech rate

Injects dynamic prompt tone adjustments into ARC system instructions.
"""

from __future__ import annotations

import numpy as np
from typing import Any, Optional


def analyze_voice_emotion(
    audio_data: bytes | np.ndarray,
    sample_rate: int = 16000,
) -> dict[str, Any]:
    """
    Analyze short audio buffer for speaker emotion.
    Returns:
        {
            "emotion": "neutral" | "frustrated" | "excited" | "tired",
            "confidence": float,
            "metrics": dict,
            "prompt_guidance": str,
        }
    """
    # 1. Convert to float32 numpy array
    if isinstance(audio_data, bytes):
        if len(audio_data) < 1600:  # < 0.05 seconds
            return _neutral_result("Audio buffer too short")
        # Assume int16 PCM
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
    elif isinstance(audio_data, np.ndarray):
        if audio_data.dtype == np.int16:
            audio_np = audio_data.astype(np.float32) / 32768.0
        else:
            audio_np = audio_data.astype(np.float32)
    else:
        return _neutral_result("Unsupported audio type")

    if audio_np.ndim > 1:
        audio_np = audio_np[:, 0]

    if len(audio_np) < int(sample_rate * 0.25):  # Need at least 250ms of audio
        return _neutral_result("Insufficient duration")

    # 2. Extract acoustic features using librosa or numpy
    try:
        import librosa

        # Energy / RMS
        rms_series = librosa.feature.rms(y=audio_np)[0]
        rms_mean = float(np.mean(rms_series))
        rms_max = float(np.max(rms_series)) if len(rms_series) > 0 else rms_mean

        # Zero-crossing rate
        zcr_series = librosa.feature.zero_crossing_rate(y=audio_np)[0]
        zcr_mean = float(np.mean(zcr_series))

        # Pitch estimation using YIN
        # Target speech range: 65 Hz to 450 Hz
        try:
            f0 = librosa.yin(audio_np, fmin=65, fmax=450, sr=sample_rate)
            valid_f0 = f0[~np.isnan(f0)]
            if len(valid_f0) > 4:
                pitch_mean = float(np.mean(valid_f0))
                pitch_std = float(np.std(valid_f0))
            else:
                pitch_mean = 150.0
                pitch_std = 15.0
        except Exception:
            pitch_mean = 150.0
            pitch_std = 15.0

    except Exception:
        # Fast pure-numpy fallback
        rms_mean = float(np.sqrt(np.mean(audio_np ** 2)))
        rms_max = float(np.max(np.abs(audio_np)))
        zero_crossings = np.sum(np.diff(np.sign(audio_np) != 0))
        zcr_mean = float(zero_crossings / max(1, len(audio_np)))
        pitch_mean = 150.0
        pitch_std = 15.0

    metrics = {
        "rms_mean": round(rms_mean, 4),
        "rms_max": round(rms_max, 4),
        "zcr": round(zcr_mean, 4),
        "pitch_mean": round(pitch_mean, 1),
        "pitch_std": round(pitch_std, 1),
    }

    # 3. Decision Heuristics
    emotion = "neutral"
    confidence = 0.70

    if rms_mean < 0.02 and pitch_std < 18.0:
        emotion = "tired"
        confidence = 0.75
    elif rms_mean > 0.08 and pitch_std > 45.0 and zcr_mean > 0.10:
        emotion = "excited"
        confidence = 0.82
    elif (rms_mean > 0.07 and pitch_std > 35.0 and zcr_mean > 0.12) or (rms_max > 0.35 and pitch_std > 30.0):
        emotion = "frustrated"
        confidence = 0.80

    guidance = _build_tone_guidance(emotion)

    return {
        "emotion": emotion,
        "confidence": confidence,
        "metrics": metrics,
        "prompt_guidance": guidance,
    }


def _build_tone_guidance(emotion: str) -> str:
    if emotion == "frustrated":
        return (
            "[EMOTION DETECTED: FRUSTRATED / STRESSED] "
            "The user's tone indicates frustration or tension. "
            "Be exceptionally calm, concise, and solution-focused. "
            "Do not apologize excessively, make excuses, or elaborate unprompted."
        )
    elif emotion == "excited":
        return (
            "[EMOTION DETECTED: ENTHUSIASTIC / ENERGETIC] "
            "The user sounds excited or enthusiastic. Match their positive, proactive energy."
        )
    elif emotion == "tired":
        return (
            "[EMOTION DETECTED: TIRED / LOW ENERGY] "
            "The user sounds fatigued. Keep responses gentle, quiet, warm, and brief."
        )
    return ""


def _neutral_result(reason: str = "") -> dict[str, Any]:
    return {
        "emotion": "neutral",
        "confidence": 1.0,
        "metrics": {"reason": reason},
        "prompt_guidance": "",
    }
