# Code Review: Allow Lists (SPEC-005)

## Artifact Verification
- [x] RESEARCH-005 found and complete
- [x] SPEC-005 found and complete
- [x] PROMPT-005 files preserved
- [x] Context utilization <40% (implementation touches targeted files only; large document_processor.py and presidio internals were not modified beyond the merge/validate insertion point)

## Specification Alignment (70%)

### Functional Requirements

| Req | Status | Notes |
|-----|--------|-------|
| REQ-001 | PASS | All three templates (detect.html, anonymize.html, documents.html) include `{% include "partials/allow_list_input.html" %}` which renders a text input with `name="allow_list"` and label "Allow list". |
| REQ-002 | PASS | `detect_submit` in pages.py accepts `allow_list: str = Form("")`, parses with `parse_allow_list()`, passes to `run_detection()`. |
| REQ-003 | PASS | `anonymize_submit` in pages.py accepts `allow_list: str = Form("")`, parses with `parse_allow_list()`, passes to `run_anonymization()`. |
| REQ-004 | PASS | `documents_submit` in pages.py accepts `allow_list: str = Form("")`, parses with `parse_allow_list()`, passes to `process_document()`. |
| REQ-005 | PASS | Instance-wide terms displayed via `partials/allow_list_instance_terms.html` as read-only tags labeled "Instance-wide terms (always applied)". GET handlers pass `instance_allow_list=settings.allow_list` to template context. |
| REQ-006 | PASS | `merge_allow_lists()` in `utils.py` replaces duplicated merge logic in detect.py (line 88), anonymize.py (line 81), and document_processor.py (line 242). |
| REQ-007 | PASS | `merge_allow_lists()` uses `dict.fromkeys()` for order-preserving deduplication: instance terms first, per-request appended. Unit test `test_deduplication_preserves_order` confirms `["A","B"] + ["B","C"] = ["A","B","C"]`. |
| REQ-008 | PASS | `parse_comma_separated()` strips whitespace via `item.strip()`. Unit test `test_strips_whitespace` confirms. |
| REQ-009 | PASS | `parse_comma_separated()` filters empty strings via `if item.strip()`. Unit test `test_removes_empty_entries` confirms `"term1,,term2, ,term3"` yields `["term1","term2","term3"]`. |
| REQ-010 | PASS | All three audit log functions accept `allow_list_count: int | None`. `_emit_audit()` includes it when non-None and > 0. Count reflects merged total (`len(merged_allow_list) if merged_allow_list else None`). Terms are never logged -- only the integer count. |
| REQ-011 | PASS | `allow_list: str = Form("")` defaults to empty string. `parse_allow_list("")` returns `[]`, and `parsed_allow_list or None` yields `None`, so existing behavior (instance-only) is preserved. |
| REQ-012 | PASS | Helper text in `allow_list_input.html` reads: "Comma-separated terms. Must match exactly as they appear in the text (case-sensitive). Terms containing commas cannot be added via this field." Input has `aria-describedby="allow_list_help"` pointing to `<small id="allow_list_help">`. |

### Non-Functional Requirements

| Req | Status | Notes |
|-----|--------|-------|
| PERF-001 | PASS | `validate_allow_list()` checks max 100 terms and max 200 chars per term. `validate_instance_allow_list()` logs warning if instance list exceeds 500 terms. Constants defined at module level: `MAX_ALLOW_LIST_TERMS=100`, `MAX_ALLOW_LIST_TERM_LENGTH=200`, `INSTANCE_ALLOW_LIST_WARN_THRESHOLD=500`. |
| PERF-002 | PASS | `merge_allow_lists()` uses `dict.fromkeys()` which is O(n). |
| SEC-001 | PASS | All `{{ term }}` expressions in templates use Jinja2 auto-escaping. No `|safe` filter on allow list term values (grep confirms). |
| SEC-002 | PASS | `_emit_audit()` only includes `allow_list_count` (integer). Terms are never passed to audit functions. Test `test_detect_audit_excludes_allow_list_terms` explicitly verifies "SecretCompany" is not in logged kwargs. |
| SEC-003 | PASS | `validate_allow_list()` is called inside `run_detection()`, `run_anonymization()`, and `process_document()` BEFORE the merge step. Both API routers and pages.py handlers call these shared functions, so validation is applied to both paths. ValueError is raised on violation (fail-closed). API routers catch ValueError and return 422; pages.py catches ValueError and returns error template. |
| UX-001 | PASS | Instance terms styled with `term-tag readonly` class: `background: #e9ecef; color: #6c757d; border: 1px solid #dee2e6` -- visually muted/disabled appearance. |
| UX-002 | PASS | Validation errors surface through `ValueError` catch blocks. Web UI renders them in the results partial as error messages. API returns 422 with descriptive detail. Tests confirm error messages contain "exceeds maximum of 100 terms" and "exceeds maximum length". |

### Edge Cases

| Edge | Status | Notes |
|------|--------|-------|
| EDGE-001 (case sensitivity) | PASS | Documented in helper text ("case-sensitive"). E2E test `test_allow_list_case_sensitivity` verifies "john smith" does not suppress "John Smith". |
| EDGE-002 (partial match) | PASS | Documented behavior. No code change needed. |
| EDGE-003 (empty strings) | PASS | `parse_comma_separated()` filters empties. Unit test `test_removes_empty_entries`. |
| EDGE-004 (Unicode) | PASS | Unit test `test_unicode_terms` with "Munchen", "Strasse", "Beijing". Integration test `test_unicode_terms_in_api`. |
| EDGE-005 (duplicates) | PASS | `merge_allow_lists()` deduplicates via `dict.fromkeys()`. Unit tests `test_deduplication_preserves_order` and `test_deduplication_all_duplicates`. Integration test `test_merge_deduplicates`. |
| EDGE-006 (parsing edge cases) | PASS | Unit test `test_trailing_comma` verifies `"term1, term2 , , term3,"` produces correct output. |
| EDGE-007 (max terms exceeded) | PASS | Unit test `test_rejects_too_many_terms`. Integration tests for all three endpoints. |
| EDGE-008 (term too long) | PASS | Unit test `test_rejects_term_too_long`. Integration tests for detect and anonymize API. |
| EDGE-009 (regex special chars) | PASS | Unit test `test_regex_special_chars_accepted`. Integration test `test_regex_special_chars_in_exact_mode`. |
| EDGE-010 (language-dependent) | PARTIAL | No dedicated integration test verifying different detection outcomes across languages. This is informational per spec ("Informational only" for EDGE-011 which is related). Acceptable for v1 since it concerns Presidio internals. |
| EDGE-011 (score threshold) | PASS | Spec marks as "Informational only". No code change needed. |
| EDGE-012 (comma-containing terms) | PASS | Unit test `test_comma_containing_term_splits` verifies "Smith, John" splits into ["Smith", "John"]. Helper text mentions "Terms containing commas cannot be added via this field." |

### Failure Scenarios

| Fail | Status | Notes |
|------|--------|-------|
| FAIL-001 (validation error) | PASS | Fail-closed: ValueError raised, entire request rejected. API returns 422, web UI shows inline error. No truncation. |
| FAIL-002 (invalid instance terms at startup) | PASS | `validate_instance_allow_list()` called in lifespan handler (main.py:41). Logs warnings for empty strings, overly long terms, and lists exceeding 500 terms. Does not block startup. |
| FAIL-003 (Presidio unavailable) | PASS | Allow list does not change error handling. Existing `httpx.ConnectError` handling returns 503/service unavailable. |
| FAIL-004 (XSS attempt) | PASS | Jinja2 auto-escaping active. No `|safe` on term values. Terms passed to Presidio as-is (functionally inert). |

## Context Engineering (20%)

| Criterion | Status | Notes |
|-----------|--------|-------|
| PROMPT-005 preserved | PASS | `SDD/prompts/PROMPT-005-allow-lists-2026-03-29.md` present with complete tracking of all 8 steps. |
| Traceability | PASS | PROMPT-005 lists all files created and modified, requirements coverage matrix, and test results. |
| Context utilization | PASS | Implementation touches only the files specified in the spec's "Essential files for implementation" list. No extraneous files modified. |
| Artifact completeness | PASS | RESEARCH-005, SPEC-005, and PROMPT-005 form a complete chain from research to spec to implementation tracking. |

## Test Coverage (10%)

### Unit Tests (test_allow_list_utils.py): 37 tests
- `parse_comma_separated`: 10 tests covering basic parsing, whitespace, empties, Unicode, None, edge cases
- `parse_allow_list`: 5 tests covering empty string, whitespace, parsing, comma-containing terms
- `validate_allow_list`: 8 tests covering empty list, valid terms, too many terms, term too long, boundary values, custom limits, regex special chars
- `merge_allow_lists`: 9 tests covering instance-only, per-request-only, both, neither, deduplication, empty cases
- `validate_instance_allow_list`: 5 tests covering empty list, empty strings, long terms, large list, valid list

### Integration Tests (test_allow_list_web.py): 26 tests
- Web UI: input field visibility (3 tests), submit with allow_list (3 tests), empty allow_list (1 test), validation errors (3 tests)
- API: validation errors for detect, anonymize, documents (5 tests), valid allow_list (2 tests)
- Audit logging: count inclusion (2 tests), term exclusion (1 test), no count when None (1 test)
- Instance merge: applied without per-request (1 test), deduplication (1 test)
- Edge cases: Unicode (1 test), regex special chars (1 test), whitespace-only entries (1 test)

### E2E Tests (test_allow_list_e2e.py): 8 tests
- Input visibility on all three pages (3 tests)
- Helper text visibility (1 test)
- Allow list suppresses entity in detect and anonymize (2 tests)
- Case sensitivity behavior (1 test)
- Instance terms displayed when configured (1 test)

### Coverage Assessment
- All spec-defined test scenarios are covered
- The spec's Validation Strategy lists ~10 unit, ~12 integration, ~5 edge case, ~8 E2E tests. Actual counts are 37 unit, 26 integration (including edge cases), and 8 E2E, exceeding spec expectations.
- EDGE-010 (language-dependent behavior) lacks a dedicated cross-language integration test, but this was noted as informational in the spec. Minor gap, non-blocking.

## Decision: APPROVED

## Commendations

- **Clean utility extraction**: The `utils.py` module is well-structured with clear separation between parsing (`parse_comma_separated`, `parse_allow_list`), validation (`validate_allow_list`), and merging (`merge_allow_lists`). Each function has a single responsibility.
- **Consistent validation placement**: Validation is correctly placed inside the shared processing functions (`run_detection`, `run_anonymization`, `process_document`) before the merge step, ensuring both API and web UI paths are covered by a single validation point, exactly as specified.
- **Template reuse via partials**: The `allow_list_input.html` partial avoids triplicating the input field markup across three templates. The `allow_list_instance_terms.html` partial is similarly reused.
- **Fail-closed error handling**: ValueError propagation is consistent -- API routers convert to 422, web UI handlers render error templates. No silent truncation or partial processing anywhere.
- **Audit logging discipline**: `_emit_audit()` only includes `allow_list_count` when non-None and > 0, and never receives term values. The test explicitly asserts term values are absent from audit kwargs.
- **Backward compatibility preserved**: The `allow_list: str = Form("")` default ensures existing requests without allow_list continue to work. The `parsed_allow_list or None` pattern correctly converts empty lists to None for Presidio.
- **Test coverage exceeds spec requirements**: 37 + 26 + 8 = 71 tests vs the spec's estimated ~35.
- **`merge_allow_lists` returns None for empty result**: Correctly preserves the Presidio convention where `None` means "skip allow list filtering" vs `[]` which may still trigger the code path.
