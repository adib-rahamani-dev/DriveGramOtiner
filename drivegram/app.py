import hashlib
import hmac
import secrets
import shutil
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from starlette.middleware.sessions import SessionMiddleware

from drivegram.config import get_settings
from drivegram.db import database
from drivegram.errors import ServiceError
from drivegram.google import SCOPE
from drivegram.models import Control, Job, LoginAttempt, OAuthToken, utcnow
from drivegram.queue import cancel_job, control_lock, current_scope, queue_selected
from drivegram.security import admin_hash, auth_fingerprint, check_password, cipher, configure_logging
from drivegram.telegram import message_link

LABELS = {"discovered": "کشف‌شده", "queued": "در صف", "downloading": "در حال دانلود",
          "uploading": "در حال ارسال", "completed": "تکمیل‌شده", "failed": "ناموفق", "canceled": "لغوشده"}


def create_app(settings=None, sessions=None):
    settings = settings or get_settings()
    if sessions is None:
        _, sessions = database()
    password_hash = admin_hash(settings)
    fingerprint = auth_fingerprint(settings, password_hash)
    secret = settings.session_secret.get_secret_value()
    if len(secret) < 32:
        raise ValueError("SESSION_SECRET must have at least 32 characters")
    configure_logging(settings)
    app = FastAPI(title="DriveGram", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=secret, session_cookie="drivegram_admin",
                       max_age=8 * 3600, same_site="lax", https_only=settings.cookie_secure)
    base = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=base / "static"), name="static")
    templates = Jinja2Templates(directory=base / "templates")

    @app.middleware("http")
    async def headers(request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            # Exceptions can include OAuth code or bot URLs: never return/log their raw text.
            response = JSONResponse({"error": "خطای داخلی؛ اتصال دیتابیس و تنظیمات را بررسی کنید."}, status_code=500)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                       "img-src 'self' data:; frame-ancestors 'none'; form-action 'self' https://accounts.google.com",
        })
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def authorized(request):
        if request.session.get("admin") != fingerprint:
            raise HTTPException(401, "ابتدا وارد پنل شوید.")

    def csrf(request, token):
        expected = request.session.get("csrf", "")
        if not expected or not hmac.compare_digest(expected, token or ""):
            raise HTTPException(403, "درخواست معتبر نیست؛ صفحه را تازه کنید.")

    def csrf_token(request):
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(32)
        return request.session["csrf"]

    @app.exception_handler(ServiceError)
    async def service_error(request, error):
        return JSONResponse({"error": error.message}, status_code=409)

    @app.get("/healthz")
    def health():
        try:
            with sessions() as session:
                session.execute(text("SELECT 1"))
                if not session.get(Control, 1):
                    return JSONResponse({"status": "migration_required"}, status_code=503)
            return {"status": "ok"}
        except Exception:
            return JSONResponse({"status": "database_unavailable"}, status_code=503)

    @app.get("/login")
    def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"csrf": csrf_token(request), "error": None})

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...), csrf_value: str = Form(...)):
        csrf(request, csrf_value)
        key = hashlib.sha256((request.client.host if request.client else "local").encode()).hexdigest()
        with sessions.begin() as session:
            control_lock(session)
            attempt = session.get(LoginAttempt, key)
            now = utcnow()
            if attempt is None:
                attempt = LoginAttempt(key=key, failures=0, window_start=now)
                session.add(attempt)
            if attempt.window_start < now - timedelta(minutes=15):
                attempt.failures, attempt.window_start = 0, now
            if attempt.failures >= 5:
                return templates.TemplateResponse(request, "login.html",
                    {"csrf": csrf_token(request), "error": "تلاش‌های زیادی انجام شده؛ ۱۵ دقیقه بعد امتحان کنید."}, status_code=429)
            valid = len(password) <= 1024 and len(username) <= 128 and check_password(username, password, settings, password_hash)
            attempt.failures = 0 if valid else attempt.failures + 1
        if not valid:
            return templates.TemplateResponse(request, "login.html",
                {"csrf": csrf_token(request), "error": "نام کاربری یا رمز عبور اشتباه است."}, status_code=401)
        request.session.clear()
        request.session["admin"] = fingerprint
        csrf_token(request)
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request, csrf_value: str = Form(...)):
        csrf(request, csrf_value)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/")
    def panel(request: Request):
        if request.session.get("admin") != fingerprint:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request, "panel.html", {"csrf": csrf_token(request),
            "oauth_notice": request.session.pop("oauth_notice", None)})

    @app.get("/api/status")
    def status(request: Request, page: int = 1):
        authorized(request)
        page = max(1, page)
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(settings.temp_dir)
        with sessions() as session:
            control = session.get(Control, 1)
            token = session.get(OAuthToken, 1)
            scope = current_scope(session, settings)
            total = session.scalar(select(func.count()).select_from(Job))
            rows = session.scalars(select(Job).order_by(Job.created_at.desc(), Job.id).offset((page - 1) * 30).limit(30)).all()
            count = session.scalar(select(func.count()).select_from(Job).where(Job.status == "queued"))
            heartbeat_ok = bool(control.worker_heartbeat and control.worker_heartbeat > utcnow() - timedelta(seconds=90))
            google_status = "نیاز به تنظیم اتصال"
            if settings.google_configured and token:
                if control.scan_error:
                    google_status = control.scan_error
                elif control.baseline_scope == scope and control.last_scan_at:
                    google_status = "متصل؛ آخرین اسکن موفق"
                else:
                    google_status = "مجوز ذخیره شده؛ منتظر اسکن اولیه"
            tg_recent = bool(control.telegram_checked_at and control.telegram_checked_at > utcnow() - timedelta(seconds=120))
            return {"google": google_status,
                    "google_can_connect": bool(settings.google_client_id and settings.google_client_secret.get_secret_value()
                                               and settings.token_encryption_key.get_secret_value()),
                    "telegram": ("متصل؛ ربات و کانال تأیید شدند" if control.telegram_ok and tg_recent
                                 else (control.telegram_error or "نیاز به تنظیم اتصال")),
                    "auto_sync": control.auto_sync, "worker_ok": heartbeat_ok,
                    "last_scan": control.last_scan_at, "queue_count": count, "disk_free": disk.free,
                    "disk_total": disk.total, "page": page, "pages": max(1, (total + 29) // 30),
                    "jobs": [{"id": j.id, "name": j.original_name, "size": j.size_bytes,
                              "status": j.status, "label": LABELS[j.status], "downloaded": j.bytes_downloaded,
                              "attempts": j.attempts, "error": j.error_message, "review": j.needs_review,
                              "completed_at": j.completed_at, "created_at": j.created_at,
                              "link": message_link(j.telegram_chat_id, j.telegram_message_id),
                              "can_queue": j.status in {"discovered", "failed", "canceled"} and not j.needs_review
                                           and j.source_scope == scope,
                              "can_cancel": j.status in {"discovered", "queued", "downloading", "failed"}}
                             for j in rows]}

    @app.post("/api/sync")
    async def toggle(request: Request):
        authorized(request)
        data = await request.json()
        csrf(request, request.headers.get("X-CSRF-Token"))
        if not isinstance(data.get("enabled"), bool):
            raise HTTPException(400, "مقدار تنظیم معتبر نیست.")
        with sessions.begin() as session:
            control = control_lock(session)
            if data["enabled"] and control.baseline_scope != current_scope(session, settings):
                raise ServiceError("baseline_required", "ابتدا اتصال Google و اولین اسکن را تکمیل کنید.")
            control.auto_sync = data["enabled"]
        return {"ok": True}

    @app.post("/api/jobs/action")
    async def actions(request: Request):
        authorized(request)
        csrf(request, request.headers.get("X-CSRF-Token"))
        data = await request.json()
        ids = data.get("ids", [])
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) for i in ids):
            raise HTTPException(400, "فهرست کارها معتبر نیست.")
        with sessions.begin() as session:
            control_lock(session)
            for job_id in set(ids):
                job = session.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one_or_none()
                if job is None:
                    raise HTTPException(404, "کار یافت نشد.")
                if data.get("action") == "queue":
                    queue_selected(session, job, settings)
                elif data.get("action") == "cancel":
                    cancel_job(job)
                elif data.get("action") == "review_retry":
                    if not job.needs_review or data.get("confirmation") != "checked_no_message":
                        raise ServiceError("review_required", "ابتدا مطمئن شوید هیچ پیام متناظری در کانال ارسال نشده است.")
                    queue_selected(session, job, settings, reviewed=True)
                elif data.get("action") == "review_close":
                    if not job.needs_review:
                        raise ServiceError("invalid_state", "این کار نیاز به بررسی ندارد.")
                    job.needs_review = False
                    job.status = "canceled"
                    job.error_message = "بررسی دستی بسته شد؛ ارسال خودکار مجدد انجام نمی‌شود."
                else:
                    raise HTTPException(400, "عملیات معتبر نیست.")
        return {"ok": True}

    @app.post("/oauth/start")
    def oauth_start(request: Request, csrf_value: str = Form(...)):
        authorized(request)
        csrf(request, csrf_value)
        if not settings.google_client_id or not settings.google_client_secret.get_secret_value():
            raise ServiceError("google_setup", "Client ID و Client Secret را در محیط سرور وارد کنید.")
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        request.session["oauth"] = {"state": state, "verifier": verifier, "expires": time.time() + 600}
        import base64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        params = {"client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri,
                  "response_type": "code", "scope": SCOPE, "access_type": "offline", "prompt": "consent",
                  "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params), status_code=303)

    @app.get("/oauth/callback")
    def oauth_callback(request: Request, state: str = "", code: str = "", error: str = ""):
        authorized(request)
        pending = request.session.pop("oauth", {})
        if not pending or pending.get("expires", 0) < time.time() or not hmac.compare_digest(pending.get("state", ""), state):
            raise HTTPException(400, "درخواست OAuth نامعتبر یا منقضی است.")
        if error or not code:
            request.session["oauth_notice"] = "مجوز Google صادر نشد؛ دوباره تلاش کنید."
            return RedirectResponse("/", status_code=303)
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post("https://oauth2.googleapis.com/token", data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret.get_secret_value(),
                    "code": code, "code_verifier": pending["verifier"],
                    "grant_type": "authorization_code", "redirect_uri": settings.google_redirect_uri,
                })
                data = response.json()
            if response.status_code != 200 or not data.get("refresh_token") or SCOPE not in data.get("scope", "").split():
                raise ValueError()
            encrypted = cipher(settings).encrypt(data["refresh_token"].encode()).decode()
            with sessions.begin() as session:
                control = control_lock(session)
                if session.scalar(select(func.count()).select_from(Job).where(Job.status.in_(("downloading", "uploading")))):
                    raise ServiceError("busy", "برای تغییر اتصال، ابتدا منتظر پایان انتقال‌های فعال بمانید.")
                token = session.get(OAuthToken, 1)
                if not token:
                    token = OAuthToken(id=1)
                    session.add(token)
                token.refresh_encrypted, token.generation = encrypted, secrets.token_hex(32)
                token.updated_at = utcnow()
                control.auto_sync = False
                control.baseline_scope = None
                control.scan_error = None
            request.session["oauth_notice"] = "مجوز ذخیره شد؛ اولین اسکن فقط فایل‌ها را فهرست می‌کند."
        except ServiceError:
            raise
        except Exception:
            request.session["oauth_notice"] = "اتصال Google کامل نشد؛ تنظیمات OAuth و کلید رمزگذاری را بررسی کنید."
        return RedirectResponse("/", status_code=303)

    return app
