from __future__ import annotations

from types import SimpleNamespace

from api.main import app
from application.auth import SESSION_MAX_AGE


def _settings():
    return SimpleNamespace(
        admin_handoff_origins="https://app.openmusicrepository.com",
        public_base_url="https://ads.openmusicrepository.com",
        osap_public_url="https://app.openmusicrepository.com",
        session_secret="test-session-secret",
        service_token="",
    )


def test_admin_handoff_post_sets_short_lived_http_only_cookie(client, monkeypatch):
    monkeypatch.setattr("api.routes.auth.get_settings", _settings)
    monkeypatch.setattr("application.auth.get_settings", _settings)
    monkeypatch.setattr(
        "api.routes.auth.verify_osap_admin",
        lambda token: {"user_id": "admin-1", "roles": ["admin"], "name": "Admin"},
    )
    response = client.post(
        "/auth/session",
        headers={"Origin": "https://app.openmusicrepository.com"},
        data={"token": "user-access-token", "next": "/admin"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    cookie = response.headers["set-cookie"].lower()
    assert "ai_publicidad_session=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert f"max-age={SESSION_MAX_AGE}" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_admin_handoff_rejects_untrusted_origin(client, monkeypatch):
    monkeypatch.setattr("api.routes.auth.get_settings", _settings)
    response = client.post(
        "/auth/session",
        headers={"Origin": "https://attacker.example"},
        data={"token": "user-access-token", "next": "/admin"},
        follow_redirects=False,
    )
    assert response.status_code == 403
