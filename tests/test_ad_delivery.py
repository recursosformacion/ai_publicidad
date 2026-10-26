from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.models import AdDelivery, AdEvent, Campaign, Creative, TargetingRule


def _serve_payload() -> dict:
    return {
        "application": "osap",
        "page": {
            "type": "work_detail",
            "entity_type": "work",
            "entity_id": "42",
            "language": "es",
        },
        "placement": "sidebar",
        "format": {"type": "text"},
    }


def _campaign_payload(name: str, *, status: str = "active", priority: int = 0, house: bool = False) -> dict:
    return {
        "name": name,
        "status": status,
        "starts_at": None,
        "ends_at": None,
        "priority": priority,
        "is_house_ad": house,
    }


def _creative_payload(campaign_id: int, title: str, *, format: str = "text") -> dict:
    return {
        "campaign_id": campaign_id,
        "title": title,
        "body": "Texto de prueba",
        "image_url": None,
        "alt_text": None,
        "format": format,
        "language": "es",
        "destination_url": "https://openmusicrepository.com/",
        "status": "approved",
    }


def test_admin_crud_and_delivery_uses_commercial_then_house_fallback(client, test_engine):
    # Create a real configuration through the public HTTP routes, not direct ORM inserts.
    commercial_campaign = client.post(
        "/api/v1/admin/campaigns",
        json=_campaign_payload("test commercial", priority=100),
    )
    assert commercial_campaign.status_code == 201
    commercial_campaign_id = commercial_campaign.json()["id"]

    commercial_creative = client.post(
        "/api/v1/admin/creatives",
        json=_creative_payload(commercial_campaign_id, "Commercial ad"),
    )
    assert commercial_creative.status_code == 201
    commercial_creative_id = commercial_creative.json()["id"]

    rule = client.post(
        "/api/v1/admin/targeting-rules",
        json={
            "creative_id": commercial_creative_id,
            "rule_type": "page_type",
            "rule_value": "work_detail",
            "effect": "include",
        },
    )
    assert rule.status_code == 201
    rule_id = rule.json()["id"]
    assert client.get(f"/api/v1/admin/targeting-rules/{rule_id}").json()["rule_value"] == "work_detail"

    # Multiple include values for the same field are alternatives, not an AND.
    alternative_rule = client.post(
        "/api/v1/admin/targeting-rules",
        json={
            "creative_id": commercial_creative_id,
            "rule_type": "page_type",
            "rule_value": "person_detail",
            "effect": "include",
        },
    )
    assert alternative_rule.status_code == 201

    house_campaign = client.post(
        "/api/v1/admin/campaigns",
        json=_campaign_payload("test OSAP fallback", priority=-100, house=True),
    )
    assert house_campaign.status_code == 201
    house_campaign_id = house_campaign.json()["id"]
    house_creative = client.post(
        "/api/v1/admin/creatives",
        json=_creative_payload(house_campaign_id, "OSAP fallback", format="responsive"),
    )
    assert house_creative.status_code == 201
    house_creative_id = house_creative.json()["id"]

    # The API chooses the commercial creative while its campaign is active.
    commercial_delivery = client.post("/api/v1/ads/serve", json=_serve_payload())
    assert commercial_delivery.status_code == 200
    commercial_payload = commercial_delivery.json()
    assert commercial_payload["kind"] == "commercial"
    assert commercial_payload["is_house_ad"] is False
    assert commercial_payload["ad_id"] == commercial_creative_id

    # Repeated impression confirmations produce one counted impression.
    impression_request = {"impression_id": commercial_payload["impression_id"]}
    first_impression = client.post("/api/v1/events/impression", json=impression_request)
    second_impression = client.post("/api/v1/events/impression", json=impression_request)
    assert first_impression.status_code == second_impression.status_code == 200
    assert first_impression.json()["counted"] is True
    assert second_impression.json()["counted"] is False

    # Pause the commercial campaign via CRUD and request the same slot again.
    paused = client.put(
        f"/api/v1/admin/campaigns/{commercial_campaign_id}",
        json=_campaign_payload("test commercial", status="paused", priority=100),
    )
    assert paused.status_code == 200
    house_delivery = client.post("/api/v1/ads/serve", json=_serve_payload())
    assert house_delivery.status_code == 200
    house_payload = house_delivery.json()
    assert house_payload["kind"] == "house"
    assert house_payload["is_house_ad"] is True
    assert house_payload["ad_id"] == house_creative_id

    # Delivery and event tables are observable but intentionally read-only.
    deliveries = client.get("/api/v1/admin/deliveries")
    assert deliveries.status_code == 200
    assert len(deliveries.json()) == 2
    events = client.get("/api/v1/admin/events?event_type=impression")
    assert events.status_code == 200
    assert len(events.json()) == 1

    # Rows referenced by delivery history cannot be deleted out from under reports.
    assert client.delete(f"/api/v1/admin/creatives/{commercial_creative_id}").status_code == 409

    with Session(test_engine) as db:
        saved_deliveries = db.scalars(select(AdDelivery)).all()
        assert len(saved_deliveries) == 2
        saved_events = db.scalars(select(AdEvent)).all()
        assert len(saved_events) == 1
        assert saved_events[0].event_type == "impression"
        saved_rule = db.get(TargetingRule, rule_id)
        assert saved_rule is not None


def test_admin_can_update_and_delete_configuration_without_history(client, test_engine):
    campaign_response = client.post(
        "/api/v1/admin/campaigns", json=_campaign_payload("CRUD campaign")
    )
    assert campaign_response.status_code == 201
    campaign_id = campaign_response.json()["id"]

    creative_response = client.post(
        "/api/v1/admin/creatives", json=_creative_payload(campaign_id, "CRUD creative")
    )
    assert creative_response.status_code == 201
    creative_id = creative_response.json()["id"]

    updated_creative_data = _creative_payload(campaign_id, "Updated creative")
    updated_creative_data["status"] = "paused"
    updated_creative = client.put(
        f"/api/v1/admin/creatives/{creative_id}", json=updated_creative_data
    )
    assert updated_creative.status_code == 200
    assert updated_creative.json()["title"] == "Updated creative"
    assert updated_creative.json()["status"] == "paused"

    rule_response = client.post(
        "/api/v1/admin/targeting-rules",
        json={
            "creative_id": creative_id,
            "rule_type": "placement",
            "rule_value": "sidebar",
            "effect": "include",
        },
    )
    assert rule_response.status_code == 201
    rule_id = rule_response.json()["id"]
    rule_update = client.put(
        f"/api/v1/admin/targeting-rules/{rule_id}",
        json={
            "creative_id": creative_id,
            "rule_type": "placement",
            "rule_value": "header",
            "effect": "exclude",
        },
    )
    assert rule_update.status_code == 200
    assert rule_update.json()["rule_value"] == "header"

    assert client.get(f"/api/v1/admin/creatives?campaign_id={campaign_id}").status_code == 200
    assert client.delete(f"/api/v1/admin/targeting-rules/{rule_id}").json() == {"deleted": True}
    assert client.delete(f"/api/v1/admin/creatives/{creative_id}").json() == {"deleted": True}
    assert client.delete(f"/api/v1/admin/campaigns/{campaign_id}").json() == {"deleted": True}

    with Session(test_engine) as db:
        assert db.get(Campaign, campaign_id) is None
        assert db.get(Creative, creative_id) is None
        assert db.get(TargetingRule, rule_id) is None


def test_click_redirect_uses_database_destination_not_request_url(client, test_engine):
    campaign_response = client.post(
        "/api/v1/admin/campaigns", json=_campaign_payload("redirect test")
    )
    campaign_id = campaign_response.json()["id"]
    creative_data = _creative_payload(campaign_id, "Redirect test")
    creative_data["destination_url"] = "https://example.org/ad"
    creative_response = client.post("/api/v1/admin/creatives", json=creative_data)
    assert creative_response.status_code == 201

    delivery = client.post("/api/v1/ads/serve", json=_serve_payload())
    assert delivery.status_code == 200
    click_url = delivery.json()["click_url"].replace("http://127.0.0.1:8305", "")
    response = client.get(click_url, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.org/ad"

    with Session(test_engine) as db:
        click_event = db.scalar(select(AdEvent).where(AdEvent.event_type == "click"))
        assert click_event is not None


def test_admin_rejects_unsafe_destinations(client):
    campaign_response = client.post(
        "/api/v1/admin/campaigns", json=_campaign_payload("unsafe destination test")
    )
    campaign_id = campaign_response.json()["id"]
    creative_data = _creative_payload(campaign_id, "Unsafe creative")
    creative_data["destination_url"] = "javascript:alert(1)"
    response = client.post("/api/v1/admin/creatives", json=creative_data)
    assert response.status_code == 422


def test_initial_house_seed_is_idempotent():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from scripts.seed_house_ads import CAMPAIGN_NAME, CREATIVE_TITLE, seed_house_ads

    test_engine = create_engine("sqlite://")
    try:
        from domain.models import Base

        Base.metadata.create_all(bind=test_engine)
        with Session(test_engine) as db:
            assert seed_house_ads(db) is True
            db.commit()

        with Session(test_engine) as db:
            campaign = db.query(Campaign).filter(Campaign.name == CAMPAIGN_NAME).one()
            creative = (
                db.query(Creative)
                .filter(Creative.campaign_id == campaign.id, Creative.title == CREATIVE_TITLE)
                .one()
            )
            assert campaign.is_house_ad is True
            assert campaign.status == "active"
            assert creative.status == "approved"
            assert creative.language == "es"
            assert creative.format == "responsive"
            assert creative.destination_url == "https://openmusicrepository.com/"
            assert seed_house_ads(db) is False
            db.commit()
            assert db.query(Campaign).count() == 1
            assert db.query(Creative).count() == 1
    finally:
        test_engine.dispose()
