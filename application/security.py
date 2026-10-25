"""Service authentication and safe destination validation."""

import hmac
from urllib.parse import urlparse

from fastapi import Header, HTTPException, status

from infrastructure.config import get_settings


def require_service_token(x_osap_service_token: str = Header(default="")) -> None:
    settings = get_settings()
    if settings.env != "production" and not settings.service_token:
        return
    if not settings.service_token or not hmac.compare_digest(x_osap_service_token, settings.service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service credentials")


def validate_destination(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Destination must be an absolute HTTP(S) URL without embedded credentials")
    return url
