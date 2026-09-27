from pathlib import Path

from analyzer.repository import analyze_change, scan_repository


ROOT = Path(__file__).parents[1] / "sample-project"


def test_scanner_finds_files_symbols_dependencies_and_tests():
    evidence = scan_repository(ROOT)
    assert "app/auth/routes.py" in evidence.files
    assert any(symbol.name == "login" for symbol in evidence.symbols)
    assert "fastapi" in evidence.dependencies
    assert "tests/test_auth.py" in evidence.tests
    assert "POST /auth/login (app/auth/routes.py)" in evidence.routes


def test_phone_auth_analysis_returns_cross_cutting_impact():
    result = analyze_change(ROOT, "Add phone-number authentication")
    assert result.affected_files
    assert result.affected_components
    assert result.tests
    assert result.security_risks
    assert result.plan
    assert all((ROOT / file_name).is_file() for file_name in result.affected_files)
    assert "app/users/service.py" in result.affected_files


def test_unrelated_request_does_not_receive_arbitrary_impact_files_or_routes(tmp_path):
    repo = tmp_path / "unrelated-project"
    repo.mkdir()
    (repo / "auth.py").write_text("@router.post('/login')\ndef login():\n    return None\n", encoding="utf-8")
    (repo / "README.md").write_text("Authentication endpoint documentation.", encoding="utf-8")

    result = analyze_change(repo, "Add weather forecasting")

    assert result.affected_files == []
    assert result.affected_apis == []
    assert result.affected_components == []
    assert all(not item["files"] for item in result.plan)


def test_dependency_manifests_and_routes_are_read_from_real_files(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==1.2\n# ignored-comment\nuvicorn>=2\n", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text(
        '{"packages":{"":{"name":"example"},"node_modules/@scope/client":{"version":"1.0.0"}}}',
        encoding="utf-8",
    )
    (tmp_path / "routes.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter(prefix='/v1')\n@router.post('/events')\ndef create_event():\n    return None\n\ndef load_value(data):\n    return data.get('/not-an-api-route')\n",
        encoding="utf-8",
    )

    evidence = scan_repository(tmp_path)

    assert set(evidence.dependencies) == {"fastapi", "uvicorn", "@scope/client"}
    assert evidence.routes == ["POST /v1/events (routes.py)"]


def test_relative_imports_add_only_connected_repository_files(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "target.py").write_text("phone_enabled = True\n", encoding="utf-8")
    (package / "connector.py").write_text("from .target import phone_enabled\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("def helper():\n    return None\n", encoding="utf-8")

    result = analyze_change(tmp_path, "Add phone authentication")

    assert "pkg/target.py" in result.affected_files
    assert "pkg/connector.py" in result.affected_files
    assert "unrelated.py" not in result.affected_files
    assert result.confidence_label == "Heuristic estimate"


def test_documentation_is_not_affected_by_code_keyword_matches_alone(tmp_path):
    (tmp_path / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Authentication flow documentation.", encoding="utf-8")

    result = analyze_change(tmp_path, "Add phone authentication")

    assert "auth.py" in result.affected_files
    assert "README.md" not in result.affected_files


def test_non_test_python_module_is_not_listed_as_test_file(tmp_path):
    (tmp_path / "service.py").write_text("def test_helper():\n    return True\n", encoding="utf-8")

    evidence = scan_repository(tmp_path)

    assert evidence.tests == []
