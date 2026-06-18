# user_settings.py
# Saves balance to a JSON file with Railway env var fallback.
# Also reads ACCOUNT_BALANCE from Railway env as default for all users.

import json
import os
import logging

logger = logging.getLogger(__name__)

SETTINGS_FILE = "/tmp/user_settings.json"  # /tmp persists longer on Railway


def _load() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(data: dict):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save settings: {e}")


def get_balance(chat_id: int):
    data = _load()
    val  = data.get(str(chat_id))
    if val:
        return float(val)
    # Fallback — use ACCOUNT_BALANCE env var set in Railway
    env_bal = os.environ.get("ACCOUNT_BALANCE")
    if env_bal:
        try:
            return float(env_bal)
        except Exception:
            pass
    return None


def set_balance(chat_id: int, balance: float):
    data = _load()
    data[str(chat_id)] = balance
    _save(data)


def clear_balance(chat_id: int):
    data = _load()
    data.pop(str(chat_id), None)
    _save(data)