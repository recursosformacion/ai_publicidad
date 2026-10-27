"""Integration tests for bounded HTML composition and immediate view accounting."""

from html.parser import HTMLParser

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.main import app
from domain.models import AdDelivery, AdEvent


class _AdHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.root: dict[str, str | None] | None = None
        self.cards: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "div" and "ap-layout" in (values.get("class") or "").split():
            self.root = values
        if tag == "a" and "ap-ad-card" in (values.get("class") or "").split():
            self.cards.append(values)


def _make_format(client, code: str, width: int, height: int, category: str) -> int:
    response = client.post(
        "/api/v1/admin/ad-formats",
        json={
            "code": code,
            "name": f"Test {code}",
            "width": width,
            "height": height,
            "device": "both",
            "category": category,
            "placement_notes": None,
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _make_creative(client, campaign_id: int, title: str, fmt_id: int) -> int:
    campaign_title = title
    creative = client.post(
        "/api/v1/admin/creatives",
        json={
            "campaign_id": campaign_id,
            "title": campaign_title,
            "body": "Anuncio de laboratorio.",
            "image_url": None,
            "alt_text": None,
            "format": "responsive",
            "language": "es",
            "destination_url": "https://openmusicrepository.com/",
            "status": "approved",
            "ad_format_ids": [fmt_id],
        },
    )
    assert creative.status_code == 201, creative.text
    creative_id = creative.json()["id"]
    for rule_type, rule_value in (
        ("application", "osap"),
        ("placement", "layout_lab"),
    ):
        rule = client.post(
            "/api/v1/admin/targeting-rules",
            json={
                "creative_id": creative_id,
                "rule_type": rule_type,
                "rule_value": rule_value,
                "effect": "include",
            },
        )
        assert rule.status_code == 201, rule.text
    return creative_id


def _seed_layout_candidates(client) -> dict[str, int]:
    rectangle = _make_format(client, "lab_rectangle_300x250", 300, 250, "rectangle")
    square = _make_format(client, "lab_square_200x200", 200, 200, "square")
    banner = _make_format(client, "lab_banner_320x50", 320, 50, "banner")

    def add_house(title: str, fmt_id: int) -> int:
        campaign = client.post(
            "/api/v1/admin/campaigns",
            json={
                "name": f"Layout lab campaign {title}",
                "status": "active",
                "starts_at": None,
                "ends_at": None,
                "priority": 10,
                "is_house_ad": True,
            },
        )
        assert campaign.status_code == 201, campaign.text
        return _make_creative(client, campaign.json()["id"], title, fmt_id)

    return {
        "rectangle": add_house("Lab rectangle one", rectangle),
        "rectangle2": add_house("Lab rectangle two", rectangle),
        "square": add_house("Lab square", square),
        "banner": add_house("Lab banner", banner),
    }

def _compose_payload(width: int, height: int, **overrides) -> dict:
    payload = {
        "application": "osap",
        "page": {
            "type": "ad_layout_lab",
            "entity_type": "layout_test",
            "entity_id": f"test-{width}x{height}",
            "language": "es",
        },
        "placement": "layout_lab",
        "device": "desktop",
        "mode": "auto_area",
        "area": {"width": width, "height": height},
        "max_ads": 3,
        "gap": 12,
        "orientation": "auto",
    }
    payload.update(overrides)
    return payload


def test_composer_uses_largest_available_size_and_never_mixes_sizes(client, test_engine):
    creative_ids = _seed_layout_candidates(client)

    response = client.post("/api/v1/ads/compose", json=_compose_payload(640, 320))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    parser = _AdHtmlParser()
    parser.feed(response.text)
    root = parser.root
    assert root is not None
    assert root["data-layout-status"] == "ok"
    assert root["data-layout"] == "row"
    assert root["data-ad-count"] == "2"
    assert root["data-area-width"] == "640"
    assert root["data-area-height"] == "320"

    cards = parser.cards
    assert len(cards) == 2
    selected_creatives = {int(card["data-ad-id"] or 0) for card in cards}
    assert selected_creatives == {creative_ids["rectangle"], creative_ids["rectangle2"]}
    # Every card in one block must have exactly the same dimensions.
    assert {(card["data-width"], card["data-height"]) for card in cards} == {("300", "250")}
    for card in cards:
        x, y = int(card["data-x"] or 0), int(card["data-y"] or 0)
        width, height = int(card["data-width"] or 0), int(card["data-height"] or 0)
        assert x >= 0 and y >= 0
        assert x + width <= 640
        assert y + height <= 320
        assert "/r/" in (card["href"] or "")
        assert card.get("data-impression-id")

    with Session(test_engine) as db:
        deliveries = db.query(AdDelivery).all()
        events = db.query(AdEvent).all()
        assert len(deliveries) == 2
        assert len(events) == 2
        assert all(delivery.impression_confirmed for delivery in deliveries)
        assert all(delivery.impression_confirmed_at is not None for delivery in deliveries)
        assert all(event.event_type == "impression" for event in events)
        assert {delivery.page_type for delivery in deliveries} == {"ad_layout_lab"}
        assert {delivery.placement for delivery in deliveries} == {"layout_lab"}


def test_fixed_format_returns_exactly_one_ad_and_counts_its_view(client, test_engine):
    creative_ids = _seed_layout_candidates(client)
    response = client.post(
        "/api/v1/ads/compose",
        json={
            "application": "osap",
            "page": {
                "type": "ad_layout_lab",
                "entity_type": "layout_test",
                "entity_id": "fixed-format",
                "language": "es",
            },
            "placement": "layout_lab",
            "device": "desktop",
            "mode": "fixed_format",
            "format_code": "lab_rectangle_300x250",
        },
    )
    assert response.status_code == 200
    parser = _AdHtmlParser()
    parser.feed(response.text)
    cards = parser.cards
    assert len(cards) == 1
    assert int(cards[0]["data-ad-id"] or 0) == creative_ids["rectangle"]
    assert cards[0]["data-width"] == "300"
    assert cards[0]["data-height"] == "250"

    with Session(test_engine) as db:
        assert db.query(AdDelivery).count() == 1
        assert db.query(AdEvent).count() == 1


def test_no_fill_returns_an_empty_fragment_without_creating_views(client, test_engine):
    _seed_layout_candidates(client)
    response = client.post("/api/v1/ads/compose", json=_compose_payload(140, 80))
    assert response.status_code == 200
    assert 'data-layout-status="no-fill"' in response.text
    assert "No hay anuncios compatibles" in response.text

    with Session(test_engine) as db:
        assert db.query(AdDelivery).count() == 0
        assert db.query(AdEvent).count() == 0


def test_layout_lab_is_local_only_and_page_is_packaged(client, monkeypatch):
    response = client.get("/layout-lab")
    assert response.status_code == 200
    assert "Laboratorio de composición publicitaria" in response.text
    assert 'data-case="wide"' in response.text
    assert "Solicitar composición" in response.text

    from types import SimpleNamespace

    monkeypatch.setattr("api.routes.layout_lab.get_settings", lambda: SimpleNamespace(env="production"))
    hidden = client.get("/layout-lab")
    assert hidden.status_code == 404

    # Development mode alone is not enough when pointed at a MySQL database.
    monkeypatch.setattr(
        "api.routes.layout_lab.get_settings",
        lambda: SimpleNamespace(
            env="development",
            database_url="mysql+pymysql://user:password@localhost/OSAP_PUBLICIDAD",
            enable_layout_lab=False,
        ),
    )
    hidden_mysql = client.get("/layout-lab")
    assert hidden_mysql.status_code == 404

    monkeypatch.setattr(
        "api.routes.layout_lab.get_settings",
        lambda: SimpleNamespace(
            env="development",
            database_url="mysql+pymysql://user:password@localhost/OSAP_PUBLICIDAD",
            enable_layout_lab=True,
        ),
    )
    allowed_mysql = client.get("/layout-lab")
    assert allowed_mysql.status_code == 200
