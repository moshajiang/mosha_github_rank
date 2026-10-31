FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/backend
ENV GITHUB_RANK_DB=/app/data/github_rank.sqlite3 GITHUB_RANK_CONFIG=/app/config/sources.yaml
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/github_rank/ ./backend/github_rank/
COPY config/ ./config/
COPY --from=web /web/dist/ ./frontend/dist/
RUN mkdir -p /app/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"
CMD ["python", "-m", "uvicorn", "github_rank.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
