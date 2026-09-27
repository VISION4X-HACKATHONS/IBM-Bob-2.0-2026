FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY analyzer analyzer
COPY agents agents
COPY backend backend
COPY sample-project sample-project
# Render injects PORT at runtime; fall back to 8001 for local Docker use
EXPOSE 8001
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
