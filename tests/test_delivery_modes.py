"""Delivery-mode separation: fixed vs adaptive creatives."""

from __future__ import annotations


def _campaign(client) -> int:
    response = client.post(
        "/api/v1/admin/campaigns",
        json={"name": "Delivery modes", "status": "active", "is_house_ad": True},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _format(client) -> int:
    response = client.post(
        "/api/v1/admin/ad-formats",
        json={
            "code": "delivery_300x250",
            "name": "Delivery 300x250",
            "width": 300,
            "height": 250,
            "device": "both",
            "category": "rectangle",
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _creative(client, campaign_id: int, format_id: int, delivery: str) -> int:
    response = client.post(
        "/api/v1/admin/creatives",
        json={
            "campaign_id": campaign_id,
            "title": f"Creative {delivery}",
            "body": "Anuncio de prueba",
            "format": "text",
            "delivery_mode": delivery,
            "language": "es",
            "destination_url": "https://openmusicrepository.com/",
            "status": "approved",
            "ad_format_ids": [format_id],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _compose(client, **extra):
    payload = {
        "application": "osap",
        "page": {"type": "work_detail", "language": "es"},
        "placement": "content_top",
        "mode": "auto_area",
        "area": {"width": 300, "height": 250},
        "max_ads": 1,
    }
    payload.update(extra)
    return client.post("/api/v1/ads/compose", json=payload)


def test_fixed_creative_is_not_used_for_adaptive_request(client):
    campaign_id = _campaign(client)
    _creative(client, campaign_id, _format(client), "fixed")
    response = _compose(client)
    assert response.status_code == 200
    assert "ap-ad-card" not in response.text
    assert 'data-layout-status="no-fill"' in response.text


def test_adaptive_creative_is_used_for_adaptive_request(client):
    campaign_id = _campaign(client)
    format_id = _format(client)
    _creative(client, campaign_id, format_id, "adaptive")
    response = _compose(client)
    assert response.status_code == 200
    assert "ap-ad-card" in response.text
    assert 'data-format="delivery_300x250"' in response.text


def test_adaptive_creative_is_not_used_for_fixed_request(client):
    campaign_id = _campaign(client)
    format_id = _format(client)
    _creative(client, campaign_id, format_id, "adaptive")
    response = _compose(client, mode="fixed_format", format_code="delivery_300x250")
    assert response.status_code == 200
    assert 'data-layout-status="no-fill"' in response.text
