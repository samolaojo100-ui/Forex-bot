import json
import os
import logging

logger = logging.getLogger(__name__)

# /tmp persists longer than /app on Railway
SETTINGS_FILE = "/tmp/trendguard_settings.json"
AUTH_FILE     = "/tmp/trendguard_authorized.json"


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


# ── Access control ────────────────────────────────────────────────────
# Approved chat IDs are stored separately from balance settings so that
# editing one never risks corrupting the other. Combined with the
# AUTHORIZED_USERS env var in config.py (which always stays authorized
# even if /tmp is wiped on redeploy).

def _load_auth() -> dict:
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"approved": []}


def _save_auth(data: dict):
    try:
        with open(AUTH_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save auth list: {e}")


def is_authorized(chat_id: int) -> bool:
    from config import AUTHORIZED_USERS  # imported lazily to avoid circular imports

    chat_id_str = str(chat_id)
    if chat_id_str in AUTHORIZED_USERS:
        return True

    data = _load_auth()
    return chat_id_str in data.get("approved", [])


def approve_user(chat_id: int):
    data = _load_auth()
    chat_id_str = str(chat_id)
    if chat_id_str not in data["approved"]:
        data["approved"].append(chat_id_str)
        _save_auth(data)


def revoke_user(chat_id: int):
    data = _load_auth()
    chat_id_str = str(chat_id)
    if chat_id_str in data["approved"]:
        data["approved"].remove(chat_id_str)
        _save_auth(data)


def list_approved_users() -> list:
    data = _load_auth()
    return data.get("approved", [])
