from pathlib import Path

import pytest

from drivegram.errors import Canceled, ServiceError
from drivegram.models import Job
from drivegram.queue import claim_job, current_scope
from drivegram.worker import cleanup, transfer, transfer_path


class FakeDrive:
    def __init__(self, *args):
        pass
    def download(self, job, path, progress):
        path.write_bytes(b"data")
        progress(4)
    def close(self):
        pass


class FakeTelegram:
    calls = 0
    def __init__(self, *args):
        pass
    def send(self, path, name):
        FakeTelegram.calls += 1
        assert path.read_bytes() == b"data"
        return "-10012345", 55, "file-id"
    def close(self):
        pass


def claim(sessions, settings):
    with sessions.begin() as session:
        return claim_job(session, settings, current_scope(session, settings))


def test_success_stored_before_file_cleanup_no_second_send(sessions, settings, queued):
    FakeTelegram.calls = 0
    job_id, token = claim(sessions, settings)
    transfer(sessions, settings, job_id, token, FakeDrive, FakeTelegram)
    with sessions() as session:
        job = session.get(Job, queued)
        assert job.status == "completed" and job.telegram_message_id == 55
        assert job.telegram_chat_id == "-10012345" and job.telegram_file_id == "file-id"
    assert not transfer_path(settings, job_id, token).parent.exists()
    assert claim(sessions, settings) is None
    assert FakeTelegram.calls == 1


def test_transient_download_failure_is_bounded_and_partial_removed(sessions, settings, queued):
    class BrokenDrive(FakeDrive):
        def download(self, job, path, progress):
            path.write_bytes(b"partial")
            raise ServiceError("download_network", "network", retryable=True)
    job_id, token = claim(sessions, settings)
    transfer(sessions, settings, job_id, token, BrokenDrive, FakeTelegram)
    with sessions() as session:
        job = session.get(Job, queued)
        assert job.status == "queued" and job.attempts == 1 and job.next_attempt_at
    assert not transfer_path(settings, job_id, token).parent.exists()


def test_unknown_upload_cannot_blind_retry_and_keeps_file_until_review(sessions, settings, queued):
    class UnknownTelegram(FakeTelegram):
        def send(self, path, name):
            raise ServiceError("upload_unknown", "unknown", ambiguous=True)
    job_id, token = claim(sessions, settings)
    transfer(sessions, settings, job_id, token, FakeDrive, UnknownTelegram)
    with sessions() as session:
        job = session.get(Job, queued)
        assert job.status == "failed" and job.needs_review
    cleanup(sessions, settings)
    assert transfer_path(settings, job_id, token, "ویدیو.mp4").exists()
    assert claim(sessions, settings) is None
    with sessions.begin() as session:
        job = session.get(Job, queued)
        job.needs_review, job.status = False, "canceled"
    cleanup(sessions, settings)
    assert not transfer_path(settings, job_id, token).parent.exists()


def test_download_cancellation_cleans_up(sessions, settings, queued):
    class CancelDrive(FakeDrive):
        def download(self, job, path, progress):
            path.write_bytes(b"data")
            with sessions.begin() as session:
                session.get(Job, job.id).cancel_requested = True
            progress(4)
            raise Canceled()
    job_id, token = claim(sessions, settings)
    transfer(sessions, settings, job_id, token, CancelDrive, FakeTelegram)
    with sessions() as session:
        assert session.get(Job, queued).status == "canceled"
    assert not transfer_path(settings, job_id, token).parent.exists()


def test_paths_never_use_untrusted_drive_names(settings):
    with pytest.raises(ValueError):
        transfer_path(settings, "../../outside", "invalid")
    assert settings.temp_dir.is_relative_to(Path(settings.temp_dir.parent))
