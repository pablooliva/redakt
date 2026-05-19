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
# Bake the committed runtime policy into the image so the prod compose
# (which does not mount a host-side config.yaml) still picks up the
# floors, closed-world settings, strong-anchors, and quasi-identifier
# lists. Aligns with the "ship the image" deploy model: rolling back
# config requires a rebuild, but config is committed to git anyway so
# review-with-code is the audit trail. The dev compose's bind mount of
# the host file takes precedence at runtime, so iteration on the host
# still works.
COPY config.yaml ./
RUN uv pip install --system -e .

RUN useradd -m -u 1001 redakt && chown -R redakt:redakt /app
USER 1001

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/live || exit 1

CMD ["python", "-c", "import uvicorn; from redakt.log_config import UVICORN_LOG_CONFIG; uvicorn.run('redakt.main:app', host='0.0.0.0', port=8000, reload=True, reload_dirs=['/app/src'], log_config=UVICORN_LOG_CONFIG)"]
