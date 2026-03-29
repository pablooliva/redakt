# RESEARCH-004-language-detection

## Executive Summary

Feature 4 (Language Auto-Detection with Manual Override) has **core infrastructure already in place** from Features 1-3. The `lingua-language-detector` library is integrated, all API endpoints accept `"language": "auto"` (default) or explicit ISO 639-1 codes, all web UI pages have auto/en/de radio toggles, and all responses include `language_detected`. However, the implementation has several gaps that require attention before it can be considered production-ready: a hardcoded language list decoupled from configurable settings, an English-only fallback bias inappropriate for German-majority deployments, exception handling that swallows errors silently, and no production observability. The remaining work is focused on hardening, validation, and GDPR risk assessment rather than new feature development.

---

## System Data Flow

### Current Implementation (Already Exists)

Language detection is already wired into every user-facing flow:

```
User input (text / document)
    |
    v
Router (detect.py:60, anonymize.py:52, document_processor.py:234)
    |-- language == "auto"?
    |       YES -> detect_language(text)    [services/language.py:28]
    |       NO  -> use provided language
    v
Validate against settings.supported_languages  [config.py:15]
    |
    v
Pass resolved language to presidio.analyze()   [services/presidio.py:23]
    |
    v
Return language_detected in response           [models/*.py]
```

### Key Entry Points (with line numbers)

| File | Line | Function | Role |
|---|---|---|---|
| `src/redakt/services/language.py` | 28 | `detect_language(text)` | Core async detection, delegates to Lingua |
| `src/redakt/services/language.py` | 43 | `_detect_sync(text)` | Synchronous Lingua call in executor |
| `src/redakt/services/language.py` | 20 | `_build_detector()` | Cached Lingua detector builder (EN + DE) |
| `src/redakt/routers/detect.py` | 44 | `run_detection()` | Detection endpoint language resolution (line 60-63) |
| `src/redakt/routers/anonymize.py` | 38 | `run_anonymization()` | Anonymize endpoint language resolution (line 52-55) |
| `src/redakt/services/document_processor.py` | 133 | `detect_document_language()` | Document-level detection (concatenates first chunks up to 5KB) |
| `src/redakt/services/document_processor.py` | 179 | `process_document()` | Calls `detect_document_language()` at line 234 |
| `src/redakt/routers/pages.py` | 35, 92, 151 | Form handlers | Accept `language: str = Form("auto")` |
| `src/redakt/config.py` | 14-15, 19 | Settings | `default_language`, `supported_languages`, `language_detection_timeout` |

### Data Transformations

1. **Input**: `"language": "auto"` (string, from JSON body or form field)
2. **Detection**: Lingua library returns `Language.ENGLISH` or `Language.GERMAN` enum
3. **Mapping**: `LINGUA_TO_ISO` dict converts to ISO 639-1 (`"en"`, `"de"`) at `language.py:11-13`
4. **Validation**: Checked against `settings.supported_languages = ["en", "de"]` at `config.py:15`
5. **Output**: Passed as `language` string to Presidio's `/analyze` endpoint and returned as `language_detected` in all responses

### External Dependencies

| Dependency | Version | Purpose | License |
|---|---|---|---|
| `lingua-language-detector` | >=2.1 | Language detection library | Apache 2.0 |
| Presidio Analyzer (REST) | internal port 5001 (host-mapped to 5002 in standalone Presidio docker-compose) | Accepts `language` parameter on `/analyze` | MIT |

> **Note on ports**: In the Redakt `docker-compose.yml`, presidio-analyzer runs on internal port 5001 (`PORT=5001` at `docker-compose.yml:26`), and the Redakt service connects to it at `http://presidio-analyzer:5001` (no host port mapping). The "port 5002" referenced in CLAUDE.md refers to the *host-mapped* port in Presidio's standalone `docker-compose-text.yml` (host 5002 -> container 5001). Within the Redakt stack, all Presidio communication uses port 5001.

### Integration Points

| Component | How language flows through it |
|---|---|
| **API models** | `DetectRequest.language` (default "auto"), `AnonymizeRequest.language` (default "auto") -- `models/detect.py:6`, `models/anonymize.py:6` |
| **API responses** | `DetectResponse.language_detected`, `AnonymizeResponse.language_detected`, `DocumentUploadResponse.language_detected` |
| **Presidio client** | `presidio.analyze(language=resolved_language)` at `services/presidio.py:13-36` (language passed at line 23) |
| **Audit logging** | All log functions accept `language` parameter -- `services/audit.py:56,65,74` (`log_detection`, `log_anonymization`, `log_document_upload`) |
| **Web UI templates** | All three pages (detect, anonymize, documents) have identical radio toggle groups |
| **Result partials** | All three result partials display `language_detected` in metadata |

---

## Stakeholder Mental Models

### Product Team Perspective
- **Expectation**: Users in a German enterprise deal with EN/DE content daily. Language should "just work" without manual selection.
- **Key concern**: Auto-detection must be reliable enough that users don't need to think about it. Wrong language = missed PII = compliance failure.
- **Success metric**: Users rarely need to override the auto-detected language.

### Engineering Team Perspective
- **Current state**: Core infrastructure exists and is wired into all pipelines. However, code existence does not equal validated correctness. The existing 6 unit tests use trivially simple sentences and do not cover enterprise-representative content patterns (German legal text, mixed DE/EN business emails, short German addresses).
- **Remaining concerns**: (1) Hardcoded language list in detector builder is decoupled from configurable `supported_languages` setting. (2) Mixed-language content handling is undefined -- currently detects the dominant language only. (3) No confidence score returned to user. (4) All fallback paths hardcode `"en"` instead of using a configurable fallback. (5) Exception handling swallows all errors with no details logged. (6) The UI shows detected language in results but does not update the radio toggle to reflect what was detected.
- **Performance**: Detection runs in a thread executor with a 2-second timeout (not empirically profiled for max-size inputs). Lingua's `from_languages` with 2 languages is fast for typical inputs.

### Support Team Perspective
- **Common scenario**: German text with English names/terms (company names, product names, technical jargon). Auto-detection may flip to "en" if English terms dominate.
- **Need**: Clear indication of what language was used, easy override, and ability to retry.

### User Perspective
- **Web UI user**: Sees auto/en/de toggle before submission, sees detected language in results. If wrong, must change toggle and resubmit.
- **API user (AI agent)**: Sends `"language": "auto"`, gets `language_detected` in response. Can retry with explicit language if results look wrong.
- **Pain point**: No feedback loop -- the UI shows detected language in results but doesn't pre-fill or update the toggle. The user cannot see the detection *before* analysis runs.

### Data Protection Officer / Legal Perspective
- **Key question**: What is the acceptable miss rate for PII detection due to language misdetection? Under GDPR, any missed personal name in text shared externally could constitute a data protection incident (Article 4(12)).
- **Need**: Quantified accuracy data for language mismatch scenarios. Clear documentation of known limitations for the organization's data protection impact assessment.
- **Open item**: The DPO should be consulted on whether "partial degradation" of NER-based detection is acceptable, or whether stronger safeguards (dual-pass analysis, mandatory confidence scores) are required.

### Security / Penetration Testing Perspective
- **Adversarial concern**: Can an attacker craft input that intentionally confuses the language detector to bypass PII detection? E.g., prepending English filler text to a German document to flip detection to English, causing German names to be missed by the English NER model.
- **Assessment**: Low risk in the enterprise context (internal, authenticated users), but should be documented as a known limitation. The manual override serves as a user-side mitigation.

### Operations / SRE Perspective
- **Monitoring gap**: No observability into language detection quality in production. If detection accuracy degrades (model issue, content shift), the team would not know until users report missed PII.
- **Need**: Structured log fields or metrics for: detection confidence, fallback events (count, reason), language distribution over time. These enable dashboarding and alerting without code changes.

---

## Production Edge Cases

### Mixed-Language Content
- **Scenario**: German paragraph with English names, email addresses, URLs
- **Current behavior**: Lingua detects dominant language. If 60% German, returns "de". English names/emails are still caught by Presidio's language-agnostic regex recognizers (EmailRecognizer, UrlRecognizer, etc.)
- **Risk**: NER-based recognizers (SpacyRecognizer) are language-specific. A German text with `language="de"` uses `de_core_news_lg`, which may still recognize English names but with lower confidence.
- **Partial mitigation**: Presidio's regex-based recognizers (email, phone, credit card, IBAN, etc.) are language-agnostic. However, the affected NER categories -- person names, locations, organizations -- are the highest-risk PII for GDPR compliance. Saying "only NER is affected" understates the practical impact; these are exactly the entities most likely to cause data protection incidents if missed.

### Short Text
- **Scenario**: User pastes "John Mueller" (3 words)
- **Current behavior**: Lingua may struggle with very short text. The `with_minimum_relative_distance(0.25)` setting in `language.py:23` means Lingua returns `None` if it's not 25% more confident in one language vs another.
- **Fallback**: `_detect_sync` returns `"en"` when Lingua returns None (`language.py:46-47`)
- **Test**: `test_language.py:30-32` covers `"123"` returning `"en"` as fallback
- **Concern**: Short German text (names like "Hans Mueller", addresses like "Hauptstr. 5, Berlin") is exactly the high-risk PII that should not be missed. Falling back to English for ambiguous short text means German NER (`de_core_news_lg`) is not used, potentially missing German name patterns. See Gap 2 (English Fallback Bias) for the configurable fallback recommendation.

### Unsupported Language Input
- **Scenario**: User sends `"language": "fr"` (French)
- **Current behavior**: Returns HTTP 400 with message listing supported languages (`detect.py:66-69`, `anonymize.py:57-61`)
- **Note**: The spaCy multilingual config (`spacy_multilingual.yaml`) includes `es_core_news_md` (Spanish), but Redakt's `supported_languages` config only lists `["en", "de"]`. Adding Spanish would require updating the config setting.

### Empty / Whitespace Text
- **Scenario**: User submits empty textarea
- **Current behavior**: `detect_language("")` returns `"en"` immediately (`language.py:29-30`). Detection endpoints return early with `language="unknown"` (`detect.py:54-57`).

### Detection Timeout
- **Scenario**: Lingua hangs (unlikely but possible with pathological input)
- **Current behavior**: 2-second asyncio timeout, falls back to `"en"` with a warning log (`language.py:32-39`)
- **Concern**: The timeout value (2.0s) was not empirically profiled. For a 512KB text input through Lingua's n-gram analysis, 2 seconds may or may not be sufficient. Performance profiling with max-size inputs should be done to validate this threshold.

### Exception Handling Weakness
- **Scenario**: Lingua misconfiguration, corrupted model, OOM, or any unexpected error during detection
- **Current behavior**: `language.py:38` catches `(asyncio.TimeoutError, Exception)`, which swallows ALL exceptions and falls back to `"en"`. The warning log at line 39 does not include the exception type, message, or traceback (`logger.warning("Language detection failed, falling back to 'en'")`). No `exc_info=True`, no exception message logged.
- **Risk**: A broken Lingua installation, corrupted model file, or persistent OOM condition would be invisible in production. The system would silently process all text as English, potentially missing German PII on every request. Repeated fallbacks would not trigger any alert.
- **Recommendation for SPEC-004**:
  1. Log the actual exception type and message: `logger.warning("Language detection failed: %s", exc, exc_info=True)`
  2. Separate handling for `asyncio.TimeoutError` (expected, log at WARNING) vs. other exceptions (unexpected, log at ERROR)
  3. Consider emitting a metric or structured log field for fallback events to enable production monitoring

### Document Language Detection
- **Scenario**: Multi-page PDF or multi-sheet XLSX
- **Current behavior**: Concatenates first chunks up to 5KB **in chunk order**, detects once for entire document (`document_processor.py:133-172`). All chunks processed with same language.
- **Trade-off**: Consistent processing vs. potential mixed-language documents. Correct for v1.
- **Limitation**: Chunk ordering depends on the extractor (page order for PDF, sheet order for XLSX). For documents where the beginning differs from the body (e.g., a German contract with an English cover letter, or an XLSX where Sheet 1 is English headers and Sheet 2 is German data), the first 5KB may not represent the dominant language.
- **Potential mitigation (post-v1)**: Sample from beginning, middle, and end of the document rather than only the first 5KB. For v1, this is an accepted limitation that should be documented in user-facing help text.

---

## Presidio Language Support Analysis

### What the Current Presidio Setup Supports

From `presidio/presidio-analyzer/presidio_analyzer/conf/spacy_multilingual.yaml`:

| Language | Model | Status in Redakt |
|---|---|---|
| `en` | `en_core_web_lg` | Active, in `supported_languages` |
| `de` | `de_core_news_lg` | Active, in `supported_languages` |
| `es` | `es_core_news_md` | Configured in Presidio but NOT in Redakt's `supported_languages` |

### Language-Specific Recognizers

- **English**: US SSN, US driver license, US passport, US bank number, US ITIN, UK NHS, UK NINO, AU/SG/IN recognizers
- **German**: 13 recognizers -- DE tax ID (Steueridentifikationsnummer), DE passport, DE ID card, DE KFZ plate, DE VAT (USt-IdNr), and more
- **Language-agnostic**: Email, phone (international), credit card, IBAN, IP address, URL, crypto addresses, domain names

### What Happens with Wrong Language

If English text is analyzed with `language="de"`:
- Regex recognizers (email, phone, IBAN) still work -- they are language-agnostic
- NER model (`de_core_news_lg`) processes the text -- may miss English names or detect them with lower confidence
- German-specific regex recognizers run but won't match English patterns (no harm, just wasted cycles)
- Overall: partial degradation of NER-based detection

**GDPR Risk Assessment**: "Partial degradation" is a significant concern for a GDPR compliance tool. The affected NER-based entity categories -- person names, locations, organizations -- are among the highest-risk PII categories. A missed person name in anonymized text shared with an AI tool constitutes a potential data protection incident under GDPR Article 4(12). The fact that regex-based recognizers (email, phone, IBAN, credit card) remain unaffected mitigates the risk for structured PII, but unstructured PII (names, locations) is precisely what NER exists to catch.

**Quantification needed**: Before SPEC-004 is finalized, the team should run empirical accuracy tests comparing:
1. German text with German names analyzed with `language="de"` (baseline)
2. Same text analyzed with `language="en"` (mismatch scenario)
3. Measure entity detection recall for PERSON, LOCATION, ORGANIZATION entities

This data is essential for determining whether the confidence score enhancement (Gap 2) should be mandatory rather than optional, and whether the mixed-language strategy (Gap 1) needs a more robust approach for v1.

**Adversarial risk**: An attacker could potentially prepend English text to a German document to flip auto-detection to English, causing German NER to use the wrong model. This is a low-probability risk in the enterprise deployment context (internal users), but should be documented as a known limitation.

---

## Language Detection Library Analysis

### Current Choice: lingua-language-detector

Already integrated at `lingua-language-detector>=2.1` in `pyproject.toml`.

| Attribute | Detail |
|---|---|
| **Accuracy** | Strong short-text accuracy among pure Python libraries per Lingua's own benchmarks (see [Lingua README](https://github.com/pemistahl/lingua-py#library-comparison)). Uses n-gram frequency analysis. No independent benchmark data exists for the specific EN/DE enterprise-jargon domain this system targets. |
| **Performance** | Fast when built with `from_languages()` (subset). Only EN+DE = very fast. |
| **Model size** | ~30MB for full model; much smaller for 2-language subset |
| **License** | Apache 2.0 |
| **API** | Clean Python API. `detect_language_of(text)` returns `Language` enum or `None`. |
| **Configuration** | `minimum_relative_distance(0.25)` -- a reasonable starting point, but not empirically validated against representative enterprise EN/DE content. May need adjustment based on production fallback rates. |
| **Thread safety** | Detector is read-only after build; safe for concurrent use from executor |
| **Caching** | `_build_detector()` uses `@lru_cache(maxsize=1)` -- detector is built once per process lifetime. A process restart is required to pick up changes to supported languages. This is acceptable for production (configuration changes require restart), but makes unit testing harder (cache persists across tests). |

### Alternatives Considered (from spec)

| Library | Pros | Cons | Verdict |
|---|---|---|---|
| `langdetect` | Google's library, well-known | Non-deterministic by default, less accurate for short text | Not needed -- Lingua already chosen |
| `fasttext` | Facebook's library, very accurate | Large model (~917MB), C dependency, overkill for 2 languages | Not needed |
| `lingua-py` | Same as lingua-language-detector | This IS the chosen library | Already integrated |

### Recommendation

**Keep `lingua-language-detector`**. It is already integrated, tested, and well-suited for the EN/DE binary detection use case. No library change needed.

---

## Files That Matter

### Core Logic (Already Implemented)

| File | Purpose | Status |
|---|---|---|
| `src/redakt/services/language.py` | Lingua integration, async detection, fallback | **Complete** |
| `src/redakt/config.py:14-19` | `default_language`, `supported_languages`, `language_detection_timeout` | **Complete** |
| `src/redakt/services/presidio.py:16-23` | Passes `language` to Presidio `/analyze` | **Complete** |
| `src/redakt/routers/detect.py:59-69` | Language resolution + validation in detect flow | **Complete** |
| `src/redakt/routers/anonymize.py:51-62` | Language resolution + validation in anonymize flow | **Complete** |
| `src/redakt/services/document_processor.py:133-172` | Per-document language detection | **Complete** |

### Web UI (Already Implemented)

| File | Purpose | Status |
|---|---|---|
| `src/redakt/templates/detect.html:15-29` | Auto/EN/DE radio toggle | **Complete** |
| `src/redakt/templates/anonymize.html:17-31` | Auto/EN/DE radio toggle | **Complete** |
| `src/redakt/templates/documents.html:25-39` | Auto/EN/DE radio toggle | **Complete** |
| `src/redakt/templates/partials/detect_results.html:19` | Shows `language_detected` | **Complete** |
| `src/redakt/templates/partials/anonymize_results.html:21` | Shows `language_detected` | **Complete** |
| `src/redakt/templates/partials/document_results.html:58` | Shows `language_detected` | **Complete** |

### API Models (Already Implemented)

| File | Purpose | Status |
|---|---|---|
| `src/redakt/models/detect.py:6,23` | `language` input field, `language_detected` output field | **Complete** |
| `src/redakt/models/anonymize.py:6,15` | `language` input field, `language_detected` output field | **Complete** |
| `src/redakt/models/document.py:19` | `language_detected` output field | **Complete** |

### Tests

| File | Purpose | Status |
|---|---|---|
| `tests/test_language.py` | 6 tests for language detection service | **Complete** (6 tests) |
| `tests/test_detect.py` | Includes language parameter testing | **Partial** |
| `tests/test_anonymize_api.py` | Includes language parameter testing | **Partial** |
| `tests/test_document_processor.py` | Includes document language detection | **Partial** |
| `tests/test_pages.py` | Form-based language parameter | **Partial** |

### Configuration

| File | Purpose | Status |
|---|---|---|
| `pyproject.toml:10` | `lingua-language-detector>=2.1` dependency | **Complete** |
| `presidio/.../spacy_multilingual.yaml` | Presidio NLP models (en, de, es) | **Complete** |

---

## Gap Analysis: What Remains

While the core language detection infrastructure exists, several gaps need attention before the feature can be considered production-ready. The "already implemented" framing should not prevent validation work.

### Gap 1: Hardcoded Lingua Languages vs. Configurable `supported_languages` (HIGH)

**Current state**: `_build_detector()` in `language.py:20-25` is hardcoded to `Language.ENGLISH, Language.GERMAN`. But `settings.supported_languages` in `config.py:15` is a configurable list overridable via `REDAKT_SUPPORTED_LANGUAGES` env var. The `LINGUA_TO_ISO` mapping at `language.py:11-14` is also hardcoded to only EN and DE.

**Problem**: If an admin adds `"es"` to `supported_languages` (Presidio already has the Spanish model loaded via `spacy_multilingual.yaml`), the Lingua detector will never return `"es"` -- it physically cannot detect Spanish. Spanish text sent with `language: "auto"` would be silently misclassified as English or German. The validation step would then accept the misclassified language (since `"en"` and `"de"` are both in `supported_languages`), and the text would be analyzed with the wrong NER model.

**Recommendation**: SPEC-004 must require one of:
1. **Dynamic detector building**: `_build_detector()` reads `settings.supported_languages`, maps ISO codes to Lingua Language enums via `ISO_TO_LINGUA`, and builds the detector dynamically. The `LINGUA_TO_ISO` and `ISO_TO_LINGUA` dicts must also be expanded.
2. **Explicit invariant documentation**: If dynamic building is deferred, add a code comment and configuration doc stating that adding a language requires code changes to `language.py` (update `LINGUA_TO_ISO`, `ISO_TO_LINGUA`, and `_build_detector()`). Add a startup validation check that warns if `supported_languages` contains codes not in `LINGUA_TO_ISO`.

Option 1 is strongly recommended as it is low effort and eliminates the coupling.

### Gap 2: English Fallback Bias (HIGH)

**Current state**: Every fallback path in `language.py` returns `"en"`:
- Empty/whitespace text: `language.py:30` -> `"en"`
- Timeout or any exception: `language.py:39` -> `"en"`
- Lingua returns None (ambiguous): `language.py:46-47` -> `"en"`

Meanwhile, `settings.default_language` at `config.py:14` exists but is set to `"auto"` (not a fallback language), and is **never referenced in `language.py`**. There is no configurable fallback language.

**Problem**: In a German-majority enterprise, defaulting to English on every failure systematically degrades PII detection for the most common language. Short German texts (names, addresses) are high-risk PII that are exactly the cases where Lingua is most likely to return None or hit the `minimum_relative_distance` threshold.

**Recommendation**: SPEC-004 should:
1. Add a `language_detection_fallback` setting (or repurpose `default_language` for this when its value is not `"auto"`).
2. Wire the configurable fallback into all three fallback paths in `language.py`.
3. Default the fallback to `"en"` for backward compatibility, but document that German-majority deployments should set it to `"de"`.

### Gap 3: Mixed-Language Content Strategy (Open Question)

**Current state**: Lingua detects the dominant language. No multi-language analysis.
**Spec requirement**: "How to handle mixed-language content?"
**Options**:
1. **Accept as-is (recommended for v1)**: Detect dominant language, rely on Presidio's regex recognizers for cross-language patterns. Document this as a known limitation.
2. **Dual-pass analysis**: Run Presidio with both `en` and `de`, merge results. More accurate but doubles processing time and complicates overlap resolution.
3. **Per-paragraph detection**: Split text into paragraphs, detect each separately, analyze each with its detected language. Complex and may fragment entity numbering.

**GDPR caveat**: "Only NER is affected" by wrong-language detection is a misleading mitigation. NER covers the highest-risk PII categories: person names, locations, organizations. These are exactly the entities most likely to cause GDPR violations if missed. Regex-based recognizers covering email, phone, IBAN, and credit card are helpful but do not substitute for NER-based name/location detection.

**Recommendation**: Option 1 for v1, but the trade-off must be explicitly documented for users and the DPO. The confidence score (Gap 4) becomes more important as a signal that mixed-language content may have been misclassified.

### Gap 4: Detection Confidence Feedback

**Current state**: `language_detected` returns only the language code. No confidence score.
**Potential enhancement**: Return `language_confidence` (float, 0.0-1.0) so users/agents can decide whether to trust the detection or override.
**Lingua API**: `detect_language_of(text)` returns `Language` enum. For confidence, use `compute_language_confidence_values(text)` which returns `list[ConfidenceValue]`.

**Recommendation**: Given the GDPR implications of wrong-language detection (Gap 3), adding `language_confidence` to responses should be considered mandatory rather than optional. Low effort (Lingua already supports it), high value for API users (agents can auto-retry if confidence is low) and for production monitoring (low-confidence detections can be tracked).

### Gap 5: Full-Text vs. Sample Detection

**Current state**: Text endpoints detect on full text. Document endpoint samples first 5KB.
**Spec question**: "Should detection run on the full text or a sample?"
**Lingua guidance**: Lingua is accurate even on short text (one of its key advantages). Running on full text is fine for text endpoints (max 512KB). The 5KB sample for documents is reasonable.

**Recommendation**: Keep current behavior. Full text for text endpoints, 5KB sample for documents.

### Gap 6: Spanish Language Support

**Current state**: Presidio's spaCy config includes `es_core_news_md` (Spanish) but Redakt's `supported_languages` only lists `["en", "de"]`. Lingua's detector is built for EN+DE only.
**Consideration**: Adding Spanish would require (if Gap 1 is addressed with dynamic detector building):
1. Add `"es"` to `settings.supported_languages`
2. No other code changes needed (detector builds dynamically, ISO mapping expanded)
3. Add Spanish radio button to UI templates

If Gap 1 is NOT addressed dynamically, adding Spanish also requires manual code changes to `language.py`.

**Recommendation**: Defer to post-v1. The spec focuses on German enterprise use case (EN+DE).

### Gap 7: Exception Handling and Observability

**Current state**: `language.py:38` catches `(asyncio.TimeoutError, Exception)` and logs a generic warning with no exception details. No metrics, no structured log fields for fallback events.

**Recommendation**: See "Exception Handling Weakness" in Production Edge Cases above. SPEC-004 should require improved logging and consider production observability (metric/structured log for fallback events, detection confidence).

### Gap 8: Test Coverage Gaps

Specific test scenarios that should be verified/added:
1. **API endpoint tests**: Explicit language override (non-auto) with `"en"` and `"de"`
2. **Validation tests**: Unsupported language code returns 400
3. **Mixed-language detection**: German text with English names -- measure actual NER recall
4. **Cross-language accuracy**: German names analyzed with `language="en"` vs `language="de"` to quantify degradation
5. **Document language detection**: Verify 5KB sampling behavior with multi-language documents
6. **Timeout handling**: Mock slow detection, verify fallback
7. **E2E tests**: Language toggle behavior in browser, auto-detection display in results
8. **Representative content**: Test with enterprise-like content (legal prose, mixed EN/DE emails, short German addresses, technical docs with English jargon) -- the existing 6 unit tests use trivially simple sentences

---

## Security Considerations

### Authentication/Authorization
- No auth requirements specific to language detection. Same as all other endpoints.

### Data Privacy
- Language detection runs on the raw text BEFORE anonymization. The text is processed in-memory only.
- Lingua library is pure computation -- no external API calls, no data exfiltration.
- Detected language is metadata, not PII. Safe to log and return in responses.
- Audit logs include `language` field (already implemented in `audit.py:50`).

### Input Validation
- **Language parameter**: Must be `"auto"` or a value in `settings.supported_languages`. Validated in every router.
- **Text for detection**: Same size limits as the endpoint (`max_text_length: 512_000`). No additional validation needed for language detection specifically.
- **Injection**: Language code is a short string used only as a key lookup. No injection risk.

---

## Testing Strategy

### Unit Tests (existing: 6 in test_language.py)

| Test | Status |
|---|---|
| Detect English text | Exists |
| Detect German text | Exists |
| Empty text fallback | Exists |
| Whitespace text fallback | Exists |
| Exception fallback | Exists |
| Short ambiguous text fallback | Exists |

### Unit Tests (potential additions)

| Test | Priority |
|---|---|
| Mixed EN/DE text (German paragraph with English names) | Medium |
| Lingua confidence values (if Gap 2 is addressed) | Low |
| Very long text detection (performance, full 512KB) | Low |

### Integration Tests (language-related scenarios in existing test files)

| Test | File | Status |
|---|---|---|
| API detect with `language: "auto"` | `test_detect.py` | Verify exists |
| API detect with explicit `language: "en"` | `test_detect.py` | Verify exists |
| API detect with unsupported `language: "fr"` | `test_detect.py` | Verify exists |
| API anonymize with `language: "auto"` | `test_anonymize_api.py` | Verify exists |
| Document upload with `language: "auto"` | `test_documents_api.py` | Verify exists |
| Web form with language radio value | `test_pages.py` | Verify exists |

### E2E Tests (browser-facing behavior)

| Test | Priority |
|---|---|
| Auto radio selected by default on all 3 pages | High |
| Submit with auto, verify language_detected shown in results | High |
| Override to "de", submit English text, verify language shown as "de" | Medium |
| Override to "en", submit German text, verify language shown as "en" | Medium |

---

## Documentation Needs

### User-Facing Docs
- **What users need to know**: Auto-detection works for English and German. Mixed-language content uses the dominant language. Override is available via the toggle.
- **Where to document**: In-app help text or tooltip near the language toggle.

### Developer Docs (API)
- **What agents need to know**: `language` parameter defaults to `"auto"`. Response includes `language_detected`. To retry with different language, send explicit ISO 639-1 code.
- **Where to document**: API reference / OpenAPI spec for Redakt.

### Configuration Docs
- `REDAKT_SUPPORTED_LANGUAGES`: Comma-separated list of ISO 639-1 codes (default: `en,de`)
- `REDAKT_DEFAULT_LANGUAGE`: Default language parameter (default: `auto`)
- `REDAKT_LANGUAGE_DETECTION_TIMEOUT`: Timeout in seconds for detection (default: `2.0`)

---

## Architectural Recommendation

**Feature 4's core infrastructure exists but requires validation and hardening.** The specification phase should focus on:

1. **[HIGH] Fix the hardcoded language list coupling** (Gap 1): Make `_build_detector()` dynamic based on `settings.supported_languages`, or at minimum add startup validation and documentation. This is the most architecturally fragile aspect.
2. **[HIGH] Make fallback language configurable** (Gap 2): Wire `settings.default_language` (or a new `language_detection_fallback` setting) into the fallback paths in `language.py`. For a German enterprise, defaulting to `"en"` on every failure is the wrong default.
3. **[HIGH] Quantify PII detection accuracy under language mismatch**: Run empirical tests with German text analyzed as English and vice versa. Measure entity detection recall for PERSON, LOCATION, ORGANIZATION. This data is essential for GDPR risk assessment and for deciding whether confidence scores are mandatory.
4. **[MEDIUM] Improve exception handling** (Gap 7): Log actual exception details, separate timeout vs. unexpected error handling, add observability for fallback events.
5. **[MEDIUM] Add confidence score to responses** (Gap 4): Given GDPR implications, this should be treated as mandatory rather than optional.
6. **[MEDIUM] Validate Lingua accuracy** on representative enterprise content (Gap 8, item 8).
7. **Formally document** mixed-language limitations for users and the DPO.
8. **Add missing E2E tests** for language toggle UI behavior.

The implementation phase for SPEC-004 involves more work than initially estimated: hardcoded language coupling fix, configurable fallback, improved exception handling, confidence score addition, representative test coverage, and E2E tests. No new dependencies needed, but `language.py` requires meaningful changes.
