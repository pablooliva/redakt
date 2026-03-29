# CRITICAL-IMPL: Language Auto-Detection (SPEC-004)

**Date:** 2026-03-29
**Reviewer:** Adversarial Critical Review
**Scope:** Implementation vs SPEC-004 requirements, technical vulnerabilities, test coverage
**Overall Severity:** MEDIUM -- Implementation is solid on the happy path with several meaningful gaps in edge case handling, spec compliance, and test rigor.

---

## Executive Summary

The SPEC-004 implementation delivers the core language detection hardening: dynamic detector building from config (REQ-001), startup validation (REQ-002/004), configurable fallback (REQ-003), confidence scores in API responses (REQ-005 through REQ-008), and structured logging (SEC-001). The code is well-organized and the NamedTuple return type change (REQ-017) was applied consistently across all callers.

However, the review identified **3 HIGH**, **5 MEDIUM**, and **4 LOW** findings spanning specification violations, a latent bug in the document processor, weak test assertions, and missing test scenarios.

---

## Specification Violations

### FINDING-01: `_build_empty_response` returns `"unknown"` instead of fallback language [HIGH]

**Spec reference:** EDGE-003 -- "The `language_detected` field is set to `settings.language_detection_fallback` (not `"unknown"`, which is not in `supported_languages`)."

**File:** `src/redakt/services/document_processor.py`, lines 319, 336, 356

`_build_empty_response()` hardcodes `"language_detected": "unknown"` in all three branches (xlsx, json, other). The spec explicitly prohibits returning `"unknown"` because it is not in `supported_languages` and is not a valid ISO 639-1 code. This is a direct EDGE-003 violation carried over from pre-SPEC-004 code that was not updated.

**Impact:** Empty documents return an invalid language code in the API response. Downstream consumers that validate `language_detected` against `supported_languages` will break. The `DocumentUploadResponse` Pydantic model has no validation on `language_detected`, so this passes silently.

**Fix:** Replace `"unknown"` with `settings.language_detection_fallback` in all three branches of `_build_empty_response()`.

---

### FINDING-02: REQ-008 field description not documented on model [MEDIUM]

**Spec reference:** REQ-008 -- "The API field description must document this: 'Confidence score for the detected language. For documents, this reflects the sampled portion (first ~5KB), not the full document.'"

**File:** `src/redakt/models/document.py`, line 20

The `language_confidence` field in `DocumentUploadResponse` is declared as `language_confidence: float | None = None` with no `Field(description=...)`. The spec explicitly requires the field description to document the 5KB sampling caveat.

**Impact:** API documentation (OpenAPI/Swagger) does not communicate the sampling limitation. Consumers may incorrectly assume confidence reflects the entire document.

**Fix:** Add `Field(default=None, description="Confidence score for the detected language. For documents, this reflects the sampled portion (first ~5KB), not the full document.")`.

---

### FINDING-03: EDGE-008 GDPR accuracy tests not implemented [MEDIUM]

**Spec reference:** EDGE-008 -- "Before implementation is considered complete, run three empirical tests and record results" (language mismatch PII detection accuracy).

The spec explicitly requires integration tests that submit German text with both correct and incorrect language settings to Presidio and record entity detection recall. These tests require a running Presidio instance and cannot be mocked. No such tests exist in any test file.

**Impact:** The quantified data for the DPO's data protection impact assessment is missing. The spec frames this as a completion criteria, not a nice-to-have.

**Note:** This is understandable since these require live Presidio. They should be added as E2E tests or marked as a tracked follow-up.

---

### FINDING-04: Missing confidence structured log field for successful detection [LOW]

**Spec reference:** SEC-001 -- structured log fields must include `language_fallback_reason` when fallback is true.

**File:** `src/redakt/services/language.py`, lines 94-103

The successful detection log at DEBUG level correctly omits `language_fallback_reason` (since it's not a fallback). However, it also omits `language_fallback: False` is included but there is no `language_fallback_reason` -- this is correct per spec (only required "when fallback is true"). No issue here on closer inspection.

**Revised:** No violation. Withdrawing this finding.

---

## Technical Vulnerabilities

### FINDING-05: `_detect_sync` runs in default executor with no bound on concurrency [MEDIUM]

**File:** `src/redakt/services/language.py`, line 91

`asyncio.get_running_loop().run_in_executor(None, _detect_sync, text)` uses the default thread pool executor. Under high concurrency, this creates unbounded thread usage for language detection. While Lingua's detector is read-only and thread-safe, each call to `compute_language_confidence_values()` performs CPU-intensive n-gram computation. Under load, this could starve the thread pool used by other `run_in_executor` calls in the application.

**Impact:** Under high concurrent load, language detection could exhaust the default thread pool, causing latency spikes for unrelated async operations using the same executor.

**Severity:** MEDIUM (unlikely in enterprise-internal deployment with limited concurrent users, but architecturally unsound).

**Fix:** Consider a dedicated `ThreadPoolExecutor` with a bounded size, or document this as a known scaling limitation.

---

### FINDING-06: `_build_detector` fallback to all mapped languages is a silent degradation [MEDIUM]

**File:** `src/redakt/services/language.py`, lines 62-65

When `supported_languages` contains fewer than 2 entries that map to Lingua languages, `_build_detector()` silently falls back to using ALL languages in `LINGUA_TO_ISO` (en, de, es). This contradicts the fail-fast philosophy of REQ-002.

**Scenario:** If `supported_languages = ["en"]` (a valid config -- startup validation passes since "en" is in `ISO_TO_LINGUA` and can be the fallback), the detector silently includes German and Spanish, which are NOT in `supported_languages`. Auto-detection could then return "de" or "es", which would then fail `supported_languages` validation in the router.

**Impact:** Confusing error path. A single-language deployment would get sporadic 400 errors from the router when Lingua detects a non-supported language, despite the detector being built.

**Fix:** Either (a) add startup validation that `supported_languages` has >= 2 entries, or (b) when < 2 Lingua languages are available, skip auto-detection entirely and always return the single supported language.

---

### FINDING-07: Confidence computation exception in `_detect_sync` logs at WARNING but spec says nothing about this level [LOW]

**File:** `src/redakt/services/language.py`, lines 163-175

When `compute_language_confidence_values()` raises, the code logs at WARNING. The spec (EDGE-006) specifies: "Separate handling for `asyncio.TimeoutError` (WARNING) vs. other exceptions (ERROR)." However, the confidence computation exception is a different case -- it's not a full detection failure. The WARNING level is arguably appropriate, but the spec doesn't explicitly address this sub-case.

**Impact:** Minor. The behavior is reasonable, just not explicitly specified.

---

### FINDING-08: `_build_empty_response` sets `language_confidence` to `None` but only after the caller adds it [HIGH]

**File:** `src/redakt/services/document_processor.py`, lines 218-220

```python
result = _build_empty_response(extension, file_size, extraction, warnings)
result["language_confidence"] = None
```

The `_build_empty_response` function itself does NOT include `language_confidence` in its returned dict. The caller patches it in at line 220. However, this is fragile -- if any other code path calls `_build_empty_response` without this patch, the key would be missing. More critically, combined with FINDING-01, empty documents return `{"language_detected": "unknown", "language_confidence": None}` -- an invalid language with null confidence, which looks like a manual override rather than an empty-document fallback.

**Impact:** Inconsistent response for empty documents. The `language_confidence` should be `None` (no detection attempted) per EDGE-003, which is correct, but `language_detected` being `"unknown"` is wrong (see FINDING-01).

---

## Test Coverage Gaps

### FINDING-09: No test for `_build_empty_response` language value [HIGH]

**Files:** `tests/test_documents_api.py`

`test_empty_file` (line 166) asserts `data["anonymized_content"] == ""` and `data["mappings"] == {}` but does NOT assert `data["language_detected"]` or `data["language_confidence"]`. This means FINDING-01 (returning `"unknown"`) is untested and would not be caught.

**Fix:** Add assertions: `assert data["language_detected"] == "en"` and `assert data["language_confidence"] is None`.

---

### FINDING-10: E2E tests for documents page are minimal [MEDIUM]

**File:** `tests/e2e/test_language_e2e.py`

The `TestDocumentsPageLanguage` class has only one test (`test_auto_radio_selected_by_default`). It is missing:
- Test for auto-detect showing language and confidence after document upload
- Test for manual override on document upload
- Test for manual override hiding confidence on document upload

The detect and anonymize pages each have 3-4 tests, but documents has only 1. This is explicitly required by the spec's Validation Strategy: "Submit with auto, verify confidence label shown in results" and "Override to 'de'/'en', verify `language_detected` shows override."

**Fix:** Add document upload E2E tests that mirror the detect/anonymize page tests.

---

### FINDING-11: `test_exception_logs_at_error_with_exc_info` does not verify `exc_info` [MEDIUM]

**File:** `tests/test_language.py`, lines 182-188

The test verifies that "failed" appears in the log text, but does NOT verify that `exc_info=True` was used (i.e., that a traceback is present). The spec (EDGE-006) explicitly requires `exc_info=True` for exception logging. The test would pass even if `exc_info` were removed.

**Fix:** Assert that the traceback text (e.g., "RuntimeError" or "broken detector") appears in the log output, confirming exc_info was active.

---

### FINDING-12: No test for single-language `supported_languages` behavior [LOW]

No test verifies what happens when `supported_languages` has only one language. This relates to FINDING-06 -- the detector silently falls back to all mapped languages. A test would document and pin the behavior.

---

### FINDING-13: No test for `detect_document_language` with empty chunks [LOW]

**File:** `src/redakt/services/document_processor.py`, lines 150-162

When all chunks are empty (whitespace-only), `detect_document_language` returns `(fallback, None)`. This path is not directly tested -- the closest test (`test_empty_file`) goes through the full `process_document` pipeline and hits `_build_empty_response` before `detect_document_language` is ever called. The `detect_document_language` function's empty-chunks branch is untested in isolation.

---

### FINDING-14: `test_short_ambiguous_text` is brittle [LOW]

**File:** `tests/test_language.py`, line 59

```python
async def test_short_ambiguous_text(self):
    result = await detect_language("123")
    assert result.language == "en"  # Fallback
    assert result.confidence == 0.0  # Fallback confidence
```

This test assumes Lingua returns `None` for "123", triggering the fallback path. If a future Lingua version changes its behavior for numeric-only strings, the test would break for a reason unrelated to Redakt's logic. The test should mock Lingua to return `None` to test the fallback path deterministically, OR should be labeled as a behavior/smoke test rather than a unit test.

---

## Summary of Findings

| # | Finding | Severity | Category |
|---|---------|----------|----------|
| 01 | `_build_empty_response` returns `"unknown"` instead of fallback | HIGH | Spec violation |
| 02 | REQ-008 field description missing on `DocumentUploadResponse` | MEDIUM | Spec violation |
| 03 | EDGE-008 GDPR accuracy tests not implemented | MEDIUM | Spec violation |
| 05 | Unbounded thread pool for `_detect_sync` | MEDIUM | Scalability |
| 06 | Silent detector fallback to all languages when < 2 configured | MEDIUM | Logic bug |
| 07 | Confidence exception log level not specified | LOW | Spec ambiguity |
| 08 | `_build_empty_response` missing `language_confidence` key | HIGH | Fragility |
| 09 | No test for empty document language value | HIGH | Test gap |
| 10 | E2E documents page language tests minimal | MEDIUM | Test gap |
| 11 | `exc_info` not verified in exception log test | MEDIUM | Weak assertion |
| 12 | No test for single-language config behavior | LOW | Test gap |
| 13 | No test for `detect_document_language` empty chunks path | LOW | Test gap |
| 14 | `test_short_ambiguous_text` is brittle | LOW | Test quality |

## Recommended Actions (Priority Order)

1. **Fix FINDING-01 immediately** -- Replace `"unknown"` with `settings.language_detection_fallback` in `_build_empty_response()`. This is a spec violation and a latent bug.
2. **Fix FINDING-08/09 together** -- Move `language_confidence` into `_build_empty_response()` and add test assertions for empty document responses.
3. **Fix FINDING-06** -- Add startup validation requiring >= 2 `supported_languages`, or handle single-language config explicitly.
4. **Add FINDING-10 E2E tests** -- Complete the documents page language E2E tests.
5. **Fix FINDING-11** -- Strengthen the exception logging test assertion.
6. **Add FINDING-02 field description** -- Small change with documentation impact.
7. **Track FINDING-03/05** -- GDPR accuracy tests and thread pool bounding can be follow-up items.

---

## Findings Addressed (2026-03-29)

All actionable findings from this critical review have been resolved:

| # | Finding | Status | Resolution |
|---|---------|--------|------------|
| 01 | `_build_empty_response` returns `"unknown"` | FIXED | Replaced with `settings.language_detection_fallback` in all three branches. |
| 02 | REQ-008 field description missing | FIXED | Added `Field(description="...")` to `DocumentUploadResponse.language_confidence`. |
| 03 | EDGE-008 GDPR accuracy tests | ACCEPTED | Requires live Presidio. Tracked as follow-up. |
| 05 | Unbounded thread pool | ACCEPTED | Documented as known scaling limitation for enterprise-internal deployment. |
| 06 | Silent detector fallback to all languages | FIXED | Added startup validation in `validate_language_config()` requiring >= 2 supported languages with Lingua mappings. Single-language config now raises `ValueError` at startup. |
| 07 | Confidence exception log level | ACCEPTED | WARNING is appropriate for this sub-case (detection succeeded, only confidence failed). |
| 08 | `_build_empty_response` missing `language_confidence` | FIXED | Added `language_confidence: None` to all three branches of `_build_empty_response()`. Removed fragile caller-side patching. |
| 09 | No test for empty document language value | FIXED | Added `language_detected` and `language_confidence` assertions to `test_empty_file` in `tests/test_documents_api.py`. |
| 10 | E2E documents page tests minimal | ACCEPTED | E2E tests require Docker Compose stack. Tracked as follow-up alongside FINDING-03. |
| 11 | `exc_info` not verified in test | FIXED | Added assertions in `test_exception_logs_at_error_with_exc_info` verifying `exc_info` is set and exception type is `RuntimeError`. |
| 12 | No test for single-language config | FIXED | Added `TestSingleLanguageConfig::test_single_language_raises_at_startup` in `tests/test_language.py`. |
| 13 | No test for empty chunks path | FIXED | Added `TestDocumentLanguageDetection::test_empty_chunks_return_fallback` in `tests/test_language.py`. |
| 14 | `test_short_ambiguous_text` brittle | ACCEPTED | Acknowledged as behavior/smoke test. Acceptable for v1 -- documents real Lingua behavior for numeric-only input. |

**Tests:** 213 passed, 0 failed (was 210 before fixes; 3 new tests added).
