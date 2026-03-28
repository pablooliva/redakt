# SPEC-002-anonymize-deanonymize

## Executive Summary

- **Based on Research:** RESEARCH-002-anonymize-deanonymize.md
- **Creation Date:** 2026-03-28
- **Author:** Claude (with Pablo)
- **Status:** Approved

## Research Foundation

### Production Issues Addressed
- No prior production issues — this is a new feature (Feature 2)
- Research critical review identified and resolved 7 findings (2 HIGH, 3 MEDIUM, 2 LOW) before specification

### Stakeholder Validation
- **Product Team:** Core value proposition is paste-anonymize-copy-paste to LLM-paste response-deanonymize. Two-field UX with visible mapping. Copy-to-clipboard is critical.
- **Engineering Team:** Stateless backend, reuse existing patterns (language detection, allow lists, audit logging, error handling). HTMX for server interactions, JS for client-only deanonymization. No new infrastructure dependencies.
- **Support Team:** Anticipated support topics: leftover placeholders (LLM modified them), lost mapping (page refresh — by design), missed entities (Presidio NER accuracy).
- **User:** Must be fast, obvious, and handle the case where LLM adds/modifies text around placeholders.

### System Integration Points
- `src/redakt/services/presidio.py` — `PresidioClient.analyze()` for PII detection (reuse as-is)
- `src/redakt/services/language.py` — Language detection (reuse as-is)
- `src/redakt/config.py` — Settings: thresholds, allow lists, timeouts (reuse as-is)
- `src/redakt/services/audit.py` — Audit logging (extend with `log_anonymization()`)
- `src/redakt/routers/detect.py` — Pattern reference for `run_detection()` shared function
- `src/redakt/main.py` — Router registration point
- `src/redakt/templates/base.html` — Navigation link addition

## Intent

### Problem Statement
Users need to safely anonymize text containing PII before pasting it into AI tools, and then restore the original PII values in the AI's response. Currently, Feature 1 only detects PII — it cannot transform it. Users must manually redact and restore PII, which is error-prone and time-consuming.

### Solution Approach
Build a `POST /api/anonymize` endpoint that calls Presidio Analyzer for entity detection, then performs Redakt-side text replacement with numbered placeholders (`<PERSON_1>`, `<EMAIL_ADDRESS_1>`, etc.). The mapping is returned to the client. Deanonymization is purely client-side JavaScript — no server endpoint needed. The backend remains stateless with zero PII at rest.

**Placeholder format decision:** Placeholders use raw Presidio entity type names (e.g., `EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD`, `DATE_TIME`, `IP_ADDRESS`). No abbreviation table is maintained. This avoids a custom mapping layer and keeps placeholder types unambiguous. Note: the feature spec (`docs/v1-feature-spec.md`) uses abbreviated examples like `<EMAIL_1>` — the actual implementation uses the full Presidio type name `<EMAIL_ADDRESS_1>`.

### Expected Outcomes
- Users can anonymize text in one click and get a copyable result with a visible mapping
- Deanonymization restores original values from LLM output via client-side string replacement
- API consumers (AI agents) receive the mapping in the response body and handle deanonymization themselves
- No PII is stored server-side at any point

## Success Criteria

### Functional Requirements
- REQ-001: `POST /api/anonymize` accepts text and returns anonymized text with placeholder mapping
- REQ-002: Same PII value with same entity type produces the same placeholder across the text (e.g., "John Smith" x3 -> all `<PERSON_1>`)
- REQ-003: Same PII value with different entity types produces different placeholders (e.g., "Amazon" as ORG -> `<ORGANIZATION_1>`, "Amazon" as LOC -> `<LOCATION_1>`)
- REQ-004: Placeholder counter is per entity type, starting at 1 (e.g., `<PERSON_1>`, `<PERSON_2>`, `<EMAIL_ADDRESS_1>`)
- REQ-005: Cross-type overlapping entities are resolved before replacement (higher score wins, longer span breaks ties)
- REQ-006: Text with no PII detected returns the original text unchanged with an empty mapping
- REQ-007: Language auto-detection is the default, with manual override available
- REQ-008: Allow list terms (instance-wide + per-request) are excluded from anonymization
- REQ-009: Audit log records anonymization metadata (timestamp, action, entity types/counts, source) — never PII
- REQ-010: Web UI provides two text fields: "Anonymize" (input) and "Deanonymize" (paste LLM output)
- REQ-011: Client-side deanonymization replaces all placeholders with original values using in-memory mapping
- REQ-012: Copy-to-clipboard button for anonymized text output. Use `navigator.clipboard.writeText()` with a fallback to `document.execCommand('copy')` for HTTP contexts. (`navigator.clipboard` requires a secure context — HTTPS or localhost. Enterprise deployments behind HTTP reverse proxies need the fallback.)
- REQ-013: "Clear mapping" button for explicit user control over PII mapping disposal
- REQ-014: Web UI anonymize request uses HTMX (POST to server, swap HTML response)
- REQ-015: Mapping is passed from HTMX response to JS via a `data-mappings` attribute on the result container element. `deanonymize.js` listens for `htmx:afterSwap`, parses the JSON from the attribute into an in-memory variable, then removes the attribute from the DOM to minimize PII exposure in the markup.

### Non-Functional Requirements
- PERF-001: Anonymize endpoint responds within the same latency envelope as detect (dominated by Presidio Analyzer call)
- PERF-002: Client-side deanonymization is instantaneous (string replacement in-memory)
- SEC-001: PII mapping stored only in in-memory JavaScript variable — not sessionStorage, not localStorage
- SEC-002: Content-Security-Policy header restricts `script-src` to `'self'` and the HTMX CDN origin. **No inline scripts or event handlers permitted** — all JS must be in external files. This applies globally (all pages), so existing inline handlers in Feature 1's `detect.html` must be moved to an external `detect.js` file as part of this feature's work.
- SEC-003: Subresource Integrity (SRI) hash on HTMX CDN `<script>` tag
- SEC-004: `X-Content-Type-Options: nosniff` header
- SEC-005: Backend never persists, logs, or caches PII values
- UX-001: Mapping displayed in a collapsible section for transparency
- UX-002: Mapping auto-expires on page navigation, refresh, or tab close (in-memory variable lifecycle)

## Edge Cases (Research-Backed)

### Known Production Scenarios
- EDGE-001: **Duplicate entity values**
  - Research reference: "Production Edge Cases — Duplicate entity values"
  - Current behavior: N/A (new feature)
  - Desired behavior: "John Smith" appears 3x -> all become `<PERSON_1>`, single mapping entry
  - Test approach: Submit text with repeated PII values, verify single placeholder and mapping entry

- EDGE-002: **Cross-type overlapping entities**
  - Research reference: "Overlapping entities" + Critical Review Finding #3
  - Current behavior: Presidio returns both overlapping entities of different types
  - Desired behavior: Resolve by score (higher wins), tie-break by span length (longer wins), then first-encountered
  - Test approach: Mock analyzer results with overlapping spans of different types/scores, verify resolution

- EDGE-003: **Placeholder collision with original text**
  - Research reference: "Placeholder collision with original text"
  - Current behavior: N/A (new feature)
  - Desired behavior: Accept as v1 known limitation. Replacement proceeds normally. Consider adding a warning in the response if a generated placeholder already exists in the input text.
  - Test approach: Submit text containing `<PERSON_1>` literal, verify behavior is documented

- EDGE-004: **LLM-modified placeholders**
  - Research reference: "Client-side deanonymization edge cases" + Critical Review Finding #5
  - Current behavior: N/A (new feature)
  - Desired behavior: Known v1 limitation. Only exact-match placeholders (case-sensitive, with angle brackets) are deanonymized. `PERSON_1`, `<person_1>`, `<PERSON 1>` are NOT replaced.
  - Test approach: Verify deanonymization only replaces exact matches

- EDGE-005: **Deanonymization replacement order**
  - Research reference: "Client-side deanonymization edge cases — Replacement order"
  - Current behavior: N/A (new feature)
  - Desired behavior: Replace longest placeholders first to prevent `<PERSON_1>` from corrupting `<PERSON_12>`
  - Test approach: Create mapping with `<PERSON_1>` through `<PERSON_12>`, verify no corruption

- EDGE-006: **Empty analyzer results**
  - Research reference: "Empty analyzer results"
  - Current behavior: N/A (new feature)
  - Desired behavior: Return original text unchanged, empty mapping `{}`
  - Test approach: Submit text with no PII, verify empty mapping response

- EDGE-007: **Phantom placeholders in LLM output**
  - Research reference: "Phantom placeholders"
  - Current behavior: N/A (new feature)
  - Desired behavior: Accepted edge case. If LLM generates `<PERSON_1>` that matches a mapping entry, it will be deanonymized. Extremely unlikely in normal usage.
  - Test approach: Document as known limitation

- EDGE-008: **Missing placeholders in LLM output**
  - Research reference: "Missing placeholders"
  - Current behavior: N/A (new feature)
  - Desired behavior: Unused mapping entries are silently ignored. No error.
  - Test approach: Deanonymize text that contains only a subset of mapping placeholders

## Failure Scenarios

### Graceful Degradation
- FAIL-001: **Presidio Analyzer unavailable**
  - Trigger condition: Presidio Analyzer service is down or unreachable
  - Expected behavior: Return 503 Service Unavailable (reuse existing `ConnectError` handling from `presidio.py`)
  - User communication: "PII detection service is currently unavailable. Please try again later."
  - Recovery approach: Automatic — next request retries the connection

- FAIL-002: **Presidio Analyzer timeout**
  - Trigger condition: Analyzer request exceeds timeout
  - Expected behavior: Return 504 Gateway Timeout (reuse existing `TimeoutException` handling)
  - User communication: "PII detection timed out. Try with shorter text or try again."
  - Recovery approach: Automatic — next request retries

- FAIL-003: **Text exceeds size limit**
  - Trigger condition: Input text exceeds 512KB
  - Expected behavior: Return 422 Validation Error (Pydantic validation)
  - User communication: Field-level validation error
  - Recovery approach: User submits shorter text

- FAIL-004: **Browser mapping lost (page refresh/navigation)**
  - Trigger condition: User refreshes the page or navigates away after anonymizing
  - Expected behavior: Mapping is gone (in-memory variable cleared). Deanonymization not possible.
  - User communication: UI should warn user that mapping will be lost. "Clear mapping" button confirms disposal.
  - Recovery approach: User re-anonymizes the original text to get a new mapping

## Implementation Constraints

### Context Requirements
- **Maximum context utilization:** <40% during implementation
- **Essential files for implementation:**
  - `src/redakt/routers/detect.py` — Pattern for `run_detection()`, router structure
  - `src/redakt/services/presidio.py` — `PresidioClient.analyze()` interface
  - `src/redakt/models/detect.py` — Request/response model pattern
  - `src/redakt/services/audit.py` — Audit logging pattern
  - `src/redakt/main.py` — Router registration
  - `src/redakt/config.py` — Settings access pattern
  - `src/redakt/templates/base.html` — Template structure, nav links
  - `src/redakt/routers/pages.py` — HTMX page route pattern
- **Files that can be delegated to subagents:**
  - `src/redakt/static/deanonymize.js` — Client-side JS (after partial template is finalized)
  - `src/redakt/static/detect.js` — Extract inline handler from detect.html
  - `tests/test_anonymize_api.py` — API tests (after endpoint is built)
  - `tests/test_anonymizer_service.py` — Unit tests (after service is built)

### Technical Constraints
- Presidio Analyzer REST API is the only PII detection mechanism (no library embedding)
- Presidio Anonymizer `/anonymize` endpoint is NOT used — Redakt performs its own text replacement
- HTMX for server interactions, vanilla JS for client-only deanonymization (no JS framework)
- FastAPI + Pydantic for request/response validation
- Jinja2 templates with HTMX partial swaps
- 512KB max text size (consistent with Feature 1)

## Validation Strategy

### Automated Testing
- Unit Tests:
  - [ ] Placeholder generation: same value + same type -> same placeholder
  - [ ] Placeholder generation: different values -> different placeholders
  - [ ] Placeholder generation: same value + different type -> different placeholders
  - [ ] Placeholder generation: counter increments per entity type, starting at 1
  - [ ] Overlap resolution: higher score wins
  - [ ] Overlap resolution: equal score -> longer span wins
  - [ ] Overlap resolution: same-type contained entities (Presidio already handles, verify no double-handling)
  - [ ] Text replacement: correct substitution at character positions
  - [ ] Text replacement: entities processed in reverse position order
  - [ ] Edge case: empty text -> return unchanged
  - [ ] Edge case: no entities detected -> return original text, empty mapping
  - [ ] Edge case: single entity
  - [ ] Edge case: many entities of same type
  - [ ] Mapping structure: `{ "<TYPE_N>": "original_value" }` format

- Integration Tests:
  - [ ] Full flow: text -> analyze -> generate placeholders -> replace -> response
  - [ ] Language detection integration (auto-detect and manual override)
  - [ ] Allow list integration (allowed terms excluded from anonymization)
  - [ ] Audit logging produces correct metadata (action: "anonymize", entity counts, no PII)
  - [ ] Error handling: Presidio Analyzer down -> 503
  - [ ] Error handling: Presidio Analyzer timeout -> 504
  - [ ] Validation: text exceeds 512KB -> 422

- Edge Case Tests:
  - [ ] Duplicate entity values produce single mapping entry
  - [ ] Text containing placeholder-like patterns (e.g., literal `<PERSON_1>`)
  - [ ] Very long text with many entities

### Manual Verification

Client-side JavaScript is tested manually for v1. No JS test framework is added — `deanonymize.js` is small enough that manual browser verification is sufficient. The core replacement logic should be structured as a pure function for future testability if a JS test runner is introduced later.

- [ ] Deanonymization: all placeholders replaced with original values
- [ ] Deanonymization: placeholders not in text are silently ignored
- [ ] Deanonymization: text with no placeholders returns unchanged
- [ ] Deanonymization: `<PERSON_12>` not corrupted by `<PERSON_1>` replacement (longest-first order)
- [ ] Deanonymization: LLM-modified placeholders (missing brackets, lowercase) left unchanged
- [ ] Copy-to-clipboard works (requires HTTPS or localhost — see note below)
- [ ] Full user flow: paste text -> anonymize -> copy -> paste into LLM -> copy response -> paste back -> deanonymize
- [ ] Mapping visibility in collapsible section
- [ ] "Clear mapping" button disposes mapping and resets UI
- [ ] Page refresh clears mapping (in-memory variable lifecycle)
- [ ] API response structure matches contract (`anonymized_text`, `mappings`, `language_detected`)
- [ ] Feature 1 detect page still works after CSP and inline handler migration
- [ ] Web UI error states display correctly (Presidio down, timeout, validation errors)

### Performance Validation
- [ ] Anonymize endpoint latency dominated by Presidio Analyzer call (Redakt-side replacement adds <10ms overhead)
- [ ] Client-side deanonymization completes in <50ms for typical text sizes

### Stakeholder Sign-off
- [ ] Product Team review
- [ ] Engineering Team review
- [ ] Security Team review (CSP, SRI, in-memory storage)

## Dependencies and Risks

### External Dependencies
- Presidio Analyzer service (port 5002) — must be running for PII detection
- HTMX CDN (`unpkg.com`) — must be reachable for web UI (mitigated by SRI)

### Identified Risks
- RISK-001: **LLM placeholder modification** — LLMs may alter placeholder format, preventing deanonymization. Mitigation: Document as known v1 limitation. The `<TYPE_N>` format is chosen to be distinctive enough that well-behaved LLMs preserve it.
- RISK-002: **Health check misleading** — Presidio Anonymizer health status reports "degraded" when Anonymizer is down, even though Feature 2 works fine (Redakt does its own replacement). Mitigation: Note in docs; consider per-feature health reporting in future.
- RISK-003: **Placeholder collision** — Input text may already contain `<TYPE_N>` patterns. Mitigation: Accept as v1 known limitation; the format is distinctive enough for normal usage. Revisit if real-world usage reveals problems.

## Implementation Notes

### New Files to Create

| File | Purpose |
|------|---------|
| `src/redakt/models/anonymize.py` | `AnonymizeRequest`, `AnonymizeResponse` Pydantic models |
| `src/redakt/routers/anonymize.py` | `POST /api/anonymize` endpoint + shared `run_anonymization()` function |
| `src/redakt/services/anonymizer.py` | Placeholder generation, overlap resolution, text replacement logic |
| `src/redakt/templates/anonymize.html` | Anonymize/deanonymize page template |
| `src/redakt/templates/partials/anonymize_results.html` | HTMX partial for anonymize results |
| `src/redakt/static/deanonymize.js` | Client-side deanonymization + copy-to-clipboard logic |
| `src/redakt/static/detect.js` | Extracted inline handler from `detect.html` (clear results on input) — required by CSP `script-src 'self'` policy |
| `tests/test_anonymize_api.py` | API endpoint integration tests |
| `tests/test_anonymizer_service.py` | Placeholder generation + replacement unit tests |

### Existing Files to Modify

| File | Change |
|------|--------|
| `src/redakt/main.py` | Register anonymize router |
| `src/redakt/services/audit.py` | Add `log_anonymization()` function |
| `src/redakt/templates/base.html` | Add nav link to anonymize page; add SRI to HTMX script tag; add CSP/X-Content-Type-Options meta or middleware |
| `src/redakt/templates/detect.html` | Remove inline `oninput` handler — replaced by external `detect.js` (CSP compliance) |
| `src/redakt/routers/pages.py` | Add anonymize/deanonymize page route |

### API Contract

#### REST API

**`POST /api/anonymize`**

Request:
```json
{
  "text": "Please review John Smith's contract. His email is john@example.com.",
  "language": "auto",
  "score_threshold": null,
  "entities": null,
  "allow_list": []
}
```

All optional fields above show their defaults. `score_threshold: null` uses `settings.default_score_threshold` (currently `0.35`, same as detect). `language: "auto"` triggers auto-detection. `entities: null` means detect all entity types. `allow_list: []` means no per-request exclusions (instance-wide allow list from config still applies).

Response:
```json
{
  "anonymized_text": "Please review <PERSON_1>'s contract. His email is <EMAIL_ADDRESS_1>.",
  "mappings": {
    "<PERSON_1>": "John Smith",
    "<EMAIL_ADDRESS_1>": "john@example.com"
  },
  "language_detected": "en"
}
```

#### Web UI Contract

Follows the established Feature 1 pattern (`GET /detect` page + `POST /detect/submit` form).

**`GET /anonymize`** — Renders `anonymize.html` (full page with both Anonymize and Deanonymize fields).

**`POST /anonymize/submit`** — HTMX form submission. Returns `partials/anonymize_results.html`.

Form fields (matching `Form()` parameters in `pages.py`):
- `text` (str) — Text to anonymize
- `language` (str) — `"auto"`, `"en"`, or `"de"`

HTMX attributes on the form:
```html
<form hx-post="/anonymize/submit" hx-target="#anonymize-results" hx-indicator="#spinner">
```

**Partial response structure (`partials/anonymize_results.html`):**

On success — renders the anonymized text, a copy button, and embeds the mapping as a `data-mappings` JSON attribute on a container element:
```html
<div id="anonymize-output" data-mappings='{"&lt;PERSON_1&gt;": "John Smith"}'>
  <h2>Anonymized Text</h2>
  <pre id="anonymized-text">Please review &lt;PERSON_1&gt;'s contract.</pre>
  <button id="copy-btn">Copy to clipboard</button>
  <details>
    <summary>Mapping (2 entries)</summary>
    <table>...</table>
  </details>
  <p class="meta">Language: en</p>
</div>
```

`deanonymize.js` reads `data-mappings` from `#anonymize-output` after HTMX swaps the partial into the DOM (listen for `htmx:afterSwap` event). The mapping is parsed into an in-memory JS variable. The `data-mappings` attribute is then removed from the DOM to minimize exposure.

On error — renders an error message (same pattern as `partials/detect_results.html`):
```html
<div class="result error"><p>Service is starting up, please wait...</p></div>
```

Error message mapping (same as Feature 1):
- 503 → "Service is starting up, please wait..."
- 504 → "Anonymization timed out. Please try again."
- Text too long → "Text exceeds maximum length of {max} characters."

**Deanonymize UX:**

The deanonymize field and button are on the same `anonymize.html` page, below the anonymize section. They are always visible but disabled until a mapping exists in memory.
- User pastes LLM output into the deanonymize textarea
- User clicks "Deanonymize" button
- JS performs string replacement using the in-memory mapping
- Result appears in a read-only output area below the button
- "Clear mapping" button clears the in-memory variable, disables the deanonymize section, and resets all output areas

**Router import pattern:**

`pages.py` imports `run_anonymization` from `routers/anonymize.py` (same pattern as `run_detection` from `routers/detect.py`). The shared function raises `AnonymizationError` (analogous to `DetectionError`), and `pages.py` catches it to render error HTML.

**AI agent usage note:** API agents consume `POST /api/anonymize` (JSON), receive the mapping in the response body, and perform their own string-replacement deanonymization. No session concept or deanonymize endpoint is needed — the JSON response is self-contained.

### Core Algorithm: Anonymize Flow

1. Validate request (Pydantic)
2. Empty text check -> return text unchanged
3. Resolve language (auto-detect or manual override)
4. Validate language
5. Merge allow lists (config + request)
6. Call `presidio.analyze()` -> get entity list with positions and scores
7. **Resolve cross-type overlaps:**
   - Presidio uses exclusive `end` positions (Python slice semantics: `text[start:end]`).
   - Two entities overlap when `start_a < end_b AND start_b < end_a`. Adjacent entities (`end_a == start_b`) are NOT overlapping.
   - Sort entities by score descending
   - For each entity, check overlap with already-accepted entities using the predicate above
   - Discard lower-score overlapping entity
   - Tie-break: longer span `(end - start)` wins; then first-encountered (stable order)
8. **Generate numbered placeholders:**
   - Group by `(entity_type, original_text)` -> assign `<ENTITY_TYPE_N>`
   - Counter per entity type, starting at 1
   - Build mapping: `{ "<PERSON_1>": "John Smith", "<EMAIL_ADDRESS_1>": "john@example.com" }`
9. **Perform text replacement:**
   - Process entities in reverse position order (highest start index first)
   - Replace each span with its placeholder
   - Reverse order preserves character indices for subsequent replacements
10. Audit log (action: "anonymize", entity counts, no PII)
11. Return `{ anonymized_text, mappings, language_detected }`

### Core Algorithm: Client-Side Deanonymize

1. User pastes text into deanonymize field
2. Get mapping from in-memory JS variable
3. Sort placeholder keys by length descending (longest first)
4. For each placeholder, `replaceAll` exact match in the pasted text
5. Display deanonymized result

### Suggested Implementation Order

1. Models (`anonymize.py`) — request/response schemas
2. Anonymizer service (`anonymizer.py`) — overlap resolution, placeholder generation, text replacement
3. Unit tests for anonymizer service
4. Router (`anonymize.py`) — API endpoint using service
5. Integration tests for API endpoint
6. Audit logging extension
7. Web UI templates + HTMX routes (including `anonymize_results.html` partial with `data-mappings` attribute)
8. Client-side JS (`deanonymize.js` — deanonymize, copy-to-clipboard; `detect.js` — extracted inline handler from Feature 1)
9. Security headers (CSP, SRI, X-Content-Type-Options) + remove inline `oninput` from `detect.html`
10. Manual verification of both Feature 1 (detect) and Feature 2 (anonymize) under CSP

### Areas for Subagent Delegation
- Client-side JavaScript (`deanonymize.js`) — can be delegated after the HTMX partial structure is finalized (depends on `data-mappings` attribute contract and DOM element IDs from `anonymize_results.html`)
- Test files — can be written in parallel once interfaces are defined
- Security headers middleware — independent concern
- `detect.js` extraction — simple, mechanical task (move inline handler to external file)

### Critical Implementation Considerations
- **Do NOT call Presidio Anonymizer `/anonymize`** — Redakt performs text replacement itself (per-entity control not possible via Presidio's per-type API)
- **Overlap resolution must run before placeholder assignment** — overlapping spans corrupt text if both are replaced
- **Reverse position order for replacement** — replacing from end of string backwards preserves character indices
- **Placeholder key is `(entity_type, text_value)`** — not just text value alone
- **Placeholders use raw Presidio entity type names** — `<EMAIL_ADDRESS_1>`, not `<EMAIL_1>`. No abbreviation mapping.
- **CSP + SRI are security requirements**, not nice-to-haves — they protect the in-memory PII mapping from exfiltration
- **CSP is global** — adding `script-src 'self'` breaks any page with inline handlers. Feature 1's `detect.html` has an inline `oninput` handler that must be extracted to `detect.js` before CSP is enabled. Verify all pages after CSP is added.
- **Clipboard API requires secure context** — `navigator.clipboard.writeText()` only works over HTTPS or localhost. Include `document.execCommand('copy')` fallback for HTTP deployments.
