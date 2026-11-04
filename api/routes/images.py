"""Public serving of optimized advertising images."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from application.images import image_file
from infrastructure.config import get_settings

router = APIRouter(tags=["images"])


@router.get("/media/{filename}", include_in_schema=False)
def image_asset(filename: str) -> FileResponse:
    path_name = Path(filename)
    if path_name.name != filename:
        raise HTTPException(status_code=404, detail="Image not found")
    path = image_file(get_settings().image_root, path_name.stem, path_name.suffix)
    if path is None:
        raise HTTPException(status_code=404, detail="Image not found")
    media_type = "image/gif" if path.suffix == ".gif" else "image/webp"
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
