# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Redakt is an enterprise-internal web app and REST API that wraps Microsoft Presidio for GDPR-compliant PII detection and anonymization. Users anonymize text before pasting it into AI tools. AI agents can also call the same REST endpoints.

The Redakt application code is being built on top of Presidio, which lives as a forked repository at `./presidio/`.

## Architecture

- **Redakt API** — Stateless backend that orchestrates Presidio's two services. Never persists PII. Anonymization mappings are returned to the client (browser holds them; deanonymization is client-side).
- **Presidio Analyzer** (port 5002) — PII detection via NLP/regex/country-specific recognizers. REST API.
- **Presidio Anonymizer** (port 5001) — PII replacement operators (replace, redact, mask, hash, encrypt). REST API.
- **Redakt Frontend** — Web UI that talks to the Redakt API.

All four services run from a single `docker-compose.yml`. Presidio services are internal — only Redakt API talks to them.

## Running Presidio Locally

```bash
# Transformers-based (better accuracy, larger image — uses StanfordAIMI/stanford-deidentifier-base)
docker compose -f presidio/docker-compose-transformers.yml up --build

# spaCy-based (faster builds, lighter — uses en_core_web_lg)
docker compose -f presidio/docker-compose-text.yml up --build
```

Analyzer: `http://localhost:5002`, Anonymizer: `http://localhost:5001`

## Key Documentation

- `docs/v1-feature-spec.md` — V1 feature specification (6 features, API contracts, open questions)
- `docs/presidio-integration.md` — How Presidio works, its architecture, API surface, and integration options
- `presidio/docs/api-docs/api-docs.yml` — OpenAPI 3.0 spec for Presidio's REST API

## Presidio Subdirectory

`./presidio/` is a fork of [microsoft/presidio](https://github.com/microsoft/presidio) (remote: `git@github.com:pablooliva/presidio.git`). It is a separate git repository, not a submodule. Do not modify Presidio source unless explicitly asked — Redakt wraps it via its REST API.

Key Presidio modules: `presidio-analyzer/`, `presidio-anonymizer/`, `presidio-structured/`, `presidio-image-redactor/`, `presidio-cli/`.

## Testing

```bash
# Unit + integration tests (fast, no Docker needed)
uv run pytest tests/

# E2E browser tests with Playwright (requires docker compose up)
uv run pytest tests/e2e/

# E2E with visible browser
uv run pytest tests/e2e/ --headed
```

- Unit/integration tests use FastAPI's TestClient with mocked Presidio — no real services needed.
- E2E tests use Playwright (Chromium) against the real Docker Compose stack on `localhost:8000`.
- E2E tests are excluded from `uv run pytest tests/` by default (`--ignore=tests/e2e` in pyproject.toml).
- When implementing features with browser-facing behavior (JS, HTMX, CSP, client-side logic, multi-step UI flows), add E2E tests in `tests/e2e/`.
- E2E tests use real Presidio NLP — test data must account for real detection (not mocked).

## Design Decisions

- **Client-side PII mapping**: Anonymize endpoint returns the placeholder-to-original mapping. The browser (or AI agent) holds it in memory. Deanonymization is client-side string replacement. Backend stays stateless with no PII at rest.
- **Language auto-detection**: All endpoints default to auto-detect, with manual override available.
- **Allow lists**: Instance-wide config merged with per-request terms. Passed to Presidio's `allow_list` parameter.
- **Audit logging**: Metadata only (timestamp, action, entity types/counts, source). Never logs actual PII or original text.
