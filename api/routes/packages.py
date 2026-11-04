"""Public, isolated serving of static HTML creative packages."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from application.packages import content_security_policy, resolve_package_file
from infrastructure.config import get_settings

router = APIRouter(tags=["packages"])

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".ico": "image/x-icon",
}


@router.get("/pkg/{digest}/{asset_path:path}", include_in_schema=False)
def package_asset(digest: str, asset_path: str) -> FileResponse:
    """Serve one immutable package file without exposing the filesystem."""
    settings = get_settings()
    path = resolve_package_file(settings.package_root, digest, asset_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Package asset not found")
    media_type = _CONTENT_TYPES.get(path.suffix.lower())
    if media_type is None:
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Security-Policy": content_security_policy(settings),
            "Cross-Origin-Resource-Policy": "cross-origin",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
