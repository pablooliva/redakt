# PROMPT-004: Language Auto-Detection with Manual Override

- **Feature:** Language Auto-Detection with Manual Override
- **Spec:** `SDD/requirements/SPEC-004-language-detection.md`
- **Date:** 2026-03-29
- **Status:** COMPLETE

## Implementation Steps

### Step 1: Config changes -- COMPLETE
- Added `language_detection_fallback: str = "en"` to `Settings` in `config.py`
- Env var: `REDAKT_LANGUAGE_DETECTION_FALLBACK`

### Step 2: Language service hardening -- COMPLETE
- Expanded `LINGUA_TO_ISO` and `ISO_TO_LINGUA` to cover en, de, es
- Made `_build_detector()` dynamic: reads `settings.supported_languages`, maps to Lingua enums
- Added `validate_language_config()` for startup validation
- Defined `LanguageDetection(NamedTuple)` with `language: str`, `confidence: float | None`
- Changed `detect_language()` return type to `LanguageDetection`
- Added confidence computation via `compute_language_confidence_values()`
- Replaced all hardcoded `"en"` fallbacks with `settings.language_detection_fallback`
- Separated `asyncio.TimeoutError` (WARNING) from other exceptions (ERROR) with `exc_info=True`
- Added structured log fields: `language_detected`, `language_confidence`, `language_fallback`, `language_fallback_reason`

### Step 3: Model updates -- COMPLETE
- Added `language_confidence: float | None = None` to `DetectResponse`, `AnonymizeResponse`, `DocumentUploadResponse`

### Step 4: Router updates -- COMPLETE
- Updated `detect.py` to unpack `LanguageDetection` from `detect_language()`
- Updated `anonymize.py` same way
- Updated `document_processor.py` -- `detect_document_language()` now returns `(str, float | None)` tuple
- Updated `pages.py` to pass `language_confidence` to templates
- Updated `documents.py` router to pass `language_confidence` to response model
- Updated empty text handling in detect/anonymize to use `settings.language_detection_fallback` instead of `"unknown"`

### Step 5: Startup validation -- COMPLETE
- Added `validate_language_config()` call in FastAPI lifespan handler in `main.py`

### Step 6: Template updates -- COMPLETE
- Added confidence label display to all three result partials
- Labels: High (>= 0.8), Medium (>= 0.5), Low (< 0.5), None (0.0)
- Confidence indicator omitted entirely when null (manual override)

### Step 7: Unit tests -- COMPLETE
- 25 tests in `test_language.py` covering:
  - Basic detection (English, German)
  - Tuple unpacking
  - Configurable fallback for empty text, timeout, exception
  - Confidence scores
  - Dynamic detector build from settings
  - Startup validation (valid, unsupported code, fallback not in supported)
  - Exception handling logging
  - Representative enterprise content (German legal, English business)

### Step 8: Integration tests -- COMPLETE
- Added `language_confidence` field assertions in `test_detect.py`, `test_anonymize_api.py`, `test_documents_api.py`
- Auto-detect returns non-null confidence
- Manual override returns null confidence
- Empty text returns null confidence

### Step 9: E2E tests -- COMPLETE
- Created `tests/e2e/test_language_e2e.py` with 8 tests covering:
  - Auto radio default on all 3 pages
  - Confidence label shown for auto-detect
  - Manual override respected (language_detected shows override value)
  - Manual override hides confidence label

## Files Modified
1. `src/redakt/config.py` -- Added `language_detection_fallback` setting
2. `src/redakt/services/language.py` -- Rewritten: dynamic detector, LanguageDetection NamedTuple, confidence, configurable fallback, improved logging, validate_language_config()
3. `src/redakt/models/detect.py` -- Added `language_confidence` field
4. `src/redakt/models/anonymize.py` -- Added `language_confidence` field
5. `src/redakt/models/document.py` -- Added `language_confidence` field
6. `src/redakt/routers/detect.py` -- Updated for LanguageDetection return type, language_confidence in result/response
7. `src/redakt/routers/anonymize.py` -- Same as detect
8. `src/redakt/routers/documents.py` -- Pass language_confidence to response model
9. `src/redakt/routers/pages.py` -- Pass language_confidence to templates
10. `src/redakt/services/document_processor.py` -- detect_document_language returns (str, float | None), language_confidence threaded through all reassembly functions
11. `src/redakt/main.py` -- Added validate_language_config() in lifespan
12. `src/redakt/templates/partials/detect_results.html` -- Confidence label
13. `src/redakt/templates/partials/anonymize_results.html` -- Confidence label
14. `src/redakt/templates/partials/document_results.html` -- Confidence label

## Files Created
1. `tests/e2e/test_language_e2e.py` -- 8 E2E tests

## Test Files Updated
1. `tests/conftest.py` -- Mock fixtures return LanguageDetection instead of str
2. `tests/test_language.py` -- Rewritten with 25 tests (was 6)
3. `tests/test_detect.py` -- Added language_confidence assertions
4. `tests/test_anonymize_api.py` -- Added language_confidence assertions
5. `tests/test_documents_api.py` -- Added language_confidence assertions + 2 new tests
6. `tests/test_document_processor.py` -- Updated mock fixtures for LanguageDetection
7. `tests/test_pages.py` -- Updated inline mocks for LanguageDetection

## Test Results
- 213 tests passing (was 189 before SPEC-004)
- 24 new tests added
- 0 failures

## Completion
- **Status:** Complete
- **Completion Date:** 2026-03-29
- **Code Review:** APPROVED (95.5%)
- **Critical Review:** All findings resolved (3 HIGH, 5 MEDIUM, 4 LOW)
- All 17 functional requirements: Complete
- All 3 non-functional requirements (PERF-001, SEC-001, SEC-002): Complete
- All 3 UX requirements (UX-001, UX-002, UX-003): Complete
- All 10 edge cases: Handled
- All 4 failure scenarios: Documented
