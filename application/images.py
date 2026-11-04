"""Optimized image storage for advertising creatives."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

if TYPE_CHECKING:
    from infrastructure.config import Settings


class ImageProcessingError(ValueError):
    """The uploaded image is not a supported or safe image."""


@dataclass(frozen=True)
class StoredImage:
    sha256: str
    extension: str
    content_type: str
    size_bytes: int


def optimize_image(
    payload: bytes,
    root: str | Path,
    *,
    max_dimension: int,
    quality: int,
) -> StoredImage:
    """Convert a static image to size-bounded WebP and store it by content hash."""
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            if getattr(source, "is_animated", False):
                # Keep animated GIF/WebP unchanged rather than silently dropping frames.
                if source.format == "GIF":
                    extension, content_type = ".gif", "image/gif"
                else:
                    extension, content_type = ".webp", "image/webp"
                digest = hashlib.sha256(payload).hexdigest()
                root_path = Path(root).resolve()
                root_path.mkdir(parents=True, exist_ok=True)
                target = root_path / f"{digest}{extension}"
                if not target.exists():
                    target.write_bytes(payload)
                return StoredImage(digest, extension, content_type, len(payload))

            image = ImageOps.exif_transpose(source)
            if max(image.size) > max_dimension:
                image.thumbnail(
                    (max_dimension, max_dimension),
                    Image.Resampling.LANCZOS,
                )
            has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            output = io.BytesIO()
            image.save(
                output,
                format="WEBP",
                quality=quality,
                method=6,
                lossless=has_alpha or source.format == "PNG",
            )
            optimized = output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageProcessingError("La imagen no se pudo procesar") from exc

    digest = hashlib.sha256(optimized).hexdigest()
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    target = root_path / f"{digest}.webp"
    if not target.exists():
        target.write_bytes(optimized)
    return StoredImage(digest, ".webp", "image/webp", len(optimized))


def image_file(root: str | Path, digest: str, extension: str = ".webp") -> Path | None:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    if extension not in {".webp", ".gif"}:
        return None
    root_path = Path(root).resolve()
    path = (root_path / f"{digest}{extension}").resolve()
    if not path.is_relative_to(root_path) or not path.is_file():
        return None
    return path


def image_url(settings: Settings, stored: StoredImage) -> str:
    base = settings.public_base_url
    return f"{str(base).rstrip('/')}/media/{stored.sha256}{stored.extension}"
