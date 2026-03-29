## Research Critical Review: Document Support

### Severity: HIGH

---

### Critical Gaps Found

1. **`generate_placeholders()` cannot accept shared state across chunks** (HIGH)
   - The research identifies (Decision 4) that multi-chunk documents need consistent mapping and recommends the "analyze-first" approach. However, it glosses over a fundamental problem: `generate_placeholders()` uses a local `counters` dict initialized to empty on every call. The "analyze-first" approach still requires generating a unified placeholder set across all chunks, which means either (a) concatenating all text into one string and calling `anonymize_entities()` once, or (b) refactoring `generate_placeholders()` to accept external state.
   - Evidence: The research says "This requires refactoring `generate_placeholders()` to accept an existing mapping as input, or using a stateful wrapper" (line 284) but then recommends the "alternative" (analyze-first) as if it avoids this problem. It does not. Even with analyze-first, you still call `generate_placeholders()` once with all entities from all chunks, but those entities reference positions within their respective chunks, not a single unified text. The `replace_entities()` function operates on a single `text` string, so you cannot pass it entities from multiple chunks at once.
   - Risk: Implementation will hit a design wall at the core of the pipeline. The research underestimates the refactoring needed.
   - Recommendation: Explicitly design the multi-chunk pipeline. The most practical approach is likely: analyze each chunk separately, collect all unique `(entity_type, original_text)` pairs across chunks, build a unified placeholder map, then apply replacements per-chunk using that shared map. This requires a new function (not just reuse of existing ones).

2. **`run_anonymization()` is not directly reusable for document processing** (HIGH)
   - The research repeatedly says document processing will "reuse `run_anonymization()`" (lines 54, 79). But `run_anonymization()` does language detection, allow list merging, Presidio REST calls, AND anonymization in one function. For documents, you need to call Presidio per-chunk but share mapping state across chunks. You cannot just call `run_anonymization()` N times because each call generates independent placeholder numbering.
   - Evidence: `run_anonymization()` in `anonymize.py` (line 38-96) calls `anonymize_entities()` which internally calls `generate_placeholders()` with fresh state every time.
   - Risk: Implementers who follow the research's guidance will either produce inconsistent placeholder numbering across chunks or have to refactor significantly without prior design.
   - Recommendation: The research should specify that `run_anonymization()` will NOT be called per-chunk. Instead, the document processor needs to call `presidio.analyze()` per-chunk directly, then use a new unified anonymization function that operates across all chunks.

3. **No analysis of Presidio rate limiting or concurrent call behavior** (MEDIUM)
   - A 10MB Excel file could have thousands of text cells. Each cell requires a separate `POST /analyze` call to Presidio. The research mentions a 120-second timeout but never analyzes how many Presidio calls this implies or whether Presidio can handle rapid sequential/concurrent requests at that volume.
   - Evidence: No benchmarks, no mention of batching multiple cells into single Presidio calls, no analysis of Presidio's throughput characteristics.
   - Risk: A moderately large spreadsheet (e.g., 2000 text cells) would make 2000 sequential HTTP requests to Presidio. At even 50ms per request, that is 100 seconds -- dangerously close to the 120s timeout. With network overhead and NLP processing, it would likely exceed it.
   - Recommendation: Investigate (a) batching multiple cells into a single Presidio call by concatenating cell text with separators, (b) concurrent Presidio calls (e.g., asyncio.gather with bounded concurrency), or (c) realistic benchmarks of Presidio throughput per request.

4. **No encoding detection strategy for text files** (MEDIUM)
   - Edge case 8 mentions "Unicode/encoding -- Detect encoding or fail gracefully" but provides no strategy. Text files (.txt, .csv, .md, .rtf) could be UTF-8, Latin-1, Windows-1252, UTF-16, or others. The research just says "read as UTF-8 text" for .txt/.md (line 45).
   - Evidence: No mention of `chardet`, `charset-normalizer`, or any encoding detection library.
   - Risk: Enterprise documents frequently use Windows-1252 or Latin-1 encoding, especially in German-language environments (umlauts). Files will fail to parse or produce garbled text silently.
   - Recommendation: Add `charset-normalizer` (lightweight, MIT) to the dependency list and specify a decode strategy: try UTF-8, fall back to detected encoding, fail with a clear error message.

5. **XLSX zip bomb protection is mentioned but not addressed** (MEDIUM)
   - Edge case 15 says "Limit decompressed size" for zip-based formats. The research lists `defusedxml` for XML attacks but provides no concrete mitigation for zip bombs in XLSX/DOCX files.
   - Evidence: openpyxl and python-docx both extract ZIP archives internally. No mention of configuring extraction limits or using `zipfile` with size checks.
   - Risk: A malicious XLSX file could decompress to gigabytes, causing OOM. The 10MB upload limit only constrains the compressed size.
   - Recommendation: Research whether openpyxl/python-docx expose ZIP extraction limits. If not, consider pre-checking the ZIP manifest (file sizes listed in the ZIP directory) before passing to the library.

6. **CSP header blocks file download if v2 adds file responses** (LOW)
   - The existing `SecurityHeadersMiddleware` sets `default-src 'self'` and `connect-src 'self'`. For v1 (JSON-only responses), this is fine. But the research explicitly positions file download output as a v2 feature. If the API returns binary file responses with `Content-Disposition: attachment`, the CSP may interfere with blob URL downloads in the browser depending on implementation.
   - Evidence: `main.py` line 20-26 sets restrictive CSP. Research Decision 7 discusses file download for v2.
   - Risk: Low for v1, but worth noting for v2 planning.
   - Recommendation: Note this as a v2 consideration.

7. **No analysis of `defusedxml` compatibility with openpyxl/python-docx** (MEDIUM)
   - The research recommends `defusedxml` for XML parsing (line 469) and notes that DOCX/XLSX contain XML internally (line 471). However, openpyxl and python-docx use their own internal XML parsing. Simply adding `defusedxml` to the project does not automatically protect these libraries.
   - Evidence: `defusedxml` works by monkey-patching stdlib XML parsers or providing drop-in replacements. Whether openpyxl/python-docx respect these patches depends on their implementation.
   - Risk: False sense of security. The research implies DOCX/XLSX are protected by defusedxml, but they may not be.
   - Recommendation: Verify whether openpyxl and python-docx are vulnerable to XXE or entity expansion. If so, check if `defusedxml.defuse_stdlib()` patches their internal parsers effectively.

---

### Questionable Assumptions

1. **"In-memory processing is fine for 10MB files"**
   - The research assumes 10MB max file size means ~10MB memory per request (line 475). This ignores amplification: parsing an XLSX file produces Python objects (openpyxl Workbook, Cell objects, strings) that consume far more memory than the raw file bytes. A 10MB XLSX with many small text cells could expand to 50-100MB of Python objects. Multiply by concurrent requests and memory becomes a real concern.
   - Alternative possibility: Memory usage could be 5-10x the file size during processing. With multiple concurrent uploads, this could exhaust container memory.

2. **"Cell-by-cell processing is simpler than presidio-structured's column approach"**
   - The research dismisses column-level entity detection (line 124) in favor of cell-by-cell. But for structured data like a CSV with a "Name" column, column-level detection could be far more accurate for short cell values. A cell containing just "Smith" will not be detected as a PERSON by NLP, but knowing the column header is "Name" would enable detection.
   - Alternative possibility: Column-header-aware detection (analyze header + sample cells to determine column type, then anonymize all cells in that column) could produce significantly better results for tabular data.

3. **"All output as JSON/text for v1" is acceptable UX**
   - Decision 7 chooses JSON-only output for all formats, including XLSX. This means a user uploads a spreadsheet and gets back a JSON blob with `sheet -> rows -> cells`. The user cannot re-import this into Excel without writing code. The research frames this as "simplifies the API" but does not assess whether users would actually find this useful.
   - Alternative possibility: Users who upload Excel files expect Excel output. Returning JSON may make the feature essentially useless for the primary use case (anonymizing a spreadsheet to share with colleagues). For CSV at minimum, returning CSV text (not JSON) should be trivial.

4. **"pdfminer.six is sufficient for text-based PDFs"**
   - The research recommends pdfminer.six and acknowledges it is "slower" than PyMuPDF. But it does not test or verify extraction quality on real-world PDFs. PDFs with multi-column layouts, headers/footers, tables, or unusual font encodings can produce garbled or out-of-order text with pdfminer.six.
   - Alternative possibility: Extraction quality may be poor enough on common enterprise PDFs (annual reports, contracts with columns, scanned-then-OCR'd documents) that users see it as broken.

5. **"Language auto-detect per chunk" works for documents**
   - The research proposes auto-detecting language per chunk (edge case 13, line 408). But for short cell values in Excel (a few words), language detection is unreliable. A German name in an English spreadsheet could trigger German language detection for that cell, changing which recognizers run.
   - Alternative possibility: Language should be detected once for the document (from the longest text chunk or a sample) and applied uniformly, with per-chunk detection as a fallback only if explicitly requested.

---

### Missing Perspectives

- **InfoSec / Penetration Testing**: File uploads are the single largest attack surface expansion in the project. The research lists attack vectors but lacks depth. No mention of: polyglot files (files that are valid in multiple formats), embedded macros in DOCX/XLSX, or resource exhaustion via pathological inputs (e.g., a CSV with one cell containing 500KB of text that is technically under the file size limit but creates a single enormous Presidio call).
- **Enterprise IT / Deployment**: No analysis of how the new dependencies (6 additional packages) affect Docker image size, build time, or CVE surface area. Enterprise deployments often have dependency audit requirements.
- **Accessibility / UX Design**: The file upload UI is mentioned but not designed. Drag-and-drop accessibility, progress indication for large files, and error recovery flow are not explored.
- **Data Engineering**: For the XLSX use case, no consideration of how real enterprise spreadsheets look -- merged cells, hidden sheets, data validation dropdowns, named ranges, pivot tables. openpyxl handles some of these but not all, and the research does not address which are in/out of scope.

---

### Recommended Actions Before Proceeding

1. **Design the multi-chunk anonymization pipeline in detail** (HIGH, blocking) -- The current `generate_placeholders()` / `replace_entities()` / `anonymize_entities()` functions are single-text-only. Specify exactly which new functions are needed and what their signatures look like. This is the architectural crux of the feature.

2. **Benchmark Presidio throughput for high-volume cell processing** (HIGH, blocking) -- Send 500-2000 small text payloads to Presidio Analyzer sequentially and measure total time. Determine whether batching or concurrency is needed to stay within the 120s timeout.

3. **Prototype PDF extraction on 3-5 real enterprise PDFs** (MEDIUM) -- Verify pdfminer.six produces usable text from typical contracts, reports, and invoices before committing to it. If quality is poor, PyMuPDF's AGPL license may need to be evaluated against enterprise legal requirements.

4. **Decide on encoding detection strategy** (MEDIUM) -- Add `charset-normalizer` or equivalent to the dependency plan and specify the fallback chain.

5. **Reconsider JSON-only output for CSV** (MEDIUM) -- Returning anonymized CSV as CSV text (not JSON-wrapped) is trivial and dramatically more useful. Consider whether CSV and JSON formats should preserve their native format even in v1.

6. **Verify defusedxml coverage for openpyxl and python-docx** (MEDIUM) -- Test whether `defusedxml.defuse_stdlib()` actually protects these libraries' internal XML parsing.

7. **Add language detection strategy for documents** (LOW) -- Specify whether language is detected once per document or per chunk, and how short-text unreliability is handled.

---

## Findings Addressed

All findings were resolved on 2026-03-29 by updating `SDD/research/RESEARCH-003-document-support.md`. Each finding is addressed as follows:

### Critical Gaps (HIGH)

1. **`generate_placeholders()` cannot accept shared state across chunks** — RESOLVED. Decision 4 completely rewritten with a detailed three-phase pipeline design. New `build_unified_placeholder_map()` function specified with full signature and implementation sketch. Explicitly documents that `generate_placeholders()` is NOT reused for multi-chunk documents. The existing function remains untouched for single-text `/api/anonymize`.

2. **`run_anonymization()` is not directly reusable for document processing** — RESOLVED. Integration Points section rewritten to explicitly state that `run_anonymization()` and `anonymize_entities()` are NOT called per-chunk. The document processor calls `presidio.analyze()` directly, uses `resolve_overlaps()` and `replace_entities()` as lower-level reusable functions, and implements its own orchestration via the new `build_unified_placeholder_map()`. Data flow diagram updated with correct step numbering (steps 4-9).

### Critical Gaps (MEDIUM)

3. **No analysis of Presidio rate limiting or concurrent call behavior** — RESOLVED. Decision 5 expanded with detailed throughput analysis (estimated ms/request for short, medium, and long text). Three batching/concurrency strategies analyzed (concatenation, bounded async concurrency, hybrid). Recommendation: bounded async concurrency via `asyncio.Semaphore(10)` with `asyncio.gather()`, which reduces 2000-cell processing from ~40-160s sequential to ~4-8s concurrent.

4. **No encoding detection strategy for text files** — RESOLVED. New "Text Encoding Detection: charset-normalizer" subsection added in File Format Extraction Libraries. Specifies a four-step decode strategy (BOM check, UTF-8 try, charset-normalizer fallback, error). `charset-normalizer` added to the dependencies table (MIT, ~300KB, pure Python).

5. **XLSX zip bomb protection is mentioned but not addressed** — RESOLVED. New "ZIP-Based Format Protection" subsection in Security Considerations. Concrete mitigation: open with `zipfile.ZipFile`, inspect ZIP directory, sum `info.file_size` for all entries, reject if total exceeds 100MB (10x max upload size). Fast check that reads ZIP central directory only.

6. **CSP header blocks file download if v2 adds file responses** — RESOLVED. New "CSP Considerations for v2 File Downloads" subsection added. Notes that `blob:` directive will need to be added to CSP when v2 implements file downloads. Documented as v2 implementation note.

7. **No analysis of `defusedxml` compatibility with openpyxl/python-docx** — RESOLVED. New "defusedxml Coverage for openpyxl and python-docx" subsection. Specifies that `defusedxml.defuse_stdlib()` must be called at startup BEFORE importing openpyxl/python-docx. Notes the lxml caveat for python-docx. Recommends an implementation-time verification test with a malicious XML entity expansion payload.

### Questionable Assumptions

1. **"In-memory processing is fine for 10MB files"** — RESOLVED. Decision 5 expanded with detailed memory amplification analysis per format (XLSX: 50-100MB, PDF: 30-50MB, DOCX: 3-5x, CSV/JSON/TXT: 1-2x). Peak per-request usage estimated at 100-150MB. Container sizing guidance added (1GB minimum, 3-5 concurrent uploads). openpyxl `read_only=True` mode noted as optimization.

2. **"Cell-by-cell processing is simpler than presidio-structured's column approach"** — RESOLVED. Decision 2 expanded with explicit limitation acknowledgment: short cell values (single names) will have lower detection rates. Column-header-aware detection analyzed but deferred to v2 as `column_hints` parameter. Additional XLSX edge cases documented (merged cells, hidden sheets, data validation, named ranges).

3. **"All output as JSON/text for v1" is acceptable UX** — RESOLVED. Decision 7 updated to "Option E with native-format exceptions." CSV returns native CSV text (not JSON-wrapped rows). JSON returns native JSON object. XLSX remains JSON structure (v1 limitation explicitly acknowledged with UX tradeoff discussion). Added note that if user feedback indicates XLSX output is a blocker, it should be prioritized for v2.

4. **"pdfminer.six is sufficient for text-based PDFs"** — RESOLVED. PDF section expanded with known extraction quality limitations (multi-column layouts, headers/footers, tables, font encoding edge cases, OCR'd PDFs with invisible text layer). Mitigation: warning message when extracted text is suspiciously short relative to file size. Prototyping recommendation added: test on 3-5 representative enterprise PDFs during implementation.

5. **"Language auto-detect per chunk" works for documents** — RESOLVED. Edge case 13 rewritten: language detected ONCE per document (from longest chunk or first 5KB sample), applied uniformly. User can override with explicit `language` parameter. Data flow diagram updated to show language detection as a distinct step (step 4) before chunk analysis.

### Missing Perspectives

- **InfoSec / Penetration Testing** — RESOLVED. New "Additional Perspectives" section with InfoSec subsection covering polyglot files, macro-enabled formats, pathological inputs (single large cell), and concurrent upload resource exhaustion. Security Considerations section expanded with items 14-16.

- **Enterprise IT / Deployment** — RESOLVED. New subsection covering Docker image impact (~17MB, pure Python, no system packages), CVE surface area (mature libraries, recommend CI/CD auditing), and infrastructure impact (no new ports/services).

- **Accessibility / UX Design** — RESOLVED. New subsection covering keyboard-accessible file input, progress indication via HTMX `hx-indicator`, error recovery UX, and accepted formats display.

- **Data Engineering** — RESOLVED. New subsection covering real enterprise XLSX features (merged cells, hidden sheets, data validation, pivot tables) and CSV delimiter detection strategy (`csv.Sniffer` with manual override fallback).
