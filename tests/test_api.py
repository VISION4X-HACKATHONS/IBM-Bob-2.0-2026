from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analyzer.repository import validate_repository_path
from backend.main import _is_public_github_https_url, _resolve_repository, app


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_public_github_https_url_is_validated():
    assert _is_public_github_https_url("https://github.com/example/demo.git") is True
    assert _is_public_github_https_url("http://github.com/example/demo") is False
    assert _is_public_github_https_url("https://example.com/example/demo") is False
    assert _is_public_github_https_url("file:///tmp/repo") is False


def test_git_url_is_cloned_and_used_as_repository(monkeypatch, tmp_path):
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    (repo / "app.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (repo / "test_app.py").write_text("def test_hello():\n    assert hello() == 'world'\n", encoding="utf-8")

    def fake_clone(_url: str, target: Path):
        target.mkdir(parents=True, exist_ok=True)
        for child in repo.iterdir():
            if child.is_file():
                (target / child.name).write_text(child.read_text(encoding="utf-8"), encoding="utf-8")
        return target

    monkeypatch.setattr("backend.main.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr("backend.main.tempfile.mkdtemp", lambda prefix: str(tmp_path / "clone-root"))
    monkeypatch.setattr("backend.main.Path.mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.main._clone_public_github_repo", lambda repo_url: repo)
    resolved = _resolve_repository("https://github.com/example/demo.git")
    assert resolved == repo.resolve()


def test_gemini_provider_generates_patch(monkeypatch):
    from backend.services import code_generator

    repo = (Path(__file__).resolve().parents[1] / "sample-project").resolve()
    monkeypatch.setattr(code_generator, "_load_plan_context", lambda _plan_id: ({"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}], "request": "Add phone auth"}}, {"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}, "plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}))
    monkeypatch.setattr(code_generator, "_call_gemini", lambda _prompt: '{"files": [{"file": "app/auth/service.py", "content": "from app.users.service import find_by_email\n\n\ndef authenticate(email: str, password: str) -> bool:\n    user = find_by_email(email)\n    return user is not None and password == \\\"demo-password\\\" and \\\"@\\\" in email\n"}], "summary": "done"}')
    monkeypatch.setattr(code_generator, "_call_llm", lambda prompt: code_generator._call_gemini(prompt))
    result = code_generator.generate_code_patches("analysis-1")
    assert result["patch_data"][0]["file"] == "app/auth/service.py"


def test_invalid_gemini_payload_is_rejected(monkeypatch):
    from backend.services import code_generator

    repo = (Path(__file__).resolve().parents[1] / "sample-project").resolve()
    monkeypatch.setattr(code_generator, "_load_plan_context", lambda _plan_id: ({"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}], "request": "Add phone auth"}}, {"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}, "plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}))
    monkeypatch.setattr(code_generator, "_call_llm", lambda _prompt: "not-json")
    with pytest.raises(ValueError, match="JSON"):
        code_generator.generate_code_patches("analysis-1")


def test_validate_repository_path_accepts_windows_absolute_path(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    windows_path = str(repo).replace("/", "\\")
    resolved = validate_repository_path(windows_path)
    assert resolved == repo.resolve()


def test_validate_repository_path_strips_quotes_from_absolute_windows_path(tmp_path):
    repo = tmp_path / "quoted-project"
    repo.mkdir()
    quoted = f'"{str(repo).replace("/", "\\")}"'
    resolved = validate_repository_path(quoted)
    assert resolved == repo.resolve()


def test_validate_repository_path_accepts_relative_path_from_root():
    resolved = validate_repository_path("sample-project")
    assert resolved == (ROOT / "sample-project").resolve()


def test_validate_repository_path_accepts_forward_slash_windows_path(tmp_path):
    repo = tmp_path / "forward-slash-project"
    repo.mkdir()
    forward = str(repo).replace("\\", "/")
    resolved = validate_repository_path(forward)
    assert resolved == repo.resolve()


def test_validate_repository_path_rejects_nonexistent_path():
    missing = ROOT / "definitely-missing-repo"
    with pytest.raises(FileNotFoundError, match="Repository path does not exist"):
        validate_repository_path(str(missing))


def test_validate_repository_path_rejects_file_instead_of_directory(tmp_path):
    file_path = tmp_path / "repo.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="Repository path must be a directory"):
        validate_repository_path(str(file_path))


def test_validate_repository_path_rejects_traversal_attempts():
    with pytest.raises(ValueError, match="Repository path escapes the CODEGUARDIAN root"):
        validate_repository_path("../outside-repo")


def test_validate_repository_path_does_not_join_absolute_windows_path_with_root(tmp_path):
    repo = tmp_path / "actual-project"
    repo.mkdir()
    windows_absolute = str(repo).replace("/", "\\")
    resolved = validate_repository_path(windows_absolute)
    assert resolved == repo.resolve()
    assert str(resolved).startswith(str(tmp_path.resolve()))
    assert not str(resolved).startswith(str(ROOT.resolve()))


def test_plan_and_implementation_require_analysis_approval():
    analysis = client.post("/api/analyze", json={"request": "Add phone-number authentication", "repository_path": "sample-project"}).json()
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
    analysis = client.post("/api/analyze", json={"request": "Add phone-number authentication", "repository_path": "sample-project"}).json()
    response = client.post("/api/implement", json={"analysis_id": analysis["id"], "approved": True, "files": ["secrets.env"]})
    assert response.status_code == 400


def test_report_includes_actual_verification_result():
    analysis = client.post("/api/analyze", json={"request": "Add phone-number authentication", "repository_path": "sample-project"}).json()
    verification = client.post("/api/verify", json={"repository_path": "sample-project", "analysis_id": analysis["id"]})
    report = client.get(f"/api/report/{analysis['id']}")
    assert verification.json()["status"] == "TESTS_PASSED"
    assert report.json()["status"] == "verified"
    assert report.json()["report"]["verification"]["exit_code"] == 0
    assert report.json()["report"]["verification"]["passed"] == 2


def test_verification_uses_analyzed_repository_as_working_directory(tmp_path):
    (tmp_path / "test_root.py").write_text(
        "from pathlib import Path\ndef test_cwd_is_repository():\n    assert Path.cwd() == Path(__file__).resolve().parent\n",
        encoding="utf-8",
    )

    response = client.post("/api/verify", json={"repository_path": str(tmp_path)})

    assert response.json()["status"] == "TESTS_PASSED"
    assert response.json()["working_directory"] == str(tmp_path.resolve())
    assert response.json()["tests_discovered"] == 1
    assert response.json()["passed"] == 1


def test_verification_rejects_a_different_repository_than_the_analysis(tmp_path):
    analysis = client.post("/api/analyze", json={"request": "Add phone-number authentication", "repository_path": "sample-project"}).json()

    response = client.post("/api/verify", json={"repository_path": str(tmp_path), "analysis_id": analysis["id"]})

    assert response.status_code == 400
    assert "must match the analyzed repository" in response.json()["detail"]


def test_no_tests_returns_explicit_discovery_state(tmp_path):
    response = client.post("/api/verify", json={"repository_path": str(tmp_path)})

    assert response.json()["status"] == "NO_TESTS_FOUND"
    assert response.json()["total"] is None
    assert "No supported test files" in response.json()["reason"]


def test_test_collection_error_is_not_reported_as_regression_failure(tmp_path):
    (tmp_path / "test_broken.py").write_text("def test_broken(:\n    pass\n", encoding="utf-8")

    response = client.post("/api/verify", json={"repository_path": str(tmp_path)})

    assert response.json()["status"] == "TEST_DISCOVERY_ERROR"
    assert response.json()["failed"] is None
    assert "could not collect" in response.json()["reason"]


def test_failing_repository_returns_real_failure_counts(tmp_path):
    (tmp_path / "test_failure.py").write_text("def test_failure():\n    assert 1 == 2\n", encoding="utf-8")

    response = client.post("/api/verify", json={"repository_path": str(tmp_path)})

    assert response.json()["status"] == "TESTS_FAILED"
    assert response.json()["failed"] == 1
    assert response.json()["passed"] == 0
    assert response.json()["total"] == 1


def test_javascript_tests_are_discovered_and_executed(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"node --test"}}', encoding="utf-8")
    (tmp_path / "math.test.js").write_text(
        "const test = require('node:test');\nconst assert = require('node:assert/strict');\ntest('addition', () => assert.equal(1 + 1, 2));\n",
        encoding="utf-8",
    )

    response = client.post("/api/verify", json={"repository_path": str(tmp_path)})

    assert response.json()["status"] == "TESTS_PASSED"
    assert response.json()["discovered_test_files"] == ["math.test.js"]
    assert response.json()["passed"] == 1
    assert response.json()["total"] == 1


def test_unittest_repository_uses_unittest_and_parses_real_counts(tmp_path):
    (tmp_path / "test_unittest.py").write_text(
        "import unittest\nclass RealTests(unittest.TestCase):\n    def test_success(self):\n        self.assertEqual(2 + 2, 4)\n",
        encoding="utf-8",
    )
    (tmp_path / "legacy_test.py").write_text(
        "import unittest\nclass LegacyTests(unittest.TestCase):\n    def test_another_success(self):\n        self.assertTrue(True)\n",
        encoding="utf-8",
    )

    response = client.post("/api/verify", json={"repository_path": str(tmp_path)})

    assert response.json()["status"] == "TESTS_PASSED"
    assert response.json()["framework"] == "unittest"
    assert response.json()["passed"] == 2
    assert response.json()["total"] == 2


def test_analysis_and_real_test_counts_are_retrievable_from_persistence(tmp_path):
    (tmp_path / "app.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (tmp_path / "test_login.py").write_text("def test_login():\n    assert True\n", encoding="utf-8")
    analysis = client.post("/api/analyze", json={"request": "Improve login handling", "repository_path": str(tmp_path)}).json()

    verification = client.post("/api/verify", json={"repository_path": str(tmp_path), "analysis_id": analysis["id"]})
    report = client.get(f"/api/report/{analysis['id']}")

    assert verification.json()["status"] == "TESTS_PASSED"
    assert report.json()["report"]["verification"]["passed"] == 1
    assert report.json()["report"]["verification"]["working_directory"] == str(tmp_path.resolve())


def test_git_status_is_read_only_and_returns_repository_evidence():
    sample_repo = (ROOT / "sample-project").resolve()
    response = client.get("/api/git/status", params={"repository_path": "sample-project"})
    assert response.status_code == 200
    assert response.json()["repository_path"] == str(sample_repo)
    assert isinstance(response.json()["status"], list)


def test_analysis_accepts_an_actual_repository_path_outside_workspace(tmp_path):
    repo = tmp_path / "real-project"
    repo.mkdir()
    (repo / "app.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("fastapi==0.115.6\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_hello():\n    assert hello() == 'world'\n", encoding="utf-8")

    response = client.post("/api/analyze", json={"request": "Add login flow", "repository_path": str(repo)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["repository_path"] == str(repo.resolve())
    assert payload["result"]["evidence"]["files"]
    assert payload["result"]["tests"]


def test_ollama_unavailable_returns_clear_error(monkeypatch):
    import urllib.error

    from backend.services import code_generator

    def raise_error(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(code_generator, "_call_ollama", raise_error)
    with pytest.raises(RuntimeError, match="AI code generator unavailable"):
        code_generator.generate_code_patches("analysis-1")


def test_invalid_model_json_is_rejected(monkeypatch):
    from backend.services import code_generator

    repo = (Path(__file__).resolve().parents[1] / "sample-project").resolve()
    monkeypatch.setattr(code_generator, "_load_plan_context", lambda _plan_id: ({"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}], "request": "Add phone auth"}}, {"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}, "plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}))
    monkeypatch.setattr(code_generator, "_call_ollama", lambda *_args, **_kwargs: "not-json")
    with pytest.raises(ValueError, match="JSON"):
        code_generator.generate_code_patches("analysis-1")


def test_generated_file_outside_allowlist_is_rejected(monkeypatch):
    from backend.services import code_generator

    repo = (Path(__file__).resolve().parents[1] / "sample-project").resolve()
    monkeypatch.setattr(code_generator, "_load_plan_context", lambda _plan_id: ({"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}], "request": "Add phone auth"}}, {"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}, "plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}))
    monkeypatch.setattr(code_generator, "_call_ollama", lambda *_args, **_kwargs: '{"files": [{"file": "app/secret.py", "content": "print(1)"}], "summary": "done"}')
    with pytest.raises(ValueError, match="allowlist"):
        code_generator.generate_code_patches("analysis-1")


def test_path_traversal_is_rejected(monkeypatch):
    from backend.services import code_generator

    repo = (Path(__file__).resolve().parents[1] / "sample-project").resolve()
    monkeypatch.setattr(code_generator, "_load_plan_context", lambda _plan_id: ({"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}], "request": "Add phone auth"}}, {"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}, "plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}))
    monkeypatch.setattr(code_generator, "_call_ollama", lambda *_args, **_kwargs: '{"files": [{"file": "../outside.py", "content": "print(1)"}], "summary": "done"}')
    with pytest.raises(ValueError, match="inside"):
        code_generator.generate_code_patches("analysis-1")


def test_valid_generated_file_converts_to_diff(monkeypatch):
    from backend.services import code_generator

    repo = (Path(__file__).resolve().parents[1] / "sample-project").resolve()
    original = (repo / "app/auth/service.py").read_text(encoding="utf-8")
    monkeypatch.setattr(code_generator, "_load_plan_context", lambda _plan_id: ({"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}], "request": "Add phone auth"}}, {"repository_path": str(repo), "result": {"plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}, "plan": [{"task": "Update auth", "files": ["app/auth/service.py"]}]}))
    monkeypatch.setattr(code_generator, "_call_ollama", lambda *_args, **_kwargs: '{"files": [{"file": "app/auth/service.py", "content": "from app.users.service import find_by_email\n\n\ndef authenticate(email: str, password: str) -> bool:\n    user = find_by_email(email)\n    return user is not None and password == \\\"demo-password\\\" and \\\"@\\\" in email\n"}], "summary": "done"}')
    result = code_generator.generate_code_patches("analysis-1")
    assert result["patch_data"][0]["file"] == "app/auth/service.py"
    assert "--- app/auth/service.py" in result["patch_data"][0]["unified_diff"]
    assert "+++ app/auth/service.py" in result["patch_data"][0]["unified_diff"]
    assert "@@" in result["patch_data"][0]["unified_diff"]
    assert original != result["patch_data"][0]["unified_diff"]


def test_generate_patch_reaches_implementation_service(monkeypatch):
    analysis = client.post("/api/analyze", json={"request": "Add phone-number authentication", "repository_path": "sample-project"}).json()
    fake_patch = [{"file": "app/auth/service.py", "unified_diff": "--- app/auth/service.py\n+++ app/auth/service.py\n@@\n-from app.users.service import find_by_email\n+from app.users.service import find_by_email\n"}]

    from backend.services import code_generator
    monkeypatch.setattr(code_generator, "generate_code_patches", lambda _plan_id: {"patch_data": fake_patch, "summary": "done"})
    response = client.post("/api/implement", json={"analysis_id": analysis["id"], "approved": True, "generate_patch": True})

    assert response.status_code == 200
    assert response.json()["status"] == "implementation_complete"
    assert response.json()["patch_data"][0]["file"] == "app/auth/service.py"