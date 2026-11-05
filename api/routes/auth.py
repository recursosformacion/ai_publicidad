"""OSAP login handoff for the advertising administration panel."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from application.auth import (
    SESSION_COOKIE,
    safe_next,
    set_session_cookie,
    verify_osap_admin,
)
from infrastructure.config import get_settings

router = APIRouter(tags=["auth"])


@router.get("/auth/login", include_in_schema=False)
def login() -> RedirectResponse:
    settings = get_settings()
    return RedirectResponse(
        f"{settings.osap_public_url.rstrip('/')}/?auth=login&return_to=ads",
        status_code=303,
    )


@router.get("/auth/session", include_in_schema=False)
def auth_session(token: str = "", next: str = "/admin") -> RedirectResponse:
    user = verify_osap_admin(token)
    if user is None:
        return RedirectResponse("/auth/login?error=session", status_code=303)
    settings = get_settings()
    response = RedirectResponse(
        safe_next(next, f"{settings.public_base_url.rstrip('/')}/admin"),
        status_code=303,
    )
    set_session_cookie(response, user)
    return response


@router.get("/auth/logout", include_in_schema=False)
def logout(request: Request) -> RedirectResponse:
    settings = get_settings()
    response = RedirectResponse(
        f"{settings.osap_public_url.rstrip('/')}/",
        status_code=303,
    )
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
