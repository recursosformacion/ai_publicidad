"""Serve a local-only visual lab for area-aware ad composition."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from infrastructure.config import get_settings

router = APIRouter(tags=["layout-lab"])
LAYOUT_LAB_HTML_PATH = Path(__file__).resolve().parents[1] / "static" / "layout_lab.html"


@router.get("/layout-lab", response_class=FileResponse, include_in_schema=False)
def layout_lab() -> FileResponse:
    """The lab creates real test delivery/impression records, so never expose it in production."""
    if get_settings().env == "production":
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(LAYOUT_LAB_HTML_PATH, media_type="text/html; charset=utf-8")
