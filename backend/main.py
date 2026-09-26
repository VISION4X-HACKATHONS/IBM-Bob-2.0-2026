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
