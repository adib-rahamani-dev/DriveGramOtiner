import hashlib
import hmac
import secrets
from datetime import timedelta

import httpx
from sqlalchemy import func, select

from drivegram.errors import ServiceError
from drivegram.models import Control, Job, utcnow
from drivegram.queue import control_lock


def destination_settings(session, settings):
    control = session.get(Control, 1)
    if control and control.private_chat_id:
        return settings.model_copy(update={"telegram_chat_id": control.private_chat_id, "telegram_channel_id": ""})
    return settings


def begin_pairing(session):
    control = control_lock(session)
    if session.scalar(select(func.count()).select_from(Job).where(Job.status.in_(("downloading", "uploading")))):
        raise ServiceError("busy", "برای اتصال پی‌وی ابتدا منتظر پایان انتقال‌های فعال بمانید.")
    code = "dg_" + secrets.token_urlsafe(32)
    control.pair_hash = hashlib.sha256(code.encode()).hexdigest()
    control.pair_expires_at = utcnow() + timedelta(minutes=10)
    control.pair_poll_until = None
    return "https://t.me/DriveGramOtiner_bot?start=" + code


def accept_pairing(session, update):
    control = control_lock(session)
    if not control.pair_hash or not control.pair_expires_at or control.pair_expires_at <= utcnow():
        return False
    message = update.get("message", {})
    chat, sender = message.get("chat", {}), message.get("from", {})
    command = message.get("text", "").split()
    if (chat.get("type") != "private" or sender.get("is_bot") or chat.get("id") != sender.get("id")
            or not isinstance(chat.get("id"), int) or chat["id"] <= 0
            or len(command) != 2 or command[0] not in {"/start", "/start@DriveGramOtiner_bot"}):
        return False
    if not hmac.compare_digest(control.pair_hash, hashlib.sha256(command[1].encode()).hexdigest()):
        return False
    if session.scalar(select(func.count()).select_from(Job).where(Job.status.in_(("downloading", "uploading")))):
        return False
    control.private_chat_id = str(chat["id"])
    control.pair_hash = control.pair_expires_at = control.pair_poll_until = None
    control.telegram_ok, control.telegram_checked_at, control.telegram_error = False, None, None
    return True


def poll_pairing_once(sessions, settings, client=None):
    with sessions.begin() as session:
        control = control_lock(session)
        now = utcnow()
        if (not control.pair_hash or not control.pair_expires_at or control.pair_expires_at <= now
                or (control.pair_poll_until and control.pair_poll_until > now)):
            return False
        control.pair_poll_until = now + timedelta(seconds=20)
        offset, pending_hash = control.telegram_update_offset, control.pair_hash
    owned_client = client is None
    client = client or httpx.Client(timeout=10)
    base = (settings.telegram_bot_api_url if settings.telegram_api_id and settings.telegram_api_hash.get_secret_value()
            else "https://api.telegram.org")
    try:
        response = client.post(base.rstrip("/") + "/bot" + settings.telegram_bot_token.get_secret_value() + "/getUpdates",
                               json={"offset": offset, "timeout": 0, "allowed_updates": ["message"]})
        data = response.json()
        if not data.get("ok") or not isinstance(data.get("result"), list):
            raise ValueError()
        with sessions.begin() as session:
            control = control_lock(session)
            # A new admin request invalidates a poll that was already in flight.
            if control.pair_hash != pending_hash:
                return False
            paired = False
            for update in data["result"]:
                if isinstance(update.get("update_id"), int):
                    control.telegram_update_offset = max(control.telegram_update_offset, update["update_id"] + 1)
                paired = accept_pairing(session, update) or paired
            return paired
    except Exception:
        with sessions.begin() as session:
            control = control_lock(session)
            if control.pair_hash == pending_hash:
                control.telegram_error = "دریافت درخواست اتصال ممکن نیست؛ شبکه، توکن و webhook قبلی ربات را بررسی کنید."
        return False
    finally:
        if owned_client:
            client.close()
