import re

from fastapi.testclient import TestClient

from drivegram.app import create_app


def login(client, settings):
    response = client.get("/login")
    token = re.search('name="csrf_value" value="([^"]+)"', response.text).group(1)
    return client.post("/login", data={"username": settings.admin_username,
        "password": settings.admin_password.get_secret_value(), "csrf_value": token})


def test_admin_only_csrf_and_no_secrets_in_status(sessions, settings):
    with TestClient(create_app(settings, sessions)) as client:
        assert client.get("/api/status").status_code == 401
        assert client.post("/login", data={"username": "admin", "password": "x", "csrf_value": "bad"}).status_code == 403
        signed_in = login(client, settings)
        assert signed_in.status_code == 200
        assert "httponly" in signed_in.history[0].headers.get("set-cookie", "").lower()
        response = client.get("/api/status")
        assert response.status_code == 200
        assert settings.telegram_bot_token.get_secret_value() not in response.text
        assert settings.admin_password.get_secret_value() not in response.text
        assert response.json()["google"] == "نیاز به تنظیم اتصال"
        assert client.post("/api/sync", json={"enabled": True}).status_code == 403
        token = re.search('name="csrf-token" content="([^"]+)"', client.get("/").text).group(1)
        assert client.post("/api/sync", json={"enabled": True}, headers={"X-CSRF-Token": token}).status_code == 409


def test_persistent_login_rate_limit(sessions, settings):
    with TestClient(create_app(settings, sessions)) as client:
        token = re.search('name="csrf_value" value="([^"]+)"', client.get("/login").text).group(1)
        for _ in range(5):
            assert client.post("/login", data={"username": "admin", "password": "bad", "csrf_value": token}).status_code == 401
    with TestClient(create_app(settings, sessions)) as client:
        token = re.search('name="csrf_value" value="([^"]+)"', client.get("/login").text).group(1)
        assert client.post("/login", data={"username": "admin", "password": "bad", "csrf_value": token}).status_code == 429


def test_stale_oauth_state_is_rejected(sessions, settings):
    with TestClient(create_app(settings, sessions)) as client:
        login(client, settings)
        assert client.get("/oauth/callback?state=forged&code=dummy").status_code == 400
