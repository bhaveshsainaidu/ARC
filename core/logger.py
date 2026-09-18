"""
core/logger.py — Structured, Privacy-Preserving Logger for ARC.

Provides categorized logging (AUDIO, GEMINI, TOOLS, DASHBOARD, SYSTEM, ERROR)
with automatic secret redaction, file rotation, and optional UI callbacks.
Guarantees that API keys, tokens, and personal memory contents are NEVER
leaked into logs or terminal output.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

_RE_GEMINI_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{35}")
_RE_BEARER_TOKEN = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{16,}", re.IGNORECASE)
_RE_BASE64_LONG = re.compile(r"(?:[A-Za-z0-9+/]{80,}={0,2})")

def sanitize_message(msg: str) -> str:
    """Mask any private API keys, bearer tokens, or runaway base64 payloads."""
    if not isinstance(msg, str):
        msg = str(msg)
    msg = _RE_GEMINI_KEY.sub("[REDACTED_API_KEY]", msg)
    msg = _RE_BEARER_TOKEN.sub("Bearer [REDACTED_TOKEN]", msg)
    if len(msg) > 500:
        # Check for embedded base64 blobs
        msg = _RE_BASE64_LONG.sub("[BASE64_DATA_TRUNCATED]", msg)
    return msg


class SensitiveDataFilter(logging.Filter):
    """Logging filter that sanitizes record messages before output."""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_message(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: (sanitize_message(v) if isinstance(v, str) else v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(sanitize_message(v) if isinstance(v, str) else v for v in record.args)
        return True


class ArcLogger:
    """Singleton structured logger for the ARC agent."""
    _instance: Optional[ArcLogger] = None
    _lock = threading.Lock()

    def __init__(self, log_dir: Optional[Path] = None):
        if log_dir is None:
            if getattr(sys, "frozen", False):
                base = Path(sys.executable).parent
            else:
                base = Path(__file__).resolve().parent.parent
            log_dir = base / "logs"

        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "arc.log"

        self._ui_callbacks: list[Callable[[str, str, str], None]] = [] # (category, level, message)
        self._callback_lock = threading.Lock()

        # Core python logger setup
        self._py_logger = logging.getLogger("ARC")
        self._py_logger.setLevel(logging.DEBUG)
        self._py_logger.propagate = False

        # Clear existing handlers if re-initialized
        self._py_logger.handlers.clear()

        # Rotating file handler (5 MB max, 3 backups)
        file_handler = RotatingFileHandler(
            str(self.log_file),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d [%(category)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SensitiveDataFilter())
        self._py_logger.addHandler(file_handler)

    @classmethod
    def get_instance(cls, log_dir: Optional[Path] = None) -> ArcLogger:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(log_dir)
            return cls._instance

    def add_ui_callback(self, callback: Callable[[str, str, str], None]) -> None:
        """Register a callback (category, level, message) to mirror to HUD."""
        with self._callback_lock:
            if callback not in self._ui_callbacks:
                self._ui_callbacks.append(callback)

    def remove_ui_callback(self, callback: Callable[[str, str, str], None]) -> None:
        with self._callback_lock:
            if callback in self._ui_callbacks:
                self._ui_callbacks.remove(callback)

    def log(self, category: str, message: str, level: str = "INFO", exc: Optional[Exception] = None) -> None:
        cat = category.upper().strip()
        lvl = level.upper().strip()
        safe_msg = sanitize_message(message)

        log_level = getattr(logging, lvl, logging.INFO)
        extra = {"category": cat}

        if exc:
            self._py_logger.log(log_level, f"{safe_msg} | Exception: {exc}", extra=extra, exc_info=True)
        else:
            self._py_logger.log(log_level, safe_msg, extra=extra)

        # Notify UI callbacks safely
        with self._callback_lock:
            callbacks = list(self._ui_callbacks)
        for cb in callbacks:
            try:
                cb(cat, lvl, safe_msg)
            except Exception:
                pass

    def audio(self, message: str, level: str = "INFO") -> None:
        self.log("AUDIO", message, level)

    def gemini(self, message: str, level: str = "INFO") -> None:
        self.log("GEMINI", message, level)

    def tool(self, tool_name: str, message: str, level: str = "INFO") -> None:
        self.log("TOOLS", f"[{tool_name}] {message}", level)

    def dashboard(self, message: str, level: str = "INFO") -> None:
        self.log("DASHBOARD", message, level)

    def system(self, message: str, level: str = "INFO") -> None:
        self.log("SYSTEM", message, level)

    def error(self, message: str, exc: Optional[Exception] = None, category: str = "ERROR") -> None:
        self.log(category, message, "ERROR", exc=exc)

    def get_recent_logs(self, max_lines: int = 100) -> list[str]:
        """Read the last N lines from the log file safely."""
        if not self.log_file.exists():
            return []
        try:
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                return [line.strip() for line in lines[-max_lines:]]
        except Exception:
            return []

    def clear_logs(self) -> None:
        """Clear active log file content without breaking file handles."""
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [SYSTEM] [INFO] Logs reset.\n")
        except Exception:
            pass

    def close(self) -> None:
        """Close handlers and release file locks."""
        for handler in list(self._py_logger.handlers):
            try:
                handler.close()
                self._py_logger.removeHandler(handler)
            except Exception:
                pass


# Backward compatibility aliases
ArcLogger = ArcLogger
BhaveshLogger = ArcLogger

# Module-level convenience functions
_default_logger = ArcLogger.get_instance()

def get_logger() -> ArcLogger:
    return _default_logger

def log_audio(msg: str, level: str = "INFO") -> None:
    _default_logger.audio(msg, level)

def log_gemini(msg: str, level: str = "INFO") -> None:
    _default_logger.gemini(msg, level)

def log_tool(tool_name: str, msg: str, level: str = "INFO") -> None:
    _default_logger.tool(tool_name, msg, level)

def log_dashboard(msg: str, level: str = "INFO") -> None:
    _default_logger.dashboard(msg, level)

def log_system(msg: str, level: str = "INFO") -> None:
    _default_logger.system(msg, level)

def log_error(msg: str, exc: Optional[Exception] = None, category: str = "ERROR") -> None:
    _default_logger.error(msg, exc=exc, category=category)
