from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ANCHOR API"}


def test_health_does_not_require_authentication(client: TestClient) -> None:
    """The probe must answer without credentials."""
    assert client.get("/api/health").status_code == 200
