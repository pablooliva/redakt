# Critical Review: SPEC-001-pii-detection

**Date:** 2026-03-28
**Reviewing:** `SDD/requirements/SPEC-001-pii-detection.md`
**Overall Severity:** MEDIUM

## Executive Summary

The specification is well-structured and thorough for a v1 feature. It correctly incorporates all critical review findings from the research phase. However, there are several ambiguities that will cause implementation confusion, a Docker configuration nuance that could waste debugging time, a missing edge case around mixed-language text, and the HTMX/API dual-response pattern is underspecified. None of these are blockers — they are clarifications needed to avoid rework during implementation.

## Ambiguities That Will Cause Problems

### 1. REQ-006: How to distinguish `source: "web_ui"` from `source: "api"` — MEDIUM

The spec says audit logs should include `source (web_ui or api)` but doesn't define how the backend distinguishes between them. Both the web UI (via HTMX) and AI agents hit the same `POST /api/detect` endpoint.

- Possible interpretations: (A) Check `Accept` header — HTMX sends `text/html`, agents send `application/json`. (B) Check for a custom header like `X-Redakt-Source`. (C) HTMX uses a separate route (`/detect/submit`) that tags the source internally.
- Recommendation: Use the `Accept` header or `HX-Request` header (HTMX sets this automatically). If `HX-Request: true` is present, source is `web_ui`, otherwise `api`. Simple, no client-side configuration needed.

### 2. HTMX vs JSON dual response pattern — MEDIUM

The implementation notes mention "Use `Accept` header to distinguish, or create a separate `/detect/submit` route for HTMX that returns HTML fragments" but doesn't commit to one approach. This is a key architectural decision that affects routing, templates, and testing.

- Option A (content negotiation): Single endpoint, check `Accept` header, return JSON or HTML fragment. Simpler routing but more complex endpoint logic.
- Option B (separate routes): `/api/detect` returns JSON, `/detect/submit` returns HTML fragment. Cleaner separation but two routes doing similar work.
- Recommendation: Go with Option B. Cleaner separation of concerns, easier to test independently, and the HTMX route can call the API route internally. This also naturally solves the audit `source` distinction — `/api/detect` is always `api`, `/detect/submit` is always `web_ui`.

### 3. REQ-008: UX-001 contradiction with data flow — LOW

UX-001 says "Web UI shows the detected language and allows manual override before submission." But the current data flow submits text → detects language server-side → calls Presidio. This means the user would need to submit twice: once for language detection, then again for PII detection with the confirmed/overridden language.

- Possible interpretations: (A) Single submission — language is detected and PII analyzed in one step, language shown in the results. Override requires resubmission. (B) Two-step — first call detects language only, user confirms/overrides, then second call does PII detection.
- Recommendation: Go with (A) for v1. Show detected language in the results. If the user wants to override, they change the dropdown and resubmit. Simpler implementation, and most users won't need to override.

## Missing Specifications

### 1. Mixed-language text — MEDIUM

The spec handles "auto-detect language" but doesn't address what happens when text contains both German and English. Example: "Please review the Vertrag von Hans Müller, Steuernummer 12/345/67890."

- lingua-py will return one language — likely German due to the German words
- But English PII patterns (email, phone formats) also need to be caught
- Presidio only runs recognizers for the specified language

Why it matters: A user could paste mixed-language content and have English-format PII (like a US phone number) missed because Presidio is told the text is German.

Suggested addition: Document this as a known limitation for v1. Consider running Presidio twice (once per supported language) in a future version, or note that pattern-based recognizers (email, credit card, IBAN) are language-agnostic and still fire regardless of language setting.

### 2. CORS configuration — LOW

The spec doesn't mention CORS. For v1 (same-origin, HTMX served by same backend), this isn't needed. But if AI agents call from different origins or a future browser extension is built, CORS will be needed.

Suggested addition: Note that CORS is not configured in v1 (not needed for same-origin). Add as a future consideration.

### 3. Logging configuration — LOW

REQ-006 specifies audit logging but doesn't define the Python logging setup. Questions: What log level? What logger name? Does the audit logger use a separate handler from application debug logs?

Suggested addition: Audit logs go to a named logger (`redakt.audit`) at `INFO` level with a JSON formatter. Application logs use a separate logger (`redakt`) at `WARNING` level by default (configurable via env var).

## Docker Configuration Clarification Needed

### Presidio default port is 3000, not 5001 — MEDIUM

The spec's docker-compose correctly sets `PORT=5001` via environment variable. But the Presidio Dockerfiles default to `PORT=3000`. The healthcheck inside the Dockerfile also uses `${PORT}` so it will adapt. However:

- The Dockerfiles already include `HEALTHCHECK` instructions. The docker-compose healthcheck definitions will **override** the Dockerfile ones. This is fine but worth noting — if you remove the healthcheck from docker-compose, the Dockerfile defaults (using `${PORT}`) will still work.
- The spec's docker-compose doesn't map Presidio ports to the host (correct — they should stay internal). But for debugging, developers may want to temporarily add `ports: - "5002:5001"`. Worth noting in a developer docs section.

## Research Disconnects

### `de_core_news_md` vs `de_core_news_lg` — LOW

The spaCy multilingual config uses `de_core_news_md` (medium model) for German but `en_core_web_lg` (large model) for English. The large model is more accurate for NER. This is Presidio's default config, not something we chose — but it means German NER accuracy may be slightly lower than English. Worth noting as a known limitation, and the large German model (`de_core_news_lg`) could be swapped in later if needed.

## Edge Cases Still Missing

### EDGE-008: Concurrent requests during Presidio startup

If `depends_on: condition: service_healthy` works correctly, Redakt won't start until Presidio is healthy. But if Presidio becomes temporarily unhealthy after startup (e.g., memory pressure), Redakt should handle this gracefully. FAIL-001 covers "Presidio unavailable" but doesn't specify what happens if Presidio goes down *after* being initially healthy.

- Suggested behavior: Same as FAIL-001 — return 503. The health endpoint should reflect the degraded state.

### EDGE-009: Score threshold of 0.0

A user or agent could set `score_threshold: 0.0` to get every possible detection, including very low-confidence noise. This is valid but could return a large number of results.

- Suggested behavior: Allow it. Document that very low thresholds may produce false positives.

## Risk Reassessment

- RISK-003 (Presidio startup time): Actually **LOWER** severity than stated. The spec uses spaCy, which loads in 10–30 seconds. The `start_period: 30s` plus 10 retries at 10s gives 130 seconds total. This is very generous for spaCy. Risk is minimal.

## Recommended Actions Before Proceeding

| Priority | Action |
|---|---|
| **P1** | Decide on HTMX response pattern: separate routes (recommended) vs content negotiation. Update spec. |
| **P1** | Clarify how `source` is determined in audit logs. |
| **P1** | Clarify language override UX: single submission with override-and-resubmit (recommended). |
| **P2** | Document mixed-language text as a known v1 limitation. |
| **P2** | Add logging configuration details (logger names, levels). |
| **P3** | Note German model is `md` not `lg` as a known limitation. |
| **P3** | Add EDGE-008 (Presidio goes down after startup) and EDGE-009 (score threshold 0.0). |

## Proceed/Hold Decision

**PROCEED.** No blockers found. The P1 items are clarifications that can be resolved quickly during implementation or with a brief spec update. The spec is solid and implementation-ready with these minor additions.
