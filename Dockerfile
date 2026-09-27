# ── Stage 1: Build the React/Vite frontend ──────────────────────────────────
FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
# Backend URL is the same origin (single service), so use relative /api path.
# We override the full API constant in main.tsx via the fallback default.
RUN npm run build

# ── Stage 2: Python backend + bundled frontend ───────────────────────────────
FROM python:3.13-slim
WORKDIR /app

# git is required to clone public GitHub repos for analysis
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY analyzer analyzer
COPY agents agents
COPY backend backend
COPY sample-project sample-project

# Copy the built React app so FastAPI can serve it as static files
COPY --from=frontend-build /frontend/dist /app/frontend/dist

# Render injects PORT at runtime; fall back to 10000 (Render's default)
EXPOSE 10000
# Docker healthcheck so the container is only marked ready when uvicorn is up
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-10000}/api/health', timeout=4)"
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --timeout-keep-alive 75"]
