# Specification Critical Review: Language Auto-Detection (SPEC-004)

**Reviewer:** Adversarial Critical Review
**Date:** 2026-03-29
**Spec Version:** Draft
**Research Basis:** RESEARCH-004-language-detection.md

---

## Executive Summary

SPEC-004 is well-structured and benefits from the fact that most infrastructure already exists -- the spec is primarily a hardening exercise. However, the review found one internal contradiction (EDGE-003 specifies two conflicting behaviors for the same input), several requirements that will be ambiguous during implementation (confidence for documents, startup validation mechanics, `detect_language` signature change coordination), and two significant research findings that were dropped: the empirical accuracy testing recommendation and the adversarial language-flip attack scenario. The `lru_cache` behavior is also described inconsistently between RISK-001 and FAIL-002. Overall severity is MEDIUM -- the spec is implementable but will cause friction without the clarifications below.

### Overall Severity: MEDIUM

---

## Ambiguities That Will Cause Problems

### 1. [EDGE-003] Empty text: contradictory desired behavior (HIGH)

The spec states two conflicting outcomes for empty/whitespace text:

- "Returns `settings.language_detection_fallback` with `language_confidence: null` (no detection attempted)."
- "Detection endpoints return early with `language="unknown"`."

These are mutually exclusive. The current code in `detect.py:54-57` returns `language="unknown"` before `detect_language()` is even called. So the question is: what does `detect_language("")` return? And does it matter, since the router short-circuits?

- **Interpretation A:** `detect_language("")` returns `(fallback_lang, None)`, but the router ignores it and returns `"unknown"`.
- **Interpretation B:** `detect_language("")` returns `("unknown", None)`, matching the router behavior.
- **Interpretation C:** The router stops returning `"unknown"` and instead uses the fallback language.

**Recommendation:** Decide whether empty text returns `"unknown"` (current behavior) or the fallback language. If `"unknown"`, then `detect_language` should also return `"unknown"` for consistency -- but `"unknown"` is not in `supported_languages`, which means it bypasses validation. Clarify the full flow explicitly: what does each layer return, and how does the response look to the user?

### 2. [REQ-005/REQ-008] Document confidence: per-document or per-chunk? (MEDIUM)

REQ-008 says `DocumentUploadResponse` includes `language_confidence: float | None`. But REQ-012 says language is detected once per document from a 5KB sample. For a multi-page document, the confidence reflects only the first 5KB -- not the overall document's language homogeneity.

- **Problem:** A user uploading a 50-page document where the first 5KB is clearly English gets `language_confidence: 0.95`. But pages 10-50 are German. The high confidence is misleading.
- **Recommendation:** Either (a) document the confidence caveat explicitly in the API response description ("confidence reflects the sampled portion, not the full document"), or (b) consider returning `null` for document confidence since it is inherently unreliable for multi-page docs. The spec should state which approach and why.

### 3. [REQ-017] `detect_language` return type: tuple or dataclass? (MEDIUM)

The spec says "return both the language code and confidence score (as a tuple or dataclass)" but does not decide which. This will cause an implementation argument.

- **Tuple:** `(str, float | None)` -- lightweight, but callers must remember positional meaning. Destructuring `language, confidence = await detect_language(text)` is clean but fragile if a third value is added later.
- **Dataclass/NamedTuple:** More extensible, self-documenting, but heavier for a two-field result.
- **Recommendation:** Decide now. A `NamedTuple` is the best compromise (lightweight, named fields, extensible). Specify it in the requirement.

### 4. [REQ-002/REQ-004] Startup validation: when and how? (MEDIUM)

REQ-002 says "validate on application startup" and "raise a clear exception preventing startup." REQ-004 says the same for fallback validation. But the spec does not say where this validation code lives.

- **In `language.py` module-level?** Runs at import time, which is early but makes testing harder (import fails).
- **In `_build_detector()` before building?** Runs on first request, not on startup -- contradicts "preventing startup."
- **In a FastAPI `lifespan` handler?** Runs on startup as intended but requires wiring.
- **In `config.py` as a Pydantic validator?** Clean but couples config validation to language detection internals.
- **Recommendation:** Specify the mechanism. A FastAPI lifespan handler or a Pydantic `model_validator` on `Settings` are the two clean options. Pick one.

### 5. [REQ-013] UI toggles "should remain hardcoded" vs. dynamic generation note (LOW)

REQ-013 says toggles stay hardcoded to auto/en/de "for v1" with a note that dynamic generation is "post-v1." But REQ-001 makes the detector dynamic from `supported_languages`. This creates a configuration paradox: an admin adds `"es"` to `supported_languages`, the detector now supports Spanish, the API accepts Spanish, but the UI has no Spanish toggle. Users on the web UI cannot select Spanish; they must rely on auto-detection or use the API directly.

- **Recommendation:** Add a note to the spec that the UI limitation must be documented for operators: "Adding languages to `supported_languages` enables API and auto-detection support but does not add UI toggles until post-v1."

---

## Missing Specifications

### 1. Empirical accuracy testing -- dropped from research (HIGH)

The research document explicitly calls for empirical accuracy tests (under "Quantification needed"):
> "Before SPEC-004 is finalized, the team should run empirical accuracy tests comparing: (1) German text with German names analyzed with `language="de"`, (2) Same text analyzed with `language="en"`, (3) Measure entity detection recall for PERSON, LOCATION, ORGANIZATION."

This recommendation was not incorporated into the spec. There is no requirement, success criterion, or validation step for measuring actual PII detection recall under language mismatch. The spec treats this as a documentation exercise (RISK-003: "document as a v1 known limitation") rather than an empirical validation.

- **Why it matters:** Without this data, the DPO cannot make an informed decision about whether the mixed-language limitation is acceptable. The spec's GDPR risk mitigation amounts to "we told them it might not work."
- **Suggested addition:** Add a pre-implementation validation step: run the three empirical tests described in the research, record recall numbers, and include them in the known-limitations documentation.

### 2. Adversarial language-flip scenario -- dropped from research (MEDIUM)

The research identifies an adversarial attack: "An attacker could prepend English filler text to a German document to flip auto-detection to English, causing German NER to use the wrong model." The spec does not mention this scenario in edge cases or failure scenarios.

- **Why it matters:** Even in an enterprise context, this is a manipulation vector. If an employee preparing text for anonymization is trying to bypass PII detection for specific German names, prepending English text is trivial.
- **Suggested addition:** Add as EDGE-009 with a note that it is accepted for v1 (internal users, low likelihood) but documented as a known limitation. The confidence score partially mitigates this (mixed-language text produces lower confidence).

### 3. What happens when `compute_language_confidence_values` is slow? (MEDIUM)

REQ-005 requires calling `compute_language_confidence_values(text)` in addition to `detect_language_of(text)`. The spec does not address whether this doubles the detection time, whether it runs within the same 2-second timeout, or whether it can be combined with the detection call.

- **Why it matters:** If both calls happen inside `_detect_sync`, they share the timeout. If confidence computation is slow, the whole detection may time out more frequently, increasing fallback rates.
- **Suggested addition:** Specify that both calls happen inside `_detect_sync` within the existing timeout. If confidence computation fails but language detection succeeded, return the language with `confidence: null` rather than falling back.

### 4. Structured log field specification (LOW)

The spec mentions "structured log field `language_fallback: true`" (FAIL-003) and "structured log fields" (Implementation Notes Step 2, item 8) but does not define the exact field names, types, or which log lines include them. Implementers will invent their own.

- **Suggested addition:** Define the structured fields: `language_detected: str`, `language_confidence: float`, `language_fallback: bool`, `language_fallback_reason: str` (one of: "empty_text", "timeout", "exception", "ambiguous", "none").

---

## Research Disconnects

### Findings Not Addressed in Spec

1. **Research: "No independent benchmark data exists for the specific EN/DE enterprise-jargon domain"** -- The spec does not require any validation of Lingua accuracy on representative enterprise content. The "representative content" tests in the validation strategy use sample sentences chosen by the implementer, not real enterprise data.

2. **Research: "`minimum_relative_distance(0.25)` not empirically validated"** -- The spec preserves the 0.25 threshold without questioning whether it is appropriate. The research notes it "may need adjustment based on production fallback rates." The spec should at minimum state that this value is provisional and may be tuned.

3. **Research: "The UI shows detected language in results but doesn't pre-fill or update the toggle"** -- Identified as a user pain point. Not addressed in the spec, not even as a deferred enhancement. Should be noted as a known UX limitation.

4. **Research: "2-second timeout not empirically profiled"** -- The spec says "no change needed" for the timeout (PERF-001) but the research says the timeout "was not empirically profiled" for max-size inputs. These are contradictory assessments.

### Stakeholder Needs Without Corresponding Requirements

1. **DPO/Legal: "Quantified accuracy data for language mismatch scenarios"** -- No requirement produces this data.
2. **Operations/SRE: "Confidence distribution" monitoring** -- Mentioned in stakeholder table but no requirement specifies how to expose confidence distribution for monitoring (e.g., histogram metric, log aggregation pattern).

---

## Contradictions

### 1. `lru_cache` exception behavior: RISK-001 vs. FAIL-002 (HIGH)

- **RISK-001** says: "`lru_cache` does NOT cache exceptions (it only caches successful returns)."
- **FAIL-002** says: "Note: `@lru_cache` caches exceptions too -- if build fails, cache must be cleared or service restarted."

These directly contradict each other. The correct behavior is that **Python's `@lru_cache` does NOT cache exceptions** -- if the function raises, the next call will retry. RISK-001 is correct; FAIL-002 is wrong.

- **Impact:** FAIL-002's recovery guidance ("cache must be cleared or service restarted") is unnecessarily alarming and may lead operators to restart services when they don't need to.
- **Recommendation:** Fix FAIL-002 to state that `lru_cache` does not cache exceptions. The real risk (stated correctly in RISK-001) is that a non-functional detector object returned successfully IS cached.

### 2. EDGE-003 empty text: dual return values (HIGH)

Already described above in Ambiguities #1. The spec specifies both `language_detection_fallback` and `"unknown"` for the same scenario.

### 3. PERF-001 vs. Research timeout assessment (LOW)

PERF-001 says "Timeout value is adequate ... no change needed." The research says the timeout "was not empirically profiled" and recommends profiling. The spec adopted the conclusion without the evidence.

---

## Risk Reassessment

### RISK-001: `lru_cache` caches broken state -- Severity is LOWER than stated

The spec correctly identifies the theoretical risk but overstates the practical impact. The `_build_detector()` function either raises (not cached) or returns a valid detector. A "non-functional detector" that appears valid is an extremely unlikely failure mode -- Lingua's `LanguageDetectorBuilder.build()` either succeeds with a working detector or throws. The per-request exception handling provides an adequate safety net.

### RISK-002: Lingua confidence calibration -- Severity is HIGHER than stated

The spec says to "display confidence as a relative indicator, not an absolute probability." But the spec also requires displaying it as a percentage (REQ-015: "Display as percentage e.g. 92%"). Users WILL interpret "92%" as "92% probability of being correct." The UI presentation contradicts the documented caveat.

- **Recommendation:** Either (a) display as a qualitative label (High/Medium/Low) instead of a percentage, or (b) display as a percentage with a tooltip explaining it is relative, not absolute. The spec should decide which.

### RISK-003: Mixed-language GDPR risk -- Severity is HIGHER than stated

The spec classifies this as documented/mitigated. But the mitigation (confidence score + documentation) is weak:
- Confidence scores are not calibrated (RISK-002).
- Documentation shifts responsibility to the user ("recommend manual override for known mixed-language content"), but users do not know their content is mixed-language until after detection runs.
- The spec provides no mechanism for the system to proactively warn users when confidence is low (e.g., a warning banner in the UI saying "Language detection confidence is low -- consider selecting language manually").

### RISK-004: Breaking change to `detect_language` signature -- Severity is LOWER than stated

The spec already enumerates all callers (3 routers + document processor + pages.py). The change is mechanical, not architectural. A type checker will catch any missed call sites. Low practical risk.

---

## Untestable or Hard-to-Verify Criteria

1. **UX-001 "works without any configuration"** -- How do you objectively verify "just works"? This is a subjective experience criterion, not a testable requirement.

2. **UX-002 "positioned near the main input/upload area"** -- "Near" is subjective. What counts as near? Within 200px? In the same form section? This is a layout guideline, not a verifiable requirement. It is also already implemented, so the point is moot unless the layout changes.

3. **EDGE-001 "Verify confidence is lower for mixed content than pure content"** -- This depends on Lingua's internal behavior, which the spec does not control. If Lingua happens to return high confidence for mixed EN/DE content (possible for German-dominant text with a few English words), this test assertion would fail despite correct system behavior.

---

## Recommended Actions Before Proceeding

1. **[HIGH] Resolve EDGE-003 contradiction.** Decide: does empty text return `"unknown"` or the fallback language? Document the full flow from router to response.

2. **[HIGH] Fix FAIL-002 `lru_cache` contradiction.** Remove the incorrect claim that `lru_cache` caches exceptions.

3. **[HIGH] Add empirical accuracy testing.** Before implementation, run the three mismatch tests recommended in the research. Record PII detection recall numbers. This is essential for GDPR risk documentation.

4. **[MEDIUM] Decide `detect_language` return type.** Tuple vs. NamedTuple vs. dataclass. Specify in REQ-017.

5. **[MEDIUM] Specify startup validation mechanism.** Lifespan handler, Pydantic validator, or module-level code. Pick one in REQ-002/REQ-004.

6. **[MEDIUM] Address confidence display contradiction.** Percentage display (REQ-015) conflicts with "not an absolute probability" (RISK-002). Choose qualitative labels or percentage-with-caveat.

7. **[MEDIUM] Specify confidence computation timeout behavior.** Does `compute_language_confidence_values` share the 2s timeout with detection? What happens if confidence fails but detection succeeded?

8. **[LOW] Add adversarial language-flip as EDGE-009.** Document even if accepted for v1.

9. **[LOW] Add UI toggle limitation note for operators.** Dynamic `supported_languages` without dynamic UI toggles will confuse admins.

10. **[LOW] Reconcile PERF-001 with research timeout recommendation.** Either profile the timeout or state it is accepted as-is with rationale.

---

## Findings Addressed

**Date:** 2026-03-29
**Resolved by:** Spec update pass -- all findings resolved.

### HIGH Findings

1. **[EDGE-003] Empty text contradiction -- RESOLVED.** Decided: empty text returns `settings.language_detection_fallback` (not `"unknown"`). Both router layer and service layer return the fallback language with `confidence: null`. Rationale documented: `"unknown"` is not in `supported_languages` and bypasses validation. Full two-layer flow specified explicitly.

2. **[FAIL-002 vs RISK-001] `lru_cache` exception behavior -- RESOLVED.** Fixed FAIL-002 to correctly state that Python's `@lru_cache` does NOT cache exceptions. Recovery guidance updated: next request automatically retries the build. Service restart only recommended for configuration changes (successful builds are cached).

3. **[Empirical accuracy testing] Dropped GDPR finding -- RESOLVED.** Added as EDGE-008 (Language mismatch PII detection accuracy). Requires three empirical tests comparing PII detection recall under correct vs. mismatched language settings. Added corresponding GDPR Accuracy Tests section to Validation Strategy. Results feed into known-limitations documentation for DPO review.

### MEDIUM Findings

4. **[REQ-017] Return type ambiguity -- RESOLVED.** Decided: `LanguageDetection(NamedTuple)` with `language: str` and `confidence: float | None`. Provides named field access and tuple unpacking. Specified in REQ-017 with exact class definition.

5. **[REQ-002/REQ-004] Startup validation location -- RESOLVED.** Specified: `validate_language_config()` function in `language.py`, called from FastAPI lifespan handler in `main.py`. Avoids import-time failures that break testing. Added `main.py` to essential files list.

6. **[REQ-008] Document confidence caveat -- RESOLVED.** Added explicit caveat: confidence reflects the sampled portion (first ~5KB), not the full document. API field description text specified. Users informed that high confidence does not guarantee document-wide language homogeneity.

7. **[REQ-015 vs RISK-002] Confidence display contradiction -- RESOLVED.** Changed from percentage display to qualitative labels: High (>= 0.8), Medium (>= 0.5), Low (< 0.5), None (0.0 fallback). Rationale: Lingua scores are not calibrated probabilities. Raw numeric value remains in API response for programmatic consumers. RISK-002 updated to reference the qualitative label approach.

8. **[Confidence + timeout interaction] -- RESOLVED.** Added to REQ-005: both `detect_language_of()` and `compute_language_confidence_values()` run inside `_detect_sync()` within the shared timeout. If confidence fails but detection succeeded, return `confidence: null` (not `0.0`). Distinction documented: `null` = unavailable, `0.0` = fallback.

### MEDIUM Findings (Missing Specifications)

9. **[Adversarial language-flip] Dropped from research -- RESOLVED.** Added as EDGE-010. Accepted as v1 known limitation (enterprise context, low probability). Confidence score partially mitigates. Documented for known-limitations.

10. **[Structured log field specification] -- RESOLVED.** Added to SEC-001: defined exact field names and types (`language_detected: str`, `language_confidence: float | None`, `language_fallback: bool`, `language_fallback_reason: str` with enumerated values). Implementation notes Step 2 updated to reference SEC-001.

### LOW Findings

11. **[REQ-013] UI toggle limitation note -- RESOLVED.** Added operator documentation note: adding languages to `supported_languages` enables API and auto-detection but does not add UI toggles until post-v1. Must be documented in deployment docs.

12. **[PERF-001 vs research timeout] -- RESOLVED.** PERF-001 updated to acknowledge the timeout was not empirically profiled. Accepted as-is for v1 with rationale (EN/DE binary detection is fast). Documented that production monitoring of fallback rates (FAIL-003 logs) should inform tuning. Timeout is configurable without code changes.

### Research Disconnects

13. **[Empirical accuracy testing] -- RESOLVED.** See HIGH finding #3 above.

14. **[`minimum_relative_distance(0.25)` not validated] -- RESOLVED.** Added note to RISK-002 that the threshold is provisional and may need tuning based on production fallback rates.

15. **[UI toggle not updating after detection] -- RESOLVED.** Added as known UX limitation in UX-003. Deferred to post-v1.

16. **[Timeout not profiled] -- RESOLVED.** See LOW finding #12 above.

17. **[DPO quantified accuracy data] -- RESOLVED.** Addressed by EDGE-008 GDPR accuracy tests.

18. **[Operations confidence distribution monitoring] -- RESOLVED.** Structured log fields (SEC-001) enable log aggregation for confidence distribution monitoring. No additional metrics endpoint required for v1.

### Untestable Criteria

19. **[UX-001 "just works"] -- ACKNOWLEDGED.** Subjective criterion; already implemented. No change needed. Validated through E2E tests (auto-detect produces correct results for representative content).

20. **[UX-002 "positioned near"] -- ACKNOWLEDGED.** Already implemented, layout not changing. Moot point.

21. **[EDGE-001 mixed content confidence assertion] -- RESOLVED.** Test approach updated to not assert confidence is strictly lower for mixed content. Instead, verify confidence is returned and dominant language detected correctly.
