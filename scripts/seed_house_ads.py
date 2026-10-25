"""Explicitly seed a generic OSAP house ad for a local/test database.

This script never runs automatically and refuses to target production.
"""

from infrastructure.config import get_settings
from infrastructure.database import SessionLocal
from domain.models import Campaign, Creative


def main() -> None:
    settings = get_settings()
    if settings.env == "production":
        raise SystemExit("Refusing to seed production. Use a reviewed, explicit deployment procedure.")
    if not settings.database_url or not settings.database_url.startswith("sqlite"):
        raise SystemExit(
            "Este script de datos de ejemplo solo admite SQLite local. "
            "No se escribirán anuncios en un servidor MySQL/MariaDB."
        )

    with SessionLocal() as db:
        existing = db.query(Campaign).filter(Campaign.name == "OSAP house ads - initial").first()
        if existing:
            print("Initial OSAP house campaign already exists; nothing changed.")
            return

        campaign = Campaign(
            name="OSAP house ads - initial",
            status="active",
            priority=-100,
            is_house_ad=True,
        )
        db.add(campaign)
        db.flush()
        db.add(
            Creative(
                campaign_id=campaign.id,
                title="Descubre OpenMusicRepository",
                body="Explora el catálogo y encuentra recursos para tus obras musicales.",
                image_url=None,
                alt_text=None,
                format="responsive",
                language="es",
                destination_url="https://openmusicrepository.com/",
                status="approved",
            )
        )
        db.commit()
        print("Initial OSAP house ad created.")


if __name__ == "__main__":
    main()
