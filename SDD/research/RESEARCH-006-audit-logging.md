# RESEARCH-006-audit-logging

## System Data Flow

### Key Entry Points

Audit logging is **already partially implemented**. The core audit service exists at `src/redakt/services/audit.py` and is called from all three endpoint types. This research documents what exists and identifies gaps for a complete Feature 6 implementation.

1. **API: Detect** -- `src/redakt/routers/detect.py:144-151`
   - After successful detection, determines source via `request.headers.get("HX-Request")` (line 144)
   - Calls `log_detection(entity_count, entity_types, language, source, allow_list_count)` (lines 145-151)
   - Only logs on success -- errors/exceptions skip the audit call

2. **API: Anonymize** -- `src/redakt/routers/anonymize.py:138-145`
   - Same HX-Request pattern for source detection (line 138)
   - Calls `log_anonymization(entity_count, entity_types, language, source, allow_list_count)` (lines 139-145)
   - Only logs on success

3. **API: Document Upload** -- `src/redakt/routers/documents.py:139-150`
   - Same HX-Request source detection (line 139)
   - Calls `log_document_upload(file_type, file_size_bytes, entity_count, entity_types, language, source, allow_list_count)` (lines 142-150)
   - Explicitly notes "no PII: no filename, no content" in comment (line 138)

4. **Web UI: Detect** -- `src/redakt/routers/pages.py:77-83`
   - Hardcoded `source="web_ui"` (line 80)
   - Calls `log_detection()` with same parameters

5. **Web UI: Anonymize** -- `src/redakt/routers/pages.py:147-153`
   - Hardcoded `source="web_ui"` (line 150)
   - Calls `log_anonymization()`

6. **Web UI: Documents** -- `src/redakt/routers/pages.py:258-266`
   - Hardcoded `source="web_ui"` (line 263)
   - Calls `log_document_upload()`

### Audit Service Implementation (existing)

**File: `src/redakt/services/audit.py`**

- `setup_logging(log_level)` -- Called during app lifespan startup at `main.py:39`. Creates a dedicated `redakt.audit` logger at INFO level with `JSONFormatter`, writing to stdout. Prevents propagation to parent logger (line 24).
- `JSONFormatter` (lines 6-17) -- Formats log records as JSON. Adds `timestamp` (UTC ISO 8601), `level`, `logger` name. If record has `audit_data` attribute, merges it into the JSON. Otherwise falls back to `message` field.
- `_emit_audit()` (lines 35-64) -- Core emission function. Creates a log record manually via `makeRecord()`, attaches `audit_data` dict with: `action`, `entity_count`, `entity_types`, `language`, `source`. Conditionally adds `allow_list_count` if present and > 0. Accepts `**extra` for additional fields (used for `file_type` and `file_size_bytes` in document uploads). **No try/except wraps `audit_logger.handle(record)` at line 64** -- an exception in the handler (e.g., broken stdout, formatter bug) would propagate up to the calling endpoint and return a 500 to the client even though the actual processing succeeded. This must be fixed with defensive error handling (see Error Handling section below).
- `log_detection()` (lines 67-74) -- Thin wrapper calling `_emit_audit("detect", ...)`.
- `log_anonymization()` (lines 77-84) -- Thin wrapper calling `_emit_audit("anonymize", ...)`.
- `log_document_upload()` (lines 87-105) -- Wrapper adding `file_type` and `file_size_bytes` as extra fields.

#### BUG: Duplicate Handler Accumulation on Reload

`setup_logging()` at `audit.py:20-28` calls `audit_logger.addHandler(audit_handler)` unconditionally every time it is invoked. Python's `logging.getLogger("redakt.audit")` returns the **same logger instance** across calls. The Dockerfile (line 26) runs uvicorn with `reload=True`, and each reload triggers the lifespan context manager (`main.py:38-44`), which calls `setup_logging()` again. After N reloads, the audit logger has N handlers, and each audit event is emitted N times to stdout.

**Fix required**: Guard handler addition with `if not audit_logger.handlers:` or clear existing handlers before adding (`audit_logger.handlers.clear()`). In production, if `reload=True` is not disabled (and nothing currently guarantees it is), this bug would corrupt audit log integrity.

### Logging Infrastructure (existing)

**File: `src/redakt/log_config.py`**

- `UVICORN_LOG_CONFIG` -- Custom dict config for uvicorn. Used in `Dockerfile` CMD line (line 26).
- `HealthCheckFilter` -- Suppresses `/api/health/live` access log noise (line 42-44).
- Uvicorn access logs go to stdout, error logs to stderr.
- The audit logger (`redakt.audit`) is separate from uvicorn's loggers -- it writes to its own stdout handler with JSON formatting.

### Data Transformations

```
Request arrives at endpoint (detect/anonymize/document)
        |
        v
Processing occurs (Presidio analysis, anonymization)
        |
        v
Source determination: request.headers.get("HX-Request") -> "web_ui" or "api"
  (API routes: detect.py:144, anonymize.py:138, documents.py:139)
  (Web routes: hardcoded "web_ui" in pages.py)
        |
        v
Metadata extraction (entity_count, entity_types, language, etc.)
  NOTE: Original text and PII values are NEVER passed to log functions
        |
        v
_emit_audit() in services/audit.py:35
  -> Creates logging.LogRecord with audit_data attribute
  -> JSONFormatter.format() merges audit_data into JSON
        |
        v
StreamHandler -> stdout (JSON lines)
```

### Error Handling in Audit Emission

The audit logging call sites (`detect.py:145-151`, `anonymize.py:139-145`, `documents.py:142-150`, `pages.py:77-83`, `pages.py:147-153`, `pages.py:258-266`) are all placed **after** successful processing but **before** the response is returned, and **none** are wrapped in try/except. If `audit_logger.handle(record)` at `audit.py:64` raises (broken pipe, full disk on future file handler, formatter bug on unusual input), the exception propagates up and the endpoint returns a 500 error -- even though the PII detection/anonymization succeeded. The user loses the result.

**Design decision required**: Should audit failure be swallowed (logged to app logger, request continues) or should it fail the request? For a compliance tool, the answer is almost certainly "swallow and continue" -- the user's result is more important than a single audit entry, and the audit failure itself should be logged via the app logger for investigation.

**Recommendation**: Wrap `audit_logger.handle(record)` in `_emit_audit()` with a try/except that catches `Exception`, logs the failure to the app logger (`logging.getLogger("redakt")`), and returns silently.

### Event Loop Blocking Risk

`audit_logger.handle(record)` at `audit.py:64` is a synchronous call. In FastAPI with uvicorn, async endpoint handlers run on the event loop. Writing to stdout is normally fast, but if the Docker log driver is slow (e.g., remote fluentd, full pipe buffer), this call blocks the event loop and stalls all concurrent requests.

**Mitigation options for future consideration**:
- Use `logging.handlers.QueueHandler` with a `QueueListener` to offload emission to a background thread
- Use `asyncio.to_thread()` at the call site (adds complexity)
- For v1 with stdout-only, this is low risk. For file-based logging, the blocking risk increases and should be addressed.

### External Dependencies

- **Python stdlib `logging`** -- Used directly, no third-party logging library
- **No file output** -- Currently stdout only (no file handler configured)
- **No log rotation** -- Not implemented; relies on Docker log drivers
- **No structured logging library** -- Uses custom `JSONFormatter` on stdlib logging

### Integration Points

- **App startup**: `setup_logging()` called in `main.py:39` during lifespan context
- **All three API routers**: detect.py, anonymize.py, documents.py import and call audit functions
- **Web UI router**: pages.py imports and calls the same audit functions
- **Config**: `settings.log_level` (default "WARNING") controls app logger level; audit logger is always INFO (line 22-23 of audit.py)
- **Docker**: `Dockerfile` line 26 configures uvicorn with `UVICORN_LOG_CONFIG` from `log_config.py`

## Stakeholder Mental Models

- **Product Team perspective:** Audit logging provides a compliance trail for GDPR. The primary consumer is a compliance officer who needs to demonstrate anonymization activity. They care about: what actions were taken, how many entities were found, and whether usage is from the web UI or automated agents. They do NOT need to see original text -- that would be a GDPR violation.

- **Engineering Team perspective:** The existing implementation is functional but minimal. Key gaps: no file-based logging, no log viewer, no error/failure logging, no request ID for correlation, no operator field (spec says "operator used" but it is not logged), no configurable file output path. The audit service uses stdlib logging with a custom formatter -- simple and dependency-free, but lacks structured logging features (context binding, processors, etc.).

- **Support Team perspective:** When investigating issues, support needs to correlate audit entries with specific requests. Currently there is no request ID, session ID, or user identifier. For v1 without auth, this is acceptable, but the schema should be extensible.

- **Infrastructure/DevOps perspective:** Log collection, aggregation, and retention are critical deployment concerns. The current stdout-only approach relies entirely on the Docker log driver. Different log drivers (json-file, fluentd, awslogs, gelf) have different JSON parsing behaviors -- some expect one JSON object per line (which the current implementation provides), others may wrap it in their own JSON envelope. The `docker-compose.yml` has no `logging:` configuration, so the default `json-file` driver is used with no max-size constraint. In production, log retention policies, centralized aggregation (ELK, Loki, CloudWatch), and alerting on audit anomalies (e.g., sudden spike in entity counts, unusual hours of usage) would need to be configured at the infrastructure layer.

- **Legal/DPO (Data Protection Officer) perspective:** The audit log schema should be evaluated against GDPR Article 30 requirements for records of processing activities. The current "metadata only" approach is sound for PII avoidance, but a DPO may ask whether the audit trail itself is sufficient to demonstrate compliance (e.g., can you prove every processing activity was logged? can you prove logs were not tampered with?). The v1 limitations around log integrity and the lack of tamper detection should be explicitly communicated to the DPO.

- **QA/Testing perspective:** Testing the actual JSON output from the audit logger is non-trivial with pytest. The `caplog` fixture captures log records by their `message` attribute, but the `JSONFormatter` reads from `record.audit_data` (a custom attribute). Tests must either: (a) inspect `record.audit_data` directly from captured records, (b) add a custom handler that captures formatted output, or (c) capture stdout. Existing tests (e.g., `test_detect.py:170-181`) use mock-based approaches to verify `log_detection` was called with correct args -- they do not test the actual JSON output format. This is a gap.

- **User perspective:** Users do not directly interact with audit logs. The spec's open question about a log viewer in the web UI is relevant here -- for v1, log file / Docker log access is likely sufficient.

## Production Edge Cases

### Historical Issues

No production deployment yet (v1 in development). The following are anticipated edge cases:

### Anticipated Edge Cases

1. **Duplicate audit entries**: Both API routes and web UI routes call `log_detection()` / `log_anonymization()`. However, the web UI form submit routes (`pages.py`) call the shared `run_detection()` / `run_anonymization()` functions (which do NOT log), then log separately. The API routes (`detect.py`, `anonymize.py`) also call shared functions then log separately. So there are **no duplicate logs** -- each route logs exactly once. **Caveat**: The source detection via `HX-Request` header is fragile -- any API caller can set `HX-Request: true` to appear as `web_ui` source. An HTMX request sent directly to `/api/detect` would be logged as `source="web_ui"`. While this does not create duplicate entries, it means the `source` field is **spoofable and underdocumented**. Future route consolidation or refactoring should preserve the invariant that each request is logged exactly once. **Note on the duplicate handler bug**: With the `setup_logging()` bug described above, each audit event IS emitted N times after N reloads, which constitutes duplicate entries in a different sense. This must be fixed.

2. **Missing audit on errors**: If Presidio is unavailable (503), times out (504), or returns errors (502), the audit log call is skipped entirely. Failed requests are NOT audited. This could be a compliance gap -- a compliance officer might want to know about failed attempts too.

3. **Empty text requests**: Both detect and anonymize handle empty text as early returns (detect.py:59-64, anonymize.py:53-57). The audit log IS still called for empty text in **both API and web UI routes**: `run_detection()` / `run_anonymization()` return a result with `entity_count=0` for empty text, and the calling code (API routes at detect.py:145-151, anonymize.py:139-145; web UI routes at pages.py:77-83, pages.py:147-153) always proceeds to log after a successful return. Entity_count will be 0 and entity_types will be []. This is correct and consistent behavior across both code paths.

4. **Large entity_types lists**: If a document contains many different PII types, the `entity_types` list in the JSON log could be large. The current implementation logs all unique types -- no truncation.

5. **Concurrent requests**: The `logging` module is thread-safe. The async FastAPI handlers run on the event loop, and `audit_logger.handle(record)` is synchronous but fast (just writes to stdout). Under normal conditions, this is not a concern. However, if the Docker log driver is slow or stdout pipe buffer is full, this synchronous call blocks the event loop and stalls all concurrent requests. See "Event Loop Blocking Risk" section above for mitigation options.

6. **Log volume**: In a busy enterprise, many requests per second could generate high log volume. No rate limiting or sampling on audit logs. This is correct for compliance -- every request must be logged.

6. **`file_type` can be empty string**: When no filename is provided via the API, `_sanitize_extension()` at `documents.py:37-51` returns `""` for `None` filename, and `extension.lstrip(".")` at `documents.py:143` still produces `""`. The audit log will contain `"file_type": ""`. For the web UI route, `pages.py:191-193` similarly sets `extension = ""` when `file.filename` is falsy. Log consumers expecting a valid file type will get an empty string. **Recommendation**: Default to `"unknown"` when the extension is empty after stripping the dot.

### Error Patterns

- The audit logger itself has no error handling. If stdout is broken (unlikely in Docker), `StreamHandler` would raise, potentially crashing the request. This is a real risk -- see "Error Handling in Audit Emission" section above for detailed analysis and recommendation. The fix is to wrap `audit_logger.handle(record)` in `_emit_audit()` with try/except.

## Files That Matter

### Core Logic (existing implementation)

| File | Lines | Purpose |
|------|-------|---------|
| `src/redakt/services/audit.py` | 1-105 | Audit service: JSONFormatter, setup_logging, _emit_audit, log_detection, log_anonymization, log_document_upload |
| `src/redakt/log_config.py` | 1-44 | Uvicorn log config, HealthCheckFilter |
| `src/redakt/main.py` | 39 | setup_logging() call in lifespan |
| `src/redakt/config.py` | 21 | `log_level` setting (default "WARNING") |

### Audit Call Sites (where audit functions are invoked)

| File | Lines | Action |
|------|-------|--------|
| `src/redakt/routers/detect.py` | 144-151 | log_detection from API detect |
| `src/redakt/routers/anonymize.py` | 138-145 | log_anonymization from API anonymize |
| `src/redakt/routers/documents.py` | 138-150 | log_document_upload from API document upload |
| `src/redakt/routers/pages.py` | 77-83 | log_detection from web UI detect |
| `src/redakt/routers/pages.py` | 147-153 | log_anonymization from web UI anonymize |
| `src/redakt/routers/pages.py` | 258-266 | log_document_upload from web UI document upload |

### Tests (existing coverage)

| File | Lines | What's Tested |
|------|-------|---------------|
| `tests/test_detect.py` | 170-181 | Audit log emitted for detect, source="api", no PII in log |
| `tests/test_anonymize_api.py` | 134-150 | Audit log emitted for anonymize, source="api", no PII in log |
| `tests/test_documents_api.py` | 225-243 | Audit log emitted for document upload, source="api", no PII in log |
| `tests/test_allow_list_web.py` | 282-322 | allow_list_count included/excluded in audit logs |

### Test Coverage Gaps

- No tests for `JSONFormatter` output format (actual JSON structure)
- No tests for `setup_logging()` configuration behavior
- No tests for `_emit_audit()` directly
- No tests verifying audit logs are NOT emitted on error/failure paths
- No tests for web UI source detection (pages.py always hardcodes "web_ui")
- No tests verifying timestamp format in log output
- No tests for file-based logging (not yet implemented)
- No E2E tests validating audit log output in Docker

### Configuration

| File | Setting | Current Value | Purpose |
|------|---------|---------------|---------|
| `src/redakt/config.py` | `log_level` | `"WARNING"` | Controls app logger; audit logger is always INFO |
| `docker-compose.yml` | N/A | No logging config | No Docker log driver configuration |
| `Dockerfile` | CMD | Uses `UVICORN_LOG_CONFIG` | Uvicorn logging setup |

### Missing Configuration (gaps)

- No `REDAKT_AUDIT_LOG_FILE` or similar setting for file output path
- No `REDAKT_AUDIT_LOG_ENABLED` toggle
- No log rotation settings (max size, backup count)

## Security Considerations

### Authentication/Authorization

- No authentication in v1. All requests are anonymous.
- The `source` field distinguishes "web_ui" vs "api" via the `HX-Request` header (set by HTMX). This is **spoofable** -- any API caller can set `HX-Request: true` to appear as web UI. For v1 without auth, this is acceptable. The feature spec notes: "Should logs include a user identifier if authentication is added later?" -- the schema should be extensible for this.

### Data Privacy (CRITICAL)

The audit system is designed around the principle of **metadata only, never PII**:

1. **Text is never passed to log functions**: The audit functions accept `entity_count`, `entity_types`, `language`, `source` -- none of which contain original text or PII values.
2. **File names are not logged**: Document upload logs `file_type` (extension only, e.g., "txt") and `file_size_bytes` -- never the filename (which could contain PII like "john_smith_contract.pdf").
3. **Mappings are not logged**: The anonymization mappings (which contain original PII values) are never passed to audit functions.
4. **Entity types are safe**: Types like "PERSON", "EMAIL_ADDRESS" are category labels, not actual values.

**Potential PII leak vectors to watch:**

- `language` field: Safe (ISO 639-1 codes like "en", "de").
- `entity_types` list: Safe (enum-like category names from Presidio).
- `allow_list_count`: Safe (just a number, not the actual allow list terms).
- `file_type` / `file_size_bytes`: Safe (generic metadata).
- **Future additions**: Any new fields (e.g., error messages, request paths, query parameters) must be reviewed for PII content. Error messages from Presidio could potentially contain text snippets.

### Log Integrity and Tamper Detection (v1 Limitation)

For a GDPR compliance audit trail, log integrity is critical. The current implementation has **no tamper-detection mechanism**:

- **No log signing**: Audit entries are plain JSON lines to stdout. Nothing prevents modification or deletion.
- **No append-only guarantees**: Docker's default `json-file` log driver stores container logs in a JSON file on the host. These files can be edited, truncated, or deleted by anyone with host access. Docker's log driver can also silently drop old logs when file size limits are configured.
- **No sequence numbers or hash chain**: There is no way to detect if entries have been removed or reordered.
- **No chain-of-custody**: The `docker-compose.yml` has no logging driver configuration (verified at `docker-compose.yml:1-45`), relying on Docker's default `json-file` driver with no max-size constraint.

**Known v1 limitation**: A compliance officer relying on these logs cannot cryptographically prove they have not been tampered with. For v1, this is acceptable given the scope (internal enterprise tool, pre-production). For production hardening, consider:
- Adding a monotonically increasing sequence number to each audit entry for gap detection
- Shipping logs to an immutable log store (e.g., AWS CloudWatch, append-only S3, centralized SIEM)
- Documenting this limitation in compliance guidance so the DPO is aware

This limitation should be noted in any compliance documentation per GDPR Article 30 (records of processing activities).

### Input Validation

- Audit log fields are derived from processing results, not directly from user input. No injection risk in the current implementation.
- JSON serialization via `json.dumps()` handles special characters safely.
- The `**extra` kwargs in `_emit_audit()` are an open extension point -- any caller could add arbitrary fields. Currently only used for `file_type` and `file_size_bytes` (documents.py:142-150). This is a **schema integrity risk**: any caller could accidentally pass PII-containing fields through this mechanism. **Recommendation**: Either constrain `**extra` to an explicit allowlist of permitted keys (e.g., `{"file_type", "file_size_bytes"}`) or replace the open `**extra` pattern with explicit keyword parameters. This is especially important before authentication is added, as a `user_id` field passed via `**extra` would bypass any validation.

## Testing Strategy

### Unit Tests

1. **JSONFormatter output structure**: Verify the JSON output contains exactly the expected fields (`timestamp`, `level`, `logger`, plus audit_data fields). Verify ISO 8601 UTC timestamp format.
2. **_emit_audit() field assembly**: Test that all fields are correctly assembled, `allow_list_count` is omitted when None or 0, `**extra` fields are included.
3. **log_detection() / log_anonymization() / log_document_upload()**: Test each wrapper passes correct `action` value and fields.
4. **setup_logging() configuration**: Verify audit logger level is INFO regardless of `log_level` setting. Verify handler uses JSONFormatter. Verify `propagate=False`.
5. **No PII in any log output**: Parameterized tests with PII-containing inputs, asserting no PII appears in captured log output.
6. **Error path audit behavior**: Verify audit logs are NOT emitted when Presidio errors occur (503, 504, 502 paths).

### Integration Tests

1. **Full request -> audit log**: Use `TestClient`, capture log output, verify JSON structure for detect/anonymize/document endpoints.
2. **Source detection**: Send requests with and without `HX-Request` header, verify `source` field in log output.
3. **File-based logging** (if implemented): Verify log file is created, written to, and contains valid JSON lines.
4. **Concurrent request audit isolation**: Multiple concurrent requests should produce distinct, non-interleaved log entries.

### Testing Implementation Notes

- **`caplog` limitations**: pytest's `caplog` fixture captures `LogRecord` objects but accesses them via `.message`. The `JSONFormatter` reads from `record.audit_data`, a custom attribute. To test actual JSON output, either: (a) access `record.audit_data` directly from `caplog.records`, (b) attach a custom `StreamHandler` writing to a `StringIO` buffer, or (c) mock the handler and inspect what it receives.
- **Existing test pattern**: Current tests (e.g., `test_detect.py:170-181`) mock `log_detection` and verify it was called with correct kwargs. This validates the call site but not the `_emit_audit()` -> `JSONFormatter` -> JSON output pipeline.

### Edge Cases to Test

- Empty text input -> audit log with entity_count=0 (verify for BOTH API and web UI routes)
- Very long entity_types list (many PII types)
- Document with no PII -> audit log with entity_count=0, entity_types=[]
- Unicode content (PII in non-Latin scripts) -> verify no PII leaks into log
- allow_list_count=0 vs None behavior
- Rapid sequential requests -> all logged, correct order

### E2E Tests

- Since audit logging is a backend/infrastructure concern with no browser-facing behavior, E2E tests are not strictly necessary.
- However, validating that Docker stdout contains audit JSON lines after web UI interactions could be valuable for deployment confidence.

## Documentation Needs

### User-Facing Docs

- **Compliance guide**: How to access and interpret audit logs. What each field means. What is guaranteed NOT to be in logs (PII).
- **Docker log collection**: How to configure Docker log drivers (json-file, fluentd, etc.) to collect Redakt audit logs. Log line format documentation.
- **File-based logging** (if implemented): How to enable, configure path, rotation settings.

### Developer Docs

- **Audit log schema**: JSON schema for each action type (detect, anonymize, document_upload). Field descriptions, types, and constraints.
- **Adding new audited endpoints**: How to add audit logging to new features. Pattern: call `_emit_audit()` or create a new wrapper function.
- **PII safety checklist**: What to verify before adding any new field to audit logs.

### Configuration Docs

- `REDAKT_LOG_LEVEL` -- Controls application logger level; audit logger always runs at INFO.
- New settings needed (if implemented):
  - `REDAKT_AUDIT_LOG_FILE` -- Path for file-based audit log output (default: None / stdout only)
  - `REDAKT_AUDIT_LOG_ROTATION_SIZE` -- Max file size before rotation (e.g., 10MB)
  - `REDAKT_AUDIT_LOG_ROTATION_COUNT` -- Number of rotated files to keep

## Gaps Between Feature Spec and Current Implementation

### Already Implemented

| Spec Requirement | Status | Location | Notes |
|------------------|--------|----------|-------|
| Every detect request is logged | Done | detect.py:145-151, pages.py:77-83 | |
| Every anonymize request is logged | Done | anonymize.py:139-145, pages.py:147-153 | |
| Every document upload is logged | Done | documents.py:142-150, pages.py:258-266 | |
| Metadata only, never PII | Done | audit functions only accept metadata params | |
| Timestamp | Done | JSONFormatter adds UTC ISO 8601 timestamp | |
| Action type | Done | "detect", "anonymize", "document_upload" | |
| Entity types found | **Divergent** | audit.py:57 uses `entity_types` | See schema divergence note below |
| Entity count | Done | entity_count integer | |
| Language | **Divergent** | audit.py:58 uses `language` | See schema divergence note below |
| JSON lines format | Done | JSONFormatter outputs single-line JSON | |
| Stdout output | Done | StreamHandler to stdout | |
| Distinguish web UI vs API | Done | "web_ui" / "api" via HX-Request header | |

#### Schema Divergence from Feature Spec

The feature spec at `docs/v1-feature-spec.md:219-229` uses field names `entities_found` and `language_detected` in its example log entry. The implementation at `audit.py:54-60` uses `entity_types` and `language`. This is a **naming divergence**.

More importantly, the spec example shows `entities_found` with **duplicates** preserving per-occurrence type information:
```json
"entities_found": ["PERSON", "PERSON", "EMAIL_ADDRESS", "DE_TAX_ID"]
```

The implementation at `detect.py:110` deduplicates and sorts entity types:
```python
entity_types = sorted(set(r["entity_type"] for r in results))
```

This means the audit log loses per-entity occurrence data. For `entity_count: 4, entity_types: ["PERSON"]`, the types list does not convey what those 4 entities were categorized as individually if there were mixed types. A compliance officer reading the spec would expect per-occurrence types.

**Decision required**: Either (a) match the spec field names and semantics (use `entities_found` with duplicates, use `language_detected`), or (b) update the spec to match the implementation. This should be decided during the spec phase, not left implicit. For compliance downstream consumers, schema consistency matters.

### Not Yet Implemented (Gaps)

| Spec Requirement | Gap | Notes |
|------------------|-----|-------|
| "operator used" field | Missing | Spec example shows `"operator": "replace"`. Currently all anonymization uses the replace operator (Redakt does client-side placeholder replacement via `anonymizer.py`, not Presidio's anonymizer operators). While v1 only uses "replace", the schema should be designed for when multiple operators (mask, hash, encrypt) are supported. When that happens, the operator may differ **per entity** within a single request, requiring either a list of operators or a per-entity breakdown -- not just a single string. **Design decision required during spec phase.** |
| Schema field names | Divergent | Spec uses `entities_found` (with duplicates) and `language_detected`; implementation uses `entity_types` (deduplicated) and `language`. See "Schema Divergence" section above. |
| Optional file output | Missing | Spec says "optionally to a file". No file handler, no config setting. Needs: config setting for file path, RotatingFileHandler, setup in `setup_logging()`. File-based logging introduces concurrency concerns (file locking), configuration validation (path permissions), and rotation behavior in containerized environments that are non-trivial. |
| Log rotation | Missing | Needed if file output is added. `logging.handlers.RotatingFileHandler` with maxBytes and backupCount. |
| Error/failure logging | Missing | Failed requests (503, 504, 502, 422, 413) skip audit logging entirely. May need a separate `log_error()` or expanding existing functions. |
| Duplicate handler bug | Bug | `setup_logging()` appends a new handler on every call without checking for existing handlers. See "BUG: Duplicate Handler Accumulation" section above. |
| Defensive error handling | Missing | No try/except around audit emission. See "Error Handling in Audit Emission" section above. |
| Log integrity | Missing (v1 limitation) | No tamper detection, sequence numbers, or signing. See "Log Integrity and Tamper Detection" section above. |

### Open Questions from Spec (with Recommended Answers)

1. **"Should logs distinguish between web UI and API (agent) usage?"**
   - Already implemented via `source` field ("web_ui" / "api"). Resolved.

2. **"Should there be a log viewer in the web UI, or is log file / Docker log access sufficient for v1?"**
   - Recommendation: Docker log access is sufficient for v1. A log viewer adds significant complexity (log storage, pagination, search, access control) for minimal v1 value. The compliance officer can use `docker logs redakt | jq` or a centralized log platform.

3. **"What log format? (JSON lines for machine parsing, or structured text?)"**
   - Already implemented as JSON lines. Resolved.

4. **"Should logs include a user identifier if authentication is added later?"**
   - Recommendation: Design the schema to be extensible. Add an optional `user_id` field (default null) that can be populated when auth is added. The `**extra` kwargs pattern in `_emit_audit()` already supports this without schema changes.

## Implementation Complexity Assessment

The existing implementation covers the **core audit logging flow** (every request type is logged with metadata, JSON format, stdout output). However, the remaining work involves higher-complexity items than a simple line-item count suggests. Counting checklist items, roughly 60-65% of the spec is covered. Counting by effort, the remaining work represents approximately **40-50% of total effort** due to the non-trivial nature of the gaps.

Remaining work:

1. **Fix duplicate handler bug** -- Quick fix but critical for development correctness. Guard `addHandler()` in `setup_logging()`. ~10 minutes.
2. **Add defensive try/except around audit emission** -- Quick fix. Wrap `audit_logger.handle()` in `_emit_audit()`. ~15 minutes.
3. **Resolve schema divergence** -- Design decision: match spec field names (`entities_found`, `language_detected`) and semantics (duplicated vs deduplicated entity list), or update spec. Affects all call sites and tests. ~30 minutes implementation + spec update.
4. **Add `operator` field** -- Not trivial as initially assessed. While v1 only uses "replace", the schema must be designed for future multi-operator support (per-entity operators). Design decision needed during spec phase. ~30 minutes including design.
5. **Add optional file output** -- Medium-high. Config setting + `RotatingFileHandler` in `setup_logging()`. Introduces file permission concerns in Docker (containerized paths, volume mounts), concurrency (file locking with multiple workers), and configuration validation. ~2 hours.
6. **Add comprehensive tests** -- Medium. JSONFormatter tests, integration tests with captured log output, edge cases. Note: testing actual JSON output requires careful handling of `caplog` fixture limitations with custom formatters (the `JSONFormatter` attaches `audit_data` to the record, but `caplog` captures the `message` attribute, not the formatted output -- tests must capture handler output directly or use a custom approach). ~2-3 hours.
7. **Handle empty `file_type`** -- Trivial. Default to `"unknown"` when extension is empty. ~5 minutes.
8. **Constrain `**extra` kwargs** -- Low. Replace open pattern with explicit parameters or add an allowlist. ~15 minutes.
9. **Documentation** -- Low. Audit log schema reference, configuration docs, log integrity limitations. ~30 minutes.

Total estimated effort: **Medium feature** -- the core flow exists but bug fixes, schema decisions, file output, and comprehensive testing represent meaningful remaining work.
