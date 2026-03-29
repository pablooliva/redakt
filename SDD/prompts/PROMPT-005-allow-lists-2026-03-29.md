# PROMPT-005-allow-lists Implementation Tracking

- **Spec:** `SDD/requirements/SPEC-005-allow-lists.md`
- **Date:** 2026-03-29
- **Status:** Complete
- **Completion Date:** 2026-03-29

## Implementation Steps

| Step | Description | Status |
|------|-------------|--------|
| 1 | Create shared utility (`utils.py`) | COMPLETE |
| 2 | Replace duplicated merge logic in routers | COMPLETE |
| 3 | Add input validation to shared processing functions | COMPLETE |
| 4 | Add allow_list input to web UI templates | COMPLETE |
| 5 | Display instance-wide terms in UI | COMPLETE |
| 6 | Update pages.py submit handlers | COMPLETE |
| 7 | Update audit logging | COMPLETE |
| 8 | Add tests | COMPLETE |

## Test Results

- **Total tests:** 281 passing (68 new + 213 pre-existing)
- **Unit tests (utils):** 37 tests in `test_allow_list_utils.py`
- **Integration tests (web/API):** 26 tests in `test_allow_list_web.py` (+ 5 added during critical review)
- **E2E tests:** 8 tests in `tests/e2e/test_allow_list_e2e.py` (written, not run -- require Docker)

## Files Created
- `SDD/prompts/PROMPT-005-allow-lists-2026-03-29.md` (this file)
- `src/redakt/utils.py` -- Shared utility: parse_comma_separated, parse_allow_list, validate_allow_list, merge_allow_lists, validate_instance_allow_list
- `src/redakt/templates/partials/allow_list_input.html` -- Shared partial for allow list form group
- `src/redakt/templates/partials/allow_list_instance_terms.html` -- Instance-wide terms display
- `tests/test_allow_list_utils.py` -- 37 unit tests for utility functions
- `tests/test_allow_list_web.py` -- 26 integration tests for web UI + API + audit
- `tests/e2e/test_allow_list_e2e.py` -- 8 E2E Playwright tests

## Files Modified
- `src/redakt/routers/detect.py` -- Use shared merge/validate, add allow_list_count to result
- `src/redakt/routers/anonymize.py` -- Use shared merge/validate, add allow_list_count to result
- `src/redakt/services/document_processor.py` -- Use shared merge/validate, add allow_list_count to result
- `src/redakt/routers/documents.py` -- Catch ValueError, pass allow_list_count to audit
- `src/redakt/routers/pages.py` -- Add allow_list Form param to all 3 handlers, pass instance_allow_list to GET contexts
- `src/redakt/services/audit.py` -- Add allow_list_count param to all audit functions
- `src/redakt/main.py` -- Add validate_instance_allow_list at startup
- `src/redakt/templates/detect.html` -- Include allow_list_input partial
- `src/redakt/templates/anonymize.html` -- Include allow_list_input partial
- `src/redakt/templates/documents.html` -- Include allow_list_input partial
- `src/redakt/static/style.css` -- Add styles for allow list input, instance terms tags

## Requirements Coverage

- REQ-001 through REQ-012: Complete
- PERF-001/002: Complete -- Validation limits enforced (100 terms, 200 chars), O(n) merge with dict.fromkeys()
- SEC-001/002/003: Complete -- Jinja2 auto-escaping, no term logging, validation on both API and web paths
- UX-001/002: Complete -- Instance terms styled as readonly tags, validation errors shown to user
- EDGE-001 through EDGE-012: Complete -- All handled (case sensitivity documented, comma limitation documented)
- FAIL-001 through FAIL-004: Complete -- All handled

## Implementation Completion Summary

**Completed:** 2026-03-29

All 8 implementation steps completed successfully. All requirements (functional, performance, security, UX) are implemented and validated. Critical review findings from `SDD/reviews/CRITICAL-IMPL-allow-lists-20260329.md` have been resolved, bringing the total test count from 276 to 281 (68 new + 213 pre-existing).

### Key Deliverables
- Shared utility module (`src/redakt/utils.py`) with parse, validate, merge functions
- Web UI allow list input on all 3 pages via shared Jinja2 partials
- Instance-wide terms display as read-only tags
- Fail-closed input validation covering both API and web UI paths
- Audit logging with `allow_list_count` metadata (never term values)
- Startup validation for instance-wide allow list configuration

### Artifacts
- Specification: `SDD/requirements/SPEC-005-allow-lists.md`
- Implementation Tracking: `SDD/prompts/PROMPT-005-allow-lists-2026-03-29.md`
- Implementation Summary: `SDD/prompts/implementation-complete/IMPLEMENTATION-SUMMARY-005-2026-03-29_20-00-00.md`
- Code Review: `SDD/reviews/REVIEW-005-allow-lists-20260329.md`
- Critical Review: `SDD/reviews/CRITICAL-IMPL-allow-lists-20260329.md`
