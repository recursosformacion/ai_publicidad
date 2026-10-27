"""Configuration for the advertising service.

The service owns a private osap.toml. Connection values can be copied from osap-api's
configuration, but this service uses its independent OSAP_PUBLICIDAD schema.
Secrets are never committed.
"""

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


DATABASE_NAME = "OSAP_PUBLICIDAD"


def locate_osap_config(explicit_path: str | None = None) -> Path | None:
    """Locate this service's private osap.toml; never fall back to osap-api's config."""
    if explicit_path:
        path = Path(explicit_path)
        if not path.is_file():
            raise ValueError("El fichero indicado por OSAP_CONFIG no existe o no es accesible.")
        return path

    # Each service owns its config. The current working directory should be this
    # repository root; no credentials are borrowed from sibling application folders.
    candidate = Path("osap.toml")
    return candidate if candidate.is_file() else None


def database_url_from_osap_toml(path: str | Path) -> str | None:
    """Build a URL for OSAP_PUBLICIDAD from this service's private [db] settings."""
    config_path = Path(path)
    if not config_path.is_file():
        return None

    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("No se pudo leer el fichero TOML de configuración de OSAP.") from exc

    db = data.get("db")
    if not isinstance(db, dict):
        return None

    host = db.get("host")
    username = db.get("user")
    password = db.get("password")
    if not all(isinstance(value, str) and value.strip() for value in (host, username, password)):
        return None

    try:
        port = int(db.get("port", 3306))
    except (TypeError, ValueError):
        port = 3306
    if not 0 < port < 65536:
        port = 3306

    url = URL.create(
        "mysql+pymysql",
        username=username,
        password=password,
        host=host,
        port=port,
        database=DATABASE_NAME,
        query={"charset": "utf8mb4"},
    )
    return url.render_as_string(hide_password=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_PUBLICIDAD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    # Explicit URL wins. Otherwise, read this service's OSAP_CONFIG/[db]; local development falls back to SQLite.
    database_url: str | None = None
    osap_config_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AI_PUBLICIDAD_OSAP_CONFIG", "OSAP_CONFIG"),
    )
    public_base_url: str = "http://127.0.0.1:8305"
    service_token: str = ""
    visitor_hash_secret: str = ""
    enable_layout_lab: bool = False
    service_name: str = "ai_publicidad"

    @model_validator(mode="after")
    def resolve_database_and_validate(self) -> "Settings":
        explicit_url = bool(self.database_url and self.database_url.strip())

        if not explicit_url:
            config_path = locate_osap_config(self.osap_config_path)
            if config_path is not None:
                resolved_url = database_url_from_osap_toml(config_path)
                if not resolved_url:
                    raise ValueError("El fichero osap.toml no contiene una conexión [db] completa.")
                self.database_url = resolved_url
            elif self.env == "production":
                raise ValueError(
                    "En producción configure AI_PUBLICIDAD_DATABASE_URL o cree el osap.toml "
                    "privado de ai_publicidad con su conexión a OSAP_PUBLICIDAD."
                )
            else:
                self.database_url = "sqlite:///./ai_publicidad.sqlite3"

        assert self.database_url is not None
        if self.env == "production":
            if not self.service_token.strip():
                raise ValueError("AI_PUBLICIDAD_SERVICE_TOKEN es obligatorio en producción")
            if not self.visitor_hash_secret.strip():
                raise ValueError("AI_PUBLICIDAD_VISITOR_HASH_SECRET es obligatorio en producción")
            if self.database_url.startswith("sqlite"):
                raise ValueError("La base de datos de producción debe ser MySQL/MariaDB")
            try:
                parsed_url = make_url(self.database_url)
            except (ValueError, TypeError) as exc:
                raise ValueError("AI_PUBLICIDAD_DATABASE_URL no es una URL válida.") from exc
            if parsed_url.database != DATABASE_NAME:
                raise ValueError("La base de datos de publicidad debe llamarse OSAP_PUBLICIDAD.")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("AI_PUBLICIDAD_PUBLIC_BASE_URL debe usar HTTPS en producción")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached process configuration."""
    return Settings()
