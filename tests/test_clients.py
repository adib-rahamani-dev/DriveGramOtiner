import hashlib
import logging

import httpx
import pytest
from pydantic import SecretStr

from drivegram.errors import ServiceError
from drivegram.google import GoogleDrive
from drivegram.models import Job, OAuthToken
from drivegram.security import RedactingFormatter, cipher
from drivegram.telegram import Telegram, caption, streamable_video


def test_pagination_download_stream_and_encrypted_refresh(sessions, settings, tmp_path):
    data = b"data"
    meta = {"id": "file123", "version": "1", "size": "4", "parents": ["folder123"], "mimeType": "video/mp4"}
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ephemeral", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer ephemeral"
        if request.url.path.endswith("folder123"):
            return httpx.Response(200, json={"mimeType": "application/vnd.google-apps.folder"})
        if request.url.path.endswith("file123"):
            return httpx.Response(200, content=data) if request.url.params.get("alt") == "media" else httpx.Response(200, json=meta)
        if request.url.params.get("pageToken"):
            return httpx.Response(200, json={"files": [{"id": "second"}]})
        return httpx.Response(200, json={"files": [meta], "nextPageToken": "page2"})
    encrypted = cipher(settings).encrypt(b"private-refresh").decode()
    assert "private-refresh" not in encrypted
    with sessions.begin() as session:
        session.add(OAuthToken(id=1, refresh_encrypted=encrypted, generation="test"))
    drive = GoogleDrive(settings, sessions, httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(drive.list_files()) == 2
    job = Job(drive_file_id="file123", version_key="v:1", size_bytes=4, md5_checksum=hashlib.md5(data).hexdigest())
    counts = []
    drive.download(job, tmp_path / "download.mp4", counts.append)
    assert counts == [4]
    assert (tmp_path / "download.mp4").read_bytes() == data
    assert sum(r.url.host == "oauth2.googleapis.com" for r in seen) == 1
    assert any(r.url.params.get("pageToken") == "page2" for r in seen)
    drive.close()


def test_changed_snapshot_rejected_before_download(settings, sessions):
    drive = GoogleDrive(settings, sessions)
    drive.metadata = lambda _: {"parents": ["folder123"], "version": "2"}
    with pytest.raises(ServiceError) as error:
        drive.validate_snapshot(Job(drive_file_id="file123", version_key="v:1"))
    assert error.value.code == "source_changed"
    drive.close()


def test_google_quota_respects_retry_after(sessions, settings):
    drive = GoogleDrive(settings, sessions, httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(403, headers={"Retry-After": "90"},
                                json={"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}))))
    drive.access, drive.expires = "mock", float("inf")
    with pytest.raises(ServiceError) as error:
        drive.list_files()
    assert error.value.retryable and error.value.retry_after == 90
    drive.close()


def test_telegram_wrong_bot_and_retry_after(settings):
    api = Telegram(settings, httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"ok": True, "result": {"username": "wrong"}}))))
    with pytest.raises(ServiceError) as error:
        api.check()
    assert error.value.code == "wrong_bot"
    api.close()
    api = Telegram(settings, httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 123}}))))
    with pytest.raises(ServiceError) as error:
        api.call("sendDocument", sending=True)
    assert error.value.retryable and error.value.retry_after == 123 and not error.value.ambiguous
    api.close()


def test_upload_read_timeout_is_ambiguous_but_connect_failure_safe_to_retry(settings):
    for exception, ambiguous in ((httpx.ReadTimeout, True), (httpx.ConnectError, False)):
        def handler(request):
            raise exception("never log raw request URL", request=request)
        api = Telegram(settings, httpx.Client(transport=httpx.MockTransport(handler)))
        with pytest.raises(ServiceError) as error:
            api.call("sendVideo", sending=True)
        assert error.value.ambiguous is ambiguous
        api.close()


def test_caption_unicode_and_probe_fallback(tmp_path):
    assert len(caption("😀" * 2000).encode("utf-16-le")) <= 2048
    assert caption("original.mp4") == "original.mp4"
    path = tmp_path / "not-video.mp4"
    path.write_bytes(b"invalid")
    assert streamable_video(path) is None


def test_log_formatter_redacts_token_bearing_paths_and_secrets(settings):
    record = logging.LogRecord("test", 40, "", 1,
        "http://host/bot%s/getMe client_secret=test-secret", (settings.telegram_bot_token.get_secret_value(),), None)
    output = RedactingFormatter(settings).format(record)
    assert settings.telegram_bot_token.get_secret_value() not in output
    assert "test-secret" not in output


def test_proxy_credentials_are_redacted_from_logs(settings):
    proxy = "http://proxy-user:private-proxy-password@localhost:1234"
    configured = settings.model_copy(update={"telegram_http_proxy": SecretStr(proxy)})
    record = logging.LogRecord("test", 40, "", 1, "Connection failed through %s", (proxy,), None)
    output = RedactingFormatter(configured).format(record)
    assert proxy not in output
    assert "private-proxy-password" not in output
