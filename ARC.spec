# -*- mode: python ; coding: utf-8 -*-
"""
ARC.spec — PyInstaller Specification for ARC (Adaptive Real-Time Cognitive Agent).
Builds a production-ready Windows 64-bit executable with all 55+ actions, plugins,
MediaPipe models, FastAPI dashboard assets, and hardware drivers bundled.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
PROJECT_ROOT = Path.cwd()

# ── Dynamic Submodule Auto-Collection ──────────────────────────────────────────
action_modules = collect_submodules('actions')
plugin_modules = collect_submodules('plugins')
core_modules   = collect_submodules('core')
memory_modules = collect_submodules('memory')

hidden_imports = list(set(
    action_modules +
    plugin_modules +
    core_modules +
    memory_modules +
    [
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'google.genai',
        'fastapi',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'cv2',
        'mediapipe',
        'mss',
        'mss.windows',
        'sounddevice',
        'numpy',
        'cryptography',
        'cryptography.fernet',
        'psutil',
        'pyautogui',
        'pyperclip',
        'pygetwindow',
        'watchdog',
        'watchdog.observers',
        'watchdog.events',
        'win32evtlog',
        'win32evtlogutil',
        'win32con',
        'win32gui',
        'win32process',
        'win32api',
        'comtypes',
        'pycaw',
        'pypdf',
        'docx',
        'openpyxl',
        'pptx',
    ]
))

# ── Asset and Resource Datas ──────────────────────────────────────────────────
datas = [
    (str(PROJECT_ROOT / 'core' / 'prompt.txt'), 'core'),
    (str(PROJECT_ROOT / 'models' / 'hand_landmarker.task'), 'models'),
    (str(PROJECT_ROOT / 'dashboard' / 'static'), 'dashboard/static'),
    (str(PROJECT_ROOT / 'config' / 'arc.ico'), 'config'),
    (str(PROJECT_ROOT / 'config' / 'api_keys.json.template'), 'config'),
    (str(PROJECT_ROOT / 'config' / 'settings.json'), 'config'),
    (str(PROJECT_ROOT / 'actions'), 'actions'),
    (str(PROJECT_ROOT / 'plugins'), 'plugins'),
]

a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'scapy',       # excluded to eliminate 65MB memory bloat
        'matplotlib',
        'IPython',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ARC',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # Disabled UPX to avoid DLL false-positive antivirus triggers
    console=False,      # GUI app mode: no ugly black terminal prompt
    icon=str(PROJECT_ROOT / 'config' / 'arc.ico'),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ARC',
)
