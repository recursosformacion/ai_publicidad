"""Integration tests for isolated static HTML ad packages."""

import io
import zipfile

from infrastructure.config import get_settings


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _creative(client, campaign_id: int, *, fmt: str = "html_package", formats=None) -> int:
    response = client.post(
        "/api/v1/admin/creatives",
        json={
            "campaign_id": campaign_id,
            "title": "HTML package ad",
            "body": "Paquete HTML",
            "image_url": None,
            "alt_text": None,
            "format": fmt,
            "language": "es",
            "destination_url": "https://openmusicrepository.com/",
            "status": "approved",
            "ad_format_ids": formats or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _format(client) -> int:
    response = client.post(
        "/api/v1/admin/ad-formats",
        json={
            "code": "html_test_300x250",
            "name": "HTML test 300x250",
            "width": 300,
            "height": 250,
            "device": "both",
            "category": "rectangle",
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _campaign(client) -> int:
    response = client.post(
        "/api/v1/admin/campaigns",
        json={
            "name": "HTML package campaign",
            "status": "active",
            "priority": 10,
            "is_house_ad": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _configure_package_root(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "package_root", str(tmp_path / "packages"))
    monkeypatch.setattr(settings, "package_content_base_url", "http://127.0.0.1:8305")
    monkeypatch.setattr(settings, "package_frame_ancestors", "http://osap-app")
    return settings


def _upload(client, creative_id: int, payload: bytes, name: str = "ad.zip"):
    return client.post(
        f"/api/v1/admin/creatives/{creative_id}/package",
        files={"file": (name, payload, "application/zip")},
    )


def test_html_package_upload_and_isolated_serving(client, monkeypatch, tmp_path):
    _configure_package_root(monkeypatch, tmp_path)
    creative_id = _creative(client, _campaign(client))
    package = _zip({
        "index.html": (
            b"<!doctype html><html><body>"
            b"<link rel=stylesheet href=style.css><h1>Ad</h1></body></html>"
        ),
        "style.css": b"h1{color:#123}",
        "logo.svg": b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
    })

    response = _upload(client, creative_id, package)
    assert response.status_code == 201, response.text
    data = response.json()
    assert len(data["sha256"]) == 64
    assert data["entrypoint"] == "index.html"

    html = client.get(f"/pkg/{data['sha256']}/index.html")
    assert html.status_code == 200
    assert "default-src 'none'" in html.headers["content-security-policy"]
    assert "img-src http://127.0.0.1:8305" in html.headers["content-security-policy"]
    assert "frame-ancestors http://osap-app" in html.headers["content-security-policy"]
    assert html.headers["x-content-type-options"] == "nosniff"
    assert html.headers["cache-control"].startswith("public, max-age=")

    css = client.get(f"/pkg/{data['sha256']}/style.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")

    assert client.get(f"/pkg/{data['sha256']}/missing.css").status_code == 404


def test_html_package_rejects_script_and_path_traversal(client, monkeypatch, tmp_path):
    _configure_package_root(monkeypatch, tmp_path)
    creative_id = _creative(client, _campaign(client))

    script = _zip({"index.html": b"<html></html>", "ad.js": b"alert(1)"})
    assert _upload(client, creative_id, script).status_code == 422

    traversal = _zip({"index.html": b"<html></html>", "../secret.txt": b"x"})
    assert _upload(client, creative_id, traversal).status_code == 422

    assert _upload(client, creative_id, b"not a zip").status_code == 422


def test_html_package_renders_isolated_iframe_and_click_overlay(client, monkeypatch, tmp_path):
    _configure_package_root(monkeypatch, tmp_path)
    creative_id = _creative(client, _campaign(client), formats=[_format(client)])
    package = _zip({"index.html": b"<html><body>Static ad</body></html>"})
    package_data = _upload(client, creative_id, package).json()

    response = client.post(
        "/api/v1/ads/compose",
        json={
            "application": "osap",
            "page": {"type": "work_detail", "language": "es"},
            "placement": "content_top",
            "mode": "auto_area",
            "area": {"width": 300, "height": 250},
            "max_ads": 1,
        },
    )
    assert response.status_code == 200, response.text
    markup = response.text
    assert f"/pkg/{package_data['sha256']}/index.html" in markup
    assert 'sandbox=""' in markup
    assert "/r/" in markup
    assert 'class="ap-ad-card ap-ad-html"' in markup

    serve = client.post(
        "/api/v1/ads/serve",
        json={
            "application": "osap",
            "page": {"type": "work_detail", "language": "es"},
            "placement": "content_top",
            "format": {"type": "html_package", "width": 300, "height": 250},
        },
    )
    assert serve.status_code == 200, serve.text
    assert serve.json()["format"] == "html_package"
    assert serve.json()["package_url"].endswith(f"/pkg/{package_data['sha256']}/index.html")


def test_html_package_requires_format_and_package(client, monkeypatch, tmp_path):
    _configure_package_root(monkeypatch, tmp_path)
    creative_id = _creative(client, _campaign(client), fmt="text")
    assert _upload(client, creative_id, _zip({"index.html": b"<html></html>"})).status_code == 409
