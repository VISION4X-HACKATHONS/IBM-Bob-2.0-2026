"""Evidence-based repository scanning and change impact analysis."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".sql", ".md", ".txt", ".toml"}
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}
REQUEST_TERMS = {
    "phone": {"phone", "mobile", "sms", "otp", "telephone"},
    "authentication": {"auth", "authentication", "login", "register", "password", "session", "token"},
}


@dataclass
class CodeSymbol:
    name: str
    kind: str
    file: str
    line: int


@dataclass
class RepositoryEvidence:
    files: list[str] = field(default_factory=list)
    symbols: list[CodeSymbol] = field(default_factory=list)
    imports: dict[str, list[str]] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    database_components: list[str] = field(default_factory=list)
    configuration: list[str] = field(default_factory=list)


@dataclass
class ImpactResult:
    request: str
    affected_files: list[str]
    affected_components: list[str]
    affected_apis: list[str]
    database_components: list[str]
    dependencies: list[str]
    tests: list[str]
    security_risks: list[str]
    confidence: int
    evidence: RepositoryEvidence
    plan: list[dict[str, object]]


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def scan_repository(root: str | Path) -> RepositoryEvidence:
    root_path = Path(root).resolve()
    evidence = RepositoryEvidence()
    for path in sorted(root_path.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        relative = _relative(root_path, path)
        evidence.files.append(relative)
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.name.startswith(".env") or "config" in path.name.lower():
            evidence.configuration.append(relative)
        if path.name.startswith("test_") or path.name.endswith("_test.py") or "/tests/" in f"/{relative}/":
            evidence.tests.append(relative)
        if path.suffix == ".py":
            _scan_python(text, relative, evidence)
        elif path.name == "package.json":
            _scan_package_json(text, evidence)
        elif path.name in {"requirements.txt", "pyproject.toml"}:
            evidence.dependencies.extend(_dependency_lines(text))
        if path.suffix == ".sql" or "model" in path.name.lower() or "database" in path.name.lower():
            evidence.database_components.append(relative)
    evidence.dependencies = sorted(set(evidence.dependencies))
    evidence.tests = sorted(set(evidence.tests))
    evidence.database_components = sorted(set(evidence.database_components))
    evidence.configuration = sorted(set(evidence.configuration))
    return evidence


def _scan_python(text: str, relative: str, evidence: RepositoryEvidence) -> None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            evidence.symbols.append(CodeSymbol(node.name, "function", relative, node.lineno))
            if node.name.startswith(("test_", "test")):
                evidence.tests.append(relative)
        elif isinstance(node, ast.ClassDef):
            evidence.symbols.append(CodeSymbol(node.name, "class", relative, node.lineno))
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"get", "post", "put", "patch", "delete"}:
                evidence.routes.append(f"{node.func.attr.upper()} route in {relative}")
    if imports:
        evidence.imports[relative] = sorted(set(imports))


def _scan_package_json(text: str, evidence: RepositoryEvidence) -> None:
    try:
        package = json.loads(text)
    except json.JSONDecodeError:
        return
    for section in ("dependencies", "devDependencies"):
        evidence.dependencies.extend(package.get(section, {}).keys())


def _dependency_lines(text: str) -> list[str]:
    return [line.split("==")[0].split(">=")[0].strip() for line in text.splitlines() if line.strip() and not line.startswith(("#", "["))]


def analyze_change(root: str | Path, request: str) -> ImpactResult:
    evidence = scan_repository(root)
    words = set(re.findall(r"[a-z]+", request.lower()))
    matched_terms = set().union(*(REQUEST_TERMS[key] for key in REQUEST_TERMS if words & REQUEST_TERMS[key]))
    candidates: list[str] = []
    components: list[str] = []
    for file in evidence.files:
        content_match = False
        path = Path(root) / file
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if any(term in text or term in file.lower() for term in matched_terms):
            content_match = True
        if content_match:
            candidates.append(file)
    for symbol in evidence.symbols:
        if symbol.file in candidates and any(term in symbol.name.lower() for term in matched_terms | {"user", "auth"}):
            components.append(f"{symbol.kind} {symbol.name} ({symbol.file}:{symbol.line})")
    apis = [route for route in evidence.routes if any(term in route.lower() for term in matched_terms)] or evidence.routes[:4]
    security_risks = [
        "Phone verification must use expiring, rate-limited OTPs.",
        "Authentication changes must avoid logging phone numbers or verification codes.",
        "Session and account-recovery paths need regression coverage.",
    ] if "phone" in matched_terms or "authentication" in matched_terms else ["Review authorization boundaries before implementation."]
    affected_files = sorted(set(candidates + evidence.tests[:2] + evidence.database_components[:2]))
    plan = _build_plan(affected_files, evidence, request)
    confidence = min(98, 45 + len(affected_files) * 7 + len(components) * 3)
    return ImpactResult(request, affected_files, sorted(set(components)), apis, evidence.database_components, evidence.dependencies, evidence.tests, security_risks, confidence, evidence, plan)


def _build_plan(files: list[str], evidence: RepositoryEvidence, request: str) -> list[dict[str, object]]:
    groups = [
        ("Trace the authentication contract", [f for f in files if "auth" in f or "route" in f], "Find the current sign-in boundary before changing credentials.", "high"),
        ("Extend the user and database model", [f for f in files if f in evidence.database_components or "user" in f], "Phone identity and verification state must persist consistently.", "high"),
        ("Update client validation and authentication UI", [f for f in files if f.endswith((".tsx", ".jsx", ".js"))], "The request crosses the user-facing login flow.", "medium"),
        ("Add focused security and regression tests", evidence.tests, "Authentication behavior must be verified with both success and failure cases.", "high"),
        ("Run the repository test command", [], f"Verify the complete change request: {request}.", "medium"),
    ]
    return [{"task": task, "files": sorted(set(selected)), "reason": reason, "risk": risk} for task, selected, reason, risk in groups]


def to_dict(result: ImpactResult) -> dict[str, object]:
    output = asdict(result)
    output["evidence"]["symbols"] = [asdict(symbol) for symbol in result.evidence.symbols]
    return output
