import base64
import hashlib
import json
import os
import platform
import sys
import uuid
from pathlib import Path
from threading import Lock

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"
_config_lock = Lock()


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def config_exists() -> bool:
    return CONFIG_FILE.exists()


# ── Transparent Fernet Encryption At Rest ────────────────────────────────────

def _get_key_file() -> Path:
    return CONFIG_DIR / ".keyfile"


def _get_machine_hw_id() -> bytes:
    parts = [
        str(uuid.getnode()),
        platform.node(),
        platform.machine(),
    ]
    return ":".join(parts).encode("utf-8")


def _get_fernet() -> Fernet:
    ensure_config_dir()
    key_file = _get_key_file()
    salt = b""
    if key_file.exists():
        try:
            salt = key_file.read_bytes()
        except Exception:
            salt = b""

    if not salt or len(salt) < 16:
        salt = os.urandom(16)
        try:
            key_file.write_bytes(salt)
        except Exception as e:
            print(f"[Security] [!] Could not write .keyfile: {e}")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    derived_key = base64.urlsafe_b64encode(kdf.derive(_get_machine_hw_id()))
    return Fernet(derived_key)


def _read_config() -> dict:
    """Transparently decrypt and read config from disk.
    If unencrypted plain JSON is detected, it is parsed and immediately re-saved encrypted."""
    with _config_lock:
        if not CONFIG_FILE.exists():
            return {}
        try:
            raw = CONFIG_FILE.read_bytes()
            if not raw.strip():
                return {}
            # 1. Attempt decryption with Fernet
            try:
                fernet = _get_fernet()
                decrypted = fernet.decrypt(raw)
                return json.loads(decrypted.decode("utf-8"))
            except Exception:
                # 2. Fallback: plain JSON (first run / migration)
                data = json.loads(raw.decode("utf-8"))
                # Transparently re-encrypt on disk
                try:
                    fernet = _get_fernet()
                    enc = fernet.encrypt(json.dumps(data, indent=2).encode("utf-8"))
                    CONFIG_FILE.write_bytes(enc)
                except Exception:
                    pass
                return data
        except Exception as e:
            print(f"[ERR] Failed to load api_keys.json: {e}")
            return {}


def _write_config(data: dict) -> None:
    ensure_config_dir()
    serialized = json.dumps(data, indent=4).encode("utf-8")
    encrypted = _get_fernet().encrypt(serialized)
    with _config_lock:
        CONFIG_FILE.write_bytes(encrypted)


def get_key(key: str, default: str = "") -> str:
    """Retrieve key value from encrypted config."""
    return _read_config().get(key, default)


def set_key(key: str, value: str) -> None:
    """Persist key value into encrypted config."""
    cfg = _read_config()
    cfg[key] = value
    _write_config(cfg)


def save_api_keys(gemini_api_key: str) -> None:
    data = _read_config()
    data["gemini_api_key"] = gemini_api_key.strip()
    _write_config(data)


def load_api_keys() -> dict:
    return _read_config()


def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")


def get_api_key(name: str = "gemini") -> str:
    """Retrieve API key by service name."""
    if name in ("gemini", "google"):
        return get_gemini_key() or get_key("gemini_api_key")
    return get_key(f"{name}_api_key") or get_key(name)


def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def get_assistant_name() -> str:
    """Return the configured assistant name, or 'Arc' if not set."""
    return load_api_keys().get("assistant_name", "Arc") or "Arc"


def get_user_name() -> str:
    """Return the configured user name for addressing, defaulting to 'Sir'."""
    val = load_api_keys().get("user_name")
    if val and str(val).strip():
        return str(val).strip()
    return "Sir"


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    data = _read_config()
    data["assistant_name"] = assistant_name.strip() or "Arc"
    data["user_name"] = user_name.strip()
    _write_config(data)


# ── Assistant voice ──────────────────────────────────────────────────────────
AVAILABLE_VOICES = ["Charon", "Puck", "Kore", "Fenrir", "Aoede"]
DEFAULT_VOICE    = "Charon"


def get_voice() -> str:
    """Return the configured Live voice, falling back to default."""
    v = load_api_keys().get("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE
    return v if v in AVAILABLE_VOICES else DEFAULT_VOICE


def save_voice(voice_name: str) -> None:
    """Persist the chosen Live voice."""
    data = _read_config()
    v = (voice_name or "").strip()
    data["voice_name"] = v if v in AVAILABLE_VOICES else DEFAULT_VOICE
    _write_config(data)


def get_wake_word_enabled() -> bool:
    """Whether local wake-word gating is on."""
    return load_api_keys().get("wake_word_enabled", False)


def save_wake_word_enabled(enabled: bool) -> None:
    data = _read_config()
    data["wake_word_enabled"] = bool(enabled)
    _write_config(data)


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


def save_brief_enabled(enabled: bool) -> None:
    data = _read_config()
    data["morning_brief_enabled"] = enabled
    _write_config(data)


# ── Audio devices ────────────────────────────────────────────────────────────

def _patch_config(**fields) -> None:
    data = _read_config()
    data.update(fields)
    _write_config(data)


def get_input_device() -> str:
    """Microphone device name, or '' for the system default."""
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    """Speaker device name, or '' for the system default."""
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


# ── Per-plugin settings ───────────────────────────────────────────────────────

def get_plugin_config(namespace: str) -> dict:
    """All stored values for a namespace."""
    cfg = load_api_keys().get("plugin_config")
    val = cfg.get(namespace) if isinstance(cfg, dict) else None
    return dict(val) if isinstance(val, dict) else {}


def get_plugin_setting(namespace: str, key: str, default=None):
    """A single value from a namespace, or `default` if unset."""
    return get_plugin_config(namespace).get(key, default)


def save_plugin_config(namespace: str, values: dict) -> None:
    """Merge `values` into a namespace's stored config."""
    data = _read_config()
    pc = data.get("plugin_config")
    if not isinstance(pc, dict):
        pc = {}
    cur = pc.get(namespace)
    if not isinstance(cur, dict):
        cur = {}
    cur.update(values)
    pc[namespace] = cur
    data["plugin_config"] = pc
    _write_config(data)


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    data = _read_config()
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    _write_config(data)


set_plugin_enabled = save_plugin_enabled


# ── Voice Interaction Settings ───────────────────────────────────────────────

def get_barge_in_sensitivity() -> str:
    """Interruption sensitivity: 'low', 'medium', or 'high'. Default: 'medium'."""
    val = (load_api_keys().get("barge_in_sensitivity", "medium") or "medium").lower()
    return val if val in ("low", "medium", "high") else "medium"


def save_barge_in_sensitivity(val: str) -> None:
    v = (val or "medium").strip().lower()
    if v not in ("low", "medium", "high"):
        v = "medium"
    _patch_config(barge_in_sensitivity=v)


def get_headset_mode() -> bool:
    """Whether user is on headphones."""
    return bool(load_api_keys().get("headset_mode", False))


def save_headset_mode(enabled: bool) -> None:
    _patch_config(headset_mode=bool(enabled))


def get_ptt_enabled() -> bool:
    """Whether Push-to-Talk is enabled as the voice interaction mode."""
    return bool(load_api_keys().get("push_to_talk_enabled", False))


def save_ptt_enabled(enabled: bool) -> None:
    _patch_config(push_to_talk_enabled=bool(enabled))


# ── Consent Settings ─────────────────────────────────────────────────────────

_CONSENTS_FILE = CONFIG_DIR / "consents.json"

_DEFAULT_CONSENTS = {
    "camera": True,
    "camera_access": True,
    "microphone": True,
    "microphone_continuous": True,
    "screen_recording": True,
    "screen": True,
    "biometric_data": True,
    "filesystem_write": True,
    "shell_execution": True,
    "shell": True,
    "remote_dashboard_control": True,
    "telemetry": False,
}


def get_consent(scope: str, default: bool = True) -> bool:
    """Retrieve user consent status for a specific capability scope."""
    s = (scope or "").lower().strip()
    norm = s.replace("_access", "").replace("_continuous", "").replace("_execution", "")
    data = dict(_DEFAULT_CONSENTS)
    if _CONSENTS_FILE.exists():
        try:
            stored = json.loads(_CONSENTS_FILE.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update(stored)
        except Exception:
            pass
    if s in data:
        return bool(data[s])
    if norm in data:
        return bool(data[norm])
    for k, v in data.items():
        if s in k or k in s:
            return bool(v)
    return default


def set_consent(scope: str, granted: bool) -> None:
    """Persist user consent status for a specific capability scope."""
    s = (scope or "").lower().strip()
    norm = s.replace("_access", "").replace("_continuous", "").replace("_execution", "")
    ensure_config_dir()
    data = dict(_DEFAULT_CONSENTS)
    if _CONSENTS_FILE.exists():
        try:
            stored = json.loads(_CONSENTS_FILE.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update(stored)
        except Exception:
            pass
    data[s] = bool(granted)
    data[norm] = bool(granted)
    _CONSENTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")