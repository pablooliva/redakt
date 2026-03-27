# Redakt V1 — Feature Specification

## Overview

Redakt is an open-source wrapper around [Microsoft Presidio](https://github.com/microsoft/presidio) that provides PII detection, anonymization, and deanonymization through a web app and REST API. The primary use case is GDPR-compliant redaction of personal data before pasting content into LLMs.

Redakt is designed for **enterprise internal deployment** — made available to colleagues so they can safely anonymize content before using it with approved or free AI tools, protecting the organization from GDPR violations.

Redakt communicates with Presidio's REST API (Analyzer on port 5002, Anonymizer on port 5001) running as Docker containers. Redakt does not embed Presidio as a Python library — it is a separate service that orchestrates Presidio's endpoints and adds functionality on top.

---

## V1 Features

### Feature 1: PII Detection (Boolean Check)

**User story:** As a user or AI agent, I want to send text and get back a simple true/false answer for whether it contains PII.

**Behavior:**
- `POST /detect` accepts a text payload
- Calls Presidio Analyzer's `POST /analyze`
- Returns `{ "has_pii": true }` or `{ "has_pii": false }`
- Optionally returns the entity count and types detected (for transparency)

**Example request:**
```json
{
  "text": "John Smith lives in Berlin",
  "language": "auto"
}
```

**Example response:**
```json
{
  "has_pii": true,
  "entity_count": 2,
  "entities_found": ["PERSON", "LOCATION"]
}
```

**Presidio gap analysis:**

| What exists | What Redakt builds |
|---|---|
| `POST /analyze` returns full entity details (type, position, score) | Thin wrapper that reduces this to a boolean + optional summary |

**Open questions for SDD:**
- Should there be a configurable score threshold? (e.g., only flag PII above 0.7 confidence)
- Should specific entity types be excludable? (e.g., ignore LOCATION, only flag PERSON + EMAIL)
- Should the detailed entity list (with positions and scores) be available as an optional verbose mode?

---

### Feature 2: Anonymize + Reversible Deanonymization

**User story:** As a user, I want to paste text into a field, have PII anonymized, then later paste LLM-generated output into a second field and have the original PII values restored.

**Behavior:**
1. **Anonymize:** User submits text → Redakt detects PII and replaces each entity with a placeholder (e.g., `<PERSON_1>`, `<EMAIL_1>`) → Returns anonymized text **and** the mapping
2. **Deanonymize:** User pastes new text (e.g., LLM response) containing the same placeholders → the mapping is used to substitute original values back in → Returns rehydrated text

**Key design decision: Client-side mapping.** The placeholder ↔ original value mapping is returned to the client and held in the browser (in-memory or sessionStorage). Deanonymization is performed client-side via string replacement — no server call needed. This means:
- The Redakt backend **never persists PII** — it processes and forgets
- No server-side session store, no PII data at rest, no GDPR concern from stored mappings
- Browser session handles expiry naturally (tab close, or configurable timeout, e.g., 15 minutes)
- AI agents calling the REST API hold the mapping in memory for the duration of their task

**Example anonymize request:**
```json
{
  "text": "Please review John Smith's contract. His email is john@example.com.",
  "language": "auto"
}
```

**Example anonymize response:**
```json
{
  "anonymized_text": "Please review <PERSON_1>'s contract. His email is <EMAIL_1>.",
  "mappings": {
    "<PERSON_1>": "John Smith",
    "<EMAIL_1>": "john@example.com"
  }
}
```

Deanonymization happens client-side: the browser replaces `<PERSON_1>` → `John Smith`, `<EMAIL_1>` → `john@example.com` in whatever text the user pastes into the second field. No server round-trip.

**Presidio gap analysis:**

| What exists | What Redakt builds |
|---|---|
| `AnonymizerEngine` with replace, redact, hash, mask, encrypt operators | Orchestration layer that calls analyze → anonymize with `replace` operator using numbered placeholders |
| No concept of numbered/unique placeholders per entity | **Placeholder generation** — `<PERSON_1>`, `<PERSON_2>`, `<EMAIL_1>`, etc. |
| Stateless — no mapping persistence | Mapping returned to client; backend stays stateless by design |

**Open questions for SDD:**
- Should deanonymization work purely on string replacement, or should it be position-aware?
- How should duplicate PII values be handled? (e.g., "John Smith" appears 3 times — same placeholder or different?)
- Should the user be able to choose the anonymization operator (replace, mask, hash) or is replace the default for v1?
- What should the default browser-side mapping timeout be? (15 minutes? configurable?)

---

### Feature 3: Document Support (Excel + PDF)

**User story:** As a user, I want to upload an Excel spreadsheet or PDF document and have PII detected and anonymized within it, then download the result.

**Behavior:**
- User uploads a file → Redakt extracts text content → runs it through the PII pipeline → returns anonymized content (as downloadable file in the same format, or as extracted text)
- The mapping is returned to the client, same as Feature 2, so deanonymization works for documents too

**Supported file formats:**

| Format | Extraction approach | Complexity |
|---|---|---|
| **`.txt`** | Plain text, no extraction needed | Trivial |
| **`.md`** | Treat as plain text, preserve Markdown formatting | Trivial |
| **`.csv`** | Presidio's built-in `CsvReader` + `PandasDataProcessor` | Already supported |
| **`.json`** | Presidio's built-in `JsonReader` + `JsonDataProcessor` | Already supported |
| **`.xml` / `.html`** | Parse out text content, preserve tags/structure | Low |
| **`.xlsx`** | Load via pandas/openpyxl, feed into structured engine | Low |
| **`.docx`** | Extract text via `python-docx` | Low |
| **`.rtf`** | Extract text via `striprtf` or similar | Low |
| **`.pdf`** | Text extraction via pdfminer or PyMuPDF | Medium |

**Presidio gap analysis:**

| What exists | What Redakt builds |
|---|---|
| `presidio-structured` module handles pandas DataFrames and JSON | Orchestration to wire file upload → format detection → extraction → analysis → anonymization → file output |
| `CsvReader` + `JsonReader` for CSV and JSON | Readers for all other formats (txt, md, xml/html, xlsx, docx, rtf, pdf) |
| `BatchAnalyzerEngine` + `BatchAnonymizerEngine` for tabular data | Batch processing pipeline for multi-sheet/multi-page documents |
| No PDF support (only an example notebook using `pdfminer` + `pikepdf`) | **PDF text extraction** pipeline (pdfminer, PyMuPDF, or similar) |
| `presidio-image-redactor` handles OCR for scanned images | Potentially useful for scanned PDFs (image-based) |

**Open questions for SDD:**
- For Excel: should anonymization happen cell-by-cell or sheet-by-sheet? Should formulas be preserved?
- For PDF: text-based extraction only (pdfminer), or also support scanned/image-based PDFs (OCR via Tesseract)?
- Should the output be a new file in the same format (anonymized Excel → download as Excel), or is extracted text sufficient for v1?
- How should multi-sheet Excel workbooks be handled?
- For PDFs: should Redakt redact in-place (black-box annotations over PII) or replace text?
- For XML/HTML: preserve tag structure and only anonymize text content, or strip tags first?
- For `.docx`: preserve formatting (bold, headings, tables) in the output, or extract as plain text?
- File size limits? Processing timeout?

---

### Feature 4: Language Auto-Detection with Manual Override

**User story:** As a user in a German enterprise, my content is in German, English, or a mix. I want Redakt to automatically detect the language without me having to think about it, but allow me to override if the detection is wrong.

**Behavior:**
- All endpoints accept `"language": "auto"` (the default) or an explicit ISO 639-1 code (e.g., `"de"`, `"en"`)
- Auto-detection runs before PII analysis and passes the detected language to Presidio
- The web UI shows the detected language and provides a toggle/dropdown to override it
- The API response includes the detected language so agents can verify or retry with a different language

**Presidio gap analysis:**

| What exists | What Redakt builds |
|---|---|
| Presidio requires an explicit `language` parameter on every analyze call | **Language detection layer** — auto-detect before calling Presidio (e.g., using `langdetect` or `lingua`) |
| Supports multiple languages with language-specific recognizers (13 DE recognizers built in) | UI toggle to override detected language |

**Open questions for SDD:**
- Which detection library? (`langdetect`, `lingua-py`, `fasttext`?)
- How to handle mixed-language content? (e.g., German text with English names)
- Should detection run on the full text or a sample?

---

### Feature 5: Allow Lists

**User story:** As an enterprise user, I don't want our company name, product names, or internal terms constantly flagged as PII. I want to configure a list of terms that should never be treated as PII.

**Behavior:**
- An instance-wide allow list is configurable (e.g., company name, product names, office locations)
- Users can add per-request allow list terms via the UI or API
- Allow-listed terms are passed to Presidio's `allow_list` parameter, which suppresses matches for those terms

**Example request with allow list:**
```json
{
  "text": "Acme Corp's Berlin office contact is John Smith at john@acme.com",
  "language": "auto",
  "allow_list": ["Acme Corp", "Berlin"]
}
```

In this example, "Acme Corp" and "Berlin" would not be flagged, but "John Smith" and "john@acme.com" still would.

**Presidio gap analysis:**

| What exists | What Redakt builds |
|---|---|
| `allow_list` parameter on `POST /analyze` — supports exact match and regex | Instance-wide configurable allow list (config file or env var) |
| Works per-request | UI for adding per-request allow list terms |
| No persistence | Persistent instance-level allow list that merges with per-request terms |

**Open questions for SDD:**
- Where is the instance-wide allow list stored? (config file, environment variable, mounted volume?)
- Should there be a UI for managing the instance-wide list, or is it admin-only config?
- Should allow list support regex patterns or just exact matches for v1?

---

### Feature 6: Audit Logging

**User story:** As a compliance officer, I need to demonstrate that employees are properly anonymizing data before sending it to AI tools. I need an audit trail of anonymization activity.

**Behavior:**
- Every detect, anonymize, and document upload request is logged
- Logs capture metadata only — **never the actual PII or original text**
- Log entries include: timestamp, action type (detect/anonymize/document), entity types found, entity count, language, operator used
- Logs are written to stdout (for Docker log collection) and optionally to a file

**Example log entry:**
```json
{
  "timestamp": "2026-03-27T15:30:00Z",
  "action": "anonymize",
  "language_detected": "de",
  "entities_found": ["PERSON", "PERSON", "EMAIL_ADDRESS", "DE_TAX_ID"],
  "entity_count": 4,
  "operator": "replace",
  "source": "web_ui"
}
```

**Presidio gap analysis:**

| What exists | What Redakt builds |
|---|---|
| Presidio has internal logging but no audit-level output | Structured audit log middleware on all Redakt endpoints |
| No concept of usage tracking | Log format designed for compliance reporting |

**Open questions for SDD:**
- Should logs distinguish between web UI and API (agent) usage?
- Should there be a log viewer in the web UI, or is log file / Docker log access sufficient for v1?
- What log format? (JSON lines for machine parsing, or structured text?)
- Should logs include a user identifier if authentication is added later?

---

## Deployment

The entire stack — Redakt and Presidio — runs via a single `docker-compose.yml` at the project root. One command brings up everything:

```bash
docker compose up --build
```

```
+------------------------------------------------------------------+
|  docker-compose.yml                                              |
|                                                                  |
|  +-------------------+                                           |
|  |  redakt-frontend  |  Web UI (serves static assets)            |
|  |  :3000            |                                           |
|  +--------+----------+                                           |
|           |                                                      |
|           v                                                      |
|  +-------------------+                                           |
|  |  redakt-api       |  Redakt backend                           |
|  |  :8000            |  (web app + REST API for AI agents)       |
|  +---+----------+----+                                           |
|      |          |                                                |
|      v          v                                                |
|  +----------+  +---------------+                                 |
|  | presidio |  | presidio      |                                 |
|  | analyzer |  | anonymizer    |                                 |
|  | :5002    |  | :5001         |                                 |
|  +----------+  +---------------+                                 |
+------------------------------------------------------------------+
```

### Services

| Service | Description | Port |
|---|---|---|
| `redakt-frontend` | Web UI — static frontend served by nginx or similar | 3000 |
| `redakt-api` | Redakt backend — orchestrates Presidio, serves the REST API (stateless, no PII persisted) | 8000 |
| `presidio-analyzer` | Presidio's PII detection service (from `presidio/` subdir) | 5002 |
| `presidio-anonymizer` | Presidio's anonymization service (from `presidio/` subdir) | 5001 |

Presidio services are internal — only `redakt-api` talks to them. The frontend and AI agents both talk to `redakt-api`.

### NLP engine choice

The Presidio Analyzer container uses the transformers-based NER model (`StanfordAIMI/stanford-deidentifier-base`) by default, built from `presidio/Dockerfile.transformers`. This can be swapped for the lighter spaCy-based build during development.

---

## API Surface

All v1 features are exposed as REST endpoints. The web UI and AI agents use the same API — the frontend is just one client.

### Endpoints

| Method | Path | Feature | Description |
|---|---|---|---|
| `POST` | `/api/detect` | PII Detection | Returns boolean + optional entity summary |
| `POST` | `/api/anonymize` | Anonymize | Anonymizes text, returns placeholders + mapping (client holds mapping; deanonymization is client-side) |
| `POST` | `/api/documents/upload` | Document Support | Upload Excel/PDF, returns anonymized content + mapping |
| `GET` | `/api/health` | — | Health check (includes Presidio service status) |

All endpoints accept `"language": "auto"` (default) or an explicit language code. All endpoints respect the instance-wide allow list, merged with any per-request `allow_list` terms. All requests are audit-logged (metadata only, no PII).

AI agents interact with exactly the same endpoints as the web app — no separate API.

---

## Next Steps

After this spec is reviewed and agreed upon, create individual SDDs for each feature:
1. `docs/sdd-pii-detection.md` — PII detection (boolean check)
2. `docs/sdd-anonymize-deanonymize.md` — Anonymize + client-side deanonymization
3. `docs/sdd-document-support.md` — Excel + PDF document processing
4. `docs/sdd-language-detection.md` — Auto-detect with manual override
5. `docs/sdd-allow-lists.md` — Instance-wide + per-request allow lists
6. `docs/sdd-audit-logging.md` — Compliance audit trail

Each SDD will resolve the open questions listed above and define the technical architecture, data models, API contracts, and implementation approach.
