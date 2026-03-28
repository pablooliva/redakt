# Implementation Critical Review: PII Detection

## Executive Summary

The implementation covers the spec's surface area well — all 9 REQs have corresponding code and 28 unit tests pass. However, the review found **2 HIGH severity bugs** (broken allow_list Presidio integration, response_model union stripping verbose output), **3 MEDIUM issues** (duplicated detection logic, missing web UI input validation, deprecated asyncio API), and several LOW items. The issues are fixable without architectural changes.

### Severity: HIGH

---

## Specification Violations

### 1. **Presidio `allow_list` integration is wrong** — HIGH

- **Location:** `services/presidio.py:28-37`
- **Specified (SPEC REQ-005):** Allow list passed to Presidio's `allow_list` parameter
- **Implemented:** Sends both a top-level `allow_list` AND a bogus `ad_hoc_recognizers` entry with an empty `deny_list`. The `ad_hoc_recognizers` block is nonsensical — it creates an "AllowListRecognizer" that recognizes nothing.
- **Verified against Presidio source:** `presidio-analyzer/app.py:96` shows `allow_list` is a simple top-level parameter on `AnalyzerRequest`. No ad_hoc_recognizer is needed.
- **Impact:** The spurious ad_hoc_recognizer may confuse Presidio or cause unexpected behavior. The `allow_list` top-level param alone is sufficient and correct.
- **Fix:** Remove the entire `ad_hoc_recognizers` block. Keep only `payload["allow_list"] = allow_list`.

### 2. **`response_model` union may strip `details` from verbose responses** — HIGH

- **Location:** `routers/detect.py:24-27`
- **Specified (SPEC REQ-004):** When `?verbose=true`, response includes `details` array
- **Implemented:** `response_model=DetectResponse | DetectDetailedResponse` — FastAPI validates the response against this union. Since `DetectResponse` matches first (it's a subset of `DetectDetailedResponse`), FastAPI may serialize using `DetectResponse` and strip the `details` field.
- **Impact:** Verbose mode may silently return responses without `details`, violating REQ-004.
- **Fix:** Remove `response_model` from the decorator entirely (let FastAPI infer from return type), or use `response_model=None` and handle serialization manually.

### 3. **Empty text + unsupported language returns 400 instead of EDGE-001 response** — MEDIUM

- **Location:** `routers/detect.py:35-51`
- **Specified (SPEC EDGE-001):** Empty text returns `{"has_pii": false, ...}`
- **Implemented:** Language validation happens BEFORE the empty text check. So `{"text": "", "language": "ja"}` returns HTTP 400 instead of the EDGE-001 empty response.
- **Impact:** Edge case mismatch. Empty text should short-circuit before language validation.
- **Fix:** Move the empty text check above language resolution.

---

## Technical Vulnerabilities

### 4. **Web UI `/detect/submit` has no text size limit** — MEDIUM

- **Location:** `routers/pages.py:27`
- **Specified (SPEC SEC-001):** Text input capped at 500KB
- **Implemented:** `text: str = Form("")` — no max_length. The API route enforces this via Pydantic's `max_length=512_000`, but the HTMX form route bypasses it entirely.
- **Attack vector:** A user (or bot) could POST megabytes of text to `/detect/submit`, which gets forwarded to Presidio with no size guard.
- **Fix:** Add length validation in the route: `if len(text) > 512_000: return error template`.

### 5. **`asyncio.get_event_loop()` deprecated in Python 3.12** — MEDIUM

- **Location:** `services/language.py:30`
- **Implemented:** `asyncio.get_event_loop().run_in_executor(None, _detect_sync, text)`
- **Impact:** Emits a DeprecationWarning in Python 3.12+. Will break in a future Python version.
- **Fix:** Replace with `asyncio.get_running_loop().run_in_executor(...)`.

### 6. **Detection logic duplicated between API and web routes** — MEDIUM

- **Location:** `routers/detect.py` vs `routers/pages.py`
- **Impact:** The `/detect/submit` route reimplements the entire detection flow (language resolution, validation, Presidio call, allow_list merge, audit logging) separately from `/api/detect`. Changes must be made in two places. The web route is already missing: allow_list merge, custom entities, custom score_threshold, and size validation.
- **Fix:** Extract a shared `run_detection()` function called by both routes.

---

## Test Gaps

### 7. **No test for EDGE-009: score_threshold=0.0**

- Spec explicitly requires testing that `score_threshold: 0.0` is allowed and returns more results.
- Current tests never submit `score_threshold: 0.0`.

### 8. **No test for EDGE-010: mixed-language text**

- Spec says to verify pattern-based entities are detected in mixed text.
- Would require integration test, but no placeholder or mock test exists.

### 9. **No test for web UI `/detect/submit` route**

- All 28 tests cover `/api/detect`, health, presidio client, and language detection.
- Zero tests for the HTMX form submission path, which has its own bugs (no size limit, no allow_list).

### 10. **`test_health_presidio_down` only tests both-down scenario**

- The mock patches `check_health` to return `False` for ALL calls. Doesn't test partial degradation (analyzer up, anonymizer down or vice versa).

### 11. **`test_detect_allow_list_merge` won't catch the ad_hoc_recognizers bug**

- The test mocks `PresidioClient.analyze` entirely, so the bogus `ad_hoc_recognizers` payload is never constructed or validated. The real Presidio integration is untested.

---

## Low Severity Items

### 12. **`score_threshold` default hardcoded in model AND config** — LOW

- `DetectRequest.score_threshold` defaults to `0.35` (hardcoded in Pydantic model)
- `config.py` also has `default_score_threshold: float = 0.35`
- If someone changes the config default, the API model won't reflect it.
- Minor: could use `Field(default=None)` and fall back to config in the router.

### 13. **`config/spacy_multilingual.yaml` is orphaned** — LOW

- Created during scaffolding, but the volume mount was removed. The presidio fork's yaml was edited directly instead. This file serves no purpose.
- Fix: Delete `config/spacy_multilingual.yaml` and the `config/` directory.

### 14. **Dockerfile health check depends on Presidio** — LOW

- Docker's `HEALTHCHECK` calls `/api/health`, which checks Presidio connectivity. If Presidio is slow, Docker may restart Redakt (which is actually healthy).
- Consider: A `/api/health/live` endpoint (always 200) for Docker, keep `/api/health` as readiness.

### 15. **No `networks` configuration in docker-compose** — LOW

- SEC-002 says Presidio should be on internal network. Docker Compose's default bridge works (no ports exposed), but an explicit internal network would be more defensive.

---

## Recommended Actions Before Proceeding

| Priority | Action | Findings |
|----------|--------|----------|
| **P0** | Fix allow_list — remove `ad_hoc_recognizers` block from `presidio.py` | #1 |
| **P0** | Fix response_model — remove union or use `response_model=None` on detect endpoint | #2 |
| **P1** | Move empty text check before language validation in `detect.py` | #3 |
| **P1** | Add text size validation to `/detect/submit` | #4 |
| **P1** | Replace `get_event_loop()` with `get_running_loop()` | #5 |
| **P1** | Extract shared detection logic from both routes | #6 |
| **P2** | Add missing tests (EDGE-009, web UI route, partial health degradation) | #7-11 |
| **P3** | Clean up orphaned config file, consider liveness endpoint | #12-15 |

---

## Proceed/Hold Decision

**HOLD — fix P0 items before Docker integration testing.** The allow_list bug will cause incorrect Presidio API calls in production, and the response_model issue may silently break verbose mode. Both are quick fixes. P1 items should be addressed in the same pass.
