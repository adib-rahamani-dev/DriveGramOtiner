import hashlib
import re
import shutil
import time

import httpx
from sqlalchemy import select

from drivegram.errors import ServiceError
from drivegram.models import OAuthToken
from drivegram.queue import version_key
from drivegram.security import cipher

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FIELDS = "id,name,mimeType,size,md5Checksum,version,modifiedTime,parents,trashed,capabilities(canDownload)"


def validate_id(value):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,256}", value):
        raise ServiceError("invalid_drive_id", "شناسه پوشه یا فایل Drive معتبر نیست.")
    return value


def response_error(response):
    delay = 0
    try:
        delay = int(response.headers.get("Retry-After", "0"))
        reasons = [e.get("reason") for e in response.json().get("error", {}).get("errors", [])]
    except (ValueError, AttributeError, TypeError):
        reasons = []
    retryable = response.status_code in {429, 500, 502, 503, 504} or bool(
        set(reasons) & {"rateLimitExceeded", "userRateLimitExceeded", "backendError"})
    return ServiceError("drive_rate_limit" if retryable else "drive_access",
                        "Drive موقتاً در دسترس نیست." if retryable else "دسترسی Drive یا مجوز دانلود را بررسی کنید.",
                        retryable=retryable, retry_after=delay)


class GoogleDrive:
    def __init__(self, settings, sessions, client=None):
        self.settings, self.sessions = settings, sessions
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=True)
        self.access = None
        self.expires = 0

    def close(self):
        self.client.close()

    def access_token(self, force=False):
        if self.access and self.expires > time.monotonic() and not force:
            return self.access
        with self.sessions() as session:
            token = session.scalar(select(OAuthToken).where(OAuthToken.id == 1))
            if not token:
                raise ServiceError("google_setup", "نیاز به تنظیم اتصال Google Drive.")
            try:
                refresh = cipher(self.settings).decrypt(token.refresh_encrypted.encode()).decode()
            except Exception:
                raise ServiceError("token_key", "کلید رمزگذاری توکن معتبر نیست.") from None
        try:
            response = self.client.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret.get_secret_value(),
                "refresh_token": refresh, "grant_type": "refresh_token",
            })
        except httpx.HTTPError:
            raise ServiceError("google_network", "ارتباط با Google قطع شد.", retryable=True) from None
        if response.status_code != 200:
            if response.status_code >= 500 or response.status_code == 429:
                raise response_error(response)
            raise ServiceError("google_reauthorize", "مجوز Google منقضی شده؛ دوباره اتصال را برقرار کنید.")
        try:
            data = response.json()
            self.access = data["access_token"]
            self.expires = time.monotonic() + max(1, int(data.get("expires_in", 3600)) - 60)
        except (ValueError, KeyError, TypeError):
            raise ServiceError("google_response", "پاسخ Google معتبر نیست.", retryable=True) from None
        return self.access

    def get(self, path, params):
        for force in (False, True):
            try:
                response = self.client.get("https://www.googleapis.com/drive/v3/" + path,
                                           params=params, headers={"Authorization": "Bearer " + self.access_token(force)})
            except httpx.HTTPError:
                raise ServiceError("google_network", "ارتباط با Drive قطع شد.", retryable=True) from None
            if response.status_code == 401 and not force:
                continue
            if response.status_code != 200:
                raise response_error(response)
            try:
                return response.json()
            except ValueError:
                raise ServiceError("drive_response", "پاسخ Drive معتبر نیست.", retryable=True) from None

    def metadata(self, file_id):
        return self.get("files/" + validate_id(file_id), {"fields": FIELDS, "supportsAllDrives": "true"})

    def list_files(self):
        folder = validate_id(self.settings.google_drive_folder_id)
        meta = self.metadata(folder)
        if meta.get("mimeType") != "application/vnd.google-apps.folder" or meta.get("trashed"):
            raise ServiceError("not_folder", "پوشه مبدا معتبر نیست.")
        result, token, seen = [], None, set()
        while True:
            params = {"q": f"'{folder}' in parents and trashed = false", "pageSize": 1000,
                      "fields": f"nextPageToken,incompleteSearch,files({FIELDS})",
                      "includeItemsFromAllDrives": "true", "supportsAllDrives": "true"}
            if token:
                params["pageToken"] = token
            page = self.get("files", params)
            if page.get("incompleteSearch"):
                raise ServiceError("incomplete_scan", "اسکن Drive کامل نیست؛ تلاش مجدد انجام می‌شود.", retryable=True)
            result.extend(page.get("files", []))
            token = page.get("nextPageToken")
            if not token:
                break
            if token in seen:
                raise ServiceError("page_cycle", "صفحه‌بندی Drive نامعتبر است.", retryable=True)
            seen.add(token)
        return result

    def validate_snapshot(self, job):
        meta = self.metadata(job.drive_file_id)
        if meta.get("trashed") or self.settings.google_drive_folder_id not in meta.get("parents", []):
            raise ServiceError("source_moved", "فایل از پوشه مبدا خارج شده است.")
        if meta.get("capabilities", {}).get("canDownload") is False:
            raise ServiceError("download_forbidden", "دانلود این فایل مجاز نیست.")
        if version_key(meta) != job.version_key:
            raise ServiceError("source_changed", "محتوای فایل تغییر کرده؛ نسخه جدید را پس از اسکن انتخاب کنید.")

    def download(self, job, path, progress):
        self.validate_snapshot(job)
        if job.size_bytes > self.settings.max_file_size_bytes:
            raise ServiceError("too_large", "حجم فایل از سقف تنظیم‌شده بیشتر است.")
        reserve = self.settings.disk_reserve_mb * 1024 * 1024
        if shutil.disk_usage(path.parent).free < job.size_bytes + reserve:
            raise ServiceError("disk_full", "فضای کافی برای دریافت فایل وجود ندارد.", retryable=True)
        start = time.monotonic()
        digest = hashlib.md5(usedforsecurity=False)
        count = 0
        try:
            with self.client.stream("GET", "https://www.googleapis.com/drive/v3/files/" + validate_id(job.drive_file_id),
                                    params={"alt": "media", "supportsAllDrives": "true"},
                                    headers={"Authorization": "Bearer " + self.access_token()}) as response:
                if response.status_code != 200:
                    response.read()
                    raise response_error(response)
                with path.open("xb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if time.monotonic() - start > self.settings.download_timeout_seconds:
                            raise ServiceError("download_timeout", "مهلت دانلود تمام شد.", retryable=True)
                        count += len(chunk)
                        if count > self.settings.max_file_size_bytes or count > job.size_bytes:
                            raise ServiceError("size_changed", "حجم دانلود با نسخه انتخاب‌شده تطابق ندارد.")
                        if shutil.disk_usage(path.parent).free < len(chunk) + reserve:
                            raise ServiceError("disk_full", "فضای دیسک کافی نیست.", retryable=True)
                        output.write(chunk)
                        digest.update(chunk)
                        progress(count)
        except httpx.HTTPError:
            self.access = None
            raise ServiceError("download_network", "دانلود به علت قطع شبکه متوقف شد.", retryable=True) from None
        except OSError:
            raise ServiceError("disk_io", "نوشتن فایل موقت ممکن نیست؛ فضای دیسک را بررسی کنید.", retryable=True) from None
        if count != job.size_bytes or (job.md5_checksum and digest.hexdigest() != job.md5_checksum):
            raise ServiceError("checksum_mismatch", "اندازه یا checksum فایل دانلودشده معتبر نیست.", retryable=True)
        self.validate_snapshot(job)
