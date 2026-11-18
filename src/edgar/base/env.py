from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from edgar import __version__

APP = "edgar"

_CONFIG_KEYS = {
    "user_agent": "EDGAR_USER_AGENT",
    "rate_limit": "EDGAR_RATE_LIMIT",
    "cache_dir": "EDGAR_CACHE_DIR",
    "timeout": "EDGAR_TIMEOUT",
}


def config_dir() -> Path:
    override = os.environ.get("EDGAR_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP


def default_cache_dir() -> Path:
    override = os.environ.get("EDGAR_CACHE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / APP


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict:
    path = config_path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            value = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_config(values: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(values, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def default_user_agent() -> str:
    return f"edgar/{__version__} (contact not configured)"


def get_setting(key: str, default=None):
    env_name = _CONFIG_KEYS.get(key)
    if env_name:
        value = os.environ.get(env_name)
        if value is not None and value != "":
            return value
    value = load_config().get(key)
    return default if value is None else value


def get_user_agent() -> str:
    return str(get_setting("user_agent", default_user_agent()))


def get_rate_limit() -> float:
    try:
        value = float(get_setting("rate_limit", 8))
    except (TypeError, ValueError):
        value = 8.0
    return max(0.1, min(value, 10.0))


def get_timeout() -> float:
    try:
        value = float(get_setting("timeout", 30))
    except (TypeError, ValueError):
        value = 30.0
    return max(1.0, value)


def get_cache_dir() -> Path:
    value = get_setting("cache_dir")
    return Path(str(value)) if value else default_cache_dir()
