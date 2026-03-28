# Research Progress

## RESEARCH-001: PII Detection (Feature 1)

**Status:** Complete — critical review resolved

### Key Decisions Made

- **Backend framework:** FastAPI
- **HTTP client:** httpx (async)
- **Language detection:** lingua-py (more accurate than langdetect on short text)
- **Python version:** 3.12
- **Dependency management:** uv
- **Docker base:** python:3.12-slim
- **Frontend:** HTMX + Jinja2 (served by FastAPI, no separate container)
- **Presidio NLP engine:** spaCy multilingual (`en_core_web_lg` + `de_core_news_lg`)
- **Score threshold:** 0.35 default (Presidio default is 0.0; 0.7 was too aggressive)
- **Allow list:** case-sensitive (Presidio default)
- **Request limits:** 500KB text, 20MB document uploads

### Critical Review Findings — Resolved

1. ~~Transformers model English-only~~ → Switched to spaCy multilingual (EN + DE)
2. ~~Score threshold 0.7 too aggressive~~ → Lowered to 0.35
3. ~~langdetect unreliable on short text~~ → Switched to lingua-py
4. ~~No language validation~~ → Redakt validates against Presidio's supported list before forwarding
5. ~~No startup readiness handling~~ → Added health check probing and depends_on design
6. ~~No request size limits~~ → 500KB text, 20MB documents
7. Allow list case sensitivity → Keeping case-sensitive (user decision)

---

## Planning Phase — COMPLETE

### Specification Finalized

- Document: `SDD/requirements/SPEC-001-pii-detection.md`
- Completion: 2026-03-28
- Status: Approved
- Critical reviews: Research review (2026-03-27) + Spec review (2026-03-28), all findings resolved

### Spec Review Resolutions

- HTMX/API separation: `/api/detect` (JSON) + `/detect/submit` (HTML fragment)
- Audit source: `HX-Request` header determines `web_ui` vs `api`
- Language UX: Three-option toggle (Auto / English / German), single submission
- German model: Upgraded to `de_core_news_lg` for better NER accuracy
- Score threshold 0.0: Explicitly allowed
- Mixed-language text: Documented as known v1 limitation (EDGE-010)
- Logging: Two loggers — `redakt.audit` (JSON, INFO) and `redakt` (WARNING, configurable)

### Specification Summary

- 9 functional requirements (REQ-001–REQ-009)
- 6 non-functional requirements (PERF, SEC, UX)
- 10 edge cases (EDGE-001–EDGE-010)
- 4 failure scenarios (FAIL-001–FAIL-004)
- 17 unit tests + 6 integration tests + 6 manual verification steps
- 20 files to create
- 11-step implementation order

---

## Implementation Phase — READY TO START

### Implementation Priorities

1. Project scaffolding (pyproject.toml, Dockerfile, docker-compose.yml)
2. Presidio client service (services/presidio.py)
3. Language detection service (services/language.py)
4. Config, models, detect router, health router
5. Audit logging service
6. FastAPI app (main.py with lifespan)
7. Web UI (templates + static)
8. Tests

### Critical Implementation Notes

- Custom spaCy config needed: `de_core_news_lg` replaces default `de_core_news_md`
- Presidio default port is 3000 — docker-compose must override to 5001
- Separate HTMX route (`/detect/submit`) from API route (`/api/detect`)
- `HX-Request` header for audit source tagging

### Known Risks

- RISK-001: spaCy NER may be less accurate than transformers for German names. Upgrade path documented.
- RISK-002: lingua-py adds ~30MB to image. Acceptable tradeoff.
- RISK-003: Presidio startup time — mitigated by generous health check config.

### Next Steps

Planning phase complete. Ready for `/implementation-start`.
