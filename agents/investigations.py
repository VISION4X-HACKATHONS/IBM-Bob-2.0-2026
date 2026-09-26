"""Normal Python investigation services prepared for future agent integration."""

from analyzer.repository import ImpactResult


def code_impact(result: ImpactResult) -> dict[str, object]:
    return {"name": "Code Impact", "files": result.affected_files, "components": result.affected_components}


def test_impact(result: ImpactResult) -> dict[str, object]:
    return {"name": "Test Impact", "tests": result.tests, "risk": "Regression coverage required"}


def dependency_impact(result: ImpactResult) -> dict[str, object]:
    return {"name": "Dependency Impact", "dependencies": result.dependencies}


def security_risk(result: ImpactResult) -> dict[str, object]:
    return {"name": "Security/Risk", "findings": result.security_risks}
