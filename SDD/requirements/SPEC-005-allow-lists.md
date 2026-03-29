# SPEC-005-allow-lists

## Executive Summary

- **Based on Research:** RESEARCH-005-allow-lists.md
- **Creation Date:** 2026-03-29
- **Status:** Draft

## Research Foundation

### Production Issues Addressed
1. **False positive PII detection** -- Company names, product names, and office locations are frequently flagged as PERSON or ORGANIZATION entities. Enterprise users need a mechanism to suppress known non-PII terms.
2. **Web UI feature parity gap** -- All three API endpoints already accept `allow_list`, but none of the three web UI forms expose this capability. Users relying on the web UI cannot add per-request allow list terms.
3. **No visibility into instance-wide terms** -- Administrators configure `REDAKT_ALLOW_LIST` via env var, but users have no way to see which terms are pre-configured, leading to duplicate entries and confusion.
4. **No input validation** -- No limits on term count, term length, or character filtering. A malicious or buggy client can send thousands of long strings, creating a denial-of-service vector against Presidio (O(n*m) comparisons).
5. **Duplicated merge logic** -- The same merge pattern (`list(settings.allow_list)` + `extend(per_request)`) is repeated in three separate locations.

### Stakeholder Validation
- **Product team:** Allow lists reduce false positives, improving trust. Instance-wide list eliminates repetitive configuration.
- **Engineering team:** Core infrastructure done; primary gap is UI + validation + DRY refactoring.
- **Support team:** Case sensitivity and partial-match behavior will generate user questions. Clear UI guidance needed.
- **User perspective:** Expects simple input, visibility into instance terms, and case-insensitive matching (v1 limitation: exact match only).
- **Enterprise IT/Ops:** Env var config with container restart is acceptable for v1. Post-v1 may need hot-reload.
- **Non-English users:** German compound words create allow list challenges; exact-match limitation documented.
- **Compliance/Legal:** Allow list change audit trail is out of scope for v1.

### System Integration Points
1. `src/redakt/config.py:16` -- Instance-wide `allow_list` setting
2. `src/redakt/services/presidio.py:19-29` -- Passes `allow_list` to Presidio `/analyze`
3. `src/redakt/routers/detect.py:81-83` -- Merge logic (instance + per-request)
4. `src/redakt/routers/anonymize.py:74-76` -- Merge logic (duplicated)
5. `src/redakt/services/document_processor.py:239-241` -- Merge logic (duplicated)
6. `src/redakt/routers/pages.py` -- Three submit handlers missing `allow_list` parameter
7. Three templates (`detect.html`, `anonymize.html`, `documents.html`) -- No allow_list input fields

## Intent

### Problem Statement
The allow_list backend infrastructure is fully functional for API consumers, but web UI users cannot add per-request allow list terms, cannot see instance-wide terms, and there is no input validation to prevent abuse. Additionally, the merge logic is duplicated across three files, creating a maintenance burden.

### Solution Approach
1. Add a comma-separated text input field to all three web UI forms
2. Update `pages.py` submit handlers to parse and pass `allow_list` to processing functions
3. Display instance-wide terms as read-only tags in the UI
4. Add input validation (term count, length, whitespace stripping, empty rejection) to both API and web UI paths
5. Extract merge logic into a shared utility function
6. Add audit logging metadata for allow_list usage (count only, never values)
7. Add comprehensive tests including E2E browser tests

### Expected Outcomes
- Web UI users can specify per-request allow list terms on all three pages
- Users can see which instance-wide terms are pre-configured
- Input validation prevents abuse and improves error messages
- Merge logic is DRY and consistent across all code paths
- Allow list usage is tracked in audit logs (metadata only)

## Success Criteria

### Functional Requirements

- **REQ-001:** All three web UI forms (detect, anonymize, documents) include a text input field labeled "Allow list" that accepts comma-separated terms.
- **REQ-002:** The `detect_submit` handler in `pages.py` accepts an `allow_list` form parameter, parses comma-separated terms, and passes them to `run_detection()`.
- **REQ-003:** The `anonymize_submit` handler in `pages.py` accepts an `allow_list` form parameter, parses comma-separated terms, and passes them to `run_anonymization()`.
- **REQ-004:** The `documents_submit` handler in `pages.py` accepts an `allow_list` form parameter, parses comma-separated terms, and passes them to `process_document()`.
- **REQ-005:** Instance-wide allow list terms (from `settings.allow_list`) are displayed as read-only tags in the UI on all three pages, clearly labeled as "Instance-wide terms".
- **REQ-006:** A shared `merge_allow_lists(instance_list, per_request_list)` utility function replaces the duplicated merge logic in `detect.py`, `anonymize.py`, and `document_processor.py`.
- **REQ-007:** The shared merge function deduplicates terms (order-preserving union via `dict.fromkeys()`) so that terms appearing in both instance and per-request lists are not sent twice to Presidio. Order: instance terms first, per-request appended, duplicates removed while preserving first-seen order.
- **REQ-008:** Per-request terms are stripped of leading/trailing whitespace before processing.
- **REQ-009:** Empty strings (after stripping) are silently removed from the parsed allow list.
- **REQ-010:** Audit log entries for detect, anonymize, and document_upload actions include `allow_list_count` (integer, total merged terms sent to Presidio, i.e., instance + per-request after deduplication) when any allow_list terms were applied. Never log the actual terms. The total merged count is chosen over per-request-only because it reflects the actual filtering applied to Presidio results, which is what operators need for debugging and compliance reporting.
- **REQ-011:** When no per-request allow list is provided via the web UI, the form field is empty and only instance-wide terms are applied (existing behavior, no regression).
- **REQ-012:** The `allow_list` input field includes helper text explaining: "Comma-separated terms. Must match exactly as they appear in the text (case-sensitive). Terms containing commas cannot be added via this field." The input field includes `aria-describedby` pointing to the helper text element for accessibility.

### Non-Functional Requirements

- **PERF-001:** Input validation rejects oversized per-request allow lists before they reach Presidio. Max 100 terms per request, max 200 characters per term. Instance-wide terms are trusted admin input with no count limit, but `validate_language_config()`-style startup validation logs a warning if the instance list exceeds 500 terms (performance advisory, non-blocking).
- **PERF-002:** The shared merge function completes in O(n) time where n = total terms (instance + per-request), using `dict.fromkeys()` for order-preserving deduplication (instance terms first, per-request appended).
- **SEC-001:** Allow list terms rendered in the UI are auto-escaped by Jinja2 to prevent XSS. No `|safe` filter is used on allow list term values.
- **SEC-002:** Allow list term values are never logged in audit logs, application logs, or error responses. Only the count is logged.
- **SEC-003:** Input validation applies to both API and web UI paths (defense in depth). Validation is placed inside `run_detection()`, `run_anonymization()`, and `process_document()` on the per-request `allow_list` parameter BEFORE the merge step. This single validation point is hit by both API routers and `pages.py` handlers. Validation is fail-closed: the entire request is rejected on violation (no truncation or partial processing).
- **UX-001:** Instance-wide terms are visually distinct from per-request terms (read-only styling, e.g., muted/disabled appearance).
- **UX-002:** Validation errors (too many terms, term too long) display a clear error message to the user identifying the specific violation.

## Edge Cases (Research-Backed)

- **EDGE-001: Case sensitivity**
  - Research reference: Production Edge Cases #1, Stakeholder Support Team
  - Current behavior: Presidio exact match is case-sensitive. "acme corp" does not suppress "Acme Corp".
  - Desired behavior: Document as v1 limitation. Display helper text in UI explaining case-sensitivity.
  - Test approach: Unit test confirming case-sensitive matching passes through to Presidio unchanged. E2E test verifying helper text is visible.

- **EDGE-002: Partial entity match**
  - Research reference: Production Edge Cases #2
  - Current behavior: Adding "John" to allow_list does not suppress "John Smith" (Presidio matches full detected span).
  - Desired behavior: Document as expected behavior. Helper text covers this.
  - Test approach: Integration test: submit text with "John Smith" as detected PERSON, "John" in allow_list, verify "John Smith" is still detected.

- **EDGE-003: Empty strings in allow list**
  - Research reference: Production Edge Cases #5
  - Current behavior: Empty strings are passed to Presidio without filtering.
  - Desired behavior: Empty strings (after whitespace stripping) are silently removed (REQ-009).
  - Test approach: Unit test: parse `"term1,,term2, ,term3"` and verify result is `["term1", "term2", "term3"]`.

- **EDGE-004: Unicode and special characters**
  - Research reference: Production Edge Cases #4
  - Current behavior: No filtering. Unicode terms passed as-is.
  - Desired behavior: Allow Unicode terms (international company names). Strip whitespace only.
  - Test approach: Unit test with actual Unicode terms (e.g., "München", "Straße", "北京市"). Integration test verifying these terms suppress detection when matched.

- **EDGE-005: Duplicate terms across instance and per-request**
  - Research reference: Production Edge Cases #6
  - Current behavior: `extend()` without deduplication. Not harmful but wasteful.
  - Desired behavior: Merge function deduplicates via `dict.fromkeys()` (REQ-007). Order: instance terms first, per-request appended, duplicates removed while preserving first-seen order.
  - Test approach: Unit test: merge `["A", "B"]` (instance) + `["B", "C"]` (per-request) = `["A", "B", "C"]` (order preserved, deduped via `dict.fromkeys()`).

- **EDGE-006: Comma-separated parsing edge cases**
  - Research reference: Documents router pattern (`_parse_comma_separated`)
  - Current behavior: Document endpoint already parses comma-separated; web UI currently does not.
  - Desired behavior: Consistent parsing: split on commas, strip whitespace, remove empty entries.
  - Test approach: Unit test: `"term1, term2 , , term3,"` produces `["term1", "term2", "term3"]`.

- **EDGE-007: Maximum term count exceeded**
  - Research reference: Security Considerations, Input Validation
  - Current behavior: No limit.
  - Desired behavior: Return 422 (API) or error message (web UI) stating "Maximum 100 allow list terms per request."
  - Test approach: Integration test: send 101 terms, verify 422 response with descriptive error.

- **EDGE-008: Term exceeding maximum length**
  - Research reference: Security Considerations, Input Validation
  - Current behavior: No limit.
  - Desired behavior: Return 422 (API) or error message (web UI) stating which term exceeded 200 characters.
  - Test approach: Integration test: send a 201-character term, verify 422 response.

- **EDGE-009: Allow list with regex special characters in exact mode**
  - Research reference: Edge Cases to Test #6
  - Current behavior: Exact mode uses Python `in` operator, so regex characters are treated as literal strings.
  - Desired behavior: No change needed. Confirm regex characters are safe in exact mode.
  - Test approach: Unit test: allow_list containing `"test@example.com"` (contains `@` and `.`) works correctly.

- **EDGE-010: Language-dependent allow list behavior**
  - Research reference: Interaction with Language Detection
  - Current behavior: Allow list filtering is language-agnostic, but NER detection that produces entity spans is language-dependent.
  - Desired behavior: Document as known behavior. Same allow list term may suppress in one language but have no effect in another (because the term is not detected in the second language).
  - Test approach: Integration test with same text/term in English vs German, verifying different detection outcomes are possible.

- **EDGE-012: Comma-containing terms in web UI input**
  - Research reference: Questionable Assumption #3 from critical review
  - Current behavior: Comma-separated parsing splits on commas, so "Smith, John" becomes "Smith" and "John".
  - Desired behavior: Document as a **known v1 limitation** of the web UI comma-separated input. The API accepts JSON arrays and can handle terms containing commas. Helper text in the UI mentions this limitation. No escape mechanism for v1; post-v1 may add a tag-style UI or quote-based escaping.
  - Test approach: Unit test confirming "Smith, John" is split into ["Smith", "John"]. E2E test verifying helper text mentions the limitation.

- **EDGE-011: Allow list terms near score threshold**
  - Research reference: Interaction with Score Threshold
  - Current behavior: Allow list filtering happens after score thresholding. Terms below threshold are already removed.
  - Desired behavior: No change. Document that allow lists only affect terms that are detected (above threshold).
  - Test approach: Informational only -- Presidio's internal ordering is not controllable from Redakt. Add a note in user-facing helper text or documentation: "Allow lists only affect terms that are detected as PII. If a term is not consistently detected, adjusting the score threshold may be more appropriate."

## Failure Scenarios

- **FAIL-001: Validation error on per-request terms**
  - Trigger condition: User submits more than 100 terms or a term exceeding 200 characters.
  - Expected behavior: Validation is **fail-closed** -- the entire request is rejected. No truncation, no partial processing. API returns 422 with descriptive error. Web UI displays inline error message.
  - User communication: "Allow list exceeds maximum of 100 terms." or "Allow list term exceeds maximum length of 200 characters."
  - Recovery approach: User reduces term count or length and resubmits.

- **FAIL-002: Instance-wide allow list contains invalid terms at startup**
  - Trigger condition: `REDAKT_ALLOW_LIST` contains empty strings, terms exceeding 200 characters, or more than 500 terms.
  - Expected behavior: Application logs a warning at startup, strips empty strings, logs warning for overly long terms (but does not block startup -- instance-wide terms are trusted admin input). Logs a performance advisory if the list exceeds 500 terms. Does NOT block startup for any of these conditions.
  - User communication: Startup log message visible to administrators.
  - Recovery approach: Administrator corrects the env var and restarts.

- **FAIL-003: Presidio service unavailable with allow list**
  - Trigger condition: Presidio Analyzer is down when a request with allow_list is submitted.
  - Expected behavior: Same error handling as without allow_list (503 for web UI, appropriate HTTP error for API). Allow list terms are not persisted.
  - User communication: "Service is starting up, please wait..."
  - Recovery approach: Retry after Presidio is healthy.

- **FAIL-004: XSS attempt via allow list terms**
  - Trigger condition: User enters `<script>alert('xss')</script>` as an allow list term.
  - Expected behavior: Term is HTML-escaped by Jinja2 auto-escaping when rendered. Term is passed to Presidio as-is (it won't match any entity span containing `<script>` tags, so it's functionally inert).
  - User communication: None -- term simply doesn't match anything.
  - Recovery approach: No recovery needed.

## Implementation Constraints

### Context Requirements
- Maximum context utilization: <40%
- Essential files for implementation:
  - `src/redakt/routers/pages.py` (3 handler updates)
  - `src/redakt/routers/detect.py` (merge logic extraction)
  - `src/redakt/routers/anonymize.py` (merge logic extraction)
  - `src/redakt/services/document_processor.py` (merge logic extraction)
  - `src/redakt/templates/detect.html` (add allow_list input)
  - `src/redakt/templates/anonymize.html` (add allow_list input)
  - `src/redakt/templates/documents.html` (add allow_list input)
  - `src/redakt/services/audit.py` (add allow_list_count)
  - `src/redakt/config.py` (validation constants, if needed)
- Files that can be delegated to subagents:
  - Test files
  - E2E test files

### Technical Constraints
1. Presidio's `allow_list` is exact match and case-sensitive -- Redakt does not override this for v1.
2. Instance-wide list is configured via `REDAKT_ALLOW_LIST` env var (JSON array format). No admin UI for v1.
3. No regex support for v1 -- `allow_list_match` parameter is not exposed. **Post-v1 note:** Presidio's regex mode uses `re.search()` (partial match, not fullmatch) with `re.IGNORECASE` by default. The `regex_flags` parameter is also configurable per-request. If regex mode is exposed in future versions, implementers must be aware that partial-match semantics differ significantly from exact mode (e.g., "Corp" would suppress "Acme Corp"). See Research Q3 for detailed analysis.
4. Jinja2 auto-escaping must remain active for all templates rendering allow list terms.
5. All web UI forms use `Form()` parameters -- allow_list is passed as a comma-separated string, not JSON array.
6. The documents endpoint already has a `_parse_comma_separated()` helper; reuse or generalize this pattern.

## Validation Strategy

### Automated Testing

**Unit Tests (~10 tests):**
- `test_merge_allow_lists()` -- shared utility: instance-only, per-request-only, both, neither, duplicates, empty strings, whitespace stripping
- `test_parse_comma_separated()` -- parsing: trailing commas, spaces, empty entries, Unicode
- `test_validation_limits()` -- max terms (100), max term length (200), edge at limit

**Integration Tests (~12 tests):**
- `test_detect_submit_with_allow_list()` -- web UI form submits allow_list, verify it reaches `run_detection()`
- `test_anonymize_submit_with_allow_list()` -- web UI form submits allow_list, verify it reaches `run_anonymization()`
- `test_documents_submit_with_allow_list()` -- web UI form submits allow_list, verify it reaches `process_document()`
- `test_detect_api_validation_too_many_terms()` -- 101 terms -> 422
- `test_detect_api_validation_term_too_long()` -- 201-char term -> 422
- `test_anonymize_api_validation()` -- same validation for anonymize
- `test_documents_api_validation()` -- same validation for documents
- `test_allow_list_suppresses_detection()` -- submit text with known PII term in allow_list, verify it's not detected
- `test_allow_list_case_sensitive()` -- "acme" in allow_list does not suppress "Acme"
- `test_audit_log_includes_allow_list_count()` -- verify audit entry contains `allow_list_count`
- `test_audit_log_excludes_allow_list_terms()` -- verify audit entry does not contain actual terms
- `test_instance_allow_list_applied_without_per_request()` -- verify instance terms work when no per-request terms submitted

**Edge Case Tests (~5 tests):**
- Regex special characters in exact mode
- Unicode terms
- Empty allow_list (field submitted but empty string)
- Maximum valid request (100 terms, each 200 chars)
- Allow list with only whitespace entries

### E2E Tests (~8 tests)
- `test_detect_allow_list_input_visible()` -- Verify allow_list input field present on detect page
- `test_anonymize_allow_list_input_visible()` -- Verify allow_list input field present on anonymize page
- `test_documents_allow_list_input_visible()` -- Verify allow_list input field present on documents page
- `test_detect_allow_list_suppresses_entity()` -- Submit text with known name, add name to allow_list, verify not detected
- `test_anonymize_allow_list_suppresses_entity()` -- Same for anonymize
- `test_instance_terms_displayed()` -- Verify instance-wide terms are visible in the UI
- `test_allow_list_helper_text_visible()` -- Verify case-sensitivity helper text is displayed
- `test_allow_list_case_sensitivity_e2e()` -- Submit "John Smith" with "john smith" in allow_list, verify still detected (case-sensitive)

### Manual Verification
- [ ] Allow list input field renders correctly on all three pages
- [ ] Instance-wide terms display when `REDAKT_ALLOW_LIST` is configured
- [ ] Per-request terms suppress expected PII entities
- [ ] Helper text about case sensitivity is visible and clear
- [ ] Validation errors display correctly for oversized inputs
- [ ] No XSS when entering `<script>` tags as allow list terms
- [ ] Audit logs show `allow_list_count` but not term values

## Dependencies and Risks

- **RISK-001: Case-sensitivity user confusion** -- Users will expect case-insensitive matching. Mitigation: Clear helper text in UI, documentation. **Decision rationale:** Research (Q3) recommended Redakt-side case-insensitive preprocessing for v1. This was deferred because: (a) Presidio's exact mode compares `text[start:end] in allow_list`, so Redakt would need to lowercase both the allow_list terms AND know the exact detected span text before sending to Presidio -- but the span text is only known after Presidio returns results, requiring post-processing rather than pre-processing; (b) using Presidio's regex mode with `re.escape()` changes semantics to partial match (`re.search()` not `re.fullmatch()`), which would cause unexpected suppressions; (c) implementing Redakt-side post-processing of Presidio results (re-check each entity against allow_list case-insensitively) is a cleaner approach but adds complexity beyond the v1 scope of "expose existing functionality in the web UI." **Post-v1 (high priority):** Implement Redakt-side case-insensitive post-filtering of Presidio results (lowercase comparison of entity text against allow_list terms, removing matches from the result set before returning to the client).
- **RISK-002: Partial-match confusion** -- Users may expect "John" to suppress "John Smith". Mitigation: Helper text explaining exact-match behavior.
- **RISK-003: Instance-wide list changes require restart** -- Container restart causes 30+ seconds downtime while Presidio reloads NLP models. Mitigation: Acceptable for v1 (enterprise internal tool). Note: env var approach may not integrate cleanly with secrets management systems (Vault, AWS SSM) in Kubernetes/Docker Swarm deployments. Post-v1: config file hot-reload or admin API (requires auth).
- **RISK-004: Large allow lists degrade Presidio performance** -- Presidio uses O(n) list `in` checks per entity. Mitigation: Input validation caps at 100 terms per request. Instance-wide list is admin-controlled. Startup validation logs a warning if instance list exceeds 500 terms.
- **RISK-005: Comma-containing terms cannot be allow-listed via web UI** -- The comma-separated input format means terms like "Smith, John" (common in CSV data, legal documents) get split into separate terms. Mitigation: Document as known v1 limitation in helper text. The API (JSON array) supports such terms. Post-v1: consider tag-style UI or quote-based escaping.
- **RISK-006: `_parse_comma_separated()` dual-use creates refactoring risk** -- The existing `_parse_comma_separated()` in `documents.py` is used for both `entities` and `allow_list` fields. If replaced with a shared utility that includes validation, it would incorrectly apply allow-list limits to entity parsing. Mitigation: Keep `_parse_comma_separated()` as a generic parser; `parse_allow_list()` wraps it with allow-list-specific validation (see Implementation Note #6).

## Implementation Notes

### Suggested Approach

**Step 1: Create shared utility function**
- Create `src/redakt/utils.py` (or add to an existing utils module)
- Implement `parse_comma_separated(raw: str | None) -> list[str] | None` as a generic parser (split on commas, strip whitespace, remove empty entries, return `None` if no valid items). This can replace the private `_parse_comma_separated()` in `documents.py` or be used alongside it.
- Implement `parse_allow_list(raw: str) -> list[str]` that calls `parse_comma_separated()` and returns `[]` (not `None`) for empty input, since allow_list-specific validation and merge will handle the empty case.
- Implement `validate_allow_list(terms: list[str], max_terms: int = 100, max_term_length: int = 200) -> None` raising `ValueError` on violations (fail-closed, no return value needed).
- Implement `merge_allow_lists(instance_list: list[str], per_request_list: list[str] | None) -> list[str] | None` with order-preserving deduplication via `dict.fromkeys()` (instance terms first, per-request appended); returns `None` if result is empty. Callers pass the return value directly to Presidio without additional `or None` checks.
- Add unit tests for all functions

**Step 2: Replace duplicated merge logic**
- Update `src/redakt/routers/detect.py` to use `merge_allow_lists()` from utils
- Update `src/redakt/routers/anonymize.py` to use `merge_allow_lists()` from utils
- Update `src/redakt/services/document_processor.py` to use `merge_allow_lists()` from utils
- Verify existing tests still pass

**Step 3: Add input validation to shared processing functions**
- Add `validate_allow_list(allow_list)` call inside `run_detection()`, `run_anonymization()`, and `process_document()` on the per-request `allow_list` parameter BEFORE the merge step. This ensures both API and web UI paths hit the same validation. Do NOT add validation in Pydantic model validators (keeps validation logic in one place with consistent error formatting).
- `validate_allow_list()` raises `ValueError` on violation. Each caller catches `ValueError` and returns the appropriate error response (422 JSON for API, HTML error template for web UI).
- Validation is fail-closed: reject the entire request on violation, never truncate or partially process.
- Add integration tests for validation

**Step 4: Add allow_list input to web UI templates**
- Add a text input field to `detect.html`, `anonymize.html`, and `documents.html`
- Field: `<input type="text" name="allow_list" placeholder="e.g. Acme Corp, ProductX, Berlin HQ">`
- Include helper text: "Comma-separated terms. Must match exactly as they appear in the text (case-sensitive)."
- Consider a shared partial `partials/allow_list_input.html` to avoid template duplication

**Step 5: Display instance-wide terms in UI**
- Create `partials/allow_list_instance_terms.html` partial
- Render `settings.allow_list` as read-only tags/badges
- Include partial in all three page templates
- Pass `instance_allow_list` to template context from GET handlers in `pages.py`
- Ensure Jinja2 auto-escaping is active (no `|safe` on term values)

**Step 6: Update pages.py submit handlers**
- Add `allow_list: str = Form("")` parameter to `detect_submit`, `anonymize_submit`, `documents_submit`
- Parse with `parse_allow_list(allow_list)`
- Validate with `validate_allow_list(parsed_terms)`
- Pass validated terms to `run_detection()`, `run_anonymization()`, `process_document()`
- Handle `ValueError` from validation, returning template error response

**Step 7: Update audit logging**
- Modify `log_detection()`, `log_anonymization()`, `log_document_upload()` to accept optional `allow_list_count: int | None` parameter
- `allow_list_count` represents the total merged count (instance + per-request, after deduplication) -- i.e., `len(merged_allow_list)` when it is not `None`
- Include `allow_list_count` in audit data when present (non-None and > 0)
- Update callers in both API routers and pages.py to pass the count after the merge step
- Never log term values

**Step 8: Add tests**
- Unit tests for utility functions
- Integration tests for web UI handlers with allow_list
- Integration tests for validation
- Integration tests for audit logging
- E2E Playwright tests for UI functionality

### API Contract

**All three API endpoints already accept `allow_list`. Validation is the only addition.**

`POST /api/detect` (existing, add validation):
```json
{
  "text": "John Smith works at Acme Corp in Berlin.",
  "language": "auto",
  "allow_list": ["Acme Corp", "Berlin"]
}
```
Response unchanged. If validation fails:
```json
// 422
{
  "detail": "Allow list exceeds maximum of 100 terms."
}
```

`POST /api/anonymize` (existing, add validation):
```json
{
  "text": "John Smith works at Acme Corp in Berlin.",
  "language": "auto",
  "allow_list": ["Acme Corp", "Berlin"]
}
```

`POST /api/documents/upload` (existing multipart form, add validation):
```
Content-Type: multipart/form-data
file: [uploaded file]
language: auto
allow_list: Acme Corp, Berlin
```

### Web UI Contract

**Template changes (all three pages):**

1. New form field (between language toggle and submit button). Input field and helper text appear first; instance-wide terms appear below in a collapsible/compact section so they do not push the input below the fold when the list is large:
```html
<div class="form-group">
    <label for="allow_list">Allow list</label>
    <input type="text" id="allow_list" name="allow_list"
           placeholder="e.g. Acme Corp, ProductX, Berlin HQ"
           aria-describedby="allow_list_help">
    <small id="allow_list_help" class="form-help">Comma-separated terms. Must match exactly as they appear in the text (case-sensitive). Terms containing commas cannot be added via this field.</small>
    {% include "partials/allow_list_instance_terms.html" %}
</div>
```

2. Instance terms partial (`partials/allow_list_instance_terms.html`):
```html
{% if instance_allow_list %}
<div class="instance-terms" role="group" aria-label="Instance-wide allow list terms">
    <small>Instance-wide terms (always applied):</small>
    {% for term in instance_allow_list %}
    <span class="term-tag readonly" aria-label="Instance term: {{ term }}">{{ term }}</span>
    {% endfor %}
</div>
{% endif %}
```

**Pages.py GET handler changes:**
- `detect_page`, `anonymize_page`, `documents_page` must pass `instance_allow_list=settings.allow_list` to template context.

**Pages.py POST handler changes:**
- All three submit handlers add `allow_list: str = Form("")` parameter.
- Parse: `parsed_terms = parse_allow_list(allow_list)`
- Validate: `validate_allow_list(parsed_terms)` (catch `ValueError`, return error template)
- Pass: `allow_list=parsed_terms` to processing function

**HTMX interaction:**
- No changes to HTMX behavior. The allow_list field is included in the form POST as a standard form field.
- No JavaScript required for allow list functionality.

### Critical Implementation Considerations

1. **Jinja2 auto-escaping:** All `{{ term }}` expressions in templates are auto-escaped. Never use `|safe` on allow list terms. The `tojson` filter is safe for JSON serialization if needed.

2. **Form field vs JSON array:** Web UI uses comma-separated string (`Form("")`). API uses JSON array. The parsing function `parse_allow_list()` handles the web UI path; API path uses Pydantic model validation.

3. **Validation placement:** Call `validate_allow_list()` inside `run_detection()`, `run_anonymization()`, and `process_document()` on the per-request `allow_list` parameter BEFORE the merge step. This single validation point is hit by both API routers (which call these shared functions) and `pages.py` handlers (which also call these shared functions). Do NOT validate in Pydantic model validators. Each caller catches the `ValueError` and formats the error response appropriately (422 JSON for API, HTML error template for web UI). Validation is fail-closed: reject the entire request, never truncate.

4. **Instance-wide term validation at startup:** Add a startup check in the FastAPI lifespan handler (where `validate_language_config()` is already called) to warn about problematic instance-wide terms: empty strings (strip them), terms exceeding 200 characters (log warning), list exceeding 500 terms (log performance advisory). Do not block startup -- just log warnings. This addresses the gap where admin-configured instance lists could cause performance issues (Presidio O(n*m) comparisons) without any visibility.

5. **Merge function returns `None` for empty list:** `merge_allow_lists()` returns `None` (not `[]`) when the result is empty (both instance list is empty and per-request is `None` or empty). Presidio treats `None` as "skip allow list filtering entirely," while `[]` may still trigger the filtering code path with an empty list. Callers pass the return value directly to `presidio.analyze(allow_list=...)` without additional `or None` checks -- the merge function handles this internally.

6. **Documents endpoint compatibility:** The documents API endpoint already has `_parse_comma_separated()`, which is used for BOTH `entities` and `allow_list` fields. The new `parse_allow_list()` must NOT replace `_parse_comma_separated()` because it adds validation (max 100 terms, max 200 chars) that would incorrectly apply to the `entities` field (which has different semantics and no such limits). Instead: keep `_parse_comma_separated()` as the generic parser in `documents.py` (or extract to utils as a generic `parse_comma_separated()` without validation), and have `parse_allow_list()` call the generic parser then apply allow-list-specific validation. The documents router uses `_parse_comma_separated()` for entities and `parse_allow_list()` for allow_list.

7. **Backward compatibility:** All changes are additive. The `allow_list` form parameter defaults to empty string, so existing requests without allow_list continue to work. API endpoints already accept `allow_list: list[str] | None = None` in their Pydantic models.

### Files to Create
1. `src/redakt/utils.py` -- Shared utility: `parse_comma_separated()`, `parse_allow_list()`, `validate_allow_list()`, `merge_allow_lists()`
2. `src/redakt/templates/partials/allow_list_input.html` -- Shared partial for allow list form group (optional, to avoid duplication across 3 templates)
3. `src/redakt/templates/partials/allow_list_instance_terms.html` -- Instance-wide terms display
4. `tests/test_allow_list_utils.py` -- Unit tests for utility functions
5. `tests/test_allow_list_web.py` -- Integration tests for web UI allow list handlers
6. `tests/e2e/test_allow_list_e2e.py` -- E2E Playwright tests

### Files to Modify
1. `src/redakt/routers/pages.py` -- Add `allow_list` to GET contexts and POST handlers
2. `src/redakt/routers/detect.py` -- Replace merge logic with shared utility, add validation
3. `src/redakt/routers/anonymize.py` -- Replace merge logic with shared utility, add validation
4. `src/redakt/services/document_processor.py` -- Replace merge logic with shared utility, add validation
5. `src/redakt/services/audit.py` -- Add `allow_list_count` to audit functions
6. `src/redakt/templates/detect.html` -- Add allow list input form group
7. `src/redakt/templates/anonymize.html` -- Add allow list input form group
8. `src/redakt/templates/documents.html` -- Add allow list input form group
