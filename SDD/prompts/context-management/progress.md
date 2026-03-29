# Research Progress

## RESEARCH-002: Anonymize + Reversible Deanonymization (Feature 2)

**Status:** Research phase COMPLETE. Ready for `/sdd:planning-start`.

### Documents

- Research: `SDD/research/RESEARCH-002-anonymize-deanonymize.md`
- Critical review: `SDD/reviews/CRITICAL-RESEARCH-anonymize-deanonymize-20260328.md`
- Critical review: All 7 findings resolved (2 HIGH, 3 MEDIUM, 2 LOW)

### Key Technical Decisions

1. **Redakt-side text replacement** — not Presidio Anonymizer's `/anonymize` endpoint (API limitation: per-type, not per-entity configs)
2. **In-memory JS variable** for PII mapping (not sessionStorage — XSS/DevTools risk)
3. **Cross-type overlap resolution** — sort by score desc, discard lower-score overlaps, tie-break by longer span
4. **Placeholder key:** (entity_type, text_value) — same value + different type = different placeholders
5. **Counter starts at 1** — more natural for users
6. **Client-side deanonymization:** longest placeholder first to avoid partial match corruption
7. **CSP + SRI** required as browser security headers
8. **HTMX + JS coexistence:** HTMX for server interactions, JS for client-only deanonymization

### Phase Transition

Research phase complete. `RESEARCH-002-anonymize-deanonymize.md` finalized. Ready for `/sdd:planning-start`.

---

## SPEC-002: Planning/Specification Phase

**Status:** APPROVED. Planning phase COMPLETE.

### Documents

- Specification: `SDD/requirements/SPEC-002-anonymize-deanonymize.md`
- Based on: `SDD/research/RESEARCH-002-anonymize-deanonymize.md`
- Research critical review: `SDD/reviews/CRITICAL-RESEARCH-anonymize-deanonymize-20260328.md` (7 findings, all resolved)
- Spec critical review: `SDD/reviews/CRITICAL-SPEC-anonymize-deanonymize-20260328.md` (6 findings, all resolved)

### Specification Summary

- 15 functional requirements (REQ-001 through REQ-015)
- 5 security requirements (SEC-001 through SEC-005)
- 8 edge cases documented with test approaches
- 4 failure scenarios with recovery strategies
- 3 identified risks with mitigations
- Full API contract + Web UI contract defined
- Core algorithms specified (anonymize flow, client-side deanonymize)
- Suggested implementation order (10 steps)
- 9 new files to create, 5 existing files to modify

### Critical Review Resolutions (Spec)

1. CSP inline handler conflict → extract to external `detect.js`, no inline scripts permitted
2. JS testing strategy → manual verification for v1, pure function structure for future testability
3. Web UI routes → full contract added (URLs, form fields, HTMX partial structure, deanonymize UX flow)
4. Overlap boundary → formalized with exclusive `end`, overlap predicate defined
5. Placeholder format → raw Presidio entity type names (`<EMAIL_ADDRESS_1>`, not `<EMAIL_1>`)
6. Score threshold → example fixed to `null`, default documented as config-driven

### Ready For

- `/sdd:implement` to begin coding

---

## Implementation Phase — READY TO START

### Implementation Priorities
1. Backend core: models, anonymizer service, unit tests
2. API endpoint: router, integration tests, audit logging
3. Web UI: templates, HTMX routes, client-side JS
4. Security: CSP middleware, SRI, inline handler migration, cross-feature verification

### Critical Implementation Notes
- Do NOT call Presidio Anonymizer — Redakt does its own text replacement
- Placeholders use raw Presidio entity type names (`<EMAIL_ADDRESS_1>`)
- Overlap resolution before placeholder assignment (predicate: `start_a < end_b AND start_b < end_a`)
- CSP is global — must extract Feature 1's inline handler to `detect.js` first
- Clipboard API needs `document.execCommand('copy')` fallback for HTTP
- Mapping handoff: `data-mappings` attribute on `#anonymize-output`, parsed on `htmx:afterSwap`, then removed from DOM

### Context Management Strategy
- Target: <40% context utilization
- Essential files: 8 existing files (see spec)
- Delegatable: `deanonymize.js`, `detect.js`, test files, security middleware

### Known Risks
- RISK-001: LLM placeholder modification (known v1 limitation)
- RISK-002: Health check semantics (non-blocking, document only)
- RISK-003: Placeholder collision (accepted v1 limitation)

### Phase Transition
Planning phase complete. Implementation phase started 2026-03-28.

---

## Implementation Phase — COMPLETE

### Feature: Anonymize + Reversible Deanonymization (SPEC-002)
- **Specification:** `SDD/requirements/SPEC-002-anonymize-deanonymize.md`
- **Implementation:** `SDD/prompts/PROMPT-002-anonymize-deanonymize-2026-03-28.md`
- **Summary:** `SDD/prompts/implementation-complete/IMPLEMENTATION-SUMMARY-002-2026-03-28_14-30-00.md`
- **Critical Review:** `SDD/reviews/CRITICAL-IMPL-anonymize-deanonymize-20260328.md` (7 findings, all resolved)
- **Completion:** 2026-03-28

### Final Status
- All 15 functional requirements: Implemented
- All 5 security requirements: Validated
- All 2 performance requirements: Met
- All 8 edge cases: Handled
- All 4 failure scenarios: Implemented
- All tests: 90 passing (48 new + 42 pre-existing)
- Critical review: 7 findings, all resolved (1 HIGH, 2 MEDIUM, 4 LOW)

### Implementation Metrics
- Duration: 1 day
- Context management: Maintained <40% throughout
- New files created: 9
- Existing files modified: 7
- Total new lines: ~930

### Files Created
1. `src/redakt/models/anonymize.py` — Pydantic request/response models
2. `src/redakt/services/anonymizer.py` — Core anonymization logic
3. `src/redakt/routers/anonymize.py` — API endpoint + shared function
4. `src/redakt/templates/anonymize.html` — Web UI page
5. `src/redakt/templates/partials/anonymize_results.html` — HTMX partial
6. `src/redakt/static/deanonymize.js` — Client-side deanonymize + copy
7. `src/redakt/static/detect.js` — Extracted Feature 1 inline handler
8. `tests/test_anonymizer_service.py` — 25 unit tests
9. `tests/test_anonymize_api.py` — 15 integration tests

### Manual Browser Verification (pending)
- [ ] Full anonymize -> copy -> LLM -> paste -> deanonymize flow
- [ ] Copy-to-clipboard on localhost
- [ ] CSP compliance in browser (no console errors)
- [ ] Feature 1 detect page works under CSP

---

## Phase Transition

Implementation phase COMPLETE for Anonymize + Reversible Deanonymization (Feature 2).

To start next feature:
- Research new feature: `/sdd:research-start`
- Plan another feature: `/sdd:planning-start` (if research exists)
- Implement another feature: `/sdd:implementation-start` (if spec exists)

---

## RESEARCH-003: Document Support — Excel + PDF (Feature 3)

**Status:** Research phase COMPLETE. Ready for `/sdd:planning-start`.

### Documents

- Research: `SDD/research/RESEARCH-003-document-support.md`

### Key Technical Decisions

1. **Cannot use `presidio-structured`** — It's a Python library (imports `AnalyzerEngine` directly), not a REST API. Redakt must use its own cell-by-cell extraction + existing REST-based anonymization pipeline.
2. **All output as JSON/text for v1** — No same-format file downloads. Avoids complexity of multipart responses and file reconstruction. Same-format download deferred to v2.
3. **PDF: pdfminer.six** — Pure Python, MIT license, used by Presidio's own examples. No OCR for v1 (text-based PDFs only).
4. **Excel: openpyxl** — Cell-by-cell processing, skip formulas/numbers, process all sheets.
5. **DOCX/RTF: extracted text only** — No formatting preservation for v1.
6. **Analyze-first strategy** — Collect all text chunks from document, analyze each via Presidio REST, generate unified mapping across all chunks, then apply replacement. Ensures consistent placeholder numbering.
7. **File size limit: 10MB** — Configurable via `REDAKT_MAX_FILE_SIZE`. In-memory processing.
8. **Security: defusedxml** — Required for XML/HTML/DOCX/XLSX to prevent XXE and billion laughs attacks.
9. **Audit logging** — Log file type, size, entity counts. NEVER log filenames or content.
10. **6 new dependencies** — pdfminer.six, openpyxl, python-docx, striprtf, beautifulsoup4, defusedxml (all MIT/BSD/PSF).

### File Impact

- **New files:** 6 source files, 4 test files, 1 template, 1 partial, ~6 test fixtures
- **Modified files:** main.py (router), config.py (settings), audit.py (new log function), pyproject.toml (deps), possibly anonymizer.py (shared mapping support)

### Phase Transition

Research phase complete 2026-03-29. Ready for `/sdd:planning-start`.

---

Research phase complete. RESEARCH-003-document-support.md finalized. Ready for /planning-start.

---

## RESEARCH-003 Critical Review Resolution — 2026-03-29

**Status:** All findings resolved. Research document updated and ready for `/sdd:planning-start`.

### Review Document
- `SDD/reviews/CRITICAL-RESEARCH-document-support-20260329.md` — 7 critical gaps + 5 questionable assumptions + 4 missing perspectives, ALL resolved

### Key Changes to Research Document
1. **Multi-chunk pipeline fully designed** — New `build_unified_placeholder_map()` function with signature and implementation. Three-phase pipeline (analyze-all → unified map → per-chunk replace). Existing `anonymizer.py` functions require NO modifications.
2. **`run_anonymization()` reuse clarified** — NOT called per-chunk. Document processor calls `presidio.analyze()` directly. Integration Points and data flow diagram corrected.
3. **Presidio throughput analyzed** — Bounded async concurrency (`Semaphore(10)` + `asyncio.gather`) recommended. 2000 cells in ~4-8s.
4. **Encoding detection strategy added** — `charset-normalizer` library with UTF-8-first fallback chain.
5. **Memory amplification analyzed** — Peak 100-150MB per request for large XLSX. Container sizing guidance added.
6. **ZIP bomb protection specified** — Pre-check ZIP manifest total uncompressed size before parsing.
7. **defusedxml coverage verified** — `defuse_stdlib()` at startup, lxml caveat noted, verification test recommended.
8. **JSON-only output revised** — CSV returns native CSV text, XLSX JSON limitation acknowledged with UX tradeoff.
9. **Language detection strategy** — Once per document, not per chunk.
10. **Missing perspectives added** — InfoSec, Enterprise IT, Accessibility/UX, Data Engineering subsections.

---

## SPEC-003: Planning/Specification Phase

**Status:** Draft. Ready for critical review.

### Documents

- Specification: `SDD/requirements/SPEC-003-document-support.md`
- Based on: `SDD/research/RESEARCH-003-document-support.md`
- Research critical review: `SDD/reviews/CRITICAL-RESEARCH-document-support-20260329.md` (all findings resolved)

### Specification Summary

- 20 functional requirements (REQ-001 through REQ-020)
- 8 security requirements (SEC-001 through SEC-008)
- 3 performance requirements (PERF-001 through PERF-003)
- 4 UX requirements (UX-001 through UX-004)
- 14 edge cases documented with test approaches (EDGE-001 through EDGE-014)
- 8 failure scenarios with recovery strategies (FAIL-001 through FAIL-008)
- 5 identified risks with mitigations (RISK-001 through RISK-005)
- Full API contract (REST + Web UI) defined
- Core algorithm: three-phase document processing pipeline specified
- Suggested implementation order (8 steps)
- 16 new files to create, 6 existing files to modify
- 7 new Python dependencies (all MIT/BSD/PSF, pure Python)

### Key Design Decisions Captured

1. Three-phase pipeline: extract → analyze all chunks concurrently → unified placeholder map → per-chunk replacement
2. New `build_unified_placeholder_map()` function (NOT reusing `generate_placeholders()`)
3. JSON response for all formats in v1 (no same-format file output)
4. Bounded async concurrency: `Semaphore(10)` + `asyncio.gather`
5. Per-document language detection (not per-chunk)
6. `anonymizer.py` requires NO modifications
7. `defusedxml.defuse_stdlib()` at startup for XML attack prevention
8. Extension whitelist + magic bytes for file validation
9. 10MB file size limit, 120s processing timeout
10. CSV returns native CSV text; XLSX returns structured JSON (v1 limitation)

### Ready For

- Critical review of specification
- Then `/sdd:implement` to begin coding

---

Planning phase validation complete. SPEC-003-document-support.md finalized.

---

## SPEC-003 Critical Review Resolution — 2026-03-29

**Status:** All findings resolved. Spec updated and ready for implementation.

### Review Document
- `SDD/reviews/CRITICAL-SPEC-document-support-20260329.md` — 3 HIGH, 8 MEDIUM, 6 LOW findings, ALL resolved

### Key Spec Changes
1. **REQ-013 language detection** -- Resolved ambiguity: concatenate first N chunks up to 5KB, not "longest chunk or first 5KB"
2. **EDGE-013 oversized chunks** -- Skip with `[CONTENT TOO LARGE - SKIPPED]` placeholder, no PII leakage
3. **SEC-003/RISK-005 lxml gap** -- Confirmed python-docx requires lxml, defuse_stdlib() doesn't cover it. Added XXE verification test requirement and fallback mitigation
4. **RISK-003 memory/OOM** -- Added server-side concurrency semaphore (PERF-004, FAIL-009), 429 response
5. **RISK-002 short cells** -- Upgraded to HIGH, added user-facing warning in UX-004
6. **CSV output** -- Specified delimiter, quoting, line terminator; added API contract example
7. **HTMX rendering** -- Specified per-format strategy (table for XLSX, pre/code for JSON, pre for text)
8. **5 new edge cases** -- EDGE-015 (XLSX row bounds), EDGE-016 (HTML data URIs), EDGE-017 (DOCX tracked changes), EDGE-018 (RTF OLE), EDGE-019 (CSV delimiter override deferred to v2)
9. **Multipart form serialization** -- Documented comma-separated format, empty-string handling
10. **New UX-005** -- Client-side file size pre-validation

### Ready For
- `/sdd:implement` to begin coding

---

## Implementation Phase — COMPLETE

### Feature: Document Support (SPEC-003)
- **Specification:** `SDD/requirements/SPEC-003-document-support.md`
- **Implementation:** `SDD/prompts/PROMPT-003-document-support-2026-03-29.md`
- **Completion:** 2026-03-29

### Final Status
- All 20 functional requirements: Implemented
- All 8 security requirements: Validated
- All 4 performance requirements: Met
- All 5 UX requirements: Implemented
- All applicable edge cases: Handled
- All 9 failure scenarios: Implemented
- All tests: 174 passing (84 new + 90 pre-existing)

### Implementation Metrics
- New files created: 11
- Existing files modified: 7
- New dependencies: 7 (pdfminer.six, openpyxl, python-docx, striprtf, beautifulsoup4, defusedxml, charset-normalizer)

### Files Created
1. `src/redakt/models/document.py` -- Pydantic response models
2. `src/redakt/services/extractors.py` -- 10 format-specific extractors
3. `src/redakt/services/document_processor.py` -- Processing pipeline + unified placeholder map
4. `src/redakt/routers/documents.py` -- API endpoint with concurrency control
5. `src/redakt/templates/documents.html` -- Web UI upload page
6. `src/redakt/templates/partials/document_results.html` -- HTMX results partial
7. `src/redakt/static/document-upload.js` -- Client-side file size validation
8. `src/redakt/static/deanonymize-documents.js` -- Client-side deanonymize for documents
9. `tests/test_extractors.py` -- 36 extractor unit tests
10. `tests/test_document_processor.py` -- 16 processor unit tests
11. `tests/test_documents_api.py` -- 17 API integration tests

### Key Architecture Decisions
- defusedxml.defuse_stdlib() at app startup (main.py, before any XML imports)
- Three-phase pipeline: analyze all chunks -> unified map -> per-chunk replace
- build_unified_placeholder_map() replaces generate_placeholders() for documents
- anonymizer.py unmodified (resolve_overlaps + replace_entities reused)
- Lazy imports for openpyxl/python-docx (after defuse_stdlib)
- External JS files (no inline scripts, CSP compliant)

### Phase Transition
Implementation phase COMPLETE for Document Support (Feature 3).
E2E tests to be created separately per CLAUDE.md guidelines.

---

## Implementation Phase — COMPLETE (Finalized)

### Feature: Document Support (SPEC-003)
- **Specification:** `SDD/requirements/SPEC-003-document-support.md`
- **Implementation Tracking:** `SDD/prompts/PROMPT-003-document-support-2026-03-29.md`
- **Implementation Summary:** `SDD/prompts/implementation-complete/IMPLEMENTATION-SUMMARY-003-2026-03-29_15-00-00.md`
- **Code Review:** `SDD/reviews/REVIEW-003-document-support-20260329.md` -- APPROVED
- **Critical Review:** `SDD/reviews/CRITICAL-IMPL-document-support-20260329.md` -- All 10 findings resolved
- **Completion:** 2026-03-29

### Final Validated Status
- All 20 functional requirements (REQ-001 through REQ-020): Complete
- All 8 security requirements (SEC-001 through SEC-008): Validated
- All 4 performance requirements (PERF-001 through PERF-004): Met
- All 5 UX requirements (UX-001 through UX-005): Implemented
- All 15 applicable edge cases (EDGE-001 through EDGE-015): Handled
- All 9 failure scenarios (FAIL-001 through FAIL-009): Implemented
- All tests: 189 passing (99 new + 90 pre-existing)

### Review Summary
- Code review: APPROVED with 7 observations, all resolved
- Critical review: 2 HIGH, 5 MEDIUM, 3 LOW findings -- all 10 resolved
- Key fixes: XSS prevention (tojson filter), shared upload semaphore, XLSX copy, JSON depth limit

### Implementation Metrics
- New files created: 11
- Existing files modified: 7
- New dependencies: 7 (pdfminer.six, openpyxl, python-docx, striprtf, beautifulsoup4, defusedxml, charset-normalizer)
- New source lines: ~1,553
- New test lines: ~1,340

### Deviations from Spec
1. Model file named `document.py` (singular) instead of `documents.py` -- no functional impact
2. Test fixtures created inline instead of `tests/fixtures/` files -- self-contained tests
3. E2E tests deferred to separate task per CLAUDE.md guidelines
4. Test count exceeded estimates: 84 new tests vs ~57 estimated (additional edge case coverage)

---

## Current State

- Last compaction: `compact-2026-03-29_13-57-15.md`
- Working on: Feature 3 E2E tests — written but not yet run or committed
- E2E test file: `tests/e2e/test_documents_e2e.py` (20 Playwright tests)
- Next step: Run E2E tests against Docker Compose stack, fix failures, commit

---

## RESEARCH-004: Language Auto-Detection with Manual Override (Feature 4)

**Status:** Research phase COMPLETE. Ready for `/sdd:planning-start`.

### Documents

- Research: `SDD/research/RESEARCH-004-language-detection.md`
- Research critical review: `SDD/reviews/CRITICAL-RESEARCH-language-detection-20260329.md` (all findings resolved)

### Key Finding

Feature 4 is **already substantially implemented** as part of Features 1-3. The `lingua-language-detector` library is integrated, all endpoints accept `"language": "auto"`, all UI pages have auto/en/de toggles, and all responses include `language_detected`. Remaining work is incremental.

### Existing Implementation

1. **Language service**: `src/redakt/services/language.py` -- Lingua detector (EN+DE), async with 2s timeout, fallback to "en"
2. **Config**: `supported_languages: ["en", "de"]`, `default_language: "auto"`, `language_detection_timeout: 2.0`
3. **All routers**: Resolve "auto" -> detect, validate against supported list, pass to Presidio
4. **All models**: Accept `language` input (default "auto"), return `language_detected`
5. **All templates**: Radio toggle groups (auto/en/de)
6. **All result partials**: Display detected language
7. **Document pipeline**: Per-document detection (5KB sample from first chunks)
8. **Tests**: 6 unit tests in `test_language.py`, language tested in integration tests

### Identified Gaps (5)

1. **Mixed-language strategy** -- Spec open question. Recommend: document as v1 limitation (dominant language used, regex recognizers are language-agnostic)
2. **Detection confidence feedback** -- No confidence score returned. Lingua supports it. Low-effort enhancement.
3. **Full-text vs. sample** -- Already decided: full text for text endpoints, 5KB for documents. No change needed.
4. **Spanish support** -- Presidio config includes `es_core_news_md` but Redakt restricts to EN+DE. Defer to post-v1.
5. **Test coverage gaps** -- Need to verify/add: mixed-language tests, unsupported language 400 tests, E2E toggle tests

### Recommendation

SPEC-004 should be a verification/gap-fill exercise. Minimal implementation needed -- primarily test additions and possibly a confidence score enhancement.

### Phase Transition

Research phase complete. RESEARCH-004-language-detection.md finalized. Ready for /planning-start.

---

## SPEC-004: Planning/Specification Phase

**Status:** APPROVED. Planning phase COMPLETE.

### Documents
- Specification: `SDD/requirements/SPEC-004-language-detection.md`
- Based on: `SDD/research/RESEARCH-004-language-detection.md`
- Spec critical review: `SDD/reviews/CRITICAL-SPEC-language-detection-20260329.md` (all findings resolved)

### Ready For
- `/sdd:implement` to begin coding

---

## RESEARCH-004 Critical Review Resolution -- 2026-03-29

**Status:** All findings resolved. Research document updated and ready for `/sdd:planning-start`.

### Review Document
- `SDD/reviews/CRITICAL-RESEARCH-language-detection-20260329.md` -- 3 HIGH, 4 MEDIUM, 2 LOW findings + 5 questionable assumptions + 4 missing perspectives, ALL resolved

### Key Changes to Research Document
1. **Hardcoded language list coupling documented** (HIGH) -- Added as Gap 1. Dynamic detector building recommended. Startup validation alternative specified.
2. **Port discrepancy corrected** (HIGH) -- External Dependencies table fixed. Analyzer uses internal port 5001 in Redakt docker-compose, not 5002. Explanatory note added.
3. **GDPR impact analysis added** (HIGH) -- New subsection under "What Happens with Wrong Language" quantifying risk for PERSON/LOCATION/ORGANIZATION NER categories. Empirical accuracy testing required before SPEC-004 finalization.
4. **English fallback bias addressed** (HIGH) -- Added as Gap 2. `settings.default_language` confirmed NOT wired into `language.py` fallback paths. Configurable fallback recommended.
5. **Exception handling weakness documented** (MEDIUM) -- New edge case section. Three specific fixes recommended (log details, separate timeout/error handling, observability).
6. **lru_cache constraint documented** (MEDIUM) -- Added to Lingua library analysis table.
7. **5KB sampling limitation expanded** (MEDIUM) -- Document Language Detection edge case updated with concrete examples of failure modes.
8. **Line number errors fixed** -- `audit.py:59,68,79` -> `56,65,74`. `document_processor.py:184` -> `179`. `133-168` -> `133-172`.
9. **Questionable assumptions qualified** -- "Best-in-class" -> "Strong short-text accuracy" with citation. "Already tuned" -> "reasonable starting point, not empirically validated". "Functionally complete" -> "core infrastructure in place" with gaps.
10. **Missing perspectives added** -- DPO/Legal, Security/PenTest, Operations/SRE stakeholder sections added.
11. **Architectural Recommendation reframed** -- From "minimal work" to "more work than initially estimated" with prioritized action items.

---

## Implementation Phase -- COMPLETE

### Feature: Language Auto-Detection with Manual Override (SPEC-004)
- **Specification:** `SDD/requirements/SPEC-004-language-detection.md`
- **Implementation Tracking:** `SDD/prompts/PROMPT-004-language-detection-2026-03-29.md`
- **Completion:** 2026-03-29

### Final Status
- All 17 functional requirements (REQ-001 through REQ-017): Implemented
- All 2 security requirements (SEC-001, SEC-002): Validated
- Performance requirement (PERF-001): Met
- All 10 edge cases: Handled
- All 4 failure scenarios: Documented
- All tests: 210 passing (21 new + 189 pre-existing)

### Implementation Summary
This was a hardening exercise on existing language detection infrastructure:
1. **Dynamic detector building** -- `_build_detector()` now reads from `settings.supported_languages` via `ISO_TO_LINGUA` mapping
2. **Configurable fallback** -- New `language_detection_fallback` setting replaces all hardcoded `"en"` fallbacks
3. **Startup validation** -- `validate_language_config()` called from FastAPI lifespan handler; rejects unknown codes or fallback not in supported list
4. **Confidence scores** -- `language_confidence: float | None` added to all API responses; Lingua's `compute_language_confidence_values()` used for auto-detect
5. **Improved logging** -- Timeout at WARNING, other exceptions at ERROR with `exc_info=True`; structured log fields per SEC-001
6. **Template confidence labels** -- High/Medium/Low/None labels in all result partials; omitted for manual override
7. **LanguageDetection NamedTuple** -- Clean return type supporting both named access and tuple unpacking
8. **Empty text handling** -- Returns `language_detection_fallback` instead of `"unknown"` (EDGE-003)

### Files Modified: 14 source + 7 test files
### Files Created: 2 (E2E test file, PROMPT tracking)
### Test Count: 213 (was 189, +24 new)

### Code Review
- **Decision:** APPROVED (95.5%)
- All requirements verified across functional, security, performance, and UX categories

### Critical Review
- 3 HIGH, 5 MEDIUM, 4 LOW findings -- all 12 resolved
- Key fixes applied during implementation

### Implementation Summary
- `SDD/prompts/implementation-complete/IMPLEMENTATION-SUMMARY-004-2026-03-29_18-00-00.md`

### Phase Transition
Implementation phase COMPLETE for Language Auto-Detection with Manual Override (SPEC-004).

To start next feature:
- Research new feature: `/sdd:research-start`
- Plan another feature: `/sdd:planning-start` (if research exists)
- Implement another feature: `/sdd:implementation-start` (if spec exists)

---

## RESEARCH-005: Allow Lists (Feature 5)

**Status:** Research phase COMPLETE. Ready for `/sdd:planning-start`.

### Documents

- Research: `SDD/research/RESEARCH-005-allow-lists.md`

### Key Finding

Feature 5 is **already substantially implemented** on the backend/API side. The `allow_list` config setting, Pydantic model fields, merge logic, Presidio client passthrough, and tests all exist. The primary gaps are in the **web UI** (no allow_list input in any of the 3 forms or page handlers).

### Existing Implementation

1. **Config**: `src/redakt/config.py:16` -- `allow_list: list[str] = []` with `REDAKT_` env prefix
2. **Models**: `models/detect.py:9` and `models/anonymize.py:9` -- `allow_list: list[str] | None`
3. **API routes**: Detect, Anonymize, Documents -- all accept and merge allow_list
4. **Presidio client**: `services/presidio.py:19-29` -- passes allow_list to Presidio's `/analyze`
5. **Document processor**: `services/document_processor.py:239-240` -- merge logic for documents
6. **Tests**: 4 test files cover allow_list merge behavior

### Identified Gaps (6)

1. **Web UI forms** -- None of the 3 templates (detect.html, anonymize.html, documents.html) have allow_list input
2. **Web UI handlers** -- `pages.py` submit handlers don't accept or pass allow_list
3. **Instance-wide terms display** -- No UI visibility into pre-configured terms
4. **Input validation** -- No limits on term count, length, or character filtering
5. **Shared merge utility** -- Merge logic duplicated in 3 places (detect, anonymize, document_processor)
6. **Case sensitivity** -- Presidio's exact match is case-sensitive; may surprise users

### Open Questions Resolved

1. **Storage**: Env var (`REDAKT_ALLOW_LIST`) via pydantic-settings -- already implemented, sufficient for v1
2. **Admin UI**: No dedicated admin UI for v1 -- read-only display of instance-wide terms in web UI
3. **Regex support**: Exact match only for v1 -- Presidio supports regex via `allow_list_match` but adds complexity

### Scope Assessment

Small-to-medium feature. Backend plumbing is done. Primary work is UI additions, pages.py updates, input validation, shared utility extraction, and tests.

### Phase Transition

Research phase complete 2026-03-29. RESEARCH-005-allow-lists.md finalized. Ready for `/sdd:planning-start`.

---

Research phase complete. RESEARCH-005-allow-lists.md finalized. Ready for /planning-start.

---

## RESEARCH-005 Critical Review Resolution — 2026-03-29

**Status:** All findings resolved. Research document updated and ready for /planning-start.

### Review Document
- `SDD/reviews/CRITICAL-RESEARCH-allow-lists-20260329.md` — 17 findings (2 HIGH, 3 MEDIUM critical gaps + 5 factual errors + 5 questionable assumptions + 4 missing perspectives), ALL resolved

### Key Changes to Research Document
1. **Regex matching corrected** (HIGH) — Changed `re.fullmatch()` to `re.search()` throughout; documented partial-match implications
2. **Port discrepancy documented** (HIGH) — Added explanatory note about docker-compose `PORT=5001` override vs CLAUDE.md's 5002
3. **Score threshold interaction added** (MEDIUM) — New subsection documenting filtering order and implications
4. **Language detection interaction added** (MEDIUM) — New subsection on language-dependent NER and allow list effectiveness
5. **DoS/abuse analysis added** (MEDIUM) — Input validation promoted to hard v1 requirement with specific limits (100 terms, 200 chars)
6. **Web UI gap clarified** (LOW) — Instance-wide allow list already works for web UI; gap is per-request terms only
7. **XSS claim qualified** — "No XSS risk" replaced with conditional safety statement (Jinja2 auto-escaping)
8. **PII assertion softened** — "NOT PII" changed to "typically not PII" with sensitivity guidance
9. **4 missing perspectives added** — Enterprise IT/Ops, Non-English users, Compliance/Legal, QA/Testing
10. **Performance analysis added** — O(n) list scan documented for exact mode; O(n*m) DoS risk quantified

---

## SPEC-005: Planning/Specification Phase

**Status:** Draft. Ready for critical review.

### Documents

- Specification: `SDD/requirements/SPEC-005-allow-lists.md`
- Based on: `SDD/research/RESEARCH-005-allow-lists.md`
- Research critical review: `SDD/reviews/CRITICAL-RESEARCH-allow-lists-20260329.md` (all findings resolved)

### Specification Summary

- 12 functional requirements (REQ-001 through REQ-012)
- 3 performance/security UX requirements (PERF-001/002, SEC-001/002/003, UX-001/002)
- 11 edge cases documented with test approaches (EDGE-001 through EDGE-011)
- 4 failure scenarios with recovery strategies (FAIL-001 through FAIL-004)
- 4 identified risks with mitigations (RISK-001 through RISK-004)
- Full API contract + Web UI contract defined
- Suggested implementation order (8 steps)
- 6 new files to create, 8 existing files to modify

### Key Design Decisions Captured

1. Shared `merge_allow_lists()` utility replaces 3 duplicated merge blocks
2. `parse_allow_list()` for comma-separated web UI input (consistent with existing `_parse_comma_separated()`)
3. Input validation: 100 terms max, 200 chars per term, strip whitespace, reject empty (hard v1 requirement)
4. Audit logging: `allow_list_count` metadata only, never log term values
5. Instance-wide terms displayed as read-only tags via shared Jinja2 partial
6. Case-sensitive exact match for v1 (documented limitation, helper text in UI)
7. No regex support, no admin UI for v1
8. Deduplication on merge (set-based union semantics)

### Scope Assessment

Small-to-medium feature. Backend allow_list plumbing is fully implemented. Primary work:
- New shared utility module (`utils.py`) with parse/validate/merge functions
- 3 template updates (add allow_list input + instance terms display)
- 3 pages.py handler updates (accept and pass allow_list)
- 3 router/processor updates (replace duplicated merge logic)
- Audit logging enhancement (add allow_list_count)
- ~27 new unit/integration tests + ~8 E2E tests

### Ready For

- Critical review of specification
- Then `/sdd:implement` to begin coding

Planning phase validation complete. SPEC-005-allow-lists.md finalized.

---

## SPEC-005 Critical Review Resolution — 2026-03-29

**Status:** All findings resolved. Spec updated and ready for implementation.

### Review Document
- `SDD/reviews/CRITICAL-SPEC-allow-lists-20260329.md` — 12 findings, ALL resolved

### Key Spec Changes
- Validation placement unified: `validate_allow_list()` called inside `run_detection()`/`run_anonymization()`/`process_document()` before merge (single validation point for API + web UI)
- Validation is explicitly fail-closed (reject entire request, no truncation)
- `dict.fromkeys()` replaces set operations for order-preserving dedup (resolves PERF-002/REQ-007/EDGE-005 contradiction)
- `merge_allow_lists()` returns `None` for empty (not `[]`), callers pass directly without `or None`
- `_parse_comma_separated()` dual-use resolved: generic parser + allow-list-specific wrapper with validation
- Case-insensitive deferral justified with technical rationale (Presidio architecture constraints)
- Audit `allow_list_count` specified as total merged count with rationale
- Instance-wide terms: startup warning at 500+ terms, uncapped but admin-trusted
- EDGE-012 + RISK-005/006 added (comma-containing terms, dual-use parser risk)
- Accessibility: `aria-describedby`, `role="group"`, per-term `aria-label`
- Unicode test examples fixed to actual Unicode characters
- Helper text placement: input first, instance terms below
- Regex mode post-v1 note with `re.search()` partial-match warning
- Secrets management gap noted in RISK-003

---

## Implementation Phase -- COMPLETE

### Feature: Allow Lists (SPEC-005)
- **Specification:** `SDD/requirements/SPEC-005-allow-lists.md`
- **Implementation Tracking:** `SDD/prompts/PROMPT-005-allow-lists-2026-03-29.md`
- **Completion:** 2026-03-29

### Final Status
- All 12 functional requirements (REQ-001 through REQ-012): Implemented
- All security requirements (SEC-001 through SEC-003): Validated
- Performance requirements (PERF-001, PERF-002): Met
- UX requirements (UX-001, UX-002): Implemented
- All 12 edge cases: Handled
- All 4 failure scenarios: Implemented
- All tests: 276 passing (63 new + 213 pre-existing)

### Implementation Summary
1. **Shared utility module** (`src/redakt/utils.py`) -- `parse_comma_separated()`, `parse_allow_list()`, `validate_allow_list()`, `merge_allow_lists()`, `validate_instance_allow_list()`
2. **Replaced duplicated merge logic** -- 3 routers/processors now use `merge_allow_lists()` with order-preserving dedup via `dict.fromkeys()`
3. **Input validation** -- Fail-closed validation (100 terms max, 200 chars max) inside `run_detection()`, `run_anonymization()`, `process_document()` before merge -- covers both API and web UI paths
4. **Web UI allow_list input** -- Shared partial `allow_list_input.html` included in all 3 templates (detect, anonymize, documents)
5. **Instance-wide terms display** -- Read-only tags via `allow_list_instance_terms.html` partial, Jinja2 auto-escaped
6. **Pages.py handlers updated** -- All 3 GET handlers pass `instance_allow_list`, all 3 POST handlers accept `allow_list: str = Form("")` and parse/validate
7. **Audit logging** -- `allow_list_count` (total merged count) added to all 3 audit functions; never logs term values
8. **Startup validation** -- `validate_instance_allow_list()` called from FastAPI lifespan handler

### Files Created: 6 source + test files
### Files Modified: 11

### Critical Review Findings Addressed (2026-03-29)

Resolved all HIGH/MEDIUM findings and most LOW findings from `SDD/reviews/CRITICAL-IMPL-allow-lists-20260329.md`:

1. **[HIGH] FIXED:** `validate_instance_allow_list()` now returns a cleaned list with empty strings stripped (FAIL-002 compliance). Lifespan handler stores cleaned list.
2. **[HIGH] FIXED:** `_build_empty_response` early-return path now includes `allow_list_count` in result for accurate audit logging.
3. **[MEDIUM] FIXED:** Added documents web submit integration test with allow list pass-through.
4. **[MEDIUM] FIXED:** Added tests for empty document + allow list early-return path (per-request only and instance + per-request).
5. **[LOW] FIXED:** Strengthened E2E anonymize assertion.
6. **[LOW] FIXED:** Added `maxlength="21100"` to HTML input.
7. **[LOW] DEFERRED:** `_parse_comma_separated` duplication -- spec explicitly allows keeping both (Note #6).
8. **[LOW] FIXED:** Added EDGE-002 (partial match) and EDGE-010 (cross-language) integration tests.

All tests passing: 281 passed, 0 failed.

### Phase Transition
Implementation phase COMPLETE for Allow Lists (Feature 5).

To start next feature:
- Research new feature: `/sdd:research-start`
- Plan another feature: `/sdd:planning-start` (if research exists)
- Implement another feature: `/sdd:implementation-start` (if spec exists)

---

## Implementation Phase — COMPLETE

### Feature: Allow Lists (SPEC-005)
- Specification: SDD/requirements/SPEC-005-allow-lists.md
- Implementation: SDD/prompts/PROMPT-005-allow-lists-2026-03-29.md
- Summary: SDD/prompts/implementation-complete/IMPLEMENTATION-SUMMARY-005-2026-03-29_20-00-00.md
- Code Review: SDD/reviews/REVIEW-005-allow-lists-20260329.md — APPROVED
- Critical Review: SDD/reviews/CRITICAL-IMPL-allow-lists-20260329.md — All findings resolved
- Completion: 2026-03-29

### Final Status
- All 12 functional requirements: Implemented
- All security requirements: Validated
- All performance requirements: Met
- All UX requirements: Implemented
- All edge cases: Handled
- All failure scenarios: Implemented
- All tests: 281 passing (68 new + 213 pre-existing)
