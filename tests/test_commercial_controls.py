"""Integration tests for commercial orders, budgets and visitor frequency caps."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.models import AdDelivery, AdEvent, Campaign


def _campaign(client, name: str, **extra) -> int:
    data = {"name": name, "status": "active", "starts_at": None, "ends_at": None, "priority": 10, "is_house_ad": False, "brand_id": None, "minimum_interval_seconds": 0}
    data.update(extra)
    response = client.post("/api/v1/admin/campaigns", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _creative(client, campaign_id: int, name: str) -> int:
    response = client.post("/api/v1/admin/creatives", json={
        "campaign_id": campaign_id, "title": name, "body": "Anuncio de control comercial",
        "image_url": None, "alt_text": None, "format": "text", "language": "es",
        "destination_url": "https://openmusicrepository.com/", "status": "approved", "ad_format_ids": [],
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _serve_payload(visitor_id: str | None = None) -> dict:
    payload = {"application": "osap", "page": {"type": "work_detail", "entity_type": "work", "entity_id": "commercial-test", "language": "es"}, "placement": "sidebar", "format": {"type": "text"}}
    if visitor_id is not None:
        payload["visitor_id"] = visitor_id
    return payload


def _advertiser(client) -> int:
    response = client.post("/api/v1/admin/advertisers", json={
        "name": "Cliente de pruebas", "legal_name": "Cliente de pruebas SL",
        "contact_name": "Administración", "contact_email": "ads@example.org",
        "phone": None, "website_url": "https://example.org/", "notes": None, "status": "active",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _order(client, *, advertiser_id: int, **overrides) -> int:
    payload = {"advertiser_id": advertiser_id, "name": "Pedido de pruebas", "reference": None, "status": "active",
        "starts_at": None, "ends_at": None, "currency": "EUR", "billing_model": "fixed", "fixed_fee_cents": 0,
        "total_budget_cents": None, "daily_budget_cents": None, "cpm_cents": 0, "cpc_cents": 0,
        "impression_limit_total": None, "impression_limit_daily": None, "click_limit_total": None, "click_limit_daily": None, "pacing_mode": "none"}
    payload.update(overrides)
    response = client.post("/api/v1/admin/orders", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_advertisers_orders_and_safe_archiving(client):
    advertiser_id = _advertiser(client)
    order_id = _order(client, advertiser_id=advertiser_id, reference="OSAP-TEST-ORD-1")
    assert client.get(f"/api/v1/admin/orders/{order_id}").json()["advertiser_id"] == advertiser_id
    assert len(client.get(f"/api/v1/admin/orders?advertiser_id={advertiser_id}").json()) == 1
    campaign_id = _campaign(client, "Order-linked campaign", order_id=order_id)
    _creative(client, campaign_id, "Order-linked ad")
    deleted_order = client.delete(f"/api/v1/admin/orders/{order_id}")
    assert deleted_order.json()["archived"] is True
    assert client.get(f"/api/v1/admin/orders/{order_id}").json()["status"] == "archived"
    deleted_advertiser = client.delete(f"/api/v1/admin/advertisers/{advertiser_id}")
    assert deleted_advertiser.json()["archived"] is True
    assert client.get(f"/api/v1/admin/advertisers/{advertiser_id}").json()["status"] == "archived"


def test_visitor_frequency_caps_fail_closed_and_only_hash_is_stored(client, test_engine):
    campaign_id = _campaign(client, "Visitor cap", max_impressions_per_visitor=1)
    creative_id = _creative(client, campaign_id, "Visitor limited ad")
    first = client.post("/api/v1/ads/serve", json=_serve_payload("opaque-visitor-1"))
    assert first.status_code == 200 and first.json()["ad_id"] == creative_id
    assert client.post("/api/v1/ads/serve", json=_serve_payload("opaque-visitor-1")).status_code == 503
    assert client.post("/api/v1/ads/serve", json=_serve_payload()).status_code == 503
    assert client.post("/api/v1/ads/serve", json=_serve_payload("opaque-visitor-2")).status_code == 200
    with Session(test_engine) as db:
        deliveries = db.scalars(select(AdDelivery).where(AdDelivery.campaign_id == campaign_id)).all()
        assert len(deliveries) == 2
        assert all(item.visitor_key_hash for item in deliveries)
        assert all("opaque-visitor" not in item.visitor_key_hash for item in deliveries)


def test_cpm_budget_reserves_pending_delivery_then_charges_confirmed_impression(client, test_engine):
    advertiser_id = _advertiser(client)
    order_id = _order(client, advertiser_id=advertiser_id, name="One-impression budget", billing_model="cpm", total_budget_cents=1, cpm_cents=1000)
    campaign_id = _campaign(client, "CPM campaign", order_id=order_id)
    creative_id = _creative(client, campaign_id, "Budget controlled ad")
    first = client.post("/api/v1/ads/serve", json=_serve_payload())
    assert first.status_code == 200 and first.json()["ad_id"] == creative_id
    assert client.post("/api/v1/ads/serve", json=_serve_payload()).status_code == 503
    confirm = client.post("/api/v1/events/impression", json={"impression_id": first.json()["impression_id"]})
    assert confirm.status_code == 200 and confirm.json()["counted"] is True
    assert client.post("/api/v1/ads/serve", json=_serve_payload()).status_code == 503
    with Session(test_engine) as db:
        event = db.scalar(select(AdEvent).where(AdEvent.event_type == "impression"))
        assert event is not None and event.charge_microcents == 1_000_000
        assert db.query(Campaign).filter_by(id=campaign_id).one().order_id == order_id


def test_order_schema_rejects_invalid_cpm_and_pacing(client):
    advertiser_id = _advertiser(client)
    invalid_cpm = client.post("/api/v1/admin/orders", json={"advertiser_id": advertiser_id, "name": "Bad CPM", "billing_model": "cpm", "cpm_cents": 0})
    assert invalid_cpm.status_code == 422
    invalid_pacing = client.post("/api/v1/admin/orders", json={"advertiser_id": advertiser_id, "name": "Bad pacing", "billing_model": "cpm", "cpm_cents": 100, "pacing_mode": "even"})
    assert invalid_pacing.status_code == 422
