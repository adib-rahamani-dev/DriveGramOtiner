import re
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from drivegram.app import create_app
from drivegram.errors import ServiceError
from drivegram.models import Control, Job, utcnow
from drivegram.pairing import accept_pairing, begin_pairing, destination_settings, poll_pairing_once
from drivegram.queue import claim_job, current_scope
from drivegram.telegram import Telegram
from tests.test_app import login


def update(code, chat_id=123, kind="private"):
    return {"update_id": 9, "message": {"chat": {"id": chat_id, "type": kind},
            "from": {"id": chat_id, "is_bot": False}, "text": "/start " + code}}


def code_from_url(url):
    return parse_qs(urlparse(url).query)["start"][0]


def test_pairing_is_private_one_use_and_blocks_claims(sessions, settings, queued):
    with sessions.begin() as session:
        code = code_from_url(begin_pairing(session))
        assert code not in session.get(Control, 1).pair_hash
        assert claim_job(session, settings, current_scope(session, settings)) is None
        assert not accept_pairing(session, update(code, -123, "group"))
        assert not accept_pairing(session, update("incorrect"))
        assert accept_pairing(session, update(code))
        assert not accept_pairing(session, update(code, 999))
        target = destination_settings(session, settings)
        assert target.telegram_target_id == "123"
        assert target.telegram_channel_id == ""
        assert claim_job(session, settings, current_scope(session, settings)) is not None


def test_expired_pairing_and_active_upload_cannot_change_destination(sessions, queued):
    with sessions.begin() as session:
        code = code_from_url(begin_pairing(session))
        session.get(Control, 1).pair_expires_at = utcnow() - timedelta(seconds=1)
        assert not accept_pairing(session, update(code))
        session.get(Job, queued).status = "uploading"
        with pytest.raises(ServiceError):
            begin_pairing(session)


def test_poll_persists_pair_and_offset_without_sending_messages(sessions, settings):
    with sessions.begin() as session:
        code = code_from_url(begin_pairing(session))
    settings.telegram_api_id = ""

    def handler(request):
        assert request.url.path.endswith("/getUpdates")
        return httpx.Response(200, json={"ok": True, "result": [update(code)]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert poll_pairing_once(sessions, settings, client)
        assert not poll_pairing_once(sessions, settings, client)
    with sessions() as session:
        assert session.get(Control, 1).private_chat_id == "123"
        assert session.get(Control, 1).telegram_update_offset == 10


def test_private_destination_does_not_require_channel_membership(settings, tmp_path):
    settings.telegram_chat_id = "123"
    methods = []

    def handler(request):
        methods.append(request.url.path.rsplit("/", 1)[1])
        if methods[-1] == "getMe":
            result = {"id": 77, "username": "DriveGramOtiner_bot"}
        elif methods[-1] == "getChat":
            result = {"id": 123, "type": "private"}
        else:
            assert b'"chat_id":"123"' in request.content
            result = {"chat": {"id": 123}, "message_id": 42, "document": {"file_id": "file"}}
        return httpx.Response(200, json={"ok": True, "result": result})

    api = Telegram(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        api.check()
        path = tmp_path / "video.mkv"
        path.write_bytes(b"data")
        assert api.send(path, path.name)[:2] == ("123", 42)
        assert methods == ["getMe", "getChat", "sendDocument"]
    finally:
        api.close()


def test_pairing_endpoint_requires_admin_csrf_and_live_worker(sessions, settings):
    with TestClient(create_app(settings, sessions)) as client:
        assert client.post("/api/telegram/pair").status_code == 401
        login(client, settings)
        assert client.post("/api/telegram/pair").status_code == 403
        token = re.search('name="csrf-token" content="([^"]+)"', client.get("/").text).group(1)
        headers = {"X-CSRF-Token": token}
        assert client.post("/api/telegram/pair", headers=headers).status_code == 409
        with sessions.begin() as session:
            session.get(Control, 1).worker_heartbeat = utcnow()
        response = client.post("/api/telegram/pair", headers=headers)
        assert response.status_code == 200
        assert response.json()["url"].startswith("https://t.me/DriveGramOtiner_bot?start=dg_")
        assert response.json()["expires_in"] == 600
