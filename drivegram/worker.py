import logging
import shutil
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select

from drivegram.config import get_settings
from drivegram.db import database
from drivegram.errors import Canceled, LostClaim, ServiceError
from drivegram.google import GoogleDrive
from drivegram.models import Job, utcnow
from drivegram.pairing import destination_settings, poll_pairing_once
from drivegram.queue import claim_job, control_lock, current_scope, finish_error, record_scan, recover_stale
from drivegram.security import configure_logging, safe_filename
from drivegram.telegram import Telegram

log = logging.getLogger("drivegram.worker")


def transfer_path(settings, job_id, claim_token, name="media.mp4"):
    import uuid
    # Untrusted names cannot affect directories and retain their original extension.
    job_id, claim_token = str(uuid.UUID(job_id)), str(uuid.UUID(claim_token))
    root = settings.temp_dir.resolve()
    path = root / job_id / claim_token / safe_filename(name)
    if not path.is_relative_to(root):
        raise ValueError("Invalid temporary path")
    return path


def owned_job(session, job_id, claim):
    job = session.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one()
    if job.claim_token != claim or job.status not in {"downloading", "uploading"}:
        raise LostClaim()
    if job.lease_until is None or job.lease_until < utcnow():
        raise LostClaim()
    return job


def transfer(sessions, settings, job_id, claim, drive_factory=GoogleDrive, telegram_factory=Telegram):
    path = transfer_path(settings, job_id, claim)
    stopped, lost = threading.Event(), threading.Event()
    keep_file = False
    last_progress = [0.0]

    def heartbeat():
        last_ok = time.monotonic()
        while not stopped.wait(min(10, settings.lease_seconds / 4)):
            try:
                with sessions.begin() as session:
                    job = owned_job(session, job_id, claim)
                    job.lease_until = utcnow() + timedelta(seconds=settings.lease_seconds)
                last_ok = time.monotonic()
            except LostClaim:
                lost.set()
                return
            except Exception:
                if time.monotonic() - last_ok >= settings.lease_seconds / 2:
                    lost.set()
                    return

    def progress(count):
        if lost.is_set():
            raise LostClaim()
        if time.monotonic() - last_progress[0] < 0.5:
            return
        with sessions.begin() as session:
            job = owned_job(session, job_id, claim)
            if job.cancel_requested:
                raise Canceled()
            job.bytes_downloaded = count
        last_progress[0] = time.monotonic()

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    drive = telegram = None
    sending = False
    try:
        with sessions() as session:
            snapshot = session.get(Job, job_id)
            target_settings = destination_settings(session, settings)
        path = transfer_path(settings, job_id, claim, snapshot.original_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        drive, telegram = drive_factory(settings, sessions), telegram_factory(target_settings)
        drive.download(snapshot, path, progress)
        if lost.is_set():
            raise LostClaim()
        with sessions.begin() as session:
            job = owned_job(session, job_id, claim)
            if job.cancel_requested:
                raise Canceled()
            if current_scope(session, settings) != job.source_scope:
                raise ServiceError("source_changed", "اتصال Google تغییر کرده است؛ دوباره اسکن کنید.")
            job.bytes_downloaded = job.size_bytes
            job.telegram_chat_id = target_settings.telegram_target_id
            job.status = "uploading"
        sending = True
        chat_id, message_id, file_id = telegram.send(path, snapshot.original_name)
        # Commit success before cleanup. A lost commit must remain ambiguous on restart.
        with sessions.begin() as session:
            job = owned_job(session, job_id, claim)
            job.status = "completed"
            job.telegram_chat_id, job.telegram_message_id, job.telegram_file_id = chat_id, message_id, file_id
            job.completed_at = utcnow()
            job.claim_token = job.lease_until = None
        sending = False
        log.info("Transfer completed job=%s", job_id)
    except LostClaim:
        keep_file = sending
        log.warning("Claim lost job=%s", job_id)
    except ServiceError as error:
        keep_file = error.ambiguous
        try:
            with sessions.begin() as session:
                control_lock(session)
                job = owned_job(session, job_id, claim)
                finish_error(session, job, error, settings)
            log.warning("Transfer stopped job=%s code=%s", job_id, error.code)
        except Exception:
            keep_file = sending or keep_file
            log.error("Could not persist error job=%s; lease recovery required", job_id)
    except Exception:
        keep_file = sending
        try:
            with sessions.begin() as session:
                control_lock(session)
                job = owned_job(session, job_id, claim)
                finish_error(session, job, ServiceError(
                    "upload_unknown" if sending else "worker_error",
                    "نتیجه ارسال نامشخص است؛ گفتگوی مقصد را بررسی کنید." if sending else "خطای پردازش؛ تلاش محدود مجدد انجام می‌شود.",
                    retryable=not sending, ambiguous=sending,
                ), settings)
        except Exception:
            pass
        log.error("Transfer interrupted job=%s", job_id)
    finally:
        stopped.set()
        thread.join(timeout=15)
        for service in (drive, telegram):
            if service:
                service.close()
        if not keep_file:
            shutil.rmtree(path.parent, ignore_errors=True)


def cleanup(sessions, settings):
    root = settings.temp_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with sessions.begin() as session:
        control_lock(session)
        keep = {j.id for j in session.scalars(select(Job).where(
            (Job.status.in_(("downloading", "uploading"))) | Job.needs_review.is_(True)))}
        # Hold the same lock as claimers: cleanup cannot race a newly claimed job.
        import uuid
        for directory in root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                uuid.UUID(directory.name)
            except ValueError:
                continue
            if directory.name not in keep:
                shutil.rmtree(directory, ignore_errors=True)


def scan_once(sessions, settings, drive_factory=GoogleDrive):
    with sessions() as session:
        scope = current_scope(session, settings)
    drive = drive_factory(settings, sessions)
    try:
        items = drive.list_files()
        with sessions.begin() as session:
            control_lock(session)
            if current_scope(session, settings) != scope:
                return 0
            return record_scan(session, items, scope, settings)
    finally:
        drive.close()


def scanner(sessions, settings, stopping):
    wait = 0
    while not stopping.wait(wait):
        wait = settings.poll_interval_seconds
        if settings.google_configured:
            try:
                added = scan_once(sessions, settings)
                log.info("Scan complete added=%d", added)
            except ServiceError as error:
                wait = max(wait, error.retry_after)
                with sessions.begin() as session:
                    control = control_lock(session)
                    control.scan_error = error.message
            except Exception:
                log.error("Scan failed; check database and configuration")


def main():
    settings = get_settings()
    configure_logging(settings)
    _, sessions = database()
    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    scan_thread = threading.Thread(target=scanner, args=(sessions, settings, stopping), daemon=True)
    scan_thread.start()
    futures = set()
    last_check = 0
    telegram_ready = False
    with ThreadPoolExecutor(max_workers=settings.max_concurrent_transfers) as executor:
        while not stopping.is_set():
            try:
                with sessions.begin() as session:
                    control = control_lock(session)
                    disk = shutil.disk_usage(settings.temp_dir)
                    control.worker_heartbeat = utcnow()
                    control.worker_disk_free, control.worker_disk_total = disk.free, disk.total
                    recover_stale(session, settings)
                cleanup(sessions, settings)
                settings.worker_heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
                settings.worker_heartbeat_path.touch()
                if settings.telegram_bot_token.get_secret_value() and poll_pairing_once(sessions, settings):
                    telegram_ready, last_check = False, 0
                with sessions() as session:
                    target_settings = destination_settings(session, settings)
                if time.monotonic() - last_check >= 60:
                    telegram_ready = False
                    last_check = time.monotonic()
                    error_message = "نیاز به تنظیم اتصال تلگرام."
                    if target_settings.telegram_configured:
                        telegram = Telegram(target_settings)
                        try:
                            telegram.check()
                            telegram_ready, error_message = True, None
                        except ServiceError as error:
                            error_message = error.message
                        finally:
                            telegram.close()
                    with sessions.begin() as session:
                        control = control_lock(session)
                        control.telegram_ok, control.telegram_error = telegram_ready, error_message
                        control.telegram_checked_at = utcnow()
                futures = {f for f in futures if not f.done()}
                if telegram_ready and settings.google_configured and len(futures) < settings.max_concurrent_transfers:
                    with sessions.begin() as session:
                        claimed = claim_job(session, settings, current_scope(session, settings))
                    if claimed:
                        futures.add(executor.submit(transfer, sessions, settings, *claimed))
            except Exception:
                log.error("Worker iteration failed; retrying without logging credentials")
            stopping.wait(1)
    scan_thread.join(timeout=5)


if __name__ == "__main__":
    main()
