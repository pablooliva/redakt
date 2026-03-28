# Specification Critical Review: Anonymize + Reversible Deanonymization

**Document reviewed:** `SDD/requirements/SPEC-002-anonymize-deanonymize.md`
**Date:** 2026-03-28
**Reviewer role:** Adversarial critical review

## Executive Summary

The specification is thorough and well-structured — it faithfully transforms the research into actionable requirements. However, it contains a security requirement (CSP `script-src 'self'`) that will break the existing Feature 1 detect page (inline `oninput` handler), has no concrete plan for testing client-side JavaScript, underspecifies the web UI routes (no URL patterns or form contract), and carries an inconsistency with the feature spec on placeholder format (`<EMAIL_1>` vs `<EMAIL_ADDRESS_1>`). Six findings total: 2 HIGH, 3 MEDIUM, 1 LOW.

---

## Critical Findings

### 1. **CSP `script-src 'self'` Will Break Feature 1** — HIGH

SEC-002 requires: "Content-Security-Policy header restricts `script-src` to `'self'` and the HTMX CDN origin."

The existing `detect.html` (line 12) uses an inline event handler:
```html
<textarea ... oninput="document.getElementById('results').innerHTML = ''"></textarea>
```

A `script-src 'self' https://unpkg.com` policy blocks all inline scripts and event handlers. Adding CSP as FastAPI middleware affects **all** pages globally. This will silently break Feature 1's detect page — the textarea clear-on-input behavior will stop working with no visible error (CSP violations are console-only).

**Options:**
- **a)** Use `'unsafe-inline'` in `script-src` — weakens CSP significantly, undermines the security rationale
- **b)** Move all inline handlers to external JS files — requires modifying Feature 1's templates and adding a new JS file for detect
- **c)** Use CSP nonces (generate per-request, inject into inline scripts) — more complex but most secure
- **d)** Use `'unsafe-hashes'` with a hash of the specific inline handler — narrow exception, good middle ground

**Recommendation:** The spec must choose an approach and document the cross-feature impact. Option (b) is simplest and aligns with Feature 2's pattern of external JS. If chosen, the spec should add `detect.html` modification and a `detect.js` file to the "Existing Files to Modify" table.

---

### 2. **Client-Side JavaScript Testing Has No Execution Strategy** — HIGH

The spec's Validation Strategy lists 6 client-side test cases (deanonymization logic, copy-to-clipboard, replacement order). The "New Files to Create" table in the research listed `tests/test_deanonymize_client.py`, but the spec dropped it — the spec's file table has no client-side test file.

More fundamentally: **pytest cannot test browser JavaScript**. The spec doesn't specify:
- What test runner to use (Jest? Vitest? Manual-only?)
- Whether `deanonymize.js` should be structured for testability (e.g., module exports)
- Whether these tests are manual verification items or automated

The Client-Side Tests checkboxes in Validation Strategy imply automation, but no tooling or infrastructure is specified to make that possible.

**Recommendation:** Either:
- **a)** Declare client-side tests as manual verification items for v1 (move them to Manual Verification section) and note that automated JS testing is a v2 concern
- **b)** Add a JS test framework (e.g., Vitest) to the project, specify test file location, and add setup to Implementation Notes
- **c)** Structure `deanonymize.js` so the core replacement logic is a pure function testable from Python via a subprocess/JS runtime, and keep the DOM interaction untested

---

### 3. **Web UI Routes Are Underspecified** — MEDIUM

REQ-010 says "Web UI provides two text fields" and REQ-014 says "HTMX POST to server." But the spec never defines:

- **URL patterns:** Is it `GET /anonymize` for the page? `POST /anonymize/submit` for the form? (The detect pattern uses `/detect` and `/detect/submit`, but this isn't stated.)
- **Form field names:** What `name=` attributes do the form inputs use? The detect page uses `name="text"` and `name="language"` as Form() parameters.
- **HTMX partial response structure:** The spec creates `partials/anonymize_results.html` but doesn't describe its content. How does the partial surface the mapping to JS? REQ-015 says "data attribute or embedded JSON" but doesn't commit to one.
- **Deanonymize UX flow:** Is the deanonymize field on the same page? Does the user click a button to trigger deanonymization, or does it happen on paste? Is there a separate "Deanonymize" button?
- **How does `pages.py` call `run_anonymization()`?** The detect page imports `run_detection` from `routers/detect.py`. Will `pages.py` import `run_anonymization` from `routers/anonymize.py`? This creates a router-to-router import dependency.

**Recommendation:** Add a "Web UI Contract" section specifying URL patterns, form fields, HTMX attributes, partial template structure, and the JS-to-mapping handoff mechanism. An implementer should not have to guess any of this.

---

### 4. **Overlap Boundary Definition Is Imprecise** — MEDIUM

The overlap resolution algorithm (step 7 in Core Algorithm) says: "check overlap with already-accepted entities." But it doesn't formally define what constitutes an overlap.

Given entities with `(start, end)` positions:
- **Overlap:** `start_a < end_b AND start_b < end_a` (ranges intersect)
- **Adjacent:** `end_a == start_b` (one ends where the other begins)
- **Contained:** `start_a >= start_b AND end_a <= end_b` (one is inside the other)

Are adjacent entities considered overlapping? In most text processing, they are not (position `end` is exclusive — the character at `end` is not part of the entity). But this should be stated explicitly.

**Example:** "John Smith" at [0, 10] and "Smith" at [5, 10] — clearly overlapping. But "John" at [0, 4] and "Smith" at [5, 10] — adjacent but not overlapping (there's a space at position 4). What about "John" at [0, 5] and "Smith" at [5, 10]? The boundary position 5 is the start of one and end of the other.

**Recommendation:** State that Presidio uses exclusive `end` positions (standard Python slice semantics), and define overlap as `start_a < end_b AND start_b < end_a`. Adjacent entities (`end_a == start_b`) are not overlapping.

---

### 5. **Placeholder Entity Type Format Inconsistency With Feature Spec** — MEDIUM

The feature spec (`docs/v1-feature-spec.md`, line 60) uses abbreviated placeholders:
```
<PERSON_1>, <EMAIL_1>
```

The SPEC-002 API contract uses full Presidio entity type names:
```
<PERSON_1>, <EMAIL_ADDRESS_1>
```

These are different. Presidio returns entity types like `EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD`, `IP_ADDRESS`, `DATE_TIME`, `NRP` (nationality/religion/political group). Using the raw Presidio type name produces verbose placeholders like `<CREDIT_CARD_1>`, `<PHONE_NUMBER_1>`, `<DATE_TIME_1>`, `<IP_ADDRESS_1>`.

This is a design decision, not a bug — but it's undecided:
- **Raw type names:** Accurate, unambiguous, but verbose. `<DATE_TIME_3>` vs `<DATETIME_3>`.
- **Abbreviated names:** Cleaner for users, but requires a mapping table (which types get shortened? is it `EMAIL` or `EMAIL_ADDR`?).

**Recommendation:** Pick one explicitly. If using raw Presidio type names (recommended for simplicity — no mapping table to maintain), update the feature spec for consistency. If abbreviating, define the abbreviation table in the spec.

---

### 6. **Score Threshold Default Mismatch in API Example** — LOW

The API contract example shows `"score_threshold": 0.7`, but the existing config default is `0.35` (`config.py` line 13). The detect endpoint uses `settings.default_score_threshold` when the request field is `None`.

This isn't wrong (the example just shows a non-default value), but it could mislead implementers into hardcoding `0.7`. The spec should note that the default comes from `settings.default_score_threshold`, same as detect.

**Recommendation:** Either change the example to `null` (to show default behavior) or add a comment noting the default is config-driven (currently 0.35).

---

## Questionable Assumptions

1. **"Copy-to-clipboard works in Chrome, Firefox, Safari"** — The `navigator.clipboard.writeText()` API requires a secure context (HTTPS) or localhost. Enterprise internal deployments may use HTTP behind a reverse proxy. If the page is served over HTTP (not localhost), clipboard API will fail silently. The spec should note this constraint or specify a fallback (e.g., `document.execCommand('copy')`, deprecated but works over HTTP).

2. **"Mapping passed via data attribute or embedded JSON"** (REQ-015) — These are architecturally different. A data attribute puts the mapping on a DOM element (`data-mappings='...'`); embedded JSON means a `<script>` tag or `<template>` element with JSON content. The choice affects how JS picks it up, whether it's HTML-escaped, and XSS surface area. This should not be left to the implementer.

3. **"`deanonymize.js` is independent of backend"** — Listed as a subagent delegation candidate. But the JS needs to know the exact mapping format, placeholder format, and how the mapping arrives in the DOM (data attribute vs script tag). It's coupled to the HTMX response structure, which is itself underspecified (Finding #3).

---

## Missing Specifications

1. **Error UX in web UI** — The spec defines FAIL-001 through FAIL-004 for API errors, but doesn't specify what the web UI shows. Feature 1's `pages.py` returns error HTML partials with user-friendly messages. The anonymize web route needs the same treatment — mapping error codes to user messages. Currently unspecified.

2. **Rate limiting / abuse prevention** — Not mentioned. A stateless anonymize endpoint that processes arbitrary text could be abused for DoS via large payloads or rapid requests. The 512KB limit helps, but there's no rate limiting. This may be acceptable for v1 enterprise-internal deployment, but should be called out as a conscious omission.

3. **Accessibility** — No mention of ARIA attributes, keyboard navigation for copy/clear buttons, or screen reader support. Enterprise tools increasingly require WCAG compliance.

---

## Research Disconnects

- Research noted that the health check semantics should be clarified when Anonymizer is down (Finding #7, LOW). The spec mentions this in RISK-002 but doesn't add a requirement to address it — not even a documentation-only requirement. Acceptable for v1 but should be explicit.
- Research mentioned "AI agents hold the mapping in memory for the duration of their task." The spec doesn't have an explicit requirement or documentation plan for how agents consume the mapping. The JSON response format is sufficient, but this should be stated clearly as a non-requirement (agents just parse the response; no session concept needed).

---

## Risk Reassessment

- **RISK-001 (LLM placeholder modification):** Severity is appropriate. This is inherent to the approach and well-documented as a limitation.
- **RISK-003 (Placeholder collision):** Could be upgraded to MEDIUM for enterprise users who may be anonymizing documentation about anonymization (meta-usage). The critical review already flagged this. Adding a response-level warning when collision is detected would be low-effort mitigation.

---

## Recommended Actions Before Proceeding

| Priority | Action |
|----------|--------|
| **HIGH** | Resolve CSP vs inline handler conflict — choose approach (external JS, nonces, or unsafe-hashes) and document cross-feature impact on detect page |
| **HIGH** | Define JS testing strategy — manual-only for v1, or add a test framework. Move client-side test items to the appropriate section |
| **MEDIUM** | Add Web UI contract section — URL patterns, form fields, HTMX targets, partial structure, mapping handoff to JS |
| **MEDIUM** | Define overlap formally — state exclusive `end` position and overlap predicate |
| **MEDIUM** | Decide on placeholder entity type format — raw Presidio names or abbreviated. Align with feature spec |
| **LOW** | Fix score threshold example or add default note |

## Proceed/Hold Decision

**PROCEED WITH REVISIONS** — The core specification is solid. The 2 HIGH findings are design decisions that need to be made (CSP approach, JS testing strategy), not fundamental problems with the architecture. The MEDIUM findings are clarifications that prevent implementer guesswork. None require additional research — they can be resolved by updating the spec directly.

---

## Resolution Log (2026-03-28)

All 6 findings have been resolved in the specification:

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | CSP breaks Feature 1 inline handlers | HIGH | Chose option (b): extract inline handlers to external JS. Added `detect.js` to new files, `detect.html` to modified files. SEC-002 updated to state "no inline scripts permitted." Implementation order updated with CSP verification step. |
| 2 | JS testing has no execution strategy | HIGH | Client-side tests moved to Manual Verification section. No JS test framework for v1. Note added that core replacement logic should be structured as a pure function for future testability. |
| 3 | Web UI routes underspecified | MEDIUM | Added full "Web UI Contract" section: URL patterns (`GET /anonymize`, `POST /anonymize/submit`), form fields, HTMX attributes, partial response structure with HTML examples, error message mapping, deanonymize UX flow, router import pattern, and AI agent usage note. |
| 4 | Overlap boundary imprecise | MEDIUM | Formalized: Presidio uses exclusive `end` (Python slice semantics). Overlap predicate: `start_a < end_b AND start_b < end_a`. Adjacent entities are NOT overlapping. |
| 5 | Placeholder format inconsistency | MEDIUM | Committed to raw Presidio entity type names (`<EMAIL_ADDRESS_1>`, not `<EMAIL_1>`). Updated Solution Approach with explicit format decision and note about feature spec divergence. Updated REQ-004 example. |
| 6 | Score threshold default mismatch | LOW | Changed API example to `"score_threshold": null` with explanation that default comes from `settings.default_score_threshold` (currently 0.35). |

Additionally resolved from Questionable Assumptions and Missing Specifications:
- **Clipboard API HTTPS requirement:** REQ-012 updated with `document.execCommand('copy')` fallback for HTTP contexts.
- **Mapping handoff ambiguity:** REQ-015 committed to `data-mappings` attribute approach with `htmx:afterSwap` listener and attribute removal after parsing.
- **`deanonymize.js` coupling:** Subagent delegation note updated to reflect dependency on partial template structure.
- **Web UI error states:** Error message mapping and HTML structure added to Web UI Contract.
- **AI agent deanonymization:** Clarified in Web UI Contract — JSON response is self-contained, no session concept needed.
- **Feature 1 regression risk:** Added manual verification checklist item for detect page under CSP.

**Updated decision: PROCEED TO IMPLEMENTATION**
