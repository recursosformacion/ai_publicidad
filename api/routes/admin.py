"""Authenticated administration for campaign configuration and read-only history."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.admin_schemas import (
    AdDeliveryRead,
    AdEventRead,
    CampaignInput,
    CampaignRead,
    CreativeInput,
    CreativeRead,
    TargetingRuleInput,
    TargetingRuleRead,
)
from domain.models import AdDelivery, AdEvent, Campaign, Creative, TargetingRule
from infrastructure.database import get_db

# Authorization is intentionally deferred to a later phase.
router = APIRouter(prefix="/admin", tags=["administration"])


def _not_found(kind: str, record_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} {record_id} no existe")


def _commit_or_conflict(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from exc


# Campaigns

@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[Campaign]:
    return list(db.scalars(select(Campaign).order_by(Campaign.id).offset(offset).limit(limit)).all())


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignInput, db: Session = Depends(get_db)) -> Campaign:
    campaign = Campaign(**payload.model_dump())
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise _not_found("Campaña", campaign_id)
    return campaign


@router.put("/campaigns/{campaign_id}", response_model=CampaignRead)
def replace_campaign(
    campaign_id: int, payload: CampaignInput, db: Session = Depends(get_db)
) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise _not_found("Campaña", campaign_id)
    for key, value in payload.model_dump().items():
        setattr(campaign, key, value)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise _not_found("Campaña", campaign_id)
    if db.scalar(select(func.count()).select_from(Creative).where(Creative.campaign_id == campaign_id)):
        raise HTTPException(
            status_code=409,
            detail="La campaña tiene creatividades; elimínalas primero o pausa la campaña para conservar el histórico.",
        )
    if db.scalar(select(func.count()).select_from(AdDelivery).where(AdDelivery.campaign_id == campaign_id)):
        raise HTTPException(status_code=409, detail="La campaña tiene entregas históricas y no se puede borrar.")
    db.delete(campaign)
    db.commit()
    return {"deleted": True}


# Creatives

@router.get("/creatives", response_model=list[CreativeRead])
def list_creatives(
    campaign_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[Creative]:
    query = select(Creative)
    if campaign_id is not None:
        query = query.where(Creative.campaign_id == campaign_id)
    query = query.order_by(Creative.id).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.post("/creatives", response_model=CreativeRead, status_code=status.HTTP_201_CREATED)
def create_creative(payload: CreativeInput, db: Session = Depends(get_db)) -> Creative:
    if db.get(Campaign, payload.campaign_id) is None:
        raise HTTPException(status_code=404, detail=f"Campaña {payload.campaign_id} no existe")
    creative = Creative(**payload.model_dump())
    db.add(creative)
    db.commit()
    db.refresh(creative)
    return creative


@router.get("/creatives/{creative_id}", response_model=CreativeRead)
def get_creative(creative_id: int, db: Session = Depends(get_db)) -> Creative:
    creative = db.get(Creative, creative_id)
    if creative is None:
        raise _not_found("Creatividad", creative_id)
    return creative


@router.put("/creatives/{creative_id}", response_model=CreativeRead)
def replace_creative(
    creative_id: int, payload: CreativeInput, db: Session = Depends(get_db)
) -> Creative:
    creative = db.get(Creative, creative_id)
    if creative is None:
        raise _not_found("Creatividad", creative_id)
    if db.get(Campaign, payload.campaign_id) is None:
        raise HTTPException(status_code=404, detail=f"Campaña {payload.campaign_id} no existe")
    for key, value in payload.model_dump().items():
        setattr(creative, key, value)
    db.commit()
    db.refresh(creative)
    return creative


@router.delete("/creatives/{creative_id}")
def delete_creative(creative_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    creative = db.get(Creative, creative_id)
    if creative is None:
        raise _not_found("Creatividad", creative_id)
    if db.scalar(select(func.count()).select_from(AdDelivery).where(AdDelivery.creative_id == creative_id)):
        raise HTTPException(
            status_code=409,
            detail="La creatividad tiene entregas históricas; pausa la creatividad para conservar las estadísticas.",
        )
    db.query(TargetingRule).filter(TargetingRule.creative_id == creative_id).delete()
    db.delete(creative)
    db.commit()
    return {"deleted": True}


# Targeting rules

@router.get("/targeting-rules", response_model=list[TargetingRuleRead])
def list_targeting_rules(
    creative_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[TargetingRule]:
    query = select(TargetingRule)
    if creative_id is not None:
        query = query.where(TargetingRule.creative_id == creative_id)
    query = query.order_by(TargetingRule.id).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.post(
    "/targeting-rules",
    response_model=TargetingRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_targeting_rule(
    payload: TargetingRuleInput, db: Session = Depends(get_db)
) -> TargetingRule:
    if db.get(Creative, payload.creative_id) is None:
        raise HTTPException(status_code=404, detail=f"Creatividad {payload.creative_id} no existe")
    rule = TargetingRule(**payload.model_dump())
    db.add(rule)
    _commit_or_conflict(db, "La regla duplica una regla existente para esta creatividad.")
    db.refresh(rule)
    return rule


@router.get("/targeting-rules/{rule_id}", response_model=TargetingRuleRead)
def get_targeting_rule(rule_id: int, db: Session = Depends(get_db)) -> TargetingRule:
    rule = db.get(TargetingRule, rule_id)
    if rule is None:
        raise _not_found("Regla de segmentación", rule_id)
    return rule


@router.put("/targeting-rules/{rule_id}", response_model=TargetingRuleRead)
def replace_targeting_rule(
    rule_id: int, payload: TargetingRuleInput, db: Session = Depends(get_db)
) -> TargetingRule:
    rule = db.get(TargetingRule, rule_id)
    if rule is None:
        raise _not_found("Regla de segmentación", rule_id)
    if db.get(Creative, payload.creative_id) is None:
        raise HTTPException(status_code=404, detail=f"Creatividad {payload.creative_id} no existe")
    for key, value in payload.model_dump().items():
        setattr(rule, key, value)
    _commit_or_conflict(db, "La regla duplica una regla existente para esta creatividad.")
    db.refresh(rule)
    return rule


@router.delete("/targeting-rules/{rule_id}")
def delete_targeting_rule(rule_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    rule = db.get(TargetingRule, rule_id)
    if rule is None:
        raise _not_found("Regla de segmentación", rule_id)
    db.delete(rule)
    db.commit()
    return {"deleted": True}


# Delivery and event history is intentionally read-only: editing these rows would
# corrupt impression/click metrics and make commercial reporting unreliable.

@router.get("/deliveries", response_model=list[AdDeliveryRead])
def list_deliveries(
    campaign_id: int | None = Query(default=None, gt=0),
    creative_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[AdDelivery]:
    query = select(AdDelivery)
    if campaign_id is not None:
        query = query.where(AdDelivery.campaign_id == campaign_id)
    if creative_id is not None:
        query = query.where(AdDelivery.creative_id == creative_id)
    query = query.order_by(AdDelivery.id.desc()).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.get("/deliveries/{delivery_id}", response_model=AdDeliveryRead)
def get_delivery(delivery_id: int, db: Session = Depends(get_db)) -> AdDelivery:
    delivery = db.get(AdDelivery, delivery_id)
    if delivery is None:
        raise _not_found("Entrega", delivery_id)
    return delivery


@router.get("/events", response_model=list[AdEventRead])
def list_events(
    event_type: str | None = Query(default=None, pattern="^(impression|click)$"),
    delivery_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[AdEvent]:
    query = select(AdEvent)
    if event_type is not None:
        query = query.where(AdEvent.event_type == event_type)
    if delivery_id is not None:
        query = query.where(AdEvent.delivery_id == delivery_id)
    query = query.order_by(AdEvent.id.desc()).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.get("/events/{event_id}", response_model=AdEventRead)
def get_event(event_id: int, db: Session = Depends(get_db)) -> AdEvent:
    event = db.get(AdEvent, event_id)
    if event is None:
        raise _not_found("Evento", event_id)
    return event
