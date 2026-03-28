# RESEARCH-001-pii-detection

## Context

Feature 1 from `docs/v1-feature-spec.md`: a `POST /api/detect` endpoint that returns a boolean indicating whether text contains PII, plus optional entity summary. This is the simplest feature and serves as the foundation for the entire Redakt backend — the tech stack decision made here carries through all other features.

## System Data Flow

```
Client (Web UI or AI Agent)
    |
    | POST /api/detect { "text": "...", "language": "auto" }
    v
+-------------------+
| Redakt API        |
| (FastAPI)         |
|                   |
| 1. Auto-detect    |
|    language       |
| 2. Merge allow    |
|    lists          |
| 3. Call Presidio  |
| 4. Reduce to      |
|    boolean +      |
|    summary        |
| 5. Audit log      |
+--------+----------+
         |
         | POST /analyze { "text": "...", "language": "en", "score_threshold": 0.35, "allow_list": [...] }
         v
+-------------------+
| Presidio Analyzer |
| :5002             |
+-------------------+
         |
         | [ { "entity_type": "PERSON", "start": 0, "end": 10, "score": 0.85 }, ... ]
         v
+-------------------+
| Redakt API        |
| (response build)  |
+-------------------+
         |
         | { "has_pii": true, "entity_count": 2, "entities_found": ["PERSON", "LOCATION"], "language_detected": "en" }
         v
Client
```

### Key Entry Points

- Redakt: `POST /api/detect` — to be built
- Presidio: `POST /analyze` on port 5002 (defined in `presidio/presidio-analyzer/app.py:65-116`)
- Presidio API schema: `presidio/docs/api-docs/api-docs.yml:26-98`

### External Dependencies

- Presidio Analyzer REST API (port 5002) — required, must be running
- Language detection library (for `"language": "auto"`)

## Tech Stack Decision

### Backend Framework: FastAPI

**Decision: FastAPI over Flask.**

Rationale:
- Presidio's own sample applications (OpenAI anonymization, telemetry redaction) use FastAPI, not Flask — even though Presidio's core services are Flask
- Built-in OpenAPI/Swagger docs — Redakt gets interactive API documentation for free
- Native async support — Redakt is I/O-bound (HTTP calls to Presidio, file uploads), async is a natural fit
- Pydantic request/response models — type-safe API contracts with validation
- Better developer experience for a modern Python project

### Full Stack

| Layer | Choice | Rationale |
|---|---|---|
| **Backend framework** | FastAPI | Async, Pydantic models, auto-generated OpenAPI docs |
| **ASGI server** | Uvicorn | Standard for FastAPI; Gunicorn as process manager in production |
| **HTTP client** | httpx | Async HTTP client for calling Presidio's REST API |
| **Language detection** | lingua-py | More accurate than langdetect on short text (<30 words), critical for correct recognizer selection |
| **Dependency management** | uv | Faster than Poetry, simpler workflow, produces standard pyproject.toml |
| **Python version** | 3.12 | Matches Presidio Analyzer's Docker base image |
| **Docker base image** | python:3.12-slim | Consistent with Presidio |
| **Frontend** | HTMX + Jinja2 templates | Server-rendered, no JS build step, FastAPI serves HTML directly |
| **CSS** | TBD (Tailwind, Pico, or similar) | Lightweight styling for enterprise tool |
| **Presidio NLP engine** | spaCy multilingual | Built-in config (`spacy_multilingual.yaml`): `en_core_web_lg` + `de_core_news_lg`. Proven, no custom model config needed. Can upgrade to multilingual transformer later if accuracy is insufficient. |

### Project Structure (Proposed)

```
redakt/
├── docker-compose.yml          # Full stack: redakt + presidio services (3 services)
├── Dockerfile                  # Redakt API container
├── pyproject.toml              # uv project config
├── src/
│   └── redakt/
│       ├── __init__.py
│       ├── main.py             # FastAPI app entry point (serves API + HTML)
│       ├── config.py           # Settings (Presidio URLs, thresholds, allow lists)
│       ├── routers/
│       │   ├── detect.py       # POST /api/detect
│       │   ├── anonymize.py    # POST /api/anonymize (Feature 2)
│       │   ├── documents.py    # POST /api/documents/upload (Feature 3)
│       │   ├── health.py       # GET /api/health
│       │   └── pages.py        # GET / — serves Jinja2 HTML pages
│       ├── services/
│       │   ├── presidio.py     # HTTP client wrapper for Presidio API calls
│       │   ├── language.py     # Language auto-detection
│       │   └── audit.py        # Audit logging
│       ├── models/
│       │   ├── detect.py       # Request/response Pydantic models for detect
│       │   ├── anonymize.py    # Request/response models for anonymize
│       │   └── common.py       # Shared models
│       ├── templates/          # Jinja2 HTML templates
│       │   ├── base.html       # Layout with HTMX script tag
│       │   ├── detect.html     # PII detection page
│       │   ├── anonymize.html  # Anonymize/deanonymize page
│       │   └── documents.html  # Document upload page
│       └── static/             # CSS, vanilla JS for client-side deanonymization
│           ├── style.css
│           └── mapping.js      # ~20 lines: holds mapping, does string replacement
├── tests/
│   ├── test_detect.py
│   ├── test_presidio_client.py
│   └── conftest.py
├── presidio/                   # Git submodule
├── docs/
└── SDD/
```

## Presidio /analyze API Contract

### Request (POST /analyze on port 5002)

Required:
- `text` (string or array of strings)
- `language` (string, ISO 639-1, e.g., "en", "de") — **required, no auto-detect**

Optional:
- `score_threshold` (float, 0.0-1.0) — filter results below this confidence
- `entities` (array of strings) — only detect these entity types
- `allow_list` (array of strings) — suppress matches for these terms
- `allow_list_match` ("exact" or "regex", default "exact")
- `return_decision_process` (boolean) — include analysis explanation
- `context` (array of strings) — boost scores near these words
- `ad_hoc_recognizers` (array) — one-off pattern recognizers for this request
- `correlation_id` (string) — for tracing

### Response

Array of detected entities (empty array = no PII):
```json
[
  {
    "entity_type": "PERSON",
    "start": 0,
    "end": 10,
    "score": 0.85,
    "analysis_explanation": null
  }
]
```

Key insight: **an empty array means no PII detected.** Redakt's detect endpoint reduces this to `len(results) > 0`.

## Redakt /api/detect Endpoint Design

### Request Model

```python
class DetectRequest(BaseModel):
    text: str = Field(..., max_length=512_000)  # 500KB max
    language: str = "auto"              # "auto" or ISO 639-1 code
    score_threshold: float = 0.35       # low enough to catch pattern-based detections
    entities: list[str] | None = None   # None = all entities
    allow_list: list[str] | None = None # per-request allow list (case-sensitive)
```

### Response Model

```python
class DetectResponse(BaseModel):
    has_pii: bool
    entity_count: int
    entities_found: list[str]           # unique entity types
    language_detected: str              # the language used for analysis
```

### Optional Verbose Response

```python
class DetectDetailedResponse(DetectResponse):
    details: list[EntityDetail]         # full entity list with positions and scores

class EntityDetail(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float
```

Verbose mode triggered by query param: `POST /api/detect?verbose=true`

### Processing Steps

1. **Validate input**: Reject text exceeding 500KB. Validate language code if explicit.
2. **Language detection**: If `language == "auto"`, detect using `lingua-py`. Fall back to `"en"` if detection fails or confidence is too low.
3. **Validate language support**: Check resolved language against Presidio's supported languages (cached at startup via `GET /supportedentities?language=XX`). Return 400 if unsupported.
4. **Merge allow lists**: Combine instance-wide allow list (from config) with per-request `allow_list`. Allow list matching is case-sensitive (Presidio's default behavior).
5. **Call Presidio**: `POST http://presidio-analyzer:5002/analyze` with text, resolved language, score_threshold, entities, merged allow_list.
6. **Build response**: Count results, extract unique entity types, determine `has_pii`.
7. **Audit log**: Log metadata (timestamp, action="detect", entity_count, entity_types, language, source).
8. **Return**: `DetectResponse` or `DetectDetailedResponse` based on verbose flag.

## Open Questions — Resolved

| Question | Decision | Rationale |
|---|---|---|
| Configurable score threshold? | Yes, default 0.35 | Low enough to catch pattern-based detections (phone, credit card often score 0.4–0.6). Presidio's default is 0.0 — 0.35 filters noise while preserving real PII. Per-request override available. |
| Excludable entity types? | Yes, via `entities` param | Pass-through to Presidio's existing `entities` filter. |
| Verbose mode with details? | Yes, via `?verbose=true` | Useful for debugging and agent transparency without cluttering default response. |
| NLP engine for Presidio? | spaCy multilingual | Built-in `spacy_multilingual.yaml` supports EN + DE out of the box. The transformers model (`StanfordAIMI/stanford-deidentifier-base`) is English-only — unsuitable for a German enterprise. Can upgrade to a multilingual transformer (e.g., `Davlan/xlm-roberta-base-ner-hf`) later if accuracy is insufficient. |
| Language detection library? | lingua-py | More reliable than langdetect on short text (<30 words). ~30MB heavier but accuracy is critical — wrong language means wrong recognizers and missed PII. |
| Allow list case sensitivity? | Case-sensitive (Presidio default) | Users are expected to match exact capitalization. Documented in API. |
| Request size limit? | 500KB for text, 20MB for document uploads | Prevents OOM in NER model for text. Document limit covers typical Excel/PDF files. |

## Security Considerations

- **No PII storage**: Detect endpoint is fully stateless — text is forwarded to Presidio and discarded
- **Input validation**: Pydantic models enforce types. Text capped at 500KB, document uploads at 20MB.
- **Internal service communication**: Presidio services are on an internal Docker network, not exposed externally
- **Audit logging**: Metadata only — never log the input text or detected PII values
- **Language validation**: Redakt validates language against Presidio's supported list before forwarding. Prevents opaque 500 errors from Presidio for unsupported languages.

## Startup and Readiness

Presidio's Analyzer container needs time to load NLP models into memory (10–30 seconds for spaCy). During this window, Redakt must not forward requests.

- `docker-compose.yml` should use `depends_on` with health check conditions
- Presidio exposes `GET /health` — Redakt should probe this on startup
- Redakt's own `GET /api/health` should report `"ready": false` until Presidio responds
- On startup, Redakt should cache Presidio's supported languages (`GET /supportedentities`) for input validation

## Testing Strategy

- **Unit tests**: Mock httpx calls to Presidio, test response reduction logic, test language detection fallback
- **Integration tests**: With Presidio running in Docker, send real text and verify end-to-end flow
- **Edge cases**:
  - Empty text
  - Text with no PII
  - Text in unsupported language
  - Language auto-detection failure
  - Presidio service unavailable (health check, error handling)
  - Very long text (performance/timeout)
  - Allow list that suppresses all results (should return `has_pii: false`)

## Files That Matter

- `presidio/presidio-analyzer/app.py` — Presidio's Flask server, defines /analyze endpoint
- `presidio/docs/api-docs/api-docs.yml` — OpenAPI spec for Presidio's API
- `presidio/presidio-analyzer/presidio_analyzer/analyzer_engine.py` — Core analysis logic
- `docs/v1-feature-spec.md` — Feature requirements
- `docs/presidio-integration.md` — Presidio architecture reference

## Documentation Needs

- OpenAPI spec auto-generated by FastAPI — no manual API docs needed
- `CLAUDE.md` should be updated with build/run commands once the project is scaffolded
- `docs/` should include a "getting started" section for enterprise deployment
