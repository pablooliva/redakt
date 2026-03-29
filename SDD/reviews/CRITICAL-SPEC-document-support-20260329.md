# Specification Critical Review: Document Support (SPEC-003)

**Reviewer:** Adversarial Critical Review
**Date:** 2026-03-29
**Spec Version:** Draft
**Research Basis:** RESEARCH-003-document-support.md

---

## Overall Severity: MEDIUM-HIGH

The spec is significantly more thorough than average -- edge cases, security, and pipeline design are well-covered. However, several ambiguities and gaps will cause implementation friction, and there are two potentially HIGH severity issues around error handling semantics and the EDGE-013 behavior fork.

---

## Ambiguities That Will Cause Problems

### 1. [REQ-013] Language detection: "longest text chunk or first 5KB sample" -- which one? (HIGH)

The spec says: "Language is detected ONCE per document (from the longest text chunk or first 5KB sample)."

- **Possible interpretations:**
  - A) Use the longest text chunk (by character count) from the extracted chunks
  - B) Use the first 5KB of concatenated text from all chunks
  - C) Use whichever is longer -- the longest chunk or the first 5KB sample
- **Why it matters:** For a 500-sheet Excel file with short cells, the "longest text chunk" might be 20 characters. For a PDF, the "first 5KB" sample could span mid-sentence across pages. These produce different language detection results.
- **Recommendation:** Pick exactly one strategy. Suggest: "Concatenate the first N non-empty chunks until 5KB of text is accumulated. If total extracted text is < 5KB, use all of it."

### 2. [EDGE-013] "Return an error for that chunk or skip it with a warning" -- which one? (HIGH)

The spec presents two mutually exclusive behaviors for pathological single-cell content exceeding 512KB:

- **Possible interpretations:**
  - A) Return an HTTP error and abort the entire document
  - B) Skip the oversized chunk, include a warning in `metadata.warnings`, continue processing
- **Why it matters:** These are completely different user experiences. Option A means one bad cell kills the entire upload. Option B means partial results with potential PII leakage (the skipped chunk is returned un-anonymized or omitted).
- **Recommendation:** Choose option B (skip with warning) for robustness, but explicitly state whether the skipped chunk's original text is included in output (un-anonymized) or replaced with a placeholder like `[CONTENT TOO LARGE - SKIPPED]`. The former is a PII risk; the latter is safer.

### 3. [REQ-004] CSV output: "native format string within JSON response" (MEDIUM)

- **Possible interpretations:**
  - A) The `anonymized_content` field contains a CSV-formatted string (with newlines, delimiters)
  - B) The `anonymized_structured` field contains a 2D array of cells
- The spec says CSV uses `anonymized_content` (text string) per REQ-019, but the research (Decision 7) considered CSV a "native-format exception." The spec then says output is "anonymized CSV text" which goes in `anonymized_content`.
- **Issue:** The output delimiter is under-specified. REQ-008 says "Output uses the detected delimiter" for CSV, but what about quoting? What if the anonymized placeholder `<PERSON_1>` appears in a cell that previously didn't need quoting? The CSV writer configuration (quoting policy, line terminator) is unspecified.
- **Recommendation:** Specify: "CSV output uses `csv.writer` with `csv.QUOTE_MINIMAL` and the auto-detected delimiter. Line terminator is `\r\n` (RFC 4180)."

### 4. [REQ-019] "Never both populated, never both null when content exists" (MEDIUM)

- **Ambiguity:** What about empty files? EDGE-001 says "Return immediately with empty content, empty mapping." But REQ-019 says "never both null when content exists." For an empty file, is `anonymized_content` an empty string `""` or `null`? Is `anonymized_structured` `null`?
- **Recommendation:** Specify: "For empty files, return `anonymized_content: ""` (empty string) and `anonymized_structured: null` for text-based formats. For XLSX, return `anonymized_structured: {}` and `anonymized_content: null`."

### 5. [REQ-011] PDF warning threshold: "< 100 chars from a file > 10KB" (LOW)

- **Ambiguity:** Is 10KB the raw file size or extracted text size? A heavily formatted 50KB PDF with only a title ("Contract Agreement") would have ~20 chars extracted from a 50KB file -- clear case. But what about a 15KB PDF with 90 chars of extracted text? That is below 100 chars and above 10KB, so it triggers the warning. Is 90 chars really "limited extraction"?
- **Recommendation:** The heuristic is reasonable but document that it is a heuristic and may produce false positives for legitimately short PDFs. Consider also a ratio-based check (extracted chars / file bytes < threshold).

---

## Missing Specifications

### 1. Request body parameter serialization for multipart/form-data (HIGH)

The API contract says `entities` and `allow_list` are "comma-separated lists" in the multipart form. But:
- How are these validated? What if someone sends `entities=PERSON,,EMAIL_ADDRESS` (double comma)?
- What if `allow_list` contains a term with a comma in it?
- The existing `/api/anonymize` endpoint accepts these as JSON arrays in a JSON body. The document upload switches to multipart/form-data where arrays cannot be natively represented.
- **Why it matters:** Implementers must decide on serialization/deserialization, and API consumers need clear documentation.
- **Suggested addition:** Specify: "Parameters `entities` and `allow_list` are comma-separated strings in multipart form fields. Empty strings between commas are ignored. Terms containing commas are not supported in the comma-separated format (use the JSON body variant if needed). Alternatively, support repeated form fields: `allow_list=term1&allow_list=term2`."

### 2. Concurrent upload limits and request queuing (MEDIUM)

The spec discusses memory amplification (RISK-003) and recommends "max 3-5 concurrent document uploads" but does not specify any enforcement mechanism for v1. There is no request semaphore or queue.
- **Why it matters:** In production, nothing prevents 20 simultaneous document uploads from crashing the container with OOM.
- **Suggested addition:** Either add a requirement for a server-side upload concurrency semaphore (e.g., `asyncio.Semaphore(3)` at the router level), or explicitly state: "v1 relies on container memory limits and orchestrator restarts for OOM protection. No request-level concurrency control."

### 3. HTMX response for structured formats (XLSX, JSON) in web UI (MEDIUM)

REQ-016 says results are displayed via partial swap showing "anonymized content, mapping table, and metadata." But for XLSX, the output is `anonymized_structured` -- a nested JSON object of sheets/rows/cells. How is this rendered in the HTML partial?
- **Why it matters:** Rendering a 2D table per sheet is very different from rendering plain text in a `<pre>` tag. The template `partials/document_results.html` needs format-specific rendering logic.
- **Suggested addition:** Specify rendering strategy: "For XLSX, render each sheet as an HTML `<table>` with rows and cells. For JSON, render as formatted JSON in a `<pre>` block. For all other formats, render as plain text in a `<pre>` block."

### 4. Score threshold behavior for document uploads (LOW)

REQ-001 says `score_threshold` is optional. But unlike the text endpoint (which falls back to `settings.default_score_threshold`), the document upload spec doesn't explicitly state the fallback.
- **Suggested addition:** "If `score_threshold` is not provided, use `settings.default_score_threshold` (same as the text anonymize endpoint)."

### 5. HTMX file upload: browser file size pre-validation (LOW)

REQ-017 says the form "clearly displays" the max file size. But should the frontend validate file size in JavaScript before upload? A 50MB file would be fully uploaded before the server rejects it with 413.
- **Suggested addition:** "Client-side JavaScript checks `file.size` against the displayed limit before allowing HTMX submission. If exceeded, show an inline error without making a request."

### 6. No specification for partial failure in multi-chunk processing (MEDIUM)

FAIL-002 says if one Presidio chunk times out, "cancel remaining chunks and return error." But what about non-timeout Presidio errors? If chunk 47 of 200 returns a 500 from Presidio:
- Does the entire document fail?
- Are the other 199 chunks still usable?
- **Suggested addition:** "If any single Presidio analyze call fails (timeout, 5xx, connection error), the entire document upload fails with the corresponding error code. Partial results are not returned in v1."

---

## Research Disconnects

### 1. Research Decision 1 recommended "Option C" output -- spec chose differently

The research recommended: "Same-format where practical, extracted text as fallback." Specifically, it said CSV and JSON should return native-format output. The spec followed this for CSV (native CSV text in `anonymized_content`) and JSON (object in `anonymized_structured`), but the research also suggested XLSX could return same-format cell values in-place. The spec returns XLSX as JSON structure, which the research itself flagged as a "materially less useful" UX tradeoff.

**Not necessarily wrong**, but this is the single biggest user satisfaction risk in the spec. The primary use case ("I have a spreadsheet with employee data") results in JSON output the user cannot directly paste back into Excel.

### 2. Research mentioned CSV delimiter override parameter -- spec dropped it

The research (Data Engineering section) said: "Use csv.Sniffer().sniff() to auto-detect delimiter, with a fallback parameter for manual override." The spec (EDGE-008) only includes auto-detection with comma fallback. The manual override parameter is missing.

### 3. Research mentioned "progress indicator for long-running processing" -- spec defers to v2

The research's Out of Scope section lists "Progress indicator for long-running document processing" as v2. But PERF-001 allows up to 120 seconds of processing. A 2-minute wait with only a spinner is a poor UX. The spec's UX-002 specifies `hx-indicator` (a spinner), but no progress feedback. This is a reasonable v1 tradeoff but worth flagging.

### 4. Research raised lxml concern -- spec acknowledges but doesn't resolve

RISK-005 says: "Check during implementation whether lxml is installed." This is not a spec-level resolution -- it is punting a potentially HIGH severity security issue to implementation time. `python-docx` is known to depend on `lxml`. This should be confirmed now (check `python-docx` dependencies) and the mitigation specified, not left as a "check during implementation" task.

---

## Risk Reassessment

### RISK-002 (Short cell values): Actually HIGHER severity

Rated Medium impact, but this is the most common real-world use case. The primary persona is "I have a spreadsheet with employee data." Spreadsheet data is overwhelmingly short cell values -- single names, phone numbers, addresses split across columns. If detection rates are low for the exact use case the feature is built for, user trust erodes quickly.

**Reassessed: HIGH likelihood, HIGH impact.** The spec correctly documents this as a known limitation, but the prominence of this limitation should be elevated -- it should be in the user-facing upload page itself, not just in documentation.

### RISK-003 (Memory amplification): Actually HIGHER severity than stated

Rated Medium likelihood, Medium impact. But: enterprise users uploading 10MB Excel files is not "medium likelihood" -- it is the expected use case. And OOM-killing the container affects all users, not just the uploader.

**Reassessed: HIGH likelihood, HIGH impact.** The mitigation (just documenting recommended memory) is insufficient for production. At minimum, the spec should require a document upload concurrency semaphore.

### RISK-005 (defusedxml/lxml gap): Actually CONFIRMED, not speculative

`python-docx` requires `lxml` as a hard dependency. This is not a "check during implementation" scenario -- it is a confirmed gap. `defusedxml.defuse_stdlib()` does NOT protect lxml parsers. The spec must specify the mitigation: either use `defusedxml.lxml.parse()` wrappers, or verify that python-docx's internal lxml usage does not process untrusted external entities (DOCX XML content is from the ZIP archive, not from external URLs, which reduces but does not eliminate risk).

**Reassessed: HIGH severity.** This is a known XXE vector that the spec claims to address (SEC-003) but actually does not fully address.

### RISK-001 (PDF extraction quality): Accurately rated

Medium likelihood, Medium impact is correct. The mitigation (warning message) is appropriate for v1.

### RISK-004 (Presidio throughput): Actually LOWER severity

The bounded async concurrency (Semaphore(10)) effectively addresses this. At 10 concurrent requests and 20ms latency, even 2000 cells process in ~4 seconds. This is a well-mitigated risk.

**Reassessed: LOW severity** after mitigation.

---

## Contradictions

### 1. CSV appears in both output categories

REQ-019 lists CSV under `anonymized_content` (string). But REQ-004 says "Output is anonymized CSV text (native format string within JSON response)." These are consistent, but the API contract example only shows text and XLSX examples. A CSV example should be added to prevent implementers from guessing.

### 2. PERF-003 vs EDGE-013 ambiguity

PERF-003 says: "If a single cell/chunk exceeds this, return an error for that chunk." EDGE-013 says: "return an error for that chunk or skip it with a warning." These should say the same thing.

---

## Untestable or Weakly Testable Criteria

### 1. PERF-002: "approximately 4-8 seconds"

This depends entirely on Presidio's latency, which varies by hardware, model, and input. The "approximately" makes this informational, not a testable requirement.

### 2. REQ-016: "keyboard-accessible" file input

Technically testable (tab to input, enter to open file dialog), but the spec doesn't define what "keyboard-accessible" means for drag-and-drop. Is drag-and-drop required to be keyboard-accessible? The spec says it's "an enhancement, not a requirement" (UX-001), which helps, but the drag-and-drop target area should also not trap keyboard focus.

### 3. PERF-001: "within 120 seconds for files up to 10MB"

This is environment-dependent. A 10MB PDF on a developer laptop may process in 30 seconds but take 3 minutes in a resource-constrained container. The spec should clarify the target environment (e.g., "on the reference Docker Compose stack with default resource limits").

---

## Missing Edge Cases

### 1. XLSX with thousands of empty rows/columns (MEDIUM)

Excel files often have accidental formatting applied to row 1,048,576. openpyxl's `iter_rows()` without bounds will iterate all of them. This could produce millions of empty chunks that pass through the pipeline.
- **Suggested addition:** EDGE-015: "For XLSX, iterate only over `ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column)` and skip None/empty cells before chunk creation. Validate that the total chunk count does not exceed a reasonable limit (e.g., 50,000 cells) to prevent resource exhaustion."

### 2. JSON with circular references (LOW)

Python's `json.load()` cannot produce circular references, so this is safe. But if a future version adds YAML support, this matters.

### 3. HTML with enormous inline data URIs (MEDIUM)

An HTML file within the 10MB limit could contain a 9MB base64-encoded image in a `<img src="data:...">` tag. BeautifulSoup's `get_text()` would strip it, but parsing the DOM first still loads it into memory.
- **Suggested addition:** EDGE-016: "HTML files with very large embedded data URIs are parsed normally by BeautifulSoup. The data URI content is stripped during text extraction. No special handling needed beyond the 10MB file size limit."

### 4. RTF with embedded objects (LOW)

RTF files can contain embedded OLE objects (images, other documents). `striprtf` ignores these, but the spec should document this explicitly.

### 5. DOCX with tracked changes / comments (MEDIUM)

python-docx can access tracked changes and comments, which may contain PII (reviewer names, suggested text). The spec does not address whether these are extracted and anonymized.
- **Suggested addition:** EDGE-017: "DOCX tracked changes and comments are not processed in v1. Only accepted paragraph text and table cell text are extracted. Tracked changes and comments may contain PII that is not anonymized -- document as a known limitation."

### 6. File with no extension (LOW)

What happens when someone uploads a file with no extension (e.g., just `report`)? The spec validates by extension whitelist, so this would be caught by FAIL-004. But the error message says "Unsupported file format '.{ext}'" -- what is `ext` when there is no extension?
- **Suggested addition:** Handle gracefully: "Unsupported file format. Supported formats: ..."

---

## Critical Questions Answered

### 1. What will cause arguments during implementation due to spec ambiguity?

The EDGE-013 "error or skip" fork will be the biggest source of debate. The language detection strategy ("longest chunk or first 5KB") will also require a decision at implementation time.

### 2. Which requirements will be hardest to verify as "done"?

REQ-012 (unified placeholders across chunks) is easy to unit-test but hard to verify in E2E with real Presidio, because detection is non-deterministic for short cell values. You may need carefully crafted test data with high-confidence PII (full names + email patterns) to get reliable cross-chunk detection.

### 3. What's the most likely way this spec leads to wrong implementation?

The implementer calls `anonymize_entities()` per-chunk instead of building the three-phase pipeline. The spec warns against this multiple times, but it is the obvious "easy" path. The `build_unified_placeholder_map()` function signature and pseudocode help, but the integration with `resolve_overlaps()` per-chunk and the entity enrichment step (adding `original_text`) could be missed.

### 4. Which edge cases are still missing?

XLSX with accidental max-row formatting (see above), DOCX tracked changes, and the "no file extension" edge case.

### 5. What happens when this feature interacts with existing features?

The main interaction is REQ-018: document upload mapping feeding into Feature 2's `deanonymize.js`. This is well-specified. The risk is that document uploads produce much larger mappings (hundreds of entries for a big spreadsheet), and the client-side deanonymization UI may not handle a 500-entry mapping table gracefully (rendering, scrolling, performance).

---

## Recommended Actions Before Proceeding

1. **[HIGH] Resolve EDGE-013 ambiguity.** Decide: skip oversized chunks with warning, or fail the entire document. Specify what happens to the skipped chunk's content in the output.

2. **[HIGH] Resolve REQ-013 language detection strategy.** Pick one algorithm, not "X or Y."

3. **[HIGH] Confirm and specify lxml/defusedxml mitigation.** `python-docx` depends on `lxml`. `defusedxml.defuse_stdlib()` does not cover lxml. Specify the exact mitigation (e.g., `defusedxml.lxml` wrappers, or document why DOCX-internal XML is not an XXE risk since entities come from the ZIP archive, not external URLs).

4. **[MEDIUM] Add document upload concurrency semaphore.** RISK-003 is higher severity than stated. Add a server-side semaphore (e.g., 3-5 concurrent uploads) to prevent OOM.

5. **[MEDIUM] Specify CSV output format details.** Delimiter, quoting policy, line terminator for the CSV string in `anonymized_content`.

6. **[MEDIUM] Specify HTMX rendering for structured formats.** How does the web UI partial render XLSX (tables) vs JSON (formatted code) vs text (pre)?

7. **[MEDIUM] Add EDGE-015 for XLSX max-row iteration bounds.** Prevent accidental iteration over millions of empty rows.

8. **[MEDIUM] Specify multipart form parameter serialization.** How `entities` and `allow_list` are encoded in multipart form-data.

9. **[LOW] Add CSV example to API contract.** The contract shows text and XLSX examples but not CSV.

10. **[LOW] Add EDGE-017 for DOCX tracked changes.** Document as known limitation that tracked changes/comments may contain un-anonymized PII.

11. **[LOW] Elevate RISK-002 visibility.** Short cell detection is the primary use case's biggest weakness. Consider adding a user-facing note on the upload page.

---

## Findings Addressed

**Date:** 2026-03-29
**Resolved by:** Spec revision based on critical review findings

All findings from this review have been resolved in `SPEC-003-document-support.md`. Below is the resolution for each.

### Ambiguities Resolved

1. **[HIGH] REQ-013 language detection** -- Resolved. Picked ONE algorithm: "Concatenate the first N non-empty chunks (in extraction order) until 5KB of text is accumulated. If total extracted text is less than 5KB, use all of it." Updated REQ-013, the pipeline step 4, and the Solution Approach section.

2. **[HIGH] EDGE-013 "error or skip" fork** -- Resolved. Picked: **skip with warning**. Oversized chunks are replaced with `[CONTENT TOO LARGE - SKIPPED]` in output (original text NOT included to avoid PII leakage). Warning added to `metadata.warnings`. PERF-003 updated to match. No contradiction remains between PERF-003 and EDGE-013.

3. **[MEDIUM] REQ-004 CSV output format** -- Resolved. Specified: `csv.writer` with `csv.QUOTE_MINIMAL`, auto-detected delimiter, `\r\n` line terminator (RFC 4180). Added CSV example to API contract.

4. **[MEDIUM] REQ-019 empty file behavior** -- Resolved. Specified exact values for empty files: text-based returns `anonymized_content: ""`, `anonymized_structured: null`; XLSX returns `anonymized_structured: {}`, `anonymized_content: null`.

5. **[LOW] REQ-011 PDF warning threshold** -- Resolved. Clarified that 10KB refers to raw file byte size and 100 chars to extracted text character count. Documented as a heuristic that may produce false positives for legitimately short PDFs.

### Missing Specifications Added

1. **[HIGH] Multipart form parameter serialization** -- Added to REQ-001. `entities` and `allow_list` are comma-separated strings. Empty strings between commas are silently ignored. Terms with commas not supported. Score threshold fallback documented.

2. **[MEDIUM] Concurrent upload limits** -- Added PERF-004, FAIL-009, and RISK-003 mitigation. Server-side `asyncio.Semaphore(3)` at router level. 429 response when exceeded. Configurable via `REDAKT_MAX_CONCURRENT_UPLOADS`. Added to config changes and error responses.

3. **[MEDIUM] HTMX rendering for structured formats** -- Added to REQ-016. XLSX renders as HTML `<table>` per sheet. JSON renders as formatted JSON in `<pre><code>`. All others render as plain text in `<pre>`.

4. **[LOW] Score threshold fallback** -- Added to REQ-001: "If `score_threshold` is not provided, the server uses `settings.default_score_threshold`."

5. **[LOW] Client-side file size validation** -- Added UX-005: JavaScript checks `file.size` before HTMX submission, shows inline error if exceeded.

6. **[MEDIUM] Partial failure in multi-chunk processing** -- Updated FAIL-002: any single Presidio failure (timeout, 5xx, connection error) fails the entire document. Partial results not returned in v1.

### Research Disconnects Addressed

1. **Research Decision 1 (output format)** -- Acknowledged as-is. The XLSX-as-JSON tradeoff is already documented. No spec change needed (the research disconnect was flagged for awareness, not as a bug).

2. **CSV delimiter override parameter** -- Added EDGE-019 explicitly documenting this as a v2 enhancement, not dropped silently.

3. **Progress indicator** -- Already documented as v2 in the research. No spec change needed (acknowledged as reasonable v1 tradeoff).

4. **[HIGH] lxml/defusedxml gap** -- Resolved. RISK-005 upgraded to CONFIRMED HIGH severity. SEC-003 rewritten with full analysis: python-docx requires lxml (hard dependency), `defusedxml.defuse_stdlib()` does NOT cover lxml, practical risk reduced by ZIP-archive origin of XML. Added required implementation verification: XXE test with crafted DOCX, fallback to `defusedxml.lxml` or `resolve_entities=False`. Added XXE verification test to validation checklist.

### Risk Reassessments Applied

1. **RISK-002 (short cell detection)** -- Upgraded to HIGH likelihood, HIGH impact. Added user-facing warning to UX-004. Elevated visibility in RISK-002 description.

2. **RISK-003 (memory/OOM)** -- Upgraded to HIGH likelihood, HIGH impact. Added server-side concurrency semaphore (PERF-004) as v1 mitigation instead of deferring to v2.

3. **RISK-004 (Presidio throughput)** -- Downgraded to LOW severity after mitigation.

4. **RISK-005 (defusedxml/lxml)** -- Upgraded to CONFIRMED HIGH. See lxml resolution above.

### Contradictions Resolved

1. **CSV in both output categories** -- Added CSV example to API contract. No actual contradiction existed (both references were consistent), but the missing example could cause confusion.

2. **PERF-003 vs EDGE-013** -- Resolved. Both now say the same thing: skip oversized chunks with `[CONTENT TOO LARGE - SKIPPED]` placeholder and warning.

### Testability Improvements

1. **PERF-002** -- Added clarification that 4-8 seconds is an informational estimate, not a hard requirement. Testable requirement is concurrent execution (verified by mock timing).

2. **REQ-016 keyboard accessibility** -- Added to UX-001: "Tab to file input, Enter/Space to open dialog. Drag-and-drop target must not trap keyboard focus."

3. **PERF-001** -- Added target environment clarification: "on the reference Docker Compose stack with default resource limits."

### Missing Edge Cases Added

1. **[MEDIUM] EDGE-015: XLSX max-row iteration bounds** -- Added. Bounded by `ws.max_row`/`ws.max_column`. Cell count limit of 50,000. Added to validation checklist and config.

2. **[LOW] JSON circular references** -- No action needed (Python `json.load()` cannot produce circular references). Noted in review for future YAML consideration.

3. **[MEDIUM] EDGE-016: HTML large data URIs** -- Added. Documented as handled by BeautifulSoup `get_text()` stripping + 10MB file limit.

4. **[LOW] EDGE-018: RTF embedded OLE objects** -- Added. Documented that `striprtf` ignores them.

5. **[MEDIUM] EDGE-017: DOCX tracked changes/comments** -- Added as known v1 limitation. Only accepted paragraph and table cell text extracted. Added verification test to checklist.

6. **[LOW] File with no extension** -- Updated FAIL-004 to handle gracefully with appropriate error message.

### Additional Changes

- Added `max_concurrent_uploads: int = 3` and `max_xlsx_cells: int = 50_000` to config changes table
- Added 429 and 502 to error response codes in API contract
- Updated Critical Implementation Considerations with confirmed lxml gap and concurrency semaphore guidance
- Added 8 new test cases to the validation checklist covering new edge cases and requirements
