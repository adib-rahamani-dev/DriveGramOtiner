import hashlib
import random
import uuid
from datetime import timedelta

from sqlalchemy import func, or_, select

from drivegram.errors import ServiceError
from drivegram.models import Control, Job, OAuthToken, utcnow

ACTIVE = ("downloading", "uploading")
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mpeg", ".mpg", ".ts")


def version_key(item):
    if item.get("md5Checksum"):
        return f"md5:{item['md5Checksum']}:{item.get('size', '0')}"
    return f"v:{item.get('version', item.get('modifiedTime', 'unknown'))}"


def current_scope(session, settings):
    token = session.get(OAuthToken, 1)
    generation = token.generation if token else "none"
    return hashlib.sha256((settings.google_drive_folder_id + ":" + generation).encode()).hexdigest()


def control_lock(session):
    return session.execute(select(Control).where(Control.id == 1).with_for_update()).scalar_one()


def record_scan(session, items, scope, settings):
    control = control_lock(session)
    baseline = control.baseline_scope != scope
    existing = {(j.drive_file_id, j.version_key): j for j in session.scalars(select(Job))}
    added = 0
    for item in items:
        if not (item.get("mimeType", "").startswith("video/")
                or item.get("name", "").lower().endswith(VIDEO_EXTENSIONS)):
            continue
        pair = (item["id"], version_key(item))
        if pair in existing:
            previous = existing[pair]
            if previous.source_scope != scope and previous.status not in (*ACTIVE, "completed") and not previous.needs_review:
                previous.source_scope = scope
                previous.status = "discovered"
                previous.cancel_requested = False
            continue
        size = int(item.get("size", 0))
        oversized = size > settings.max_file_size_bytes
        new_job = Job(
            id=str(uuid.uuid4()), drive_file_id=pair[0], version_key=pair[1], source_scope=scope,
            original_name=item["name"], mime_type=item["mimeType"], size_bytes=size,
            md5_checksum=item.get("md5Checksum"),
            status="failed" if oversized else ("queued" if control.auto_sync and not baseline else "discovered"),
            error_code="too_large" if oversized else None,
            error_message="حجم فایل از سقف تنظیم‌شده بیشتر است." if oversized else None,
        )
        session.add(new_job)
        existing[pair] = new_job
        added += 1
    control.baseline_scope = scope
    control.last_scan_at = utcnow()
    control.scan_error = None
    return added


def claim_job(session, settings, scope):
    # All claimers serialize on this durable row, enforcing a GLOBAL concurrency cap.
    control = control_lock(session)
    now = utcnow()
    if control.pair_hash and control.pair_expires_at and control.pair_expires_at > now:
        return None
    if control.telegram_retry_at and control.telegram_retry_at > now:
        return None
    count = session.scalar(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE)))
    if count >= settings.max_concurrent_transfers:
        return None
    job = session.execute(select(Job).where(
        Job.status == "queued", Job.source_scope == scope, Job.cancel_requested.is_(False),
        or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now),
    ).order_by(Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1)).scalar_one_or_none()
    if job is None:
        return None
    job.status = "downloading"
    job.attempts += 1
    job.claim_token = str(uuid.uuid4())
    job.lease_until = now + timedelta(seconds=settings.lease_seconds)
    job.bytes_downloaded = 0
    job.error_code = job.error_message = None
    session.flush()
    return job.id, job.claim_token


def recover_stale(session, settings):
    control_lock(session)
    jobs = session.scalars(select(Job).where(
        Job.status.in_(ACTIVE), or_(Job.lease_until.is_(None), Job.lease_until < utcnow())
    ).with_for_update()).all()
    for job in jobs:
        if job.status == "uploading":
            job.status = "failed"
            job.needs_review = True
            job.error_code = "upload_unknown"
            job.error_message = "worker هنگام ارسال قطع شد؛ قبل از ارسال مجدد گفتگوی مقصد را بررسی کنید."
        elif job.cancel_requested:
            job.status = "canceled"
        elif job.attempts >= settings.max_attempts:
            job.status = "failed"
            job.error_code = "attempts_exhausted"
            job.error_message = "تعداد تلاش‌ها به سقف رسید."
        else:
            job.status = "queued"
            job.next_attempt_at = utcnow() + timedelta(seconds=settings.retry_base_seconds)
            job.bytes_downloaded = 0
        job.claim_token = None
        job.lease_until = None
    return len(jobs)


def finish_error(session, job, error, settings):
    job.error_code, job.error_message = error.code, error.message
    job.needs_review = error.ambiguous
    job.claim_token = None
    job.lease_until = None
    if error.code == "canceled" or (job.cancel_requested and not error.ambiguous):
        job.status = "canceled"
    elif error.retryable and not error.ambiguous and job.attempts < settings.max_attempts:
        job.status = "queued"
        delay = max(error.retry_after, min(3600, settings.retry_base_seconds * 2 ** (job.attempts - 1)))
        job.next_attempt_at = utcnow() + timedelta(seconds=delay + random.uniform(0, delay * 0.1))
    else:
        job.status = "failed"
    if error.code == "telegram_rate_limit":
        control_lock(session).telegram_retry_at = utcnow() + timedelta(seconds=error.retry_after)


def queue_selected(session, job, settings, *, reviewed=False):
    if job.status not in {"discovered", "failed", "canceled"}:
        raise ServiceError("invalid_state", "این کار در وضعیت قابل ارسال نیست.")
    if job.needs_review and not reviewed:
        raise ServiceError("review_required", "نتیجه ارسال نامشخص است؛ ابتدا گفتگوی مقصد را بررسی کنید.")
    if job.source_scope != current_scope(session, settings):
        raise ServiceError("old_source", "این فایل متعلق به اتصال یا پوشه قبلی است؛ دوباره اسکن کنید.")
    if job.size_bytes > settings.max_file_size_bytes:
        raise ServiceError("too_large", "حجم فایل از سقف تنظیم‌شده بیشتر است.")
    job.status = "queued"
    job.cancel_requested = job.needs_review = False
    job.attempts = job.bytes_downloaded = 0
    job.error_code = job.error_message = job.next_attempt_at = None


def cancel_job(job):
    if job.status == "uploading":
        raise ServiceError("upload_in_progress", "ارسال شروع شده و لغو امن آن ممکن نیست؛ منتظر نتیجه بمانید.")
    if job.status not in {"discovered", "queued", "downloading", "failed"}:
        raise ServiceError("invalid_state", "این کار قابل لغو نیست.")
    if job.status == "downloading":
        job.cancel_requested = True
    else:
        job.status = "canceled"
