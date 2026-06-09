FROM node:20-alpine AS frontend-builder

WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

ENV GATEWAY_DB_PATH=/app/data/gateway.db

COPY pyproject.toml ./
COPY app/ ./app/
COPY config/ ./config/
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir .

COPY --from=frontend-builder /src/frontend/dist ./frontend/dist

RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
