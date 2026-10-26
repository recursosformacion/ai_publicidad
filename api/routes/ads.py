"""Ad selection and delivery endpoints."""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import AdPayload, ServeAdRequest
from application.security import require_service_token, validate_destination
from domain.models import AdDelivery, AdFormat, Campaign, Creative, TargetingRule
from infrastructure.config import get_settings
from infrastructure.database import get_db

router = APIRouter(prefix="/ads", tags=["ads"])


def _campaign_is_current(campaign: Campaign, now: datetime) -> bool:
    if campaign.status != "active":
        return False
    starts = campaign.starts_at
    ends = campaign.ends_at
    if starts and starts.replace(tzinfo=timezone.utc) > now:
        return False
    if ends and ends.replace(tzinfo=timezone.utc) < now:
        return False
    return True


def _matches_targeting(db: Session, creative_id: int, request: ServeAdRequest) -> bool:
    rules = db.scalars(select(TargetingRule).where(TargetingRule.creative_id == creative_id)).all()
    context = {
        "application": request.application,
        "page_type": request.page.type,
        "placement": request.placement,
        "language": request.page.language,
        "entity_type": request.page.entity_type or "",
        "entity_id": request.page.entity_id or "",
    }
    # Inclusion rules for the same field are alternatives (OR); exclusion
    # rules always win. Treating every include as a separate AND made it
    # impossible to target a creative to more than one page type or language.
    rules_by_type: dict[str, list[TargetingRule]] = {}
    for rule in rules:
        rules_by_type.setdefault(rule.rule_type, []).append(rule)

    for rule_type, typed_rules in rules_by_type.items():
        actual = context.get(rule_type, "")
        excluded = [
            rule for rule in typed_rules
            if rule.effect == "exclude"
            and (actual == rule.rule_value or rule.rule_value == "*")
        ]
        if excluded:
            return False

        included = [rule for rule in typed_rules if rule.effect == "include"]
        if included and not any(
            actual == rule.rule_value or rule.rule_value == "*"
            for rule in included
        ):
            return False
    return True


@router.post("/serve", response_model=AdPayload, dependencies=[Depends(require_service_token)])
def serve_ad(request: ServeAdRequest, db: Session = Depends(get_db)) -> AdPayload:
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(Creative, Campaign)
        .join(Campaign, Campaign.id == Creative.campaign_id)
        .where(Creative.status == "approved")
        .order_by(Campaign.priority.desc(), Creative.id.asc())
    ).all()

    selected: tuple[Creative, Campaign, AdFormat | None] | None = None
    size_requested = request.format.width is not None and request.format.height is not None
    requested_catalog_format: AdFormat | None = None
    if size_requested:
        requested_catalog_format = db.scalar(
            select(AdFormat).where(
                AdFormat.is_active.is_(True),
                AdFormat.width == request.format.width,
                AdFormat.height == request.format.height,
                AdFormat.device.in_(("both", request.device)),
            )
        )

    # A creative can support more than one standard size (for example, the OSAP
    # background banner has desktop and mobile variants). Prefer an exact active
    # size match, and only use unassigned generic creatives as fallback.
    for house_pass in (False, True):
        size_passes = (True, False) if size_requested else (False,)
        for exact_size_pass in size_passes:
            for creative, campaign in rows:
                if campaign.is_house_ad != house_pass or not _campaign_is_current(campaign, now):
                    continue
                if creative.format not in {request.format.type, "responsive"}:
                    continue
                if creative.language not in {request.page.language, "mul", "es"}:
                    continue

                assigned_formats = list(creative.ad_formats)
                matched_format: AdFormat | None = None
                if size_requested:
                    if exact_size_pass:
                        matched_format = next(
                            (
                                ad_format
                                for ad_format in assigned_formats
                                if ad_format.is_active
                                and ad_format.width == request.format.width
                                and ad_format.height == request.format.height
                                and ad_format.device in {"both", request.device}
                            ),
                            None,
                        )
                        if matched_format is None:
                            continue
                    elif assigned_formats:
                        # Do not deliver a fixed-size creative into the wrong slot.
                        continue
                    else:
                        # A generic house ad can still fill a known requested slot;
                        # record that slot in history even though the creative is reusable.
                        matched_format = requested_catalog_format
                elif assigned_formats:
                    # Old integrations that send no dimensions can keep using
                    # unassigned generic creatives until they start declaring a slot size.
                    continue

                if not _matches_targeting(db, creative.id, request):
                    continue
                try:
                    validate_destination(creative.destination_url)
                except ValueError:
                    continue
                selected = (creative, campaign, matched_format)
                break
            if selected:
                break
        if selected:
            break

    if selected is None:
        raise HTTPException(status_code=503, detail="No compatible commercial or house ad configured")

    creative, campaign, matched_format = selected
    token = secrets.token_urlsafe(32)
    delivery = AdDelivery(
        token=token,
        creative_id=creative.id,
        campaign_id=campaign.id,
        application=request.application,
        page_type=request.page.type,
        entity_type=request.page.entity_type,
        entity_id=request.page.entity_id,
        placement=request.placement,
        language=request.page.language,
        ad_format_id=matched_format.id if matched_format is not None else None,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    settings = get_settings()
    return AdPayload(
        ad_id=creative.id,
        impression_id=token,
        kind="house" if campaign.is_house_ad else "commercial",
        format=creative.format,
        title=creative.title,
        body=creative.body,
        image_url=creative.image_url,
        alt_text=creative.alt_text,
        language=creative.language,
        click_url=f"{settings.public_base_url.rstrip('/')}/r/{token}",
        is_house_ad=campaign.is_house_ad,
        ad_format_code=matched_format.code if matched_format is not None else None,
        ad_format_name=matched_format.name if matched_format is not None else None,
        ad_width=matched_format.width if matched_format is not None else None,
        ad_height=matched_format.height if matched_format is not None else None,
    )
