"""Serve the standalone web administration interface."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["administration-ui"])
ADMIN_HTML_PATH = Path(__file__).resolve().parents[1] / "static" / "admin.html"


@router.get("/admin", response_class=FileResponse, include_in_schema=False)
def admin_ui() -> FileResponse:
    """Serve the single-page administration UI."""
    return FileResponse(ADMIN_HTML_PATH, media_type="text/html; charset=utf-8")
