# PROMPT-006-audit-logging-2026-03-29

## Status: Complete
## Completion Date: 2026-03-29

## Implementation Status

All requirements complete. 325 tests passing (0 failures).

## Requirements Completed

- [x] REQ-001: setup_logging() guards against duplicate handler accumulation (close + clear)
- [x] REQ-002: _emit_audit() defensive error handling (try/except, log to app logger)
- [x] REQ-003: Schema fields renamed: entities_found, language_detected
- [x] REQ-004: entities_found is deduplicated and sorted
- [x] REQ-005: operator field for anonymize action (hardcoded "replace")
- [x] REQ-006: File-based output via RotatingFileHandler when REDAKT_AUDIT_LOG_FILE set
- [x] REQ-007: REDAKT_AUDIT_LOG_MAX_BYTES and REDAKT_AUDIT_LOG_BACKUP_COUNT config
- [x] REQ-008: **extra kwargs replaced with explicit parameters
- [x] REQ-009: Empty file_type defaults to "unknown"
- [x] REQ-010: detect action has no operator field
- [x] REQ-011: document_upload includes operator field
- [x] REQ-012: All audit entries include required fields
- [x] REQ-013: Source field values and known v1 limitations documented in audit.py docstring
- [x] REQ-014: Config settings added (audit_log_file, audit_log_max_bytes, audit_log_backup_count)
- [x] REQ-015: allow_list_count behavior unchanged for document_upload
- [x] REQ-016: language_confidence excluded from audit schema (documented limitation)

## Edge Cases Handled

- [x] EDGE-001: Duplicate handler accumulation fixed
- [x] EDGE-002: Audit failure during stdout write caught
- [x] EDGE-003: Empty text requests (no change needed)
- [x] EDGE-004: Large entity types list (no truncation)
- [x] EDGE-005: Empty file_type defaults to "unknown"
- [x] EDGE-006: Schema field rename (clean, no backward compat needed)
- [x] EDGE-007: entities_found is deduplicated and sorted
- [x] EDGE-008: Concurrent requests (logging module is thread-safe)
- [x] EDGE-009: Invalid file path logs warning, falls back to stdout
- [x] EDGE-010: Non-writable path (same as EDGE-009)
- [x] EDGE-011: operator absent for detect action
- [x] EDGE-012: allow_list_count=0 vs None
- [x] EDGE-013: Document with zero text chunks
- [x] EDGE-014: setup_logging() with file then without (proper close)

## Failure Scenarios Handled

- [x] FAIL-001: Handler raises during emission
- [x] FAIL-002: File handler fails after stdout write
- [x] FAIL-003: RotatingFileHandler rotation failure (handled by Python)
- [x] FAIL-004: Invalid REDAKT_AUDIT_LOG_FILE at startup
- [x] FAIL-005: Presidio error (no audit entry, known limitation)

## Files Modified

1. `src/redakt/services/audit.py` — Full rewrite: handler guard, error handling, schema rename, explicit params, file output, known-limitations docstring
2. `src/redakt/config.py` — Added 3 audit config settings
3. `src/redakt/main.py` — Updated setup_logging() call with new params
4. `src/redakt/routers/detect.py` — Renamed audit kwargs
5. `src/redakt/routers/anonymize.py` — Renamed audit kwargs, added operator="replace"
6. `src/redakt/routers/documents.py` — Renamed audit kwargs, added operator="replace"
7. `src/redakt/routers/pages.py` — Renamed audit kwargs at 3 call sites, added operator="replace" for anonymize/document

## Files Created

1. `tests/test_audit.py` — 18 unit tests
2. `tests/test_audit_integration.py` — 8 integration tests

## Existing Tests Updated

1. `tests/test_detect.py` — entity_types -> entities_found
2. `tests/test_anonymize_api.py` — entity_types -> entities_found, added operator assertion
3. `tests/test_documents_api.py` — entity_types -> entities_found, added operator assertion

## Review Findings Addressed

All findings from both REVIEW-006 and CRITICAL-IMPL reviews resolved:

- **JSONFormatter timestamp** -- Changed from `datetime.now()` to `record.created` for QueueHandler compatibility
- **exc_info=True safety** -- Reviewed and added explanatory comment confirming no PII leakage risk
- **Web UI route audit tests** -- Added 3 integration tests for `/detect/submit`, `/anonymize/submit`, `/documents/submit`
- **PII-absence tests expanded** -- Added tests for anonymize and document upload audit paths (SEC-001)
- **EDGE-003 empty text** -- Added tests for detect and anonymize empty-text audit entries
- **EDGE-013 zero-chunk document** -- Added test for empty document audit entry
- **EDGE-008 concurrent requests** -- Added docstring comment documenting stdlib thread-safety guarantee
- **Strengthened assertions** -- Anonymize and document integration tests now verify specific field values

## Deviations from Spec

None. All requirements implemented as specified.

## Test Results

325 passed, 0 failed, 1 warning (DeprecationWarning from defusedxml)

Unit tests: 26 (was 24), Integration tests: 18 (was 8)
