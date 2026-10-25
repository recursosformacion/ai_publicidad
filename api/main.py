"""FastAPI application entry point for ai_publicidad."""

from fastapi import FastAPI

from api.routes.health import router as health_router
from api.routes.metadata import router as metadata_router

app = FastAPI(
    title="ai_publicidad",
    description="Servicio independiente de publicidad directa.",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(metadata_router, prefix="/api/v1")


def run() -> None:
    """Run the API server."""
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8305, reload=False)


if __name__ == "__main__":
    run()
