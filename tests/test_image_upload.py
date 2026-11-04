"""Advertising image upload and WebP conversion."""

from io import BytesIO

from PIL import Image

from infrastructure.config import get_settings


def _jpeg(width: int = 320, height: int = 200) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (width, height), "white").save(stream, format="JPEG", quality=95)
    return stream.getvalue()


def _creative(client, campaign_id: int, fmt: str = "image") -> int:
    response = client.post(
        "/api/v1/admin/creatives",
        json={
            "campaign_id": campaign_id,
            "title": "Image creative",
            "body": None,
            "image_url": "https://example.org/old.jpg",
            "alt_text": "Anuncio de prueba",
            "format": fmt,
            "language": "es",
            "destination_url": "https://openmusicrepository.com/",
            "status": "approved",
            "ad_format_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _campaign(client) -> int:
    response = client.post(
        "/api/v1/admin/campaigns",
        json={"name": "Image upload campaign", "status": "active", "is_house_ad": True},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_upload_converts_to_webp_and_serves_it(client, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "image_root", str(tmp_path / "media"))
    creative_id = _creative(client, _campaign(client))

    response = client.post(
        f"/api/v1/admin/creatives/{creative_id}/image",
        files={"file": ("ad.jfif", _jpeg(), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["content_type"] == "image/webp"
    assert data["url"].endswith(f"/media/{data['sha256']}.webp")

    image = client.get(f"/media/{data['sha256']}.webp")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/webp"
    assert image.headers["cache-control"].startswith("public, max-age=")

    creative = client.get(f"/api/v1/admin/creatives/{creative_id}")
    assert creative.status_code == 200
    assert creative.json()["image_url"] == data["url"]


def test_image_upload_requires_image_format_and_alt_text(client, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "image_root", str(tmp_path / "media"))
    creative_id = _creative(client, _campaign(client), fmt="text")
    response = client.post(
        f"/api/v1/admin/creatives/{creative_id}/image",
        files={"file": ("ad.jpg", _jpeg(), "image/jpeg")},
    )
    assert response.status_code == 409

    text_response = client.post(
        f"/api/v1/admin/creatives/{creative_id}/image",
        files={"file": ("ad.txt", b"not an image", "text/plain")},
    )
    assert text_response.status_code in {400, 409}
