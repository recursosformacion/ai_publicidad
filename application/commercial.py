"""Commercial eligibility, privacy-safe frequency caps and budget accounting."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domain.models import AdDelivery, AdEvent, AdOrder, Advertiser, Campaign
from infrastructure.config import get_settings

PENDING_IMPRESSION_RESERVATION = timedelta(minutes=15)


def utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_day_start(now: datetime) -> datetime:
    current = utc_datetime(now) or datetime.now(timezone.utc)
    return datetime.combine(current.date(), time.min, tzinfo=timezone.utc)


def visitor_key_hash(visitor_id: str | None) -> str | None:
    """Hash opaque first-party visitor IDs; never persist the supplied identifier."""
    if not visitor_id:
        return None
    settings = get_settings()
    secret = settings.visitor_hash_secret or settings.service_token or "ai-publicidad-nonproduction-key"
    return hmac.new(secret.encode("utf-8"), visitor_id.encode("utf-8"), hashlib.sha256).hexdigest()


def _count_deliveries(db: Session, *, campaign_id: int | None = None, order_id: int | None = None,
                      visitor_hash: str | None = None, since: datetime | None = None) -> int:
    query = select(func.count(AdDelivery.id))
    if order_id is not None:
        query = query.join(Campaign, Campaign.id == AdDelivery.campaign_id).where(Campaign.order_id == order_id)
    if campaign_id is not None:
        query = query.where(AdDelivery.campaign_id == campaign_id)
    if visitor_hash is not None:
        query = query.where(AdDelivery.visitor_key_hash == visitor_hash)
    if since is not None:
        query = query.where(AdDelivery.delivered_at >= since)
    return int(db.scalar(query) or 0)


def _count_events(db: Session, event_type: str, *, campaign_id: int | None = None,
                  order_id: int | None = None, since: datetime | None = None) -> int:
    query = select(func.count(AdEvent.id)).join(
        AdDelivery, AdEvent.delivery_id == AdDelivery.id
    ).where(AdEvent.event_type == event_type)
    if order_id is not None:
        query = query.join(Campaign, Campaign.id == AdDelivery.campaign_id).where(Campaign.order_id == order_id)
    if campaign_id is not None:
        query = query.where(AdDelivery.campaign_id == campaign_id)
    if since is not None:
        query = query.where(AdEvent.occurred_at >= since)
    return int(db.scalar(query) or 0)


def _order_spend_microcents(db: Session, order: AdOrder, since: datetime | None = None,
                            now: datetime | None = None) -> int:
    """Charged events plus short-lived CPM reservations for unconfirmed deliveries."""
    query = select(func.coalesce(func.sum(AdEvent.charge_microcents), 0)).join(
        AdDelivery, AdEvent.delivery_id == AdDelivery.id
    ).join(Campaign, Campaign.id == AdDelivery.campaign_id).where(Campaign.order_id == order.id)
    if since is not None:
        query = query.where(AdEvent.occurred_at >= since)
    charged = int(db.scalar(query) or 0)
    current = utc_datetime(now) or datetime.now(timezone.utc)
    if order.billing_model != "cpm":
        return charged
    pending_query = select(func.count(AdDelivery.id)).join(
        Campaign, Campaign.id == AdDelivery.campaign_id
    ).where(
        Campaign.order_id == order.id,
        AdDelivery.impression_confirmed.is_(False),
        AdDelivery.delivered_at >= current - PENDING_IMPRESSION_RESERVATION,
    )
    if since is not None:
        pending_query = pending_query.where(AdDelivery.delivered_at >= since)
    pending_count = int(db.scalar(pending_query) or 0)
    return charged + pending_count * order.cpm_cents * 1_000


def _unit_charge_microcents(order: AdOrder) -> int:
    if order.billing_model == "cpm":
        return order.cpm_cents * 1_000
    if order.billing_model == "cpc":
        return order.cpc_cents * 1_000_000
    return 0


def charge_microcents_for_event(db: Session, campaign: Campaign, event_type: str) -> int:
    """Return a budget-safe event charge; fixed fee orders never accrue per-event charges."""
    if campaign.is_house_ad or campaign.order_id is None:
        return 0
    order = db.scalar(select(AdOrder).where(AdOrder.id == campaign.order_id).with_for_update())
    if order is None:
        return 0
    if event_type == "impression" and order.billing_model != "cpm":
        return 0
    if event_type == "click" and order.billing_model != "cpc":
        return 0
    charge = _unit_charge_microcents(order)
    if charge <= 0:
        return 0
    now = datetime.now(timezone.utc)
    spent = _order_spend_microcents(db, order, now=now)
    today_spent = _order_spend_microcents(db, order, since=utc_day_start(now), now=now)
    if order.total_budget_cents is not None and spent + charge > order.total_budget_cents * 1_000_000:
        return 0
    if order.daily_budget_cents is not None and today_spent + charge > order.daily_budget_cents * 1_000_000:
        return 0
    return charge


def _window_is_current(starts_at: datetime | None, ends_at: datetime | None, now: datetime) -> bool:
    starts, ends, current = utc_datetime(starts_at), utc_datetime(ends_at), utc_datetime(now)
    return not ((starts and starts > current) or (ends and ends < current))


def campaign_business_eligible(db: Session, campaign: Campaign, visitor_id: str | None, now: datetime) -> bool:
    """Apply campaign caps, advertiser/order status, budget ceilings and pacing."""
    day_start = utc_day_start(now)
    visitor_hash = visitor_key_hash(visitor_id)
    visitor_caps_configured = campaign.max_impressions_per_visitor > 0 or campaign.visitor_interval_seconds > 0
    if visitor_caps_configured and visitor_hash is None:
        return False

    if campaign.max_impressions_total is not None and _count_deliveries(db, campaign_id=campaign.id) >= campaign.max_impressions_total:
        return False
    if campaign.max_impressions_daily is not None and _count_deliveries(db, campaign_id=campaign.id, since=day_start) >= campaign.max_impressions_daily:
        return False
    if campaign.max_clicks_total is not None and _count_events(db, "click", campaign_id=campaign.id) >= campaign.max_clicks_total:
        return False
    if campaign.max_clicks_daily is not None and _count_events(db, "click", campaign_id=campaign.id, since=day_start) >= campaign.max_clicks_daily:
        return False

    if visitor_hash:
        if campaign.max_impressions_per_visitor > 0 and _count_deliveries(db, campaign_id=campaign.id, visitor_hash=visitor_hash) >= campaign.max_impressions_per_visitor:
            return False
        if campaign.visitor_interval_seconds > 0:
            repeat_after = (utc_datetime(now) or datetime.now(timezone.utc)) - timedelta(seconds=campaign.visitor_interval_seconds)
            if _count_deliveries(db, campaign_id=campaign.id, visitor_hash=visitor_hash, since=repeat_after):
                return False

    if campaign.order_id is None:
        return True

    # MySQL row lock serializes eligibility/budget reservations for one order.
    order = db.scalar(select(AdOrder).where(AdOrder.id == campaign.order_id).with_for_update())
    if order is None or order.status != "active" or not _window_is_current(order.starts_at, order.ends_at, now):
        return False
    advertiser = db.get(Advertiser, order.advertiser_id)
    if advertiser is None or advertiser.status != "active":
        return False

    if order.impression_limit_total is not None and _count_deliveries(db, order_id=order.id) >= order.impression_limit_total:
        return False
    if order.impression_limit_daily is not None and _count_deliveries(db, order_id=order.id, since=day_start) >= order.impression_limit_daily:
        return False
    if order.click_limit_total is not None and _count_events(db, "click", order_id=order.id) >= order.click_limit_total:
        return False
    if order.click_limit_daily is not None and _count_events(db, "click", order_id=order.id, since=day_start) >= order.click_limit_daily:
        return False

    if order.billing_model in {"cpm", "cpc"}:
        unit = _unit_charge_microcents(order)
        spent = _order_spend_microcents(db, order, now=now)
        spent_daily = _order_spend_microcents(db, order, since=day_start, now=now)
        if order.total_budget_cents is not None:
            budget = order.total_budget_cents * 1_000_000
            if spent >= budget or spent + unit > budget:
                return False
            if order.pacing_mode == "even":
                start, end = utc_datetime(order.starts_at), utc_datetime(order.ends_at)
                if start is not None and end is not None and end > start:
                    elapsed = max(0.0, min(1.0, (now - start).total_seconds() / (end - start).total_seconds()))
                    allowed = max(unit, int(budget * elapsed))
                    if spent >= allowed:
                        return False
        if order.daily_budget_cents is not None:
            daily_budget = order.daily_budget_cents * 1_000_000
            if spent_daily >= daily_budget or spent_daily + unit > daily_budget:
                return False
    return True
