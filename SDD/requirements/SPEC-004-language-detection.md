# SPEC-004-language-detection

## Executive Summary
- **Based on Research:** RESEARCH-004-language-detection.md
- **Creation Date:** 2026-03-29
- **Status:** Approved

Language auto-detection with manual override is already substantially implemented across Features 1-3. The `lingua-language-detector` library is integrated, all API endpoints accept `"language": "auto"` (default) or explicit ISO 639-1 codes, all web UI pages have auto/en/de radio toggles, and all responses include `language_detected`. This specification formalizes existing behavior as requirements and addresses the gaps identified during research: hardcoded language lists, English fallback bias, silent exception handling, missing confidence scores, and insufficient test coverage. The implementation is a hardening and validation exercise, not new feature development.

## Research Foundation

### Production Issues Addressed
1. **Hardcoded Lingua languages** -- `_build_detector()` hardcodes `Language.ENGLISH, Language.GERMAN` instead of reading from `settings.supported_languages`. Adding a language to config without updating code causes silent misclassification.
2. **English fallback bias** -- Every fallback path in `language.py` returns `"en"`, ignoring `settings.default_language`. German-majority deployments systematically degrade PII detection on fallback.
3. **Silent exception swallowing** -- `language.py:38` catches all exceptions with a generic warning, logging no exception type, message, or traceback. A broken Lingua installation would be invisible in production.
4. **No confidence feedback** -- API responses include `language_detected` but no confidence score. Users and agents cannot assess detection reliability.
5. **Missing test coverage** -- Existing 6 unit tests use trivially simple sentences. No mixed-language tests, no representative enterprise content tests, no E2E toggle tests.

### Stakeholder Validation

| Perspective | Key Requirement |
|---|---|
| Product | Auto-detection must "just work" -- users rarely need to override |
| Engineering | Fix hardcoded coupling, configurable fallback, proper error handling |
| Support | Clear indication of detected language, easy override, ability to retry |
| User (Web) | See detected language in results, simple toggle to override and resubmit |
| User (API/Agent) | `language_detected` and `language_confidence` in response for programmatic decisions |
| DPO/Legal | Wrong language = missed PII = potential GDPR Art. 4(12) incident. Known limitations must be documented for DPIA |
| Operations/SRE | Observability into detection quality -- structured logs for fallback events, confidence distribution |

### System Integration Points

All integration points are already implemented. This spec formalizes and hardens them.

| Component | File(s) | Current Status |
|---|---|---|
| Language service | `src/redakt/services/language.py` | Needs hardening (Gaps 1-3, confidence) |
| Configuration | `src/redakt/config.py:14-19` | Complete -- settings exist but fallback not wired |
| Presidio client | `src/redakt/services/presidio.py:16-23` | Complete -- passes `language` to `/analyze` |
| Detect router | `src/redakt/routers/detect.py:59-69` | Complete -- resolves and validates language |
| Anonymize router | `src/redakt/routers/anonymize.py:51-62` | Complete -- resolves and validates language |
| Document processor | `src/redakt/services/document_processor.py:133-172` | Complete -- per-document 5KB sample detection |
| Web UI toggles | `src/redakt/templates/detect.html`, `anonymize.html`, `documents.html` | Complete |
| Result partials | `src/redakt/templates/partials/detect_results.html`, etc. | Complete -- display `language_detected` |
| API models | `src/redakt/models/detect.py`, `anonymize.py`, `document.py` | Need `language_confidence` field |
| Audit logging | `src/redakt/services/audit.py:56,65,74` | Complete -- `language` parameter logged |
| Page routes | `src/redakt/routers/pages.py:35,92,151` | Complete -- accept `language` form field |

## Intent

### Problem Statement
The language detection infrastructure works for the happy path but has five production-readiness gaps: (1) the Lingua detector is hardcoded to EN+DE, decoupled from the configurable `supported_languages` setting; (2) all fallback paths hardcode English, inappropriate for German-majority deployments; (3) exceptions are swallowed silently with no diagnostic information; (4) API responses lack confidence scores that users and agents need to assess detection reliability; (5) test coverage does not include representative enterprise content or E2E browser tests. These gaps create GDPR compliance risk (wrong language = missed NER-based PII for person names, locations, organizations) and operational blindness (silent failures in production).

### Solution Approach
1. Make `_build_detector()` dynamic -- read `settings.supported_languages`, map ISO codes to Lingua Language enums, build detector from configured languages.
2. Add a configurable `language_detection_fallback` setting and wire it into all fallback paths.
3. Improve exception handling -- log exception details, separate timeout from unexpected errors, add structured log fields for observability.
4. Add `language_confidence` to all API responses and result partials.
5. Add comprehensive tests: unit tests with representative content, integration tests for all language paths, E2E tests for UI toggles.
6. Document mixed-language limitations for users and the DPO.

### Expected Outcomes
- Language detection dynamically supports any language in `settings.supported_languages` without code changes.
- Fallback language is configurable per deployment (German enterprises can set `"de"`).
- Production failures are visible via exception details and structured log fields.
- API consumers receive confidence scores and can programmatically decide whether to trust detection or override.
- Test suite validates language detection with enterprise-representative content.
- GDPR risk from language misdetection is documented and mitigated.

## Success Criteria

### Functional Requirements

- **REQ-001: Dynamic Lingua detector building** -- `_build_detector()` must read `settings.supported_languages`, map each ISO 639-1 code to a Lingua `Language` enum via an expanded `ISO_TO_LINGUA` dict, and build the detector from the resulting language set. The `LINGUA_TO_ISO` and `ISO_TO_LINGUA` mappings must cover all languages that Presidio supports (at minimum: en, de, es).
- **REQ-002: Startup language validation** -- On application startup, validate that every code in `settings.supported_languages` exists in `ISO_TO_LINGUA`. If a code is missing, log an ERROR and raise a clear exception preventing startup (fail-fast). **Mechanism:** Implement as a `validate_language_config()` function in `language.py`, called from the FastAPI lifespan handler in `main.py`. This runs once at startup before the app accepts requests, and does not interfere with test imports (unlike module-level validation).
- **REQ-003: Configurable fallback language** -- Add a `language_detection_fallback` setting to `config.py` (env: `REDAKT_LANGUAGE_DETECTION_FALLBACK`, default: `"en"`). All fallback paths in `language.py` (empty text, timeout, exception, Lingua returns None) must use this setting instead of hardcoded `"en"`.
- **REQ-004: Fallback language validation** -- On startup, validate that `language_detection_fallback` is present in `supported_languages`. If not, log an ERROR and raise. **Mechanism:** Part of the same `validate_language_config()` function called from the FastAPI lifespan handler (see REQ-002).
- **REQ-005: Language confidence in API responses** -- All API responses that include `language_detected` must also include `language_confidence` (float, 0.0-1.0). Use Lingua's `compute_language_confidence_values(text)` for auto-detected text. For explicit language override, `language_confidence` is `null`. For fallback, `language_confidence` is `0.0`. **Timeout behavior:** Both `detect_language_of()` and `compute_language_confidence_values()` run inside `_detect_sync()` within the single shared timeout (PERF-001). If the timeout fires after language detection succeeds but before confidence computation completes, return the detected language with `language_confidence: null` (not `0.0`, since detection did succeed -- `null` signals that confidence is unavailable, while `0.0` signals a fallback). If confidence computation raises an exception but language detection succeeded, same behavior: return language with `confidence: null`.
- **REQ-006: Language confidence in detect response** -- `DetectResponse` model includes `language_confidence: float | None`.
- **REQ-007: Language confidence in anonymize response** -- `AnonymizeResponse` model includes `language_confidence: float | None`.
- **REQ-008: Language confidence in document response** -- `DocumentUploadResponse` model includes `language_confidence: float | None`. **Caveat:** For documents, confidence reflects the language detection of the sampled portion (first chunks up to 5KB per REQ-012), not the full document content. This is a known limitation -- a high confidence score does not guarantee the entire document is in the detected language. The API field description must document this: "Confidence score for the detected language. For documents, this reflects the sampled portion (first ~5KB), not the full document."
- **REQ-009: Auto-detection default** -- All endpoints default to `"language": "auto"` when no language parameter is provided. (Already implemented -- formalized.)
- **REQ-010: Manual override** -- All endpoints accept an explicit ISO 639-1 code. When provided, auto-detection is skipped and the provided language is used directly. (Already implemented -- formalized.)
- **REQ-011: Language validation on all endpoints** -- All endpoints validate the resolved language (whether auto-detected or manually specified) against `settings.supported_languages`. Return HTTP 400 with a message listing supported languages if invalid. (Already implemented -- formalized.)
- **REQ-012: Per-document language detection** -- Document upload endpoint detects language once per document by concatenating the first chunks up to 5KB. All chunks in that document are processed with the same detected language. (Already implemented -- formalized.)
- **REQ-013: Web UI language toggle** -- All three pages (detect, anonymize, documents) display a radio group with "Auto", plus one option per language in `settings.supported_languages`. "Auto" is selected by default. (Currently hardcoded to auto/en/de -- should remain so for v1, with a note that dynamic generation is a post-v1 enhancement.) **Operator note:** Adding languages to `supported_languages` enables API acceptance and auto-detection support for that language, but does NOT add UI radio toggles until the post-v1 dynamic generation enhancement. Web UI users must rely on auto-detection for languages beyond EN/DE, or use the API directly. This limitation must be documented in operator/deployment documentation.
- **REQ-014: Detected language display** -- All result partials display the resolved `language_detected` value. (Already implemented -- formalized.)
- **REQ-015: Confidence display in results** -- All result partials display `language_confidence` when available (auto-detect). Display as a qualitative label mapped from the numeric score: **High** (>= 0.8), **Medium** (>= 0.5), **Low** (< 0.5), **None** (0.0, fallback). Omit the confidence indicator entirely when `null` (manual override). Rationale: Lingua's confidence scores are not calibrated probabilities -- displaying as a percentage (e.g., "92%") would mislead users into interpreting it as a probability of correctness. Qualitative labels convey relative confidence without implying calibration. The raw numeric value remains available in the API response for programmatic consumers.
- **REQ-016: Audit logging includes language** -- All audit log entries include the `language` field with the resolved language code. (Already implemented -- formalized.)
- **REQ-017: detect_language returns confidence** -- `detect_language()` must return a `LanguageDetection` NamedTuple with two fields: `language: str` and `confidence: float | None`. Definition: `class LanguageDetection(NamedTuple): language: str; confidence: float | None`. This provides named field access (`result.language`, `result.confidence`) while also supporting tuple unpacking (`language, confidence = await detect_language(text)`). All callers must be updated to use the new return type.

### Non-Functional Requirements

- **PERF-001: Detection latency** -- Language detection must complete within `settings.language_detection_timeout` (default 2.0s). If exceeded, fall back with confidence `0.0`. The 2.0s timeout has not been empirically profiled against max-size inputs (512KB). It is accepted as-is for v1 based on the rationale that EN/DE binary detection with Lingua's `from_languages()` is fast for typical inputs. If production monitoring (FAIL-003 structured logs) shows elevated fallback rates due to timeouts, the timeout value should be tuned. This is a configurable setting requiring no code changes to adjust.
- **PERF-002: Detector build time** -- The `@lru_cache` on `_build_detector()` means the detector is built once per process lifetime. Build time is not user-facing. No change needed.
- **SEC-001: No PII in language logs** -- Language detection logs must never include the input text. Only the detected language code, confidence score, and fallback reason (if applicable) may be logged. **Structured log fields:** All language detection log entries must include the following structured fields: `language_detected: str` (ISO 639-1 code), `language_confidence: float | None`, `language_fallback: bool`, and (when fallback is true) `language_fallback_reason: str` (one of: `"empty_text"`, `"timeout"`, `"exception"`, `"ambiguous"` [Lingua returned None], `"confidence_unavailable"`).
- **SEC-002: Language parameter injection** -- Language parameter is a short string used only as a key lookup. No injection risk. Validation against `supported_languages` list provides allowlist protection. (Already implemented -- formalized.)
- **UX-001: Zero-configuration experience** -- Default behavior (auto-detect, English fallback) works without any configuration. Users do not need to understand language detection to use Redakt.
- **UX-002: Override discoverability** -- The language toggle is visible on every page before submission, positioned near the main input/upload area.
- **UX-003: Detection transparency** -- After submission, the detected language and confidence are visible in results so users can assess whether to override and retry. **Known UX limitation (v1):** The UI shows the detected language in results but does not pre-fill or update the radio toggle to reflect the detection. The user must manually change the toggle and resubmit to override. Updating the toggle based on detection results is a post-v1 enhancement.

## Edge Cases (Research-Backed)

- **EDGE-001: Mixed EN/DE content (German paragraph with English names)**
  - Research reference: Production Edge Cases > Mixed-Language Content
  - Current behavior: Lingua detects dominant language. English names in German text still caught by Presidio's regex recognizers (email, phone, IBAN) but NER-based recognition (person names, locations, organizations) uses only the dominant language's model.
  - Desired behavior: Same as current (v1 limitation). Document the trade-off. Confidence score signals ambiguity.
  - Test approach: Submit German paragraph with English names, verify PII detection results include expected entities. Note: Do not assert that confidence is strictly lower for mixed content -- Lingua's behavior for German-dominant text with a few English words may still produce high confidence. Instead, verify that a confidence value is returned and that the dominant language is detected correctly.

- **EDGE-002: Short ambiguous text (3-10 words)**
  - Research reference: Production Edge Cases > Short Text
  - Current behavior: Lingua may return `None` due to `minimum_relative_distance(0.25)` threshold. Falls back to hardcoded `"en"`.
  - Desired behavior: Falls back to `settings.language_detection_fallback` with `language_confidence: 0.0`. User sees low/zero confidence and knows to verify.
  - Test approach: Submit "Hans Mueller" and "John Smith" separately, verify fallback and confidence values.

- **EDGE-003: Empty or whitespace-only text**
  - Research reference: Production Edge Cases > Empty / Whitespace Text
  - Current behavior: `detect_language("")` returns `"en"` immediately. Detection endpoints (`detect.py:54-57`) return early with `language="unknown"` before `detect_language()` is called.
  - Desired behavior: Two layers, consistent behavior:
    1. **Router layer**: Detection endpoints continue to short-circuit empty/whitespace text and return early with an empty results response. The `language_detected` field is set to `settings.language_detection_fallback` (not `"unknown"`, which is not in `supported_languages`). `language_confidence` is `null` (no detection attempted).
    2. **Service layer**: `detect_language("")` returns `(settings.language_detection_fallback, None)` for empty/whitespace input. This ensures consistent behavior if any caller bypasses the router short-circuit.
  - Rationale: Returning `"unknown"` bypasses `supported_languages` validation and is not a valid ISO 639-1 code. The fallback language is always valid (validated at startup by REQ-004).
  - Test approach: Submit empty string and whitespace-only string via API, verify `language_detected` equals the configured fallback language and `language_confidence` is `null`.

- **EDGE-004: Unsupported language code**
  - Research reference: Production Edge Cases > Unsupported Language Input
  - Current behavior: HTTP 400 with message listing supported languages.
  - Desired behavior: Same. No change needed.
  - Test approach: Send `"language": "fr"` via API, verify 400 response with supported language list.

- **EDGE-005: Detection timeout**
  - Research reference: Production Edge Cases > Detection Timeout
  - Current behavior: 2-second timeout, falls back to `"en"` with generic warning.
  - Desired behavior: Falls back to `settings.language_detection_fallback` with `language_confidence: 0.0`. Log includes timeout duration and text length (not text content).
  - Test approach: Mock slow detection (sleep > 2s), verify fallback and log output.

- **EDGE-006: Lingua exception (corrupted model, OOM, misconfiguration)**
  - Research reference: Production Edge Cases > Exception Handling Weakness
  - Current behavior: All exceptions caught, generic warning logged, falls back to `"en"`.
  - Desired behavior: Exception type and message logged at ERROR level (not WARNING) with `exc_info=True`. Falls back to `settings.language_detection_fallback` with `language_confidence: 0.0`. Separate handling for `asyncio.TimeoutError` (WARNING) vs. other exceptions (ERROR).
  - Test approach: Mock Lingua to raise `RuntimeError`, verify ERROR log includes exception details and fallback is configurable.

- **EDGE-007: Multi-page document with mixed languages**
  - Research reference: Production Edge Cases > Document Language Detection
  - Current behavior: Concatenates first chunks up to 5KB, detects once. All chunks use same language.
  - Desired behavior: Same (v1 limitation). Documented as known limitation. Post-v1: sample from beginning, middle, and end.
  - Test approach: Create test document where first 5KB is English and remainder is German, verify detection uses first 5KB.

- **EDGE-008: Language mismatch PII detection accuracy (GDPR validation)**
  - Research reference: Presidio Language Support Analysis > Quantification needed; DPO/Legal stakeholder needs
  - Current behavior: Unknown -- no empirical data on PII detection recall under language mismatch.
  - Desired behavior: Before implementation is considered complete, run three empirical tests and record results:
    1. German text with German names analyzed with `language="de"` (baseline recall for PERSON, LOCATION, ORGANIZATION)
    2. Same text analyzed with `language="en"` (mismatch scenario)
    3. English text with English names analyzed with `language="en"` (baseline) vs `language="de"` (mismatch)
  - Purpose: Provides quantified data for the DPO's data protection impact assessment. Documents the actual degradation from language mismatch rather than assuming "partial degradation."
  - Test approach: Create integration tests that submit known German text (with known PII entities) to Presidio with both correct and incorrect language settings. Record entity detection recall (found entities / expected entities) for each NER-based entity type. Include results in known-limitations documentation.
  - Note: These tests require a running Presidio instance (integration or E2E tests, not unit tests with mocks). Results may vary by Presidio model version.

- **EDGE-009: Language added to `supported_languages` config but not in `ISO_TO_LINGUA`**
  - Research reference: Gap Analysis > Gap 1
  - Current behavior: Lingua cannot detect the new language. Text in that language is silently misclassified.
  - Desired behavior: Startup fails with a clear error message (REQ-002). Admin must ensure both Presidio model and Lingua mapping are available.
  - Test approach: Set `REDAKT_SUPPORTED_LANGUAGES=en,de,xx` (invalid), verify startup failure with descriptive error.

- **EDGE-010: Adversarial language-flip attack**
  - Research reference: Security / Penetration Testing Perspective; Presidio Language Support Analysis > Adversarial risk
  - Scenario: An attacker prepends English filler text to a German document to flip auto-detection to English, causing German NER to use the wrong model and miss German person names.
  - Current behavior: Lingua detects dominant language based on n-gram analysis of all text. Prepending sufficient English text flips detection.
  - Desired behavior: Accepted as a v1 known limitation. Enterprise context (internal, authenticated users) makes this low probability. The confidence score partially mitigates this: mixed-language text produces lower confidence, signaling ambiguity to the user.
  - Mitigation: Document as a known limitation. Users who suspect manipulation can manually override the language toggle.
  - Test approach: No automated test required for v1. Document the attack vector in known-limitations.

## Failure Scenarios

- **FAIL-001: Lingua library not installed or import fails**
  - Trigger condition: Missing dependency, corrupted installation
  - Expected behavior: Application fails to start (import error at module load). This is acceptable -- language detection is a core dependency.
  - User communication: N/A (startup failure, operator sees import error in logs)
  - Recovery approach: Reinstall dependencies (`uv sync`)

- **FAIL-002: Lingua detector build failure**
  - Trigger condition: Invalid language enum, memory exhaustion during model load
  - Expected behavior: First request that triggers detection fails. Error logged at CRITICAL level. Subsequent requests retry build because Python's `@lru_cache` does NOT cache exceptions -- if the function raises, the next call retries from scratch.
  - User communication: HTTP 500 with generic error message (no PII exposure)
  - Recovery approach: Fix the underlying issue (configuration, memory). The next request will automatically retry the build. Service restart is not strictly required for build failures that raise exceptions, but is recommended after configuration changes to `supported_languages` (since successful builds ARE cached for process lifetime).

- **FAIL-003: Persistent detection failures (all requests falling back)**
  - Trigger condition: Corrupted Lingua model, persistent OOM, misconfiguration
  - Expected behavior: Every request logs an ERROR (not just WARNING). Structured log field `language_fallback: true` on every request enables alerting.
  - User communication: Users see `language_confidence: 0.0` on every response, signaling unreliable detection
  - Recovery approach: Operator monitors fallback rate via logs, investigates root cause, restarts service

- **FAIL-004: `lru_cache` caches a broken detector**
  - Trigger condition: `_build_detector()` returns successfully but the detector object is corrupted or non-functional
  - Expected behavior: Every `_detect_sync` call fails, caught by exception handler, logged at ERROR
  - User communication: `language_confidence: 0.0` on all responses
  - Recovery approach: Service restart clears the `lru_cache`. Document that configuration changes to `supported_languages` require a restart.

## Implementation Constraints

### Context Requirements

**Essential files for implementation (must read):**
- `src/redakt/services/language.py` -- Primary file to modify (dynamic detector, configurable fallback, confidence, exception handling, `validate_language_config()`)
- `src/redakt/main.py` -- Add `validate_language_config()` call to FastAPI lifespan handler
- `src/redakt/config.py` -- Add `language_detection_fallback` setting
- `src/redakt/models/detect.py` -- Add `language_confidence` field
- `src/redakt/models/anonymize.py` -- Add `language_confidence` field
- `src/redakt/models/document.py` -- Add `language_confidence` field
- `src/redakt/routers/detect.py` -- Update to use new `detect_language` return type, pass confidence to response
- `src/redakt/routers/anonymize.py` -- Same as above
- `src/redakt/services/document_processor.py` -- Same as above, update `detect_document_language`

**Files that can be delegated to subagents:**
- `tests/test_language.py` -- Expand with new test cases
- `tests/test_detect.py` -- Add language-specific integration tests
- `tests/test_anonymize_api.py` -- Add language-specific integration tests
- `tests/test_documents_api.py` -- Add language-specific integration tests
- `tests/e2e/test_language_e2e.py` -- New E2E test file
- `src/redakt/templates/partials/detect_results.html` -- Add confidence display
- `src/redakt/templates/partials/anonymize_results.html` -- Add confidence display
- `src/redakt/templates/partials/document_results.html` -- Add confidence display

### Technical Constraints

1. **Lingua API**: `detect_language_of(text)` returns `Language | None`. For confidence: `compute_language_confidence_values(text)` returns `list[ConfidenceValue]` (each has `.language` and `.value` attributes).
2. **`@lru_cache` on `_build_detector()`**: Cache is per-process, persists for process lifetime. Configuration changes require restart. Dynamic building based on `settings.supported_languages` is safe because settings are immutable after startup.
3. **Thread executor**: `_detect_sync` runs in a thread executor. Must remain thread-safe. Lingua detector is read-only after build -- safe for concurrent use.
4. **Presidio language support**: Limited to languages with spaCy models configured in `spacy_multilingual.yaml`. Currently: en (`en_core_web_lg`), de (`de_core_news_lg`), es (`es_core_news_md`). Adding a language to Redakt config also requires a Presidio spaCy model.
5. **No new dependencies**: Lingua already installed. Confidence API is part of the same library.

## Validation Strategy

### Automated Testing

**Unit Tests (`tests/test_language.py` -- expand existing):**
- Dynamic detector builds from `settings.supported_languages`
- Startup validation rejects unsupported language codes
- Configurable fallback used for empty text, timeout, exception, Lingua None
- Confidence score returned for auto-detected text
- Confidence is `0.0` for fallback scenarios
- Confidence is `None` for manual override
- Exception handling logs exception details at ERROR level
- Timeout handling logs at WARNING level (not ERROR)
- Representative enterprise content: German legal text, mixed EN/DE email, short German address

**Integration Tests (`tests/test_detect.py`, `tests/test_anonymize_api.py`, `tests/test_documents_api.py`):**
- API response includes `language_confidence` field
- Auto-detect returns non-null confidence
- Manual override returns null confidence
- Unsupported language returns 400
- `language_detected` matches expected for English and German text

**GDPR Accuracy Tests (integration tests requiring running Presidio):**
- German text with known German names analyzed with `language="de"` -- record PERSON/LOCATION/ORGANIZATION recall
- Same German text analyzed with `language="en"` -- record recall degradation
- English text with known English names analyzed with `language="en"` vs `language="de"` -- record recall
- Results documented in known-limitations for DPO review

**E2E Tests (`tests/e2e/test_language_e2e.py`):**
- Auto radio selected by default on all 3 pages
- Submit with auto, verify `language_detected` shown in results
- Submit with auto, verify confidence label (High/Medium/Low) shown in results
- Override to "de", submit English text, verify `language_detected` shows "de"
- Override to "en", submit German text, verify `language_detected` shows "en"
- Manual override does not show confidence label

### Manual Verification
- Submit German text with auto-detect, verify German detected
- Submit English text with auto-detect, verify English detected
- Submit mixed EN/DE text, verify dominant language detected and confidence is lower
- Override language toggle, verify override is respected
- Check audit logs contain language field

## Dependencies and Risks

- **RISK-001: `lru_cache` caches broken state** -- If `_build_detector()` raises, `lru_cache` does NOT cache exceptions (it only caches successful returns). However, if it returns a non-functional detector, that is cached. Mitigation: Startup validation (REQ-002) catches configuration errors early. Runtime detector failures are caught per-request.
- **RISK-002: Lingua confidence calibration** -- Lingua's confidence scores may not be well-calibrated for the EN/DE binary case. A score of 0.7 does not necessarily mean 70% probability of correctness. Mitigation: Web UI displays qualitative labels (High/Medium/Low) instead of percentages to avoid misleading users (see REQ-015). API responses return the raw numeric value for programmatic use, with documentation noting that scores are relative indicators, not calibrated probabilities. The `minimum_relative_distance(0.25)` threshold is provisional and may need tuning based on production fallback rates.
- **RISK-003: Mixed-language GDPR risk** -- Mixed EN/DE content uses only the dominant language's NER model. Person names, locations, and organizations in the minority language may be missed. Mitigation: Document as a v1 known limitation. Recommend manual language override for known mixed-language content. Confidence score helps signal ambiguity.
- **RISK-004: Breaking change to `detect_language` signature** -- Changing `detect_language()` from returning `str` to returning `(str, float | None)` is a breaking change for all callers. Mitigation: Update all callers in the same implementation pass. The callers are enumerated in the research (3 routers + document processor).

## Implementation Notes

### Suggested Approach

**Step 1: Config changes** (~5 min)
- Add `language_detection_fallback: str = "en"` to `Settings` in `config.py`

**Step 2: Language service hardening** (~30 min) -- Core changes to `language.py`
1. Expand `LINGUA_TO_ISO` and `ISO_TO_LINGUA` to cover en, de, es (and any other languages Presidio supports)
2. Make `_build_detector()` dynamic: read `settings.supported_languages`, map to Lingua enums, build
3. Add `validate_language_config()` function for startup validation (called from FastAPI lifespan handler in `main.py`): check all `supported_languages` are in `ISO_TO_LINGUA`, check `language_detection_fallback` is in `supported_languages`
4. Define `LanguageDetection(NamedTuple)` with `language: str` and `confidence: float | None`. Change `detect_language()` to return `LanguageDetection`.
5. Use `compute_language_confidence_values()` in `_detect_sync()` for confidence. Both calls share the existing timeout. If confidence fails but detection succeeded, return `confidence=None`.
6. Replace all hardcoded `"en"` fallbacks with `settings.language_detection_fallback`
7. Improve exception handling: separate `asyncio.TimeoutError` (WARNING) from other exceptions (ERROR), log `exc_info=True`
8. Add structured log fields: `language_detected`, `language_confidence`, `language_fallback`, `language_fallback_reason` (see SEC-001)

**Step 3: Model updates** (~10 min)
- Add `language_confidence: float | None = None` to `DetectResponse`, `AnonymizeResponse`, `DocumentUploadResponse`

**Step 4: Router updates** (~20 min)
- Update all routers to unpack `(language, confidence)` from `detect_language()`
- Pass confidence to response models
- Update `detect_document_language()` in `document_processor.py` to return confidence

**Step 5: Template updates** (~10 min)
- Add confidence display to all three result partials (show as qualitative label: High/Medium/Low/None when non-null, omit for manual override)

**Step 6: Unit tests** (~30 min)
- Expand `tests/test_language.py` with new scenarios (dynamic detector, configurable fallback, confidence, exception handling, representative content)

**Step 7: Integration tests** (~20 min)
- Add `language_confidence` assertions to existing test files
- Add missing language-path tests

**Step 8: E2E tests** (~20 min)
- Create `tests/e2e/test_language_e2e.py` for browser toggle and confidence display tests

### Critical Implementation Considerations

1. **`detect_language()` return type change is the riskiest refactor.** All callers must be updated atomically. The `LanguageDetection` NamedTuple supports both named access (`result.language`) and tuple unpacking (`language, confidence = await detect_language(text)`), making the migration straightforward. The callers are: `detect.py:60`, `anonymize.py:52`, `document_processor.py:234` (via `detect_document_language`), and `pages.py` (via the shared router functions). Grep for `detect_language` to find all call sites.

2. **`lru_cache` and testing.** The `@lru_cache` on `_build_detector()` persists across test runs. Tests that modify `settings.supported_languages` must clear the cache (call `_build_detector.cache_clear()`) to ensure the detector is rebuilt. This is already a consideration in the existing tests.

3. **Lingua `compute_language_confidence_values` returns a list.** For the detected language, extract the matching `ConfidenceValue` entry. If the list is empty or the detected language is not in the list, confidence is `0.0`.

4. **Backward compatibility.** The `language_confidence` field defaults to `None` in response models, so existing API consumers that don't use this field are unaffected. No breaking API changes for consumers.

5. **Web UI radio buttons remain hardcoded to auto/en/de for v1.** Dynamic generation from `settings.supported_languages` is a post-v1 enhancement. This is acceptable because the v1 target is EN/DE only.

## Implementation Summary

- **Status:** Complete
- **Completion Date:** 2026-03-29
- **Implementation Tracking:** `SDD/prompts/PROMPT-004-language-detection-2026-03-29.md`
- **Implementation Summary:** `SDD/prompts/implementation-complete/IMPLEMENTATION-SUMMARY-004-2026-03-29_18-00-00.md`

### Outcome
All 17 functional requirements, 3 non-functional requirements, 2 security requirements, and 3 UX requirements implemented and validated. This was a hardening exercise on existing language detection infrastructure -- no new dependencies were required (Lingua was already installed). 213 tests passing (24 new tests added, up from 189). Code review APPROVED at 95.5%. Critical review completed with all 12 findings resolved (3 HIGH, 5 MEDIUM, 4 LOW).

### Key Implementation Decisions
1. `LanguageDetection(NamedTuple)` chosen for clean return type supporting both named access and tuple unpacking
2. `validate_language_config()` runs from FastAPI lifespan handler (not module-level) to avoid interfering with test imports
3. Confidence displayed as qualitative labels (High/Medium/Low/None) rather than percentages, since Lingua scores are not calibrated probabilities
4. Empty text returns `language_detection_fallback` instead of `"unknown"` to stay within `supported_languages` validation
