# Redakt

Open-source PII detection and anonymization wrapper around [Microsoft Presidio](https://github.com/microsoft/presidio). Web UI and REST API for GDPR-compliant redaction before pasting content into LLMs. Designed for enterprise internal deployment.

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

## API

All endpoints accept `"language": "auto"` (default) or an explicit language code. All endpoints respect allow lists and are audit-logged.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/detect` | PII detection — returns boolean + entity summary |
| `POST` | `/api/anonymize` | Anonymize text — returns placeholders + mapping |
| `POST` | `/api/deanonymize` | Restore original values from placeholders + mapping |
| `POST` | `/api/documents/upload` | Upload a file for PII detection/anonymization |
| `GET` | `/api/health` | Health check (includes Presidio service status) |

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
```

### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `REDAKT_PRESIDIO_ANALYZER_URL` | `http://localhost:5001` | Presidio Analyzer URL |
| `REDAKT_PRESIDIO_ANONYMIZER_URL` | `http://localhost:5001` | Presidio Anonymizer URL |
| `REDAKT_LOG_LEVEL` | `WARNING` | Application log level |
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
