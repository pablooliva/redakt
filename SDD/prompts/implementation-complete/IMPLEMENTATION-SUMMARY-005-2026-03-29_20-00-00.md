# Implementation Summary: SPEC-005 Allow Lists

- **Feature:** Allow Lists
- **Spec:** `SDD/requirements/SPEC-005-allow-lists.md`
- **Research:** `SDD/research/RESEARCH-005-allow-lists.md`
- **Implementation Tracking:** `SDD/prompts/PROMPT-005-allow-lists-2026-03-29.md`
- **Code Review:** `SDD/reviews/REVIEW-005-allow-lists-20260329.md` -- APPROVED
- **Critical Review:** `SDD/reviews/CRITICAL-IMPL-allow-lists-20260329.md` -- All findings resolved
- **Completion Date:** 2026-03-29

## Feature Overview

Allow Lists enables web UI users to specify per-request terms that should not be flagged as PII, provides visibility into instance-wide pre-configured terms, adds input validation to prevent abuse, consolidates duplicated merge logic into a shared utility, and tracks allow list usage in audit logs.

The backend allow_list infrastructure was already fully functional for API consumers (Features 1-3). This feature closed the web UI gap and added validation, DRY refactoring, and audit metadata.

## Requirements Completion Matrix

### Functional Requirements (REQ)

| ID | Description | Status |
|----|-------------|--------|
| REQ-001 | Allow list text input on all 3 web UI forms | Complete |
| REQ-002 | detect_submit handler accepts and passes allow_list | Complete |
| REQ-003 | anonymize_submit handler accepts and passes allow_list | Complete |
| REQ-004 | documents_submit handler accepts and passes allow_list | Complete |
| REQ-005 | Instance-wide terms displayed as read-only tags | Complete |
| REQ-006 | Shared merge_allow_lists() utility replaces duplicated logic | Complete |
| REQ-007 | Order-preserving deduplication via dict.fromkeys() | Complete |
| REQ-008 | Whitespace stripping on per-request terms | Complete |
| REQ-009 | Empty strings silently removed | Complete |
| REQ-010 | Audit logging includes allow_list_count (never term values) | Complete |
| REQ-011 | No regression when no per-request allow list provided | Complete |
| REQ-012 | Helper text with case-sensitivity and comma limitation notes | Complete |

### Performance Requirements (PERF)

| ID | Description | Status |
|----|-------------|--------|
| PERF-001 | Input validation: max 100 terms, max 200 chars/term, startup warning at 500+ | Complete |
| PERF-002 | O(n) merge via dict.fromkeys() | Complete |

### Security Requirements (SEC)

| ID | Description | Status |
|----|-------------|--------|
| SEC-001 | Jinja2 auto-escaping on all allow list term rendering (no \|safe) | Complete |
| SEC-002 | Term values never logged in audit, app logs, or error responses | Complete |
| SEC-003 | Validation on both API and web UI paths (defense in depth) | Complete |

### UX Requirements (UX)

| ID | Description | Status |
|----|-------------|--------|
| UX-001 | Instance-wide terms visually distinct (read-only styling) | Complete |
| UX-002 | Clear validation error messages identifying specific violation | Complete |

### Edge Cases (EDGE)

| ID | Description | Status |
|----|-------------|--------|
| EDGE-001 | Case sensitivity documented as v1 limitation | Complete |
| EDGE-002 | Partial entity match ("John" vs "John Smith") | Complete |
| EDGE-003 | Empty strings in allow list | Complete |
| EDGE-004 | Unicode and special characters | Complete |
| EDGE-005 | Duplicate terms across instance and per-request | Complete |
| EDGE-006 | Comma-separated parsing edge cases | Complete |
| EDGE-007 | Maximum term count exceeded | Complete |
| EDGE-008 | Term exceeding maximum length | Complete |
| EDGE-009 | Regex special characters in exact mode | Complete |
| EDGE-010 | Language-dependent allow list behavior | Complete |
| EDGE-011 | Allow list terms near score threshold | Complete |
| EDGE-012 | Comma-containing terms in web UI | Complete |

### Failure Scenarios (FAIL)

| ID | Description | Status |
|----|-------------|--------|
| FAIL-001 | Validation error on per-request terms (fail-closed) | Complete |
| FAIL-002 | Instance-wide allow list invalid terms at startup | Complete |
| FAIL-003 | Presidio service unavailable with allow list | Complete |
| FAIL-004 | XSS attempt via allow list terms | Complete |

## Implementation Artifacts

### Files Created

| File | Purpose |
|------|---------|
| `src/redakt/utils.py` | Shared utility: parse_comma_separated, parse_allow_list, validate_allow_list, merge_allow_lists, validate_instance_allow_list |
| `src/redakt/templates/partials/allow_list_input.html` | Shared partial for allow list form group |
| `src/redakt/templates/partials/allow_list_instance_terms.html` | Instance-wide terms display as read-only tags |
| `tests/test_allow_list_utils.py` | 37 unit tests for utility functions |
| `tests/test_allow_list_web.py` | 26 integration tests for web UI + API + audit (+ 5 from critical review) |
| `tests/e2e/test_allow_list_e2e.py` | 8 E2E Playwright tests |

### Files Modified

| File | Changes |
|------|---------|
| `src/redakt/routers/detect.py` | Use shared merge/validate, add allow_list_count to result |
| `src/redakt/routers/anonymize.py` | Use shared merge/validate, add allow_list_count to result |
| `src/redakt/services/document_processor.py` | Use shared merge/validate, add allow_list_count to result |
| `src/redakt/routers/documents.py` | Catch ValueError, pass allow_list_count to audit |
| `src/redakt/routers/pages.py` | Add allow_list Form param to all 3 handlers, pass instance_allow_list to GET contexts |
| `src/redakt/services/audit.py` | Add allow_list_count param to all audit functions |
| `src/redakt/main.py` | Add validate_instance_allow_list at startup |
| `src/redakt/templates/detect.html` | Include allow_list_input partial |
| `src/redakt/templates/anonymize.html` | Include allow_list_input partial |
| `src/redakt/templates/documents.html` | Include allow_list_input partial |
| `src/redakt/static/style.css` | Add styles for allow list input, instance terms tags |

## Technical Decisions

1. **Shared utility module** -- Created `src/redakt/utils.py` rather than adding to existing modules, keeping parse/validate/merge logic centralized and testable.
2. **Validation placement** -- `validate_allow_list()` called inside `run_detection()`, `run_anonymization()`, and `process_document()` before merge. Single validation point covers both API and web UI paths.
3. **Fail-closed validation** -- Entire request rejected on validation violation. No truncation or partial processing.
4. **dict.fromkeys() for dedup** -- Order-preserving deduplication (instance terms first, per-request appended). Replaces set-based approaches that lose ordering.
5. **merge_allow_lists() returns None for empty** -- Presidio treats None as "skip allow list filtering" vs [] which still triggers the code path.
6. **Kept _parse_comma_separated() in documents.py** -- Spec Note #6 explicitly allows keeping both the generic parser and the allow-list-specific wrapper to avoid applying allow-list validation limits to entity parsing.
7. **Startup validation non-blocking** -- `validate_instance_allow_list()` strips empty strings and logs warnings but never blocks application startup. Returns cleaned list.
8. **maxlength="21100" on HTML input** -- 100 terms * 200 chars + 100 commas = 20,100, rounded up for safety.

## Test Coverage

| Category | Count | File |
|----------|-------|------|
| Unit tests (utils) | 37 | `tests/test_allow_list_utils.py` |
| Integration tests (web/API/audit) | 31 | `tests/test_allow_list_web.py` |
| E2E tests (Playwright) | 8 | `tests/e2e/test_allow_list_e2e.py` |
| **New tests total** | **68** | |
| Pre-existing tests | 213 | |
| **All tests total** | **281** | All passing |

### Critical Review Test Additions (5 tests)
- Documents web submit integration test with allow list pass-through
- Empty document + allow list early-return path (per-request only)
- Empty document + allow list early-return path (instance + per-request)
- EDGE-002 partial match integration test
- EDGE-010 cross-language integration test

## Deployment Readiness

- All 281 tests passing (0 failures)
- No new dependencies required
- Backward compatible: `allow_list` form parameter defaults to empty string
- E2E tests written but require Docker Compose stack for execution
- No configuration changes required for deployment (existing `REDAKT_ALLOW_LIST` env var unchanged)
- Startup validation provides operator visibility into instance-wide list health
