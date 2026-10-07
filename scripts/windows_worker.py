"""Run the 50 MB cloud-API worker through Windows' existing network connection."""
import os
from pathlib import Path

from sqlalchemy.engine import make_url

from drivegram.config import get_settings


def prepare():
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    settings = get_settings()
    if settings.telegram_api_mode != "cloud":
        raise ValueError("Windows worker requires cloud mode")
    url = make_url(settings.database_url.get_secret_value())
    if url.host != "db" or url.database != "drivegram":
        raise ValueError("Windows worker requires this project's Compose database")
    os.environ["DATABASE_URL"] = url.set(host="127.0.0.1", port=15432).update_query_dict(
        {"connect_timeout": "5"}).render_as_string(hide_password=False)
    os.environ["TEMP_DIR"] = str(root / "data" / "windows-transfers")
    os.environ["WORKER_HEARTBEAT_PATH"] = str(root / "data" / "windows-worker-heartbeat")
    get_settings.cache_clear()


if __name__ == "__main__":
    if (Path(__file__).resolve().parent.parent / "data" / "google-script-active").exists():
        raise SystemExit("Google Apps Script is active; local Windows transfers are disabled.")
    try:
        prepare()
        from drivegram.worker import main
        main()
    except Exception:
        raise SystemExit("Windows worker stopped; check local services and configuration. Private details suppressed.") from None
