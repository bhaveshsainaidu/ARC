"""
scripts/build_release.py — Automated Windows Executable Packager for GitHub Releases.

1. Cleans previous build artifacts.
2. Compiles ARC with PyInstaller using ARC.spec.
3. Packages models, actions, plugins, templates, and web dashboard assets.
4. Produces a production-grade 'dist/ARC-Windows-x64.zip' ready for GitHub Releases.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
RELEASE_DIR = DIST / "ARC"
ZIP_OUTPUT = DIST / "ARC-Windows-x64.zip"


def log(msg: str) -> None:
    print(f"\n[ARC Build] {msg}")


def clean() -> None:
    log("Cleaning previous build and distribution caches...")
    if BUILD.exists():
        shutil.rmtree(BUILD, ignore_errors=True)
    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)


def compile_exe() -> None:
    log("Compiling ARC via PyInstaller (ARC.spec)...")
    spec_path = ROOT / "ARC.spec"
    if not spec_path.exists():
        raise FileNotFoundError(f"Missing specification file: {spec_path}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_path),
    ]

    t0 = time.time()
    res = subprocess.run(cmd, cwd=str(ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller build failed with exit code {res.returncode}")
    log(f"Compilation finished in {time.time() - t0:.1f}s.")


def post_process_bundle() -> None:
    log("Verifying bundled distribution assets...")
    if not RELEASE_DIR.exists():
        raise FileNotFoundError(f"Expected release directory not found at: {RELEASE_DIR}")

    exe_file = RELEASE_DIR / "ARC.exe"
    if not exe_file.exists():
        raise FileNotFoundError(f"ARC.exe was not created in: {RELEASE_DIR}")

    # Ensure clean config directory with template (never bundle personal secret keys)
    cfg_dir = RELEASE_DIR / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    if (ROOT / "config" / "api_keys.json.template").exists():
        shutil.copy2(ROOT / "config" / "api_keys.json.template", cfg_dir / "api_keys.json.template")
    if (ROOT / "config" / "settings.json").exists():
        shutil.copy2(ROOT / "config" / "settings.json", cfg_dir / "settings.json")
    if (ROOT / "config" / "arc.ico").exists():
        shutil.copy2(ROOT / "config" / "arc.ico", cfg_dir / "arc.ico")

    # Remove any accidentally leaked private key files from the release folder
    private_key = cfg_dir / "api_keys.json"
    if private_key.exists():
        private_key.unlink(missing_ok=True)
    key_salt = cfg_dir / ".keyfile"
    if key_salt.exists():
        key_salt.unlink(missing_ok=True)

    # Ensure models are intact
    models_dir = RELEASE_DIR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    src_model = ROOT / "models" / "hand_landmarker.task"
    dst_model = models_dir / "hand_landmarker.task"
    if src_model.exists() and not dst_model.exists():
        shutil.copy2(src_model, dst_model)

    # Create empty runtime directories
    (RELEASE_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "memory").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "outputs").mkdir(parents=True, exist_ok=True)

    log(f"Bundle verified. Main executable: {exe_file} ({exe_file.stat().st_size / 1024 / 1024:.1f} MB)")


def create_release_zip() -> Path:
    log("Compressing standalone release into ZIP for GitHub Releases...")
    if ZIP_OUTPUT.exists():
        ZIP_OUTPUT.unlink()

    with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _, files in os.walk(RELEASE_DIR):
            for file in files:
                full_path = Path(root) / file
                rel_path = Path("ARC") / full_path.relative_to(RELEASE_DIR)
                zf.write(full_path, rel_path)

    zip_size_mb = ZIP_OUTPUT.stat().st_size / 1024 / 1024
    log(f"Release package generated successfully: {ZIP_OUTPUT} ({zip_size_mb:.1f} MB)")
    return ZIP_OUTPUT


def main() -> None:
    print("=" * 70)
    print("  ARC WINDOWS EXECUTABLE RELEASE BUILDER")
    print("=" * 70)
    clean()
    compile_exe()
    post_process_bundle()
    zip_path = create_release_zip()
    print("\n" + "=" * 70)
    print("  SUCCESS! Ready for GitHub Releases.")
    print(f"  Distribution Folder : {RELEASE_DIR}")
    print(f"  GitHub Release Asset: {zip_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
