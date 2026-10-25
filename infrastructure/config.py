"""Environment-driven configuration.

Secrets are read from environment variables; no credential file is committed.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_PUBLICIDAD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./ai_publicidad.sqlite3"
    public_base_url: str = "http://127.0.0.1:8305"
    service_token: str = ""
    service_name: str = "ai_publicidad"

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        if self.env == "production":
            if not self.service_token.strip():
                raise ValueError("AI_PUBLICIDAD_SERVICE_TOKEN es obligatorio en producción")
            if self.database_url.startswith("sqlite"):
                raise ValueError("La base de datos de producción debe ser MySQL/MariaDB")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("AI_PUBLICIDAD_PUBLIC_BASE_URL debe usar HTTPS en producción")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached process configuration."""
    return Settings()
