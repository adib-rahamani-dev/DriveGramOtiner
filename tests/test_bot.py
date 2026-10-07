import json

import httpx

from drivegram.bot import owner_actions
from drivegram.models import Control, Job
from drivegram.pairing import poll_pairing_once


def owner_update(text="/videos", owner=123):
    return {"update_id": 10, "message": {"chat": {"id": owner, "type": "private"},
            "from": {"id": owner, "is_bot": False}, "text": text}}


def send_update(job_id, owner=123):
    return {"update_id": 11, "callback_query": {"id": "callback", "from": {"id": owner},
            "message": {"chat": {"id": owner, "type": "private"}}, "data": f"dg:send:{job_id}"}}


def test_owner_only_catalog_and_guarded_queue(sessions, settings, queued):
    with sessions.begin() as session:
        control = session.get(Control, 1)
        control.private_chat_id = "123"
        job = session.get(Job, queued)
        job.status = "discovered"
        assert owner_actions(session, settings, control, owner_update(owner=999)) == []
        assert owner_actions(session, settings, control, send_update(queued, owner=999)) == []
        catalog = owner_actions(session, settings, control, owner_update())[0][1]
        assert job.original_name in catalog["text"]
        assert catalog["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"dg:send:{queued}"
        actions = owner_actions(session, settings, control, send_update(queued))
        assert job.status == "queued"
        assert actions[0][0] == "answerCallbackQuery"
        job.status, job.needs_review = "failed", True
        owner_actions(session, settings, control, send_update(queued))
        assert job.status == "failed" and job.needs_review
        catalog = owner_actions(session, settings, control, owner_update())[0][1]
        assert "dg:send:" not in json.dumps(catalog)
        job.status, job.needs_review = "completed", False
        owner_actions(session, settings, control, send_update(queued))
        assert job.status == "completed"


def test_paired_poll_serves_commands_and_does_not_replay_updates(sessions, settings, queued):
    with sessions.begin() as session:
        control = session.get(Control, 1)
        control.private_chat_id = "123"
    methods = []
    def handler(request):
        method = request.url.path.rsplit("/", 1)[1]
        methods.append(method)
        if method == "getUpdates":
            assert "callback_query" in json.loads(request.content)["allowed_updates"]
            return httpx.Response(200, json={"ok": True, "result": [owner_update()]})
        assert json.loads(request.content)["chat_id"] == "123"
        return httpx.Response(200, json={"ok": True, "result": {}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert not poll_pairing_once(sessions, settings, client)
        with sessions.begin() as session:
            session.get(Control, 1).pair_poll_until = None
        assert not poll_pairing_once(sessions, settings, client)
    assert methods == ["getUpdates", "sendMessage", "getUpdates"]
    with sessions() as session:
        assert session.get(Control, 1).telegram_update_offset == 11
