"""OSAP user sessions for the advertising administration panel."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request, status

from infrastructure.config import get_settings

SESSION_COOKIE = "ai_publicidad_session"
SESSION_MAX_AGE = 7 * 24 * 3600


def _secret() -> str:
    settings = get_settings()
    return settings.session_secret or settings.service_token or "ai-publicidad-dev-session"


def _session_payload(user: dict[str, Any]) -> str:
    data = {
        "user": {
            "user_id": user.get("user_id"),
            "roles": user.get("roles") or [],
            "name": user.get("name"),
            "email": user.get("email"),
        },
        "exp": int(time.time()) + SESSION_MAX_AGE,
    }
    raw = base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    ).rstrip(b"=")
    signature = hmac.new(_secret().encode(), raw, hashlib.sha256).hexdigest()
    return f"{raw.decode()}.{signature}"


def _session_user(request: Request) -> dict[str, Any] | None:
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw or "." not in raw:
        return None
    payload, signature = raw.rsplit(".", 1)
    expected = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < int(time.time()):
        return None
    user = data.get("user")
    return user if isinstance(user, dict) and user.get("user_id") else None


def current_admin(request: Request) -> dict[str, Any] | None:
    user = _session_user(request)
    if not user:
        return None
    roles = {str(role) for role in (user.get("roles") or [])}
    return user if "admin" in roles else None


def require_admin_session(request: Request) -> None:
    settings = get_settings()
    if settings.env == "test":
        return
    if current_admin(request) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OSAP admin session required",
        )


def verify_osap_admin(token: str) -> dict[str, Any] | None:
    token = token.removeprefix("Bearer ").strip()
    if not token:
        return None
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.auth_base_url.rstrip('/')}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    roles = {str(role) for role in (data.get("roles") or [])}
    return data if data.get("user_id") and "admin" in roles else None


def safe_next(value: str, fallback: str) -> str:
    """Allow only local paths or the configured public origin."""
    settings = get_settings()
    if value.startswith("/") and not value.startswith("//"):
        return value
    parsed = urlsplit(value)
    public = urlsplit(settings.public_base_url)
    if parsed.scheme == public.scheme and parsed.netloc == public.netloc:
        return value
    return fallback


def set_session_cookie(response: Any, user: dict[str, Any]) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        _session_payload(user),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path="/",
    )
