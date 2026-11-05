"""Serve the standalone web administration interface."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["administration-ui"])
STATIC_PATH = Path(__file__).resolve().parents[1] / "static"
ADMIN_HTML_PATH = STATIC_PATH / "admin.html"
FAVICON_PATH = STATIC_PATH / "favicon.ico"


@router.get("/admin", response_class=FileResponse, include_in_schema=False)
def admin_ui() -> FileResponse:
    """Serve the single-page administration UI."""
    return FileResponse(
        ADMIN_HTML_PATH,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@router.get("/favicon.ico", response_class=FileResponse, include_in_schema=False)
def favicon() -> FileResponse:
    """Serve the OSAP favicon for the standalone administration panel."""
    return FileResponse(FAVICON_PATH, media_type="image/x-icon")
