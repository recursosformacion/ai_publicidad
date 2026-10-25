"""Ad selection and delivery endpoints."""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import AdPayload, ServeAdRequest
from application.security import require_service_token, validate_destination
from domain.models import AdDelivery, Campaign, Creative, TargetingRule
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

    selected: tuple[Creative, Campaign] | None = None
    for house_pass in (False, True):
        for creative, campaign in rows:
            if campaign.is_house_ad != house_pass or not _campaign_is_current(campaign, now):
                continue
            if creative.format not in {request.format.type, "responsive"}:
                continue
            if creative.language not in {request.page.language, "mul", "es"}:
                continue
            if not _matches_targeting(db, creative.id, request):
                continue
            try:
                validate_destination(creative.destination_url)
            except ValueError:
                continue
            selected = (creative, campaign)
            break
        if selected:
            break

    if selected is None:
        raise HTTPException(status_code=503, detail="No compatible commercial or house ad configured")

    creative, campaign = selected
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
    )
