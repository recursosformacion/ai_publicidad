"""FastAPI application entry point for ai_publicidad."""

from fastapi import FastAPI

from api.routes.ads import router as ads_router
from api.routes.clicks import router as clicks_router
from api.routes.events import router as events_router
from api.routes.health import router as health_router
from api.routes.metadata import router as metadata_router
from domain.models import Base
from infrastructure.config import get_settings
from infrastructure.database import engine

app = FastAPI(
    title="ai_publicidad",
    description="Servicio independiente de publicidad directa.",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(metadata_router, prefix="/api/v1")
app.include_router(ads_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(clicks_router)


@app.on_event("startup")
def initialize_development_schema() -> None:
    """Auto-create schema only for local SQLite; MySQL schemas always use migrations."""
    settings = get_settings()
    if settings.env != "production" and settings.database_url and settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)


def run() -> None:
    """Run the API server."""
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8305, reload=False)


if __name__ == "__main__":
    run()
