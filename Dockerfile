FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY src/ ./src/
RUN uv pip install --system .

RUN useradd -m -u 1001 redakt && chown -R redakt:redakt /app
USER 1001

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/live || exit 1

CMD ["python", "-c", "import uvicorn; from redakt.log_config import UVICORN_LOG_CONFIG; uvicorn.run('redakt.main:app', host='0.0.0.0', port=8000, reload=True, reload_dirs=['/app/src'], log_config=UVICORN_LOG_CONFIG)"]
