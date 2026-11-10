"""Idempotently seed four OSAP product house ads for the content_bottom slot.

Each product lives in its own campaign because the composition engine never mixes two
creatives from the same campaign; four campaigns allow four 200x200 squares in one row.
No database writes occur unless --apply is supplied. In MySQL, the target must be
OSAP_PUBLICIDAD.
"""

# ruff: noqa: E402

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from domain.models import AdFormat, Campaign, Creative, TargetingRule
from infrastructure.config import DATABASE_NAME, get_settings
from infrastructure.database import SessionLocal

FORMAT_CODE = "square_200x200"
PLACEMENT = "content_bottom"
CAMPAIGN_PREFIX = "OSAP footer"

PRODUCTS = (
    {
        "name": "Vídeos",
        "title": "OSAP · Vídeos de interpretación",
        "body": (
            "Busca interpretaciones en vídeo por obra, voz y tipo de material, "
            "y vota las mejores versiones."
        ),
        "destination_url": "https://videos.openmusicrepository.com/",
    },
    {
        "name": "Blog",
        "title": "OSAP · Blog",
        "body": (
            "Guías, análisis y novedades sobre repertorio, ediciones y "
            "prácticas de interpretación."
        ),
        "destination_url": "https://blog.openmusicrepository.com/",
    },
    {
        "name": "Apóyanos",
        "title": "OSAP · Apóyanos",
        "body": (
            "Ayuda a mantener el repertorio abierto y las herramientas de "
            "estudio para músicos y coros."
        ),
        "destination_url": "https://support.openmusicrepository.com/",
    },
    {
        "name": "Repertorio",
        "title": "OSAP · Repertorio abierto",
        "body": (
            "Explora obras, compositores y fuentes musicales en un catálogo "
            "abierto y colaborativo."
        ),
        "destination_url": "https://openmusicrepository.com/",
    },
)


def _ensure_format(db: Session) -> tuple[AdFormat, bool]:
    ad_format = db.scalar(select(AdFormat).where(AdFormat.code == FORMAT_CODE))
    if ad_format is not None:
        return ad_format, False
    ad_format = AdFormat(
        code=FORMAT_CODE,
        name="Cuadrado compacto 200×200",
        width=200,
        height=200,
        device="both",
        category="square",
        placement_notes="Cuadrado compacto para huecos de hasta 300 px de alto.",
        is_active=True,
    )
    db.add(ad_format)
    db.flush()
    return ad_format, True


def seed_osap_footer_ads(db: Session) -> bool:
    """Ensure the four product campaigns, creatives, formats and rules exist."""
    changed = False
    ad_format, created_format = _ensure_format(db)
    changed = changed or created_format

    for product in PRODUCTS:
        campaign_name = f"{CAMPAIGN_PREFIX} — {product['name']}"
        campaign = db.scalar(select(Campaign).where(Campaign.name == campaign_name))
        if campaign is None:
            campaign = Campaign(
                name=campaign_name,
                status="active",
                priority=-90,
                is_house_ad=True,
            )
            db.add(campaign)
            db.flush()
            changed = True
        elif not campaign.is_house_ad:
            raise ValueError(
                f"La campaña existente {campaign_name!r} no está marcada como anuncio "
                "propio; no se modificará automáticamente."
            )

        creative = db.scalar(
            select(Creative).where(
                Creative.campaign_id == campaign.id,
                Creative.title == product["title"],
            )
        )
        if creative is None:
            creative = Creative(
                campaign_id=campaign.id,
                title=product["title"],
                body=product["body"],
                image_url=None,
                alt_text=None,
                format="text",
                delivery_mode="adaptive",
                language="es",
                destination_url=product["destination_url"],
                status="approved",
            )
            db.add(creative)
            db.flush()
            changed = True

        if ad_format.id not in {item.id for item in creative.ad_formats}:
            creative.ad_formats.append(ad_format)
            changed = True

        for rule_type, rule_value in (
            ("application", "osap"),
            ("placement", PLACEMENT),
        ):
            existing = db.scalar(
                select(TargetingRule).where(
                    TargetingRule.creative_id == creative.id,
                    TargetingRule.rule_type == rule_type,
                    TargetingRule.rule_value == rule_value,
                )
            )
            if existing is None:
                db.add(
                    TargetingRule(
                        creative_id=creative.id,
                        rule_type=rule_type,
                        rule_value=rule_value,
                        effect="include",
                    )
                )
                changed = True

    return changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prepara cuatro anuncios propios de productos OSAP (200×200) para la "
            "ranura content_bottom, cada uno en su propia campaña."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Confirma la escritura idempotente. Sin esta opción solo muestra el plan.",
    )
    parser.add_argument(
        "--allow-sqlite",
        action="store_true",
        help="Permite la carga local en SQLite; no usar para la base MySQL de OSAP.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("No hay base de datos configurada.")

    url = make_url(settings.database_url)
    if url.drivername.startswith("mysql"):
        if url.database != DATABASE_NAME:
            raise SystemExit(
                f"Escritura bloqueada: el destino debe ser {DATABASE_NAME}, "
                f"no {url.database!r}."
            )
    elif url.drivername.startswith("sqlite"):
        if settings.env == "production":
            raise SystemExit("Producción no puede usar SQLite.")
        if args.apply and not args.allow_sqlite:
            raise SystemExit(
                "La configuración apunta a SQLite, no a OSAP_PUBLICIDAD. "
                "Usa --allow-sqlite solo para una prueba local intencionada."
            )
    else:
        raise SystemExit("Motor de base de datos no compatible para esta carga.")

    safe_url = url.render_as_string(hide_password=True)
    if not args.apply:
        print(f"Simulación; no se ha escrito nada. Destino: {safe_url}")
        return

    with SessionLocal() as db:
        changed = seed_osap_footer_ads(db)
        if changed:
            db.commit()
        else:
            db.rollback()

    print(
        f"Carga completada en {safe_url}: "
        f"{len(PRODUCTS)} anuncios cuadrados de OSAP preparados."
    )


if __name__ == "__main__":
    main()
