"""Create the OSAP_PUBLICIDAD schema using the private OSAP DB connection.

This command is explicit and requires --apply. It never creates users, grants
privileges, creates tables, or reads/writes the existing osap-api schema.
"""

import argparse
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.config import (
    DATABASE_NAME,
    database_url_from_osap_toml,
    locate_osap_config,
)


def get_connection_url() -> str:
    """Get an explicit URL or reuse the DB connection from the private osap.toml."""
    explicit_url = os.environ.get("AI_PUBLICIDAD_DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url

    config_path = locate_osap_config(
        os.environ.get("AI_PUBLICIDAD_OSAP_CONFIG") or os.environ.get("OSAP_CONFIG")
    )
    if config_path is None:
        raise SystemExit(
            "No se encuentra osap.toml. Define OSAP_CONFIG o AI_PUBLICIDAD_OSAP_CONFIG."
        )

    url = database_url_from_osap_toml(config_path)
    if not url:
        raise SystemExit("osap.toml no contiene una conexión [db] completa.")
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea la base vacía OSAP_PUBLICIDAD.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ejecuta CREATE DATABASE IF NOT EXISTS; sin esta opción no se modifica el servidor.",
    )
    args = parser.parse_args()

    try:
        url = make_url(get_connection_url())
    except (ValueError, TypeError):
        raise SystemExit("La conexión configurada no es una URL MySQL/MariaDB válida.") from None

    if not url.drivername.startswith("mysql"):
        raise SystemExit("La conexión debe utilizar MySQL/MariaDB.")
    if url.database != DATABASE_NAME:
        raise SystemExit("La conexión debe apuntar a OSAP_PUBLICIDAD; se cancela por seguridad.")
    if not args.apply:
        print("Comprobación de configuración correcta: objetivo OSAP_PUBLICIDAD.")
        print("No se ha modificado el servidor. Añade --apply para crear la base.")
        return

    server_url = url.set(database=None)
    engine = create_engine(server_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                "CREATE DATABASE IF NOT EXISTS `OSAP_PUBLICIDAD` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            connection.commit()
    except SQLAlchemyError:
        raise SystemExit(
            "No se pudo crear OSAP_PUBLICIDAD. Comprueba que el servidor es accesible "
            "y que la cuenta configurada tiene permiso CREATE DATABASE. Si no, un "
            "administrador debe crearla y conceder permisos sobre OSAP_PUBLICIDAD.*."
        ) from None
    finally:
        engine.dispose()

    print("OSAP_PUBLICIDAD existe. El esquema de tablas todavía debe inicializarse con Alembic.")


if __name__ == "__main__":
    main()
