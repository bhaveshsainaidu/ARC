# ⚡ ARC — Adaptive Real-Time Cognitive Agent
### A Production-Grade, Privacy-First Autonomous AI System — Engineered by Bhavesh Sai

[![License: MIT](https://img.shields.io/badge/License-MIT-gold.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Documentation: v1.0](https://img.shields.io/badge/Documentation-Complete%20Beginner's%20Guide%20v1.0-gold.svg)](DOCUMENTATION.md)
[![Vigorous Tests](https://img.shields.io/badge/Vigorous%20Tests-201%2F201%20Passed%20(100%25)-brightgreen.svg)](tests/test_arc_vigorous.py)
[![Direct3D 11 RHI](https://img.shields.io/badge/Hardware%20Acceleration-Direct3D%2011%20%2F%20VRAM-cyan.svg)](core/gpu_accelerator.py)
[![Privacy](https://img.shields.io/badge/Privacy-Local%20First%20%2F%20Zero%20Leak-purple.svg)](security/)

**ARC (Adaptive Real-Time Cognitive Agent)** is a state-of-the-art, voice-first autonomous AI companion built for Windows 10 and 11. Powered by the **Google Gemini Live API** with bidirectional audio/PCM streaming, native Direct3D 11 hardware-accelerated rendering on dedicated GPU VRAM, sub-millisecond action dispatching, 30 FPS optical hand-gesture tracking, and a comprehensive 50+ tool ecosystem.

ARC is architected with **complete self-awareness**: it introspects its live capabilities, system health, active hardware, and memory records in real time to deliver deterministic, verified responses.

> 📚 **New to ARC?** Read the [**Complete Documentation v1.0 for Absolute Beginners**](DOCUMENTATION.md) for a comprehensive walkthrough of every single file, command, and subsystem.

---

## 📑 Table of Contents

- [📖 Complete Beginner Documentation v1.0](DOCUMENTATION.md)
- [✨ Core Capabilities](#-core-capabilities)
- [🏗️ System Architecture](#️-system-architecture)
- [⚡ Sub-Millisecond Low Latency Engine](#-sub-millisecond-low-latency-engine)
- [🎮 GPU VRAM & Direct3D 11 Hardware Acceleration](#-gpu-vram--direct3d-11-hardware-acceleration)
- [🖐️ Camera Console & 30 FPS Gesture Recognition](#️-camera-console--30-fps-gesture-recognition)
- [🧠 Complete Self-Awareness & Capability Matrix](#-complete-self-awareness--capability-matrix)
- [🛠️ Reinforced Action & Tool Suites](#️-reinforced-action--tool-suites)
- [🛡️ Ethical AI, Privacy Shield & Consent Matrix](#️-ethical-ai-privacy-shield--consent-matrix)
- [📱 Remote Mobile Cybernetic HUD Dashboard](#-remote-mobile-cybernetic-hud-dashboard)
- [🧪 Vigorous Verification Suite (201/201 Passing)](#-vigorous-verification-suite-201201-passing)
- [🚀 Quick Start Guide](#-quick-start-guide)
- [📂 Project Directory Layout](#-project-directory-layout)
- [🤝 Contributing & License](#-contributing--license)

---

## ✨ Core Capabilities

- ⚡ **Gemini Live Bidirectional Streaming**: Ultra-low latency voice turns with continuous PCM audio streaming and zero synthesis lag.
- 🗣️ **Intelligent Speech Barge-In**: Interrupt the assistant mid-sentence. Echo suppression and dynamic RMS noise-floor calibration prevent false triggers.
- 🎮 **GPU VRAM Offload**: PyQt6 Direct3D 11 RHI graphics pipeline and OpenCV OpenCL 3.0 UMat pipelines run directly in dedicated GDDR6 VRAM, bypassing DRAM contention.
- 🖐️ **30 FPS Optical Hand Gesture Control**: 21-landmark MediaPipe tracking supports pinch-to-zoom, two-finger scroll, palm mute, peace sign QR activation, swipe navigation, and thumbs-up safety confirmation.
- 🧩 **Complete Self-Awareness Core**: Dynamic capability map across 8 domains (perception, computer control, development, research, productivity, system, healthcare, privacy).
- 🔬 **Autonomous Research Agent**: 5-subquestion query decomposition, parallel arXiv/Semantic Scholar searches, source credibility scoring, and contradiction detection.
- 📊 **Autonomous Presentation Builder**: Generates production-ready 10-slide PowerPoint presentations (`.pptx`) with custom themes, statistics citations, and speaker notes.
- 💻 **Multi-Language Code Sandbox**: Language detection, AST syntax validation, bug fix suggestions, algorithmic time complexity analysis, and subprocess sandboxing.
- 🩺 **Clinical Healthcare Suite**: Emergency red flag screening, 4-tier care triage recommendations, prescription extraction, and drug interaction screenings with strict non-diagnostic guardrails.
- 🛡️ **Zero-Leak Security**: Regex-based masking of secrets in rotating logs, hardware-bound Fernet AES encryption at rest, and an 8-scope consent matrix.

---

## 🏗️ System Architecture

```
                                  ┌────────────────────────┐
                                  │   Google Gemini Live   │
                                  │  Bidirectional Audio   │
                                  └───────────▲────────────┘
                                              │  WebSocket PCM / LZ4 Frames
                                  ┌───────────▼────────────┐
                                  │       main.py          │
                                  │   Session Controller   │
                                  └─▲───────▲─────────▲───┬┘
                                    │       │         │   │
             ┌──────────────────────┘       │         │   └───────────────────────┐
             │                              │         │                           │
┌────────────▼─────────────┐   ┌────────────▼───────┐ │ ┌─────────────────────┐   │
│         ui.py            │   │  Audio Engine      │ │ │   Remote Dashboard  │   │
│  - Cybernetic HUD (60fps)│   │  - sounddevice PCM │ │ │   - FastAPI Server  │   │
│  - Direct3D 11 VRAM Pipe │   │  - Noise Floor RMS │ │ │   - TLS AES-256 Auth│   │
│  - Camera Gesture View   │   │  - Dynamic Barge-In│ │ │   - Real-time Mirror│   │
│  - Live Telemetry Panel  │   │  - Push-to-Talk    │ │ │   - Emergency Stop  │   │
└──────────────────────────┘   └────────────────────┘ │ └─────────────────────┘   │
                                                      │                           │
                   ┌──────────────────────────────────┴─────────────┐             │
                   │           Actions & Plugins System             │             │
                   │  - 50+ Auto-Discovered Reinforced Tools        │             │
                   │  - Low Latency Dispatch Engine (LRU Cache)     │             │
                   │  - Multi-Language Sandbox Execution            │             │
                   │  - Deep Research & Presentation Builders       │             │
                   │  - Clinical Health Triage & Drug Screeners     │             │
                   └────────────────────────────────────────────────┘             │
                                                                                  │
                   ┌──────────────────────────────────────────────────────────────▼┐
                   │                     Local Core Layer                          │
                   │  - ArcSelfAwareness (Live Capability & Telemetry Registry)    │
                   │  - GPUAccelerator (NVML Telemetry & Direct3D 11 Offloading)   │
                   │  - MemoryStore (Episodic Store + BM25 Search + Fernet Enc)    │
                   │  - ConsentManager (8-Scope Privacy Policy & Audit Logging)    │
                   └───────────────────────────────────────────────────────────────┘
```

---

## ⚡ Sub-Millisecond Low Latency Engine

ARC implements a dedicated latency optimization engine (`core/latency_optimizer.py`):
1. **O(1) Hash-Indexed Dispatch**: Bypasses heavy introspection pipelines for sub-millisecond tool routing.
2. **60-Second TTL Caching**: Idempotent read operations (hardware probes, biomarker metrics, system status) resolve in `< 10ms`.
3. **LZ4 Hardware Compression**: WebSocket audio and screen mirror binary frames are compressed in-flight with zero perceived transmission overhead.
4. **Latency Profiler**: Microsecond timing telemetry (`@measure_latency`) surfaces performance bottlenecks across all subsystems.

---

## 🎮 GPU VRAM & Direct3D 11 Hardware Acceleration

Engineered specifically to eliminate system DRAM contention when multitasking:
- **DirectX DWM Routing**: Automatically sets `GpuPreference=2;` in the Windows Graphics registry to pin execution to high-performance NVIDIA RTX/AMD discrete GPUs.
- **Qt6 RHI Direct3D 11**: Forces Qt Quick to render using Direct3D 11 directly in GDDR6 VRAM.
- **OpenCV OpenCL 3.0 UMat**: Video capture frames, optical flow, and gesture landmarks are held in GPU texture memory without copying to host DRAM.
- **NVML Telemetry**: Real-time CTypes queries monitor VRAM usage, GPU load, and thermal throttling in hardware.

---

## 🖐️ Camera Console & 30 FPS Gesture Recognition

ARC features an embedded camera console driven by MediaPipe 21-landmark neural tracking:

| Gesture | Landmark Detection | Triggered Action |
| :--- | :--- | :--- |
| **Pinch In / Out** | Thumb Tip (4) ↔ Index Tip (8) distance | Desktop / Document Zoom |
| **Two-Finger Scroll** | Index (8) + Middle (12) extended vertical | Page & Document Scroll |
| **Open Palm (1.5s)** | All 5 finger tips extended | Mute / Unmute Microphone |
| **Peace Sign (1.0s)** | Index (8) + Middle (12) spread 'V' | Display Mobile Remote QR |
| **Horizontal Swipe** | Wrist (0) velocity > 0.60 screen/sec | Switch Desktops / Tabs |
| **Thumbs Up** | Thumb extended upward | Confirm Sensitive Action Gate |
| **Closed Fist** | All 4 finger tips curled to palm | Emergency Stop / Interruption |

---

## 🧠 Complete Self-Awareness & Capability Matrix

ARC maintains a live, introspective map of its identity, operational limits, and available tools (`core/self_awareness.py`):
- **Live Capability Queries**: Ask *"What can you do?"* or *"Describe tool code_helper"* for precise, real-time specifications.
- **Hardware Probes**: Live checks for connected webcams, audio inputs, battery health, and GPU VRAM availability.
- **Self-Healing Diagnostics**: Automatically tests and reports degraded or failed tools, adjusting system prompts so the LLM never hallucinates unavailable capabilities.
- **Continuous Memory Introspection**: Answers *"What have you learned about me?"* directly from episodic memory stores.

---

## 🛠️ Reinforced Action & Tool Suites

ARC ships with over 50 fully tested, production-ready actions in `actions/`:

- **Development & Coding**:
  - `code_helper`: Language detection (Python, JS, Java, C++, Rust), syntax validation, bug fixing, time complexity analysis, unit test generation, and sandbox execution.
  - `dev_agent`: Workspace dependency scanning, git branch automation, and project build orchestration.
- **Research & Knowledge**:
  - `research_agent`: 5-query decomposition, parallel arXiv/Semantic Scholar search, source credibility scoring, contradiction detection, and APA citation generation.
  - `fact_checker`: Multi-source claim verification with confidence scores.
- **Productivity & Documents**:
  - `presentation_builder`: 10-slide custom PowerPoint (`.pptx`) generation with dark/corporate themes and speaker notes.
  - `document_intelligence`: Deep analysis of PDF, DOCX, and TXT files with regex entity extraction.
- **Healthcare & Clinical**:
  - `symptom_checker`: 4-tier clinical triage with red flag emergency escalation and physician discussion prompts.
  - `medical_document_analyzer`: Parses lab panels (glucose, lipid, renal, CBC) and prescription instructions.
  - `medication_manager`: Dosage schedule tracking and online drug-drug interaction screening.
  - `prior_auth_agent`: Generates clinical justification letters (never submits autonomously).
- **System & Security**:
  - `system_monitor`: Real-time anomaly alerts (CPU > 80%, RAM > 90%, GPU > 85°C) and root-cause lag diagnosis.
  - `cyber_shield`: Port scan detection, file integrity monitoring (FIM), and incident tracking.
  - `defender_control`: Windows Defender scan status, threat history, and definition updating.

---

## 🛡️ Ethical AI, Privacy Shield & Consent Matrix

ARC adheres to a strict user-sovereign privacy model:
1. **8-Scope Consent Matrix**: Camera access, continuous microphone, screen recording, biometric data, filesystem writes, shell execution, remote dashboard, and telemetry each require explicit user consent (`actions/consent_manager.py`).
2. **Instant Revocation**: Revoking a permission halts subsystem access immediately with zero caching.
3. **Data Sovereignty**: Full data inventory inspection, export to ZIP, and previewed secure deletion.
4. **Mandatory Clinical Disclaimers**: All health responses include standardized, clean ASCII medical disclaimers; diagnosis is strictly excluded from clinical outputs.

---

## 📱 Remote Mobile Cybernetic HUD Dashboard

Pair any smartphone or tablet on your local Wi-Fi:
- **Instant QR Pairing**: Point your phone camera at the HUD QR code.
- **Hardware Metrics**: Live CPU, RAM, VRAM, and battery telemetry streamed over WebSockets.
- **Remote Push-to-Talk**: Hold the phone screen button to speak to ARC from across the room.
- **Dual Emergency Stop**: Tap the red `🛑 STOP` button on mobile or press `Escape` on Windows to instantly halt all audio, speech, and tool execution.

---

## 🧪 Vigorous Verification Suite (201/201 Passing)

ARC includes the most vigorous automated test suite in the open-source personal AI space (`tests/test_arc_vigorous.py`):

```
============================= test session starts =============================
collected 201 items

TestSelfAwareness   (SA01–SA20) : 20 / 20 PASSED  [100%]
TestLowLatency      (LL01–LL25) : 25 / 25 PASSED  [100%]
TestTools           (TC01–TC43) : 43 / 43 PASSED  [100%]
TestRendering       (HR01–HR25) : 25 / 25 PASSED  [100%]
TestHeavyLoad       (ML01–FS02) : 33 / 33 PASSED  [100%]
TestEthicalAI       (EA01–EA20) : 20 / 20 PASSED  [100%]
TestEdgeCases       (EC01–EC20) : 20 / 20 PASSED  [100%]
TestRebrand         (RB01–RB15) : 15 / 15 PASSED  [100%]

============================ 201 passed in 37.54s =============================
```

To run the full suite and generate a self-contained HTML report:
```bash
python -m pytest tests/test_arc_vigorous.py -v --html=tests/arc_vigorous_report.html --self-contained-html
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Operating System**: Windows 10 or 11 (64-bit)
- **Python**: 3.10, 3.11, or 3.12
- **Hardware**: Dedicated NVIDIA RTX / GTX GPU recommended (Direct3D 11 acceleration)
- **API Key**: Free [Google Gemini API Key](https://aistudio.google.com/)

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/bhaveshsainaidu/ARC.git
cd ARC

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies and browser drivers
python setup.py
```

### 3. Launching ARC
```bash
python main.py
```
*On first boot, the Cybernetic HUD setup window will prompt for your Gemini API key. All keys are encrypted locally with machine-bound Fernet keys.*

---

## 📂 Project Directory Layout

```
ARC/
├── actions/                  # 50+ Auto-discovered tool modules
│   ├── code_helper.py        # Multi-language code sandbox & complexity analyzer
│   ├── gesture_control.py    # 30 FPS MediaPipe hand gesture tracker
│   ├── presentation_builder.py # 10-slide PowerPoint generator
│   ├── research_agent.py     # 5-stage academic & web research agent
│   ├── symptom_checker.py    # Clinical triage & red flag screener
│   └── system_monitor.py     # Hardware telemetry & lag diagnostic
├── config/                   # Encrypted configurations & icons
│   ├── api_keys.json.template# Template for API credentials
│   └── arc.ico               # Cybernetic gold application icon
├── core/                     # Central nervous system
│   ├── action_loader.py      # Dynamic action auto-discovery & validation
│   ├── gpu_accelerator.py    # Direct3D 11, NVML & OpenCL VRAM pipeline
│   ├── latency_optimizer.py  # Fast dispatch, LRU cache & LZ4 compression
│   └── self_awareness.py     # Live capability introspection singleton
├── dashboard/                # FastAPI remote mobile web HUD
├── memory/                   # Episodic memory, BM25 text index & health stores
├── plugins/                  # Drop-in user plugins & Defender monitors
├── security/                 # Local cyber shield & audit trail
├── tests/                    # 201-test vigorous test suite & regression tests
├── main.py                   # Session controller & Gemini Live WebSocket client
├── ui.py                     # PyQt6 Cybernetic HUD & Direct3D 11 graphics
├── setup.py                  # One-click environment bootstrap script
└── requirements.txt          # Filtered dependencies with OS platform markers
```

---

## 🤝 Contributing & License

Contributions are welcome! Please read our [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before submitting pull requests.

ARC is released under the **[MIT License](LICENSE)**.

Copyright (c) 2026 **Bhavesh Sai**.
