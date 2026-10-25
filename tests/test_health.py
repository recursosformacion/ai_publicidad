from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_does_not_expose_configuration() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ai_publicidad"}


def test_page_type_catalog_is_explicitly_provisional() -> None:
    response = client.get("/api/v1/metadata/page-types")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 1
    assert payload["status"] == "provisional"
    assert any(item["code"] == "work_detail" for item in payload["page_types"])
