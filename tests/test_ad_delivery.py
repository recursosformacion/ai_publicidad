from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.main import app
from domain.models import AdDelivery, Base, Campaign, Creative
from infrastructure.database import engine

client = TestClient(app)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        commercial = Campaign(name="commercial", status="active", priority=100, is_house_ad=False)
        house = Campaign(name="house", status="active", priority=0, is_house_ad=True)
        db.add_all([commercial, house])
        db.flush()
        db.add_all([
            Creative(campaign_id=commercial.id, title="Ad", body="Text", destination_url="https://example.org/ad", format="text", language="es", status="approved"),
            Creative(campaign_id=house.id, title="OSAP", body="Explore the catalogue", destination_url="https://openmusicrepository.com", format="text", language="es", status="approved"),
        ])
        db.commit()


def _payload() -> dict:
    return {
        "application": "osap",
        "page": {"type": "work_detail", "entity_type": "work", "entity_id": "42", "language": "es"},
        "placement": "sidebar",
        "format": {"type": "text"},
    }


def test_serve_ad_returns_commercial_and_impression_can_be_confirmed_once() -> None:
    response = client.post("/api/v1/ads/serve", json=_payload())
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "commercial"

    first = client.post("/api/v1/events/impression", json={"impression_id": payload["impression_id"]})
    second = client.post("/api/v1/events/impression", json={"impression_id": payload["impression_id"]})
    assert first.status_code == second.status_code == 200
    with Session(engine) as db:
        delivery = db.query(AdDelivery).one()
        assert delivery.impression_confirmed is True
        assert len([e for e in delivery.__dict__ if e == "id"]) == 1


def test_house_ad_is_used_when_no_commercial_creative_matches() -> None:
    with Session(engine) as db:
        db.query(Creative).filter(Creative.title == "Ad").update({"status": "paused"})
        db.commit()
    response = client.post("/api/v1/ads/serve", json=_payload())
    assert response.status_code == 200
    assert response.json()["kind"] == "house"


def test_click_redirect_uses_database_destination_not_request_url() -> None:
    payload = client.post("/api/v1/ads/serve", json=_payload()).json()
    response = client.get(payload["click_url"].replace("http://127.0.0.1:8305", ""), follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.org/ad"
