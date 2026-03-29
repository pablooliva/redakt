# REVIEW-003: Document Support (SPEC-003)

**Date:** 2026-03-29
**Reviewer:** Claude Opus 4.6 (automated spec-driven code review)
**Decision:** APPROVED WITH OBSERVATIONS

---

## 1. Artifact Verification

| Artifact | Expected | Found | Status |
|----------|----------|-------|--------|
| SPEC-003 | `SDD/requirements/SPEC-003-document-support.md` | Present | OK |
| RESEARCH-003 | `SDD/research/RESEARCH-003-document-support.md` | Present | OK |
| PROMPT-003 | `SDD/prompts/PROMPT-003-document-support-2026-03-29.md` | Present, status COMPLETE | OK |
| `src/redakt/models/document.py` | Response models | Present | OK (note: spec says `documents.py`, impl uses `document.py` -- minor naming divergence, no functional impact) |
| `src/redakt/services/extractors.py` | 10 format extractors | Present, all 10 | OK |
| `src/redakt/services/document_processor.py` | Processing pipeline | Present | OK |
| `src/redakt/routers/documents.py` | API endpoint | Present | OK |
| `src/redakt/main.py` | defusedxml + router reg | Both present | OK |
| `src/redakt/config.py` | Document settings | All 6 settings added | OK |
| `src/redakt/services/audit.py` | `log_document_upload()` | Present | OK |
| `src/redakt/routers/pages.py` | Web routes | GET /documents + POST /documents/submit | OK |
| `src/redakt/templates/documents.html` | Upload page | Present | OK |
| `src/redakt/templates/partials/document_results.html` | Results partial | Present | OK |
| `src/redakt/static/document-upload.js` | Client-side validation | Present | OK |
| `src/redakt/static/deanonymize-documents.js` | Client-side deanonymize | Present | OK |
| `src/redakt/templates/base.html` | Nav link added | "Documents" link present | OK |
| `tests/test_extractors.py` | Extractor unit tests | 36 tests claimed | OK |
| `tests/test_document_processor.py` | Processor unit tests | 16 tests claimed | OK |
| `tests/test_documents_api.py` | API integration tests | 17 tests claimed | OK |
| `tests/conftest.py` | `mock_doc_detect_language` fixture | Present | OK |
| Test fixtures (sample files) | Spec lists sample.txt, sample.csv, etc. | Only `.gitkeep` in `tests/fixtures/` | OBSERVATION (see below) |

---

## 2. Specification Alignment Analysis

### Functional Requirements (REQ-001 through REQ-020)

| Requirement | Status | Notes |
|-------------|--------|-------|
| **REQ-001** POST /api/documents/upload multipart/form-data | PASS | Endpoint accepts file, language, score_threshold, entities (comma-separated), allow_list (comma-separated). Empty strings between commas handled by `_parse_comma_separated()`. |
| **REQ-002** 10 file formats | PASS | `EXTRACTORS` dict in `extractors.py` maps all 10 extensions. `settings.supported_file_types` lists all 10. |
| **REQ-003** Text encoding detection | PASS | `_decode_text()` tries UTF-8 first, falls back to charset-normalizer, errors if confidence < 0.5 (uses `coherence` metric). |
| **REQ-004** CSV auto-detected delimiter, QUOTE_MINIMAL | PASS | `csv.Sniffer().sniff()` with comma fallback. Output uses `csv.writer` with detected delimiter, `QUOTE_MINIMAL`, `\r\n` terminator. |
| **REQ-005** JSON recursive extraction | PASS | `_extract_json_strings()` recursively extracts strings; numbers/booleans/null preserved. Output in `anonymized_structured`. |
| **REQ-006** XML via defusedxml | PASS | `defusedxml.ElementTree.fromstring()` used. Text nodes collected. Output as plain text. |
| **REQ-007** HTML via BeautifulSoup | PASS | Script/style decomposed. `get_text(separator=" ", strip=True)`. Output as plain text. |
| **REQ-008** XLSX via openpyxl | PASS | All sheets processed. Only string cells extracted. `read_only=True, data_only=True`. Merged cells: openpyxl read_only mode returns top-left value. Output as structured JSON `{sheet_name: [[cell, ...], ...]}`. |
| **REQ-009** DOCX via python-docx | PASS | Paragraphs and table cells extracted. No formatting preservation. |
| **REQ-010** RTF via striprtf | PASS | `rtf_to_text()` converts to plain text. |
| **REQ-011** PDF via pdfminer.six | PASS | `extract_text()` used. Warning logic: `len(text.strip()) < 100 and len(raw) > 10_000` matches spec thresholds exactly. Warning message matches spec. |
| **REQ-012** Unified placeholder map | PASS | `build_unified_placeholder_map()` uses `seen` dict keyed by `(entity_type, original_text)` and `counters` dict. Same PII across chunks gets same placeholder. |
| **REQ-013** Per-document language detection | PASS | `detect_document_language()` accumulates chunks up to 5KB, calls `detect_language()` once. Explicit language skips detection. |
| **REQ-014** Allow list support | PASS | Instance-wide merged with per-request in `process_document()`. Passed to every Presidio analyze call. |
| **REQ-015** Audit logging | PASS | `log_document_upload()` logs action, file_type, file_size_bytes, entity_count, entity_types, language, source. Filename never logged. |
| **REQ-016** Web UI format-specific rendering | PASS | Template renders XLSX as `<table>` per sheet, JSON as `<pre><code>`, others as `<pre>`. |
| **REQ-017** Formats + size limit displayed | PASS | `documents.html` shows supported formats, 10 MB limit, and detection accuracy note. |
| **REQ-018** Mapping compatible with deanonymize pattern | PASS | `data-mappings` attribute on `#document-output` div. `deanonymize-documents.js` reads it on `htmx:afterSwap`, same pattern as Feature 2. |
| **REQ-019** anonymized_content XOR anonymized_structured | PASS | `CONTENT_FORMATS` vs `STRUCTURED_FORMATS` sets control which field is populated. Empty file handling returns correct nulls per format. |
| **REQ-020** Bounded async concurrency Semaphore(10) | PASS | `asyncio.Semaphore(10)` wraps each `presidio.analyze()` call in `process_document()`. `asyncio.gather()` runs all chunks concurrently. |

### Security Requirements (SEC-001 through SEC-008)

| Requirement | Status | Notes |
|-------------|--------|-------|
| **SEC-001** File size limit 10MB | PASS | `validate_file()` checks `file_size > settings.max_file_size`, returns 413. Configurable via `REDAKT_MAX_FILE_SIZE`. |
| **SEC-002** Extension whitelist + magic bytes | PASS | Extension checked against `settings.supported_file_types`. `MAGIC_BYTES` dict verifies PDF (`%PDF-`) and XLSX/DOCX (`PK\x03\x04`). |
| **SEC-003** defusedxml.defuse_stdlib() | PASS | Called at module level in `main.py` before any XML library imports. openpyxl and python-docx imported lazily inside extractor functions. |
| **SEC-004** ZIP bomb protection | PASS | `_check_zip_bomb()` sums `info.file_size` from `zipfile.ZipFile.infolist()`. Rejects if > 100MB. Called for both XLSX and DOCX. |
| **SEC-005** Filename sanitized | PASS | `_sanitize_extension()` in router strips path components via `Path(filename).name`, extracts suffix. Filename never used for filesystem ops. |
| **SEC-006** No PII at rest | PASS | All processing in memory. Audit logs contain no filenames, content, or text. |
| **SEC-007** Macro-enabled formats rejected | PASS | `.xlsm`, `.docm` not in `supported_file_types` list; extension whitelist rejects them. |
| **SEC-008** Content-type not trusted | PASS | Validation relies solely on extension + magic bytes. `file.content_type` never used. |

**SEC-003 OBSERVATION (lxml/XXE):** The spec requires a DOCX XXE verification test (SEC-003, RISK-005): "Write a verification test with a crafted DOCX containing an XXE entity reference." The XML XXE test exists (`test_defusedxml_blocks_xxe` in `test_extractors.py`), but it tests the XML extractor, not the DOCX extractor with lxml. The DOCX-specific XXE verification test is **missing**. The spec explicitly lists this as a required test item. This is an observation rather than a rejection-level finding because the practical risk is low (DOCX XML comes from within ZIP archives), but the spec's explicit verification step was not completed.

### Performance Requirements (PERF-001 through PERF-004)

| Requirement | Status | Notes |
|-------------|--------|-------|
| **PERF-001** 120s timeout | PASS | `asyncio.wait_for(..., timeout=settings.document_processing_timeout)` in both API and web routes. Default 120.0 in config. Configurable via `REDAKT_DOCUMENT_PROCESSING_TIMEOUT`. |
| **PERF-002** Bounded async concurrency | PASS | `Semaphore(10)` + `asyncio.gather()` in `process_document()`. |
| **PERF-003** Per-chunk text size bounded | PASS | Chunks > `max_text_length` (512KB) skipped, replaced with `[CONTENT TOO LARGE - SKIPPED]`, warning added. Warning deduplicated. |
| **PERF-004** Upload concurrency Semaphore(3) | PASS | `_upload_semaphore` in `routers/documents.py` uses `settings.max_concurrent_uploads` (default 3). Returns 429 when full. |

### UX Requirements (UX-001 through UX-005)

| Requirement | Status | Notes |
|-------------|--------|-------|
| **UX-001** Keyboard-accessible file input | PASS | Standard `<input type="file">` used. No drag-and-drop trap. Tab navigates past it. |
| **UX-002** Loading spinner | PASS | `hx-indicator="#spinner"` on form. `<span id="spinner" class="htmx-indicator">` present. |
| **UX-003** Error recovery via HTMX | PASS | Errors rendered via partial swap to `#document-results`. User can re-upload without refresh. |
| **UX-004** Format list + size limit + accuracy note | PASS | All three displayed in `documents.html`. Accuracy note text matches spec: "Detection accuracy is lower for short cell values..." |
| **UX-005** Client-side file size pre-validation | PASS | `document-upload.js` reads `data-max-file-size` from form, checks `file.size` on change and intercepts `htmx:configRequest` with `evt.preventDefault()`. |

### Edge Cases (EDGE-001 through EDGE-019)

| Edge Case | Status | Notes |
|-----------|--------|-------|
| **EDGE-001** Empty files | PASS | Each extractor handles `b""` input. `_build_empty_response()` returns appropriate empty response per format. |
| **EDGE-002** Password-protected files | PASS | XLSX and DOCX extractors catch "password"/"encrypted" in exception message. PDF extractor does the same. Returns 422 with correct message. |
| **EDGE-003** Corrupted files | PASS | Parser exceptions caught in extractors and `process_document()`. Returns 422. |
| **EDGE-004** No extractable text | PASS | Empty chunks filtered. PDF returns warning for minimal text. |
| **EDGE-005** Mixed content Excel | PASS | `isinstance(value, str)` check in `extract_xlsx()` skips numbers, booleans, None. |
| **EDGE-006** Multi-sheet consistency | PASS | `build_unified_placeholder_map()` spans all chunks across all sheets. |
| **EDGE-007** Non-UTF-8 encoding | PASS | `_decode_text()` with charset-normalizer fallback. Coherence < 0.5 triggers error. |
| **EDGE-008** CSV delimiter detection | PASS | `csv.Sniffer().sniff()` with comma fallback on `csv.Error`. |
| **EDGE-009** Deeply nested JSON | PASS | `_extract_json_strings()` recurses into dicts and lists. Test covers 5+ levels. |
| **EDGE-010** PII spanning cells | N/A | Documented known limitation. No test needed per spec. |
| **EDGE-011** Short cell text | N/A | Documented known limitation. UX-004 note addresses it. |
| **EDGE-012** Image-based PDF | PASS | Warning heuristic implemented. Warning message matches spec. |
| **EDGE-013** Oversized chunks | PASS | Chunks > `max_text_length` replaced with `[CONTENT TOO LARGE - SKIPPED]`. Warning added and deduplicated. |
| **EDGE-014** Hidden Excel sheets | PASS | `openpyxl.load_workbook()` with `read_only=True` processes all sheets including hidden. No filtering applied. |
| **EDGE-015** XLSX empty rows/columns | PASS | `iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column)` bounds iteration. Cell count limit of 50,000 enforced with clear error message. |
| **EDGE-016** HTML data URIs | N/A | Handled by BeautifulSoup `get_text()` stripping + 10MB file limit. No special test needed per spec. |
| **EDGE-017** DOCX tracked changes | OBSERVATION | Spec says "Document as known limitation" AND lists a test: "Create DOCX with tracked changes containing PII, verify they are not included in extracted text." This test is **missing** from `test_extractors.py`. Low impact since python-docx default behavior is well-known, but the spec's test checklist explicitly includes it. |
| **EDGE-018** RTF embedded OLE | N/A | Documented as known behavior. striprtf ignores OLE objects. |
| **EDGE-019** CSV delimiter override | N/A | Deferred to v2 per spec. |

### Failure Scenarios (FAIL-001 through FAIL-009)

| Failure | Status | Notes |
|---------|--------|-------|
| **FAIL-001** Presidio unavailable | PASS | `httpx.ConnectError` caught in router, returns 503. |
| **FAIL-002** Presidio timeout/error | PASS | `httpx.TimeoutException` -> 504, `httpx.HTTPStatusError` (5xx) -> 502. |
| **FAIL-003** File too large | PASS | 413 returned by `validate_file()`. |
| **FAIL-004** Unsupported format | PASS | 400 returned. Distinct messages for missing vs unsupported extension. |
| **FAIL-005** Magic byte mismatch | PASS | 400 returned with descriptive message. |
| **FAIL-006** ZIP bomb | PASS | 400 returned by `_check_zip_bomb()`. |
| **FAIL-007** Encoding detection failure | PASS | 422 returned by `_decode_text()`. |
| **FAIL-008** Processing timeout | PASS | `asyncio.wait_for()` with 120s timeout. 504 returned. |
| **FAIL-009** Concurrent upload limit | PASS | Semaphore(3) check in router. 429 returned. |

---

## 3. Context Engineering Assessment

| Criterion | Status | Notes |
|-----------|--------|-------|
| PROMPT document maintained | PASS | PROMPT-003 is present, marked COMPLETE, lists all created/modified files, tracks all requirements. |
| Implementation follows spec approach | PASS | Three-phase pipeline (extract -> analyze -> unified map -> replace) matches spec. `build_unified_placeholder_map()` replaces `generate_placeholders()` as specified. `resolve_overlaps()` and `replace_entities()` reused from `anonymizer.py` without modification. `anonymize_entities()` and `run_anonymization()` correctly NOT used per-chunk. |
| No unnecessary modifications | PASS | `anonymizer.py` unchanged. Existing tests still pass (90 pre-existing). |
| Code follows existing patterns | PASS | Router structure mirrors `anonymize.py` pattern. Audit logging follows `_emit_audit` pattern. Config follows `pydantic_settings` pattern. |

---

## 4. Test Coverage Assessment

### Spec Test Checklist vs Implementation

**Extractor tests (`test_extractors.py`):** 36 tests

Coverage is strong across all 10 formats. Notable items:

- TXT: UTF-8, empty, non-UTF-8, BOM -- all covered
- CSV: standard, semicolon delimiter, empty cells, empty file -- covered
- JSON: flat, nested, arrays, non-string preservation, deeply nested, invalid -- covered
- XML: text nodes, empty, XXE blocking, invalid -- covered
- HTML: text extraction, script/style stripping, empty -- covered
- XLSX: single sheet, multi-sheet, mixed types, empty, ZIP bomb, corrupted -- covered
- DOCX: paragraphs, table cells, empty, ZIP bomb -- covered
- RTF: basic, empty -- covered
- PDF: text, empty, warning heuristic, corrupted -- covered

**Missing from spec test checklist:**
1. DOCX tracked changes/comments test (EDGE-017) -- spec explicitly lists it
2. DOCX XXE verification test (SEC-003/RISK-005) -- spec explicitly lists it as a required verification step
3. XLSX merged cells test -- spec lists it; not present in tests (though the behavior is implicitly handled by openpyxl's read_only mode)
4. XLSX hidden sheets test (EDGE-014) -- spec lists it; not explicitly tested
5. XLSX empty rows/columns bounded iteration test (EDGE-015) -- spec lists it; not explicitly tested (cell count limit IS tested via `test_corrupted_file` path)
6. TXT undetectable encoding test -- spec lists it; not explicitly in tests (though the `_decode_text` coherence check is the mechanism)

**Processor tests (`test_document_processor.py`):** 16 tests

- `build_unified_placeholder_map()` thoroughly tested (single chunk, same PII across chunks, different values, counter per type, empty)
- `validate_file()` tested (oversized, unsupported extension, no extension, magic byte mismatch, valid files)
- `process_document()` tested (no PII, with PII, empty file, oversized chunk, language detection, language explicit, JSON structured output, CSV output, unsupported format, oversized file)
- Missing: concurrent upload semaphore test (FAIL-009/PERF-004) -- this would be router-level
- Missing: async concurrency verification (mock timing test per spec)

**API integration tests (`test_documents_api.py`):** 17 tests

- Upload for txt, csv, json, xlsx, docx, pdf -- covered
- Language override, allow list, entities filter -- covered
- Error cases: unsupported type, too large, empty, corrupted, no extension -- covered
- Presidio unavailable -- covered
- Audit log verification (no PII) -- covered
- Response structure verification -- covered
- Missing: concurrent upload 429 test (spec lists it)

### Test Quality

Tests are substantive, not trivial. They verify actual behavior with realistic inputs. Mock setup is clean. The `conftest.py` fixtures are well-organized. Tests create real in-memory XLSX/DOCX files for integration testing.

---

## 5. Observations (Non-Blocking)

1. **Missing DOCX XXE verification test (SEC-003/RISK-005):** The spec explicitly requires a test with a crafted DOCX containing `<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>` to verify python-docx/lxml does not resolve external entities. Only the XML extractor XXE test exists. This should be added as a follow-up.

2. **Missing DOCX tracked changes test (EDGE-017):** The spec lists this in the test checklist. While python-docx's default behavior is well-documented, the verification test confirms it works as expected.

3. **Missing concurrent upload 429 test:** The spec lists "4th concurrent upload returns 429" as a test item. Not present in any test file.

4. **Test fixtures directory empty:** The spec lists several sample files (`sample.txt`, `sample.csv`, etc.) to be created in `tests/fixtures/`. Tests instead create fixtures inline (e.g., `_make_xlsx()`, `_make_docx()`). This is functionally equivalent and arguably better (self-contained tests), but diverges from the spec's file list.

5. **Model file naming:** Spec says `documents.py`, implementation uses `document.py`. Trivial.

6. **`_col_num_to_letter_standalone()` duplication:** The `_col_num_to_letter()` function is duplicated in both `extractors.py` and `document_processor.py`. Minor code smell; could be a shared utility. Non-blocking.

7. **Upload semaphore race condition:** In `routers/documents.py` line 80, `sem.locked() and sem._value == 0` accesses a private attribute (`_value`) of `asyncio.Semaphore`. This is not part of the public API and could break across Python versions. The logic also has a TOCTOU issue (check-then-acquire is not atomic). However, the subsequent `async with sem` still provides correct limiting -- the check is just an early-reject optimization. The worst case is that a request that should get 429 instead waits briefly for the semaphore. Non-blocking.

---

## 6. Decision

### APPROVED

The implementation is a faithful and thorough execution of SPEC-003. All 20 functional requirements, 8 security requirements, 4 performance requirements, 5 UX requirements, and 9 failure scenarios are correctly implemented. The code reuses `resolve_overlaps()` and `replace_entities()` from `anonymizer.py` without modification, correctly avoids `anonymize_entities()` for multi-chunk processing, and implements the unified placeholder map as specified.

The observations above are non-blocking improvements that can be addressed in a follow-up commit:
- Add DOCX XXE verification test (SEC-003/RISK-005)
- Add DOCX tracked changes test (EDGE-017)
- Add concurrent upload 429 test (PERF-004/FAIL-009)

---

## 7. Findings Addressed (2026-03-29)

Three non-blocking observations from this review have been resolved:

### 1. DOCX XXE verification test (SEC-003/RISK-005) -- ADDED
- **File:** `tests/test_extractors.py` -- `test_defusedxml_blocks_xxe_in_docx`
- Creates a valid DOCX, then injects an XXE payload (`<!ENTITY xxe SYSTEM "file:///etc/passwd">`) into `word/document.xml` inside the ZIP archive
- Passes the crafted file through `extract_docx()`
- Verifies that either `ExtractionError` is raised (defusedxml blocks the entity) or, if parsing succeeds, no external entity content is present in the output

### 2. DOCX tracked changes test (EDGE-017) -- ADDED
- **File:** `tests/test_extractors.py` -- `test_tracked_changes_known_limitation`
- Creates a DOCX and injects `<w:del>` and `<w:ins>` tracked-change markup into `word/document.xml`
- Verifies that accepted paragraph text IS extracted
- Verifies that deleted tracked-change content (`DELETED_PII_CONTENT`) is NOT included in extraction
- Documents the known limitation that python-docx only reads the accepted document body

### 3. Concurrent upload 429 test (PERF-004/FAIL-009) -- ADDED
- **File:** `tests/test_documents_api.py` -- `test_concurrent_upload_limit_429`
- Patches `_get_upload_semaphore()` to return a semaphore with 0 remaining slots (fully acquired)
- Sends an upload request and verifies it receives 429 Too Many Requests
- Verifies the response detail message contains "Too many"

**Test results after additions:** 177 tests passing (87 new + 90 pre-existing).
