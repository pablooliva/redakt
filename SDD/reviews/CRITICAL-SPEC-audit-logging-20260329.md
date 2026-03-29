## Specification Critical Review: Audit Logging

### Overall Severity: MEDIUM

The spec is thorough in documenting existing behavior and fixing known bugs, but contains several ambiguities, a significant architectural concern around the `entities_found` change, and missing specifications that will cause implementation confusion.

---

### Ambiguities That Will Cause Problems

1. **[REQ-004] `entities_found` with duplicates -- where does the non-deduplicated list come from?** -- SEVERITY: HIGH
   - The spec says call sites must pass "the full entity type list with duplicates" instead of the deduplicated/sorted set.
   - Problem: The deduplication happens at different levels for each code path, and in some cases the non-deduplicated list does not exist at the call site:
     - **detect.py**: `entity_types` is computed at line 110 as `sorted(set(...))` from `results` (Presidio raw output). The raw `results` list is available, so `sorted(r["entity_type"] for r in results)` is feasible.
     - **anonymize.py**: `entity_types` is returned by `anonymize_entities()` in `anonymizer.py:127`, which does `sorted(set(e["entity_type"] for e in resolved))`. The call site at `anonymize.py:108` receives the tuple `(anonymized_text, mappings, entity_types)`. The raw `results` from Presidio are NOT available at the audit call site (line 139-145) -- only the already-deduplicated `result.entity_types`. The `resolved` entities (post-overlap-resolution) are internal to `anonymize_entities()`.
     - **documents.py**: `entity_types` comes from `document_processor.py:288`, also `sorted(set(...))`. The raw per-chunk entities are not available at the audit call site.
     - **pages.py** (anonymize, documents): Same problem -- they use `result.entity_types` and `result.pop("entity_types")`, both already deduplicated.
   - Possible interpretations: (A) Modify `anonymize_entities()` and `process_document()` to also return the non-deduplicated list. (B) Pass the raw Presidio results alongside the deduplicated list. (C) Only preserve duplicates where feasible (detect) and accept deduplication elsewhere.
   - Recommendation: The spec must specify exactly which functions need signature changes to propagate the non-deduplicated list. This is not a "change the call site" task -- it requires modifying `anonymize_entities()` return value and `process_document()` return dict. The spec's implementation notes (Step 6) gloss over this by saying "compute sorted-with-duplicates list for audit" but the raw data is not accessible at most call sites. This will cause implementation arguments.

2. **[REQ-005] `operator` field -- single string vs reality of document processing** -- SEVERITY: MEDIUM
   - The spec says `operator` is always `"replace"` for v1, as a string.
   - Problem: For `document_upload`, the anonymization happens inside `process_document()` which calls `anonymize_entities()` per chunk. The audit call site (`documents.py:142-150`) does not know what operator was used -- it hardcodes the value. This is technically fine for v1, but the spec does not explicitly state "hardcode `operator='replace'` at the call site." An implementer might look for the operator in the `result` dict (where it does not exist).
   - Recommendation: Explicitly state in implementation notes that `operator="replace"` is hardcoded at each call site, not derived from processing results.

3. **[REQ-006/REQ-007] `setup_logging()` signature change for file config** -- SEVERITY: MEDIUM
   - The spec says `setup_logging()` needs to accept file config parameters, and notes "extend the signature to accept the file config parameters."
   - Problem: Currently `setup_logging(log_level: str)` is called from `main.py:39` as `setup_logging(settings.log_level)`. The spec says to pass file config but does not specify whether to: (A) pass individual parameters (`audit_log_file`, `audit_log_max_bytes`, `audit_log_backup_count`), (B) pass the entire `settings` object, or (C) import `settings` directly inside `setup_logging()`.
   - Option (C) would mean `setup_logging()` has a hidden dependency on `settings`, making it harder to test. Option (A) makes the signature verbose. Option (B) couples to the Settings class.
   - Recommendation: Specify the approach. Given that tests need to control these values, option (A) with explicit parameters is most testable but the spec should say so.

4. **[REQ-003/REQ-004] Parameter naming in function signatures** -- SEVERITY: LOW
   - The spec says to rename the JSON output keys from `entity_types` to `entities_found` and `language` to `language_detected`. Step 4 of implementation notes says "The function signature parameter names should also be renamed for clarity."
   - Problem: Renaming function parameters is a breaking change to all call sites. The spec lists the 6 call sites for the audit functions but does not account for the `DetectionResult` and `AnonymizationResult` classes that also use `entity_types` and `language` as attribute names. Are those renamed too? They are used in both audit and response paths.
   - Recommendation: Clarify that the rename is ONLY in the `_emit_audit()` function signature and the JSON output keys, NOT in `DetectionResult`, `AnonymizationResult`, or other intermediate data structures.

---

### Missing Specifications

1. **How to propagate non-deduplicated entity lists through anonymize and document paths** -- SEVERITY: HIGH
   - Why it matters: The spec requires `entities_found` with duplicates (REQ-004) but the anonymization and document processing pipelines only expose deduplicated lists. The implementation requires changes to `anonymize_entities()` return type and `process_document()` return dict -- neither of which is listed in "Files to Modify."
   - Suggested addition: Add `src/redakt/services/anonymizer.py` and `src/redakt/services/document_processor.py` to "Files to Modify" with specific guidance on returning the non-deduplicated list alongside the deduplicated one.

2. **What happens to existing tests that mock audit functions with old parameter names** -- SEVERITY: MEDIUM
   - Why it matters: The spec lists 4 test files to modify (test_detect.py, test_anonymize_api.py, test_documents_api.py, test_allow_list_web.py) but does not specify the nature of the changes. These tests mock `log_detection(entity_types=..., language=...)` and assert on kwargs. After the rename, they need `entities_found=...` and `language_detected=...`. If the function signature parameters are renamed, every mock assertion breaks.
   - Suggested addition: Explicitly state that all mock assertions must be updated from `entity_types` to `entities_found` and `language` to `language_detected`, and that new assertions for `operator` must be added to anonymize and document tests.

3. **No specification for `allow_list_count` behavior in the document upload path** -- SEVERITY: LOW
   - The `documents.py:141` does `result.pop("allow_list_count", None)`. The document processor returns this value. The spec does not address whether this should change or stay the same. It is implicitly covered by "existing behavior, no change" in REQ-012, but worth making explicit since the spec touches every other field.

4. **No specification for what `entity_count` represents in document_upload** -- SEVERITY: LOW
   - For detect, `entity_count = len(results)` (number of Presidio matches).
   - For anonymize, `entity_count = len(result.mappings)` (number of unique placeholder mappings, NOT number of entity occurrences).
   - For document_upload, `entity_count = len(result["mappings"])` (same as anonymize).
   - This means `entity_count` has different semantics across actions: for detect it counts all occurrences, for anonymize/document it counts unique mappings. If "John Smith" appears 3 times, detect logs `entity_count: 3` but anonymize logs `entity_count: 1` (one mapping `<PERSON_1>: John Smith`). The spec does not acknowledge this inconsistency. With the new `entities_found` containing duplicates, the discrepancy becomes more visible: `entity_count: 1, entities_found: ["PERSON", "PERSON", "PERSON"]` would be confusing.
   - Suggested addition: Define `entity_count` consistently, or document the semantic difference per action.

5. **Missing: How `setup_logging()` interacts with file handler on subsequent calls** -- SEVERITY: MEDIUM
   - REQ-001 says "existing handlers are cleared before adding the new handler."
   - If `handlers.clear()` is called on every invocation, the `RotatingFileHandler` is also destroyed and recreated. This means: (a) the file is re-opened, (b) if the file was rotated, the new handler starts fresh with no awareness of previous rotation state, (c) any buffered data in the old handler is lost if `flush()` is not called before clearing.
   - Recommendation: Specify that `handlers.clear()` should call `handler.close()` on each handler before clearing, or iterate and close handlers explicitly. Python's `Logger.handlers.clear()` does NOT close handlers -- it just removes them from the list, potentially leaking file descriptors.

---

### Research Disconnects

1. **Research finding "Event Loop Blocking Risk" addressed only as a limitation, not tested** -- The research identified that synchronous `audit_logger.handle(record)` blocks the event loop if Docker log driver is slow. The spec's PERF-001 sets a 5ms threshold for file-based logging but provides no mechanism to enforce or measure this. There is no test for it. The "5ms" number appears to be arbitrary with no benchmark backing.

2. **Research finding "QA/Testing perspective" on `caplog` limitations well-addressed** -- The spec provides a concrete `StringIO` approach in implementation notes. This is good alignment.

3. **Research finding "Source field is spoofable and underdocumented"** -- The spec acknowledges this in REQ-013 as a "documented known limitation" but does not specify WHERE it should be documented (code comment? compliance docs? API docs?). For a compliance-relevant limitation, the documentation location matters.

4. **Research finding on log volume / rate limiting** -- Research noted "No rate limiting or sampling on audit logs" and said this is correct for compliance. The spec does not mention log volume at all. For an enterprise deployment processing thousands of requests, the combination of `entities_found` WITH DUPLICATES (potentially hundreds of entries per request for large documents) and file-based logging could produce substantial log volume. The spec should at least acknowledge this in RISK items.

---

### Risk Reassessment

- **RISK-001 (6 call sites to update)**: Actually HIGHER severity because it is not just 6 call sites. The non-deduplicated entity list is not available at 4 of the 6 call sites (anonymize API, anonymize web, document API, document web). This requires changes to `anonymize_entities()` and `process_document()` -- upstream functions that are shared with the response path. Touching these functions risks breaking the API response format.

- **RISK-003 (Event loop blocking with file I/O)**: Severity is accurate (LOW for v1). However, the spec sets a "5ms" threshold in PERF-001 with no way to enforce it. Either remove the specific number or add a test that measures it.

- **RISK-005 (Schema change breaks existing log parsers)**: Actually LOWER severity than stated. There is no production deployment, so the risk is effectively zero. The mitigation note is sufficient.

- **NEW RISK: `anonymize_entities()` return type change** -- SEVERITY: MEDIUM. Changing `anonymize_entities()` to return both deduplicated and non-deduplicated entity lists modifies a function used by multiple code paths. If the return type changes from `tuple[str, dict, list]` to `tuple[str, dict, list, list]`, all callers (anonymize.py:108, pages.py anonymize path, document_processor.py) must be updated. A missed caller will crash at runtime with a tuple unpacking error.

---

### Contradictions

1. **REQ-004 vs Implementation Step 4** -- REQ-004 says `entities_found` preserves duplicates. Implementation Step 4 says "compute the full entity type list with duplicates (sorted but NOT deduplicated) for the audit log." But Step 6 says "Compute `entities_found_audit = sorted(r["entity_type"] for r in results)`" -- this only works for detect.py where `results` (raw Presidio output) is available. For anonymize.py, the equivalent `results` variable exists at line 85 but has gone through `anonymize_entities()` by the time the audit call happens at line 139. The `results` from Presidio are the pre-overlap-resolution entities, while the audit should arguably log post-overlap-resolution entities. The spec does not clarify whether duplicates should reflect pre- or post-overlap-resolution counts.

2. **REQ-011 vs document_upload semantics** -- REQ-011 says document_upload includes the `operator` field "same as anonymize, since document upload includes anonymization." But not all document uploads involve anonymization -- the early return paths in `process_document()` for unsupported formats or empty documents may skip anonymization entirely. Should `operator` still be `"replace"` in those cases?

---

### Critical Questions Answered

1. **What will cause arguments during implementation due to spec ambiguity?** -- Where the non-deduplicated entity list comes from for anonymize and document paths. The spec assumes it is available at the call site; it is not.

2. **Which requirements will be hardest to verify as "done"?** -- PERF-001's "less than 1ms" and "5ms" thresholds. There is no test that measures timing, and logging latency varies by system load, Docker log driver, and disk speed. These are unverifiable as written.

3. **What is the most likely way this spec leads to wrong implementation?** -- An implementer follows the spec's Step 6 literally, tries to get `sorted(r["entity_type"] for r in results)` at the anonymize call site, discovers `results` is not in scope, and either (a) hacks around it by adding the raw results to `AnonymizationResult`, bloating the object, or (b) gives up and keeps the deduplicated list, silently violating REQ-004.

4. **Which edge cases are still missing?**
   - EDGE: Document with zero text chunks (all chunks are empty/whitespace) -- what does `entities_found` contain?
   - EDGE: `setup_logging()` called with file config, then called again without file config (e.g., test teardown) -- does the file handler get removed?
   - EDGE: `RotatingFileHandler` writing to a Docker volume mount where the mount disappears mid-operation.
   - EDGE: Very large `entities_found` list (1000+ entries for a big document) -- JSON serialization performance, log line length limits.

5. **Feature interaction issues:**
   - **Allow lists + audit**: If allow lists suppress entity detection, the `entities_found` list shrinks and `entity_count` decreases. This is correct behavior but means audit logs cannot distinguish between "no PII existed" and "PII was suppressed by allow list." The `allow_list_count` helps somewhat, but a compliance officer might want to know that suppression occurred even when entity_count is 0.
   - **Language detection + audit**: The `language_detected` field logs the resolved language, not whether it was auto-detected or manually specified. A compliance officer cannot distinguish `language_detected: "en"` (auto) from `language_detected: "en"` (manual). The `language_confidence` field is NOT included in the audit schema (REQ-012 does not list it), which means this distinction is lost.

---

### Recommended Actions Before Proceeding

1. **[HIGH PRIORITY] Resolve the `entities_found` propagation problem.** Decide whether to: (a) modify `anonymize_entities()` and `process_document()` to return non-deduplicated lists, (b) pass raw Presidio results alongside processed results, or (c) accept deduplication in anonymize/document paths and only preserve duplicates for detect. Add the affected upstream files to "Files to Modify." This is the single biggest gap in the spec.

2. **[HIGH PRIORITY] Clarify `entity_count` semantics per action.** Currently inconsistent (total occurrences for detect, unique mappings for anonymize/document). With `entities_found` now containing duplicates, `len(entities_found) != entity_count` for anonymize/document, which will confuse log consumers.

3. **[MEDIUM PRIORITY] Specify `setup_logging()` signature and handler cleanup.** State whether it accepts individual parameters or the settings object. Specify that `handler.close()` must be called before clearing handlers to prevent file descriptor leaks.

4. **[MEDIUM PRIORITY] Drop or rephrase PERF-001 timing thresholds.** Replace "less than 1ms" and "5ms" with qualitative statements like "audit emission must not introduce perceptible latency" since the specific numbers are unverifiable without benchmarking infrastructure.

5. **[LOW PRIORITY] Add `language_confidence` to audit schema or document its exclusion.** Without it, audit logs cannot distinguish auto-detected from manually specified languages, which may matter for compliance reporting.

6. **[LOW PRIORITY] Specify documentation location for v1 known limitations.** REQ-013 and SEC-004 reference "documented known limitation" but do not say where. Add a requirement for a compliance notes section in deployment docs or inline code comments.

---

## Findings Addressed

All findings from this critical review have been resolved in SPEC-006-audit-logging.md. Summary of resolutions:

### Ambiguities That Will Cause Problems

1. **[HIGH] `entities_found` with duplicates -- where does the non-deduplicated list come from?** -- Resolved by changing REQ-004 to use **deduplicated, sorted** lists (matching what is actually available at all call sites). The duplicates requirement was dropped because anonymize and document pipelines only expose deduplicated lists, and propagating non-deduplicated lists would require invasive changes to `anonymize_entities()` and `process_document()` shared functions. The `entity_count` field provides occurrence information. JSON examples updated to show deduplicated lists.

2. **[MEDIUM] `operator` field -- single string vs reality** -- Resolved by updating REQ-005 to explicitly state the operator is **hardcoded at each call site** (`operator="replace"`), not derived from processing results.

3. **[MEDIUM] `setup_logging()` signature change for file config** -- Resolved by updating REQ-006 to specify **explicit parameters** approach: `setup_logging(log_level, audit_log_file, audit_log_max_bytes, audit_log_backup_count)`. Individual params chosen over settings object for testability.

4. **[LOW] Parameter naming in function signatures** -- Resolved by updating REQ-003 to explicitly state the rename applies ONLY to `_emit_audit()` signature and JSON output keys, NOT to `DetectionResult`, `AnonymizationResult`, or other intermediate data structures.

### Missing Specifications

1. **[HIGH] How to propagate non-deduplicated entity lists** -- Resolved by eliminating the need: REQ-004 changed to deduplicated lists. No changes to `anonymize_entities()` or `process_document()` needed. Files to Modify section updated to explicitly exclude these files.

2. **[MEDIUM] What happens to existing tests with old parameter names** -- Resolved by adding explicit per-file test update instructions in Implementation Note #7 and the Files to Modify list.

3. **[LOW] `allow_list_count` behavior in document upload path** -- Resolved by adding REQ-015 explicitly preserving existing behavior.

4. **[LOW] `entity_count` semantics in `document_upload`** -- Resolved by adding semantic clarification to REQ-012 documenting the per-action difference (total occurrences for detect, unique mappings for anonymize/document).

5. **[MEDIUM] `setup_logging()` handler cleanup** -- Resolved by updating REQ-001 to require `handler.close()` on each handler before clearing. Implementation Step 1 updated with explicit close-then-clear code. EDGE-014 added for the teardown scenario.

### Research Disconnects

1. **PERF-001 arbitrary thresholds** -- Resolved by replacing "less than 1ms" and "5ms" with qualitative statement: "must not introduce perceptible request latency." Performance Validation section updated similarly.

2. **Source field documentation location** -- Resolved by updating REQ-013 and SEC-004 to specify documentation location: code comments in `audit.py` module-level docstring "Known v1 Limitations" section.

3. **Log volume concern** -- Resolved by adding RISK-007 acknowledging log volume for enterprise deployments. Notes that `entities_found` is bounded (deduplicated, ~50 max Presidio types) and `RotatingFileHandler` limits disk usage.

4. **`language_confidence` exclusion** -- Resolved by adding REQ-016 documenting intentional exclusion with rationale (keep schema minimal for v1, deferred to post-v1).

### Risk Reassessment

- **RISK-001 severity reduced** -- No longer requires upstream function changes. Simple keyword argument rename at 6 call sites. Risk updated in spec.
- **RISK-005 acknowledged as low** -- No production deployment, so schema change risk is effectively zero.
- **NEW RISK-007 added** -- Log volume for enterprise deployments.
- **`anonymize_entities()` return type change risk eliminated** -- By keeping deduplicated lists, no return type change is needed.

### Contradictions

1. **REQ-004 vs Implementation Step 4/6** -- Resolved by aligning both to deduplicated lists. Step 4 and Step 6 updated to pass existing deduplicated list as-is. No pre/post overlap resolution ambiguity since the existing `entity_types` (post-overlap, deduplicated) is used.

2. **REQ-011 vs document_upload early return** -- Resolved by updating REQ-011 to specify `operator="replace"` is always present, even for early-return paths, because the intended operation was anonymization.

### Edge Cases Added

- **EDGE-013:** Document with zero text chunks -- audit logs `entity_count: 0, entities_found: [], operator: "replace"`.
- **EDGE-014:** `setup_logging()` called with file config then without -- close-then-clear ensures proper cleanup.
