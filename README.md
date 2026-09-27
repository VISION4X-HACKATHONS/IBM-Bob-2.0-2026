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

The frontend runs at `http://localhost:5173` and the API at `http://localhost:8000` by default.

### AI provider configuration

```powershell
# Local Ollama default
$env:LLM_PROVIDER = "ollama"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "qwen2.5-coder:7b"

# Cloud Gemini example
$env:LLM_PROVIDER = "gemini"
$env:GEMINI_API_KEY = "<your-api-key>"
$env:GEMINI_MODEL = "gemini-3.7-flash"
```

For local development, Ollama remains the default. Gemini is supported for cloud demo use.

No API key is required for the local Ollama workflow. If Ollama is unavailable, the backend returns:

`AI code generator unavailable. Start Ollama and ensure the configured model exists.`

### Frontend API URL

For local development, the frontend reads the API base from `VITE_API_URL`.

```bash
VITE_API_URL=http://127.0.0.1:8000
```

For cloud deployment, set the rendered backend URL instead of hardcoding localhost.

### GitHub public demo repositories

The repository field accepts either:
- a local filesystem path, or
- a public GitHub HTTPS URL like `https://github.com/owner/repo.git`

The backend validates the GitHub URL, clones it into a temporary directory, analyzes the clone, and keeps the flow in the safe approval + verification pipeline.

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
