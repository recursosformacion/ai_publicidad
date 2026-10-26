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
        "Entregas",
        "Impresiones y clics",
        'id="record-form"',
        'id="create"',
        'id="save-form"',
        "openForm(r,true)",
        "controls[key].disabled=readOnly",
        "specsForHistory(row)",
        "Borrar",
        "Editar",
        "Ver",
    ):
        assert marker in html


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
