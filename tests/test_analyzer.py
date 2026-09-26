from pathlib import Path

from analyzer.repository import analyze_change, scan_repository


ROOT = Path(__file__).parents[1] / "sample-project"


def test_scanner_finds_files_symbols_dependencies_and_tests():
    evidence = scan_repository(ROOT)
    assert "app/auth/routes.py" in evidence.files
    assert any(symbol.name == "login" for symbol in evidence.symbols)
    assert "fastapi" in evidence.dependencies
    assert "tests/test_auth.py" in evidence.tests


def test_phone_auth_analysis_returns_cross_cutting_impact():
    result = analyze_change(ROOT, "Add phone-number authentication")
    assert result.affected_files
    assert result.affected_components
    assert result.tests
    assert result.security_risks
    assert result.plan
