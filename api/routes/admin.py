"""Administration API for campaign configuration and read-only history."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.admin_schemas import (
    AdDeliveryRead,
    AdEventRead,
    AdFormatInput,
    AdFormatRead,
    BrandInput,
    BrandRead,
    CampaignInput,
    CampaignRead,
    CreativeInput,
    CreativeRead,
    TargetingRuleInput,
    TargetingRuleRead,
)
from domain.models import (
    AdDelivery,
    AdEvent,
    AdFormat,
    AdOrder,
    Brand,
    Campaign,
    Creative,
    TargetingRule,
    brand_competitors,
    creative_ad_formats,
)
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


def _resolve_ad_formats(db: Session, format_ids: list[int]) -> list[AdFormat]:
    if not format_ids:
        return []
    formats = list(db.scalars(select(AdFormat).where(AdFormat.id.in_(format_ids))).all())
    found_ids = {ad_format.id for ad_format in formats}
    missing_ids = sorted(set(format_ids) - found_ids)
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"No existen estos formatos de anuncio: {missing_ids}",
        )
    return formats


# Brands and competitor relationships

def _brand_payload(db: Session, brand: Brand) -> dict[str, object]:
    rows = db.execute(
        select(brand_competitors.c.brand_left_id, brand_competitors.c.brand_right_id).where(
            (brand_competitors.c.brand_left_id == brand.id)
            | (brand_competitors.c.brand_right_id == brand.id)
        )
    ).all()
    competitors = sorted(
        right if left == brand.id else left
        for left, right in rows
    )
    return {
        "id": brand.id,
        "name": brand.name,
        "website_url": brand.website_url,
        "notes": brand.notes,
        "is_active": brand.is_active,
        "competitor_brand_ids": competitors,
    }


def _set_brand_competitors(
    db: Session,
    brand_id: int,
    competitor_ids: list[int],
) -> None:
    if brand_id in competitor_ids:
        raise HTTPException(status_code=422, detail="Una marca no puede ser competidora de sí misma.")
    other_ids = set(competitor_ids)
    if other_ids:
        found = set(
            db.scalars(select(Brand.id).where(Brand.id.in_(other_ids))).all()
        )
        missing = sorted(other_ids - found)
        if missing:
            raise HTTPException(status_code=404, detail=f"No existen estas marcas competidoras: {missing}")

    db.execute(
        brand_competitors.delete().where(
            (brand_competitors.c.brand_left_id == brand_id)
            | (brand_competitors.c.brand_right_id == brand_id)
        )
    )
    for other_id in sorted(other_ids):
        left, right = sorted((brand_id, other_id))
        db.execute(
            brand_competitors.insert().values(
                brand_left_id=left,
                brand_right_id=right,
            )
        )


@router.get("/brands", response_model=list[BrandRead])
def list_brands(
    include_inactive: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    query = select(Brand)
    if not include_inactive:
        query = query.where(Brand.is_active.is_(True))
    brands = list(db.scalars(query.order_by(Brand.name).offset(offset).limit(limit)).all())
    return [_brand_payload(db, brand) for brand in brands]


@router.post("/brands", response_model=BrandRead, status_code=status.HTTP_201_CREATED)
def create_brand(payload: BrandInput, db: Session = Depends(get_db)) -> dict[str, object]:
    brand = Brand(
        name=payload.name.strip(),
        website_url=payload.website_url,
        notes=payload.notes,
        is_active=payload.is_active,
    )
    try:
        db.add(brand)
        db.flush()
        _set_brand_competitors(db, brand.id, payload.competitor_brand_ids)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una marca con ese nombre.") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(brand)
    return _brand_payload(db, brand)


@router.get("/brands/{brand_id}", response_model=BrandRead)
def get_brand(brand_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise _not_found("Marca", brand_id)
    return _brand_payload(db, brand)


@router.put("/brands/{brand_id}", response_model=BrandRead)
def replace_brand(
    brand_id: int, payload: BrandInput, db: Session = Depends(get_db)
) -> dict[str, object]:
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise _not_found("Marca", brand_id)
    brand.name = payload.name.strip()
    brand.website_url = payload.website_url
    brand.notes = payload.notes
    brand.is_active = payload.is_active
    try:
        _set_brand_competitors(db, brand.id, payload.competitor_brand_ids)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una marca con ese nombre.") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(brand)
    return _brand_payload(db, brand)


@router.delete("/brands/{brand_id}")
def delete_brand(brand_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise _not_found("Marca", brand_id)
    linked_campaigns = db.scalar(
        select(func.count()).select_from(Campaign).where(Campaign.brand_id == brand_id)
    ) or 0
    if linked_campaigns:
        brand.is_active = False
        db.commit()
        return {
            "deleted": False,
            "deactivated": True,
            "message": "La marca se ha desactivado porque tiene campañas asociadas.",
        }
    db.execute(
        brand_competitors.delete().where(
            (brand_competitors.c.brand_left_id == brand_id)
            | (brand_competitors.c.brand_right_id == brand_id)
        )
    )
    db.delete(brand)
    db.commit()
    return {"deleted": True}


# Standard ad-format catalogue

@router.get("/ad-formats", response_model=list[AdFormatRead])
def list_ad_formats(
    include_inactive: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[AdFormat]:
    query = select(AdFormat)
    if not include_inactive:
        query = query.where(AdFormat.is_active.is_(True))
    query = query.order_by(AdFormat.width, AdFormat.height).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.post("/ad-formats", response_model=AdFormatRead, status_code=status.HTTP_201_CREATED)
def create_ad_format(payload: AdFormatInput, db: Session = Depends(get_db)) -> AdFormat:
    ad_format = AdFormat(**payload.model_dump())
    db.add(ad_format)
    _commit_or_conflict(db, "Ya existe un formato con ese código.")
    db.refresh(ad_format)
    return ad_format


@router.get("/ad-formats/{format_id}", response_model=AdFormatRead)
def get_ad_format(format_id: int, db: Session = Depends(get_db)) -> AdFormat:
    ad_format = db.get(AdFormat, format_id)
    if ad_format is None:
        raise _not_found("Formato de anuncio", format_id)
    return ad_format


@router.put("/ad-formats/{format_id}", response_model=AdFormatRead)
def replace_ad_format(
    format_id: int, payload: AdFormatInput, db: Session = Depends(get_db)
) -> AdFormat:
    ad_format = db.get(AdFormat, format_id)
    if ad_format is None:
        raise _not_found("Formato de anuncio", format_id)
    for key, value in payload.model_dump().items():
        setattr(ad_format, key, value)
    _commit_or_conflict(db, "Ya existe otro formato con ese código.")
    db.refresh(ad_format)
    return ad_format


@router.delete("/ad-formats/{format_id}")
def delete_ad_format(format_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    ad_format = db.get(AdFormat, format_id)
    if ad_format is None:
        raise _not_found("Formato de anuncio", format_id)

    creative_count = db.scalar(
        select(func.count())
        .select_from(creative_ad_formats)
        .where(creative_ad_formats.c.ad_format_id == format_id)
    ) or 0
    delivery_count = db.scalar(
        select(func.count())
        .select_from(AdDelivery)
        .where(AdDelivery.ad_format_id == format_id)
    ) or 0
    if creative_count or delivery_count:
        ad_format.is_active = False
        db.commit()
        return {
            "deleted": False,
            "deactivated": True,
            "message": (
                "El formato se ha desactivado porque está asociado a anuncios o entregas. "
                "Se conserva el histórico y no se ofrecerá para nuevas entregas."
            ),
        }

    db.delete(ad_format)
    db.commit()
    return {"deleted": True}


# Campaigns

@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(
    include_archived: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[Campaign]:
    query = select(Campaign)
    if not include_archived:
        query = query.where(Campaign.status != "archived")
    query = query.order_by(Campaign.id.desc()).offset(offset).limit(limit)
    return list(db.scalars(query).all())


def _validate_campaign_brand(db: Session, brand_id: int | None) -> None:
    if brand_id is not None and db.get(Brand, brand_id) is None:
        raise HTTPException(status_code=404, detail=f"Marca {brand_id} no existe")


def _validate_campaign_order(db: Session, order_id: int | None) -> None:
    if order_id is not None and db.get(AdOrder, order_id) is None:
        raise HTTPException(status_code=404, detail=f"Pedido/contrato {order_id} no existe")


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignInput, db: Session = Depends(get_db)) -> Campaign:
    _validate_campaign_brand(db, payload.brand_id)
    _validate_campaign_order(db, payload.order_id)
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
    _validate_campaign_brand(db, payload.brand_id)
    _validate_campaign_order(db, payload.order_id)
    for key, value in payload.model_dump().items():
        setattr(campaign, key, value)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise _not_found("Campaña", campaign_id)

    creatives = list(
        db.scalars(select(Creative).where(Creative.campaign_id == campaign_id)).all()
    )
    delivery_count = db.scalar(
        select(func.count())
        .select_from(AdDelivery)
        .where(AdDelivery.campaign_id == campaign_id)
    ) or 0

    if delivery_count:
        # Keep the campaign, creatives, and targeting linked to immutable delivery
        # history, but make every item ineligible for future delivery.
        campaign.status = "archived"
        for creative in creatives:
            creative.status = "archived"
        db.commit()
        return {
            "deleted": False,
            "archived": True,
            "message": (
                "La campaña y sus creatividades se han archivado porque existen entregas "
                "históricas. Las estadísticas se conservan y los anuncios dejan de entregarse."
            ),
        }

    # No deliveries reference the campaign, so its dependent setup can be removed safely.
    creative_ids = [creative.id for creative in creatives]
    if creative_ids:
        db.query(TargetingRule).filter(TargetingRule.creative_id.in_(creative_ids)).delete(
            synchronize_session=False
        )
    for creative in creatives:
        db.delete(creative)
    db.delete(campaign)
    db.commit()
    return {"deleted": True}


# Creatives

@router.get("/creatives", response_model=list[CreativeRead])
def list_creatives(
    campaign_id: int | None = Query(default=None, gt=0),
    include_archived: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[Creative]:
    query = select(Creative)
    if campaign_id is not None:
        query = query.where(Creative.campaign_id == campaign_id)
    if not include_archived:
        query = query.where(Creative.status != "archived")
    query = query.order_by(Creative.id.desc()).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.post("/creatives", response_model=CreativeRead, status_code=status.HTTP_201_CREATED)
def create_creative(payload: CreativeInput, db: Session = Depends(get_db)) -> Creative:
    if db.get(Campaign, payload.campaign_id) is None:
        raise HTTPException(status_code=404, detail=f"Campaña {payload.campaign_id} no existe")
    creative = Creative(**payload.model_dump(exclude={"ad_format_ids"}))
    creative.ad_formats = _resolve_ad_formats(db, payload.ad_format_ids)
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
    for key, value in payload.model_dump(exclude={"ad_format_ids"}).items():
        setattr(creative, key, value)
    creative.ad_formats = _resolve_ad_formats(db, payload.ad_format_ids)
    db.commit()
    db.refresh(creative)
    return creative


@router.delete("/creatives/{creative_id}")
def delete_creative(creative_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    creative = db.get(Creative, creative_id)
    if creative is None:
        raise _not_found("Creatividad", creative_id)

    delivery_count = db.scalar(
        select(func.count())
        .select_from(AdDelivery)
        .where(AdDelivery.creative_id == creative_id)
    ) or 0
    if delivery_count:
        # A soft delete preserves historical reporting while immediately excluding
        # this creative from delivery (the serving endpoint only selects approved rows).
        creative.status = "archived"
        db.commit()
        return {
            "deleted": False,
            "archived": True,
            "message": (
                "La creatividad se ha archivado porque tiene entregas históricas. "
                "Las estadísticas se conservan y el anuncio deja de entregarse."
            ),
        }

    db.query(TargetingRule).filter(TargetingRule.creative_id == creative_id).delete()
    db.delete(creative)
    db.commit()
    return {"deleted": True}


# Targeting rules

@router.get("/targeting-rules", response_model=list[TargetingRuleRead])
def list_targeting_rules(
    creative_id: int | None = Query(default=None, gt=0),
    include_archived: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[TargetingRule]:
    query = select(TargetingRule).join(Creative, Creative.id == TargetingRule.creative_id)
    if creative_id is not None:
        query = query.where(TargetingRule.creative_id == creative_id)
    if not include_archived:
        query = query.where(Creative.status != "archived")
    query = query.order_by(TargetingRule.id.desc()).offset(offset).limit(limit)
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
