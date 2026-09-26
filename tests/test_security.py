from fastapi.testclient import TestClient

from backend.main import app


def test_verify_rejects_repository_outside_workspace():
    response = TestClient(app).post("/api/verify", json={"repository_path": "C:/"})
    assert response.status_code == 400
