import json
import os
import logging

logger = logging.getLogger(__name__)

# /tmp persists longer than /app on Railway
SETTINGS_FILE = "/tmp/trendguard_settings.json"


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
    # Fallback to Railway env variable
    env = os.environ.get("ACCOUNT_BALANCE")
    if env:
        try:
            return float(env)
        except Exception:
            pass
    return None


def set_balance(chat_id: int, balance: float):
    data = _load()
    data[str(chat_id)] = balance
    _save(data)
