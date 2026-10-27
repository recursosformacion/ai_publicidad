"""Idempotently seed standard ad formats and four OpenMusicRepository house creatives.

The command is read-only unless --apply is supplied. MySQL writes are restricted to
OSAP_PUBLICIDAD; SQLite writes require an explicit --allow-sqlite flag.
"""

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


CAMPAIGN_NAME = "OpenMusicRepository — campaña de difusión"

# Dimensions come from the requested OSAP layout. Standard sizes such as
# 728x90, 320x50, 300x250 and 160x600 are commonly catalogued display units;
# 200x200 is kept as the compact square requested for this particular layout.
FORMAT_CATALOG = (
    {
        "code": "leaderboard_728x90",
        "name": "Leaderboard 728×90 · escritorio",
        "width": 728,
        "height": 90,
        "device": "desktop",
        "category": "banner",
        "placement_notes": "Fondo/banner OSAP en escritorio.",
    },
    {
        "code": "mobile_banner_320x50",
        "name": "Banner móvil 320×50",
        "width": 320,
        "height": 50,
        "device": "mobile",
        "category": "banner",
        "placement_notes": "Fondo/banner OSAP en móvil.",
    },
    {
        "code": "medium_rectangle_300x250",
        "name": "Rectángulo mediano 300×250",
        "width": 300,
        "height": 250,
        "device": "both",
        "category": "rectangle",
        "placement_notes": (
            "Puede centrarse como bloque destacado sin cambiar la estructura; "
            "en una columna lateral estrecha quizá exija ampliarla."
        ),
    },
    {
        "code": "wide_skyscraper_160x600",
        "name": "Vertical ancho 160×600",
        "width": 160,
        "height": 600,
        "device": "desktop",
        "category": "video",
        "placement_notes": (
            "Ranura vertical para la zona de vídeos; no exige ensanchar la columna "
            "si hay al menos 160 px. La reproducción de vídeo requiere un recurso "
            "audiovisual, que este anuncio textual todavía no incorpora."
        ),
    },
    {
        "code": "square_200x200",
        "name": "Cuadrado compacto 200×200",
        "width": 200,
        "height": 200,
        "device": "both",
        "category": "square",
        "placement_notes": (
            "Alternativa cuadrada compacta, con menos cambio estructural que 300×250."
        ),
    },
)


CREATIVE_SEEDS = (
    {
        "title": "OpenMusicRepository · Fondo OSAP",
        "body": (
            "Descubre OpenMusicRepository: explora partituras, obras y recursos "
            "musicales para preparar tu próxima interpretación."
        ),
        "formats": ("leaderboard_728x90", "mobile_banner_320x50"),
        "placement": "header",
    },
    {
        "title": "OpenMusicRepository · Rectángulo destacado",
        "body": (
            "Encuentra tu próxima obra. Busca repertorio, autores y partituras "
            "en OpenMusicRepository."
        ),
        "formats": ("medium_rectangle_300x250",),
        "placement": "content_top",
    },
    {
        "title": "OpenMusicRepository · Formato vertical",
        "body": (
            "Un repertorio abierto para la música: descubre obras y recursos "
            "que pueden ayudarte en tus ensayos y actuaciones."
        ),
        "formats": ("wide_skyscraper_160x600",),
        "placement": "sidebar",
    },
    {
        "title": "OpenMusicRepository · Cuadrado compacto",
        "body": (
            "Explora el repertorio musical y encuentra recursos para tu coro "
            "o conjunto en OpenMusicRepository."
        ),
        "formats": ("square_200x200",),
        "placement": "content_inline",
    },
)


def seed_omr_campaign(db: Session) -> bool:
    """Ensure five catalog formats and one campaign with four creative records exist."""
    changed = False
    formats_by_code: dict[str, AdFormat] = {}

    for seed in FORMAT_CATALOG:
        ad_format = db.scalar(select(AdFormat).where(AdFormat.code == seed["code"]))
        if ad_format is None:
            ad_format = AdFormat(**seed, is_active=True)
            db.add(ad_format)
            db.flush()
            changed = True
        formats_by_code[ad_format.code] = ad_format

    campaign = db.scalar(select(Campaign).where(Campaign.name == CAMPAIGN_NAME))
    if campaign is None:
        campaign = Campaign(
            name=CAMPAIGN_NAME,
            status="active",
            priority=-50,
            is_house_ad=True,
        )
        db.add(campaign)
        db.flush()
        changed = True
    elif not campaign.is_house_ad:
        raise ValueError(
            f"La campaña {CAMPAIGN_NAME!r} ya existe, pero no está marcada como anuncio propio. "
            "No se modificará automáticamente."
        )

    for seed in CREATIVE_SEEDS:
        creative = db.scalar(
            select(Creative).where(
                Creative.campaign_id == campaign.id,
                Creative.title == seed["title"],
            )
        )
        if creative is None:
            creative = Creative(
                campaign_id=campaign.id,
                title=seed["title"],
                body=seed["body"],
                image_url=None,
                alt_text=None,
                format="responsive",
                language="es",
                destination_url="https://openmusicrepository.com/",
                status="approved",
            )
            db.add(creative)
            db.flush()
            changed = True

        assigned_ids = {item.id for item in creative.ad_formats}
        for code in seed["formats"]:
            ad_format = formats_by_code[code]
            if ad_format.id not in assigned_ids:
                creative.ad_formats.append(ad_format)
                assigned_ids.add(ad_format.id)
                changed = True

        expected_rules = (("application", "osap"), ("placement", seed["placement"]), ("placement", "layout_lab"))
        for rule_type, rule_value in expected_rules:
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
            "Prepara el catálogo de formatos estándar y una campaña propia "
            "de OpenMusicRepository con cuatro anuncios."
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
        help="Permite una carga en SQLite local para pruebas; no es la base MySQL de OSAP.",
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
                "Revisa osap.toml; --allow-sqlite solo vale para una prueba local intencionada."
            )
    else:
        raise SystemExit("Motor de base de datos no compatible para esta carga inicial.")

    safe_url = url.render_as_string(hide_password=True)
    if not args.apply:
        print(f"Simulación; no se ha escrito nada. Destino: {safe_url}")
        print(f"Formatos que se comprobarán/crearán: {len(FORMAT_CATALOG)}")
        print(f"Campaña: {CAMPAIGN_NAME!r}")
        print(f"Creatividades: {len(CREATIVE_SEEDS)}")
        print("Añade --apply para confirmar la carga.")
        return

    with SessionLocal() as db:
        changed = seed_omr_campaign(db)
        db.commit()

    if changed:
        target = DATABASE_NAME if url.drivername.startswith("mysql") else url.database
        print(
            f"Carga completada en {target}: catálogo de formatos y campaña "
            f"con {len(CREATIVE_SEEDS)} anuncios preparados."
        )
    else:
        print("El catálogo, la campaña, sus anuncios y sus reglas ya estaban completos; no se duplicó nada.")


if __name__ == "__main__":
    main()
