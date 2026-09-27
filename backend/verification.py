from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "coverage", ".pytest_cache", ".codeguardian"}
PYTHON_TEST = re.compile(r"(?:^test_.*\.py$|^.*_test\.py$)", re.IGNORECASE)
JS_TEST = re.compile(r"^.*\.(?:test|spec)\.(?:js|jsx|ts|tsx)$", re.IGNORECASE)


def discover_test_files(repository: Path) -> tuple[list[str], list[str]]:
    python_files: list[str] = []
    javascript_files: list[str] = []
    for path in sorted(repository.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(repository).parts[:-1]):
            continue
        relative = path.relative_to(repository).as_posix()
        if PYTHON_TEST.fullmatch(path.name):
            python_files.append(relative)
        if JS_TEST.fullmatch(path.name):
            javascript_files.append(relative)
    return python_files, javascript_files


def _python_executable(repository: Path) -> str:
    candidates = [
        repository / ".venv" / "Scripts" / "python.exe",
        repository / ".venv" / "bin" / "python",
        repository / "venv" / "Scripts" / "python.exe",
        repository / "venv" / "bin" / "python",
    ]
    return str(next((path for path in candidates if path.is_file()), Path(sys.executable)))


def _python_framework(repository: Path, test_files: list[str]) -> str:
    config_files = ("pytest.ini", "tox.ini", "setup.cfg")
    for name in config_files:
        path = repository / name
        if path.is_file() and re.search(r"pytest", path.read_text(encoding="utf-8", errors="ignore"), re.IGNORECASE):
            return "pytest"
    pyproject = repository / "pyproject.toml"
    if pyproject.is_file() and re.search(r"\[tool\.pytest(?:\.|\])", pyproject.read_text(encoding="utf-8", errors="ignore")):
        return "pytest"
    if any((repository / Path(test_file).parent / "conftest.py").is_file() for test_file in test_files):
        return "pytest"

    unittest_found = False
    pytest_found = False
    for test_file in test_files:
        source = (repository / test_file).read_text(encoding="utf-8", errors="ignore")
        if re.search(r"(?:import pytest|from pytest\b|pytest\.)", source):
            pytest_found = True
        if re.search(r"(?:import unittest|from unittest\b|TestCase)", source):
            unittest_found = True
        if re.search(r"^\s{0,3}def\s+test\w*\s*\(", source, re.MULTILINE):
            pytest_found = True
    if pytest_found:
        return "pytest"
    return "unittest" if unittest_found else "pytest"


def _count_summary(output: str) -> dict[str, int | float | None]:
    counts: dict[str, int | float | None] = {"passed": None, "failed": None, "skipped": None, "errors": None, "total": None, "duration": None}
    patterns = {
        "passed": r"\b(\d+) passed\b|\bpass(?:ed)?\s+(\d+)\b",
        "failed": r"\b(\d+) failed\b|\bfail(?:ed)?\s+(\d+)\b",
        "skipped": r"\b(\d+) skipped\b|\bskip(?:ped)?\s+(\d+)\b",
        "errors": r"\b(\d+) errors?\b|\berrors?\s+(\d+)\b",
    }
    found = False
    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            counts[key] = int(next(group for group in match.groups() if group is not None))
            found = True
    if found:
        for key in patterns:
            if counts[key] is None:
                counts[key] = 0
        counts["total"] = sum(int(counts[key] or 0) for key in patterns)
    unittest_runs = list(re.finditer(r"Ran (\d+) tests? in ([0-9]+(?:\.[0-9]+)?)s", output))
    if unittest_runs:
        total = sum(int(match.group(1)) for match in unittest_runs)
        counts["failed"] = sum(map(int, re.findall(r"failures=(\d+)", output)))
        counts["errors"] = sum(map(int, re.findall(r"errors=(\d+)", output)))
        counts["skipped"] = sum(map(int, re.findall(r"skipped=(\d+)", output)))
        counts["passed"] = max(0, total - int(counts["failed"]) - int(counts["errors"]) - int(counts["skipped"]))
        counts["total"] = total
        counts["duration"] = sum(float(match.group(2)) for match in unittest_runs)
    duration_match = re.search(r"\bin ([0-9]+(?:\.[0-9]+)?)s\b|duration_ms\s+([0-9]+(?:\.[0-9]+)?)", output)
    if duration_match:
        duration = next(group for group in duration_match.groups() if group is not None)
        counts["duration"] = float(duration) / 1000 if duration_match.group(2) else float(duration)
    return counts


def _npm_command(repository: Path) -> tuple[list[str] | None, str | None]:
    manifest = repository / "package.json"
    if not manifest.is_file():
        return None, "JavaScript test files were found, but package.json is missing."
    try:
        package = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Could not read package.json: {exc}"
    test_script = package.get("scripts", {}).get("test")
    if not test_script:
        return None, "JavaScript test files were found, but package.json has no test script."
    dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    if "vitest" in dependencies or "vitest" in test_script:
        extra = ["--run"]
    elif "jest" in dependencies or "jest" in test_script:
        extra = ["--runInBand"]
    else:
        extra = []
    manager = "pnpm" if (repository / "pnpm-lock.yaml").is_file() else "yarn" if (repository / "yarn.lock").is_file() else "npm"
    executable = shutil.which(manager) or (f"{manager}.cmd" if os.name == "nt" else manager)
    return [executable, "test", *( ["--", *extra] if extra else [])], None


def verify_repository(repository: Path) -> dict[str, Any]:
    python_files, javascript_files = discover_test_files(repository)
    discovered_files = python_files + javascript_files
    python_framework = _python_framework(repository, python_files) if python_files else None
    framework_parts = ([python_framework] if python_framework else []) + (["npm test"] if javascript_files else [])
    common: dict[str, Any] = {
        "status": "NO_TESTS_FOUND" if not discovered_files else "TEST_EXECUTION_ERROR",
        "reason": "No supported test files were discovered in the analyzed repository." if not discovered_files else None,
        "passed": None,
        "failed": None,
        "skipped": None,
        "errors": None,
        "total": None,
        "duration": None,
        "tests_discovered": len(discovered_files),
        "discovered_test_files": discovered_files,
        "framework": " + ".join(framework_parts) if framework_parts else None,
        "command": [],
        "working_directory": str(repository),
        "stdout": "",
        "stderr": "",
        "exit_code": None,
    }
    if not discovered_files:
        return common

    commands: list[list[str]] = []
    if python_files:
        executable = _python_executable(repository)
        if python_framework == "pytest":
            commands.append([executable, "-m", "pytest", "--collect-only", "-q"])
        else:
            patterns = []
            if any(Path(file_name).name.lower().startswith("test") for file_name in python_files):
                patterns.append("test*.py")
            if any(Path(file_name).name.lower().endswith("_test.py") and not Path(file_name).name.lower().startswith("test") for file_name in python_files):
                patterns.append("*_test.py")
            for pattern in patterns:
                commands.append([executable, "-m", "unittest", "discover", "-v", "-p", pattern])
    if javascript_files:
        command, reason = _npm_command(repository)
        if command is None:
            common["reason"] = reason
            common["status"] = "TEST_EXECUTION_ERROR"
            return common
        commands.append(command)

    started = time.perf_counter()
    outputs: list[str] = []
    errors: list[str] = []
    executed_commands: list[list[str]] = []
    executions: list[subprocess.CompletedProcess[str]] = []
    for command in commands:
        executed_commands.append(command)
        try:
            completed = subprocess.run(command, cwd=repository, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as exc:
            common.update({"status": "TEST_EXECUTION_ERROR", "reason": "Test command timed out after 120 seconds.", "exit_code": None})
            common["stdout"] = exc.stdout or ""
            common["stderr"] = exc.stderr or ""
            common["command"] = executed_commands
            common["duration"] = round(time.perf_counter() - started, 3)
            return common
        except OSError as exc:
            common.update({"status": "TEST_EXECUTION_ERROR", "reason": str(exc), "stderr": str(exc), "command": executed_commands})
            common["duration"] = round(time.perf_counter() - started, 3)
            return common

        output = completed.stdout + completed.stderr
        if command[1:4] == ["-m", "pytest", "--collect-only"]:
            collected = re.search(r"\b(\d+) tests? collected\b", output)
            if completed.returncode == 5 or (collected and int(collected.group(1)) == 0):
                common.update({"status": "NO_TESTS_FOUND", "reason": "Pytest found no runnable tests in the analyzed repository.", "exit_code": completed.returncode})
                common["stdout"], common["stderr"] = completed.stdout, completed.stderr
                common["command"] = executed_commands
                common["duration"] = round(time.perf_counter() - started, 3)
                return common
            if completed.returncode != 0:
                common.update({"status": "TEST_DISCOVERY_ERROR", "reason": "Pytest could not collect tests from the analyzed repository.", "exit_code": completed.returncode})
                common["stdout"], common["stderr"] = completed.stdout, completed.stderr
                common["command"] = executed_commands
                common["duration"] = round(time.perf_counter() - started, 3)
                return common
            execution_command = [command[0], "-m", "pytest", "-q"]
            executed_commands[-1] = execution_command
            try:
                completed = subprocess.run(execution_command, cwd=repository, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired as exc:
                common.update({"status": "TEST_EXECUTION_ERROR", "reason": "Test command timed out after 120 seconds."})
                common["stdout"], common["stderr"] = exc.stdout or "", exc.stderr or ""
                common["exit_code"] = None
                common["command"] = executed_commands
                common["duration"] = round(time.perf_counter() - started, 3)
                return common
            except OSError as exc:
                common.update({"status": "TEST_EXECUTION_ERROR", "reason": str(exc), "stderr": str(exc)})
                common["command"] = executed_commands
                common["duration"] = round(time.perf_counter() - started, 3)
                return common
        executions.append(completed)
        outputs.append(completed.stdout)
        errors.append(completed.stderr)

    combined_output = "\n".join(outputs + errors)
    counts = _count_summary(combined_output)
    if counts["total"] == 0:
        status = "NO_TESTS_FOUND"
        reason = f"{python_framework or 'Configured test runner'} discovered no runnable tests in the analyzed repository."
    elif re.search(r"no tests? (?:were )?found|no test files? found", combined_output, re.IGNORECASE):
        status = "NO_TESTS_FOUND"
        reason = "The configured test runner discovered no runnable tests."
    elif any(result.returncode != 0 for result in executions):
        has_test_failures = any(int(counts[key] or 0) > 0 for key in ("failed", "errors"))
        if has_test_failures:
            status, reason = "TESTS_FAILED", None
        elif "error collecting" in combined_output.lower():
            status, reason = "TEST_DISCOVERY_ERROR", "The test runner could not collect tests from the analyzed repository."
        else:
            status, reason = "TEST_EXECUTION_ERROR", "The test command exited unsuccessfully without a parseable test-failure count."
    elif counts["total"] is None:
        status, reason = "TEST_EXECUTION_ERROR", "The test runner exited without a parseable test summary; raw output is preserved."
    elif counts["total"] and counts["skipped"] == counts["total"]:
        status, reason = "TESTS_SKIPPED", None
    else:
        status, reason = "TESTS_PASSED", None
    return {
        **common,
        "status": status,
        "reason": reason,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "errors": counts["errors"],
        "total": counts["total"],
        "duration": counts["duration"] if counts["duration"] is not None else round(time.perf_counter() - started, 3),
        "command": executed_commands,
        "stdout": "\n".join(outputs),
        "stderr": "\n".join(errors),
        "output": combined_output,
        "exit_code": max((result.returncode for result in executions), default=0),
    }