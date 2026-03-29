# RESEARCH-003: Document Support (Excel + PDF)

## System Data Flow

### Current Architecture (Features 1 & 2 — Detect + Anonymize)

The existing codebase provides a clear pattern for Feature 3. Key entry points:

**Request handling:**
- `src/redakt/main.py` (lines 39-53) — FastAPI app with lifespan-managed `httpx.AsyncClient`, routers for detect, anonymize, health, pages. Static files mounted at `/static`.
- `src/redakt/routers/anonymize.py` — `run_anonymization()` (line 38) is the shared async function for both API and web routes. Returns `AnonymizationResult` with `anonymized_text`, `mappings`, `entity_types`, `language`.
- `src/redakt/routers/pages.py` — HTMX web routes: form POST -> template partial response. Reuses `run_anonymization()` and `run_detection()`.

**Core anonymization pipeline (`src/redakt/services/anonymizer.py`):**
1. `resolve_overlaps()` — score-desc, longer-span tiebreak
2. `generate_placeholders()` — keyed by `(entity_type, original_text)`, numbered per type
3. `replace_entities()` — reverse position order replacement
4. `anonymize_entities()` — orchestrates 1-3, returns `(anonymized_text, mappings, entity_types)`

**Presidio integration (`src/redakt/services/presidio.py`):**
- `PresidioClient.analyze()` — calls `POST {analyzer_url}/analyze` with text, language, score_threshold, entities, allow_list
- Communication is REST only — no Python library imports from Presidio
- Error handling: ConnectError -> 503, TimeoutException -> 504, HTTPStatusError(5xx) -> 502

**Config (`src/redakt/config.py`):**
- `Settings` with pydantic-settings, `REDAKT_` env prefix
- Key limits: `max_text_length=512_000` (~500KB), `presidio_timeout=30.0`
- `supported_languages: ["en", "de"]`, `allow_list: []`, `default_score_threshold: 0.35`

**Models:**
- `src/redakt/models/anonymize.py` — `AnonymizeRequest(text, language, score_threshold, entities, allow_list)`, `AnonymizeResponse(anonymized_text, mappings, language_detected)`
- `src/redakt/models/detect.py` — `DetectRequest`, `DetectResponse`, `DetectDetailedResponse`
- `src/redakt/models/common.py` — `ErrorResponse`, `HealthResponse`

### Proposed Document Upload Data Flow

```
POST /api/documents/upload (multipart/form-data)
  ↓
[1] Validate file: extension, content-type, size limit
  ↓
[2] Read file bytes into memory (or SpooledTemporaryFile)
  ↓
[3] Extract text content (format-specific extractor)
  │  ├─ .txt/.md → read as UTF-8 text
  │  ├─ .csv → parse rows/cells, extract cell text
  │  ├─ .json → parse structure, extract string values
  │  ├─ .xml/.html → parse DOM, extract text nodes
  │  ├─ .xlsx → openpyxl: iterate sheets → rows → cells
  │  ├─ .docx → python-docx: iterate paragraphs + tables
  │  ├─ .rtf → striprtf: convert to plain text
  │  └─ .pdf → pdfminer.six: extract text per page
  ↓
[4] Detect language once (from longest chunk or first 5KB sample)
  ↓
[5] For each text chunk: call presidio.analyze() (bounded async concurrency)
  │  └─ Presidio Analyzer REST → resolve_overlaps() per chunk → collect entities
  ↓
[6] Build unified placeholder map across ALL chunks (build_unified_placeholder_map())
  ↓
[7] For each chunk: apply replace_entities() with unified per-chunk map
  ↓
[8] Reassemble anonymized content into output format
  │  ├─ Text-based (.txt, .md, .rtf) → return as anonymized text
  │  ├─ Structured (.csv, .json) → return anonymized native-format text
  │  ├─ .xlsx → return anonymized data as JSON structure (v1) / file download (v2)
  │  ├─ .docx → return as extracted anonymized text
  │  └─ .pdf → return as extracted anonymized text (not PDF output for v1)
  ↓
[9] Return: anonymized content + unified mapping (from step 6)
  ↓
Audit logging (action: "document_upload", file_type, entity counts, NO PII)
```

### External Dependencies

- **Presidio Analyzer** (port 5002 via REST) — same as Features 1 & 2
- **Presidio Anonymizer** (port 5001) — NOT used (Redakt does its own replacement)
- **presidio-structured** — Python library, NOT a REST API. Cannot be used from Redakt since Redakt communicates with Presidio via REST only.

### Integration Points

- Does NOT reuse `run_anonymization()` per-chunk (it produces independent placeholder numbering per call — see Decision 4 for details)
- Does NOT call `anonymize_entities()` per-chunk (same reason — fresh counter state per call)
- DOES reuse `PresidioClient.analyze()` for PII detection (called per-chunk via bounded async concurrency)
- DOES reuse `resolve_overlaps()` from `anonymizer.py` for per-chunk overlap resolution
- DOES reuse `replace_entities()` from `anonymizer.py` for per-chunk text replacement
- New function `build_unified_placeholder_map()` replaces `generate_placeholders()` for multi-chunk documents (see Decision 4)
- Language detection called ONCE per document (not per chunk) via `detect_language()`
- New audit log function needed: `log_document_upload()`
- New router: `src/redakt/routers/documents.py`
- New service: `src/redakt/services/extractors.py` (file format extraction)
- New service: `src/redakt/services/document_processor.py` (orchestration)

---

## Presidio Structured Module Analysis

### What `presidio-structured` Does

Located at `presidio/presidio-structured/presidio_structured/`, this module provides:

1. **`AnalysisBuilder`** (`analysis_builder.py`) — Uses `BatchAnalyzerEngine` (Python library, not REST) to analyze tabular/JSON data and determine which columns/keys contain PII entity types.
   - `PandasAnalysisBuilder` — Analyzes DataFrame columns, determines entity type per column
   - `JsonAnalysisBuilder` — Analyzes JSON keys, determines entity type per key

2. **`StructuredEngine`** (`structured_engine.py`) — Takes data + analysis config → anonymizes using Presidio's `OperatorsFactory` (Python library)
   - Uses `PandasDataProcessor` for DataFrames (cell-by-cell replacement)
   - Uses `JsonDataProcessor` for nested JSON (key-path based replacement)

3. **Readers** (`data/data_reader.py`):
   - `CsvReader` — wraps `pandas.read_csv()`
   - `JsonReader` — wraps `json.load()`

### Why `presidio-structured` Cannot Be Used Directly

**Critical finding: `presidio-structured` is a Python library that imports `AnalyzerEngine` and `BatchAnalyzerEngine` directly.** It does NOT use the REST API. Redakt's architecture communicates with Presidio via REST only (CLAUDE.md: "Redakt communicates with Presidio's REST API... does not embed Presidio as a Python library").

**Implications:**
- Cannot use `PandasAnalysisBuilder` or `JsonAnalysisBuilder` (they instantiate `AnalyzerEngine` locally)
- Cannot use `StructuredEngine` (it uses `OperatorsFactory` from `presidio_anonymizer`)
- The data reader classes (`CsvReader`, `JsonReader`) are trivial wrappers — no reason to use them
- The column-level entity detection approach (determining "this column is PERSON") is not needed — Redakt analyzes cell text directly

### What Redakt Should Do Instead

For structured formats (CSV, JSON, XLSX), Redakt should:
1. Extract text from each cell/value
2. Call the existing `run_anonymization()` or `anonymize_entities()` per cell/chunk
3. Replace cell values with anonymized text
4. Return the anonymized structure + merged mapping

This is simpler and more consistent than `presidio-structured`'s approach, which tries to classify entire columns by entity type. Redakt's cell-by-cell approach also produces proper numbered placeholders and a mapping for deanonymization, which `presidio-structured` does not support.

---

## File Format Extraction Libraries

### PDF: pdfminer.six vs PyMuPDF

| Aspect | pdfminer.six | PyMuPDF (fitz) |
|---|---|---|
| License | MIT | AGPL-3.0 (commercial license available) |
| Install size | ~5MB | ~20MB (includes MuPDF C library) |
| Text extraction quality | Good for text-based PDFs | Excellent, handles more edge cases |
| Speed | Slower | 5-10x faster |
| Layout analysis | Detailed (`LTTextContainer`, `LTChar`) | Basic block/line/span |
| OCR support | No | Yes (via Tesseract integration) |
| Page-level extraction | Yes (`extract_pages()`) | Yes (`page.get_text()`) |
| Pure Python | Yes | No (C extension) |
| Presidio example | Uses pdfminer.six (notebook) | Not used |
| Docker compatibility | Easy (pure Python) | Requires system libs |

**Recommendation: pdfminer.six for v1.**
- Pure Python = simple Docker builds, no system dependencies
- Presidio's own PDF example uses it
- AGPL license of PyMuPDF is a concern for enterprise
- Text-based PDFs only for v1 is reasonable scope (scanned PDFs = OCR = major complexity)
- `extract_text()` for simple extraction, `extract_pages()` for page-level control

**Known extraction quality limitations:**
- **Multi-column layouts:** pdfminer.six may interleave text from adjacent columns. Its `LAParams` (layout analysis parameters) can be tuned (`line_margin`, `word_margin`, `boxes_flow`) to improve column detection, but results vary per document.
- **Headers/footers:** Extracted inline with body text. No automatic separation.
- **Tables in PDFs:** Text extraction loses tabular structure. Cells may merge or reorder.
- **Font encoding edge cases:** Some PDFs use custom font encodings (especially older documents). pdfminer.six handles most standard encodings but may produce garbled output for unusual fonts.
- **OCR'd PDFs with invisible text layer:** pdfminer.six extracts the invisible text layer successfully (these are technically text-based PDFs, not image-only).

**Mitigation:** For v1, accept that extraction quality varies by PDF complexity. If extraction produces empty or very short text relative to file size, return a warning: "Limited text could be extracted from this PDF. Results may be incomplete." This helps users understand when a PDF has poor extractability.

**Prototyping recommendation:** During implementation, test extraction on 3-5 representative enterprise PDFs (contract, invoice, annual report, multi-column document, form) to validate quality before finalizing. If quality is unacceptable for common use cases, PyMuPDF's AGPL license should be evaluated against enterprise legal requirements, or a commercial license obtained.

### XLSX: openpyxl

- **openpyxl** is the standard Python library for .xlsx files
- Already a transitive dependency of pandas (commonly installed)
- Cell-by-cell iteration: `ws.iter_rows()` → read `cell.value` → anonymize → write back
- Preserves formatting, formulas reference structure, multiple sheets
- For v1: anonymize string cell values only, skip formulas/numbers
- Write anonymized workbook back to bytes → return as file download

**pandas is not needed** for reading/writing Excel in Redakt's use case. openpyxl gives direct cell access which is what we need for cell-by-cell anonymization with position tracking.

### DOCX: python-docx

- Extracts paragraphs, tables, headers/footers
- `doc.paragraphs` → iterate → `paragraph.text` for extraction
- For anonymization: modify `paragraph.runs` to replace text while preserving formatting
- Challenge: a single word may span multiple runs (different formatting)
- For v1: extract text from paragraphs + table cells, anonymize, write back
- Preserving formatting exactly is complex — acceptable to output with simplified formatting for v1

### RTF: striprtf

- `striprtf` library — pure Python, MIT license, ~10KB
- `rtf_to_text(rtf_content)` → plain text
- One-way extraction only — cannot produce anonymized RTF output
- For v1: extract text, anonymize, return as plain text (not RTF output)

### XML/HTML: Python stdlib + BeautifulSoup

- **xml.etree.ElementTree** (stdlib) — good for well-formed XML
- **BeautifulSoup** (bs4) — handles malformed HTML, more forgiving parser
- Strategy: walk the DOM tree, extract text nodes, anonymize text content, preserve tags
- For v1: extract text content only, return as anonymized text (simpler than in-place DOM modification)
- For XML: `ElementTree.itertext()` extracts all text
- For HTML: `BeautifulSoup.get_text()` or iterate `.strings`

### Text Encoding Detection: charset-normalizer

Enterprise text files (.txt, .csv, .md, .rtf) frequently use non-UTF-8 encodings, especially in German-language environments (Windows-1252 for umlauts, Latin-1, UTF-16 with BOM). The extraction strategy must handle encoding detection.

**Library: `charset-normalizer`** (MIT license, ~300KB, pure Python)
- Successor to `chardet`, faster and more accurate
- Already widely used (it's a dependency of `requests`)

**Decode strategy for text-based formats:**
1. Check for UTF-8 BOM (`\xef\xbb\xbf`) or UTF-16 BOM (`\xff\xfe` / `\xfe\xff`). If present, decode accordingly.
2. Try UTF-8 decode. If successful with no replacement characters, use it.
3. Fall back to `charset_normalizer.from_bytes(data).best()` for detected encoding.
4. If detection confidence is below 0.5 or detection fails, return a clear error: "Could not determine file encoding. Please save the file as UTF-8 and re-upload."

**Applies to:** .txt, .md, .csv, .rtf (binary formats like .xlsx, .docx, .pdf handle encoding internally)

### CSV: Python stdlib

- `csv.reader()` / `csv.DictReader()` — stdlib, no extra dependency
- Cell-by-cell processing: read row → anonymize each cell → write to output
- Preserve structure (column count, headers)
- Output as anonymized CSV file

### JSON: Python stdlib

- `json.load()` / `json.dumps()` — stdlib
- Recursively walk structure, anonymize string values
- Preserve structure (keys, nesting, arrays)
- Output as anonymized JSON file

---

## FastAPI File Upload Handling

### UploadFile

```python
from fastapi import UploadFile, File

@router.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    language: str = Form(default="auto"),
):
    contents = await file.read()
    # file.filename, file.content_type, file.size available
```

### Key Considerations

1. **File size limits:** FastAPI's `UploadFile` uses `SpooledTemporaryFile` — files under 1MB stay in memory, larger files spill to disk temp files
2. **Custom size limit:** Validate `file.size` or `len(contents)` after reading. Configurable via `Settings`.
3. **Content-type validation:** `file.content_type` is client-reported (untrustworthy). Must validate by file extension AND/OR magic bytes.
4. **Cleanup:** `UploadFile` is automatically cleaned up by Starlette when the request completes
5. **Async reading:** `await file.read()` reads entire file. For very large files, could use `file.read(chunk_size)` in a loop.
6. **`python-multipart` is already a dependency** (in pyproject.toml) — required for `UploadFile`

### Proposed Config Additions

```python
class Settings(BaseSettings):
    # ... existing ...
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    supported_file_types: list[str] = [
        ".txt", ".md", ".csv", ".json",
        ".xml", ".html", ".xlsx", ".docx", ".rtf", ".pdf"
    ]
    document_processing_timeout: float = 120.0  # 2 minutes for large documents
```

---

## Critical Design Decisions

### Decision 1: Output Format — Same Format vs Extracted Text

**Options:**
- A) Always return same-format file (anonymized Excel → download Excel)
- B) Always return extracted text
- C) Same-format where practical, extracted text as fallback

**Recommendation: Option C for v1.**
- **Same-format output for:** .txt, .md, .csv, .json, .xlsx (cell values replaced in-place)
- **Extracted text output for:** .pdf, .rtf, .xml, .html, .docx
- Rationale: Formats where we can do cell/field-level replacement should preserve structure. Formats requiring complex layout reconstruction (PDF, RTF) should output as plain text.
- PDF in-place redaction (blackbox annotations) is a different feature — complex, requires pikepdf, and doesn't match the "anonymize with placeholders" pattern.

### Decision 2: Excel — Cell-by-Cell Processing

- Process each cell independently through the anonymization pipeline
- Skip non-string cells (numbers, dates, formulas, None)
- Process all sheets in a workbook
- Mapping keys need cell context: the mapping is global (same as text anonymization), since `generate_placeholders()` already deduplicates by `(entity_type, original_text)`
- Formula cells: skip for v1 (formulas may reference cells that change, breaking them)

**Limitation: Short cell values and column-header awareness.**

Cell-by-cell NLP detection has a known weakness: a cell containing just "Smith" will likely NOT be detected as PERSON by Presidio's NLP models, because there is insufficient context. Column-header-aware detection (e.g., knowing column header is "Name" → treat all cells in that column as PERSON) would improve accuracy for tabular data. However, this approach:
- Requires heuristic mapping from header names to entity types (fragile, language-dependent)
- Is conceptually similar to what `presidio-structured`'s `AnalysisBuilder` does (sample cells to determine column type)
- Adds significant complexity to the v1 implementation

**v1 decision:** Pure cell-by-cell processing. Accept that very short cell values (single names, partial addresses) may have lower detection rates than full-text anonymization. This is a documented limitation.

**v2 consideration:** Column-header hinting — if a column header matches known PII-related terms (Name, Email, SSN, Address, Phone, etc.), boost detection confidence or force entity type for that column's cells. This could be implemented as an optional `column_hints` parameter.

**Additional XLSX edge cases to handle:**
- **Merged cells:** openpyxl represents merged cells with a value only in the top-left cell; other cells in the range are `MergedCell` objects with `None` value. Process only the top-left cell.
- **Hidden sheets:** Process hidden sheets by default (they may contain PII). Allow opt-out via parameter if needed.
- **Data validation dropdowns, named ranges, pivot tables:** Ignored for v1. Only string cell values are processed.
- **openpyxl read_only mode:** Use `load_workbook(data, read_only=True)` for the initial read pass to reduce memory. Write anonymized content to a new workbook for structured output.

### Decision 3: PDF — Text Extraction Only (No OCR)

- v1 supports text-based PDFs only
- Use `pdfminer.six` for extraction
- Extract all text, concatenate with page separators
- Return anonymized text (not a new PDF)
- Scanned/image PDFs: detect and return a clear error message ("This PDF appears to be image-based. Text-based PDFs only are supported in this version.")
- OCR support (Tesseract) deferred to v2

### Decision 4: Mapping Strategy for Multi-Chunk Documents

When processing a document with multiple chunks (cells, pages, paragraphs), the mapping must be consistent across the entire document.

**Why existing functions cannot be called per-chunk directly:**

The current `anonymize_entities()` function (in `src/redakt/services/anonymizer.py`) is a single-text pipeline: it calls `resolve_overlaps()` → sorts by position → calls `generate_placeholders()` (which initializes fresh `seen`, `counters`, `mappings` dicts locally) → calls `replace_entities()` on a single text string. Each call to `generate_placeholders()` starts numbering from 1.

Similarly, `run_anonymization()` (in `src/redakt/routers/anonymize.py`) wraps the full flow (language detection, allow list merging, Presidio REST call, `anonymize_entities()`) for a single text input. Calling it N times for N chunks would produce N independent placeholder numberings (e.g., every chunk would have its own `<PERSON_1>`).

**Neither function can be reused as-is for multi-chunk documents.** The document processor must implement a new pipeline.

**Recommended approach: Analyze-all-then-anonymize with new functions.**

This is a three-phase pipeline implemented via new functions in a `document_processor.py` service:

**Phase 1 — Analyze all chunks** (can be concurrent):
```
For each text chunk:
    results[i] = await presidio.analyze(chunk_text, language, ...)
    enriched[i] = resolve_overlaps(results[i])  # reuse existing function
    enriched[i] = enrich with original_text from chunk
```

**Phase 2 — Build unified placeholder map** (new function):
```python
def build_unified_placeholder_map(
    all_chunk_entities: list[list[dict]],
) -> tuple[dict[str, str], list[dict[int, str]]]:
    """Generate a single consistent placeholder mapping across all chunks.

    Maintains one `seen` dict and one `counters` dict across all chunks,
    so the same (entity_type, original_text) pair always maps to the same
    placeholder regardless of which chunk it appears in.

    Returns:
        global_mappings: {"<PERSON_1>": "John Smith", ...}
        per_chunk_maps: [chunk_0_entity_placeholder_map, chunk_1_..., ...]
    """
    seen: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    global_mappings: dict[str, str] = {}
    per_chunk_maps: list[dict[int, str]] = []

    for chunk_entities in all_chunk_entities:
        chunk_map: dict[int, str] = {}
        for i, entity in enumerate(chunk_entities):
            key = (entity["entity_type"], entity["original_text"])
            if key in seen:
                chunk_map[i] = seen[key]
            else:
                counter = counters.get(entity["entity_type"], 0) + 1
                counters[entity["entity_type"]] = counter
                placeholder = f"<{entity['entity_type']}_{counter}>"
                seen[key] = placeholder
                global_mappings[placeholder] = entity["original_text"]
                chunk_map[i] = placeholder
        per_chunk_maps.append(chunk_map)

    return global_mappings, per_chunk_maps
```

**Phase 3 — Apply replacements per-chunk** (reuses existing `replace_entities()`):
```
For each chunk i:
    anonymized_chunks[i] = replace_entities(
        chunk_text[i], enriched[i], per_chunk_maps[i]
    )
```

**Key design points:**
- `resolve_overlaps()` and `replace_entities()` from `anonymizer.py` are reused without modification.
- `generate_placeholders()` is NOT reused — `build_unified_placeholder_map()` replaces it for multi-chunk documents. The existing `generate_placeholders()` remains untouched for the single-text `/api/anonymize` endpoint.
- `run_anonymization()` is NOT called per-chunk. The document processor calls `presidio.analyze()` directly (same REST call) and handles language detection once at the document level.
- `anonymize_entities()` is NOT called — the document processor implements its own orchestration using the lower-level functions.

This means `src/redakt/services/anonymizer.py` requires **no modifications**. All new logic lives in `src/redakt/services/document_processor.py`.

### Decision 5: File Size Limits, Timeouts, and Presidio Throughput

- **Max file size:** 10MB (configurable). Sufficient for typical business documents.
- **Processing timeout:** 120 seconds. Large Excel files with many text cells could take time.
- **Per-cell timeout:** Use the existing `presidio_timeout` (30s) for each Presidio call.

**Memory amplification analysis:**

A 10MB raw file does NOT mean 10MB memory usage. Parsing amplifies memory consumption:
- **XLSX:** openpyxl loads the workbook into Python objects (Cell, Worksheet, Workbook). A 10MB XLSX with many small text cells can expand to 50-100MB of Python objects due to per-object overhead (each Cell object is ~500 bytes even for a short string). With the analyzer results and placeholder maps also in memory, peak usage could reach 100-150MB per request.
- **PDF:** pdfminer.six builds a layout tree of LTTextContainer/LTChar objects. A dense 10MB text PDF could expand to 30-50MB during parsing.
- **DOCX:** python-docx loads the full XML DOM. Amplification is typically 3-5x.
- **CSV/JSON/TXT:** Minimal amplification (1-2x), since these are loaded as native Python strings/dicts.

**Mitigation strategy:**
- The 10MB file size limit constrains the worst case. At 150MB peak per request, a container with 1GB memory can handle ~5-6 concurrent document uploads safely.
- Document the recommended minimum container memory (1GB) and concurrent upload guidance.
- For v1, this is acceptable for enterprise internal use with limited concurrency. If needed, v2 can add a request semaphore to limit concurrent document uploads (e.g., max 3 simultaneous).
- openpyxl's `read_only=True` mode can reduce memory for read operations (iterates rows without loading full workbook). Worth using since we read cells then write to a new structure.

**Presidio throughput analysis for high-volume cell processing:**

A large Excel file could contain thousands of text cells. Each cell requires a separate `POST /analyze` REST call to Presidio.

Estimated throughput scenarios:
- **Short text cells (< 100 chars):** Presidio Analyzer typically responds in 10-30ms per request (NLP model inference is fast for short text). At 20ms avg, 2000 cells = 40 seconds sequential.
- **Medium text cells (100-500 chars):** 30-80ms per request. 2000 cells = 60-160 seconds sequential. This exceeds the 120s timeout.
- **Long text (paragraphs, PDF pages):** 100-300ms per request. Fewer chunks needed, but each takes longer.

**Batching and concurrency strategies (required for v1):**

Option A: **Cell concatenation with separator** — Concatenate multiple short cell values into a single Presidio call, separated by a delimiter (e.g., `\n---CELL_BOUNDARY---\n`). After analysis, split results back to individual cells by adjusting offsets. This reduces HTTP overhead dramatically (e.g., batch 50 cells into one call → 2000 cells = 40 calls instead of 2000). Risk: PII spanning a boundary could be missed, but cell boundaries are natural PII boundaries anyway.

Option B: **Bounded async concurrency** — Use `asyncio.Semaphore` to send multiple concurrent Presidio calls (e.g., 10 at a time). Since Presidio Analyzer is stateless, concurrent requests are safe. At concurrency=10 and 20ms per request, 2000 cells complete in ~4 seconds. This is the simplest approach and uses the existing `httpx.AsyncClient` which supports concurrent requests.

Option C: **Hybrid** — Concatenate cells into batches of ~5KB each, then send batches concurrently.

**Recommendation: Option B (bounded async concurrency) for v1.**
- Simplest to implement: wrap `presidio.analyze()` calls in `asyncio.gather()` with a `Semaphore(10)`.
- No offset manipulation needed (unlike concatenation).
- Keeps individual cell boundaries clean for accurate detection.
- Estimated performance: 2000 cells at concurrency=10 = ~4-8 seconds total, well within the 120s timeout.
- If Presidio's single-worker Flask server becomes a bottleneck, the concurrency limit can be tuned down (or Presidio can be scaled to multiple workers via gunicorn/uvicorn in docker-compose).

### Decision 6: DOCX Output — Extracted Text for v1

- `python-docx` can read and write DOCX files
- Challenge: preserving exact formatting when replacing text in runs is fragile
- A single word like "John Smith" might span multiple runs if partially bold/italic
- For v1: extract text from paragraphs and table cells, anonymize, return as plain text
- v2 could add same-format DOCX output with formatting preservation

### Decision 7: API Response Format

For file-format output (xlsx, csv, json):
```
Response: StreamingResponse with file download
Headers: Content-Disposition: attachment; filename="anonymized_{original_name}"
Body: File bytes
+ X-Redakt-Mappings header (JSON) or multipart response
```

For text output (txt, md, pdf, rtf, docx, xml, html):
```
Response: JSON
{
  "anonymized_text": "...",
  "mappings": { "<PERSON_1>": "John Smith", ... },
  "language_detected": "en",
  "source_format": "pdf",
  "pages_processed": 3
}
```

**Problem with file downloads + mappings:** The client needs both the anonymized file AND the mapping. Options:
- A) Multipart response (file + JSON mapping)
- B) Two-step: upload returns mapping + download URL, then client downloads file
- C) Return JSON with base64-encoded file + mapping
- D) Return file with mapping in response header (X-Redakt-Mappings)
- E) Return JSON for all formats (text-based output only)

**Recommendation: Option E with native-format exceptions for v1.**

The base approach is JSON-only responses (simplifies the API, consistent with Feature 2). However, for formats where the native text representation is trivial to return and dramatically more useful, return native format as a string within the JSON response:

- **CSV:** Return anonymized CSV as a CSV-formatted text string (not JSON-wrapped rows). The user can paste this into a file or spreadsheet. Returning `[["Name","Email"],["<PERSON_1>","<EMAIL_ADDRESS_1>"]]` is less useful than returning `Name,Email\n<PERSON_1>,<EMAIL_ADDRESS_1>`.
- **JSON:** Return the anonymized JSON object directly in the response (already native format within JSON).
- **XLSX:** Return as structured JSON (`{sheet_name: [[cell, cell, ...], ...], ...}`). Users cannot directly re-import this to Excel without tooling, which is a known v1 UX limitation. Same-format XLSX download is deferred to v2.
- **Text formats (TXT, MD, RTF, PDF, DOCX, XML, HTML):** Return as anonymized text string.

**UX tradeoff acknowledgment:** For the XLSX use case specifically, JSON output is materially less useful than returning an anonymized .xlsx file. Users who upload spreadsheets typically want spreadsheet output. This is accepted as a v1 limitation — implementing `StreamingResponse` with file download + mapping delivery (multipart or header-based) adds significant API complexity. If user feedback indicates this is a blocker, it should be prioritized for v2.

**Revised v1 response:**
```json
{
  "anonymized_content": "...",  // text string for text formats, CSV text for CSV
  "anonymized_structured": null,  // or JSON object for JSON input, or sheet structure for XLSX
  "mappings": { "<PERSON_1>": "John Smith", ... },
  "language_detected": "en",
  "source_format": "pdf",
  "metadata": {
    "pages_processed": 3,
    "cells_processed": 150,
    "filename": "report.pdf"
  }
}
```

Exactly one of `anonymized_content` (string) or `anonymized_structured` (object) will be populated, never both.

---

## Stakeholder Mental Models

### Product Team Perspective
- "Users upload sensitive documents, get back clean versions they can share or feed to AI"
- Key metric: format coverage and extraction quality
- Concern: "Does it handle our actual documents?" — real-world PDFs, complex Excel workbooks

### Engineering Team Perspective
- File parsing is the hard part — each format is a separate extraction problem
- Must reuse existing anonymization pipeline, not build parallel paths
- Memory and timeout management for large files
- Security: file uploads are an attack vector

### User Perspective
- "I have a spreadsheet with employee data — I want to anonymize it before using it in ChatGPT"
- "I have a PDF contract — I need to redact names and emails"
- Expects: upload file, get result quickly, mapping works for deanonymization same as text
- May not understand why scanned PDFs don't work

### Support Team Perspective
- "Why doesn't my PDF work?" — scanned/image PDFs will be a common complaint
- "The Excel formatting is different" — users expect pixel-perfect reproduction
- Need clear error messages for unsupported scenarios

---

## Production Edge Cases

### File Format Edge Cases
1. **Empty files** — 0 bytes. Return immediately with empty content.
2. **Password-protected files** — Excel/PDF with passwords. Detect and return error.
3. **Corrupted files** — Invalid format despite correct extension. Handle parser exceptions gracefully.
4. **Very large files** — Near the 10MB limit with dense text. May timeout on Presidio calls.
5. **Files with no text** — Image-only PDFs, empty Excel sheets. Return content unchanged.
6. **Mixed content Excel** — Cells with formulas, numbers, dates, errors, None. Only process string cells.
7. **Multi-sheet Excel** — Process all sheets. Maintain consistent mapping across sheets.
8. **Unicode/encoding** — Files with non-UTF-8 encoding. Detect encoding or fail gracefully.
9. **CSV delimiter detection** — Comma vs semicolon vs tab. Use `csv.Sniffer` or accept delimiter parameter.
10. **Nested JSON** — Deeply nested structures. Recursively extract string values.

### PII Detection Edge Cases
11. **PII spanning cell boundaries** — e.g., first name in column A, last name in column B. Cannot detect as a single entity — this is a known limitation.
12. **Very short cell text** — Single words may not trigger NLP detection. Lower confidence scores.
13. **Mixed-language documents** — Language should be detected ONCE for the entire document, not per-chunk. For short cell values (a few words), per-chunk language detection is unreliable (a German name in an English spreadsheet could trigger German detection). Strategy: detect language from the longest text chunk or a concatenated sample of the first N chunks (e.g., first 5KB of text). Apply the detected language uniformly to all Presidio calls for that document. The user can also override with an explicit `language` parameter on upload.
14. **Structured data that looks like PII** — Product codes that look like IDs, company names that look like person names. Allow list helps but isn't complete.

### Security Edge Cases
15. **Zip bombs** — .xlsx is a ZIP archive. Limit decompressed size.
16. **XML entity expansion** — "Billion laughs" attack in XML/HTML/DOCX. Use defusedxml or limit entity expansion.
17. **Path traversal** — Filenames with `../` or absolute paths. Sanitize filename.
18. **Content-type spoofing** — .pdf extension but actually .exe. Validate magic bytes.

---

## Files That Matter

### Core Logic (to create)
- `src/redakt/services/extractors.py` — File format extraction (one function per format)
- `src/redakt/services/document_processor.py` — Orchestrates extraction → anonymization → reassembly
- `src/redakt/routers/documents.py` — `POST /api/documents/upload` endpoint + web route
- `src/redakt/models/documents.py` — Request/response models for document upload

### Core Logic (to modify)
- `src/redakt/services/anonymizer.py` — No modifications needed. `resolve_overlaps()` and `replace_entities()` are reused as-is. `generate_placeholders()` is NOT used for documents; `build_unified_placeholder_map()` in `document_processor.py` replaces it for multi-chunk scenarios.
- `src/redakt/main.py` — Register new documents router
- `src/redakt/config.py` — Add file size limits, supported types, timeout settings
- `src/redakt/services/audit.py` — Add `log_document_upload()` function

### Templates (to create)
- `src/redakt/templates/documents.html` — File upload page
- `src/redakt/templates/partials/document_results.html` — Upload results partial

### Tests (to create)
- `tests/test_extractors.py` — Unit tests for each format extractor
- `tests/test_document_processor.py` — Integration tests for the processing pipeline
- `tests/test_documents_api.py` — API endpoint integration tests
- `tests/e2e/test_documents_e2e.py` — Browser-level file upload tests

### Test Fixtures (to create)
- `tests/fixtures/` — Sample files for each format (small, with known PII)

### Existing Tests (no coverage gaps for this feature — all new code)
- `tests/test_anonymizer_service.py` — 25 unit tests for core anonymizer (stable, not modified)
- `tests/test_anonymize_api.py` — 15 integration tests for `/api/anonymize` (stable)

### Configuration
- `pyproject.toml` — Add new dependencies (openpyxl, python-docx, pdfminer.six, striprtf, beautifulsoup4, defusedxml, charset-normalizer)
- `Dockerfile` — May need system packages for PDF libraries (pdfminer.six is pure Python — no changes needed)
- `docker-compose.yml` — No changes needed (volume mount already includes all of `src/`)

---

## Security Considerations

### File Upload Attack Surface

1. **File size validation** — Enforce `max_file_size` (10MB) before processing. Check `file.size` or read in bounded manner.
2. **Extension validation** — Whitelist of allowed extensions. Do NOT rely on `file.content_type` (client-controlled).
3. **Magic byte validation** — For critical formats (PDF: `%PDF-`, XLSX: PK zip header, DOCX: PK zip header), verify magic bytes match extension.
4. **Filename sanitization** — Strip path components, limit length, remove special characters. Use only for display; generate internal names.
5. **Temp file cleanup** — Starlette's `UploadFile` handles this automatically. No manual temp files needed since we process in memory.

### XML-Specific Attacks

6. **XML External Entity (XXE)** — Use `defusedxml` or configure `xml.etree.ElementTree` to disable external entities.
7. **Billion Laughs (entity expansion)** — `defusedxml` prevents this. DOCX files also contain XML internally.
8. **For DOCX/XLSX parsing:** openpyxl and python-docx handle ZIP extraction internally. Verify they don't expand malicious ZIP entries.

### ZIP-Based Format Protection (XLSX, DOCX)

9. **ZIP bomb detection for XLSX/DOCX** — Both .xlsx and .docx are ZIP archives. A 10MB compressed file could decompress to gigabytes. Mitigation strategy:
   - Before passing to openpyxl/python-docx, open with `zipfile.ZipFile` and inspect the ZIP directory: sum `info.file_size` for all entries. If total uncompressed size exceeds a limit (e.g., 100MB = 10x the max upload size), reject with error.
   - This check is fast (reads ZIP central directory only, does not decompress) and catches naive zip bombs.
   - Sophisticated zip bombs (recursive archives) are mitigated by the 10MB upload limit — there is a physical limit to compression ratio for realistic data.

### defusedxml Coverage for openpyxl and python-docx

10. **openpyxl XML parsing:** openpyxl uses `xml.etree.ElementTree` internally for parsing XLSX XML content. `defusedxml.defuse_stdlib()` monkey-patches `xml.etree.ElementTree.parse` and `xml.etree.ElementTree.iterparse` to block external entities and entity expansion. This DOES protect openpyxl when called before any openpyxl imports.
   - **Action:** Call `defusedxml.defuse_stdlib()` at application startup (in `main.py` lifespan or module-level) BEFORE importing openpyxl/python-docx. This globally patches the stdlib XML parsers.
   - **python-docx:** Also uses `xml.etree.ElementTree` (via `lxml` if available, falls back to stdlib). If `lxml` is installed, `defusedxml.defuse_stdlib()` does NOT cover it. Check whether `lxml` is a transitive dependency. If so, use `defusedxml.lxml` equivalents or ensure lxml is not used.
   - **Verification needed during implementation:** Write a test that creates a malicious XLSX with an XML entity expansion payload and confirms it is rejected after `defuse_stdlib()` is called. This validates the protection end-to-end.

### Memory Safety

11. **Memory amplification** — A 10MB file does NOT mean 10MB memory usage. See Decision 5 for detailed memory amplification analysis. Peak memory per request can reach 100-150MB for large XLSX files. With concurrent uploads, container memory is the constraint.
12. **Concurrent uploads** — Recommend limiting concurrent document uploads via semaphore or worker count. For v1, document the recommended minimum container memory (1GB) and suggest max 3-5 concurrent document uploads.

### CSP Considerations for v2 File Downloads

13. **CSP `blob:` directive** — The current `SecurityHeadersMiddleware` in `main.py` sets `default-src 'self'` and `connect-src 'self'`. For v1 (JSON-only responses), this is fine. But v2 plans to add same-format file downloads (`Content-Disposition: attachment`). If the browser creates blob URLs for downloads (e.g., `URL.createObjectURL(blob)` in JavaScript), the CSP `default-src 'self'` would block blob URLs. When implementing v2 file downloads, CSP will need `blob:` added to the relevant directive (e.g., `default-src 'self' blob:` or `connect-src 'self' blob:`). This is a v2 implementation note, not a v1 concern.

### Additional File Upload Security

14. **Polyglot files** — Files that are valid in multiple formats (e.g., a file that is both a valid PDF and a valid HTML). Mitigated by: validating magic bytes match the declared extension, AND processing only through the extractor for the declared format. Even if a file is a polyglot, it will only be parsed as the format matching its extension.
15. **Embedded macros in DOCX/XLSX** — Macro-enabled files (.xlsm, .docm) should be rejected by extension validation (not in the supported list). Standard .xlsx/.docx files cannot contain macros. If a .xlsm is renamed to .xlsx, openpyxl will simply ignore the macro storage.
16. **Pathological single-cell content** — A CSV file within the 10MB limit could have one cell containing 5MB of text. This single cell would create one enormous Presidio call. Mitigation: apply the existing `max_text_length` (512KB) per-chunk. If a single cell/chunk exceeds this, either split it or return an error. The 512KB limit from `config.py` already exists for the text endpoint and should be reused.

### Data Privacy

17. **No PII at rest** — File contents are processed in memory and never written to disk (except Starlette's SpooledTemporaryFile for uploads > 1MB, which is cleaned up automatically).
18. **Audit logging** — Log file type, size, entity counts. NEVER log filenames (could contain PII), file contents, or extracted text.
19. **Response does not include original text** — Only anonymized content + mapping (same as Feature 2).

---

## Testing Strategy

### Unit Tests (`tests/test_extractors.py`)

Test each extractor function in isolation with small fixture files:

1. **TXT extractor** — UTF-8 text, empty file, non-UTF-8 encoding
2. **MD extractor** — Markdown with formatting preserved
3. **CSV extractor** — Standard CSV, custom delimiter, empty cells, unicode
4. **JSON extractor** — Flat object, nested object, array of objects, non-string values
5. **XML extractor** — Well-formed XML, text nodes extracted, tags preserved info
6. **HTML extractor** — HTML with scripts/styles stripped, text content only
7. **XLSX extractor** — Single sheet, multi-sheet, mixed cell types, empty sheets
8. **DOCX extractor** — Paragraphs, tables, empty document
9. **RTF extractor** — Basic RTF, empty
10. **PDF extractor** — Text-based PDF, empty PDF, multi-page

### Unit Tests (`tests/test_document_processor.py`)

11. **Single-chunk processing** — Text file with PII → anonymized text + mapping
12. **Multi-chunk processing** — Excel with multiple cells → consistent mapping across cells
13. **Cross-chunk deduplication** — Same name in multiple cells → same placeholder
14. **Empty document** — No text extracted → empty result
15. **Unsupported format** — Return clear error
16. **File too large** — Return 413 error

### Integration Tests (`tests/test_documents_api.py`)

17. **Upload text file** — Full pipeline with mocked Presidio
18. **Upload CSV** — Structured output with cell-level anonymization
19. **Upload PDF** — Text extraction + anonymization
20. **Upload XLSX** — Multi-sheet processing
21. **Invalid file type** — 400 error
22. **File too large** — 413 error
23. **Empty file** — Graceful handling
24. **Presidio unavailable** — 503 error

### E2E Tests (`tests/e2e/test_documents_e2e.py`)

25. **File upload flow** — Upload a text file with known PII, verify anonymized output in browser
26. **Mapping returned** — Verify mapping is available for deanonymization after upload
27. **Error display** — Upload unsupported file type, verify error message shown

### Test Fixtures

Small sample files with known, predictable PII for deterministic testing:
- `tests/fixtures/sample.txt` — "John Smith lives at john@example.com"
- `tests/fixtures/sample.csv` — 3 rows with names and emails
- `tests/fixtures/sample.xlsx` — 2 sheets, names in cells
- `tests/fixtures/sample.pdf` — 1 page, text with names
- `tests/fixtures/sample.json` — Nested object with PII values
- `tests/fixtures/sample.docx` — 2 paragraphs with names

---

## New Dependencies Analysis

| Package | Version | Size | License | Purpose |
|---|---|---|---|---|
| `pdfminer.six` | >=20221105 | ~5MB | MIT | PDF text extraction |
| `openpyxl` | >=3.1 | ~8MB | MIT | Excel read/write |
| `python-docx` | >=1.1 | ~3MB | MIT | Word document read |
| `striprtf` | >=0.0.26 | ~10KB | BSD-3 | RTF to text conversion |
| `beautifulsoup4` | >=4.12 | ~500KB | MIT | HTML/XML text extraction |
| `defusedxml` | >=0.7 | ~50KB | PSF | Secure XML parsing |
| `charset-normalizer` | >=3.0 | ~300KB | MIT | Text encoding detection |

All MIT/BSD/PSF licensed — no AGPL or copyleft concerns. Total additional install size: ~17MB.

**Docker image impact:** These 7 packages add ~17MB to the installed size. All are pure Python (no C extensions, no system packages needed). Build time impact is negligible. CVE surface area: these are mature, widely-used libraries with active maintenance. `charset-normalizer` may already be present as a transitive dependency of `httpx`/`requests`.

---

## Implementation Scope for V1

### In Scope (V1)
- File upload endpoint (`POST /api/documents/upload`)
- Web UI upload page with drag-and-drop
- Text extraction for all 10 formats
- Cell-by-cell anonymization for structured formats (CSV, JSON, XLSX)
- Paragraph-by-paragraph for documents (DOCX, PDF, TXT, MD, RTF)
- Text-node extraction for XML/HTML
- Unified mapping across entire document
- All output as JSON response (anonymized text/structure + mappings)
- Audit logging for document uploads
- File size limit (10MB, configurable)

### Out of Scope (V2+)
- Same-format file download output (anonymized XLSX → download as XLSX)
- Scanned PDF support (OCR via Tesseract)
- PDF in-place redaction (blackbox annotations)
- DOCX formatting preservation
- Formula handling in Excel
- Streaming/chunked upload for large files
- Image-based PII detection (screenshots, scanned documents)
- Batch file upload (multiple files at once)
- Progress indicator for long-running document processing

### Implementation Order (Suggested)

1. **Models + Config** — `DocumentUploadResponse`, file size/type settings
2. **Extractors** — One function per format, unit tested individually
3. **Document Processor** — Orchestration service (extract → anonymize → merge mappings)
4. **API Router** — `POST /api/documents/upload` endpoint
5. **Web UI** — Upload page, results partial
6. **Audit Logging** — `log_document_upload()` integration
7. **Security** — File validation, defusedxml, size checks
8. **E2E Tests** — Browser file upload testing

---

## Open Questions Resolved

| Question | Resolution |
|---|---|
| Cell-by-cell or sheet-by-sheet for Excel? | Cell-by-cell. Each cell processed independently through anonymization. |
| Preserve formulas in Excel? | No. Skip formula cells. Anonymize string values only. |
| Text-based PDF only, or OCR? | Text-based only for v1. Clear error for image-based PDFs. |
| Same-format output or extracted text? | All output as JSON/text for v1. Same-format file download deferred to v2. |
| Multi-sheet Excel? | Process all sheets. Maintain consistent mapping across sheets. |
| DOCX formatting? | Extract as plain text for v1. Formatting preservation deferred to v2. |
| XML/HTML: preserve tags? | Extract text content only. Return as plain anonymized text. |
| File size limits? | 10MB default, configurable via `REDAKT_MAX_FILE_SIZE`. |
| Processing timeout? | 120s default for documents, configurable. |
| How to return mapping with file? | All output is JSON — no file download in v1. Mapping always in response body. CSV returns native CSV text within JSON. |
| Use presidio-structured? | No. It's a Python library (not REST). Redakt's cell-by-cell approach via REST is simpler and supports numbered placeholders. |
| How to handle text encoding? | charset-normalizer library. Try UTF-8 first, fall back to detected encoding, error if detection fails. |
| Language detection: per-chunk or per-document? | Per-document. Detect once from longest chunk or first 5KB sample. Apply uniformly. User can override. |
| Presidio throughput for many cells? | Bounded async concurrency (Semaphore(10) with asyncio.gather). 2000 cells in ~4-8s. |
| ZIP bomb protection for XLSX/DOCX? | Pre-check ZIP manifest total uncompressed size. Reject if >100MB. |
| defusedxml coverage for openpyxl/python-docx? | Call defusedxml.defuse_stdlib() at startup before imports. Verify with test during implementation. |

---

## Additional Perspectives

### InfoSec / Penetration Testing

File upload is the largest attack surface expansion in Redakt. Beyond the vectors listed in the Security Considerations section:

- **Polyglot files:** Addressed — validate magic bytes match declared extension, process only through the declared format's extractor.
- **Macro-enabled formats:** .xlsm and .docm are NOT in the supported extension list. Only .xlsx and .docx are accepted.
- **Pathological inputs:** A CSV with one cell containing 500KB of text is within the 10MB limit but creates one enormous Presidio call. Mitigated by applying the existing `max_text_length` (512KB) per-chunk, consistent with the text endpoint's limit.
- **Resource exhaustion via concurrent uploads:** Documented in Decision 5 — recommend container memory sizing and concurrent upload limits.

### Enterprise IT / Deployment

- **Docker image size:** 7 new dependencies add ~17MB installed. All pure Python, no system packages. Minimal impact on build time and image size.
- **CVE surface area:** All dependencies are mature, actively maintained libraries (openpyxl, pdfminer.six, python-docx, beautifulsoup4, defusedxml, charset-normalizer, striprtf). Regular dependency auditing should be part of CI/CD pipeline.
- **No new ports or services:** Document processing runs within the existing Redakt API container. No additional infrastructure needed.

### Accessibility / UX Design

- **File upload UI:** Must be keyboard-accessible (not just drag-and-drop). Include a standard file input (`<input type="file">`) as the primary mechanism, with drag-and-drop as an enhancement.
- **Progress indication:** For v1, document processing is synchronous (the request blocks until complete). For files that take several seconds, the UI should show a loading/spinner state. HTMX's `hx-indicator` provides this.
- **Error recovery:** If processing fails (e.g., unsupported encoding, corrupted file), the user should see a clear error message and be able to upload again without refreshing the page. The HTMX partial swap pattern supports this naturally.
- **Accepted formats display:** The upload form should clearly list supported file types before the user selects a file.

### Data Engineering

- **Real enterprise XLSX files** contain merged cells, hidden sheets, data validation, named ranges, and pivot tables. For v1, only string cell values are processed. Merged cells are handled (process top-left cell only). Hidden sheets are processed. All other features (data validation, named ranges, pivot tables) are ignored — they contain no user-visible text that would be PII.
- **CSV encoding and delimiter detection:** Enterprise CSV exports often use semicolons (common in German/European locales) or tabs. Use `csv.Sniffer().sniff()` to auto-detect delimiter, with a fallback parameter for manual override.

---

## Documentation Needs

### User-Facing
- Supported file formats list with known limitations
- Maximum file size
- Note about scanned PDFs not being supported
- How mapping works for documents (same as text anonymization)

### Developer-Facing
- API contract for `POST /api/documents/upload`
- Extractor architecture (how to add new format support)
- How mapping consistency works across multi-chunk documents

### Configuration
- `REDAKT_MAX_FILE_SIZE` environment variable
- `REDAKT_SUPPORTED_FILE_TYPES` if customizable
- `REDAKT_DOCUMENT_PROCESSING_TIMEOUT` for timeout
