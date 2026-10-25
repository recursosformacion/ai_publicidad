"""Idempotently seed OSAP's initial house advertisement.

No database writes occur unless --apply is supplied. In MySQL, the target must
be OSAP_PUBLICIDAD; production writes remain an explicit operator action.
"""

import argparse
import sys
from pathlib import Path

# Keep direct execution ("python scripts/seed_house_ads.py") working.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from domain.models import Campaign, Creative
from infrastructure.config import DATABASE_NAME, get_settings
from infrastructure.database import SessionLocal


CAMPAIGN_NAME = "OSAP house ads - initial"
CREATIVE_TITLE = "Descubre OpenMusicRepository"


def seed_house_ads(db: Session) -> bool:
    """Ensure the initial campaign and Spanish fallback creative exist.

    Returns True if at least one row was added, False when the seed was already
    complete. The caller controls the transaction and commits only on success.
    """
    campaign = db.query(Campaign).filter(Campaign.name == CAMPAIGN_NAME).first()
    changed = False
    if campaign is None:
        campaign = Campaign(
            name=CAMPAIGN_NAME,
            status="active",
            priority=-100,
            is_house_ad=True,
        )
        db.add(campaign)
        db.flush()
        changed = True
    elif not campaign.is_house_ad:
        raise ValueError(
            f"La campaña existente {CAMPAIGN_NAME!r} no está marcada como anuncio propio; "
            "no se modificará automáticamente."
        )

    creative = (
        db.query(Creative)
        .filter(
            Creative.campaign_id == campaign.id,
            Creative.title == CREATIVE_TITLE,
        )
        .first()
    )
    if creative is None:
        db.add(
            Creative(
                campaign_id=campaign.id,
                title=CREATIVE_TITLE,
                body="Explora el catálogo y encuentra recursos para tus obras musicales.",
                image_url=None,
                alt_text=None,
                format="responsive",
                language="es",
                destination_url="https://openmusicrepository.com/",
                status="approved",
            )
        )
        changed = True

    return changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepara el anuncio propio inicial de OSAP en la base configurada."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Confirma la escritura idempotente. Sin esta opción solo muestra el plan.",
    )
    parser.add_argument(
        "--allow-sqlite",
        action="store_true",
        help="Permite la carga local en SQLite; no usar para inicializar la base MySQL de OSAP.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("No hay base de datos configurada.")

    url = make_url(settings.database_url)
    if url.drivername.startswith("mysql"):
        if url.database != DATABASE_NAME:
            raise SystemExit(
                f"Escritura bloqueada: el destino debe ser {DATABASE_NAME}, no {url.database!r}."
            )
    elif url.drivername.startswith("sqlite"):
        if settings.env == "production":
            raise SystemExit("Producción no puede usar SQLite.")
        if args.apply and not args.allow_sqlite:
            raise SystemExit(
                "La configuración apunta a SQLite, no a OSAP_PUBLICIDAD. "
                "Revisa tu osap.toml; usa --allow-sqlite solo para una prueba local intencionada."
            )
    else:
        raise SystemExit("Motor de base de datos no compatible para esta carga inicial.")

    # Print destination without exposing the password.
    safe_url = url.render_as_string(hide_password=True)
    if not args.apply:
        print(f"Simulación; no se ha escrito nada. Destino: {safe_url}")
        print(f"Se comprobará/creará la campaña {CAMPAIGN_NAME!r} y su creatividad inicial.")
        print("Añade --apply para confirmar la carga.")
        return

    try:
        with SessionLocal() as db:
            changed = seed_house_ads(db)
            db.commit()
    except Exception:
        raise

    if changed:
        print(f"Carga inicial completada en {DATABASE_NAME if url.drivername.startswith('mysql') else url.database}.")
    else:
        print("La campaña y la creatividad inicial ya existían; no se ha añadido nada.")


if __name__ == "__main__":
    main()
