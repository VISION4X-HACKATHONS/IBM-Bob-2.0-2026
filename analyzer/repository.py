"""Evidence-based repository scanning and change impact analysis."""

from __future__ import annotations

import ast
import json
import os
import re
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path


SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".sql", ".md", ".txt", ".toml", ".yaml", ".yml"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "coverage", ".pytest_cache", ".codeguardian"}
JS_TEST_PATTERN = re.compile(r"^.*\.(?:test|spec)\.(?:js|jsx|ts|tsx)$", re.IGNORECASE)
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
    repository_path: str
    request: str
    impact_message: str
    analysis_duration: float
    affected_files: list[str]
    affected_components: list[str]
    affected_apis: list[str]
    database_components: list[str]
    dependencies: list[str]
    tests: list[str]
    security_risks: list[str]
    confidence: int
    confidence_label: str
    evidence: RepositoryEvidence
    plan: list[dict[str, object]]


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _looks_like_windows_absolute(path_text: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", path_text)) or path_text.startswith("\\\\")


def _normalize_repository_string(path: str | Path) -> str:
    if path is None:
        raise ValueError("Repository path is required.")
    raw_text = str(path).strip()
    if raw_text == "":
        raise ValueError("Repository path is required.")

    text = raw_text.strip('"\'')
    text = text.strip()
    if text == "":
        raise ValueError("Repository path is required.")

    text = text.replace("/", "\\")
    while "\\\\" in text:
        text = text.replace("\\\\", "\\")
    if text.endswith("\\") and len(text) > 3:
        text = text.rstrip("\\")
    return text


def normalize_repository_path(path: str | Path) -> Path:
    raw_text = _normalize_repository_string(path)
    if _looks_like_windows_absolute(raw_text) or os.path.isabs(raw_text):
        candidate = Path(raw_text).expanduser()
    else:
        base_root = Path(__file__).resolve().parents[1]
        candidate = (base_root / raw_text).expanduser()
        try:
            candidate.resolve(strict=False).relative_to(base_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Repository path escapes the CODEGUARDIAN root: {raw_text}") from exc
    return candidate.resolve(strict=False)


def validate_repository_path(path: str | Path) -> Path:
    candidate = normalize_repository_path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"Repository path does not exist: {candidate}")
    if not candidate.is_dir():
        raise NotADirectoryError(f"Repository path must be a directory: {candidate}")
    if not os.access(candidate, os.R_OK):
        raise PermissionError(f"Repository path is not readable: {candidate}")
    return candidate.resolve()


def scan_repository(root: str | Path) -> RepositoryEvidence:
    root_path = validate_repository_path(root)
    evidence = RepositoryEvidence()

    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root_path).parts[:-1]):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS and path.name not in {"requirements.txt", "pyproject.toml", "Pipfile", "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}:
            continue

        relative = _relative(root_path, path)
        evidence.files.append(relative)
        text = path.read_text(encoding="utf-8", errors="ignore")

        if path.name.startswith(".env") or "config" in path.name.lower():
            evidence.configuration.append(relative)
        if (path.suffix.lower() == ".py" and (path.name.startswith("test_") or path.name.endswith("_test.py"))) or JS_TEST_PATTERN.fullmatch(path.name):
            evidence.tests.append(relative)

        if path.suffix == ".py":
            _scan_python(text, relative, evidence)
        elif path.name.endswith((".js", ".jsx", ".ts", ".tsx")):
            _scan_javascript_routes(text, relative, evidence)
        elif path.name == "package.json":
            _scan_package_json(text, evidence)
        elif path.name == "requirements.txt":
            evidence.dependencies.extend(_requirement_dependencies(text))
        elif path.name in {"pyproject.toml", "Pipfile"}:
            evidence.dependencies.extend(_toml_dependencies(path.name, text))
        elif path.name == "package-lock.json":
            evidence.dependencies.extend(_package_lock_dependencies(text))
        elif path.name == "yarn.lock":
            evidence.dependencies.extend(_yarn_lock_dependencies(text))
        elif path.name == "pnpm-lock.yaml":
            evidence.dependencies.extend(_pnpm_lock_dependencies(text))

        if path.suffix == ".sql" or "model" in path.name.lower() or "database" in path.name.lower():
            evidence.database_components.append(relative)

    evidence.dependencies = sorted(set(d for d in evidence.dependencies if d and not d.startswith("#")))
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
    router_prefixes: dict[str, str] = {}
    mounted_prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id in {"APIRouter", "FastAPI"}:
                prefix = next((_extract_literal(keyword.value) for keyword in call.keywords if keyword.arg == "prefix"), "")
                for target in node.targets:
                    if isinstance(target, ast.Name) and prefix:
                        router_prefixes[target.id] = prefix
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "include_router" and node.args and isinstance(node.args[0], ast.Name):
            prefix = next((_extract_literal(keyword.value) for keyword in node.keywords if keyword.arg == "prefix"), "")
            if prefix:
                mounted_prefixes[node.args[0].id] = prefix

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            evidence.symbols.append(CodeSymbol(node.name, "function", relative, node.lineno))
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr.lower()
                path = _extract_literal(decorator.args[0]) if decorator.args else ""
                if method not in {"get", "post", "put", "patch", "delete"} or not path:
                    continue
                owner = decorator.func.value.id if isinstance(decorator.func.value, ast.Name) else ""
                prefix = mounted_prefixes.get(owner, "") + router_prefixes.get(owner, "")
                full_path = "/" + "/".join(part.strip("/") for part in (prefix, path) if part.strip("/"))
                evidence.routes.append(f"{method.upper()} {full_path} ({relative})")
        elif isinstance(node, ast.ClassDef):
            evidence.symbols.append(CodeSymbol(node.name, "class", relative, node.lineno))
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                source_module = Path(relative).with_suffix("").as_posix().replace("/", ".")
                package = source_module.rpartition(".")[0]
                package_parts = package.split(".") if package else []
                base_parts = package_parts[: max(0, len(package_parts) - node.level + 1)]
                module = ".".join(part for part in (*base_parts, module) if part)
            if module:
                imports.append(module)
            imports.extend(f"{module}.{alias.name}" for alias in node.names if alias.name != "*" and module)
    if imports:
        evidence.imports[relative] = sorted(set(imports))


def _scan_javascript_routes(text: str, relative: str, evidence: RepositoryEvidence) -> None:
    pattern = re.compile(r"(?:router|app|server)\.(get|post|put|patch|delete)\s*\(\s*(['\"])([^'\"]+)\2", re.IGNORECASE)
    for method, _, path in pattern.findall(text):
        evidence.routes.append(f"{method.upper()} {path} ({relative})")


def _scan_package_json(text: str, evidence: RepositoryEvidence) -> None:
    try:
        package = json.loads(text)
    except json.JSONDecodeError:
        return
    for section in ("dependencies", "devDependencies"):
        evidence.dependencies.extend(package.get(section, {}).keys())


def _requirement_dependencies(text: str) -> list[str]:
    packages = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", stripped)
        if match:
            packages.append(match.group(1))
    return packages


def _toml_dependencies(name: str, text: str) -> list[str]:
    try:
        manifest = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    packages: list[str] = []
    if name == "Pipfile":
        sections = ("packages", "dev-packages")
        for section in sections:
            packages.extend(manifest.get(section, {}).keys())
    else:
        project = manifest.get("project", {})
        for requirement in project.get("dependencies", []):
            match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
            if match:
                packages.append(match.group(1))
        for requirements in project.get("optional-dependencies", {}).values():
            for requirement in requirements:
                match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
                if match:
                    packages.append(match.group(1))
        packages.extend(name for name in manifest.get("tool", {}).get("poetry", {}).get("dependencies", {}) if name != "python")
        packages.extend(name for name in manifest.get("tool", {}).get("poetry", {}).get("group", {}).values() for name in name.get("dependencies", {}))
    return packages


def _package_lock_dependencies(text: str) -> list[str]:
    try:
        lock = json.loads(text)
    except json.JSONDecodeError:
        return []
    names = []
    for package_path in lock.get("packages", {}):
        if "node_modules/" in package_path:
            names.append(package_path.rsplit("node_modules/", 1)[-1])
    if not names:
        names.extend(lock.get("dependencies", {}).keys())
    return names


def _yarn_lock_dependencies(text: str) -> list[str]:
    packages = []
    for line in text.splitlines():
        stripped = line.strip().rstrip(":")
        if not stripped or line.startswith((" ", "\t", "#")):
            continue
        selector = stripped.split(",", 1)[0].strip('"')
        match = re.match(r"((?:@[^/]+/)?[^@]+)@", selector)
        if match:
            packages.append(match.group(1))
    return packages


def _pnpm_lock_dependencies(text: str) -> list[str]:
    packages = []
    in_packages = False
    for line in text.splitlines():
        if line == "packages:":
            in_packages = True
            continue
        if in_packages and line and not line[0].isspace() and not line.startswith("#"):
            break
        if not in_packages or not line.startswith("  "):
            continue
        key = line.strip().strip("'\"").lstrip("/").rstrip(":")
        match = re.match(r"((?:@[^/]+/)?[^@/]+)@", key)
        if match:
            packages.append(match.group(1))
    return packages


def _extract_literal(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else "" for part in node.values)
    return ""


def _request_terms(request: str) -> set[str]:
    words = set(re.findall(r"[a-z]+", request.lower()))
    if not words:
        return set()
    matched = set().union(*(REQUEST_TERMS[key] for key in REQUEST_TERMS if words & REQUEST_TERMS[key]))
    return matched or words


def _find_file_matches(root: Path, evidence: RepositoryEvidence, matched_terms: set[str], request: str) -> list[str]:
    candidates: list[str] = []
    documentation_requested = bool(re.search(r"\b(?:docs?|documentation|readme)\b", request, re.IGNORECASE))
    for file_name in evidence.files:
        path = root / file_name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        file_key = file_name.lower()
        path_match = any(term in file_key for term in matched_terms)
        if path.suffix.lower() == ".md" and not (documentation_requested or path_match):
            continue
        if path_match or any(term in text for term in matched_terms):
            candidates.append(file_name)
    return sorted(set(candidates))


def _expand_import_relationships(root: Path, evidence: RepositoryEvidence, seeds: list[str]) -> list[str]:
    module_files: dict[str, str] = {}
    for relative in evidence.files:
        path = Path(relative)
        if path.suffix != ".py":
            continue
        module = path.with_suffix("").as_posix().replace("/", ".")
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        module_files[module] = relative

    relationships: dict[str, set[str]] = {}
    for source, imports in evidence.imports.items():
        for imported in imports:
            targets = [module_files[imported]] if imported in module_files else []
            for target in targets:
                relationships.setdefault(source, set()).add(target)
                relationships.setdefault(target, set()).add(source)

    connected = set(seeds)
    pending = list(seeds)
    while pending:
        current = pending.pop()
        for related in relationships.get(current, set()):
            if related not in connected and (root / related).is_file():
                connected.add(related)
                pending.append(related)
    return sorted(connected)


def _find_security_findings(root: Path, evidence: RepositoryEvidence) -> list[str]:
    findings: list[str] = []
    patterns = [
        (r"password\s*==\s*|password\s*!=\s*|token\s*==\s*|secret\s*==\s*", "Plain-text credential comparison is used in the repository."),
        (r"eval\s*\(|exec\s*\(|subprocess\.run\s*\([^\n]*shell\s*=\s*True", "Dynamic code execution or shell execution is present."),
        (r"logging\.[a-z]+\(.*(password|token|secret|key)|print\(.*(password|token|secret|key)", "Sensitive values may be logged or printed."),
    ]

    for file_name in evidence.files:
        path = root / file_name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not text:
            continue
        for pattern, message in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{file_name}:{line}: {message}")
                break
    return sorted(set(findings))


def analyze_change(root: str | Path, request: str) -> ImpactResult:
    started = time.perf_counter()
    root_path = validate_repository_path(root)
    evidence = scan_repository(root_path)
    matched_terms = _request_terms(request)
    candidates = _expand_import_relationships(root_path, evidence, _find_file_matches(root_path, evidence, matched_terms, request))

    components: list[str] = []
    for symbol in evidence.symbols:
        if symbol.file not in candidates:
            continue
        name = symbol.name.lower()
        if any(term in name for term in matched_terms) or any(keyword in name for keyword in {"auth", "user", "route", "service", "db", "model"}):
            components.append(f"{symbol.kind} {symbol.name} ({symbol.file}:{symbol.line})")
    apis = [route for route in evidence.routes if route.rsplit(" (", 1)[-1].rstrip(")") in candidates]

    security_risks = _find_security_findings(root_path, evidence)
    affected_files = sorted(set(candidates))
    plan = _build_plan(affected_files, evidence, request)
    confidence = min(98, 35 + len(affected_files) * 6 + len(components) * 3 + len(apis) * 4)

    return ImpactResult(
        repository_path=str(root_path),
        request=request,
        impact_message="No direct impact relationship discovered." if not affected_files else "Impact files match request evidence or are connected through repository-local imports.",
        analysis_duration=round(time.perf_counter() - started, 3),
        affected_files=affected_files,
        affected_components=sorted(set(components)),
        affected_apis=apis,
        database_components=evidence.database_components,
        dependencies=evidence.dependencies,
        tests=evidence.tests,
        security_risks=security_risks,
        confidence=confidence,
        confidence_label="Heuristic estimate",
        evidence=evidence,
        plan=plan,
    )


def _build_plan(files: list[str], evidence: RepositoryEvidence, request: str) -> list[dict[str, object]]:
    implementation_files = [f for f in files if f not in evidence.tests and not any(part in f.lower() for part in {"requirements", "package.json", "config"})]
    real_database = [f for f in files if f in evidence.database_components]
    real_tests = [f for f in files if f in evidence.tests]
    config_files = [f for f in files if f in evidence.configuration]
    groups = [
        ("Trace the request-handling flow", implementation_files, f"Review the actual implementation files that handle the change request: {request}", "high"),
        ("Check persistence and repository configuration", real_database + config_files, "Validate any model, schema, or configuration paths this change touches.", "high"),
        ("Validate dependencies and runtime configuration", config_files, "Confirm that the project’s declared dependencies and runtime settings still match the change.", "medium"),
        ("Add or update regression coverage", real_tests, "Protect the behavior with the repository’s existing test files.", "high"),
        ("Execute the repository verification command", [], "Run the project’s real test command and capture the actual result.", "medium"),
    ]
    return [{"task": task, "files": sorted(set(selected)), "reason": reason, "risk": risk} for task, selected, reason, risk in groups]


def to_dict(result: ImpactResult) -> dict[str, object]:
    output = asdict(result)
    output["evidence"]["symbols"] = [asdict(symbol) for symbol in result.evidence.symbols]
    return output
