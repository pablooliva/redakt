# SPEC-006-audit-logging

## Executive Summary

- **Based on Research:** RESEARCH-006-audit-logging.md
- **Creation Date:** 2026-03-29
- **Status:** Draft

## Research Foundation

### Production Issues Addressed
1. **Duplicate handler accumulation bug** -- `setup_logging()` appends a new `StreamHandler` on every invocation without checking for existing handlers. With `reload=True` in the Dockerfile, each reload triggers the lifespan context manager, calling `setup_logging()` again. After N reloads, each audit event is emitted N times to stdout, corrupting audit log integrity.
2. **No defensive error handling around audit emission** -- `_emit_audit()` calls `audit_logger.handle(record)` without try/except. If the handler raises (broken pipe, full disk on future file handler, formatter bug), the exception propagates up and the endpoint returns a 500 error -- even though detection/anonymization succeeded. The user loses the result.
3. **Schema divergence between spec and implementation** -- The feature spec uses `entities_found` (with duplicates) and `language_detected`; the implementation uses `entity_types` (deduplicated, sorted) and `language`. This inconsistency affects compliance downstream consumers.
4. **Missing `operator` field** -- The spec example includes `"operator": "replace"` but it is not logged. While v1 only uses "replace", the field should be present for schema completeness and future multi-operator support.
5. **No file-based output or log rotation** -- The spec requires "optionally to a file" but no file handler, config setting, or rotation is implemented.
6. **Significant test coverage gaps** -- No tests for `JSONFormatter` output structure, `setup_logging()` configuration, `_emit_audit()` directly, error/failure path audit behavior, or timestamp format.
7. **Open `**extra` kwargs is a schema integrity risk** -- Any caller can pass arbitrary fields through `_emit_audit(**extra)`, including PII-containing fields. No allowlist constrains permitted keys.
8. **Empty `file_type` in document upload audit** -- When no filename is provided, `file_type` is an empty string. Should default to `"unknown"`.

### Stakeholder Validation
- **Product/Compliance team:** Audit logging provides a GDPR Article 30 compliance trail. Primary consumer is a compliance officer who needs to demonstrate anonymization activity. They need: actions taken, entity counts/types, source (web UI vs API). Original text must never appear in logs.
- **Engineering team:** Core flow exists (every request type is logged with metadata, JSON format, stdout). Gaps are bug fixes, schema alignment, file output, error handling, and comprehensive testing.
- **Support team:** No request ID or user identifier for correlation. Acceptable for v1 without auth. Schema should be extensible for future user tracking.
- **Infrastructure/DevOps team:** Stdout-only approach relies on Docker log driver (`json-file` default). No `logging:` configuration in `docker-compose.yml`. File-based logging provides a deployment-independent alternative.
- **Legal/DPO perspective:** Metadata-only approach is sound for PII avoidance. v1 has no tamper-detection mechanism (no signing, no sequence numbers, no hash chain). This must be documented as a known limitation for the DPO.
- **QA/Testing perspective:** Testing JSON output requires bypassing `caplog` limitations (it captures `message`, not formatted output). Tests must capture handler output directly or inspect `record.audit_data`.

### System Integration Points
1. `src/redakt/services/audit.py` -- Core audit service: `JSONFormatter`, `setup_logging()`, `_emit_audit()`, three public log functions
2. `src/redakt/main.py:39` -- `setup_logging()` call in lifespan startup
3. `src/redakt/config.py:21` -- `log_level` setting (default "WARNING")
4. `src/redakt/log_config.py` -- Uvicorn log config, `HealthCheckFilter` (audit logger is separate)
5. `src/redakt/routers/detect.py:144-151` -- `log_detection()` call after successful detection
6. `src/redakt/routers/anonymize.py:138-145` -- `log_anonymization()` call after successful anonymization
7. `src/redakt/routers/documents.py:138-150` -- `log_document_upload()` call after successful document processing
8. `src/redakt/routers/pages.py:77-83, 147-153, 258-266` -- Web UI audit calls (hardcoded `source="web_ui"`)
9. `docker-compose.yml` -- No logging driver configuration (uses default `json-file`)
10. `Dockerfile` -- CMD runs uvicorn with `reload=True` and `UVICORN_LOG_CONFIG`

## Intent

### Problem Statement
The audit logging service is ~60-65% complete by checklist, ~50-60% by effort. The core flow works (every request type is logged to stdout with JSON metadata), but several bugs, missing features, and test gaps undermine its reliability and compliance value:

1. A handler accumulation bug causes duplicate log entries during development reloads
2. Audit failures crash the request instead of being swallowed (the user's processed result is lost)
3. The log schema diverges from the spec (field names, deduplication behavior)
4. No file-based output exists despite the spec requiring it
5. The `operator` field is missing from the schema
6. No tests validate the actual JSON output format or audit behavior on error paths
7. The open `**extra` kwargs pattern allows unconstrained field injection

### Solution Approach
1. Fix the duplicate handler bug with a handler guard in `setup_logging()`
2. Wrap audit emission in defensive try/except, logging failures to the app logger
3. Align the schema with the spec: rename fields to `entities_found` and `language_detected`, add `operator` field (entities list remains deduplicated -- see REQ-004)
4. Add optional file-based output via `REDAKT_AUDIT_LOG_FILE` env var with `RotatingFileHandler`
5. Replace open `**extra` kwargs with explicit keyword parameters
6. Default empty `file_type` to `"unknown"`
7. Add comprehensive unit and integration tests covering JSON output structure, error paths, setup behavior, and all edge cases

### Expected Outcomes
- Audit log entries are emitted exactly once per request, even during development reloads
- Audit failures never crash the user's request; failures are logged to the app logger for investigation
- The JSON schema matches the feature spec (field names, semantics, all required fields present)
- File-based output is configurable and includes log rotation
- Comprehensive test coverage validates the entire audit pipeline: call site -> `_emit_audit()` -> `JSONFormatter` -> JSON output
- The `**extra` kwargs injection risk is eliminated

## Success Criteria

### Functional Requirements

- **REQ-001:** `setup_logging()` guards against duplicate handler accumulation. If `audit_logger.handlers` is non-empty, existing handlers are **closed** (via `handler.close()`) and then removed before adding new handlers. Python's `Logger.handlers.clear()` does NOT close handlers -- it only removes them from the list, leaking file descriptors. The implementation must iterate over existing handlers, call `handler.close()` on each, then clear the list. After N calls to `setup_logging()`, the audit logger has exactly one handler (or two if file output is configured).
- **REQ-002:** `_emit_audit()` wraps `audit_logger.handle(record)` in a try/except that catches `Exception`, logs the failure to the app logger (`logging.getLogger("redakt")`), and returns silently. Audit failures never propagate to the calling endpoint.
- **REQ-003:** The audit log JSON output uses field name `entities_found` (not `entity_types`) and `language_detected` (not `language`), matching the feature spec example at `docs/v1-feature-spec.md:219-229`. The rename applies to: (a) the JSON output keys in `_emit_audit()`'s `audit_data` dict, and (b) the `_emit_audit()` function signature parameter names (for clarity). The rename does NOT apply to `DetectionResult`, `AnonymizationResult`, or other intermediate data structures -- those retain their existing attribute names (`entity_types`, `language`) since they serve the API response path, not the audit path.
- **REQ-004:** The `entities_found` field contains a **deduplicated, sorted** list of unique entity type names (e.g., `["EMAIL_ADDRESS", "PERSON"]`). This is a practical decision driven by the architecture: the anonymize and document processing pipelines only expose deduplicated entity type lists at their audit call sites (`AnonymizationResult.entity_types`, `process_document()` result dict `entity_types`). Propagating non-deduplicated lists would require invasive changes to `anonymize_entities()` return type and `process_document()` return dict -- shared functions used by multiple code paths -- creating risk of tuple unpacking errors at all callers. The `entity_count` field provides total occurrence information. The feature spec example at `docs/v1-feature-spec.md:219-229` shows duplicates, but this is updated to match the implementable reality. No changes to `anonymize_entities()`, `process_document()`, `AnonymizationResult`, or `DetectionResult` are needed for this field.
- **REQ-005:** Every audit log entry for the `anonymize` action includes an `operator` field. For v1, this is always `"replace"`, **hardcoded at each call site** (not derived from processing results -- the operator is not returned by `anonymize_entities()` or `process_document()`). The field is a string (not a list), since v1 uses a single operator per request. The schema is designed so that when multiple operators are supported per-entity in the future, a new `operators` (plural) field can be introduced alongside it.
- **REQ-006:** When `REDAKT_AUDIT_LOG_FILE` is set (non-empty string), `setup_logging()` adds a `RotatingFileHandler` to the audit logger in addition to the stdout `StreamHandler`. Both handlers use the same `JSONFormatter`. The `setup_logging()` signature is extended with explicit parameters: `setup_logging(log_level: str = "WARNING", audit_log_file: str = "", audit_log_max_bytes: int = 10_485_760, audit_log_backup_count: int = 5)`. Individual parameters (not the `settings` object) are used to keep the function testable without coupling to the Settings class. The call in `main.py` passes the values from `settings`.
- **REQ-007:** When `REDAKT_AUDIT_LOG_FILE` is set, `REDAKT_AUDIT_LOG_MAX_BYTES` controls the max file size before rotation (default: 10MB / 10485760 bytes) and `REDAKT_AUDIT_LOG_BACKUP_COUNT` controls the number of rotated backup files to keep (default: 5).
- **REQ-008:** The `**extra` kwargs parameter in `_emit_audit()` is replaced with explicit keyword parameters: `file_type: str | None = None` and `file_size_bytes: int | None = None`. No open-ended kwargs pattern. Only non-None values are included in the audit data dict.
- **REQ-009:** When `file_type` is an empty string (from documents with no filename/extension), it is defaulted to `"unknown"` before being included in the audit data.
- **REQ-010:** The `detect` action audit entry does NOT include an `operator` field (detection does not use an operator).
- **REQ-011:** The `document_upload` action audit entry includes the `operator` field (hardcoded `"replace"`, same as `anonymize`), plus `file_type` and `file_size_bytes`. The `operator` field is always `"replace"` even for early-return paths in `process_document()` (e.g., empty documents with no text chunks), because the intended operation was anonymization regardless of whether entities were found.
- **REQ-012:** All audit log entries include `timestamp` (UTC ISO 8601), `level` ("INFO"), `logger` ("redakt.audit"), `action`, `entity_count`, `entities_found`, `language_detected`, `source`. The `allow_list_count` field is included when present and > 0 (existing behavior, no change). **`entity_count` semantics vary by action and this is by design:** for `detect`, it is the total number of Presidio entity matches (all occurrences); for `anonymize` and `document_upload`, it is the number of unique placeholder mappings (i.e., `len(mappings)`). This means if "John Smith" appears 3 times, detect logs `entity_count: 3` while anonymize logs `entity_count: 1` (one mapping `<PERSON_1>: John Smith`). This difference is inherent to the processing model and is documented here for log consumers.
- **REQ-015:** The `allow_list_count` behavior in the `document_upload` path is unchanged. `process_document()` returns `allow_list_count` in the result dict, which the call site passes through to `log_document_upload()`. This is existing behavior preserved by this spec.
- **REQ-016:** The `language_confidence` field is intentionally excluded from the audit log schema. The audit log's `language_detected` field logs the resolved language code but does not distinguish between auto-detected and manually specified languages. This is a known v1 limitation -- a compliance officer cannot tell from the audit log alone whether `language_detected: "en"` was auto-detected or manually set. Adding `language_confidence` (which is `None` for manual override) would address this, but is deferred to post-v1 to keep the audit schema minimal.
- **REQ-013:** The `source` field values remain `"web_ui"` (from pages.py hardcoded value) and `"api"` (from HX-Request header absence in API routes). The spoofability of the HX-Request header is a documented known limitation for v1. This limitation, along with SEC-004's log integrity limitation, must be documented as code comments in `audit.py` (module-level docstring section "Known v1 Limitations") so they are discoverable by developers. Compliance-facing documentation of these limitations is deferred to post-v1 deployment docs.
- **REQ-014:** New configuration settings are added to `src/redakt/config.py`: `audit_log_file: str = ""` (empty = disabled), `audit_log_max_bytes: int = 10_485_760`, `audit_log_backup_count: int = 5`. All use the `REDAKT_` env prefix.

### Non-Functional Requirements

- **PERF-001:** Audit emission must not introduce perceptible request latency. Stdout logging (pipe write) is inherently fast. File-based logging adds marginal I/O overhead but is acceptable for v1 volumes. No specific timing thresholds are mandated -- the actual latency depends on system load, Docker log driver, and disk speed, making fixed thresholds unverifiable without dedicated benchmarking infrastructure. For v1 with stdout + optional file, synchronous logging is acceptable. If future profiling identifies blocking as an issue, migration to `QueueHandler`/`QueueListener` is the recommended path (documented as a v1 limitation, not implemented now).
- **PERF-002:** Log rotation (when file output is enabled) is handled by Python's `RotatingFileHandler`, which performs the rotation synchronously during the write that exceeds `maxBytes`. This is a brief blocking operation (file rename + open) that is acceptable for v1 log volumes.
- **SEC-001:** Audit log entries never contain PII, original text, filenames, anonymization mappings, or allow list term values. Only metadata fields as defined in REQ-012. This invariant must be preserved in all future field additions.
- **SEC-002:** The `**extra` kwargs injection vector is eliminated by REQ-008. No open-ended field addition is possible through the audit API.
- **SEC-003:** Error messages logged by the defensive try/except (REQ-002) must not contain PII. The exception message and type are logged, but not the audit data dict (which is safe metadata, but logging it in the error path could mask bugs). Log the exception type and message only.
- **SEC-004:** Log integrity limitation is documented: v1 has no tamper-detection, signing, sequence numbers, or hash chain. Audit entries are plain JSON lines. This is explicitly communicated as a known v1 limitation in the `audit.py` module-level docstring (see REQ-013 for documentation location).
- **UX-001:** No user-facing UI changes. Audit logging is a backend/infrastructure concern. No log viewer for v1 -- Docker log access (`docker logs redakt | jq`) is sufficient.

## Edge Cases (Research-Backed)

- **EDGE-001: Duplicate audit entries from handler accumulation**
  - Research reference: "BUG: Duplicate Handler Accumulation on Reload" section
  - Current behavior: After N uvicorn reloads (development with `reload=True`), each audit event is emitted N times.
  - Desired behavior: Exactly one emission per audit event, regardless of how many times `setup_logging()` has been called.
  - Test approach: Unit test calling `setup_logging()` three times, then emitting one audit event, and verifying exactly one handler exists and one log line is produced.

- **EDGE-002: Audit failure during stdout write**
  - Research reference: "Error Handling in Audit Emission" section
  - Current behavior: Exception propagates to the endpoint, returning 500 to the client.
  - Desired behavior: Exception is caught, logged to the app logger, and the request completes normally with its processed result.
  - Test approach: Unit test mocking `audit_logger.handle()` to raise `OSError`, verifying the calling function does not raise and the app logger receives the error.

- **EDGE-003: Empty text requests**
  - Research reference: "Empty text requests" edge case #3
  - Current behavior: Audit log IS called for empty text, with `entity_count=0` and `entity_types=[]`. Consistent across API and web UI.
  - Desired behavior: No change. `entity_count=0` and `entities_found=[]` (renamed field) is correct.
  - Test approach: Integration test submitting empty text, verifying audit log contains `entity_count: 0, entities_found: []`.

- **EDGE-004: Large entity types list**
  - Research reference: "Large entity_types lists" edge case #4
  - Current behavior: All entity types logged without truncation.
  - Desired behavior: No change. All types must be logged for compliance. No truncation.
  - Test approach: Unit test with 20+ entity types, verifying all appear in the JSON output.

- **EDGE-005: Empty `file_type` in document upload**
  - Research reference: "`file_type` can be empty string" edge case #6 (second)
  - Current behavior: `file_type` is `""` when no filename is provided.
  - Desired behavior: Default to `"unknown"` when `file_type` is empty string after stripping.
  - Test approach: Unit test calling `log_document_upload(file_type="", ...)` and verifying the audit data contains `"file_type": "unknown"`.

- **EDGE-006: Schema field rename backward compatibility**
  - Research reference: "Schema Divergence from Feature Spec" section
  - Current behavior: Fields are `entity_types` and `language`.
  - Desired behavior: Fields are `entities_found` and `language_detected`. Since there is no production deployment yet, this is a clean rename with no backward compatibility concerns.
  - Test approach: Integration test verifying the JSON output contains `entities_found` and `language_detected` (not the old names).

- **EDGE-007: `entities_found` is deduplicated and sorted**
  - Research reference: "Schema Divergence from Feature Spec" section, deduplication analysis
  - Current behavior: `entity_types` is `sorted(set(...))` -- deduplicated and sorted.
  - Desired behavior: `entities_found` remains deduplicated and sorted (e.g., `["EMAIL_ADDRESS", "PERSON"]`). The feature spec example showing duplicates is not implemented because the anonymize and document processing pipelines only expose deduplicated lists at their audit call sites, and propagating non-deduplicated lists would require invasive changes to shared upstream functions. The `entity_count` field provides occurrence count information.
  - Test approach: Integration test with text containing two PERSON entities and one EMAIL_ADDRESS, verifying `entities_found` contains `["EMAIL_ADDRESS", "PERSON"]` (sorted, deduplicated).

- **EDGE-008: Concurrent requests produce isolated log entries**
  - Research reference: "Concurrent requests" edge case #5
  - Current behavior: Python's `logging` module is thread-safe. Each `makeRecord()` + `handle()` call is atomic at the handler level.
  - Desired behavior: No change needed. Each request produces its own distinct log entry.
  - Test approach: Integration test sending 5 concurrent requests and verifying 5 distinct log entries (non-interleaved JSON lines).

- **EDGE-009: File output path does not exist**
  - Research reference: "Optional file output" gap analysis
  - Current behavior: No file output.
  - Desired behavior: If `REDAKT_AUDIT_LOG_FILE` is set to a path whose parent directory does not exist, `setup_logging()` logs a warning to the app logger and skips the file handler (stdout handler still works). The application does not crash.
  - Test approach: Unit test setting `audit_log_file` to `/nonexistent/path/audit.log`, verifying a warning is logged and only the stdout handler is added.

- **EDGE-010: File output path is not writable**
  - Research reference: "Optional file output" gap analysis
  - Current behavior: No file output.
  - Desired behavior: Same as EDGE-009 -- log warning, skip file handler, continue with stdout.
  - Test approach: Unit test with a read-only path, verifying graceful degradation.

- **EDGE-011: `operator` field absent for detect action**
  - Research reference: "operator used" field gap
  - Current behavior: No `operator` field for any action.
  - Desired behavior: `operator` field only present for `anonymize` and `document_upload` actions, not for `detect`.
  - Test approach: Unit test verifying `detect` action audit data does not contain `operator` key, while `anonymize` and `document_upload` do.

- **EDGE-012: `allow_list_count` = 0 vs None**
  - Research reference: Existing behavior in `_emit_audit()` lines 61-62
  - Current behavior: `allow_list_count` is omitted when `None` or `0`.
  - Desired behavior: No change. Only include when present and > 0.
  - Test approach: Unit test verifying `allow_list_count` is absent when `None`, absent when `0`, and present when `3`.

- **EDGE-013: Document with zero text chunks (all chunks empty/whitespace)**
  - Current behavior: `process_document()` returns early with `entity_types: []` and `mappings: {}`. Audit call logs `entity_count=0, entities_found=[]`.
  - Desired behavior: No change. The audit entry correctly reflects that no entities were found. `operator="replace"` is still included (REQ-011).
  - Test approach: Integration test with an empty document, verifying audit entry has `entity_count: 0, entities_found: [], operator: "replace"`.

- **EDGE-014: `setup_logging()` called with file config, then called again without file config**
  - Trigger: Test teardown or configuration change between calls.
  - Desired behavior: The close-then-clear approach in REQ-001 ensures the file handler from the first call is properly closed (file descriptor released), and the second call adds only the stdout handler. The file handler does not persist.
  - Test approach: Unit test calling `setup_logging()` with file config, then again without, verifying exactly 1 handler (stdout only) remains and no file descriptor leak.

## Failure Scenarios

- **FAIL-001: Audit handler raises during emission**
  - Trigger condition: `StreamHandler.emit()` raises `OSError` (broken pipe, full disk) or `JSONFormatter.format()` raises (unexpected record structure).
  - Expected behavior: `_emit_audit()` catches the exception, logs the failure to the app logger (`logging.getLogger("redakt")`) with the exception type and message (no PII), and returns silently.
  - User communication: None. The user receives their processed result normally.
  - Recovery approach: Infrastructure team investigates via app logger output. Audit gap is noted.

- **FAIL-002: File handler fails after successful stdout write**
  - Trigger condition: Stdout handler succeeds but `RotatingFileHandler` raises (disk full, permissions changed).
  - Expected behavior: The exception from the file handler is caught by the same try/except in `_emit_audit()`. The stdout entry was already written (handlers are called in order). The failure is logged to the app logger. Subsequent requests continue to attempt both handlers.
  - User communication: None.
  - Recovery approach: Infrastructure team fixes disk/permissions. Missing file entries are a known gap but stdout entries are intact.

- **FAIL-003: `RotatingFileHandler` rotation failure**
  - Trigger condition: Log file exceeds `maxBytes` but the rotation (rename) fails (e.g., file locked by another process on some OS).
  - Expected behavior: `RotatingFileHandler` internally catches rotation errors and continues writing to the current file. If the write itself fails, it is caught by FAIL-001's try/except.
  - User communication: None.
  - Recovery approach: Monitor file sizes; investigate if rotation is not occurring.

- **FAIL-004: Invalid `REDAKT_AUDIT_LOG_FILE` path at startup**
  - Trigger condition: `REDAKT_AUDIT_LOG_FILE` is set to a path that cannot be opened (non-existent parent directory, no write permission, invalid characters).
  - Expected behavior: `setup_logging()` catches the `OSError`/`PermissionError` from `RotatingFileHandler()` construction, logs a warning to the app logger, and continues with stdout-only. The application starts successfully.
  - User communication: Startup log message visible to administrators: "Audit log file handler could not be created for path '{path}': {error}. Falling back to stdout only."
  - Recovery approach: Administrator corrects the path/permissions and restarts.

- **FAIL-005: Presidio error -- no audit entry**
  - Trigger condition: Presidio is unavailable (503), times out (504), or returns an error (502). The audit log call (placed after successful processing) is never reached.
  - Expected behavior: No audit entry is emitted for failed requests. This is a known v1 limitation.
  - User communication: The user sees the appropriate error (503, 504, etc.).
  - Recovery approach: Failed request auditing is deferred to post-v1. The missing entries represent a compliance gap that should be documented for the DPO.

## Implementation Constraints

### Context Requirements
- Maximum context utilization: <30%
- Essential files for implementation:
  - `src/redakt/services/audit.py` (primary file -- all changes to audit service)
  - `src/redakt/config.py` (add 3 new settings)
  - `src/redakt/main.py` (update `setup_logging()` call to pass file config params)
  - `src/redakt/routers/detect.py` (rename audit call kwargs)
  - `src/redakt/routers/anonymize.py` (rename audit call kwargs, add `operator`)
  - `src/redakt/routers/documents.py` (rename audit call kwargs, add `operator`, fix empty `file_type`)
  - `src/redakt/routers/pages.py` (rename audit call kwargs at 3 call sites, add `operator` for anonymize/document)
- Files that can be delegated to subagents:
  - Test files

### Technical Constraints
1. Python stdlib `logging` only -- no third-party logging libraries (structlog, loguru, etc.). The existing approach with custom `JSONFormatter` is maintained.
2. `RotatingFileHandler` from `logging.handlers` for file-based rotation. No time-based rotation for v1.
3. Synchronous logging is acceptable for v1. `QueueHandler`/`QueueListener` migration is a documented post-v1 optimization.
4. The audit logger level is always `INFO`, regardless of the application `log_level` setting. This is existing behavior and must be preserved.
5. `propagate=False` on the audit logger must be preserved to prevent audit entries from appearing in the application logger.
6. All JSON output must be single-line (one JSON object per line) for compatibility with Docker log drivers and log parsing tools.
7. The `entities_found` field rename requires updating all 6 call sites (3 API routers + 3 web UI handlers in pages.py) to use the new keyword argument name. The existing deduplicated, sorted entity list is passed to both the API response and the audit function -- no separate computation is needed. See REQ-004 for the rationale for keeping the list deduplicated.
8. No changes to the web UI are required. Audit logging is entirely backend/infrastructure.
9. Docker `reload=True` in the Dockerfile is an existing behavior that this spec works around (handler guard) rather than changing. Whether to disable reload in production is a deployment decision outside this spec's scope.

## Validation Strategy

### Automated Testing

**Unit Tests (~15 tests) -- `tests/test_audit.py`:**

1. `test_json_formatter_output_structure` -- Verify JSON output contains exactly `timestamp`, `level`, `logger`, plus audit data fields. No extra fields.
2. `test_json_formatter_timestamp_format` -- Verify `timestamp` is UTC ISO 8601 format (ends with `+00:00` or `Z`).
3. `test_json_formatter_non_audit_record` -- Verify non-audit records (no `audit_data` attribute) produce `message` field instead.
4. `test_setup_logging_handler_guard` -- Call `setup_logging()` 3 times, verify audit logger has exactly 1 handler (stdout only, no file config).
5. `test_setup_logging_handler_guard_with_file` -- Call `setup_logging()` 3 times with file config, verify audit logger has exactly 2 handlers (stdout + file).
6. `test_setup_logging_audit_level_always_info` -- Verify audit logger level is INFO regardless of `log_level` parameter.
7. `test_setup_logging_propagate_false` -- Verify `audit_logger.propagate` is False.
8. `test_emit_audit_defensive_error_handling` -- Mock `audit_logger.handle()` to raise `OSError`, verify no exception propagates and app logger receives the error.
9. `test_emit_audit_entities_found_field_name` -- Call `_emit_audit()` with `["EMAIL_ADDRESS", "PERSON"]`, verify audit data contains `entities_found` key (not `entity_types`).
10. `test_log_detection_no_operator_field` -- Verify detect action audit data does not contain `operator`.
11. `test_log_anonymization_includes_operator` -- Verify anonymize action audit data contains `operator: "replace"`.
12. `test_log_document_upload_file_type_empty_defaults_unknown` -- Call with `file_type=""`, verify `"file_type": "unknown"`.
13. `test_log_document_upload_includes_operator` -- Verify document_upload action includes `operator`.
14. `test_allow_list_count_omitted_when_none` -- Verify `allow_list_count` key absent when None.
15. `test_allow_list_count_omitted_when_zero` -- Verify `allow_list_count` key absent when 0.
16. `test_allow_list_count_present_when_positive` -- Verify `allow_list_count` is included when > 0.
17. `test_setup_logging_file_handler_invalid_path` -- Set file path to non-existent directory, verify warning logged and only stdout handler added.
18. `test_setup_logging_file_handler_rotation_config` -- Verify `RotatingFileHandler` is configured with correct `maxBytes` and `backupCount`.

**Integration Tests (~8 tests) -- existing test files + `tests/test_audit_integration.py`:**

1. `test_detect_audit_json_structure` -- Full request via TestClient, capture log output, verify JSON contains all REQ-012 fields with correct names.
2. `test_anonymize_audit_json_structure` -- Same for anonymize, additionally verify `operator` field present.
3. `test_document_upload_audit_json_structure` -- Same for document upload, verify `file_type`, `file_size_bytes`, `operator`.
4. `test_source_detection_api_route` -- Request without HX-Request header, verify `source: "api"`.
5. `test_source_detection_htmx_header` -- Request with `HX-Request: true`, verify `source: "web_ui"`.
6. `test_entities_found_is_deduplicated` -- Submit text with multiple entities of same type, verify `entities_found` is deduplicated and sorted.
7. `test_audit_not_emitted_on_presidio_error` -- Mock Presidio to return 503, verify no audit log entry.
8. `test_no_pii_in_audit_output` -- Submit text with known PII, capture formatted JSON output, verify no PII values appear.

### Manual Verification
- [ ] `setup_logging()` with `reload=True`: restart uvicorn with reload, verify single log entry per request
- [ ] File-based output: set `REDAKT_AUDIT_LOG_FILE=/tmp/redakt-audit.log`, verify file is created and receives JSON lines
- [ ] Log rotation: set small `REDAKT_AUDIT_LOG_MAX_BYTES` (e.g., 1024), generate enough log entries to trigger rotation, verify rotated files exist
- [ ] Invalid file path: set `REDAKT_AUDIT_LOG_FILE=/nonexistent/audit.log`, verify app starts with warning and stdout logging continues
- [ ] Schema validation: `docker logs redakt | head -5 | jq .` -- verify field names match spec (`entities_found`, `language_detected`, `operator`)
- [ ] Verify no PII in logs: process text with known PII, grep audit log for PII values

### Performance Validation
- [ ] Baseline: verify audit logging does not introduce perceptible request latency (qualitative check -- no fixed threshold; latency varies by system)
- [ ] File output: verify file handler does not noticeably degrade request latency under normal load
- [ ] Concurrent load: send 50 concurrent requests, verify all 50 audit entries are present and well-formed

## Dependencies and Risks

### External Dependencies
- Python stdlib `logging` and `logging.handlers.RotatingFileHandler` -- stable, no version concerns.
- No new third-party dependencies.

### Identified Risks

- **RISK-001: `entities_found` field rename requires updating all 6 call sites** -- The rename from `entity_types` to `entities_found` is a keyword argument rename at all 6 audit call sites. The existing deduplicated entity list is passed as-is (no separate computation needed). Risk of a missed call site causing a runtime error. Mitigation: Search for all `log_detection`, `log_anonymization`, `log_document_upload` call sites. Add integration tests for each. No changes to upstream functions (`anonymize_entities()`, `process_document()`, `AnonymizationResult`, `DetectionResult`) are required, reducing the blast radius.

- **RISK-002: File handler in Docker containers** -- Containerized environments have ephemeral filesystems by default. A file-based audit log written inside the container is lost on restart unless a volume mount is configured. Mitigation: Document that `REDAKT_AUDIT_LOG_FILE` should point to a mounted volume path. Stdout remains the primary output; file output is supplementary.

- **RISK-003: Event loop blocking with file I/O** -- `RotatingFileHandler.emit()` is synchronous and involves file I/O. Under high load or slow disk, this could block the event loop. Mitigation: For v1, this is accepted as a known limitation. The stdout path (fast pipe write) is always present. File handler is optional. Post-v1 mitigation: `QueueHandler`/`QueueListener`.

- **RISK-004: Log rotation creates brief window of incomplete data** -- During rotation, `RotatingFileHandler` renames the current file and creates a new one. A crash during this window could lose the current entry. Mitigation: This is standard Python logging behavior and is acceptable. Critical deployments should ship logs to a centralized store rather than relying on local files.

- **RISK-005: Schema change breaks existing log parsers** -- Renaming `entity_types` -> `entities_found` and `language` -> `language_detected` changes the JSON schema. Mitigation: No production deployment exists yet, so no downstream parsers to break. The change aligns implementation with the published spec.

- **RISK-006: No tamper detection on audit logs (v1 limitation)** -- Documented known limitation. No signing, sequence numbers, or hash chain. Compliance officer cannot cryptographically prove logs have not been modified. Mitigation: Document for DPO. Recommend shipping to immutable log store (CloudWatch, append-only S3, centralized SIEM) in production. Post-v1: consider adding monotonic sequence numbers for gap detection.

- **RISK-007: Log volume for large documents** -- Enterprise deployments processing large documents with many entities will generate audit entries per request. The `entities_found` list (deduplicated) is bounded by the number of distinct entity types Presidio supports (roughly 50), so individual log entry size is bounded. However, high request volume combined with file-based logging could produce substantial log files. Mitigation: `RotatingFileHandler` with configurable max size and backup count limits disk usage. Stdout logs are managed by Docker log driver configuration (out of scope).

## Implementation Notes

### Suggested Approach

**Step 1: Fix duplicate handler bug in `setup_logging()`**
- Close and remove existing handlers before adding new ones. Python's `handlers.clear()` does NOT call `handler.close()`, so iterate explicitly:
  ```python
  for handler in audit_logger.handlers[:]:
      handler.close()
  audit_logger.handlers.clear()
  ```
- This handles both development reloads and any other scenario where `setup_logging()` is called multiple times, including test teardown where a file handler from a previous test must be properly closed.
- Add unit test verifying exactly one handler after multiple calls.

**Step 2: Add defensive error handling in `_emit_audit()`**
- Wrap `audit_logger.handle(record)` in try/except:
  ```python
  try:
      audit_logger.handle(record)
  except Exception:
      logging.getLogger("redakt").warning(
          "Audit log emission failed: %s", exc, exc_info=True
      )
  ```
- The app logger is separate from the audit logger, so this warning goes through normal logging channels.
- Do not log the audit data dict in the error handler (it is safe metadata, but keeping the error handler minimal reduces risk).

**Step 3: Replace `**extra` kwargs with explicit parameters**
- Change `_emit_audit()` signature from `**extra: object` to `file_type: str | None = None, file_size_bytes: int | None = None, operator: str | None = None`.
- In the body, conditionally add each field to `audit_data` only when non-None.
- For `file_type`, default empty string to `"unknown"`: `file_type = file_type or "unknown"` (apply before adding to dict, only when `file_type is not None`).
- Update `log_document_upload()` to pass explicit keyword arguments instead of `**extra`.
- Add `operator` parameter to `log_anonymization()` and `log_document_upload()`.

**Step 4: Rename schema fields**
- In `_emit_audit()`, change `"entity_types"` key to `"entities_found"` and `"language"` key to `"language_detected"`.
- Rename the `_emit_audit()` function signature parameters: `entity_types` -> `entities_found`, `language` -> `language_detected`. Propagate to `log_detection()`, `log_anonymization()`, `log_document_upload()` signatures.
- Update all 6 call sites to pass the renamed keyword arguments (`entities_found=` instead of `entity_types=`, `language_detected=` instead of `language=`).
- The entity list passed to audit functions remains the **existing deduplicated, sorted list** -- the same value used for the API response. No separate computation is needed. See REQ-004 for rationale.
- Do NOT rename attributes on `DetectionResult`, `AnonymizationResult`, or keys in the `process_document()` return dict. Those serve the API response path and are unchanged.

**Step 5: Add file-based output configuration**
- Add three settings to `config.py`:
  ```python
  audit_log_file: str = ""
  audit_log_max_bytes: int = 10_485_760  # 10MB
  audit_log_backup_count: int = 5
  ```
- In `setup_logging()`, after adding the stdout handler, check if `settings.audit_log_file` is non-empty:
  ```python
  if settings.audit_log_file:
      try:
          file_handler = RotatingFileHandler(
              settings.audit_log_file,
              maxBytes=settings.audit_log_max_bytes,
              backupCount=settings.audit_log_backup_count,
          )
          file_handler.setFormatter(JSONFormatter())
          audit_logger.addHandler(file_handler)
      except (OSError, PermissionError) as exc:
          logging.getLogger("redakt").warning(
              "Audit log file handler could not be created for path '%s': %s. "
              "Falling back to stdout only.",
              settings.audit_log_file, exc,
          )
  ```
- Update `setup_logging()` signature to accept explicit parameters (not the `settings` object, for testability): `setup_logging(log_level: str = "WARNING", audit_log_file: str = "", audit_log_max_bytes: int = 10_485_760, audit_log_backup_count: int = 5)`. Update the call in `main.py` to pass `settings.audit_log_file`, `settings.audit_log_max_bytes`, `settings.audit_log_backup_count`.

**Step 6: Update call sites for renamed fields and `operator`**

API routers (`detect.py`, `anonymize.py`, `documents.py`):
- Rename keyword arguments: `entity_types=` -> `entities_found=`, `language=` -> `language_detected=`.
- The existing deduplicated entity list is passed as-is (no separate computation needed).
- For `anonymize.py` and `documents.py`, add `operator="replace"` (hardcoded) to the audit function call.

Web UI handlers (`pages.py`):
- Same rename of keyword arguments at all 3 call sites.
- Add `operator="replace"` (hardcoded) for anonymize and document upload audit calls.

No changes to `anonymize_entities()`, `process_document()`, `AnonymizationResult`, or `DetectionResult` are required.

**Step 7: Add comprehensive tests**
- Create `tests/test_audit.py` for unit tests (JSONFormatter, setup_logging, _emit_audit, log_* wrappers).
- Create `tests/test_audit_integration.py` for integration tests (full request -> audit JSON validation).
- Update existing tests in `test_detect.py`, `test_anonymize_api.py`, `test_documents_api.py` if they assert on audit field names.

### Audit Log JSON Schema (post-implementation)

**Detect action:**
```json
{
  "timestamp": "2026-03-29T15:30:00+00:00",
  "level": "INFO",
  "logger": "redakt.audit",
  "action": "detect",
  "entity_count": 3,
  "entities_found": ["EMAIL_ADDRESS", "PERSON"],
  "language_detected": "en",
  "source": "api"
}
```
Note: `entity_count` is 3 (total Presidio matches), `entities_found` is deduplicated (2 unique types).

**Anonymize action:**
```json
{
  "timestamp": "2026-03-29T15:30:00+00:00",
  "level": "INFO",
  "logger": "redakt.audit",
  "action": "anonymize",
  "entity_count": 2,
  "entities_found": ["EMAIL_ADDRESS", "PERSON"],
  "language_detected": "en",
  "source": "web_ui",
  "operator": "replace",
  "allow_list_count": 2
}
```
Note: `entity_count` is 2 (unique placeholder mappings, e.g., `<PERSON_1>` and `<EMAIL_ADDRESS_1>`), not total occurrences. See REQ-012 for semantic details.

**Document upload action:**
```json
{
  "timestamp": "2026-03-29T15:30:00+00:00",
  "level": "INFO",
  "logger": "redakt.audit",
  "action": "document_upload",
  "entity_count": 3,
  "entities_found": ["EMAIL_ADDRESS", "LOCATION", "PERSON"],
  "language_detected": "de",
  "source": "api",
  "operator": "replace",
  "file_type": "xlsx",
  "file_size_bytes": 102400
}
```
Note: `entity_count` is unique placeholder mappings (same semantics as anonymize).

### Files to Create
1. `tests/test_audit.py` -- Unit tests for audit service (JSONFormatter, setup_logging, _emit_audit, log_* wrappers)
2. `tests/test_audit_integration.py` -- Integration tests (full request -> audit JSON validation)

### Files to Modify
1. `src/redakt/services/audit.py` -- All audit service changes (handler close+clear bug fix, error handling, schema rename, explicit params, file output, known-limitations docstring)
2. `src/redakt/config.py` -- Add `audit_log_file`, `audit_log_max_bytes`, `audit_log_backup_count`
3. `src/redakt/main.py` -- Update `setup_logging()` call to pass new file config parameters from settings
4. `src/redakt/routers/detect.py` -- Rename audit call kwargs: `entity_types=` -> `entities_found=`, `language=` -> `language_detected=`
5. `src/redakt/routers/anonymize.py` -- Rename audit call kwargs, add `operator="replace"`
6. `src/redakt/routers/documents.py` -- Rename audit call kwargs, add `operator="replace"`, fix empty `file_type` (default to `"unknown"`)
7. `src/redakt/routers/pages.py` -- Rename audit call kwargs at 3 call sites, add `operator="replace"` for anonymize/document
8. `tests/test_detect.py` -- Update mock assertions: `entity_types=` -> `entities_found=`, `language=` -> `language_detected=`
9. `tests/test_anonymize_api.py` -- Update mock assertions: rename kwargs + add `operator="replace"` assertion
10. `tests/test_documents_api.py` -- Update mock assertions: rename kwargs + add `operator="replace"` assertion
11. `tests/test_allow_list_web.py` -- Update audit assertions: rename any `entity_types`/`language` references to new names

**Files NOT modified** (explicitly excluded -- no upstream changes needed):
- `src/redakt/services/anonymizer.py` -- `anonymize_entities()` return type unchanged
- `src/redakt/services/document_processor.py` -- `process_document()` return dict unchanged

### Critical Implementation Considerations

1. **API response contract is unchanged.** The `entities_found` rename is for the audit log schema only. The API response fields (e.g., `entities_found` in the detect response) already use this name per the feature spec. The audit log field is being aligned to match. Do not confuse audit log fields with API response fields -- they are separate.

2. **Entity list is the same for audit and response.** The existing deduplicated, sorted entity type list is used for both the API response and the audit log. No separate computation is needed at call sites. This simplifies implementation and avoids invasive changes to upstream functions.

3. **`setup_logging()` must be idempotent.** Closing then clearing handlers and re-adding ensures clean state regardless of how many times it is called. The close-then-clear approach is preferred over `if not handlers:` because it also handles cases where handlers exist from a previous configuration, and it properly releases file descriptors from any `RotatingFileHandler`.

4. **File handler creation must not block startup.** All file I/O errors during handler creation are caught and logged as warnings. The application always starts, even with a misconfigured file path.

5. **`operator` field design for future extensibility.** v1 uses `"operator": "replace"` (string). When multiple operators per entity are supported, options are: (a) change to `"operators": ["replace", "mask"]` (new plural field, deprecate singular), or (b) change to per-entity breakdown `"entities": [{"type": "PERSON", "operator": "replace"}, ...]`. This spec uses option (a) implicitly -- a string field that can later be supplemented with a list field. No breaking change needed now.

6. **Testing the formatted JSON output.** Use a `StringIO` buffer attached as a handler (instead of `caplog`) to capture the actual formatted JSON:
   ```python
   import io
   buffer = io.StringIO()
   handler = logging.StreamHandler(buffer)
   handler.setFormatter(JSONFormatter())
   audit_logger.addHandler(handler)
   # ... emit audit ...
   output = buffer.getvalue()
   data = json.loads(output)
   ```
   This tests the full pipeline: `_emit_audit()` -> `JSONFormatter.format()` -> JSON string.

7. **Existing test updates.** Current tests mock `log_detection` etc. and verify kwargs. These tests need: (a) updated keyword argument names in mock assertions (`entities_found` instead of `entity_types`, `language_detected` instead of `language`), (b) new assertions for `operator="replace"` in anonymize and document upload test mocks. Specifically: `test_detect.py` mock assertions change `entity_types=` to `entities_found=` and `language=` to `language_detected=`; `test_anonymize_api.py` adds `operator="replace"` assertion; `test_documents_api.py` adds `operator="replace"` assertion; `test_allow_list_web.py` updates any audit field name references.
