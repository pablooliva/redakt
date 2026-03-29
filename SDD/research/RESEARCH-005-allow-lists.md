# RESEARCH-005-allow-lists

## System Data Flow

### Key Entry Points

1. **API: Detect** -- `src/redakt/routers/detect.py:117` (`POST /api/detect`)
   - Request model accepts `allow_list: list[str] | None` (line 9 of `models/detect.py`)
   - `run_detection()` (line 46) merges instance + per-request allow lists at line 81-83
   - Merged list passed to `presidio.analyze()` at line 92

2. **API: Anonymize** -- `src/redakt/routers/anonymize.py:108` (`POST /api/anonymize`)
   - Request model accepts `allow_list: list[str] | None` (line 9 of `models/anonymize.py`)
   - `run_anonymization()` (line 40) merges instance + per-request allow lists at line 74-75
   - Merged list passed to `presidio.analyze()` at line 85

3. **API: Document Upload** -- `src/redakt/routers/documents.py:62` (`POST /api/documents/upload`)
   - Accepts `allow_list: str | None = Form(None)` as comma-separated form field (line 69)
   - Parsed via `_parse_comma_separated()` (line 74-75)
   - Passed to `process_document()` which merges at `document_processor.py:239-240`
   - Merged list passed to each chunk's `presidio.analyze()` call at line 253

4. **Web UI: Detect** -- `src/redakt/routers/pages.py:31` (`POST /detect/submit`)
   - **GAP: Does NOT accept per-request allow_list from the form.** Calls `run_detection()` without `allow_list` parameter.
   - **Note:** Instance-wide allow list IS still applied. When `allow_list` is not passed (defaults to `None`), `run_detection()` still does `merged_allow_list = list(settings.allow_list)` (detect.py:81), so instance-wide terms are included. The gap is specifically that users cannot add **per-request** terms via the web UI.

5. **Web UI: Anonymize** -- `src/redakt/routers/pages.py:89` (`POST /anonymize/submit`)
   - **GAP: Does NOT accept per-request allow_list from the form.** Calls `run_anonymization()` without `allow_list` parameter.
   - **Note:** Instance-wide allow list IS still applied (same merge logic as detect, anonymize.py:74).

6. **Web UI: Documents** -- `src/redakt/routers/pages.py:149` (`POST /documents/submit`)
   - **GAP: Does NOT accept per-request allow_list from the form.** Calls `process_document()` without `allow_list` parameter.
   - **Note:** Instance-wide allow list IS still applied (document_processor.py:239).

### Data Transformations

```
Per-request allow_list (from API body or form)
        |
        v
+-- Merge Step (in each router/processor) --+
|  merged = list(settings.allow_list)        |
|  if per_request: merged.extend(per_request)|
+--------------------------------------------+
        |
        v
PresidioClient.analyze(allow_list=merged or None)
        |
        v
Presidio Analyzer POST /analyze { "allow_list": [...] }
        |
        v
AnalyzerEngine._remove_allow_list()
  - "exact" mode: keeps results where text[start:end] NOT in allow_list (i.e., removes matches)
  - "regex" mode: keeps results where re.search() does NOT match (partial match, not fullmatch)
        |
        v
Filtered results (PII entities that are NOT allow-listed)
```

### External Dependencies

| Service | Role | Port |
|---------|------|------|
| Presidio Analyzer | Receives merged allow_list, filters PII results | Internal 5001 (docker-compose override; Presidio default is 5002, but `docker-compose.yml:26` sets `PORT=5001`. CLAUDE.md references port 5002 which reflects the Presidio default, not the Redakt deployment.) |
| Presidio Anonymizer | Not involved -- allow lists affect detection only | Internal 5001 |

> **Port discrepancy note:** Presidio Analyzer's default port is 5002 (per Presidio docs and CLAUDE.md), but Redakt's `docker-compose.yml` overrides it to 5001 via `PORT=5001` environment variable (line 26). Both services run on internal port 5001 within the Docker Compose network. The Redakt app connects to the analyzer at `http://presidio-analyzer:5001` (see `config.py:11`). This is intentional to simplify internal networking but differs from upstream defaults.

### Integration Points

1. **Config** -- `src/redakt/config.py:16` -- `allow_list: list[str] = []` with env prefix `REDAKT_`
2. **Presidio Client** -- `src/redakt/services/presidio.py:19-29` -- `analyze()` accepts `allow_list` param, includes in payload
3. **Detect router** -- `src/redakt/routers/detect.py:81-83` -- Merge logic
4. **Anonymize router** -- `src/redakt/routers/anonymize.py:74-75` -- Merge logic (duplicated)
5. **Document processor** -- `src/redakt/services/document_processor.py:239-240` -- Merge logic (duplicated)
6. **Pages router** -- `src/redakt/routers/pages.py` -- Missing allow_list in all 3 web UI submit handlers

## Stakeholder Mental Models

### Product Team Perspective
- Allow lists reduce false positives, improving user trust in anonymization quality
- Enterprise users will have company-specific terms (company name, product names, office locations) that are frequently flagged as PERSON or ORGANIZATION entities
- The instance-wide list eliminates repetitive per-request configuration for known terms
- Per-request lists give users flexibility for ad-hoc suppressions

### Engineering Team Perspective
- The core infrastructure is already implemented: config setting, API models, merge logic, Presidio passthrough
- Three separate merge points exist with duplicated logic (detect, anonymize, document_processor) -- potential for extraction to shared utility
- Web UI routes are completely missing allow_list support -- this is the primary implementation gap
- Presidio supports both "exact" and "regex" allow_list matching, but Redakt currently only exposes "exact"
- The `allow_list_match` parameter from Presidio (`analyzer_request.py:39`) is not surfaced in Redakt's API

### Support Team Perspective
- Users will ask why company names keep getting flagged as PII despite "allow list"
- Case sensitivity is a likely source of confusion: Presidio's exact match is case-sensitive (`text[start:end] in allow_list`)
- Terms must match the exact substring that Presidio detects -- partial matches won't work (e.g., "Acme" won't suppress "Acme Corp" unless "Acme Corp" is in the list)

### User Perspective
- Expects a simple text input (or tag-like UI) to add terms
- Wants to see which terms are currently on the instance-wide list
- Expects allow-listed terms to "just work" regardless of case or minor variations
- May not understand the distinction between instance-wide and per-request lists

### Enterprise IT/Ops Perspective
- Deploying config changes in Kubernetes or Docker Swarm may require rolling restarts, which could violate zero-downtime requirements. The env var approach may not integrate cleanly with secrets management (Vault, AWS SSM).
- For v1, this is acceptable (enterprise-internal tool, maintenance windows expected). Post-v1, a mounted config file or admin API would address this.

### Non-English User Perspective
- German compound words (e.g., "Bundesamt" as part of "Bundesamt fur Migration und Fluchtlinge") create allow list challenges. The exact-match requirement means the full detected span must match, which is especially painful for agglutinative/compound-word languages where entity boundaries may vary.
- For v1, document this limitation. Post-v1, consider case-insensitive matching or Redakt-side preprocessing.

### Compliance/Legal Perspective
- Are allow lists themselves subject to audit? If a compliance officer needs to know which terms were suppressed when, the current approach (env var, no history) provides no audit trail for allow list changes.
- For v1, this is outside scope (no audit logging for config changes). Document as a post-v1 consideration if compliance requirements emerge.

### QA/Testing Perspective
- No current mechanism to test allow lists in staging vs. production when the instance-wide list differs between environments. Tests should validate allow list behavior with both empty and populated instance-wide lists.

## Production Edge Cases

### Potential Issues

1. **Case sensitivity** -- Presidio's exact match is case-sensitive. "acme corp" won't suppress "Acme Corp". Users will expect case-insensitive matching.
2. **Partial entity matches** -- If Presidio detects "John Smith" as PERSON, adding "John" to allow_list won't suppress it. The full detected span must match exactly.
3. **Allow list size limits** -- No current limit on the number of allow_list terms. A very large list could impact Presidio's performance (especially in regex mode where all terms are OR'd into one pattern).
4. **Unicode and whitespace** -- Terms with leading/trailing whitespace, special characters, or Unicode could fail to match expected entities.
5. **Empty strings** -- An empty string in the allow_list could theoretically match zero-length results or cause unexpected behavior.
6. **Duplicate terms** -- Instance-wide + per-request merge does `extend()` without deduplication. Not harmful but wasteful.
7. **Environment variable format** -- `REDAKT_ALLOW_LIST` as env var for a `list[str]` type via pydantic-settings. Must use JSON format: `REDAKT_ALLOW_LIST='["Acme Corp","ProductX"]'`.

### Interaction with Language Detection

Allow lists are passed to Presidio's `/analyze` endpoint alongside the resolved language. The allow list filtering is language-agnostic (it compares text spans regardless of language), but the **detection** that produces those spans IS language-dependent.

**Implications:**
- Presidio uses different NER models per language (spaCy `en_core_web_lg` for English, `de_core_news_lg` for German). A term detected as PERSON in English may not be detected at all in German, making the allow list entry irrelevant for German text.
- Conversely, the same term could be detected as different entity types in different languages (e.g., a German city name might be detected as LOCATION in German but not in English).
- Regex-based recognizers (email, phone, credit card) are typically language-agnostic and will produce the same detections regardless of language. Allow list entries for these will work consistently.
- NER-based recognizers (PERSON, LOCATION, ORGANIZATION) are language-specific. Allow list entries for these may only work for one language.

**Recommendation for v1:**
- Document this as a known behavior: allow lists suppress detected entities regardless of language, but what gets detected depends on the language.
- Add test cases for allow list terms in both English and German contexts to verify behavior.
- Consider this when writing user-facing docs: "Allow lists work best for terms that are consistently detected across your expected languages."

### Interaction with Score Threshold

Allow list filtering happens AFTER score thresholding in Presidio's pipeline (`analyzer_engine.py:258-264`). The sequence is:
1. All recognizers run and produce `RecognizerResult` objects with scores
2. Duplicate results are removed (`remove_duplicates`)
3. Low-score results are removed (`__remove_low_scores` with `score_threshold`)
4. Allow list filtering removes entities whose text matches an allow_list entry

**Implications:**
- If a term scores below the threshold (e.g., 0.30 when threshold is 0.35), it is already removed before allow list filtering. Adding it to the allow list has no effect -- it was never going to be flagged.
- If a term fluctuates near the threshold across different texts (e.g., sometimes 0.32, sometimes 0.38), users may see inconsistent behavior: sometimes the term is detected (and could be suppressed by allow list), sometimes it is not detected at all. The allow list only helps when the term IS detected.
- **Recommendation for user-facing docs:** Explain that allow lists suppress terms that ARE detected as PII. If a term is not consistently detected, adjusting the score threshold (lower = more sensitive) may be more appropriate than an allow list entry.
- **Recommendation for testing:** Test edge cases where terms are near the score threshold to verify consistent UX.

### Presidio-Specific Behaviors

- **`allow_list_match="exact"`** (default) -- Checks `word not in allow_list` where `word = text[result.start:result.end]`. Entities whose extracted text is NOT in the allow_list are kept. This is a simple O(n) list membership check (not a set).
- **`allow_list_match="regex"`** -- Joins all items with `|`, compiles as regex with `re.DOTALL | re.MULTILINE | re.IGNORECASE` (configurable via `regex_flags` parameter), then applies **`re.search()`** (NOT `re.fullmatch()`) against detected entity text. This means **partial matches will suppress entities** -- e.g., a regex allow_list entry of `"Corp"` would suppress an entity `"Acme Corp"` because `re.search("Corp", "Acme Corp")` succeeds. This is far more permissive than exact mode.
- Regex mode is inherently case-insensitive due to `re.IGNORECASE` flag (but `regex_flags` are configurable per-request via the `regex_flags` parameter on `analyzer_request.py:40`)
- Regex mode has error handling: if the regex times out (`TimeoutError`), the entity is kept (not suppressed) and a warning is logged
- **Performance note**: Exact mode uses Python list `in` operator, which is O(n) per entity. For large allow lists with many detected entities, this becomes O(n*m). Presidio does NOT convert the list to a set internally.

## Files That Matter

### Core Logic (Already Implemented)

| File | Lines | Role |
|------|-------|------|
| `src/redakt/config.py` | 16 | Instance-wide `allow_list: list[str] = []` |
| `src/redakt/services/presidio.py` | 19-29 | `analyze()` passes `allow_list` to Presidio |
| `src/redakt/models/detect.py` | 9 | `allow_list` field on DetectRequest |
| `src/redakt/models/anonymize.py` | 9 | `allow_list` field on AnonymizeRequest |
| `src/redakt/routers/detect.py` | 46-93 | `run_detection()` with merge logic |
| `src/redakt/routers/anonymize.py` | 40-85 | `run_anonymization()` with merge logic |
| `src/redakt/routers/documents.py` | 62-76 | Document upload with comma-separated parsing |
| `src/redakt/services/document_processor.py` | 181-254 | `process_document()` with merge logic |

### Gaps (Need Implementation)

| File | Lines | Gap |
|------|-------|-----|
| `src/redakt/routers/pages.py` | 31-81 | `detect_submit()` -- no per-request allow_list form field (instance-wide DOES work) |
| `src/redakt/routers/pages.py` | 89-139 | `anonymize_submit()` -- no per-request allow_list form field (instance-wide DOES work) |
| `src/redakt/routers/pages.py` | 149-253 | `documents_submit()` -- no per-request allow_list form field (instance-wide DOES work) |
| `src/redakt/templates/detect.html` | -- | No allow_list UI input for per-request terms |
| `src/redakt/templates/anonymize.html` | -- | No allow_list UI input for per-request terms |
| `src/redakt/templates/documents.html` | -- | No allow_list UI input for per-request terms |

### Tests (Existing Coverage)

| File | Coverage |
|------|----------|
| `tests/test_presidio_client.py:51-65` | Tests `analyze()` with allow_list param |
| `tests/test_detect.py:76-89` | Tests detect allow_list merge (instance + per-request) |
| `tests/test_anonymize_api.py:68-81` | Tests anonymize allow_list merge |
| `tests/test_documents_api.py:198-209` | Tests document upload allow_list pass-through |

### Configuration

| File | Role |
|------|------|
| `src/redakt/config.py` | `Settings` with `allow_list` field, `env_prefix="REDAKT_"` |
| `docker-compose.yml` | Environment variables for redakt service |

## Security Considerations

### Authentication/Authorization
- No auth in v1. The instance-wide allow list is admin-configured via environment/config, not via API.
- Per-request allow lists are untrusted user input -- but the impact of a malicious allow_list is limited: worst case, PII is not detected (privacy reduction, not data leak).

### Data Privacy
- Allow list terms are **typically** not PII (company names, product names, locations), but this is not guaranteed. Enterprises might add employee names, client names, or internal project codenames that could constitute PII or commercially sensitive data depending on context.
- Allow list terms should NOT be logged in audit logs (they could reveal organizational structure, client relationships, or employee identities).
- Instance-wide allow list is config-level data, not user data. However, it may still contain sensitive organizational information and should be treated with appropriate access controls.
- Per-request allow list terms are transient (not persisted) but could be sensitive.

### Input Validation
- **Per-request allow_list**: Currently no validation on individual terms (length, character set, count).
  - **HARD REQUIREMENT for v1 (not a follow-up):** Implement validation limits before shipping the Web UI:
    - Max terms per request: 100
    - Max term length: 200 characters
    - Strip leading/trailing whitespace from each term
    - Reject empty strings after stripping
  - **Rationale:** Without these limits, a malicious or buggy API client could send thousands of long strings, forcing Presidio to iterate through all of them for every detected entity. Since Presidio uses O(n) list `in` checks (exact mode) or O(n) regex patterns (regex mode) for each detected entity, an allow_list with 10,000 entries on a document with 500 detected entities = 5 million comparisons. This is a denial-of-service vector against the shared Presidio Analyzer service.
- **Instance-wide allow_list**: Set via environment variable or config. Should be validated at startup (non-empty strings after strip).
- **Regex patterns (if supported)**: Must be validated for compilation errors before passing to Presidio. Presidio handles timeout internally but pattern compilation errors would propagate.
- **XSS considerations**: The implementation plan calls for displaying instance-wide allow list terms as read-only tags in the Web UI. While Jinja2's auto-escaping (enabled by default for HTML templates) will handle HTML entities (`<`, `>`, `"`, `'`), this contradicts the earlier claim of "no XSS risk." The risk is low with Jinja2 auto-escaping, but the assertion should be qualified: allow list terms rendered in HTML are safe **as long as Jinja2 auto-escaping is active** (which it is for all `.html` templates in this project).

## Testing Strategy

### Unit Tests

1. **Allow list merge logic** -- Test that instance-wide and per-request lists are correctly merged
   - Instance only, per-request only, both, neither, duplicates
2. **Empty allow list handling** -- `merged_allow_list or None` correctly sends None to Presidio when empty
3. **Comma-separated parsing** (document endpoint) -- Handles trailing commas, whitespace, empty items

### Integration Tests

1. **API endpoints** -- All three endpoints (`/detect`, `/anonymize`, `/documents/upload`) correctly pass merged allow_list
2. **Web UI routes** -- Once implemented, verify allow_list form fields are accepted and merged
3. **Config-only allow list** -- No per-request terms, instance-wide terms still passed

### Edge Cases to Test

1. Case sensitivity: "acme" vs "Acme" in allow_list
2. Term that matches a partial entity span
3. Very long allow list (100+ terms) -- verify performance does not degrade significantly
4. Unicode terms
5. Empty string in allow_list
6. Allow list with regex characters when in exact mode (should be safe)
7. Web UI: comma-separated input with various edge cases (trailing comma, spaces, empty entries)
8. **Language-specific allow list behavior**: Same allow_list term with English text vs German text (verify NER-dependent detection differences)
9. **Score threshold boundary**: Term near score threshold (e.g., 0.35) with and without allow_list entry
10. **Input validation**: Reject requests with >100 terms, terms >200 chars, empty-after-strip terms
11. **XSS in allow list terms**: Terms containing `<script>`, `<img onerror=...>`, etc. rendered safely in UI via Jinja2 auto-escaping

### E2E Tests

- Verify allow_list input appears in web UI forms
- Submit text with allow_list terms, confirm they are not flagged
- Verify instance-wide allow list works with `REDAKT_ALLOW_LIST` env var
- Test allow_list with English text containing a known PERSON name in the allow list
- Test allow_list with German text containing a known PERSON name in the allow list (may behave differently due to language-specific NER)
- Verify case sensitivity behavior (document that "acme corp" does not suppress "Acme Corp" in v1)

## Documentation Needs

### User-Facing Docs
- How to configure instance-wide allow list (env var format: `REDAKT_ALLOW_LIST='["term1","term2"]'`)
- How to add per-request terms via the UI (comma-separated input field)
- How to add per-request terms via the API (JSON array in request body)
- Explanation that matching is exact and case-sensitive (for v1)
- Tips: use the exact term as it appears in text; partial matches won't work

### Developer Docs
- API contract: all endpoints accept `allow_list` in request body
- Document upload uses comma-separated string (multipart form limitation)
- Instance-wide config via `REDAKT_ALLOW_LIST` environment variable
- Merge precedence: instance-wide + per-request are combined (union), not overridden

### Configuration Docs
- `REDAKT_ALLOW_LIST` -- JSON array of strings (default: `[]`)
- Docker compose example: `REDAKT_ALLOW_LIST=["Acme Corp","Berlin HQ","ProductX"]`
- Config file alternative (if supported): `allow_list = ["term1", "term2"]`

## Open Questions Analysis

### Q1: Where is the instance-wide allow list stored?

**Current state:** Already implemented in `config.py:16` as `allow_list: list[str] = []` with env prefix `REDAKT_`. Can be set via:
- Environment variable: `REDAKT_ALLOW_LIST='["Acme Corp","ProductX"]'`
- Docker compose: in the `environment` section of the redakt service

**Recommendation for v1:** Env var is sufficient. No need for a separate config file or mounted volume.

**Rationale:** Pydantic-settings already handles JSON-encoded list types from env vars. This is consistent with all other settings (thresholds, URLs, supported languages). Restart is required to change the list.

**Restart impact note:** Container restart requires Presidio Analyzer to reload its NLP models (`start_period: 30s` in healthcheck), so updates to the allow list may cause 30+ seconds of downtime. For v1, this is acceptable because: (a) no auth system means no admin API is safe, (b) enterprise internal tools typically have maintenance windows, (c) the allow list is expected to stabilize quickly after initial setup. However, this assumption should be validated against actual enterprise usage patterns -- active enterprises may need to add/remove terms weekly as projects and office locations change.

**Post-v1 consideration:** If the list changes frequently or downtime is unacceptable, options include: a mounted JSON/YAML config file (watched with `watchfiles` for hot-reload without restart), a REST admin endpoint (requires auth), or integration with secrets management (Vault, AWS SSM) for Kubernetes/Docker Swarm deployments.

### Q2: Should there be a UI for managing the instance-wide list?

**Recommendation for v1:** No dedicated admin UI. Read-only display in the web UI (show current instance-wide terms as pre-populated tags that users can see but not edit).

**Rationale:**
- No auth system in v1 -- any UI for editing the instance-wide list would be accessible to all users
- Env var + container restart is the expected deployment workflow for enterprise internal tools
- Displaying the current instance-wide terms in the UI is useful so users know what's already covered

### Q3: Should allow list support regex patterns or just exact matches for v1?

**Recommendation for v1:** Exact match only, but with **Redakt-side case-insensitive preprocessing**.

**Rationale:**
- Presidio supports both "exact" and "regex" via `allow_list_match` parameter
- Regex adds complexity: patterns can be slow (ReDoS risk via `re.search()`), users can write invalid patterns, and `re.search()` does partial matching (not fullmatch) which is more permissive than users would expect
- Pure exact match covers the primary use case (company names, product names, locations), BUT case sensitivity is a major usability concern: "Acme Corp" won't suppress "acme corp" or "ACME CORP"
- **Middle ground for v1:** Implement case-insensitive exact matching at the Redakt layer by lowercasing both the allow_list terms and the detected entity text before comparison. This can be done by sending a lowercased allow_list to Presidio AND lowercasing the text sent for analysis... OR by using Presidio's regex mode with properly anchored patterns (e.g., `re.escape(term)` for each term, relying on `re.IGNORECASE`).
- **Simpler approach:** Use Presidio's regex mode with escaped terms: `[re.escape(term) for term in allow_list]`. Since `re.search()` is used (not `fullmatch()`), escaped exact terms will match as substrings. However, this changes semantics (substring match). For true case-insensitive exact match, the best approach is Redakt-side: normalize both sides to lowercase before passing to Presidio's exact mode. This requires Redakt to lowercase the text in the allow_list AND have Presidio compare against the lowercased entity span -- which Presidio doesn't support natively.
- **Recommended v1 approach:** Stay with Presidio's exact mode but clearly document case sensitivity as a v1 limitation. Add a note in the UI near the allow_list input explaining that terms must match exactly as they appear in the text (including capitalization).

**Post-v1 consideration:** Implement case-insensitive matching at the Redakt layer (post-process Presidio results to check allow_list membership case-insensitively), or expose `allow_list_match` parameter with proper input validation.

## Implementation Assessment

### What Already Exists (Backend)

The core allow_list infrastructure is **already fully implemented** for the API endpoints:

1. Config setting with env var support
2. Pydantic models with `allow_list` field on detect and anonymize requests
3. Merge logic in all three processing pipelines (detect, anonymize, documents)
4. Presidio client passes allow_list correctly
5. Tests cover merge behavior for all three API endpoints

### What's Missing

1. **Web UI per-request allow_list input** -- None of the three web forms (detect, anonymize, documents) have an allow_list input field. Note: instance-wide allow list terms ARE applied to web UI requests (the merge logic in `run_detection()`/`run_anonymization()`/`process_document()` always starts with `list(settings.allow_list)`). The gap is specifically per-request terms from the user.
2. **Web UI route handlers** -- `pages.py` submit handlers don't accept the `allow_list` form parameter (but they don't need to pass instance-wide terms -- those are already handled by the shared functions)
3. **UI display of instance-wide terms** -- No visibility into what terms are pre-configured
4. **Input validation** -- No limits on term count, term length, or character filtering. **This is a hard requirement for v1, not a follow-up** (see Security Considerations for DoS analysis).
5. **Deduplicated merge** -- Currently uses `extend()` without dedup (low priority, no functional impact)
6. **Shared merge utility** -- Merge logic is duplicated in 3 places (detect router, anonymize router, document processor)

### Recommended Implementation Order

1. **Add input validation** -- Max terms (100), max term length (200 chars), strip whitespace, reject empty strings. **This is a hard requirement, not a follow-up.** Apply to both API and Web UI paths.
2. **Extract shared merge function** -- DRY up the allow_list merge logic into a utility (e.g., in `config.py` or a new `utils.py`)
3. **Add UI input to all three templates** -- Comma-separated text input or tag-style input
4. **Update pages.py handlers** -- Accept `allow_list` form field, parse, pass to processing functions
5. **Add instance-wide terms display** -- Show pre-configured terms as read-only in UI (ensure Jinja2 auto-escaping for XSS safety)
6. **Add/update tests** -- Web UI integration tests, validation tests, language-specific tests, E2E tests
7. **Update docker-compose.yml** -- Add example `REDAKT_ALLOW_LIST` env var (commented out)

### Estimated Scope

This is a **small-to-medium feature** -- the backend plumbing is done. Primary work is:
- UI additions (3 templates + 1 partial for term display)
- Pages router updates (3 handlers)
- Shared utility extraction (optional but recommended)
- Input validation
- Tests (~15-20 new tests)
- E2E tests for web UI

## Presidio API Reference

### `POST /analyze` allow_list Parameters

From `presidio/presidio-analyzer/presidio_analyzer/analyzer_request.py`:

```python
self.allow_list = req_data.get("allow_list")           # List[str] or None
self.allow_list_match = req_data.get("allow_list_match", "exact")  # "exact" or "regex"
self.regex_flags = req_data.get("regex_flags", re.DOTALL | re.MULTILINE | re.IGNORECASE)  # configurable per-request
```

Note: `regex_flags` is configurable per-request via the Presidio REST API. The defaults (`DOTALL | MULTILINE | IGNORECASE`) are applied when not specified. Redakt does not currently expose this parameter.

From `presidio/presidio-analyzer/presidio_analyzer/analyzer_engine.py:349-399`:

- **Exact mode**: `if word not in allow_list` -- simple O(n) list membership check per entity
- **Regex mode**: `re_compiled.search(word, timeout=REGEX_TIMEOUT_SECONDS)` where pattern = `"|".join(allow_list)` -- **partial match** via `re.search()`, NOT full match. This means any substring match suppresses the entity.
- **Error handling**: If regex times out (`TimeoutError`), entity is kept (logged as warning, not suppressed). Pattern compilation errors would raise before matching.
- **Position**: Allow list filtering happens AFTER duplicate removal and score thresholding
