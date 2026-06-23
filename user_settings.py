import json
import os
import logging

logger = logging.getLogger(__name__)

# /tmp persists longer than /app on Railway
SETTINGS_FILE = "/tmp/trendguard_settings.json"
AUTH_FILE     = "/tmp/trendguard_authorized.json"
PENDING_FILE  = "/tmp/trendguard_pending.json"


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
    from config import AUTHORIZED_USERS
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
    # Remove from pending if they were there
    remove_pending(chat_id)


def revoke_user(chat_id: int):
    data = _load_auth()
    chat_id_str = str(chat_id)
    if chat_id_str in data["approved"]:
        data["approved"].remove(chat_id_str)
        _save_auth(data)


def list_approved_users() -> list:
    data = _load_auth()
    return data.get("approved", [])


# ── Pending queue ─────────────────────────────────────────────────────
# Each pending entry: {"id": 123, "name": "John", "username": "john"}
# Stored as a list in order of arrival (oldest first).

def _load_pending() -> list:
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_pending(data: list):
    try:
        with open(PENDING_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save pending list: {e}")


def add_pending(chat_id: int, name: str, username: str):
    """Add a user to the pending queue if not already there."""
    pending = _load_pending()
    ids = [p["id"] for p in pending]
    if chat_id not in ids:
        pending.append({"id": chat_id, "name": name, "username": username or "none"})
        _save_pending(pending)


def remove_pending(chat_id: int):
    """Remove a user from the pending queue."""
    pending = _load_pending()
    pending = [p for p in pending if p["id"] != chat_id]
    _save_pending(pending)


def next_pending() -> dict | None:
    """Return the oldest pending user, or None if queue is empty."""
    pending = _load_pending()
    return pending[0] if pending else None


def list_pending() -> list:
    return _load_pending()
