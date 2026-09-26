from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from analyzer.repository import analyze_change, to_dict


ROOT = Path(__file__).resolve().parents[1]
analyses: dict[str, dict[str, object]] = {}

app = FastAPI(title="CODEGUARDIAN API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


class AnalyzeRequest(BaseModel):
    request: str = Field(min_length=5, max_length=500)
    repository_path: str = "sample-project"


class VerifyRequest(BaseModel):
    repository_path: str = "sample-project"


class AnalysisReference(BaseModel):
    analysis_id: str


class ImplementationRequest(AnalysisReference):
    approved: bool = False
    files: list[str] = []


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze(payload: AnalyzeRequest) -> dict[str, object]:
    repository = (ROOT / payload.repository_path).resolve() if not Path(payload.repository_path).is_absolute() else Path(payload.repository_path).resolve()
    if not repository.exists() or not repository.is_dir() or ROOT not in repository.parents and repository != ROOT:
        raise HTTPException(status_code=400, detail="Repository path must be an existing directory inside this workspace.")
    analysis_id = str(uuid.uuid4())
    result = to_dict(analyze_change(repository, payload.request))
    analyses[analysis_id] = {"id": analysis_id, "status": "analyzed", "result": result}
    return analyses[analysis_id]


@app.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: str) -> dict[str, object]:
    if analysis_id not in analyses:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analyses[analysis_id]


@app.post("/api/plan")
def plan(payload: AnalysisReference) -> dict[str, object]:
    item = get_analysis(payload.analysis_id)
    result = item["result"]
    return {"analysis_id": payload.analysis_id, "status": "ready", "plan": result["plan"]}


@app.post("/api/implement")
def implement(payload: ImplementationRequest) -> dict[str, object]:
    item = get_analysis(payload.analysis_id)
    result = item["result"]
    affected_files = set(result["affected_files"])
    requested_files = sorted(set(payload.files)) if payload.files else sorted(affected_files)
    unauthorized = sorted(set(requested_files) - affected_files)
    if unauthorized:
        raise HTTPException(status_code=400, detail={"message": "Implementation files must come from the analysis result.", "files": unauthorized})
    if not payload.approved:
        return {"analysis_id": payload.analysis_id, "status": "approval_required", "files": requested_files, "message": "Review the plan and approve these files before implementation."}
    item["status"] = "implementation_approved"
    return {"analysis_id": payload.analysis_id, "status": "approved_manifest", "files": requested_files, "changed_files": [], "message": "Manifest approved. No files were modified."}


@app.post("/api/verify")
def verify(payload: VerifyRequest) -> dict[str, object]:
    repository = (ROOT / payload.repository_path).resolve()
    if not repository.exists():
        raise HTTPException(status_code=400, detail="Repository not found")
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=repository, capture_output=True, text=True, timeout=60)
    return {"status": "passed" if completed.returncode == 0 else "failed", "exit_code": completed.returncode, "output": (completed.stdout + completed.stderr)[-6000:]}


@app.get("/api/report/{analysis_id}")
def report(analysis_id: str) -> dict[str, object]:
    item = get_analysis(analysis_id)
    return {"analysis_id": analysis_id, "status": item["status"], "report": item["result"]}
