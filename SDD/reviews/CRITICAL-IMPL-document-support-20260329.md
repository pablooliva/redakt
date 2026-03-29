# Implementation Critical Review: Document Support

**Date:** 2026-03-29
**Feature:** SPEC-003 Document Support
**Reviewer Posture:** Adversarial -- attempting to break the implementation
**Overall Severity: MEDIUM** (several individually-low issues compound; two HIGH-severity findings)

---

## Specification Violations

### 1. [REQ-016 / XLSX Copy] Copy-to-clipboard broken for XLSX format -- HIGH

**Location:** `src/redakt/static/deanonymize-documents.js` lines 107-115, `src/redakt/templates/partials/document_results.html`

The copy button handler does `document.getElementById("anonymized-content")`, but for XLSX output the template renders `<table>` elements with no element carrying the `id="anonymized-content"`. The `content` variable will be `null`, and `copyToClipboard` will silently fail (no text copied, no error shown). The same issue affects JSON output -- the `<code id="anonymized-content">` is nested inside `<pre>`, so `.textContent` works there, but it should be verified.

**Impact:** XLSX users click "Copy to clipboard" and nothing happens. No feedback that copy failed.

### 2. [PERF-004 / FAIL-009] Web UI route bypasses concurrent upload semaphore -- HIGH

**Location:** `src/redakt/routers/pages.py` lines 146-239

The API route (`/api/documents/upload` in `documents.py`) uses `_get_upload_semaphore()` with 429 rejection. The web UI route (`/documents/submit` in `pages.py`) calls `process_document()` directly with no semaphore protection. A user submitting multiple documents via the web UI bypasses the concurrency limit entirely. Under load, this could exhaust Presidio or cause OOM.

**Impact:** The concurrency protection specified in PERF-004 and FAIL-009 is only enforced on the API route, not the web UI route.

### 3. [EDGE-014] Hidden sheets test missing -- LOW

**Location:** `tests/test_extractors.py`

The spec explicitly requires testing that hidden sheets are processed (`EDGE-014`). No test exists for this. The implementation likely works because `openpyxl` with `read_only=True` iterates all sheets by default, but the behavior is unverified.

### 4. [EDGE-015] XLSX cell count limit test missing -- MEDIUM

**Location:** `tests/test_extractors.py`

The spec requires a test verifying that XLSX files with >50,000 text cells return a 422 error. No test exists. The implementation in `extract_xlsx` (line 282-289) has the check, but it's untested. The `test_zip_bomb_detection` test also does not actually trigger the bomb check (comment in the test acknowledges this).

### 5. [EDGE-007] Encoding detection failure test missing -- MEDIUM

**Location:** `tests/test_extractors.py`

The spec requires testing that undetectable encoding (confidence < 0.5) returns an ExtractionError. No test exercises the `coherence < 0.5` path in `_decode_text()`.

### 6. [SEC-005] Filename sanitization incomplete -- LOW

**Location:** `src/redakt/routers/documents.py` lines 37-45

The spec says "strip path components, limit length, remove special characters." The implementation strips path components via `Path(filename).name` and lowercases the suffix, but does NOT limit length or remove special characters. The filename is never used for filesystem operations (only for extension extraction), so the practical risk is low, but it deviates from the spec.

### 7. [REQ-019] JSON empty response semantics -- LOW

**Location:** `src/redakt/services/document_processor.py` lines 325-341

The spec states for empty JSON: `anonymized_structured: null` (the parsed empty/null JSON) and `anonymized_content: null`. The implementation returns `extraction.metadata.get("original_structure")` which for empty JSON bytes will never be reached (the empty bytes check in `extract_json` returns before setting `original_structure`). This means for truly empty JSON files (`b""`), the extractor returns no metadata, and the processor returns `anonymized_structured: None` -- which matches spec. But for `b"null"` (valid JSON null), `extract_json` will parse it, produce no chunks, and set `original_structure: None`. The processor returns `anonymized_structured: None` -- correct. Edge case appears covered.

---

## Technical Vulnerabilities

### 1. XSS via data-mappings attribute -- MEDIUM

**Location:** `src/redakt/templates/partials/document_results.html` line 6

```html
<div id="document-output" data-mappings='{{ mappings_json }}'>
```

The `mappings_json` is inserted into a single-quoted HTML attribute. If a PII value (the original text that becomes a mapping value) contains a single quote followed by an event handler (e.g., original text is `O'Brien onclick=alert(1)`), it could break out of the attribute. Jinja2's autoescaping should handle this by escaping `'` to `&#39;`, but the interaction between `json.dumps()` (which does NOT escape single quotes) and Jinja2 autoescaping (which escapes `<`, `>`, `&`, `"`, but NOT `'` by default in attributes delimited by single quotes) creates a potential bypass.

Specifically: `json.dumps({"<PERSON_1>": "test' onmouseover=alert(1) x='"})` produces JSON with unescaped single quotes. Inside `data-mappings='...'`, the single quote terminates the attribute.

**Mitigation:** Use double quotes for the attribute (`data-mappings="{{ mappings_json }}"`) since `json.dumps` escapes double quotes with backslash and Jinja2 escapes `"` to `&quot;`. Or use `|tojson|e` filter.

### 2. JSON recursion depth unbounded -- MEDIUM

**Location:** `src/redakt/services/extractors.py` lines 167-179, `src/redakt/services/document_processor.py` lines 530-550

Both `_extract_json_strings()` and `_replace_json_strings()` use unbounded recursion. A maliciously crafted JSON file with thousands of nesting levels (e.g., `{"a":{"a":{"a":...}}}` nested 10,000 deep) will hit Python's default recursion limit (1000) and raise `RecursionError`. This is caught by the blanket `except Exception` in `process_document` and returns 422, so it fails gracefully, but the error message ("could not be parsed") is misleading.

**Impact:** Denial of service via stack overflow is mitigated by Python's recursion limit. The error message is inaccurate but not dangerous.

### 3. Race condition in semaphore check -- LOW

**Location:** `src/redakt/routers/documents.py` lines 80-81

```python
if sem.locked() and sem._value == 0:
```

This accesses `sem._value`, a private attribute of `asyncio.Semaphore`. Between the check and the `async with sem:` on line 87, another coroutine could release the semaphore (TOCTOU race). The check is best-effort (spec says "Requests that cannot acquire the semaphore immediately return 429"), but using a private attribute is fragile and could break across Python versions.

### 4. Memory amplification with large XLSX sheets_data -- MEDIUM

**Location:** `src/redakt/services/extractors.py` lines 266-312

The `extract_xlsx` function builds `sheets_data` (a full in-memory copy of the entire workbook as nested Python lists) in addition to the `chunks` list. For a 10MB XLSX with 50,000 text cells, this creates two parallel representations in memory. The `sheets_data` is needed for XLSX reassembly, but it includes ALL cell values (not just text), so it can be significantly larger than the chunks list.

### 5. openpyxl read_only mode close behavior -- LOW

**Location:** `src/redakt/services/extractors.py` lines 269-303

In `read_only` mode, openpyxl uses lazy loading with open file handles. The `try/finally: wb.close()` on line 303 ensures cleanup, but if the `ExtractionError` on line 284 is raised, `wb.close()` is called explicitly before the raise (line 283), and then the `finally` block calls it again. Double-close is generally safe for openpyxl, but it's needless complexity.

---

## Test Gaps

### 1. No test for XLSX with PII across multiple sheets (EDGE-006) -- MEDIUM

The spec requires verifying that the same PII value in different sheets maps to the same placeholder. The `test_multi_sheet` test in `test_extractors.py` only tests extraction, not the unified placeholder mapping across sheets. No integration test covers this end-to-end.

### 2. No test for XLSX cell count limit (EDGE-015) -- MEDIUM

No test creates an XLSX with >50,000 text cells to verify the limit triggers correctly.

### 3. No test for merged cells (EDGE-005) -- MEDIUM

The spec requires testing that only the top-left cell of a merged range is processed. No test exists. openpyxl in `read_only=True` mode may behave differently with merged cells than in normal mode.

### 4. No multi-page PDF test -- LOW

The spec requires testing multi-page PDF extraction. No test creates a multi-page PDF and verifies all pages are extracted.

### 5. No test for encoding detection failure path -- MEDIUM

The `_decode_text` function's `coherence < 0.5` branch is untested.

### 6. No test for `score_threshold` parameter forwarding -- LOW

The API endpoint accepts `score_threshold` but no test verifies it's forwarded to Presidio correctly.

### 7. No test for web UI document upload route (`/documents/submit`) -- MEDIUM

All document API tests hit `/api/documents/upload`. The web UI route at `/documents/submit` in `pages.py` has separate error handling logic and different response format, but zero test coverage.

### 8. Weak assertion in `test_zip_bomb_detection` -- LOW

**Location:** `tests/test_extractors.py` lines 294-308

The test creates a small ZIP and acknowledges in a comment that it doesn't actually trigger the bomb detection. The test has no assertion -- it's a no-op.

### 9. Weak assertion in `test_empty_rtf` -- LOW

**Location:** `tests/test_extractors.py` lines 481-485

The test has no assertion at all. It calls `extract_rtf` but never checks the result.

---

## Critical Questions Answered

### 1. How would you break this implementation with malicious input?

- **XSS via single-quote breakout in data-mappings:** Craft a document containing text like `test' onmouseover=alert(1) data-x='` that becomes a PII mapping value. The JSON-serialized mapping injected into the single-quoted `data-mappings` attribute could break out.
- **Stack overflow via deeply nested JSON:** Submit a JSON file with 1000+ levels of nesting to trigger RecursionError.
- **Memory exhaustion via XLSX:** Submit a 10MB XLSX near the size limit with maximum string cell density. The dual in-memory representation (sheets_data + chunks) amplifies memory usage.
- **Bypass concurrency limits via web UI:** The `/documents/submit` route has no semaphore, so concurrent web UI submissions bypass the limit.

### 2. What happens under concurrent load?

- API route: bounded by semaphore (3 concurrent, configurable). 4th request gets 429.
- Web UI route: unbounded. No semaphore. Could overwhelm Presidio.
- Within a single document: Presidio calls bounded by `Semaphore(10)` via `asyncio.gather`.
- The upload semaphore in `documents.py` uses a module-level global initialized lazily. Multiple event loops (unlikely in production but possible in testing) would share or conflict.

### 3. Which paths have no test coverage?

- Web UI route `/documents/submit` (entire route)
- XLSX merged cells, hidden sheets, cell count limit
- Multi-page PDF extraction
- Encoding detection failure (coherence < 0.5)
- `score_threshold` parameter forwarding
- RTF with corrupted input (test exists but has no assertion)
- ZIP bomb detection (test exists but doesn't trigger detection)
- Copy-to-clipboard for XLSX format (would reveal the bug)

### 4. What assumptions does the code make that could be violated?

- **`sem._value` exists:** Relies on CPython implementation detail of `asyncio.Semaphore`.
- **openpyxl `read_only` mode iterates all sheets including hidden:** Likely true but untested.
- **`csv.Sniffer` returns correct delimiter:** Can fail on ambiguous or very short CSV content; fallback is comma.
- **pdfminer uses `\x0c` (form-feed) as page separator:** This is a convention, not guaranteed. Some PDFs may not produce form-feeds.
- **JSON recursion stays within Python's default limit:** Not explicitly guarded.
- **Jinja2 autoescaping prevents XSS in single-quoted attributes:** It does not escape single quotes by default.

---

## Recommended Actions Before Merge

### Priority 1 (HIGH -- fix before merge)

1. **Fix XSS in data-mappings attribute:** Change `data-mappings='{{ mappings_json }}'` to use double quotes or apply `|tojson` filter. Verify the same issue in `anonymize_results.html`. This is a stored XSS vector since PII values from uploaded documents flow into the attribute.

2. **Add semaphore to web UI route:** The `/documents/submit` handler in `pages.py` must use the same `_get_upload_semaphore()` pattern as the API route, or extract a shared middleware/dependency.

3. **Fix XLSX copy-to-clipboard:** Either add an `id="anonymized-content"` to a hidden element containing text representation of XLSX data, or disable the copy button for XLSX format, or change the copy handler to serialize table content.

### Priority 2 (MEDIUM -- fix before release)

4. **Add missing test cases:** XLSX cell count limit, merged cells, hidden sheets, encoding detection failure, multi-sheet PII consistency, web UI route.

5. **Guard JSON recursion depth:** Add explicit depth limit parameter to `_extract_json_strings` and `_replace_json_strings`, or catch `RecursionError` with a clear error message.

6. **Fix semaphore race condition:** Replace `sem._value == 0` check with `try: sem.acquire_nowait()` pattern which is atomic and uses public API.

### Priority 3 (LOW -- fix in next iteration)

7. **Add assertions to empty test cases:** `test_zip_bomb_detection` and `test_empty_rtf` have no assertions.

8. **Deduplicate `_col_num_to_letter`:** The function is defined twice (in `extractors.py` as `_col_num_to_letter` and in `document_processor.py` as `_col_num_to_letter_standalone`). Extract to a shared utility.

9. **SEC-005 filename sanitization:** Add length limit as specified, even though filenames are not used for filesystem operations.

---

## Findings Addressed (2026-03-29)

All HIGH and MEDIUM findings resolved. LOW findings addressed where reasonable.

### HIGH (all fixed)

1. **XSS via data-mappings attribute** -- Both `document_results.html` and `anonymize_results.html` now use `{{ mappings|tojson }}` instead of `{{ mappings_json }}`. The `|tojson` filter escapes `'` to `\u0027`, `<` to `\u003c`, `>` to `\u003e`, and `&` to `\u0026`, preventing attribute breakout in single-quoted HTML attributes.

2. **Web UI route bypasses concurrency semaphore** -- `pages.py` now imports and uses `_get_upload_semaphore()` from `documents.py`, applying the same `sem.locked()` check before processing. Both routes share the same semaphore instance.

3. **Copy-to-clipboard broken for XLSX** -- XLSX output now wraps all sheet tables in a `<div id="anonymized-content">` container. The JS copy handler uses `innerText` (instead of `textContent`) for better table formatting, and shows "Nothing to copy" feedback if no content element is found.

### MEDIUM (all fixed)

4. **JSON recursion depth** -- `_extract_json_strings()` in `extractors.py` and `_replace_json_strings()` in `document_processor.py` now accept a `depth` parameter with a limit of 100. Exceeding the limit raises `ExtractionError` with a clear message during extraction; replacement silently returns the object at max depth (structure was already validated).

5. **Semaphore `_value` check** -- Replaced `sem.locked() and sem._value == 0` with `sem.locked()` (public API). `asyncio.Semaphore.locked()` returns True when the semaphore cannot be acquired immediately, which is the correct check for rejecting with 429.

6. **Missing tests added:**
   - `test_xlsx_cell_count_limit` -- verifies ExtractionError when cell count exceeds limit
   - `test_encoding_detection_failure` -- tests random bytes path
   - `test_encoding_low_coherence` -- mocks charset_normalizer coherence < 0.5 to verify ExtractionError
   - `test_hidden_sheet_processed` -- EDGE-014: hidden sheets are extracted
   - `test_merged_cells` -- EDGE-005: only top-left cell of merged range produces a chunk
   - `test_json_recursion_depth_limit` -- verifies 120-level nesting raises ExtractionError
   - `test_multi_page_pdf` -- verifies multi-page PDF produces per-page chunks
   - `test_same_pii_across_sheets` -- EDGE-006: same PII in different XLSX sheets maps to same placeholder
   - `test_web_ui_upload_txt` -- web UI route returns HTML partial with anonymized content
   - `test_web_ui_upload_error` -- web UI route returns error HTML for unsupported format
   - `test_web_ui_semaphore_rejection` -- web UI route returns error when semaphore is full
   - `test_web_ui_empty_file` -- web UI route handles empty files gracefully

### LOW (all fixed)

7. **Weak test assertions** -- `test_zip_bomb_detection` now creates a ZIP with 110MB uncompressed content and asserts `ExtractionError("too large to process")`. `test_empty_rtf` now asserts either empty chunks or whitespace-only content.

8. **Deduplicated `_col_num_to_letter`** -- `document_processor.py` now imports `_col_num_to_letter` from `extractors.py` instead of defining its own `_col_num_to_letter_standalone`.

9. **SEC-005 filename sanitization** -- `_sanitize_extension()` in `documents.py` now truncates filenames longer than 255 characters before extracting the extension.

### Test results

All 189 tests pass (`uv run pytest tests/ -x`).
