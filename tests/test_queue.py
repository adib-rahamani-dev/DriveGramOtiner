from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from drivegram.errors import ServiceError
from drivegram.models import Control, Job, utcnow
from drivegram.queue import (
    cancel_job,
    claim_job,
    current_scope,
    finish_error,
    queue_selected,
    record_scan,
    recover_stale,
)


def item(file_id="one", checksum="a" * 32):
    return {"id": file_id, "name": "movie.mp4", "mimeType": "video/mp4", "size": "4", "md5Checksum": checksum}


def test_first_scan_baseline_dedup_and_changed_content(sessions, settings):
    with sessions.begin() as session:
        session.get(Control, 1).auto_sync = True
        scope = current_scope(session, settings)
        assert record_scan(session, [item()], scope, settings) == 1
    with sessions.begin() as session:
        first = session.scalar(select(Job))
        assert first.status == "discovered"
        first.status = "completed"
        assert record_scan(session, [item(), item("two")], scope, settings) == 1
    with sessions.begin() as session:
        assert record_scan(session, [item(), item("two"), item(checksum="b" * 32)], scope, settings) == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 3
        jobs = session.scalars(select(Job)).all()
        assert sorted(j.status for j in jobs) == ["completed", "queued", "queued"]


def test_unique_constraint_is_final_duplicate_guard(sessions, settings, queued):
    with sessions() as session:
        original = session.get(Job, queued)
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(Job(id="different", drive_file_id=original.drive_file_id, version_key=original.version_key,
                        source_scope=original.source_scope, original_name="duplicate", mime_type="video/mp4", size_bytes=4))


def test_restart_requeues_download_but_marks_upload_ambiguous(sessions, settings, queued):
    with sessions.begin() as session:
        claimed = claim_job(session, settings, current_scope(session, settings))
    with sessions.begin() as session:
        job = session.get(Job, queued)
        job.lease_until = utcnow() - timedelta(seconds=1)
        assert recover_stale(session, settings) == 1
        assert job.status == "queued"
    with sessions.begin() as session:
        job = session.get(Job, queued)
        job.next_attempt_at = None
        assert claim_job(session, settings, current_scope(session, settings)) != claimed
    with sessions.begin() as session:
        job = session.get(Job, queued)
        job.status = "uploading"
        job.lease_until = utcnow() - timedelta(seconds=1)
        recover_stale(session, settings)
        assert job.status == "failed" and job.needs_review
        with pytest.raises(ServiceError, match="نامشخص"):
            queue_selected(session, job, settings)


def test_recovery_does_not_steal_live_worker(sessions, settings, queued):
    with sessions.begin() as session:
        claim_job(session, settings, current_scope(session, settings))
    with sessions.begin() as session:
        assert recover_stale(session, settings) == 0
        assert session.get(Job, queued).status == "downloading"


def test_retry_after_and_attempt_cap(sessions, settings, queued):
    with sessions.begin() as session:
        claim_job(session, settings, current_scope(session, settings))
        job = session.get(Job, queued)
        start = utcnow()
        finish_error(session, job, ServiceError("telegram_rate_limit", "rate", retryable=True, retry_after=120), settings)
        assert job.status == "queued"
        assert job.next_attempt_at >= start + timedelta(seconds=120)
        assert session.get(Control, 1).telegram_retry_at >= start + timedelta(seconds=120)
        job.attempts = settings.max_attempts
        finish_error(session, job, ServiceError("network", "error", retryable=True), settings)
        assert job.status == "failed"


def test_cancel_rules(sessions, settings, queued):
    with sessions.begin() as session:
        job = session.get(Job, queued)
        job.status = "uploading"
        with pytest.raises(ServiceError):
            cancel_job(job)
        job.status = "downloading"
        cancel_job(job)
        assert job.cancel_requested
        job.status = "queued"
        cancel_job(job)
        assert job.status == "canceled"


def test_scope_change_baselines_and_makes_unfinished_file_selectable(sessions, settings):
    with sessions.begin() as session:
        record_scan(session, [item()], "old-scope", settings)
    with sessions.begin() as session:
        record_scan(session, [item(), item("new")], "new-scope", settings)
        jobs = session.scalars(select(Job)).all()
        assert all(j.source_scope == "new-scope" and j.status == "discovered" for j in jobs)


@pytest.mark.postgres
def test_atomic_claim_and_global_concurrency_under_competing_workers(sessions, settings):
    if sessions.kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL required to exercise FOR UPDATE semantics")
    settings.max_concurrent_transfers = 2
    with sessions.begin() as session:
        scope = current_scope(session, settings)
        control = session.get(Control, 1)
        control.baseline_scope, control.auto_sync = scope, True
        record_scan(session, [item(str(i)) for i in range(10)], scope, settings)
    barrier = Barrier(8)
    def claimant(_):
        barrier.wait()
        with sessions.begin() as session:
            return claim_job(session, settings, scope)
    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = [r for r in executor.map(claimant, range(8)) if r]
    assert len(claims) == 2
    assert len({r[0] for r in claims}) == 2
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Job).where(Job.status == "downloading")) == 2
