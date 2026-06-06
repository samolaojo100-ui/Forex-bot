"""
User balance storage.

Railway's filesystem is ephemeral (data lost on restart), so we use
in-memory storage as the primary store, with an optional JSON file
as a best-effort cache when the filesystem is writable.
"""
import json
import os
import logging

logger = logging.getLogger(__name__)

SETTINGS_FILE = "/tmp/user_settings.json"   # /tmp is always writable on Railway

# In-memory store (survives within a session; lost on restart)
_MEMORY: dict = {}


def _load() -> dict:
    global _MEMORY
    if _MEMORY:
        return _MEMORY
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                _MEMORY = json.load(f)
    except Exception as e:
        logger.warning(f"Could not load settings from disk: {e}")
        _MEMORY = {}
    return _MEMORY


def _save(data: dict):
    global _MEMORY
    _MEMORY = data
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not persist settings to disk: {e}")


def get_balance(chat_id: int) -> float | None:
    data = _load()
    val  = data.get(str(chat_id))
    return float(val) if val is not None else None


def set_balance(chat_id: int, balance: float):
    data = _load()
    data[str(chat_id)] = balance
    _save(data)


def clear_balance(chat_id: int):
    data = _load()
    data.pop(str(chat_id), None)
    _save(data)
