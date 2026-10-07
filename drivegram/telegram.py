import json
import subprocess

import httpx

from drivegram.errors import ServiceError

EXPECTED_BOT = "DriveGramOtiner_bot"


def caption(name):
    clean = "".join(c for c in name if c.isprintable() or c == "\n")
    # Telegram entities use UTF-16 offsets; use a conservative 1024 UTF-16-unit cap.
    return clean.encode("utf-16-le")[:2048].decode("utf-16-le", errors="ignore")


def streamable_video(path):
    try:
        response = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, timeout=30, check=True,
        )
        data = json.loads(response.stdout)
        streams = data.get("streams", [])
        video = [s for s in streams if s.get("codec_type") == "video"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        formats = data.get("format", {}).get("format_name", "").split(",")
        if "mp4" not in formats or not video or any(s.get("codec_name") != "h264" for s in video):
            return None
        if any(s.get("codec_name") not in {"aac", "mp3"} for s in audio):
            return None
        # Require fast-start MP4: moov must precede mdat. Read only box headers.
        with path.open("rb") as file:
            offset, moov, mdat = 0, None, None
            size = path.stat().st_size
            while offset + 8 <= size:
                file.seek(offset)
                header = file.read(8)
                length, kind = int.from_bytes(header[:4], "big"), header[4:]
                if length == 1:
                    length = int.from_bytes(file.read(8), "big")
                elif length == 0:
                    length = size - offset
                if length < 8:
                    return None
                if kind == b"moov":
                    moov = offset
                if kind == b"mdat":
                    mdat = offset
                offset += length
            if moov is None or mdat is None or moov > mdat:
                return None
        return {"width": video[0].get("width"), "height": video[0].get("height"),
                "duration": max(1, int(float(data.get("format", {}).get("duration", 1))))}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


class Telegram:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(settings.upload_timeout_seconds, connect=15),
            proxy=(settings.telegram_http_proxy.get_secret_value() or None) if settings.telegram_api_mode == "cloud" else None,
        )
        self.base = settings.telegram_bot_api_url.rstrip("/") + "/bot" + settings.telegram_bot_token.get_secret_value()

    def close(self):
        self.client.close()

    def call(self, method, payload=None, *, sending=False, files=None):
        try:
            if files:
                response = self.client.post(self.base + "/" + method, data=payload or {}, files=files)
            else:
                response = self.client.post(self.base + "/" + method, json=payload or {})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise ServiceError("telegram_connect", "اتصال به سرویس تلگرام ممکن نیست.", retryable=True) from None
        except httpx.HTTPError:
            raise ServiceError("upload_unknown" if sending else "telegram_network",
                               "نتیجه ارسال نامشخص است؛ گفتگوی مقصد را بررسی کنید." if sending else "ارتباط تلگرام قطع شد.",
                               retryable=not sending, ambiguous=sending) from None
        try:
            data = response.json()
            if not isinstance(data, dict) or "ok" not in data:
                raise ValueError()
        except ValueError:
            raise ServiceError("telegram_response", "پاسخ تلگرام معتبر نیست؛ وضعیت ارسال را بررسی کنید.",
                               retryable=not sending, ambiguous=sending) from None
        if not data["ok"]:
            code = data.get("error_code", response.status_code)
            if code == 429:
                retry_after = int(data.get("parameters", {}).get("retry_after", 60))
                raise ServiceError("telegram_rate_limit", "محدودیت ارسال تلگرام؛ تلاش بعدی با تأخیر انجام می‌شود.",
                                   retryable=True, retry_after=retry_after)
            if code >= 500:
                raise ServiceError("telegram_server", "خطای سرور تلگرام؛ نتیجه ارسال را بررسی کنید.",
                                   retryable=not sending, ambiguous=sending)
            raise ServiceError("telegram_access", "مجوز ربات، شناسه مقصد یا فایل ارسالی را بررسی کنید.")
        return data.get("result")

    def check(self):
        me = self.call("getMe")
        if not isinstance(me, dict) or me.get("username", "").lower() != EXPECTED_BOT.lower():
            raise ServiceError("wrong_bot", "توکن متعلق به ربات DriveGramOtiner_bot نیست.")
        target = self.settings.telegram_target_id
        chat = self.call("getChat", {"chat_id": target})
        if self.settings.telegram_chat_id:
            if chat.get("type") != "private" or str(chat.get("id")) != target:
                raise ServiceError("private_access", "مقصد باید پیام خصوصی حساب متصل‌شده باشد؛ ربات را Start کنید.")
            return me
        member = self.call("getChatMember", {"chat_id": target, "user_id": me["id"]})
        if chat.get("type") != "channel" or member.get("status") not in {"administrator", "creator"}:
            raise ServiceError("channel_access", "ربات باید مدیر کانال مقصد باشد.")
        if member.get("status") == "administrator" and not member.get("can_post_messages"):
            raise ServiceError("channel_access", "مجوز ارسال پیام در کانال را به ربات بدهید.")
        return me

    def send(self, path, name):
        if path.stat().st_size > self.settings.max_file_size_bytes:
            raise ServiceError("file_too_large", "حجم فایل از سقف مجاز ارسال بیشتر است؛ فایل تغییر یا تقسیم نمی‌شود.")
        info = streamable_video(path)
        kind = "video" if info else "document"
        payload = {"chat_id": self.settings.telegram_target_id, "caption": caption(name), kind: path.as_uri()}
        if info:
            payload.update({k: v for k, v in info.items() if v is not None})
            payload["supports_streaming"] = True
        else:
            payload["disable_content_type_detection"] = True
        method = "sendVideo" if info else "sendDocument"
        if self.settings.telegram_api_mode == "cloud":
            payload.pop(kind)
            form = {key: str(value).lower() if isinstance(value, bool) else str(value)
                    for key, value in payload.items()}
            with path.open("rb") as source:
                result = self.call(method, form, sending=True,
                                   files={kind: (path.name, source, "video/mp4" if info else "application/octet-stream")})
        else:
            result = self.call(method, payload, sending=True)
        try:
            return str(result["chat"]["id"]), int(result["message_id"]), result[kind]["file_id"]
        except (KeyError, TypeError, ValueError):
            raise ServiceError("upload_unknown", "پاسخ موفق تلگرام ناقص است؛ گفتگوی مقصد را بررسی کنید.", ambiguous=True) from None


def message_link(chat_id, message_id):
    if chat_id and message_id and str(chat_id).startswith("-100"):
        return f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
    return None
