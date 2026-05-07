# Redakt

Open-source PII detection and anonymization wrapper around [Microsoft Presidio](https://github.com/microsoft/presidio). Web UI and REST API for GDPR-compliant redaction before pasting content into LLMs. Designed for enterprise internal deployment.

Read the launch announcement - [Meet Redakt: Practical GDPR Compliance for AI Teams](https://pablooliva.de/the-closing-window/meet-redakt-practical-gdpr-compliance-for-ai-teams/)

## What It Does

1. **Detect PII** — Send text, get back whether it contains personal data (with entity types and counts)
2. **Anonymize** — Replace PII with numbered placeholders (`<PERSON_1>`, `<EMAIL_1>`), then deanonymize LLM responses client-side using the returned mapping
3. **Document support** — Upload files (PDF, Excel, Word, CSV, JSON, XML, HTML, RTF, Markdown, plain text) for PII detection and anonymization
4. **Language auto-detection** — Automatically detects English and German (with manual override)
5. **Allow lists** — Configure terms that should never be flagged as PII (company names, product names, etc.)
6. **Audit logging** — GDPR-compliant metadata-only audit trail (never logs PII)

## Architecture

```
docker compose up --build
```

```
┌──────────────────────────────────────────────────────┐
│  docker-compose.yml                                  │
│                                                      │
│  ┌──────────────────────────────────────────┐        │
│  │  redakt                                  │        │
│  │  FastAPI + Jinja2/HTMX                   │        │
│  │  Web UI + REST API         :8000         │        │
│  └──────────┬───────────────────┬───────────┘        │
│             │                   │                    │
│  ┌──────────▼──────┐  ┌────────▼──────────┐          │
│  │ presidio        │  │ presidio          │          │
│  │ analyzer        │  │ anonymizer        │          │
│  │ (PII detection) │  │ (PII replacement) │          │
│  └─────────────────┘  └───────────────────┘          │
└──────────────────────────────────────────────────────┘
```

Browsers and AI agents connect to Redakt on port 8000. Presidio services are internal.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Git

### Setup

```bash
# Clone with the Presidio subrepository
git clone --recursive https://github.com/pablooliva/redakt.git
cd redakt

# Start everything
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000) for the web UI.

**Single-arch build (recommended).** On macOS / Apple Silicon hosts,
buildx may default to producing a multi-arch image stack that inflates
the analyzer image to ~36 GB uncompressed (the German transformer
weights + spaCy lemma surfaces are duplicated across `linux/amd64` and
`linux/arm64` layers). For local dev, force a single-arch build:

```bash
DOCKER_DEFAULT_PLATFORM=linux/arm64 docker compose up --build
# or, on x86_64 hosts:
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up --build

# Prod stack (uses docker-compose.prod.yml; same single-arch guidance applies):
DOCKER_DEFAULT_PLATFORM=linux/arm64 docker compose -f docker-compose.prod.yml up --build
```

Single-arch builds typically land at ~10–15 GB uncompressed. Spec ref:
SPEC-007 PERF-003 (image size is documentation-only; this is operator
guidance, not a hard cap).

**Hugging Face token (optional, build-time).** The analyzer image
fetches the German transformer weights from Hugging Face during the
build. Anonymous fetches are subject to HF Hub rate limits (RISK-001).
To pass a token without leaking it into an image layer, use BuildKit
secrets. Token plumbing is operator-hand-rolled and not part of the
default build path; if you hit `HTTP 429`, configure `HF_TOKEN` /
`HUGGINGFACE_HUB_TOKEN` in your environment and pass it through
`docker buildx build --secret id=hf_token,env=HUGGINGFACE_HUB_TOKEN ...`
with a corresponding `--mount=type=secret,id=hf_token` in
`Dockerfile.multi`.

### Production deploy (build local, stream over SSH)

Production runs do not build on the server and do not pull from a
registry. Images are built on a developer machine for `linux/amd64`,
then `docker save | ssh | docker load` streams them straight to the
Hetzner host. No registry, no auth tokens beyond your existing SSH key,
no monthly storage fee.

**Build (developer machine).** Single-arch `linux/amd64` to match the
Hetzner x86_64 host. On Apple Silicon hosts buildx runs amd64 under
QEMU emulation, which makes the analyzer image's transformer install
slow on first build (~30-60 min); subsequent builds reuse layer cache.

```bash
./tools/build-prod-images.sh
```

This populates the local Docker daemon with three tags:
`redakt-redakt:latest`, `redakt-presidio-analyzer:latest`,
`redakt-presidio-anonymizer:latest`.

**One-time setup (production host).** Ensure the external `caddy_net`
network exists, and copy `docker-compose.prod.yml` to the host (the
host needs nothing else from this repo):

```bash
docker network create caddy_net   # idempotent; ignore "already exists"
# from the dev machine:
scp docker-compose.prod.yml Hetzner-personal:~/redakt/
```

**Deploy.** From the dev machine, save + stream + load in one pipe
(~10 GB on the wire, gzip-compressed; expect a handful of minutes):

```bash
./tools/deploy-prod-images.sh
# Override default SSH alias if needed:
REDAKT_PROD_HOST=user@1.2.3.4 ./tools/deploy-prod-images.sh
```

Then on the host:

```bash
cd ~/redakt
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

The compose file keeps the original `build:` blocks so
`docker compose -f docker-compose.prod.yml up --build` still works on
a developer host when you want to rebuild without deploying. The
`image:` tags use bare names (no registry prefix) because `docker load`
preserves whatever name the image had when saved.

**Trade-off vs. a registry.** Each deploy transfers the FULL image
with no layer-level reuse on the wire. Fine for infrequent deploys;
painful if you push multiple times per day. If deploy frequency goes
up, switch to a self-hosted `registry:2` on the same Hetzner box
(layer caching, no extra cost) — see git history for the prior GHCR
flow as a reference.

## API

All endpoints accept `"language": "auto"` (default) or an explicit language code. All endpoints respect allow lists and are audit-logged.

> **Code-switched (mixed-language) text.** Auto-detection uses [lingua-py](https://github.com/pemistahl/lingua-py); whichever of `en` / `de` wins the vote drives the NLP engine for the entire request. For text that mixes both languages, set `language` explicitly to the language whose PII you most need detected. PII in the non-selected language may be missed. See `docs/presidio-integration.md` and SPEC-007 EDGE-001 for details.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/detect` | PII detection — returns boolean + entity summary |
| `POST` | `/api/anonymize` | Anonymize text — returns placeholders + mapping |
| `POST` | `/api/deanonymize` | Restore original values from placeholders + mapping |
| `POST` | `/api/documents/upload` | Upload a file for PII detection/anonymization |
| `GET` | `/api/health` | Health check (includes Presidio service status) |

See [`docs/supported-entities.md`](docs/supported-entities.md) for the full list of detectable entity types and their language scoping.

### Example: Detect

```bash
curl -X POST http://localhost:8000/api/detect \
  -H "Content-Type: application/json" \
  -d '{"text": "John Smith lives in Berlin", "language": "auto"}'
```

```json
{
  "has_pii": true,
  "entity_count": 2,
  "entities_found": ["LOCATION", "PERSON"]
}
```

### Tuning sensitivity per entity type

Some recognizers (notably `LOCATION` and `DATE_TIME`) fire at borderline confidence on generic terms like "Munich" or "today." Redakt applies an instance-wide map of per-entity score floors after Presidio returns; results below an entity's floor are dropped. Defaults: `LOCATION: 0.85`, `DATE_TIME: 0.95`.

Override per request via `entity_score_thresholds`:

```json
{
  "text": "John Smith was in Munich today",
  "entity_score_thresholds": {"LOCATION": 0.5}
}
```

Per-request keys override the instance map; entity types not listed use the global `score_threshold` (0.35 by default). Set the instance-wide map via the `REDAKT_ENTITY_SCORE_THRESHOLDS` env var (JSON-encoded). Valid keys are listed in [`docs/supported-entities.md`](docs/supported-entities.md).

### Example: Anonymize + Deanonymize Round-Trip

```bash
# 1. Anonymize — get placeholders + mapping
curl -X POST http://localhost:8000/api/anonymize \
  -H "Content-Type: application/json" \
  -d '{"text": "Contact John Smith at john@example.com"}'

# Response:
# {
#   "anonymized_text": "Contact <PERSON_1> at <EMAIL_ADDRESS_1>",
#   "mappings": {"<PERSON_1>": "John Smith", "<EMAIL_ADDRESS_1>": "john@example.com"},
#   ...
# }

# 2. Send anonymized text to your LLM, get response with placeholders...

# 3. Deanonymize — restore original values in the LLM's response
curl -X POST http://localhost:8000/api/deanonymize \
  -H "Content-Type: application/json" \
  -d '{
    "text": "<PERSON_1> has been notified at <EMAIL_ADDRESS_1>.",
    "mappings": {"<PERSON_1>": "John Smith", "<EMAIL_ADDRESS_1>": "john@example.com"}
  }'

# Response:
# {"text": "John Smith has been notified at john@example.com.", "replacements_made": 2}
```

## AI Agent Integration

Redakt is designed to work as a tool for AI agents, not just human users. Agents use the same REST API as the web UI — no separate integration layer.

**Typical agent workflow:**

1. Before sending user content to an LLM, `POST /api/anonymize` to replace PII with placeholders
2. Send the anonymized text to the LLM
3. `POST /api/deanonymize` with the LLM's response and the mapping to restore original values

**What makes this agent-friendly:**

- **Stateless round-trip** — The anonymize response includes the mapping; the agent passes it back to deanonymize. No sessions, no server-side state to manage.
- **Single JSON API** — All endpoints accept and return JSON. No browser, cookies, or HTML parsing required.
- **OpenAPI schema** — Available at `/docs` (Swagger UI) and `/openapi.json` for auto-generating client code.
- **Health check** — `GET /api/health` reports Presidio service status so agents can verify availability before processing.
- **Consistent error format** — All errors return `{"detail": "..."}` with standard HTTP status codes (400, 422, 503, 504).

## Key Design Decisions

- **No PII at rest** — The backend never persists personal data. Anonymization mappings are returned to the client. Deanonymization can happen client-side (browser string replacement) or via the `/api/deanonymize` endpoint for AI agents.
- **Metadata-only audit logs** — Audit entries log action type, entity counts/types, language, and source. Never the original text.
- **Presidio via REST API** — Redakt wraps Presidio's HTTP endpoints. The `presidio/` directory is a fork used for Docker builds, not a library dependency.

## Development

### Running Tests

```bash
# Install dev dependencies
uv sync --extra dev

# Unit + integration tests (no Docker needed)
uv run pytest tests/

# E2E browser tests (requires docker compose up)
uv run pytest tests/e2e/

# PII detection eval suite — end-to-end against the Redakt API.
# Asserts that current entity_score_thresholds keep benign phrases clean
# and detect known PII across en/de fixtures. Requires the full Docker
# Compose stack (Redakt + Presidio) running.
uv run pytest tests/eval/

# Calibration report (same fixtures, prints scores per phrase — no asserts).
# Default: shows what Redakt /api/detect returns.
# --raw: also calls Presidio directly with score_threshold=0 so you can see
# candidates the per-entity floors filtered out — useful for tuning.
# --out: also write a Markdown report (default: reports/calibration-{ts}.md,
# gitignored). Pass --out PATH for a custom destination.
uv run python tools/calibration_report.py
uv run python tools/calibration_report.py --raw --only benign,us
uv run python tools/calibration_report.py --raw --out
```

### Configuration

Defaults are defined in `src/redakt/config.py`. Set any of the following env vars (or place them in a `.env` file — see `.env.example`) to override at startup.

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `REDAKT_PRESIDIO_ANALYZER_URL` | `http://localhost:5001` | Presidio Analyzer URL |
| `REDAKT_PRESIDIO_ANONYMIZER_URL` | `http://localhost:5001` | Presidio Anonymizer URL |
| `REDAKT_LOG_LEVEL` | `WARNING` | Application log level |
| `REDAKT_ENTITY_SCORE_THRESHOLDS` | `{"LOCATION": 0.90, "DATE_TIME": 0.95}` | JSON map of per-entity score floors applied after Presidio analysis |
| `REDAKT_AUDIT_LOG_FILE` | _(empty)_ | Optional file path for audit logs (in addition to stdout) |
| `REDAKT_AUDIT_LOG_MAX_BYTES` | `10485760` | Max audit log file size before rotation (10 MB) |
| `REDAKT_AUDIT_LOG_BACKUP_COUNT` | `5` | Number of rotated audit log backups to keep |

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn
- **Frontend:** Jinja2 templates, HTMX
- **PII Engine:** Microsoft Presidio (spaCy multilingual NLP)
- **Language Detection:** lingua-py
- **Document Parsing:** pdfminer.six, openpyxl, python-docx, BeautifulSoup, defusedxml
- **Package Management:** uv
- **Testing:** pytest, Playwright (E2E)

## License

[ProPal Ethical License v1.0](LICENSE)
