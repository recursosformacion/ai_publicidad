"""Operational health endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return a minimal health response without exposing configuration."""
    return {"status": "ok", "service": "ai_publicidad"}
