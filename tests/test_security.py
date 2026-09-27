from fastapi.testclient import TestClient

from backend.main import app


def test_verify_rejects_invalid_repository_path():
    response = TestClient(app).post("/api/verify", json={"repository_path": "C:/definitely-missing-repo"})
    assert response.status_code == 400
