from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from analyzer.repository import analyze_change, to_dict, validate_repository_path
from backend.services import code_generator
from backend.services.implement_service import execute_implementation
from backend.storage import (
    get_analysis as load_analysis,
    save_analysis,
    update_analysis,
)
from backend.verification import verify_repository


ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="CODEGUARDIAN API", version="0.1.0")


def _cors_origins() -> list[str]:
    """
    Build the CORS allow-list from the ALLOWED_ORIGINS environment variable.

    The variable should be a comma-separated list of origins, e.g.:
        ALLOWED_ORIGINS=https://my-frontend.onrender.com,http://localhost:5173

    If the variable is not set, the defaults below are used so that local
    development continues to work without any extra configuration.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Default: allow local dev origins only
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    request: str = Field(min_length=5, max_length=500)
    repository_path: str


class VerifyRequest(BaseModel):
    repository_path: str
    analysis_id: str | None = None


class AnalysisReference(BaseModel):
    analysis_id: str


class ImplementationRequest(AnalysisReference):
    approved: bool = False
    files: list[str] = []
    generate_patch: bool = False
    patch_data: list[dict[str, str]] | None = None
    test_command: str | None = None


def _is_public_github_https_url(repository_path: str) -> bool:
    value = (repository_path or "").strip()

    if not value:
        return False

    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1].strip()

    if not value:
        return False

    parsed = urlparse(value)

    if parsed.scheme.lower() != "https":
        return False

    if parsed.netloc.lower() not in {
        "github.com",
        "www.github.com",
    }:
        return False

    if "localhost" in parsed.netloc.lower() or "127.0.0.1" in parsed.netloc.lower():
        return False

    path = parsed.path.strip("/")

    if not path or ".." in path:
        return False

    parts = [part for part in path.split("/") if part]

    if len(parts) != 2:
        return False

    if any(part in {"", "."} for part in parts):
        return False

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0]):
        return False

    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+",
        parts[1].removesuffix(".git"),
    ):
        return False

    return True


def _clone_public_github_repo(repo_url: str) -> Path:
    if not _is_public_github_https_url(repo_url):
        raise ValueError(
            "Repository URL must be a public HTTPS GitHub repository URL."
        )

    parsed = urlparse(repo_url)

    repo_name = (
        parsed.path.strip("/")
        .split("/")[-1]
        .removesuffix(".git")
    )

    clone_root = Path(
        tempfile.mkdtemp(prefix="codeguardian-github-")
    )

    target = clone_root / repo_name

    result = subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            repo_url,
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        shutil.rmtree(
            clone_root,
            ignore_errors=True,
        )

        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "GitHub repository clone failed."
        )

        raise RuntimeError(
            f"GitHub repository clone failed: {message}"
        )

    return target.resolve()


def _resolve_repository(repository_path: str) -> Path:
    try:
        candidate = str(repository_path).strip()

        if candidate.startswith('"') and candidate.endswith('"'):
            candidate = candidate[1:-1].strip()

        if not candidate:
            raise ValueError("Repository path is required.")

        if _is_public_github_https_url(candidate):
            return _clone_public_github_repo(candidate)

        return validate_repository_path(candidate)

    except (
        FileNotFoundError,
        NotADirectoryError,
        PermissionError,
        ValueError,
        RuntimeError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _cleanup_temp_repository(
    record: dict[str, object],
) -> None:
    clone_dir = record.get("temp_clone_dir")

    if not clone_dir:
        return

    try:
        shutil.rmtree(
            str(clone_dir),
            ignore_errors=True,
        )
    finally:
        record["temp_clone_dir"] = None
        update_analysis(record)


@app.post("/api/analyze")
def analyze(
    payload: AnalyzeRequest,
) -> dict[str, object]:

    repository = _resolve_repository(
        payload.repository_path
    )

    try:
        result = to_dict(
            analyze_change(
                repository,
                payload.request,
            )
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Repository analysis failed: {exc}",
        ) from exc

    analysis_id = str(uuid.uuid4())

    item: dict[str, object] = {
        "id": analysis_id,
        "status": "analyzed",
        "repository_path": str(repository),
        "result": result,
    }

    if _is_public_github_https_url(
        payload.repository_path
    ):
        item["temp_clone_dir"] = str(repository)

    save_analysis(item)

    return item


@app.get("/api/analysis/{analysis_id}")
def get_analysis(
    analysis_id: str,
) -> dict[str, object]:

    item = load_analysis(analysis_id)

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found",
        )

    return item


@app.post("/api/plan")
def plan(
    payload: AnalysisReference,
) -> dict[str, object]:

    item = get_analysis(
        payload.analysis_id
    )

    result = item["result"]

    return {
        "analysis_id": payload.analysis_id,
        "status": "ready",
        "plan": result["plan"],
    }


@app.post("/api/implement")
def implement(
    payload: ImplementationRequest,
) -> dict[str, object]:

    item = get_analysis(
        payload.analysis_id
    )

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found",
        )

    result = item["result"]

    affected_files = set(
        result["affected_files"]
    )

    requested_files = (
        sorted(set(payload.files))
        if payload.files
        else sorted(affected_files)
    )

    unauthorized = sorted(
        set(requested_files) - affected_files
    )

    if unauthorized:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Implementation files must come "
                    "from the analysis result."
                ),
                "files": unauthorized,
            },
        )

    if not payload.approved:
        return {
            "analysis_id": payload.analysis_id,
            "status": "approval_required",
            "files": requested_files,
            "message": (
                "Review the plan and approve these "
                "files before implementation."
            ),
        }

    item["status"] = "implementation_approved"

    update_analysis(item)

    if payload.generate_patch and not payload.patch_data:

        try:
            generated = (
                code_generator.generate_code_patches(
                    payload.analysis_id
                )
            )

            patch_data = (
                generated.get("patch_data") or []
            )

        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        if not patch_data:
            raise HTTPException(
                status_code=400,
                detail=(
                    "AI code generator returned "
                    "no valid patch data."
                ),
            )

        return execute_implementation(
            payload.analysis_id,
            str(
                Path(
                    item["repository_path"]
                ).resolve()
            ),
            patch_data,
            payload.test_command,
            requested_files,
        )

    if payload.patch_data:

        return execute_implementation(
            payload.analysis_id,
            str(
                Path(
                    item["repository_path"]
                ).resolve()
            ),
            payload.patch_data,
            payload.test_command,
            requested_files,
        )

    return {
        "analysis_id": payload.analysis_id,
        "status": "approved_manifest",
        "files": requested_files,
        "changed_files": [],
        "message": (
            "Manifest approved. No files were modified."
        ),
    }


@app.post("/api/verify")
def verify(
    payload: VerifyRequest,
) -> dict[str, object]:

    repository = _resolve_repository(
        payload.repository_path
    )

    item = (
        get_analysis(payload.analysis_id)
        if payload.analysis_id
        else None
    )

    if item is not None:

        analyzed_repository = Path(
            str(item["repository_path"])
        ).resolve()

        if repository != analyzed_repository:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Verification repository must match "
                    "the analyzed repository path."
                ),
            )

        repository = analyzed_repository

    verification = verify_repository(
        repository
    )

    if payload.analysis_id:

        item = get_analysis(
            payload.analysis_id
        )

        item["verification"] = verification

        item["status"] = (
            "verified"
            if verification["status"] == "TESTS_PASSED"
            else (
                "verification_failed"
                if verification["status"] == "TESTS_FAILED"
                else verification["status"]
            )
        )

        update_analysis(item)

    return verification


@app.get("/api/git/status")
def git_status(
    repository_path: str,
) -> dict[str, object]:

    repository = _resolve_repository(
        repository_path
    )

    status = subprocess.run(
        [
            "git",
            "status",
            "--short",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=15,
    )

    diff = subprocess.run(
        [
            "git",
            "diff",
            "--stat",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=15,
    )

    return {
        "repository_path": str(repository),
        "requested_repository_path": repository_path,
        "clean": not status.stdout.strip(),
        "status": status.stdout.splitlines(),
        "diff_stat": diff.stdout.splitlines(),
    }


@app.get("/api/report/{analysis_id}")
def report(
    analysis_id: str,
) -> dict[str, object]:

    item = get_analysis(
        analysis_id
    )

    result = item["result"]

    if item.get("temp_clone_dir"):
        _cleanup_temp_repository(item)

    return {
        "analysis_id": analysis_id,
        "status": item["status"],
        "report": {
            **result,
            "verification": item.get(
                "verification",
                {
                    "status": "pending",
                    "message": (
                        "Verification has not run."
                    ),
                },
            ),
        },
    }