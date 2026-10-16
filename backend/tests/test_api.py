from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_database():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["database"] is True


def test_trace_id_is_echoed_or_generated():
    assert client.get("/api/health", headers={"x-request-id": "abc"}).headers["x-request-id"] == "abc"
    assert len(client.get("/api/health").headers["x-request-id"]) == 32


def test_unknown_api_path_is_json_404():
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_static_paths_cannot_escape_dist():
    assert client.get("/..%2F..%2Fbackend%2Fpyproject.toml").text.find("[project]") == -1
