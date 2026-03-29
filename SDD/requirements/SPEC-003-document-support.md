# SPEC-003-document-support

## Executive Summary

- **Based on Research:** RESEARCH-003-document-support.md
- **Creation Date:** 2026-03-29
- **Status:** Draft

## Research Foundation

### Production Issues Addressed
- No prior production issues -- this is a new feature (Feature 3)
- Research critical review identified and resolved 7 critical gaps, 5 questionable assumptions, and 4 missing perspectives before specification
- Key critical review resolutions: multi-chunk pipeline design, `run_anonymization()` reuse clarification, Presidio throughput analysis, encoding detection strategy, memory amplification analysis, ZIP bomb protection, defusedxml coverage verification

### Stakeholder Validation
- **Product Team:** Users upload sensitive documents (Excel, PDF, contracts, employee data), get back anonymized versions they can share or feed to AI. Key metric is format coverage and extraction quality.
- **Engineering Team:** File parsing is the hard part -- each format is a separate extraction problem. Must reuse existing anonymization pipeline primitives, not build parallel paths. Memory and timeout management for large files. File uploads are a significant new attack surface.
- **Support Team:** Anticipated support topics: "Why doesn't my PDF work?" (scanned/image PDFs), "The Excel formatting is different" (users expect pixel-perfect reproduction), encoding issues with non-UTF-8 files. Clear error messages for unsupported scenarios are critical.
- **User:** "I have a spreadsheet with employee data -- I want to anonymize it before using it in ChatGPT." Expects: upload file, get result quickly, mapping works for deanonymization same as text.
- **InfoSec:** File upload is the largest attack surface expansion. Polyglot files, macro-enabled formats, pathological inputs, and resource exhaustion are all addressed.
- **Enterprise IT:** No new ports or services. 7 pure-Python dependencies add ~17MB. No system packages needed.

### System Integration Points
- `src/redakt/services/presidio.py` -- `PresidioClient.analyze()` for PII detection (called per-chunk via bounded async concurrency)
- `src/redakt/services/anonymizer.py` -- `resolve_overlaps()` and `replace_entities()` reused as-is. `generate_placeholders()` and `anonymize_entities()` are NOT used for documents.
- `src/redakt/services/language.py` -- `detect_language()` called ONCE per document
- `src/redakt/services/audit.py` -- Extend with `log_document_upload()` function
- `src/redakt/config.py` -- Add file size limits, supported types, timeout settings
- `src/redakt/main.py` -- Register new documents router; call `defusedxml.defuse_stdlib()` at startup
- `src/redakt/templates/base.html` -- Navigation link for documents page

## Intent

### Problem Statement
Users need to anonymize PII in structured and unstructured documents (Excel spreadsheets, PDFs, Word documents, etc.) before sharing them or feeding them to AI tools. Feature 2 only handles plain text input. Users must currently copy-paste text from each document section individually -- an error-prone and time-consuming process for multi-page or multi-sheet documents.

### Solution Approach
Build a `POST /api/documents/upload` endpoint that accepts file uploads (10 supported formats), extracts text content using format-specific extractors, analyzes all chunks via Presidio REST API with bounded async concurrency, builds a unified placeholder mapping across all chunks, applies replacements, and returns anonymized content plus the mapping as a JSON response. The three-phase pipeline is: (1) extract and analyze all chunks, (2) build unified placeholder map, (3) apply per-chunk replacements.

Key architectural decisions:
- **New `build_unified_placeholder_map()` function** maintains a single `seen` dict and `counters` dict across all chunks, ensuring consistent placeholder numbering document-wide. This replaces `generate_placeholders()` for multi-chunk documents.
- **JSON response for all formats in v1** -- no same-format file downloads. Simplifies API, consistent with Feature 2. Same-format download deferred to v2.
- **Per-document language detection** -- detect once from accumulated text sample (first non-empty chunks up to 5KB), apply uniformly to all Presidio calls.
- **Bounded async concurrency** (`Semaphore(10)` + `asyncio.gather`) for Presidio calls to handle high cell counts efficiently.

### Expected Outcomes
- Users can upload any of 10 supported file formats and receive anonymized content with a unified mapping
- Mapping works with the existing client-side deanonymization from Feature 2
- API consumers (AI agents) receive the same JSON response with mapping for programmatic deanonymization
- No PII is stored server-side at any point -- file contents are processed in memory only
- Processing completes within 120 seconds for files up to 10MB

## Success Criteria

### Functional Requirements

- **REQ-001:** `POST /api/documents/upload` accepts multipart/form-data with a file upload, optional `language` parameter (default "auto"), optional `score_threshold`, optional `entities` filter, and optional `allow_list`. Returns JSON with anonymized content and placeholder mapping. **Multipart parameter serialization:** `entities` and `allow_list` are comma-separated strings in their respective form fields (e.g., `entities=PERSON,EMAIL_ADDRESS`). Empty strings between commas are silently ignored (e.g., `PERSON,,EMAIL_ADDRESS` is treated as `["PERSON", "EMAIL_ADDRESS"]`). Terms containing commas are not supported in the comma-separated format. If `score_threshold` is not provided, the server uses `settings.default_score_threshold` (same fallback as the text anonymize endpoint).

- **REQ-002:** Support 10 file formats: `.txt`, `.md`, `.csv`, `.json`, `.xml`, `.html`, `.xlsx`, `.docx`, `.rtf`, `.pdf`. Each format uses a dedicated extractor function.

- **REQ-003:** Text-based formats (`.txt`, `.md`) are read as plain text with encoding detection. Try UTF-8 first, fall back to `charset-normalizer` detection, error if detection fails or confidence < 0.5.

- **REQ-004:** CSV files are parsed with auto-detected delimiter (`csv.Sniffer`), processed cell-by-cell. Output is anonymized CSV text (native format string within JSON response). CSV output is written with `csv.writer` using the auto-detected delimiter, `csv.QUOTE_MINIMAL` quoting policy (quotes cells only when necessary, e.g., when a cell contains the delimiter or newline), and `\r\n` line terminator (RFC 4180). Note: anonymized placeholders like `<PERSON_1>` do not contain commas or newlines, so they will not require quoting under `QUOTE_MINIMAL`.

- **REQ-005:** JSON files are parsed and string values are recursively extracted. Non-string values (numbers, booleans, null) are preserved unchanged. Output is the anonymized JSON structure in the `anonymized_structured` response field.

- **REQ-006:** XML files are parsed with `defusedxml`. Text nodes are extracted for analysis. Output is anonymized plain text (text content only, tags not preserved in v1).

- **REQ-007:** HTML files are parsed with BeautifulSoup. Script/style content is stripped. Text nodes are extracted for analysis. Output is anonymized plain text.

- **REQ-008:** XLSX files are parsed with openpyxl. All sheets are processed. Each string cell is processed individually. Non-string cells (numbers, dates, formulas, None) are skipped. Merged cells: only the top-left cell is processed. Output is structured JSON: `{sheet_name: [[cell, cell, ...], ...], ...}` in the `anonymized_structured` response field.

- **REQ-009:** DOCX files are parsed with python-docx. Text is extracted from paragraphs and table cells. No formatting preservation in v1. Output is anonymized plain text.

- **REQ-010:** RTF files are converted to plain text via `striprtf`. Output is anonymized plain text.

- **REQ-011:** PDF files are parsed with pdfminer.six. Text-based PDFs only. If extraction produces empty or very short text relative to file size (< 100 chars of extracted text from a file > 10KB in raw size), return a warning: "Limited text could be extracted from this PDF. Results may be incomplete." This is a heuristic that may produce false positives for legitimately short PDFs; this is acceptable as the warning is informational only and does not block processing. The thresholds (100 chars, 10KB) refer to extracted text character count and raw file byte size respectively. Output is anonymized plain text.

- **REQ-012:** Placeholder mapping is unified across all chunks/cells/pages in a document. The same PII value with the same entity type produces the same placeholder everywhere in the document (e.g., "John Smith" in cell A1 and cell B5 both become `<PERSON_1>`). Implemented via `build_unified_placeholder_map()`.

- **REQ-013:** Language is detected ONCE per document, then applied uniformly to all Presidio analyze calls. User can override with explicit `language` parameter. Detection algorithm: concatenate the first N non-empty chunks (in extraction order) until 5KB of text is accumulated. If total extracted text is less than 5KB, use all of it. Pass the concatenated sample to `detect_language()`. This avoids unreliable detection from very short individual chunks (e.g., single Excel cells).

- **REQ-014:** Allow list terms (instance-wide from config + per-request from upload parameter) are passed to every Presidio analyze call for the document.

- **REQ-015:** Audit logging records document upload metadata: action `"document_upload"`, file type (extension), file size (bytes), total entity count, entity types found, language detected, source (`"web_ui"` or `"api"`). NEVER logs filename, file contents, or extracted text.

- **REQ-016:** Web UI provides a document upload page at `GET /documents` with a file input (keyboard-accessible) and optional drag-and-drop enhancement. Form uses HTMX for submission. Results displayed via partial swap showing anonymized content, mapping table, and metadata. **Format-specific rendering:** For XLSX, render each sheet as an HTML `<table>` with rows and cells (one table per sheet, with sheet name as heading). For JSON, render the anonymized JSON structure as formatted JSON in a `<pre><code>` block. For all other formats (text, CSV, PDF, DOCX, RTF, XML, HTML), render as plain text in a `<pre>` block.

- **REQ-017:** Web UI upload form clearly displays the list of supported file formats and the maximum file size before the user selects a file.

- **REQ-018:** Mapping returned from document upload is compatible with the existing Feature 2 client-side deanonymization. The `deanonymize.js` mapping variable is populated from the document upload response's `data-mappings` attribute, same pattern as Feature 2.

- **REQ-019:** Response JSON uses exactly one of two fields: `anonymized_content` (string, for text-based outputs: txt, md, rtf, pdf, docx, xml, html, csv) or `anonymized_structured` (object, for structured outputs: json, xlsx). Never both populated, never both null when content exists. For empty files: text-based formats return `anonymized_content: ""` (empty string) and `anonymized_structured: null`; XLSX returns `anonymized_structured: {}` (empty object) and `anonymized_content: null`; JSON returns `anonymized_structured: null` (the parsed empty/null JSON) and `anonymized_content: null`.

- **REQ-020:** Presidio analyze calls use bounded async concurrency: `asyncio.Semaphore(10)` with `asyncio.gather()`. This limits concurrent Presidio REST calls to 10 at a time.

### Non-Functional Requirements

- **PERF-001:** Document processing completes within 120 seconds for files up to 10MB on the reference Docker Compose stack with default resource limits (as defined in `docker-compose.yml`). This is environment-dependent and may vary on resource-constrained containers. Configurable via `REDAKT_DOCUMENT_PROCESSING_TIMEOUT`.
- **PERF-002:** Bounded async concurrency (Semaphore(10)) enables processing of 2000 Excel cells in approximately 4-8 seconds at typical Presidio latency (10-30ms per short cell). This is an informational estimate, not a hard requirement -- actual latency depends on Presidio hardware, model, and input complexity. The testable requirement is that concurrent execution occurs (verified by mock timing in unit tests).
- **PERF-003:** Per-chunk text size is bounded by the existing `max_text_length` (512KB). If a single cell/chunk exceeds this, skip it and replace its content with `[CONTENT TOO LARGE - SKIPPED]` in the output, adding a warning to `metadata.warnings` (see EDGE-013 for full behavior).

- **PERF-004:** Document upload concurrency limited by a server-side `asyncio.Semaphore(3)` at the router level. Requests that cannot acquire the semaphore immediately return 429 Too Many Requests. Limit configurable via `REDAKT_MAX_CONCURRENT_UPLOADS` (default: 3).

- **SEC-001:** File size validated before processing. Maximum 10MB (configurable via `REDAKT_MAX_FILE_SIZE`). Return 413 if exceeded.
- **SEC-002:** File type validated by extension whitelist AND magic bytes verification for binary formats (PDF: `%PDF-`, XLSX/DOCX: PK ZIP header `50 4B 03 04`).
- **SEC-003:** `defusedxml.defuse_stdlib()` called at application startup (in `main.py`) before any XML parsing. Prevents XXE and billion laughs attacks in stdlib XML parsers (xml.etree, xml.sax, xml.dom). **lxml coverage gap:** `python-docx` depends on `lxml` as a hard dependency. `defusedxml.defuse_stdlib()` does NOT patch lxml parsers. However, DOCX files are ZIP archives -- `python-docx` parses XML from within the ZIP entries, not from external URLs. The XML content originates from the uploaded file, not from external entity resolution. Combined with SEC-004 (ZIP bomb check limiting uncompressed size to 100MB), the practical XXE risk is limited to crafted XML within the ZIP archive. Mitigation: (1) Call `defusedxml.defuse_stdlib()` for stdlib coverage, (2) for DOCX processing, verify during implementation that `python-docx` does not resolve external entities by adding a test with a crafted DOCX containing an XXE payload (`<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>`), (3) if the test shows lxml resolves external entities, add `defusedxml.lxml` wrappers or configure lxml with `resolve_entities=False`. Document this as a required implementation verification step.
- **SEC-004:** ZIP bomb protection for XLSX/DOCX: before parsing, open with `zipfile.ZipFile`, sum `info.file_size` for all entries. Reject if total uncompressed size exceeds 100MB (10x max upload size).
- **SEC-005:** Filename sanitized: strip path components, limit length, remove special characters. Used only for display/metadata; never used for filesystem operations.
- **SEC-006:** No PII at rest. File contents processed in memory only. Starlette's `UploadFile` auto-cleanup handles temporary files. Audit logs never contain filenames, file contents, or extracted text.
- **SEC-007:** Macro-enabled formats (`.xlsm`, `.docm`) are NOT in the supported extension list and are rejected.
- **SEC-008:** Content-type from client is NOT trusted. Validation relies on extension + magic bytes only.

- **UX-001:** File upload input is keyboard-accessible (`<input type="file">` as primary mechanism). Drag-and-drop is an enhancement, not a requirement. The drag-and-drop target area must not trap keyboard focus (i.e., Tab should move past it to the next focusable element). "Keyboard-accessible" means: Tab to the file input, Enter/Space to open the file dialog.
- **UX-002:** Loading/spinner state shown during document processing via HTMX `hx-indicator`.
- **UX-003:** Error recovery: if processing fails, user sees a clear error message and can upload again without page refresh (HTMX partial swap).
- **UX-004:** Supported formats and size limit displayed on the upload form before file selection. Include a note about detection accuracy for spreadsheets: "Detection accuracy is lower for short cell values (single names, abbreviations). For best results, use cells with full names and complete information." (See RISK-002.)
- **UX-005:** Client-side JavaScript checks `file.size` against the configured maximum file size before allowing HTMX form submission. If the file exceeds the limit, show an inline error message without making a server request. This prevents uploading large files that would be rejected by the server with 413.

## Edge Cases (Research-Backed)

- **EDGE-001: Empty files**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #1"
  - Desired behavior: Return immediately with empty content, empty mapping. No error.
  - Test approach: Upload 0-byte files for each supported format, verify empty content response.

- **EDGE-002: Password-protected files**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #2"
  - Desired behavior: Detect and return 422 error: "This file appears to be password-protected. Please remove the password and re-upload."
  - Test approach: Upload password-protected XLSX and PDF, verify error message.

- **EDGE-003: Corrupted files**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #3"
  - Desired behavior: Catch parser exceptions (openpyxl, pdfminer, python-docx errors), return 422: "The file could not be parsed. It may be corrupted or in an unsupported variant."
  - Test approach: Upload files with valid extensions but invalid content (e.g., random bytes renamed to .xlsx), verify graceful error.

- **EDGE-004: Files with no extractable text**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #5"
  - Desired behavior: Return content unchanged (empty string), empty mapping. For PDFs, include warning about limited extraction.
  - Test approach: Upload image-only PDF, empty Excel workbook, verify appropriate response.

- **EDGE-005: Mixed content Excel**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #6"
  - Desired behavior: Process only string cells. Skip formula cells, number cells, date cells, None cells, error cells. Merged cells: process only top-left cell.
  - Test approach: Create XLSX fixture with mixed cell types, verify only string cells are anonymized.

- **EDGE-006: Multi-sheet Excel with cross-sheet consistency**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #7"
  - Desired behavior: Same PII value in different sheets maps to the same placeholder. Unified mapping spans all sheets.
  - Test approach: Create XLSX with same name in Sheet1 and Sheet2, verify single placeholder in mapping.

- **EDGE-007: Non-UTF-8 encoded text files**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #8" and "Text Encoding Detection" section
  - Desired behavior: Auto-detect encoding via charset-normalizer. UTF-8 BOM or UTF-16 BOM detected first. If detection confidence < 0.5, return 422: "Could not determine file encoding. Please save the file as UTF-8 and re-upload."
  - Test approach: Upload Windows-1252 encoded CSV with German umlauts, verify correct handling.

- **EDGE-008: CSV delimiter detection**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #9"
  - Desired behavior: Auto-detect delimiter using `csv.Sniffer().sniff()`. If sniffing fails, default to comma. Output uses the detected delimiter.
  - Test approach: Upload semicolon-delimited CSV (German/European format), verify correct parsing.

- **EDGE-009: Deeply nested JSON**
  - Research reference: "Production Edge Cases -- File Format Edge Cases #10"
  - Desired behavior: Recursively extract string values from arbitrary nesting depth. Non-string leaves preserved unchanged.
  - Test approach: Upload JSON with 5+ levels of nesting containing PII strings, verify all are anonymized.

- **EDGE-010: PII spanning cell boundaries**
  - Research reference: "Production Edge Cases -- PII Detection Edge Cases #11"
  - Desired behavior: Known v1 limitation. First name in column A and last name in column B are NOT detected as a single PERSON entity. Cell-by-cell processing cannot detect cross-cell PII.
  - Test approach: Document as known limitation. No automated test needed.

- **EDGE-011: Very short cell text with low detection confidence**
  - Research reference: "Production Edge Cases -- PII Detection Edge Cases #12" and Decision 2
  - Desired behavior: Known v1 limitation. A cell containing just "Smith" may not be detected as PERSON due to insufficient context. Accept lower detection rates for very short cell values.
  - Test approach: Document as known limitation. Include in user-facing documentation.

- **EDGE-012: Image-based (scanned) PDF**
  - Research reference: Decision 3
  - Desired behavior: pdfminer.six returns empty/minimal text. If extracted text < 100 chars from a file > 10KB, return content with warning: "Limited text could be extracted from this PDF. Results may be incomplete. Scanned or image-based PDFs are not supported in this version."
  - Test approach: Upload an image-only PDF, verify warning message in response.

- **EDGE-013: Pathological single-cell content**
  - Research reference: "Security Considerations -- Additional File Upload Security #16"
  - Desired behavior: If a single chunk exceeds `max_text_length` (512KB), **skip it** and replace its content with the placeholder `[CONTENT TOO LARGE - SKIPPED]` in the output. Add a warning to `metadata.warnings`: "One or more chunks exceeded the maximum text size (512KB) and were skipped." The skipped chunk's original text is NOT included in the output (to avoid returning un-anonymized PII). Processing continues for all remaining chunks.
  - Test approach: Create CSV with one cell containing > 512KB text, verify it is replaced with the placeholder, warning is present, and other cells are processed normally.

- **EDGE-014: Hidden sheets in Excel**
  - Research reference: Decision 2 XLSX edge cases
  - Desired behavior: Process hidden sheets by default (they may contain PII). Include hidden sheet content in output.
  - Test approach: Create XLSX with hidden sheet containing PII, verify it is processed.

- **EDGE-015: XLSX with thousands of empty rows/columns**
  - Research reference: Critical review finding -- openpyxl `iter_rows()` without bounds
  - Desired behavior: For XLSX, iterate only over `ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column)` and skip `None`/empty cells before chunk creation. If the total non-empty text cell count exceeds 50,000, stop processing and return 422: "This spreadsheet contains too many cells to process (limit: 50,000 text cells). Please reduce the data or split into smaller files."
  - Test approach: Create XLSX with formatting applied far beyond actual data, verify iteration is bounded. Create XLSX with >50,000 non-empty text cells, verify 422 error.

- **EDGE-016: HTML with large embedded data URIs**
  - Research reference: Critical review finding -- inline data URIs
  - Desired behavior: HTML files with very large embedded data URIs (e.g., base64-encoded images in `<img src="data:...">`) are parsed normally by BeautifulSoup. The data URI content is stripped during `get_text()` extraction. No special handling needed beyond the 10MB file size limit.
  - Test approach: Document as known behavior. No special test needed.

- **EDGE-017: DOCX with tracked changes and comments**
  - Research reference: Critical review finding -- tracked changes as PII leakage vector
  - Desired behavior: DOCX tracked changes (insertions, deletions, revisions) and comments are NOT processed in v1. Only accepted paragraph text and table cell text are extracted via `python-docx`. Tracked changes and comments may contain PII (reviewer names, suggested text) that is not anonymized. This is a known v1 limitation.
  - Test approach: Document as known limitation. Add to user-facing documentation. Create DOCX with tracked changes containing PII, verify they are not included in extracted text (confirming python-docx default behavior).

- **EDGE-018: RTF with embedded OLE objects**
  - Research reference: Critical review finding -- RTF embedded objects
  - Desired behavior: RTF files may contain embedded OLE objects (images, other documents). The `striprtf` library ignores embedded objects during text extraction. Only plain text content is extracted and anonymized.
  - Test approach: Document as known behavior.

- **EDGE-019: CSV delimiter override (dropped research finding)**
  - Research reference: RESEARCH-003 Data Engineering section -- "csv.Sniffer().sniff() with fallback parameter for manual override"
  - Desired behavior: Deferred to v2. For v1, CSV delimiter is auto-detected via `csv.Sniffer().sniff()` with comma as the fallback (EDGE-008). A manual delimiter override parameter could be added in v2 if auto-detection proves unreliable for specific delimiter types. Documenting this as a known v2 enhancement.
  - Test approach: No test needed for v1.

## Failure Scenarios

- **FAIL-001: Presidio Analyzer unavailable**
  - Trigger condition: Presidio Analyzer service is down or unreachable during document processing
  - Expected behavior: Return 503 Service Unavailable. Reuse existing `ConnectError` handling pattern.
  - User communication: "PII detection service is currently unavailable. Please try again later."
  - Recovery approach: Automatic -- next request retries the connection.

- **FAIL-002: Presidio Analyzer timeout or error during chunk processing**
  - Trigger condition: Analyzer request exceeds timeout, returns 5xx, or connection fails during document processing
  - Expected behavior: If any single Presidio analyze call fails (timeout, 5xx, connection error), the entire document upload fails with the corresponding error code (504 for timeout, 502 for 5xx, 503 for connection error). Cancel remaining in-progress chunks and return the error. Partial results are NOT returned in v1.
  - User communication: "PII detection timed out. The document may be too large or complex. Please try a smaller file."
  - Recovery approach: User tries with a smaller document or retries.

- **FAIL-003: File exceeds size limit**
  - Trigger condition: Uploaded file exceeds 10MB (`REDAKT_MAX_FILE_SIZE`)
  - Expected behavior: Return 413 Payload Too Large. Check file size before any processing.
  - User communication: "File exceeds the maximum size of 10MB. Please upload a smaller file."
  - Recovery approach: User reduces file size or splits document.

- **FAIL-004: Unsupported file format**
  - Trigger condition: File extension not in the supported whitelist, or file has no extension
  - Expected behavior: Return 400 Bad Request.
  - User communication: If file has an unsupported extension: "Unsupported file format '.{ext}'. Supported formats: .txt, .md, .csv, .json, .xml, .html, .xlsx, .docx, .rtf, .pdf". If file has no extension: "Unsupported file format. Supported formats: .txt, .md, .csv, .json, .xml, .html, .xlsx, .docx, .rtf, .pdf"
  - Recovery approach: User converts file to a supported format or adds the correct extension.

- **FAIL-005: File type mismatch (magic bytes)**
  - Trigger condition: File extension does not match magic bytes (e.g., .pdf extension but not a PDF file)
  - Expected behavior: Return 400 Bad Request.
  - User communication: "The file content does not match the expected format for '.{ext}'. The file may be corrupted or mislabeled."
  - Recovery approach: User verifies file is the correct format.

- **FAIL-006: ZIP bomb detected**
  - Trigger condition: XLSX or DOCX file's total uncompressed size exceeds 100MB
  - Expected behavior: Return 400 Bad Request. Do not proceed with decompression.
  - User communication: "The file's compressed content is too large to process safely. Please use a simpler document."
  - Recovery approach: User uploads a different file.

- **FAIL-007: Encoding detection failure**
  - Trigger condition: Text file encoding cannot be determined (confidence < 0.5)
  - Expected behavior: Return 422 Unprocessable Entity.
  - User communication: "Could not determine file encoding. Please save the file as UTF-8 and re-upload."
  - Recovery approach: User re-saves file as UTF-8.

- **FAIL-008: Document processing timeout**
  - Trigger condition: Total document processing exceeds 120 seconds
  - Expected behavior: Return 504 Gateway Timeout. Cancel all in-progress Presidio calls.
  - User communication: "Document processing timed out. The file may contain too many text cells to process within the time limit."
  - Recovery approach: User uploads a smaller document.

- **FAIL-009: Concurrent upload limit exceeded**
  - Trigger condition: Document upload request arrives while 3 (or `REDAKT_MAX_CONCURRENT_UPLOADS`) other document uploads are already being processed
  - Expected behavior: Return 429 Too Many Requests. Do not queue the request.
  - User communication: "Too many documents are being processed. Please try again shortly."
  - Recovery approach: User retries after a brief wait.

## Implementation Constraints

### Technical Constraints
- Presidio Analyzer REST API is the only PII detection mechanism (no library embedding)
- Presidio Anonymizer `/anonymize` endpoint is NOT used -- Redakt performs its own text replacement
- `presidio-structured` Python library CANNOT be used (Redakt communicates with Presidio via REST only)
- `anonymize_entities()` and `run_anonymization()` are NOT called per-chunk (they produce independent placeholder numbering per call)
- `resolve_overlaps()` and `replace_entities()` from `anonymizer.py` ARE reused without modification
- `generate_placeholders()` is NOT used for documents; `build_unified_placeholder_map()` replaces it
- `src/redakt/services/anonymizer.py` requires NO modifications
- HTMX for server interactions, vanilla JS for client-only logic (no JS framework)
- FastAPI + Pydantic for request/response validation
- Jinja2 templates with HTMX partial swaps
- All 7 new dependencies are pure Python, MIT/BSD/PSF licensed, no system packages

### Context Requirements
- **Maximum context utilization:** <40% during implementation
- **Essential files for implementation:**
  - `src/redakt/services/anonymizer.py` -- `resolve_overlaps()`, `replace_entities()` interfaces
  - `src/redakt/services/presidio.py` -- `PresidioClient.analyze()` interface
  - `src/redakt/routers/anonymize.py` -- Pattern for router structure, `AnonymizationError`, `run_anonymization()` reference
  - `src/redakt/models/anonymize.py` -- Response model pattern
  - `src/redakt/services/audit.py` -- Audit logging pattern (`_emit_audit()`, `log_anonymization()`)
  - `src/redakt/config.py` -- Settings pattern
  - `src/redakt/main.py` -- Router registration, middleware, lifespan
  - `src/redakt/templates/base.html` -- Template structure, nav links
- **Files that can be delegated to subagents:**
  - `src/redakt/services/extractors.py` -- Individual extractor functions (after interface is defined)
  - `tests/test_extractors.py` -- Unit tests (after extractors are built)
  - `tests/test_documents_api.py` -- API tests (after endpoint is built)
  - `tests/e2e/test_documents_e2e.py` -- E2E tests (after web UI is built)
  - Test fixtures -- Sample files with known PII

## Validation Strategy

### Automated Testing

**Unit Tests -- Extractors (`tests/test_extractors.py`):**
- [ ] TXT extractor: UTF-8 text returns content correctly
- [ ] TXT extractor: empty file returns empty string
- [ ] TXT extractor: non-UTF-8 encoding (Windows-1252 with umlauts) detected and decoded
- [ ] TXT extractor: undetectable encoding returns error
- [ ] MD extractor: Markdown formatting preserved in extracted text
- [ ] CSV extractor: standard comma-delimited CSV returns list of cell texts
- [ ] CSV extractor: semicolon-delimited CSV auto-detected
- [ ] CSV extractor: empty cells handled (skipped or empty string)
- [ ] JSON extractor: flat object string values extracted
- [ ] JSON extractor: nested object string values extracted recursively
- [ ] JSON extractor: array of objects processed
- [ ] JSON extractor: non-string values (numbers, booleans, null) preserved
- [ ] XML extractor: text nodes extracted from well-formed XML
- [ ] XML extractor: defusedxml blocks XXE attempt
- [ ] HTML extractor: text content extracted, script/style stripped
- [ ] XLSX extractor: single sheet with string cells extracted
- [ ] XLSX extractor: multi-sheet workbook, all sheets extracted
- [ ] XLSX extractor: mixed cell types (string, number, formula, None), only strings extracted
- [ ] XLSX extractor: merged cells, only top-left cell processed
- [ ] XLSX extractor: hidden sheets processed
- [ ] XLSX extractor: ZIP bomb detection (oversized uncompressed content rejected)
- [ ] XLSX extractor: cell count limit (>50,000 text cells returns error) (EDGE-015)
- [ ] XLSX extractor: empty rows/columns beyond data range not iterated (EDGE-015)
- [ ] DOCX extractor: paragraphs and table cells extracted
- [ ] DOCX extractor: empty document returns empty
- [ ] DOCX extractor: ZIP bomb detection
- [ ] DOCX extractor: tracked changes/comments NOT included in extracted text (EDGE-017)
- [ ] DOCX extractor: XXE verification test -- crafted DOCX with XXE entity payload does not resolve external entities (SEC-003/RISK-005)
- [ ] RTF extractor: basic RTF converted to plain text
- [ ] RTF extractor: empty RTF returns empty
- [ ] PDF extractor: text-based PDF, text extracted per page
- [ ] PDF extractor: empty PDF returns empty
- [ ] PDF extractor: multi-page PDF, all pages extracted
- [ ] PDF extractor: image-only PDF returns minimal text with warning flag

**Unit Tests -- Document Processor (`tests/test_document_processor.py`):**
- [ ] `build_unified_placeholder_map()`: single chunk produces correct mapping
- [ ] `build_unified_placeholder_map()`: multiple chunks, same PII value maps to same placeholder
- [ ] `build_unified_placeholder_map()`: different PII values get different placeholders
- [ ] `build_unified_placeholder_map()`: counter increments per entity type across chunks
- [ ] Single-chunk processing (text file): anonymized text + correct mapping returned
- [ ] Multi-chunk processing (Excel cells): consistent mapping across all cells
- [ ] Empty document (no text extracted): returns empty content, empty mapping
- [ ] Oversized chunk handling: chunk > 512KB replaced with `[CONTENT TOO LARGE - SKIPPED]` and warning added (EDGE-013)
- [ ] Language detection: uses concatenated first-N-chunks sample up to 5KB (REQ-013)
- [ ] File validation: rejects oversized files (> 10MB)
- [ ] File validation: rejects unsupported extension
- [ ] File validation: rejects magic byte mismatch
- [ ] File validation: rejects file with no extension (FAIL-004)
- [ ] Concurrent upload semaphore: 4th concurrent upload returns 429 (PERF-004/FAIL-009)
- [ ] Async concurrency: multiple Presidio calls execute with bounded concurrency (mock verify)

**Integration Tests (`tests/test_documents_api.py`):**
- [ ] Upload `.txt` file with PII: returns anonymized text + mapping
- [ ] Upload `.csv` file: returns anonymized CSV text
- [ ] Upload `.json` file: returns anonymized JSON structure
- [ ] Upload `.xlsx` file: returns anonymized sheet structure
- [ ] Upload `.pdf` file: returns anonymized text
- [ ] Upload `.docx` file: returns anonymized text
- [ ] Language detection: auto-detect applied to document
- [ ] Language override: explicit language parameter used
- [ ] Allow list: per-request terms excluded from anonymization
- [ ] Unsupported file type: returns 400
- [ ] File too large: returns 413
- [ ] Empty file: returns empty content gracefully
- [ ] Corrupted file: returns 422
- [ ] Presidio unavailable: returns 503
- [ ] Audit log emitted with correct metadata (action, file_type, entity counts, no PII)
- [ ] Response structure: exactly one of `anonymized_content` or `anonymized_structured` populated

**E2E Tests (`tests/e2e/test_documents_e2e.py`):**
- [ ] File upload flow: upload a text file with known PII via browser, verify anonymized output displayed
- [ ] Mapping returned: verify mapping is available for deanonymization after document upload
- [ ] Error display: upload unsupported file type, verify error message shown in browser
- [ ] Large file rejection: attempt to upload oversized file, verify error message

### Manual Verification
- [ ] Full flow: upload Excel with PII -> view anonymized content -> use mapping for deanonymization
- [ ] PDF upload with text-based PDF -> verify extraction quality
- [ ] CSV with semicolons (European format) -> verify correct parsing
- [ ] File upload keyboard accessibility (no mouse required)
- [ ] Spinner/loading indicator during processing
- [ ] Error recovery: upload bad file -> see error -> upload good file -> works without refresh
- [ ] API response matches contract (`anonymized_content`, `anonymized_structured`, `mappings`, `language_detected`, `source_format`, `metadata`)
- [ ] Feature 1 (detect) and Feature 2 (anonymize) still work correctly after Feature 3 changes

### Performance Validation
- [ ] 10MB text file processes within 120 seconds
- [ ] Excel with 500+ text cells processes within 60 seconds
- [ ] Per-chunk Presidio calls show concurrent execution (not sequential)

## Dependencies and Risks

### External Dependencies
- Presidio Analyzer service (port 5002) -- must be running for PII detection
- HTMX CDN (`unpkg.com`) -- must be reachable for web UI (mitigated by SRI)
- 7 new Python packages: pdfminer.six, openpyxl, python-docx, striprtf, beautifulsoup4, defusedxml, charset-normalizer (all MIT/BSD/PSF, pure Python)

### Identified Risks

- **RISK-001: PDF extraction quality varies**
  - Description: pdfminer.six may produce poor results for multi-column layouts, complex tables, or unusual font encodings.
  - Likelihood: Medium (common in enterprise documents)
  - Impact: Medium (user gets incomplete anonymization)
  - Mitigation: Return warning when extraction produces minimal text. Document limitation. If quality is unacceptable for common use cases, evaluate PyMuPDF (AGPL) or commercial license in v2.

- **RISK-002: Short cell values have low PII detection rates**
  - Description: Cells containing just "Smith" or "Berlin" may not be detected as PII by Presidio NLP models due to insufficient context. This is the primary use case's biggest weakness -- the main persona ("I have a spreadsheet with employee data") will encounter this in nearly every upload.
  - Likelihood: HIGH (very common in spreadsheets -- the expected use case)
  - Impact: HIGH (missed PII in output erodes user trust)
  - Mitigation: Accept as v1 known limitation. Document for users. **The document upload page (UX-004) must include a user-facing note:** "Detection accuracy is lower for short cell values (single names, abbreviations). For best results, use cells with full names and complete information." v2 could add column-header hinting to boost detection for known PII columns.

- **RISK-003: Memory amplification for large files**
  - Description: A 10MB XLSX can expand to 100-150MB in Python objects. Concurrent uploads multiply this. Enterprise users uploading 10MB Excel files is the expected use case, not an edge case.
  - Likelihood: HIGH (large files are expected in enterprise use)
  - Impact: HIGH (OOM-killing the container affects all concurrent users)
  - Mitigation: 10MB file size limit constrains worst case. Document recommended minimum container memory (1GB). **v1 includes a server-side document upload concurrency semaphore:** `asyncio.Semaphore(3)` at the router level, limiting concurrent document uploads to 3. Requests beyond the limit receive 429 Too Many Requests: "Too many documents are being processed. Please try again shortly." This prevents OOM from concurrent large uploads. The semaphore limit is configurable via `REDAKT_MAX_CONCURRENT_UPLOADS` (default: 3).

- **RISK-004: Presidio throughput bottleneck**
  - Description: Presidio's single-worker Flask server may become a bottleneck under concurrent cell processing.
  - Likelihood: LOW (bounded async concurrency effectively addresses this)
  - Impact: LOW after mitigation (Semaphore(10) at 20ms latency processes 2000 cells in ~4 seconds)
  - Mitigation: Semaphore(10) limits concurrent calls. If bottleneck occurs, Presidio can be scaled to multiple workers via gunicorn in docker-compose.

- **RISK-005: defusedxml coverage gap with lxml (CONFIRMED)**
  - Description: `python-docx` requires `lxml` as a hard dependency. `defusedxml.defuse_stdlib()` does NOT cover lxml parsers. This is a confirmed gap, not speculative.
  - Likelihood: High (lxml is always present when python-docx is installed)
  - Impact: High (potential XXE vulnerability)
  - Mitigation: The practical risk is reduced because DOCX XML comes from within ZIP archives (not external URLs), but a crafted DOCX could still contain XXE payloads. Required implementation steps: (1) Write a verification test with a crafted DOCX containing an XXE entity reference, (2) if lxml resolves external entities during python-docx parsing, configure lxml with `resolve_entities=False` or use `defusedxml.lxml` wrappers, (3) document the test results. See SEC-003 for full details.

## Implementation Notes

### New Files to Create

| File | Purpose |
|------|---------|
| `src/redakt/models/documents.py` | `DocumentUploadResponse` Pydantic model with `anonymized_content`, `anonymized_structured`, `mappings`, `language_detected`, `source_format`, `metadata` |
| `src/redakt/services/extractors.py` | One extractor function per format. Returns list of text chunks. Handles encoding detection, ZIP bomb checks, defusedxml. |
| `src/redakt/services/document_processor.py` | `build_unified_placeholder_map()`, `process_document()` orchestration (extract -> analyze concurrently -> unified map -> replace per chunk -> reassemble) |
| `src/redakt/routers/documents.py` | `POST /api/documents/upload` endpoint, `DocumentProcessingError` exception, file validation logic, web route for upload page |
| `src/redakt/templates/documents.html` | File upload page with file input, format list, size limit display, HTMX form |
| `src/redakt/templates/partials/document_results.html` | HTMX partial for upload results: anonymized content, mapping table, metadata |
| `tests/test_extractors.py` | Unit tests for each format extractor (~30 tests) |
| `tests/test_document_processor.py` | Unit tests for `build_unified_placeholder_map()` and processing pipeline (~11 tests) |
| `tests/test_documents_api.py` | Integration tests for API endpoint with mocked Presidio (~16 tests) |
| `tests/e2e/test_documents_e2e.py` | Browser-level file upload E2E tests (~4 tests) |
| `tests/fixtures/sample.txt` | Text file with known PII |
| `tests/fixtures/sample.csv` | CSV with 3 rows, names and emails |
| `tests/fixtures/sample.json` | Nested JSON with PII values |
| `tests/fixtures/sample.xlsx` | 2 sheets, names in cells |
| `tests/fixtures/sample.docx` | 2 paragraphs with names |
| `tests/fixtures/sample.pdf` | 1 page text PDF with names |

### Existing Files to Modify

| File | Change |
|------|--------|
| `src/redakt/main.py` | Register documents router. Add `import defusedxml; defusedxml.defuse_stdlib()` at module level (before openpyxl/python-docx imports). |
| `src/redakt/config.py` | Add `max_file_size: int = 10 * 1024 * 1024`, `supported_file_types: list[str]`, `document_processing_timeout: float = 120.0`, `max_zip_uncompressed_size: int = 100 * 1024 * 1024`, `max_concurrent_uploads: int = 3`, `max_xlsx_cells: int = 50_000` |
| `src/redakt/services/audit.py` | Add `log_document_upload()` function with file_type, file_size_bytes, entity_count, entity_types, language, source parameters |
| `src/redakt/templates/base.html` | Add nav link to documents page |
| `src/redakt/routers/pages.py` | Add `GET /documents` page route and `POST /documents/submit` HTMX route |
| `pyproject.toml` | Add 7 new dependencies: pdfminer.six, openpyxl, python-docx, striprtf, beautifulsoup4, defusedxml, charset-normalizer |

### API Contract

#### REST API

**`POST /api/documents/upload`**

Request (multipart/form-data):
- `file` (required) -- The file to upload
- `language` (optional, default "auto") -- Language code or "auto" for auto-detection
- `score_threshold` (optional) -- Minimum confidence score (0.0-1.0)
- `entities` (optional) -- Comma-separated list of entity types to detect
- `allow_list` (optional) -- Comma-separated list of terms to exclude from detection

Response (JSON):
```json
{
  "anonymized_content": "Please review <PERSON_1>'s contract...",
  "anonymized_structured": null,
  "mappings": {
    "<PERSON_1>": "John Smith",
    "<EMAIL_ADDRESS_1>": "john@example.com"
  },
  "language_detected": "en",
  "source_format": "pdf",
  "metadata": {
    "pages_processed": 3,
    "cells_processed": null,
    "sheets_processed": null,
    "chunks_analyzed": 3,
    "file_size_bytes": 245000,
    "warnings": []
  }
}
```

For CSV:
```json
{
  "anonymized_content": "Name,Email\r\n<PERSON_1>,<EMAIL_ADDRESS_1>\r\n<PERSON_2>,<EMAIL_ADDRESS_2>\r\n",
  "anonymized_structured": null,
  "mappings": {
    "<PERSON_1>": "John Smith",
    "<EMAIL_ADDRESS_1>": "john@example.com",
    "<PERSON_2>": "Jane Doe",
    "<EMAIL_ADDRESS_2>": "jane@example.com"
  },
  "language_detected": "en",
  "source_format": "csv",
  "metadata": {
    "pages_processed": null,
    "cells_processed": 4,
    "sheets_processed": null,
    "chunks_analyzed": 4,
    "file_size_bytes": 1200,
    "warnings": []
  }
}
```

For XLSX:
```json
{
  "anonymized_content": null,
  "anonymized_structured": {
    "Sheet1": [
      ["Name", "Email"],
      ["<PERSON_1>", "<EMAIL_ADDRESS_1>"]
    ],
    "Sheet2": [
      ["Manager"],
      ["<PERSON_2>"]
    ]
  },
  "mappings": {
    "<PERSON_1>": "John Smith",
    "<EMAIL_ADDRESS_1>": "john@example.com",
    "<PERSON_2>": "Jane Doe"
  },
  "language_detected": "en",
  "source_format": "xlsx",
  "metadata": {
    "pages_processed": null,
    "cells_processed": 4,
    "sheets_processed": 2,
    "chunks_analyzed": 4,
    "file_size_bytes": 15000,
    "warnings": []
  }
}
```

Error responses:
- 400: Unsupported file format (including no extension), magic byte mismatch, ZIP bomb detected
- 413: File exceeds size limit
- 422: Password-protected file, corrupted file, encoding detection failure, too many cells (>50,000)
- 429: Too many concurrent document uploads
- 502: Presidio Analyzer returned an error (5xx)
- 503: Presidio Analyzer unavailable (connection error)
- 504: Processing timeout

#### Web UI Contract

**`GET /documents`** -- Renders `documents.html` (full page with upload form).

**`POST /documents/submit`** -- HTMX form submission. Returns `partials/document_results.html`.

Form fields:
- `file` -- File input (`<input type="file" accept=".txt,.md,.csv,.json,.xml,.html,.xlsx,.docx,.rtf,.pdf">`)
- `language` -- Language selector (auto/en/de)

HTMX attributes:
```html
<form hx-post="/documents/submit" hx-target="#document-results" hx-indicator="#spinner" hx-encoding="multipart/form-data">
```

Partial response on success:
```html
<div id="document-output" data-mappings='{"&lt;PERSON_1&gt;": "John Smith"}'>
  <h2>Anonymized Content</h2>
  <pre id="anonymized-content">...</pre>
  <button id="copy-btn">Copy to clipboard</button>
  <details>
    <summary>Mapping (N entries)</summary>
    <table>...</table>
  </details>
  <p class="meta">Format: pdf | Language: en | Chunks analyzed: 3</p>
</div>
```

Partial response on error (same pattern as Feature 2):
```html
<div class="result error"><p>Error message here</p></div>
```

### Core Algorithm: Document Processing Pipeline

1. **Validate file:** Check size (< 10MB), extension (in whitelist), magic bytes (for binary formats), ZIP manifest (for XLSX/DOCX, uncompressed < 100MB)
2. **Extract text:** Call format-specific extractor. Returns `list[TextChunk]` where `TextChunk` has `text`, `chunk_id` (e.g., cell ref, page number), and `chunk_type` (e.g., "cell", "page", "paragraph")
3. **Filter empty chunks:** Remove chunks with empty or whitespace-only text
4. **Detect language:** Concatenate the first N non-empty chunks (in extraction order) until 5KB of text is accumulated; if total text is < 5KB, use all of it. Pass the concatenated sample to `detect_language()`.
5. **Validate language:** Check against `settings.supported_languages`
6. **Merge allow lists:** Instance-wide + per-request
7. **Analyze all chunks concurrently:**
   ```python
   semaphore = asyncio.Semaphore(10)
   async def analyze_chunk(chunk):
       async with semaphore:
           results = await presidio.analyze(chunk.text, language, ...)
           resolved = resolve_overlaps(results)
           # Enrich with original_text
           for r in resolved:
               r["original_text"] = chunk.text[r["start"]:r["end"]]
           # Sort by position for consistent numbering
           resolved.sort(key=lambda e: e["start"])
           return resolved
   all_chunk_entities = await asyncio.gather(*[analyze_chunk(c) for c in chunks])
   ```
8. **Build unified placeholder map:** `build_unified_placeholder_map(all_chunk_entities)` returns `(global_mappings, per_chunk_maps)`
9. **Apply replacements per chunk:** `replace_entities(chunk.text, chunk_entities, per_chunk_map)` for each chunk
10. **Reassemble output:** Format-specific reassembly into `anonymized_content` (text) or `anonymized_structured` (object)
11. **Audit log:** `log_document_upload(file_type, file_size, entity_count, entity_types, language, source)`
12. **Return response:** `DocumentUploadResponse` with content, mapping, metadata

### Suggested Implementation Order

1. **Models + Config** -- `DocumentUploadResponse` model, config additions (`max_file_size`, `supported_file_types`, `document_processing_timeout`, `max_zip_uncompressed_size`)
2. **Extractors** -- One function per format in `extractors.py`. Start with TXT/MD (trivial), then CSV/JSON (stdlib), then XLSX/DOCX/RTF/PDF (libraries), then XML/HTML (defusedxml/BS4). Unit test each extractor.
3. **Document Processor** -- `build_unified_placeholder_map()`, `process_document()` orchestration. Unit test the mapping function and pipeline.
4. **Security** -- File validation (size, extension, magic bytes, ZIP bomb), `defusedxml.defuse_stdlib()` in `main.py`. Verify defusedxml coverage with test.
5. **API Router** -- `POST /api/documents/upload` endpoint with error handling. Integration tests with mocked Presidio.
6. **Audit Logging** -- `log_document_upload()` in `audit.py`, integrate into router.
7. **Web UI** -- Upload page template, results partial, HTMX routes, nav link. Connect `deanonymize.js` mapping.
8. **E2E Tests** -- Browser-level file upload tests.

### Areas for Subagent Delegation
- Individual extractor functions (after interface is defined)
- Test fixtures (sample files with known PII)
- E2E tests (after web UI is built)
- Unit tests for extractors (can be written in parallel once extractor signatures are defined)

### Critical Implementation Considerations
- **Call `defusedxml.defuse_stdlib()` BEFORE importing openpyxl, python-docx, or any XML parsing.** This must be at module level in `main.py` or the application entry point.
- **Do NOT call `anonymize_entities()` or `run_anonymization()` per-chunk** -- they produce independent placeholder numbering. Use the three-phase pipeline (analyze-all, unified map, replace per chunk).
- **DO reuse `resolve_overlaps()` and `replace_entities()` from `anonymizer.py`** -- these are pure functions that work correctly on single chunks.
- **`anonymizer.py` requires NO modifications.** All new logic lives in `document_processor.py` and `extractors.py`.
- **lxml/defusedxml gap is CONFIRMED** -- `python-docx` requires lxml. `defusedxml.defuse_stdlib()` does NOT cover lxml. Write an XXE verification test during implementation (see SEC-003 and RISK-005). If lxml resolves external entities, add `defusedxml.lxml` wrappers or configure `resolve_entities=False`.
- **Per-chunk text size limit:** Apply existing `max_text_length` (512KB) to individual chunks. Oversized chunks are skipped and replaced with `[CONTENT TOO LARGE - SKIPPED]` (see EDGE-013).
- **Document upload concurrency semaphore:** Implement `asyncio.Semaphore(settings.max_concurrent_uploads)` at the router level to prevent OOM from concurrent large uploads (see PERF-004, RISK-003, FAIL-009).
- **Filename in metadata:** The `metadata.filename` field was removed from the research's proposed response. Filenames could contain PII. Do NOT include filenames in audit logs or responses.
- **openpyxl read_only mode:** Use `load_workbook(data, read_only=True)` for initial read to reduce memory. Reconstruct output structure from read data.
