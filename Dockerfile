# Root-level Dockerfile for the CodeGuardian backend.
# Render uses this when dockerfilePath is not configurable via Blueprint.
# This is identical to backend/Dockerfile.
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
# Render injects PORT at runtime; fall back to 10000 (Render's default internal port)
EXPOSE 10000
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
