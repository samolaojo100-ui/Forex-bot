"""
Access control for SamSignals bot.
Only approved users can use the bot.
Admin (Sam) can add/remove users with commands.
"""
import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ACCESS_FILE = "/tmp/access_control.json"

# ── Your Telegram ID — you always have full access ─────────────────────────────
ADMIN_ID = 7527822989

def _load() -> dict:
    try:
        if os.path.exists(ACCESS_FILE):
            with open(ACCESS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load access file: {e}")
    return {"approved": [], "banned": []}


def _save(data: dict):
    try:
        with open(ACCESS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save access file: {e}")


def is_admin(chat_id: int) -> bool:
    return chat_id == ADMIN_ID


def is_approved(chat_id: int) -> bool:
    """Check if a user is allowed to use the bot."""
    if chat_id == ADMIN_ID:
        return True
    data = _load()
    return chat_id in data.get("approved", [])


def is_banned(chat_id: int) -> bool:
    data = _load()
    return chat_id in data.get("banned", [])


def approve_user(chat_id: int) -> bool:
    data = _load()
    if chat_id not in data["approved"]:
        data["approved"].append(chat_id)
        # remove from banned if they were there
        if chat_id in data.get("banned", []):
            data["banned"].remove(chat_id)
        _save(data)
        return True
    return False  # already approved


def remove_user(chat_id: int) -> bool:
    data = _load()
    if chat_id in data.get("approved", []):
        data["approved"].remove(chat_id)
        _save(data)
        return True
    return False  # wasn't approved


def ban_user(chat_id: int):
    data = _load()
    if chat_id not in data.get("banned", []):
        data["banned"].append(chat_id)
    if chat_id in data.get("approved", []):
        data["approved"].remove(chat_id)
    _save(data)


def list_users() -> list:
    data = _load()
    return data.get("approved", [])


def denied_message() -> str:
    return (
        "⛔ *Access Denied*\n\n"
        "This is a private bot.\n"
        "Contact @SamSos to request access."
    )
