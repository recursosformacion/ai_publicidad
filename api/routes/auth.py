"""OSAP login handoff for the advertising administration panel."""

from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

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


@router.post("/auth/session", include_in_schema=False)
async def auth_session(request: Request) -> Response:
    settings = get_settings()
    allowed = {
        item.strip().rstrip("/")
        for item in settings.admin_handoff_origins.split(",")
        if item.strip()
    }
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin or origin not in allowed:
        return JSONResponse(status_code=403, content={"detail": "origen de handoff no permitido"})
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        return JSONResponse(
            status_code=415,
            content={"detail": "se requiere application/x-www-form-urlencoded"},
        )
    body = await request.body()
    if len(body) > 16384:
        return JSONResponse(status_code=413, content={"detail": "solicitud demasiado grande"})
    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"detail": "formulario inválido"})
    token = (fields.get("token") or [""])[0].strip()
    next_path = (fields.get("next") or ["/admin"])[0].strip() or "/admin"
    if not token:
        return JSONResponse(status_code=400, content={"detail": "falta el token de usuario"})
    user = verify_osap_admin(token)
    if user is None:
        return RedirectResponse("/auth/login?error=session", status_code=303)
    response = RedirectResponse(
        safe_next(next_path, f"{settings.public_base_url.rstrip('/')}/admin"),
        status_code=303,
    )
    set_session_cookie(response, user)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
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
