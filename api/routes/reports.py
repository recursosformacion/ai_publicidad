"""Read-only aggregated reporting for the administration panel."""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from application.security import require_service_token
from domain.models import AdDelivery, AdEvent, AdFormat, AdOrder, Advertiser, Campaign, Creative
from infrastructure.database import get_db

router = APIRouter(
    prefix="/admin/reports",
    tags=["advertising reports"],
    dependencies=[Depends(require_service_token)],
)

DIMENSIONS = {
    "application": (AdDelivery.application, "application"),
    "page_type": (AdDelivery.page_type, "page_type"),
    "placement": (AdDelivery.placement, "placement"),
    "language": (AdDelivery.language, "language"),
    "entity_type": (AdDelivery.entity_type, "entity_type"),
    "format": (AdFormat.name, "format"),
    "campaign": (Campaign.name, "campaign"),
    "creative": (Creative.title, "creative"),
    "advertiser": (Advertiser.name, "advertiser"),
}


def _period(start_date: date | None, end_date: date | None) -> tuple[date, date, datetime, datetime]:
    today = datetime.now(timezone.utc).date()
    end = end_date or today
    start = start_date or (end - timedelta(days=29))
    if end < start:
        raise HTTPException(status_code=422, detail="end_date debe ser igual o posterior a start_date")
    if (end - start).days > 365:
        raise HTTPException(status_code=422, detail="El intervalo máximo de consulta es de 366 días")
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end, start_dt, end_dt


def _apply_delivery_filters(query, start_dt, end_dt, advertiser_id, order_id, campaign_id, creative_id, ad_kind,
                            application, page_type, placement, language):
    query = query.where(AdDelivery.delivered_at >= start_dt, AdDelivery.delivered_at < end_dt)
    if advertiser_id is not None:
        query = query.where(AdOrder.advertiser_id == advertiser_id)
    if order_id is not None:
        query = query.where(Campaign.order_id == order_id)
    if campaign_id is not None:
        query = query.where(Campaign.id == campaign_id)
    if creative_id is not None:
        query = query.where(AdDelivery.creative_id == creative_id)
    if ad_kind == "house":
        query = query.where(Campaign.is_house_ad.is_(True))
    elif ad_kind == "commercial":
        query = query.where(Campaign.is_house_ad.is_(False), Campaign.order_id.is_not(None))
    if application:
        query = query.where(AdDelivery.application == application)
    if page_type:
        query = query.where(AdDelivery.page_type == page_type)
    if placement:
        query = query.where(AdDelivery.placement == placement)
    if language:
        query = query.where(AdDelivery.language == language)
    return query


def _apply_event_filters(query, start_dt, end_dt, advertiser_id, order_id, campaign_id, creative_id, ad_kind,
                         application, page_type, placement, language):
    query = query.where(AdEvent.occurred_at >= start_dt, AdEvent.occurred_at < end_dt)
    if advertiser_id is not None:
        query = query.where(AdOrder.advertiser_id == advertiser_id)
    if order_id is not None:
        query = query.where(Campaign.order_id == order_id)
    if campaign_id is not None:
        query = query.where(Campaign.id == campaign_id)
    if ad_kind == "house":
        query = query.where(Campaign.is_house_ad.is_(True))
    elif ad_kind == "commercial":
        query = query.where(Campaign.is_house_ad.is_(False), Campaign.order_id.is_not(None))
    if application:
        query = query.where(AdDelivery.application == application)
    if page_type:
        query = query.where(AdDelivery.page_type == page_type)
    if placement:
        query = query.where(AdDelivery.placement == placement)
    if language:
        query = query.where(AdDelivery.language == language)
    return query


def _report_data(db: Session, *, start_date: date | None, end_date: date | None,
                 advertiser_id: int | None, order_id: int | None, campaign_id: int | None, creative_id: int | None,
                 ad_kind: str, application: str | None, page_type: str | None,
                 placement: str | None, language: str | None, dimension: str) -> dict:
    start, end, start_dt, end_dt = _period(start_date, end_date)

    delivery_query = (
        select(func.count(AdDelivery.id))
        .select_from(AdDelivery)
        .join(Campaign, Campaign.id == AdDelivery.campaign_id)
        .outerjoin(AdOrder, AdOrder.id == Campaign.order_id)
    )
    delivery_query = _apply_delivery_filters(
        delivery_query, start_dt, end_dt, advertiser_id, order_id, campaign_id, creative_id, ad_kind,
        application, page_type, placement, language,
    )
    deliveries = int(db.scalar(delivery_query) or 0)

    event_base = (
        select(
            func.sum(case((AdEvent.event_type == "impression", 1), else_=0)),
            func.sum(case((AdEvent.event_type == "click", 1), else_=0)),
            func.coalesce(func.sum(AdEvent.charge_microcents), 0),
        )
        .select_from(AdEvent)
        .join(AdDelivery, AdDelivery.id == AdEvent.delivery_id)
        .join(Campaign, Campaign.id == AdDelivery.campaign_id)
        .outerjoin(AdOrder, AdOrder.id == Campaign.order_id)
    )
    event_base = _apply_event_filters(
        event_base, start_dt, end_dt, advertiser_id, order_id, campaign_id, ad_kind,
        application, page_type, placement, language,
    )
    impressions, clicks, charges = db.execute(event_base).one()
    impressions, clicks, charges = int(impressions or 0), int(clicks or 0), int(charges or 0)

    currency_query = (
        select(AdOrder.currency)
        .select_from(AdDelivery)
        .join(Campaign, Campaign.id == AdDelivery.campaign_id)
        .join(AdOrder, AdOrder.id == Campaign.order_id)
        .where(AdOrder.currency.is_not(None))
    )
    currency_query = _apply_delivery_filters(
        currency_query, start_dt, end_dt, advertiser_id, order_id, campaign_id, ad_kind,
        application, page_type, placement, language,
    ).distinct()
    currencies = sorted(set(db.scalars(currency_query).all()))
    charge_currency = currencies[0] if len(currencies) == 1 else None
    if len(currencies) > 1:
        # Never add monetary amounts from different currencies into one total.
        charges = None

    dimension_expr, dimension_name = DIMENSIONS[dimension]
    delivery_group = (
        select(dimension_expr.label("label"), func.count(AdDelivery.id).label("deliveries"))
        .select_from(AdDelivery)
        .join(Campaign, Campaign.id == AdDelivery.campaign_id)
        .outerjoin(AdOrder, AdOrder.id == Campaign.order_id)
    )
    if dimension == "format":
        delivery_group = delivery_group.outerjoin(AdFormat, AdFormat.id == AdDelivery.ad_format_id)
    if dimension == "creative":
        delivery_group = delivery_group.join(Creative, Creative.id == AdDelivery.creative_id)
    if dimension == "advertiser":
        delivery_group = delivery_group.outerjoin(Advertiser, Advertiser.id == AdOrder.advertiser_id)
    delivery_group = _apply_delivery_filters(
        delivery_group, start_dt, end_dt, advertiser_id, order_id, campaign_id, ad_kind,
        application, page_type, placement, language,
    ).group_by(dimension_expr).order_by(func.count(AdDelivery.id).desc()).limit(100)

    event_group = (
        select(
            dimension_expr.label("label"),
            func.sum(case((AdEvent.event_type == "impression", 1), else_=0)).label("impressions"),
            func.sum(case((AdEvent.event_type == "click", 1), else_=0)).label("clicks"),
            func.coalesce(func.sum(AdEvent.charge_microcents), 0).label("charge_microcents"),
        )
        .select_from(AdEvent)
        .join(AdDelivery, AdDelivery.id == AdEvent.delivery_id)
        .join(Campaign, Campaign.id == AdDelivery.campaign_id)
        .outerjoin(AdOrder, AdOrder.id == Campaign.order_id)
    )
    if dimension == "format":
        event_group = event_group.outerjoin(AdFormat, AdFormat.id == AdDelivery.ad_format_id)
    if dimension == "creative":
        event_group = event_group.join(Creative, Creative.id == AdDelivery.creative_id)
    if dimension == "advertiser":
        event_group = event_group.outerjoin(Advertiser, Advertiser.id == AdOrder.advertiser_id)
    event_group = _apply_event_filters(
        event_group, start_dt, end_dt, advertiser_id, order_id, campaign_id, ad_kind,
        application, page_type, placement, language,
    ).group_by(dimension_expr).order_by(func.sum(case((AdEvent.event_type == "impression", 1), else_=0)).desc()).limit(100)

    grouped: dict[str, dict] = {}
    for row in db.execute(delivery_group):
        label = str(row.label or "(sin dato)")
        grouped[label] = {"label": label, "deliveries": int(row.deliveries or 0),
                          "impressions": 0, "clicks": 0, "charge_microcents": 0}
    for row in db.execute(event_group):
        label = str(row.label or "(sin dato)")
        item = grouped.setdefault(label, {"label": label, "deliveries": 0,
                                          "impressions": 0, "clicks": 0, "charge_microcents": 0})
        item["impressions"] = int(row.impressions or 0)
        item["clicks"] = int(row.clicks or 0)
        item["charge_microcents"] = int(row.charge_microcents or 0)
    breakdown = sorted(grouped.values(), key=lambda item: (item["deliveries"], item["impressions"], item["clicks"]), reverse=True)
    if len(currencies) > 1:
        for item in breakdown:
            item["charge_microcents"] = None

    delivery_days = (
        select(func.date(AdDelivery.delivered_at).label("day"), func.count(AdDelivery.id))
        .select_from(AdDelivery)
        .join(Campaign, Campaign.id == AdDelivery.campaign_id)
        .outerjoin(AdOrder, AdOrder.id == Campaign.order_id)
    )
    delivery_days = _apply_delivery_filters(
        delivery_days, start_dt, end_dt, advertiser_id, order_id, campaign_id, ad_kind,
        application, page_type, placement, language,
    ).group_by(func.date(AdDelivery.delivered_at))
    event_days = (
        select(
            func.date(AdEvent.occurred_at).label("day"),
            func.sum(case((AdEvent.event_type == "impression", 1), else_=0)),
            func.sum(case((AdEvent.event_type == "click", 1), else_=0)),
            func.coalesce(func.sum(AdEvent.charge_microcents), 0),
        )
        .select_from(AdEvent)
        .join(AdDelivery, AdDelivery.id == AdEvent.delivery_id)
        .join(Campaign, Campaign.id == AdDelivery.campaign_id)
        .outerjoin(AdOrder, AdOrder.id == Campaign.order_id)
    )
    event_days = _apply_event_filters(
        event_days, start_dt, end_dt, advertiser_id, order_id, campaign_id, ad_kind,
        application, page_type, placement, language,
    ).group_by(func.date(AdEvent.occurred_at))

    days: dict[str, dict] = {}
    for day, count in db.execute(delivery_days):
        key = str(day)
        days[key] = {"date": key, "deliveries": int(count or 0), "impressions": 0, "clicks": 0,
                     "charge_microcents": 0}
    for day, day_impressions, day_clicks, day_charges in db.execute(event_days):
        key = str(day)
        item = days.setdefault(key, {"date": key, "deliveries": 0, "impressions": 0, "clicks": 0,
                                      "charge_microcents": 0})
        item["impressions"] = int(day_impressions or 0)
        item["clicks"] = int(day_clicks or 0)
        item["charge_microcents"] = int(day_charges or 0)

    if len(currencies) > 1:
        for item in days.values():
            item["charge_microcents"] = None

    return {
        "period": {"start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": "UTC"},
        "filters": {"advertiser_id": advertiser_id, "order_id": order_id, "campaign_id": campaign_id,
                    "ad_kind": ad_kind, "application": application, "page_type": page_type,
                    "placement": placement, "language": language},
        "summary": {
            "deliveries": deliveries, "impressions": impressions, "clicks": clicks,
            "ctr_percent": round(clicks / impressions * 100, 4) if impressions else None,
            "charge_microcents": charges,
            "charge_currency": charge_currency,
            "multiple_currencies": len(currencies) > 1,
        },
        "daily": [days[key] for key in sorted(days)],
        "dimension": dimension_name,
        "breakdown": breakdown,
        "methodology": {
            "delivery_date": "delivered_at",
            "event_date": "occurred_at",
            "timezone": "UTC",
            "impressions": "Eventos impression registrados; no certifican visibilidad en pantalla.",
            "clicks": "Eventos click registrados al activar el enlace de seguimiento.",
            "charges": "Suma de cargos técnicos de eventos en microcéntimos; no es factura ni cobro.",
        },
    }


def _parameters(start_date, end_date, advertiser_id, order_id, campaign_id, creative_id, ad_kind,
                application, page_type, placement, language, dimension):
    return dict(start_date=start_date, end_date=end_date, advertiser_id=advertiser_id,
                order_id=order_id, campaign_id=campaign_id, creative_id=creative_id, ad_kind=ad_kind,
                application=application, page_type=page_type, placement=placement,
                language=language, dimension=dimension)


@router.get("/summary")
def report_summary(
    start_date: date | None = None,
    end_date: date | None = None,
    advertiser_id: int | None = Query(default=None, gt=0),
    order_id: int | None = Query(default=None, gt=0),
    campaign_id: int | None = Query(default=None, gt=0),
    creative_id: int | None = Query(default=None, gt=0),
    ad_kind: str = Query(default="all", pattern="^(all|commercial|house)$"),
    application: str | None = Query(default=None, max_length=80),
    page_type: str | None = Query(default=None, max_length=80),
    placement: str | None = Query(default=None, max_length=80),
    language: str | None = Query(default=None, max_length=12),
    dimension: str = Query(default="page_type", pattern="^(application|page_type|placement|language|entity_type|format|campaign|creative|advertiser)$"),
    db: Session = Depends(get_db),
) -> dict:
    """Return read-only KPIs, daily activity and one selectable breakdown."""
    return _report_data(db, **_parameters(start_date, end_date, advertiser_id, order_id,
                                          campaign_id, creative_id, ad_kind, application, page_type,
                                          placement, language, dimension))


@router.get("/export.csv")
def report_export_csv(
    start_date: date | None = None,
    end_date: date | None = None,
    advertiser_id: int | None = Query(default=None, gt=0),
    order_id: int | None = Query(default=None, gt=0),
    campaign_id: int | None = Query(default=None, gt=0),
    ad_kind: str = Query(default="all", pattern="^(all|commercial|house)$"),
    application: str | None = Query(default=None, max_length=80),
    page_type: str | None = Query(default=None, max_length=80),
    placement: str | None = Query(default=None, max_length=80),
    language: str | None = Query(default=None, max_length=12),
    dimension: str = Query(default="page_type", pattern="^(application|page_type|placement|language|entity_type|format|campaign|advertiser)$"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export the same filtered report as a UTF-8 CSV spreadsheet."""
    data = _report_data(db, **_parameters(start_date, end_date, advertiser_id, order_id,
                                          campaign_id, ad_kind, application, page_type,
                                          placement, language, dimension))
    output = StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Tipo", "Periodo UTC", "Dimensión", "Elemento", "Entregas", "Impresiones registradas",
                     "Clics registrados", "CTR (%)", "Moneda", "Cargo técnico (microcéntimos; vacío si hay varias monedas)"])
    summary = data["summary"]
    writer.writerow(["resumen", f'{data["period"]["start_date"]}–{data["period"]["end_date"]}', "", "TOTAL",
                     summary["deliveries"], summary["impressions"], summary["clicks"],
                     summary["ctr_percent"] if summary["ctr_percent"] is not None else "",
                     summary["charge_currency"] or "", summary["charge_microcents"] if summary["charge_microcents"] is not None else ""])
    for row in data["breakdown"]:
        ctr = round(row["clicks"] / row["impressions"] * 100, 4) if row["impressions"] else ""
        writer.writerow(["desglose", "", data["dimension"], row["label"], row["deliveries"],
                         row["impressions"], row["clicks"], ctr, data["summary"]["charge_currency"] or "", row["charge_microcents"] if row["charge_microcents"] is not None else ""])
    for row in data["daily"]:
        ctr = round(row["clicks"] / row["impressions"] * 100, 4) if row["impressions"] else ""
        writer.writerow(["diario", row["date"], "", "", row["deliveries"], row["impressions"],
                         row["clicks"], ctr, data["summary"]["charge_currency"] or "", row["charge_microcents"] if row["charge_microcents"] is not None else ""])
    output.seek(0)
    filename = f'publicidad-{data["period"]["start_date"]}-{data["period"]["end_date"]}.csv'
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
