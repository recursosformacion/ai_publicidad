"""FastAPI application entry point for ai_publicidad."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes.admin import router as admin_router
from api.routes.admin_ui import router as admin_ui_router
from api.routes.auth import router as auth_router
from api.routes.ads import router as ads_router
from api.routes.clicks import router as clicks_router
from api.routes.commercial_admin import router as commercial_admin_router
from api.routes.events import router as events_router
from api.routes.health import router as health_router
from api.routes.images import router as images_router
from api.routes.layout_lab import router as layout_lab_router
from api.routes.metadata import router as metadata_router
from api.routes.packages import router as packages_router
from api.routes.reports import router as reports_router
from domain.models import Base
from infrastructure.config import get_settings
from infrastructure.database import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize only local SQLite; MySQL schemas always use migrations."""
    settings = get_settings()
    if (
        settings.env != "production"
        and settings.database_url
        and settings.database_url.startswith("sqlite")
    ):
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="ai_publicidad",
    description="Servicio independiente de publicidad directa.",
    version="0.4.1",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(layout_lab_router)
app.include_router(metadata_router, prefix="/api/v1")
app.include_router(ads_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(commercial_admin_router, prefix="/api/v1")
app.include_router(auth_router)
app.include_router(admin_ui_router)
app.include_router(events_router, prefix="/api/v1")
app.include_router(clicks_router)
app.include_router(packages_router)
app.include_router(images_router)
app.mount(
    "/manual",
    StaticFiles(directory=Path(__file__).resolve().parent / "static" / "manual", html=True),
    name="manual",
)


def run() -> None:
    """Run the API server."""
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8305, reload=False)


if __name__ == "__main__":
    run()

