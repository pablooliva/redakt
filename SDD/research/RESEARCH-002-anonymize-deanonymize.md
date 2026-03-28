# RESEARCH-002: Anonymize + Reversible Deanonymization

## System Data Flow

### Current Architecture (Feature 1 — PII Detection)

The existing codebase provides the foundation for Feature 2. Key entry points and patterns:

**Request handling:**
- `src/redakt/main.py` — FastAPI app with lifespan-managed `httpx.AsyncClient` on `app.state`
- `src/redakt/routers/detect.py` — Shared `run_detection()` function used by both API and web routes
- `src/redakt/routers/pages.py` — HTMX web UI routes (form submission → HTML fragment response)
- `src/redakt/routers/health.py` — Health checks for both Presidio services

**Presidio integration:**
- `src/redakt/services/presidio.py` — `PresidioClient` with `analyze()` and `check_health()` methods
- Client is a FastAPI dependency via `get_presidio_client(request)` → extracts shared `httpx.AsyncClient` from `app.state`
- Error handling: `ConnectError` → 503, `TimeoutException` → 504, `HTTPStatusError(5xx)` → 502

**Supporting services:**
- `src/redakt/services/language.py` — lingua-py with async wrapper, 2s timeout, "en" fallback
- `src/redakt/services/audit.py` — JSON structured logging to stdout, metadata only (never PII)
- `src/redakt/config.py` — Pydantic `Settings` with `REDAKT_` env prefix

**Data models:**
- `src/redakt/models/detect.py` — `DetectRequest`, `DetectResponse`, `DetectDetailedResponse`, `EntityDetail`
- `src/redakt/models/common.py` — `ErrorResponse`, `HealthResponse`

### Proposed Anonymize Data Flow

```
POST /api/anonymize
  ↓
AnonymizeRequest validation (Pydantic)
  → text (max 512KB), language, score_threshold, entities, allow_list
  ↓
run_anonymization() async function
  ├─ [1] Empty text check → return text unchanged
  ├─ [2] Language resolution (reuse detect.py pattern)
  ├─ [3] Language validation
  ├─ [4] Allow list merge (config + request)
  ├─ [5] Call presidio.analyze() → get entity list with positions
  ├─ [6] Resolve overlapping entities (see Overlap Resolution below)
  ├─ [7] Generate numbered placeholders from resolved entities (Redakt logic)
  │   └─ Group by (entity_type, original_text) → assign <ENTITY_TYPE_N>
  │   └─ Build mapping: { "<PERSON_1>": "John Smith", "<EMAIL_1>": "john@example.com" }
  ├─ [8] Perform text replacement in Redakt (reverse position order)
  │   └─ NO call to Presidio Anonymizer — Redakt does this directly
  └─ [9] Return anonymized text + mapping to client
  ↓
Audit logging (action: "anonymize", entity counts, NO PII)
  ↓
Response: { anonymized_text, mappings, language_detected }
```

**Redakt performs text replacement itself** — Presidio's `/anonymize` REST API is not used because it keys operator configs by entity_type, making it impossible to assign different placeholders to different entities of the same type (e.g., `<PERSON_1>` vs `<PERSON_2>`). See "Key Technical Decision" section below.

**Deanonymization is CLIENT-SIDE** — no server endpoint needed. The browser holds the mapping in an in-memory JavaScript variable (not sessionStorage) and performs string replacement locally. AI agents hold the mapping in memory for the duration of their task.

---

## Presidio Anonymizer API Surface

### POST /anonymize

**Request:**
```json
{
  "text": "My name is John Smith, email john@example.com",
  "anonymizers": {
    "PERSON": { "type": "replace", "new_value": "<PERSON_1>" },
    "EMAIL_ADDRESS": { "type": "replace", "new_value": "<EMAIL_1>" }
  },
  "analyzer_results": [
    { "entity_type": "PERSON", "start": 11, "end": 21, "score": 0.85 },
    { "entity_type": "EMAIL_ADDRESS", "start": 29, "end": 45, "score": 0.99 }
  ]
}
```

**Response:**
```json
{
  "text": "My name is <PERSON_1>, email <EMAIL_1>",
  "items": [
    { "operator": "replace", "entity_type": "PERSON", "start": 11, "end": 21, "text": "<PERSON_1>" },
    { "operator": "replace", "entity_type": "EMAIL_ADDRESS", "start": 29, "end": 37, "text": "<EMAIL_1>" }
  ]
}
```

**Key details:**
- `analyzer_results` is **required** — anonymizer doesn't re-detect, it uses positions from analyzer
- `anonymizers` is **optional** — defaults to `replace` with `new_value` = `<ENTITY_TYPE>`
- Per-entity-type operator config — each type can have a different operator/new_value
- The `replace` operator accepts `new_value` parameter; if omitted, defaults to `<ENTITY_TYPE>`

### POST /deanonymize

Presidio's built-in `/deanonymize` only supports the `decrypt` operator (reversing AES encryption). **Not useful for our use case** — we use `replace` with client-side mapping instead.

### GET /anonymizers

Returns list of supported operators: `replace`, `redact`, `mask`, `hash`, `encrypt`

---

## Placeholder Generation Strategy

### Presidio's InstanceCounterAnonymizer Pattern

Presidio's sample code (`presidio/docs/samples/deployments/openai-anonymaztion-and-deanonymaztion-best-practices/`) shows a custom `InstanceCounterAnonymizer` that generates numbered placeholders. However, this is a **Python library operator** — not available via REST API.

**Redakt must implement placeholder generation and text replacement in its own orchestration layer** after the analyze call:

1. Call Presidio Analyzer → get entities with positions
2. Resolve overlapping entities (see Overlap Resolution section)
3. **Redakt generates placeholders** — assigns `<TYPE_N>` to each unique (entity_type, value) pair
4. **Redakt performs text replacement** — process entities in reverse position order to preserve indices
5. Return anonymized text + mapping to client

### Placeholder assignment rules

**Placeholder key is (entity_type, text_value):**
- "John Smith" as PERSON appears 3 times → all become `<PERSON_1>` (same type + same value = same placeholder)
- "Amazon" as ORGANIZATION → `<ORGANIZATION_1>`; "Amazon" as LOCATION (the river) → `<LOCATION_1>` (same value but different types = different placeholders)
- After overlap resolution, cross-type duplicates on the same span won't occur — but the same value at different positions with different types is possible and handled correctly

**Counter is per entity type:**
- `<PERSON_1>`, `<PERSON_2>`, `<EMAIL_1>`, `<LOCATION_1>`

**Format:** `<{ENTITY_TYPE}_{N}>` where N starts at 1 (more natural for users than 0-based)

### Implementation approach

Since we need per-entity (not per-type) operator configs, and Presidio's `anonymizers` field is keyed by entity_type, we need to handle multiple entities of the same type differently:

**Problem:** Presidio's REST API keys `anonymizers` by entity type — `{"PERSON": {"type": "replace", "new_value": "X"}}`. This means ALL persons get the SAME replacement.

**Solution:** Redakt performs the text replacement itself instead of relying on Presidio's anonymizer endpoint. The flow becomes:

1. Call Presidio Analyzer → get entity positions
2. Generate numbered placeholders per unique entity value
3. Perform text replacement directly in Redakt (process entities in reverse position order to preserve indices)
4. Return anonymized text + mapping

This is simpler and avoids the Presidio Anonymizer limitation. The anonymizer service is still used for the health check but not for the core anonymize flow in Feature 2.

**Alternative:** Call Presidio Anonymizer once per entity (separate calls). This is slower and more complex — not recommended.

**Alternative 2:** Use Presidio Anonymizer with a single generic `replace` operator, then post-process the output. But since Presidio replaces all entities of the same type with the same value, this loses the ability to distinguish between different persons.

**Recommended approach: Redakt-side replacement.** This is what Presidio's own sample code does (InstanceCounterAnonymizer is a Python-side operator, not a REST call).

---

## Stakeholder Mental Models

### Product Team perspective
- Core value proposition: paste text → get anonymized version → paste into LLM → paste LLM response → get deanonymized version
- Two-field UX: "Anonymize" field (input) and "Deanonymize" field (paste LLM output)
- Mapping visible to user for transparency (collapsible section)
- Copy-to-clipboard for anonymized text is critical UX

### Engineering Team perspective
- Stateless backend — mapping lives only on the client
- Reuse existing patterns (language detection, allow lists, audit logging, error handling)
- No new infrastructure dependencies
- **Frontend interaction model:** HTMX handles the anonymize request (POST to server, swap HTML response into DOM). The server response includes the mapping as a JSON blob in a `<script>` tag or data attribute, which JS picks up and stores in an in-memory variable. Deanonymization is purely client-side JS — no HTMX request needed. This is the first feature requiring custom JavaScript alongside HTMX; the two coexist naturally since HTMX handles server interactions and JS handles client-only logic.

### Support Team perspective
- New feature — no production history or existing support patterns
- Anticipated support topics: "my deanonymized text has placeholders still in it" (LLM modified them — known limitation), "I lost my mapping" (navigated away or refreshed — by design, mapping is ephemeral), "why didn't it catch [entity]?" (same as Feature 1 — Presidio's NER accuracy)

### User perspective
- "I paste my text, click anonymize, copy the result, paste into ChatGPT, copy ChatGPT's response, paste it back, click deanonymize, done"
- Must be fast and obvious
- Must handle the case where LLM adds/modifies text around placeholders
- Mapping should auto-expire (session/tab close)

---

## Production Edge Cases

### Duplicate entity values
- "John Smith" appears 3 times → same placeholder `<PERSON_1>` everywhere
- Deanonymization replaces all `<PERSON_1>` occurrences back to "John Smith"

### Overlapping entities

Presidio's analyzer deduplicates same-type overlaps (e.g., "John" contained within "John Smith", both PERSON — the shorter one is removed). However, **cross-type overlaps are preserved** — e.g., "Berlin" as LOCATION [0,6] and "Berlin office" as ORGANIZATION [0,13] would both be returned.

**Redakt must resolve cross-type overlaps before replacement**, because replacing overlapping spans corrupts text (the first replacement shifts character indices, breaking the second).

**Overlap resolution algorithm (applied in Redakt before placeholder assignment):**
1. Sort entities by score descending
2. For each entity, check if it overlaps (start/end range intersection) with any already-accepted entity
3. If overlap found: discard the lower-score entity
4. If scores are equal: keep the entity with the longer span (more specific match)
5. If span lengths are also equal: keep the first encountered (arbitrary but deterministic)

This runs after Presidio's own deduplication, so it only handles the cross-type overlaps that Presidio intentionally preserves.

### Placeholder collision with original text
- The original text may already contain `<PERSON_1>` — especially in technical documentation, anonymization guides, or meta-discussion about PII tools
- **v1 approach:** Accept as a known limitation. The `<TYPE_N>` format is distinctive enough for normal usage. If a collision is detected (the generated placeholder text already exists in the input), the spec could flag a warning in the response, but the replacement still proceeds. Full mitigation (e.g., using a unique delimiter like `[[PERSON_1]]` or adding a random suffix) adds complexity for a rare edge case — defer to v2 if real-world usage reveals this as a problem

### Entity values that are substrings
- "John" is a substring of "John Smith" — position-based replacement (server-side) avoids this issue
- Client-side deanonymization uses exact placeholder match, not substring search of original values

### Client-side deanonymization edge cases

**Replacement order:** Placeholders must be replaced longest-first to avoid partial matches. Example: if mapping contains both `<PERSON_1>` and `<PERSON_12>`, replacing `<PERSON_1>` first with naive `replaceAll` would corrupt `<PERSON_12>` into `OriginalValue2>`. Solution: sort placeholder keys by length descending before replacing, or use regex with word-boundary-like matching (match the full `<TYPE_N>` token including closing `>`).

**LLM-modified placeholders:** LLMs may output `PERSON_1` (no brackets), `<person_1>` (lowercase), or `<PERSON 1>` (space). These will NOT be deanonymized — this is a **known v1 limitation**, documented to the user. The placeholder format `<TYPE_N>` is chosen to be distinctive enough that well-behaved LLMs preserve it verbatim in most cases.

**Phantom placeholders:** If the LLM generates text containing `<PERSON_1>` that wasn't in the original mapping (e.g., discussing the anonymization scheme itself), deanonymization would incorrectly substitute. This is an accepted edge case — extremely unlikely in normal usage.

**Missing placeholders:** If the LLM's response doesn't include some placeholders from the mapping (e.g., the LLM summarized and dropped some entities), those mapping entries are simply unused. No error.

### Empty analyzer results
- Text with no PII → return original text unchanged, empty mapping

### Mixed-language content
- Same limitation as Feature 1 (EDGE-010) — single language per request
- Language detection picks dominant language

### Large text with many entities
- Could have dozens of entities → large mapping object
- Not a real concern — JSON mapping is tiny compared to the text itself

---

## Files That Matter

### New files to create

| File | Purpose |
|------|---------|
| `src/redakt/models/anonymize.py` | `AnonymizeRequest`, `AnonymizeResponse` Pydantic models |
| `src/redakt/routers/anonymize.py` | `POST /api/anonymize` endpoint + shared `run_anonymization()` |
| `src/redakt/services/anonymizer.py` | Placeholder generation + text replacement logic |
| `src/redakt/routers/pages.py` (modify) | Add anonymize/deanonymize web UI routes |
| `src/redakt/templates/anonymize.html` | Anonymize page template |
| `src/redakt/templates/partials/anonymize_results.html` | HTMX partial for results |
| `src/redakt/static/deanonymize.js` | Client-side deanonymization logic |
| `tests/test_anonymize_api.py` | API endpoint tests |
| `tests/test_anonymizer_service.py` | Placeholder generation + replacement unit tests |
| `tests/test_deanonymize_client.py` | Client-side deanonymization tests (if applicable) |

### Existing files to modify

| File | Change |
|------|--------|
| `src/redakt/main.py` | Register anonymize router |
| `src/redakt/services/audit.py` | Add `log_anonymization()` function |
| `src/redakt/templates/base.html` | Add nav link to anonymize page |
| `src/redakt/config.py` | No changes expected — existing settings cover all needs |

### Existing files to reuse (no changes)

| File | Reuse |
|------|-------|
| `src/redakt/services/presidio.py` | `PresidioClient.analyze()` — already implemented |
| `src/redakt/services/language.py` | Language detection — already implemented |
| `src/redakt/config.py` | Settings (thresholds, allow lists, timeouts) — already implemented |

---

## Security Considerations

### Data Privacy
- **Backend never stores PII mapping** — returned to client, then forgotten
- **Audit logs contain metadata only** — entity types/counts, never values
- **Browser storage: in-memory JavaScript variable only** — NOT sessionStorage, NOT localStorage
  - sessionStorage is readable by any script on the same origin (XSS risk), visible in DevTools Storage tab, and accessible to browser extensions — unacceptable for PII in an enterprise GDPR tool
  - In-memory variable is scoped to the current page execution context, not inspectable via the Storage tab, and cleared automatically on navigation or tab close
  - The mapping only needs to survive for one anonymize→copy→paste→deanonymize workflow within a single page load — no persistence needed
- **Mapping expiry:** Automatic — variable is lost on page navigation, refresh, or tab close. A "Clear mapping" button should also be provided for explicit user control.

### Input Validation
- Reuse existing 512KB text limit from `DetectRequest`
- Validate request body structure (Pydantic handles this)
- No new attack surface beyond what Feature 1 already validates

### Placeholder Integrity
- Placeholders use angle brackets `<TYPE_N>` — could conflict with HTML if text is rendered unescaped
- In JSON responses this is fine; in HTML templates, Jinja2 auto-escapes by default

### Browser Security Headers (new requirement for Feature 2)
- **Content-Security-Policy (CSP):** Must be added as FastAPI middleware. Restrict `script-src` to `'self'` and the HTMX CDN origin. Prevents inline script injection and unauthorized external scripts.
- **Subresource Integrity (SRI):** The HTMX CDN `<script>` tag in `base.html` must include an `integrity` attribute with a hash of the expected file. Prevents MITM tampering with the CDN-served script.
- **X-Content-Type-Options:** `nosniff` — prevent MIME-type confusion attacks
- These headers protect the in-memory PII mapping from being exfiltrated by injected scripts

---

## Testing Strategy

### Unit tests
- Placeholder generation: same value + same type → same placeholder; different values → different placeholders
- Placeholder generation: same value + different type → different placeholders (keyed by (type, value))
- Placeholder generation: counter increments per entity type, starting at 1
- Overlap resolution: cross-type overlapping entities resolved by score, then by span length
- Overlap resolution: same-type contained entities already removed by Presidio (verify no double-handling)
- Text replacement: correct substitution at positions
- Text replacement: entities processed in reverse order (preserves positions)
- Edge cases: empty text, no entities, single entity, many entities of same type
- Mapping structure: correct format `{ "<TYPE_N>": "original_value" }`

### Integration tests
- Full flow: text → analyze → generate placeholders → replace → return response
- Presidio Analyzer call with various entity types
- Language detection integration
- Allow list integration (allowed terms not anonymized)
- Audit logging produces correct metadata

### Client-side tests
- Deanonymization: all placeholders replaced with original values
- Deanonymization: handles placeholders that don't appear in text (LLM omitted them)
- Deanonymization: handles text with no placeholders
- Deanonymization: replacement order — `<PERSON_12>` not corrupted by `<PERSON_1>` replacement
- Deanonymization: LLM-modified placeholders (missing brackets, lowercase) are left unchanged (known limitation)
- Copy-to-clipboard functionality

### Edge case tests
- Duplicate entity values in text
- Text already containing placeholder-like patterns
- Very long text with many entities
- Text where all content is PII

---

## Documentation Needs

### User-facing
- How to use the anonymize/deanonymize workflow (web UI walkthrough)
- API endpoint documentation (auto-generated via FastAPI /docs)
- Explanation of client-side mapping (why PII isn't stored server-side)

### Developer
- Placeholder generation algorithm
- Why Redakt does its own replacement instead of using Presidio Anonymizer's replace
- Client-side deanonymization implementation

---

## Open Questions Resolution

From the feature spec, these questions need SDD decisions:

| Question | Recommended Resolution | Rationale |
|----------|----------------------|-----------|
| String replacement vs position-aware deanonymization? | **String replacement** | Placeholders are unique tokens — exact string match is sufficient and simpler |
| Duplicate PII values: same or different placeholder? | **Same placeholder** | "John Smith" × 3 → all `<PERSON_1>`. Simpler mapping, consistent for LLM context |
| Choose anonymization operator? | **Replace only for v1** | Replace with numbered placeholders is the core use case. Other operators (mask, hash) don't support reversible deanonymization |
| Browser-side mapping timeout? | **In-memory JS variable (page lifecycle)** | In-memory variable clears on navigation/refresh/tab close. More secure than sessionStorage (not accessible via DevTools Storage, XSS-resistant). No configurable timeout for v1 — page lifecycle is sufficient. |

## Key Technical Decision: Redakt-Side Replacement

**Decision:** Redakt performs text replacement itself, not via Presidio Anonymizer's `/anonymize` endpoint.

**Why:** Presidio's REST API keys operator configs by entity_type, not by individual entity. All `PERSON` entities get the same replacement value. We need unique per-entity placeholders (`<PERSON_1>`, `<PERSON_2>`), which requires per-entity control.

**Impact:**
- Simpler architecture (one less HTTP call to Presidio per anonymize request)
- Full control over placeholder format and assignment
- Presidio Anonymizer service is still deployed (needed for Feature 3 document support and potentially other operators in future)
- Matches what Presidio's own sample code does (InstanceCounterAnonymizer is Python-side logic)
- **Health check note:** The existing `/api/health` endpoint reports "degraded" if either Presidio service is down. With Feature 2 not using the Anonymizer, a down Anonymizer would show "degraded" even though anonymize works fine. The spec should clarify health check semantics — consider reporting per-feature health or adjusting the degraded status to reflect which features are actually impacted. This is non-blocking for Feature 2 but should be noted.

**Algorithm:**
1. Get analyzer results from Presidio (already deduplicated for same-type containment)
2. Resolve cross-type overlaps: sort by score desc → discard lower-score overlapping entities (tie-break: longer span wins)
3. Assign placeholders: group by (entity_type, original_text) → `<TYPE_N>` where N increments per type starting at 1
4. Replace in reverse position order (preserves character indices)
5. Return anonymized text + mapping dict (mapping: `{ "<TYPE_N>": "original_value" }`)
