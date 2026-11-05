"""Smoke tests for the web maintenance panel."""

from fastapi.testclient import TestClient

from api.main import app


def test_admin_panel_is_served_and_contains_navigation_and_crud_controls():
    with TestClient(app) as client:
        response = client.get("/admin")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    for marker in (
        "Campañas",
        "Creatividades / anuncios",
        "Reglas de segmentación",
        "Marcas y competencia",
        "Formatos de anuncio",
        "Entregas",
        "Impresiones y clics",
        "Informes y estadísticas",
        'id="report-card"',
        'id="report-start"',
        'id="report-creative"',
        'id="report-export"',
        "reportSummary",
        "reportExport",
        "async function apiAll(path)",
        '(item.id?item.label+" (#"+item.id+")":item.label)',
        'id="record-form"',
        'id="create"',
        'id="save-form"',
        "openForm(r,true)",
        "controls[key].disabled=readOnly",
        "specsForHistory(row)",
        'key:"ad_format_ids"',
        '["html_package","HTML (ZIP)"]',
        'id="package-upload"',
        "uploadPackage",
        'id="image-source"',
        'id="image-url"',
        "uploadImage",
        'id="creative-preview"',
        "refreshCreativePreview",
        'data-section="ad-formats"',
        'data-section="brands"',
        'key:"brand_id"',
        'key:"minimum_interval_seconds"',
        'key:"competitor_brand_ids"',
        'type:"multi-select"',
        "Borrar",
        "Editar",
        "Ver",
        'id="include-archived"',
        "Mostrar archivados",
        "archived",
    ):
        assert marker in html


def test_admin_panel_uses_osap_favicon_and_funding_link():
    with TestClient(app) as client:
        page = client.get("/admin")
        icon = client.get("/favicon.ico")

    assert page.status_code == 200
    assert '<link rel="icon" type="image/x-icon" href="/favicon.ico">' in page.text
    assert "Financiar OSAP" in page.text
    assert "https://app.openmusicrepository.com/support" in page.text
    assert icon.status_code == 200
    assert icon.headers["content-type"] == "image/x-icon"
    assert icon.content


def test_history_sections_are_read_only_in_the_web_panel():
    with TestClient(app) as client:
        response = client.get("/admin")

    assert response.status_code == 200
    html = response.text
    assert 'deliveries:{label:"Entregas"' in html
    assert 'events:{label:"Impresiones y clics"' in html
    assert "editable:false" in html
    assert 'id="detail-dialog"' not in html
    assert 'id="detail-content"' not in html
