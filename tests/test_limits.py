import hashlib

import httpx
import pytest
from sqlalchemy import select

from drivegram.errors import ServiceError
from drivegram.google import GoogleDrive
from drivegram.models import Control, Job
from drivegram.queue import current_scope
from drivegram.worker import scan_once


def test_300_mib_streaming_download_without_whole_file_in_ram(sessions, settings, tmp_path):
    chunk = b"x" * 1024 * 1024
    checksum = hashlib.md5(usedforsecurity=False)
    for _ in range(300):
        checksum.update(chunk)
    meta = {"parents": [settings.google_drive_folder_id], "md5Checksum": checksum.hexdigest(), "size": str(300 * len(chunk))}
    yielded = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(300):
                yielded.append(i)
                yield chunk
    def handler(request):
        if request.url.params.get("alt") == "media":
            return httpx.Response(200, stream=Stream())
        return httpx.Response(200, json=meta)
    drive = GoogleDrive(settings, sessions, httpx.Client(transport=httpx.MockTransport(handler)))
    drive.access, drive.expires = "test", float("inf")
    job = Job(drive_file_id="file123", version_key=f"md5:{checksum.hexdigest()}:{300 * len(chunk)}",
              md5_checksum=checksum.hexdigest(), size_bytes=300 * len(chunk))
    path = tmp_path / "300-mib.mp4"
    progress = []
    drive.download(job, path, progress.append)
    assert path.stat().st_size == 300 * 1024 * 1024
    assert len(yielded) == 300 and len(progress) == 300
    assert progress[-1] == job.size_bytes
    path.unlink()
    drive.close()


def test_failed_paginated_scan_cannot_commit_partial_baseline(sessions, settings):
    class PartialDrive:
        def __init__(self, *args):
            pass
        def list_files(self):
            raise ServiceError("network", "Page two failed", retryable=True)
        def close(self):
            pass
    with pytest.raises(ServiceError):
        scan_once(sessions, settings, PartialDrive)
    with sessions() as session:
        assert session.get(Control, 1).baseline_scope is None
        assert session.scalar(select(Job)) is None


def test_disk_space_limit_before_download(sessions, settings, tmp_path, monkeypatch):
    drive = GoogleDrive(settings, sessions)
    drive.validate_snapshot = lambda _: None
    monkeypatch.setattr("drivegram.google.shutil.disk_usage", lambda _: type("Usage", (), {"free": 0})())
    with pytest.raises(ServiceError) as error:
        drive.download(Job(size_bytes=4), tmp_path / "file", lambda _: None)
    assert error.value.code == "disk_full"
    assert not (tmp_path / "file").exists()
    drive.close()


def test_queue_persists_after_engine_reconnect(sessions, settings, queued):
    from drivegram.queue import claim_job
    engine = sessions.kw["bind"]
    engine.dispose()
    with sessions.begin() as session:
        assert session.get(Job, queued).status == "queued"
        assert claim_job(session, settings, current_scope(session, settings))[0] == queued
