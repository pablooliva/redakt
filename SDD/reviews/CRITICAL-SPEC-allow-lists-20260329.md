## Specification Critical Review: Allow Lists

### Executive Summary

This is a well-structured specification with strong research backing and clear traceability. However, it contains several ambiguities that will cause implementation disagreements, a significant contradiction between the research recommendation and the spec's own decision on case sensitivity, an underspecified validation placement that will confuse implementers, and missing edge cases around the interaction between the new shared utility and the existing `_parse_comma_separated()` function. The spec also leaves the audit logging contract partially underspecified and has a gap around what happens when instance-wide terms themselves violate the validation limits.

### Critical Findings

#### HIGH Severity

1. **Validation placement is contradictory across spec sections**
   - REQ-006 says create a shared `merge_allow_lists()` in a new `utils.py`.
   - Implementation Notes Step 3 says "Add validation call in `run_detection()`, `run_anonymization()`, and `process_document()` (or in the Pydantic models via validators)."
   - Implementation Notes Critical Consideration #3 says "Validate in the shared utility (called by both API routers and pages.py), not in Pydantic model validators."
   - Step 6 says pages.py handlers call `validate_allow_list()` and catch `ValueError`.
   - But the API routers (detect.py, anonymize.py) already use Pydantic models (`DetectRequest`, `AnonymizeRequest`) that accept `allow_list: list[str] | None`. Where does validation fire for API requests? The spec says "not in Pydantic model validators" but then never specifies WHERE in the API router path the validation call goes. The `run_detection()` / `run_anonymization()` functions receive already-parsed lists. If validation is in the shared utility, it must be called explicitly in each router -- but the spec only details the pages.py call sites, not the API router call sites.
   - Possible interpretations: (A) Validation in `run_detection()`/`run_anonymization()` before the merge step. (B) Validation as a separate call in each API router endpoint before calling `run_detection()`. (C) Validation inside `merge_allow_lists()` itself.
   - Recommendation: Explicitly specify that `validate_allow_list()` is called inside `run_detection()`, `run_anonymization()`, and `process_document()` on the `allow_list` parameter BEFORE the merge step. This gives a single validation point that both API and web UI paths hit. Alternatively, specify validation inside `merge_allow_lists()` itself, but then the function must raise or return errors, which changes its contract.

2. **Instance-wide terms are exempt from per-request validation limits, but the combined total is uncapped**
   - PERF-001 caps at 100 terms per request. REQ-007 merges instance + per-request with deduplication.
   - But if `settings.allow_list` has 200 terms (admin-configured), and a user sends 100 per-request terms, the merged list sent to Presidio has up to 300 terms. The 100-term cap only applies to per-request input.
   - The spec does not define a cap on the total merged list size. The DoS concern from the research (O(n*m) comparisons in Presidio) applies to the TOTAL list, not just per-request.
   - FAIL-002 addresses invalid instance terms at startup but only mentions empty strings and overly long terms, not excessive count.
   - Recommendation: Either (a) add a cap on total merged terms (e.g., 500), logging a warning if instance + per-request exceeds it, or (b) explicitly state that instance-wide terms are trusted admin input with no count limit, and document the performance implication.

3. **`_parse_comma_separated()` vs `parse_allow_list()` behavioral divergence risk**
   - The existing `_parse_comma_separated()` in `documents.py` returns `None` when input is falsy or all entries are empty. The spec says the new `parse_allow_list()` should have "the same behavior" (Implementation Note #6).
   - But `_parse_comma_separated()` is ALSO used for the `entities` field in the documents endpoint (line 74: `parsed_entities = _parse_comma_separated(entities)`). If `_parse_comma_separated()` is replaced with a shared utility that adds validation (max 100 terms, max 200 chars), this validation would also apply to the `entities` field, which has completely different semantics and limits.
   - The spec says "Consider replacing `_parse_comma_separated()` with the shared utility" but does not address that this function serves double duty.
   - Recommendation: Clarify that `parse_allow_list()` is allow-list-specific (includes validation) and `_parse_comma_separated()` should either remain as-is for entities parsing or be split into a generic parser (no validation) and an allow-list parser (with validation).

4. **Research recommended case-insensitive preprocessing; spec dropped it without justification trail**
   - Research Q3 recommended "Exact match only, but with Redakt-side case-insensitive preprocessing" as a middle ground. It explored multiple approaches (lowercasing, regex mode with escaped terms).
   - The spec chose plain case-sensitive exact match and documented it as a "v1 limitation" (RISK-001), but the research explicitly said case-insensitive preprocessing was the v1 recommendation.
   - This is a significant usability regression from what research recommended. A user adding "Acme Corp" when the text contains "ACME CORP" (common in legal/formal documents) will see no effect.
   - Recommendation: Either implement the research recommendation (case-insensitive comparison at the Redakt layer, e.g., lowercase both sides before sending to Presidio) or explicitly document WHY the research recommendation was rejected (complexity budget, time constraints, etc.).

#### MEDIUM Severity

5. **EDGE-005 deduplication ordering is specified but implementation mechanism is not**
   - Spec says: "Order: instance terms first, per-request appended, duplicates removed."
   - REQ-007 says: "union semantics."
   - PERF-002 says: "using set operations for deduplication."
   - These conflict: Python `set()` does not preserve order. To preserve order AND deduplicate, you need `dict.fromkeys()` or a loop. If the implementer uses `set()` per PERF-002, the ordering guarantee in EDGE-005 is violated.
   - Recommendation: Change PERF-002 to specify `dict.fromkeys()` (which is O(n) and preserves insertion order) instead of "set operations."

6. **`merge_allow_lists()` return type ambiguity**
   - Implementation Notes #5 says: "returns `None` for empty list."
   - The suggested signature says: `merge_allow_lists(instance_list: list[str], per_request_list: list[str] | None) -> list[str] | None`
   - But current code does `merged_allow_list or None` at the Presidio call site (detect.py:92, anonymize.py:85). If `merge_allow_lists()` returns `None` for empty, then callers don't need the `or None` check. But if callers still do `or None`, it's redundant.
   - More critically: when the instance list is empty and per-request is `None`, should the function return `None` or `[]`? The spec says `None`, but the current code path returns `[]` (from `list(settings.allow_list)` when `settings.allow_list` is `[]`), which is then converted to `None` by `or None`. The spec must be precise because Presidio treats `None` and `[]` differently -- `None` skips allow list filtering entirely, while `[]` may still trigger the filtering code path with an empty list.
   - Recommendation: Explicitly state that `merge_allow_lists()` returns `None` (not `[]`) when the result is empty, and that callers should pass the return value directly to Presidio without additional `or None` checks.

7. **Audit logging contract is incomplete for the documents endpoint**
   - REQ-010 says audit entries include `allow_list_count` for detect, anonymize, and document_upload actions.
   - The current `log_document_upload()` has a different signature than `log_detection()`/`log_anonymization()` (it includes `file_type` and `file_size_bytes`).
   - The spec says to "modify `log_detection()`, `log_anonymization()`, `log_document_upload()` to accept optional `allow_list_count: int | None` parameter" but does not specify whether `allow_list_count` should reflect per-request terms only, or the total merged count (instance + per-request).
   - If it reflects the merged total, operators cannot distinguish between instance-wide and per-request usage. If it reflects per-request only, it misrepresents the actual filtering applied.
   - Recommendation: Specify two fields: `allow_list_count` (total merged terms sent to Presidio) and `allow_list_per_request_count` (user-provided terms only). Or explicitly choose one and document why.

8. **No specification for what happens when BOTH validation fails AND a partial result exists**
   - FAIL-001 covers validation failure (422 / inline error). But consider: a user submits text with 101 terms. Should the system reject the entire request, or could it truncate to 100 and warn?
   - The spec implies hard rejection ("Return 422"), but the research mentions no explicit decision on fail-open vs fail-closed for validation.
   - Recommendation: Explicitly state that validation is fail-closed (reject entire request, do not truncate or partially process).

#### LOW Severity

9. **EDGE-004 test uses ASCII-only examples for "Unicode" test**
   - The test approach says: `Unit test with Unicode terms (e.g., "Munchen", "Bundesamt")`.
   - "Munchen" and "Bundesamt" are ASCII strings. The actual Unicode challenge is terms like "Munchen" (with umlaut u), "Stra\u00dfe", or CJK characters. The test examples don't actually exercise Unicode handling.
   - Recommendation: Use actual Unicode characters in test examples: "M\u00fcnchen", "Stra\u00dfe", "\u5317\u4eac\u5e02" (Beijing).

10. **Helper text placement relative to instance terms is ambiguous**
    - REQ-012 specifies helper text: "Comma-separated terms. Must match exactly as they appear in the text (case-sensitive)."
    - REQ-005 specifies instance-wide terms displayed as read-only tags.
    - The HTML template in Implementation Notes shows instance terms ABOVE the input field and helper text BELOW. But which does the user see first? If instance terms are lengthy, the input field and helper text may be pushed below the fold.
    - Recommendation: Minor, but specify that the input field and helper text should appear first, with instance terms displayed below or in a collapsible section.

11. **No specification for keyboard/accessibility behavior of the allow list input**
    - The input is a plain `<input type="text">`. No mention of ARIA labels, keyboard navigation for instance term tags, or screen reader behavior.
    - Recommendation: Add an accessibility note, at minimum ensuring the `<label>` has a proper `for` attribute (already present in template) and instance term tags have `aria-label` attributes.

12. **EDGE-011 (score threshold interaction) has no test**
    - Test approach says "Informational only -- Presidio's internal ordering is not controllable from Redakt."
    - This is correct but the edge case is still real. A user could file a bug saying "I added X to allow list but it's still detected" when the real issue is the term sometimes falls below threshold and sometimes doesn't.
    - Recommendation: At minimum, add a note in the helper text or documentation that allow lists only affect terms that are detected as PII.

### Questionable Assumptions

1. **"100 terms per request is sufficient."** No research data backs this number. Enterprise users with large product catalogs or multi-national office lists could easily need 200+ terms per request. The instance-wide list helps, but requires container restarts. The 100-term limit was stated as a DoS mitigation, but the actual DoS threshold depends on Presidio's performance characteristics (how many entities per document, latency per comparison). Was 100 empirically tested?

2. **"200 characters per term is sufficient."** German compound words and full organization names (e.g., "Bundesanstalt fur Finanzdienstleistungsaufsicht" = 46 chars) are well within this limit. But some legal entity names with addresses could exceed it. The 200-char limit seems reasonable but arbitrary.

3. **"Comma-separated input is adequate UX."** Terms containing commas (e.g., "Smith, John" as it appears in a document) cannot be added via the web UI. The spec does not address this. If a document contains "Smith, John" and the user wants to allow-list it, the comma-separated parsing will split it into "Smith" and "John" -- neither of which will match the full detected span "Smith, John". This is a real enterprise scenario (CSV-formatted names, legal citations with commas).

4. **"No JavaScript required for allow list functionality."** This is stated in the HTMX interaction section. But what about the instance-wide terms display? If there are 50+ instance terms, a collapsible/expandable section would need JS (or CSS-only accordion). The spec does not address the display of large instance lists.

### Research Disconnects

1. **Dropped: QA/Testing perspective on staging vs production config differences.** Research noted "No current mechanism to test allow lists in staging vs. production when the instance-wide list differs between environments." The spec does not address this -- no test fixtures for different instance-wide configurations, no guidance on environment-specific testing.

2. **Dropped: Regex mode consideration.** Research extensively analyzed Presidio's regex mode (partial matching via `re.search()`, `re.IGNORECASE`, timeout handling). The spec correctly excludes regex for v1, but does not add a tech debt item or post-v1 note about whether to expose `allow_list_match` in future versions. The research's analysis of regex mode's surprising partial-match semantics should be preserved as a warning for future implementers.

3. **Dropped: `regex_flags` parameter.** Research noted Presidio's per-request `regex_flags` parameter. Not relevant for v1 (no regex mode), but worth a one-line note in constraints for future reference.

4. **Weakened: Case-insensitive recommendation.** As noted in HIGH #4, the research recommended Redakt-side case-insensitive preprocessing as the v1 approach. The spec downgraded this to a post-v1 consideration without documenting the decision rationale.

5. **Dropped: Secrets management integration concern.** Research's Enterprise IT/Ops perspective raised that env vars may not integrate cleanly with Vault/AWS SSM. The spec's RISK-003 only mentions "container restart causes downtime" but not the secrets management integration gap.

### Risk Reassessment

| Risk ID | Spec Severity | Reassessed Severity | Rationale |
|---------|---------------|---------------------|-----------|
| RISK-001 | Documented limitation | **HIGH** | Case sensitivity will be the #1 user complaint. Research recommended solving it in v1. Deferring it means every user must learn about it the hard way, generating support load. |
| RISK-002 | Documented limitation | Medium (agree) | Partial-match confusion is less common -- most users add full entity names. |
| RISK-003 | Acceptable for v1 | Medium (agree) | Enterprise internal tool, maintenance windows expected. |
| RISK-004 | Mitigated by validation | **Medium-High** | The 100-term per-request cap helps, but the uncapped instance-wide list means an admin misconfiguration could still cause performance issues. No monitoring or alerting is specified. |
| (New) RISK-005 | Not in spec | **Medium** | Comma-containing terms cannot be allow-listed via web UI. This will surface as a bug report from users working with CSV data or legal documents. |
| (New) RISK-006 | Not in spec | **Low-Medium** | The `_parse_comma_separated()` dual-use for entities and allow_list creates a refactoring landmine if a future change to the shared utility breaks entities parsing. |

### Recommended Actions Before Proceeding

1. **[HIGH] Resolve validation placement ambiguity.** Specify exactly where `validate_allow_list()` is called for API requests (inside `run_detection()`/`run_anonymization()` before merge, or in the router endpoint). Update the spec to be consistent across all sections.

2. **[HIGH] Make a deliberate decision on case sensitivity for v1.** Either implement the research recommendation (case-insensitive at Redakt layer) or explicitly document in the spec WHY it was rejected, with acceptance from the product team that this will generate user confusion.

3. **[HIGH] Resolve the set-vs-ordered-dedup contradiction.** Change PERF-002 to specify `dict.fromkeys()` or equivalent order-preserving dedup, not "set operations."

4. **[MEDIUM] Address comma-in-terms limitation.** Either (a) document it as a known limitation of the comma-separated input, (b) support an escape mechanism (e.g., quotes), or (c) switch to a different delimiter for the web UI. At minimum, add it as EDGE-012.

5. **[MEDIUM] Specify whether `allow_list_count` in audit logs is total or per-request only.** This affects operational monitoring and compliance reporting.

6. **[MEDIUM] Cap total merged allow list size or explicitly state it is uncapped.** Address the gap between per-request validation (100 terms) and total merged list (potentially unbounded).

7. **[LOW] Fix Unicode test examples to use actual Unicode characters.** "Munchen" is not a Unicode test.

8. **[LOW] Add EDGE-012 for comma-containing terms in web UI input.** Document as known limitation if not fixing.

---

## Findings Addressed — 2026-03-29

All 12 findings resolved. Spec updated at `SDD/requirements/SPEC-005-allow-lists.md`.

### HIGH Severity (4 findings)

1. **Validation placement contradiction** — RESOLVED. SEC-003, Implementation Step 3, and Critical Consideration #3 now consistently specify: `validate_allow_list()` is called inside `run_detection()`, `run_anonymization()`, and `process_document()` on the per-request `allow_list` parameter BEFORE the merge step. Both API and web UI paths hit this single validation point. Validation is fail-closed. Each caller catches `ValueError` and formats error appropriately.

2. **Instance-wide terms uncapped, combined total unbounded** — RESOLVED. PERF-001 updated: instance-wide terms are trusted admin input with no hard count limit, but startup validation logs a performance advisory if the instance list exceeds 500 terms. FAIL-002 updated to include count check. Implementation Note #4 updated to specify startup validation behavior.

3. **`_parse_comma_separated()` dual-use for entities and allow_list** — RESOLVED. Implementation Note #6 now explicitly states: `parse_allow_list()` must NOT replace `_parse_comma_separated()` because validation limits would incorrectly apply to entities. A generic `parse_comma_separated()` is extracted to utils (no validation); `parse_allow_list()` wraps it with allow-list-specific validation. Step 1 updated with new function signatures.

4. **Case-insensitive preprocessing dropped without justification** — RESOLVED. RISK-001 now includes detailed decision rationale explaining why the research recommendation was deferred: (a) Presidio's exact mode requires knowing the detected span text before comparison, which is only available after Presidio returns; (b) regex mode changes semantics to partial match; (c) post-processing approach is cleaner but exceeds v1 scope. Post-v1 Redakt-side case-insensitive post-filtering is flagged as high priority.

### MEDIUM Severity (4 findings)

5. **Set-vs-ordered-dedup contradiction** — RESOLVED. PERF-002 changed from "set operations" to `dict.fromkeys()` for order-preserving O(n) deduplication. REQ-007 updated to specify `dict.fromkeys()`. EDGE-005 test approach updated.

6. **`merge_allow_lists()` return type ambiguity** — RESOLVED. Implementation Note #5 now explicitly states: returns `None` (not `[]`) when empty; callers pass return value directly to Presidio without additional `or None` checks.

7. **Audit logging contract incomplete** — RESOLVED. REQ-010 now specifies `allow_list_count` is the total merged count (instance + per-request after deduplication). Rationale documented: reflects actual filtering applied, needed for debugging and compliance. Step 7 updated to match.

8. **Fail-open vs fail-closed unspecified** — RESOLVED. FAIL-001 explicitly states validation is fail-closed: entire request rejected, no truncation or partial processing. SEC-003 and Step 3 also state fail-closed.

### LOW Severity (4 findings)

9. **Unicode test examples use ASCII** — RESOLVED. EDGE-004 test approach changed from "Munchen", "Bundesamt" to "München", "Straße", "北京市".

10. **Helper text placement ambiguous** — RESOLVED. Web UI contract template reordered: input field and helper text appear first, instance terms partial appears below. This prevents large instance lists from pushing the input below the fold.

11. **No accessibility specification** — RESOLVED. Input field now includes `aria-describedby` pointing to helper text. Instance terms partial includes `role="group"`, `aria-label` on container, and per-term `aria-label` attributes. REQ-012 updated to require `aria-describedby`.

12. **EDGE-011 score threshold has no test** — RESOLVED. EDGE-011 test approach updated to include a user-facing documentation note: "Allow lists only affect terms that are detected as PII."

### Additional Changes (from Questionable Assumptions, Research Disconnects, Risk Reassessment)

- **EDGE-012 added** — Comma-containing terms in web UI input documented as known v1 limitation with test approach.
- **RISK-005 added** — Comma-containing terms cannot be allow-listed via web UI.
- **RISK-006 added** — `_parse_comma_separated()` dual-use refactoring risk with mitigation.
- **RISK-003 updated** — Secrets management integration gap (Vault/AWS SSM) noted.
- **Technical Constraint #3 updated** — Post-v1 note added about Presidio regex mode semantics (`re.search()` partial match, `regex_flags` parameter) for future implementers.
- **REQ-012 updated** — Helper text now mentions comma limitation.
- **Step 1 updated** — Generic `parse_comma_separated()` added alongside `parse_allow_list()`.
- **Files to Create updated** — `utils.py` lists all four utility functions.
