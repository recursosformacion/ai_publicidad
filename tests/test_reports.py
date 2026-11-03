"""Integration tests for read-only advertising reports and CSV export."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from domain.models import AdDelivery, AdEvent, AdOrder, Advertiser, Campaign, Creative


def _seed_report_data(engine):
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        advertiser = Advertiser(name="Anunciante de prueba", status="active")
        db.add(advertiser)
        db.flush()
        order = AdOrder(
            advertiser_id=advertiser.id,
            name="Pedido de prueba",
            status="active",
            billing_model="cpc",
            cpc_cents=25,
            currency="EUR",
        )
        db.add(order)
        db.flush()
        campaign = Campaign(name="Campaña comercial", status="active", order_id=order.id)
        house_campaign = Campaign(name="Campaña propia", status="active", is_house_ad=True)
        db.add_all([campaign, house_campaign])
        db.flush()
        creative = Creative(
            campaign_id=campaign.id,
            title="Creatividad de prueba",
            format="text",
            language="es",
            destination_url="https://example.com",
            status="approved",
        )
        house_creative = Creative(
            campaign_id=house_campaign.id,
            title="Anuncio propio",
            format="text",
            language="es",
            destination_url="https://example.org",
            status="approved",
        )
        db.add_all([creative, house_creative])
        db.flush()
        commercial_delivery = AdDelivery(
            token="commercial-report-token",
            creative_id=creative.id,
            campaign_id=campaign.id,
            application="omr",
            page_type="work",
            entity_type="work",
            entity_id="42",
            placement="sidebar",
            language="es",
            delivered_at=now,
            impression_confirmed=True,
            impression_confirmed_at=now,
        )
        house_delivery = AdDelivery(
            token="house-report-token",
            creative_id=house_creative.id,
            campaign_id=house_campaign.id,
            application="omr",
            page_type="home",
            placement="footer",
            language="ca",
            delivered_at=now,
        )
        db.add_all([commercial_delivery, house_delivery])
        db.flush()
        db.add_all([
            AdEvent(
                delivery_id=commercial_delivery.id,
                event_type="impression",
                occurred_at=now,
                deduplication_key=f"impression:{commercial_delivery.id}",
            ),
            AdEvent(
                delivery_id=commercial_delivery.id,
                event_type="click",
                occurred_at=now,
                charge_microcents=25_000_000,
            ),
            AdEvent(
                delivery_id=house_delivery.id,
                event_type="impression",
                occurred_at=now,
                deduplication_key=f"impression:{house_delivery.id}",
            ),
        ])
        db.commit()
        return advertiser.id, order.id, campaign.id


def test_report_summary_filters_campaign_and_computes_ctr(client, test_engine):
    advertiser_id, order_id, campaign_id = _seed_report_data(test_engine)
    today = datetime.now(timezone.utc).date().isoformat()

    response = client.get(
        "/api/v1/admin/reports/summary",
        params={
            "start_date": today,
            "end_date": today,
            "advertiser_id": advertiser_id,
            "order_id": order_id,
            "campaign_id": campaign_id,
            "dimension": "page_type",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["period"]["timezone"] == "UTC"
    assert data["summary"]["deliveries"] == 1
    assert data["summary"]["impressions"] == 1
    assert data["summary"]["clicks"] == 1
    assert data["summary"]["ctr_percent"] == 100.0
    assert data["summary"]["charge_microcents"] == 25_000_000
    assert data["breakdown"] == [{
        "label": "work",
        "deliveries": 1,
        "impressions": 1,
        "clicks": 1,
        "charge_microcents": 25_000_000,
    }]

    creative_report = client.get(
        "/api/v1/admin/reports/summary",
        params={"start_date": today, "end_date": today, "campaign_id": campaign_id, "dimension": "creative"},
    )
    assert creative_report.status_code == 200
    assert creative_report.json()["breakdown"][0]["label"] == "Creatividad de prueba"
    entity_report = client.get(
        "/api/v1/admin/reports/summary",
        params={"start_date": today, "end_date": today, "entity_type": "work", "dimension": "entity_id"},
    )
    assert entity_report.status_code == 200
    assert entity_report.json()["breakdown"][0]["label"] == "42"


def test_report_can_separate_house_ads_and_export_csv(client, test_engine):
    _seed_report_data(test_engine)
    today = datetime.now(timezone.utc).date().isoformat()

    response = client.get(
        "/api/v1/admin/reports/summary",
        params={"start_date": today, "end_date": today, "ad_kind": "house"},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["deliveries"] == 1
    assert response.json()["summary"]["impressions"] == 1
    assert response.json()["summary"]["clicks"] == 0

    export = client.get(
        "/api/v1/admin/reports/export.csv",
        params={"start_date": today, "end_date": today, "ad_kind": "commercial"},
    )
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert "Impresiones registradas" in export.text
    assert "resumen" in export.text
    assert "desglose" in export.text
    assert "diario" in export.text


def test_report_rejects_invalid_period_and_dimension(client):
    response = client.get(
        "/api/v1/admin/reports/summary",
        params={"start_date": "2026-01-03", "end_date": "2026-01-01"},
    )
    assert response.status_code == 422

    response = client.get(
        "/api/v1/admin/reports/summary",
        params={"dimension": "visitor_id"},
    )
    assert response.status_code == 422



def test_report_does_not_add_charges_from_different_currencies(client, test_engine):
    advertiser_id, _, _ = _seed_report_data(test_engine)
    now = datetime.now(timezone.utc)
    with Session(test_engine) as db:
        usd_order = AdOrder(
            advertiser_id=advertiser_id,
            name="Pedido USD",
            status="active",
            billing_model="cpc",
            cpc_cents=10,
            currency="USD",
        )
        db.add(usd_order)
        db.flush()
        campaign = Campaign(name="Campaña USD", status="active", order_id=usd_order.id)
        db.add(campaign)
        db.flush()
        creative = Creative(
            campaign_id=campaign.id,
            title="Creatividad USD",
            format="text",
            language="en",
            destination_url="https://example.net",
            status="approved",
        )
        db.add(creative)
        db.flush()
        delivery = AdDelivery(
            token="usd-report-token",
            creative_id=creative.id,
            campaign_id=campaign.id,
            application="omr",
            page_type="work",
            placement="sidebar",
            language="en",
            delivered_at=now,
        )
        db.add(delivery)
        db.flush()
        db.add(AdEvent(
            delivery_id=delivery.id,
            event_type="click",
            occurred_at=now,
            charge_microcents=10_000_000,
        ))
        db.commit()

    today = now.date().isoformat()
    response = client.get(
        "/api/v1/admin/reports/summary",
        params={"start_date": today, "end_date": today},
    )
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["multiple_currencies"] is True
    assert summary["charge_currency"] is None
    assert summary["charge_microcents"] is None
