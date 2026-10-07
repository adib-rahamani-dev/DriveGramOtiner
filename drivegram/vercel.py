"""Vercel serves the control plane; transfers run on a persistent cloud worker."""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from drivegram.app import create_app
from drivegram.config import Settings


def deployment_app(environ=None):
    env = os.environ if environ is None else environ
    required = ("DATABASE_URL", "SESSION_SECRET", "TOKEN_ENCRYPTION_KEY")
    configured = all(env.get(key) for key in required) and bool(
        env.get("ADMIN_PASSWORD_HASH") or env.get("ADMIN_PASSWORD"))
    if configured:
        # Never load the developer's local .env on the public deployment.
        settings = Settings(_env_file=None, remote_worker=True, database_no_pool=True, cookie_secure=True)
        if not settings.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("Vercel requires persistent PostgreSQL via psycopg")
        from drivegram.db import make_database
        _, sessions = make_database(settings.database_url.get_secret_value(), no_pool=True)
        return create_app(settings, sessions)

    app = FastAPI(title="DriveGram", docs_url=None, redoc_url=None, openapi_url=None)
    base = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=base / "static"), name="static")
    templates = Jinja2Templates(directory=base / "templates")

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Strict-Transport-Security": "max-age=31536000",
            "Content-Security-Policy": "default-src 'self'; style-src 'self'; frame-ancestors 'none'"})
        return response

    @app.get("/")
    def pending(request: Request):
        return templates.TemplateResponse(request, "deployment.html", {})

    @app.get("/healthz")
    def health():
        return JSONResponse({"status": "setup_required", "transfers_ready": False}, status_code=503)

    return app


app = deployment_app()
