from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from backend.storage import get_analysis, update_analysis
from backend.verification import verify_repository


def _run_git(args: list[str], repository: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repository, capture_output=True, text=True, timeout=60)


def _ensure_allowed_targets(repository: Path, files: list[str], allowed_files: list[str]) -> None:
    allowed_normalized = {str(Path(item).as_posix()) for item in allowed_files}
    for file_name in files:
        normalized = str(Path(file_name).as_posix())
        if normalized not in allowed_normalized:
            raise ValueError(f"Patch target not approved for implementation: {file_name}")
        resolved = (repository / normalized).resolve()
        if repository.resolve() not in resolved.parents and resolved != repository.resolve():
            raise ValueError(f"Patch target escapes repository boundary: {file_name}")


def _collect_git_diff(repository: Path) -> str:
    diff = _run_git(["diff", "--", "."], repository)
    return diff.stdout.strip()


def _run_verification(repository: Path, test_command: str | None) -> dict[str, Any]:
    if test_command:
        try:
            completed = subprocess.run(test_command, cwd=repository, shell=True, capture_output=True, text=True, timeout=180)
            output = (completed.stdout or "") + (completed.stderr or "")
            status = "TESTS_PASSED" if completed.returncode == 0 else "TESTS_FAILED"
            return {
                "status": status,
                "reason": None if completed.returncode == 0 else "Verification command failed.",
                "command": [[test_command]],
                "output": output,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "return_code": completed.returncode,
            }
        except Exception as exc:
            return {"status": "TEST_EXECUTION_ERROR", "reason": str(exc), "output": str(exc), "return_code": 1}
    return verify_repository(repository)


def _rollback(repository: Path) -> None:
    _run_git(["restore", "--staged", "."], repository)
    _run_git(["restore", "."], repository)
    _run_git(["clean", "-fd"], repository)


def execute_implementation(
    plan_id: str,
    repository_path: str,
    patch_data: list[dict[str, str]] | None,
    test_command: str | None = None,
    approved_files: list[str] | None = None,
) -> dict[str, Any]:
    repository = Path(repository_path).resolve()
    item = get_analysis(plan_id)
    if item is None:
        raise ValueError(f"Implementation plan {plan_id} not found.")

    result = item.get("result", {})
    plan = result.get("plan", [])
    allowed_files = []
    for task in plan:
        for file_name in task.get("files", []):
            if isinstance(file_name, str):
                allowed_files.append(file_name)

    if not approved_files:
        approved_files = sorted(set(allowed_files))

    if not repository.exists() or not repository.is_dir():
        raise ValueError(f"Repository path does not exist: {repository}")

    if not patch_data:
        return {
            "status": "implementation_skipped",
            "message": "No patch data was supplied.",
            "files_changed": [],
            "allowed_files": approved_files,
            "patch_data": [],
            "verification": {"status": "NOT_RUN", "reason": "No patch was applied."},
            "rolled_back": False,
        }

    _ensure_allowed_targets(repository, [entry["file"] for entry in patch_data], approved_files)

    git_root = _run_git(["rev-parse", "--show-toplevel"], repository)
    if git_root.returncode == 0:
        repo_root = Path(git_root.stdout.strip()).resolve()
        if repo_root == repository.resolve():
            git_status = _run_git(["status", "--porcelain"], repository)
            if git_status.stdout.strip():
                raise ValueError("Git working tree is not clean before implementation.")
            pre_commit_sha = _run_git(["rev-parse", "HEAD"], repository).stdout.strip()
        else:
            pre_commit_sha = "git-not-initialized"
    else:
        pre_commit_sha = "git-not-initialized"

    for entry in patch_data:
        relative_path = entry["file"]
        diff = entry["unified_diff"]
        target = repository / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not diff:
            continue
        patch_process = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=repository, input=diff, text=True, capture_output=True, timeout=60)
        if patch_process.returncode != 0:
            stderr = patch_process.stderr.strip()
            if "No valid patches in input" in stderr:
                continue
            _rollback(repository)
            raise RuntimeError(f"Patch could not be applied to {relative_path}: {stderr}")

    diff = _collect_git_diff(repository)
    verification = _run_verification(repository, test_command)

    if verification.get("status") not in {"TESTS_PASSED", "TESTS_SKIPPED"}:
        _rollback(repository)
        return {
            "status": "implementation_failed",
            "message": "Implementation rolled back because verification failed.",
            "pre_commit_sha": pre_commit_sha,
            "diff": diff,
            "verification": verification,
            "rolled_back": True,
            "files_changed": [entry["file"] for entry in patch_data],
            "allowed_files": approved_files,
            "patch_data": patch_data,
        }

    item["status"] = "implementation_complete"
    item["implementation"] = {
        "status": "implementation_complete",
        "message": "Implementation complete.",
        "files_changed": [entry["file"] for entry in patch_data],
        "diff": diff,
        "pre_commit_sha": pre_commit_sha,
        "verification": verification,
        "rolled_back": False,
    }
    update_analysis(item)
    return {
        "status": "implementation_complete",
        "message": "Implementation complete.",
        "pre_commit_sha": pre_commit_sha,
        "diff": diff,
        "verification": verification,
        "rolled_back": False,
        "files_changed": [entry["file"] for entry in patch_data],
        "allowed_files": approved_files,
        "patch_data": patch_data,
    }
