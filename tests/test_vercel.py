from fastapi.testclient import TestClient

from drivegram.app import create_app
from drivegram.models import Control, utcnow
from drivegram.vercel import deployment_app
from tests.test_app import login


def test_unconfigured_deployment_is_honest_and_has_no_private_routes():
    with TestClient(deployment_app({})) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "انتقال فایل‌ها هنوز فعال نیست" in response.text
        assert client.get("/healthz").status_code == 503
        assert client.get("/api/status").status_code == 404
        assert client.post("/api/sync", json={"enabled": True}).status_code == 404
        assert client.get("/static/style.css").status_code == 200
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_remote_panel_reports_worker_disk_without_local_filesystem(sessions, settings, monkeypatch):
    settings.remote_worker = True

    def forbidden(*args, **kwargs):
        raise AssertionError("Remote panel must not access transfer storage")

    monkeypatch.setattr("drivegram.app.shutil.disk_usage", forbidden)
    with sessions.begin() as session:
        control = session.get(Control, 1)
        control.worker_heartbeat = utcnow()
        control.worker_disk_free, control.worker_disk_total = 9876543210, 12345678900
    with TestClient(create_app(settings, sessions)) as client:
        login(client, settings)
        result = client.get("/api/status").json()
        assert result["disk_free"] == 9876543210
        assert result["disk_total"] == 12345678900
        with sessions.begin() as session:
            session.get(Control, 1).worker_heartbeat = None
        assert client.get("/api/status").json()["disk_free"] is None
