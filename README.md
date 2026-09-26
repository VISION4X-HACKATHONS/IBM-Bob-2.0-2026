# CODEGUARDIAN

CODEGUARDIAN is a local-first application-maintenance workflow for understanding the impact of a developer change request. It scans a repository, extracts code and dependency evidence, produces a structured impact map and implementation plan, runs verification tests, and generates a report.

This repository is being built in normal VS Code development tools. IBM Bob is intentionally not used in this phase.

## Run locally

### Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` and the API at `http://localhost:8001`.

### Docker

After the local workflow is working, run `docker compose up --build`. The frontend is available at `http://localhost:5173` and the API at `http://localhost:8001`.

## Workflow

1. Enter a change request and repository path.
2. Analyze the repository using Python AST and dependency manifests.
3. Review evidence, risks, and the generated implementation plan.
4. Run the repository verification command.
5. Inspect the final report and actual test result.

## Project layout

- `backend/`: FastAPI API and workflow orchestration
- `analyzer/`: repository scanning and impact analysis
- `sample-project/`: small interconnected authentication application
- `frontend/`: React + Vite dashboard
- `tests/`: analyzer and API tests
- `docs/`: architecture, workflow, testing, and baseline notes
