from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_plan_and_implementation_require_analysis_approval():
    analysis = client.post("/api/analyze", json={"request": "Add phone-number authentication"}).json()
    analysis_id = analysis["id"]

    plan = client.post("/api/plan", json={"analysis_id": analysis_id})
    assert plan.status_code == 200
    assert plan.json()["plan"]

    pending = client.post("/api/implement", json={"analysis_id": analysis_id})
    assert pending.status_code == 200
    assert pending.json()["status"] == "approval_required"

    approved = client.post("/api/implement", json={"analysis_id": analysis_id, "approved": True})
    assert approved.status_code == 200
    assert approved.json()["changed_files"] == []


def test_implementation_rejects_files_outside_analysis():
    analysis = client.post("/api/analyze", json={"request": "Add phone-number authentication"}).json()
    response = client.post("/api/implement", json={"analysis_id": analysis["id"], "approved": True, "files": ["secrets.env"]})
    assert response.status_code == 400


def test_report_includes_actual_verification_result():
    analysis = client.post("/api/analyze", json={"request": "Add phone-number authentication"}).json()
    verification = client.post("/api/verify", json={"repository_path": "sample-project", "analysis_id": analysis["id"]})
    report = client.get(f"/api/report/{analysis['id']}")
    assert verification.json()["status"] == "passed"
    assert report.json()["status"] == "verified"
    assert report.json()["report"]["verification"]["exit_code"] == 0