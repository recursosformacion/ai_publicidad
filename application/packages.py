"""Validation and storage for isolated static HTML ad packages."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from infrastructure.config import Settings


ALLOWED_SUFFIXES = frozenset({
    ".html", ".htm", ".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".ico", ".woff", ".woff2", ".ttf", ".otf", ".avif",
})
ENTRYPOINT = "index.html"


class PackageValidationError(ValueError):
    """The uploaded ZIP is not a safe static ad package."""


@dataclass(frozen=True)
class StoredPackage:
    sha256: str
    size_bytes: int
    compressed_size: int
    entrypoint: str
    original_filename: str | None


def _safe_member_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/"):
        raise PackageValidationError("El ZIP contiene una ruta no válida.")
    pure = PurePosixPath(name)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise PackageValidationError("El ZIP contiene una ruta no válida.")
    return pure.as_posix()


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def validate_and_store_package(
    payload: bytes,
    filename: str | None,
    root: str | Path,
    *,
    max_archive_bytes: int,
    max_extracted_bytes: int,
    max_files: int,
) -> StoredPackage:
    """Validate a ZIP, extract it under a content hash and return immutable metadata."""
    if not payload:
        raise PackageValidationError("El fichero ZIP está vacío.")
    if len(payload) > max_archive_bytes:
        raise PackageValidationError("El ZIP supera el tamaño máximo permitido.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackageValidationError("El fichero no es un ZIP válido.") from exc

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos:
            raise PackageValidationError("El ZIP no contiene ficheros.")
        if len(infos) > max_files:
            raise PackageValidationError("El ZIP contiene demasiados ficheros.")
        if ENTRYPOINT not in {info.filename for info in infos}:
            raise PackageValidationError("El ZIP debe contener index.html en la raíz.")

        names: set[str] = set()
        total_size = 0
        compressed_size = 0
        for info in infos:
            if info.flag_bits & 0x1:
                raise PackageValidationError("El ZIP no puede estar cifrado.")
            if _is_symlink(info):
                raise PackageValidationError("El ZIP no puede contener enlaces simbólicos.")
            member = _safe_member_name(info.filename)
            lowered = member.lower()
            if lowered in names:
                raise PackageValidationError("El ZIP contiene nombres duplicados.")
            names.add(lowered)
            if PurePosixPath(member).suffix.lower() not in ALLOWED_SUFFIXES:
                raise PackageValidationError(
                    f"Tipo de fichero no permitido en el paquete: {member}"
                )
            if info.file_size > max_extracted_bytes:
                raise PackageValidationError("Un fichero del ZIP es demasiado grande.")
            total_size += info.file_size
            compressed_size += info.compress_size
            if total_size > max_extracted_bytes:
                raise PackageValidationError("El contenido descomprimido es demasiado grande.")

        root_path = Path(root).resolve()
        root_path.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(payload).hexdigest()
        target = root_path / digest
        if not target.exists():
            staging = Path(tempfile.mkdtemp(prefix=f".{digest[:12]}-", dir=root_path))
            try:
                for info in infos:
                    member = _safe_member_name(info.filename)
                    destination = (staging / member).resolve()
                    if not destination.is_relative_to(staging):
                        raise PackageValidationError("El ZIP intenta salir del paquete.")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with archive.open(info) as source, destination.open("wb") as output:
                            remaining = max_extracted_bytes
                            while True:
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                remaining -= len(chunk)
                                if remaining < 0:
                                    raise PackageValidationError(
                                        "El ZIP descomprimido es demasiado grande."
                                    )
                                output.write(chunk)
                    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                        raise PackageValidationError("No se pudo leer el ZIP.") from exc
                os.replace(staging, target)
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)

    safe_filename = Path(filename or "").name[:255] or None
    return StoredPackage(
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=total_size,
        compressed_size=compressed_size,
        entrypoint=ENTRYPOINT,
        original_filename=safe_filename,
    )


def resolve_package_file(root: str | Path, digest: str, asset_path: str) -> Path | None:
    """Return a safe extracted file for a public package URL, or None."""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    if not asset_path or "\\" in asset_path:
        return None
    try:
        pure = PurePosixPath(asset_path)
    except ValueError:
        return None
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    if pure.suffix.lower() not in ALLOWED_SUFFIXES:
        return None
    package_root = Path(root).resolve()
    package_dir = package_root / digest
    candidate = (package_dir / pure).resolve()
    if (
        not candidate.is_relative_to(package_dir)
        or not candidate.is_file()
        or candidate.is_symlink()
    ):
        return None
    return candidate


def package_content_url(settings: Settings, digest: str, entrypoint: str) -> str | None:
    """Build the public iframe URL on the dedicated content origin."""
    base = settings.package_content_base_url
    if not base and settings.env != "production":
        base = settings.public_base_url
    if not base:
        return None
    return f"{base.rstrip('/')}/pkg/{digest}/{entrypoint}"


def content_security_policy(settings: Settings) -> str:
    """CSP for package HTML; scripts and external resources are blocked in the MVP."""
    ancestors = settings.package_frame_ancestors.strip() or "'none'"
    source_base = settings.package_content_base_url or settings.public_base_url
    parsed = urlsplit(source_base)
    # A sandboxed iframe has an opaque origin, so 'self' is not enough for its assets.
    # Allow only the dedicated content origin explicitly.
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    origin_source = f"{origin} " if origin else ""
    return (
        f"default-src 'none'; img-src {origin_source}'self' data:; "
        f"style-src {origin_source}'self' 'unsafe-inline'; "
        f"font-src {origin_source}'self' data:; script-src 'none'; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors " + ancestors + ";"
    )
