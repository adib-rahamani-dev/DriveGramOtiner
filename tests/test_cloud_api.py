import httpx
import pytest
from pydantic import ValidationError

from drivegram.config import Settings
from drivegram.errors import ServiceError
from drivegram.models import Job
from drivegram.queue import queue_selected
from drivegram.telegram import Telegram


def cloud_settings(settings):
    return Settings(**(settings.model_dump() | {
        "telegram_api_mode": "cloud", "telegram_bot_api_url": "https://api.telegram.org",
        "telegram_api_id": "", "telegram_api_hash": "", "telegram_chat_id": "12345",
        "telegram_channel_id": "", "max_file_size_mb": 50,
    }), _env_file=None)


def test_cloud_requires_official_https_and_no_application_credentials(settings):
    configured = cloud_settings(settings)
    assert configured.telegram_configured
    assert configured.max_file_size_bytes == 50_000_000
    for address in ("http://api.telegram.org", "https://example.com", "https://api.telegram.org/other"):
        with pytest.raises(ValidationError):
            Settings(**(configured.model_dump() | {"telegram_bot_api_url": address}), _env_file=None)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, telegram_bot_api_url="https://api.telegram.org")


@pytest.mark.parametrize("video", [False, True])
def test_cloud_uploads_original_bytes_as_multipart_to_private_chat(settings, tmp_path, monkeypatch, video):
    configured = cloud_settings(settings)
    path = tmp_path / "original.mp4"
    original = b"original bytes remain unchanged\x00\xff"
    path.write_bytes(original)
    kind = "video" if video else "document"
    monkeypatch.setattr("drivegram.telegram.streamable_video", lambda _: {"duration": 2} if video else None)
    def handler(request):
        assert request.url.host == "api.telegram.org"
        assert request.url.path.endswith("sendVideo" if video else "sendDocument")
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert original in request.content
        assert b'name="chat_id"\r\n\r\n12345' in request.content
        assert b'filename="original.mp4"' in request.content
        assert b"file:///" not in request.content
        return httpx.Response(200, json={"ok": True, "result": {
            "chat": {"id": 12345}, "message_id": 17, kind: {"file_id": "stored"}}})
    api = Telegram(configured, httpx.Client(transport=httpx.MockTransport(handler)))
    assert api.send(path, "original.mp4") == ("12345", 17, "stored")
    assert path.read_bytes() == original
    api.close()


def test_cloud_rejects_oversize_before_queue_or_network(settings, sessions, queued, tmp_path):
    configured = cloud_settings(settings)
    with sessions.begin() as session:
        job = session.get(Job, queued)
        job.status = "discovered"
        job.size_bytes = 50_000_001
        with pytest.raises(ServiceError) as error:
            queue_selected(session, job, configured)
        assert error.value.code == "too_large"
        job.size_bytes = 50_000_000
        queue_selected(session, job, configured)
        assert job.status == "queued"
    path = tmp_path / "too-large.mp4"
    with path.open("wb") as file:
        file.truncate(50_000_001)
    def handler(request):
        pytest.fail("Oversized file must never reach Telegram")
    api = Telegram(configured, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ServiceError) as error:
        api.send(path, path.name)
    assert error.value.code == "file_too_large"
    api.close()


def test_cloud_upload_timeout_keeps_result_ambiguous(settings, tmp_path, monkeypatch):
    path = tmp_path / "original.mp4"
    path.write_bytes(b"original")
    monkeypatch.setattr("drivegram.telegram.streamable_video", lambda _: None)
    def handler(request):
        raise httpx.ReadTimeout("private request must not be logged", request=request)
    api = Telegram(cloud_settings(settings), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ServiceError) as error:
        api.send(path, path.name)
    assert error.value.ambiguous and not error.value.retryable
    api.close()
