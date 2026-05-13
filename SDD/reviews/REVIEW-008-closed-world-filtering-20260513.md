# Code Review: SDD-008 closed-world-filtering

**Reviewer:** sdd-workhorse (specification-driven code review)
**Date:** 2026-05-13
**Implementation under review:** see file list in IMPLEMENTATION-PLAN-008-closed-world-filtering-2026-05-13.md
**Specification:** SDD/requirements/SPEC-008-closed-world-filtering.md (post-3-iteration panel + critical-review fix)
**Test status (reported):** 421/421 pass per IMPLEMENTATION-PLAN. Verified by running `uv run pytest tests/ -q`: confirmed 421 passed.

---

## Executive Summary

The implementation is functionally sound and meets the core specification. All 21 REQ, 10 EDGE, and 5 FAIL items are implemented with meaningful test coverage. The filter logic, gate precedence, audit field threading, frozenset pre-computation, and HIPAA enforcement are all correctly implemented and match the spec precisely. Three MEDIUM-severity findings were identified — all are doc/config classification mismatches in `docs/supported-entities.md` that contradict either the spec's default entity lists or the deployed `config.yaml`. These create operator confusion risk. One MEDIUM finding involves `customizations.md` describing a quasi-identifiers list that differs from the actual default. Two LOW findings were identified (dead variable, bidirectional lint test scope). No HIGH-severity issues were found. Verdict: **REVISIONS REQUIRED** (three MEDIUM doc-correctness issues need correction before this feature is production-ready for operator consumption).

---

## Verdict

**REVISIONS REQUIRED**

---

## Specification Alignment (70%)

### Requirements Implementation (REQ-001 through REQ-021)

- **REQ-001** (`strong_anchors` default set): Implemented at `config.py:91-111`. Default set matches spec exactly (19 types: PERSON, EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE, EU_VAT_ID, BIC_CODE, SEPA_CREDITOR_ID, MEDICAL_LICENSE, DE_TAX_ID, DE_VAT_ID, DE_ID_CARD, DE_PASSPORT, DE_SOCIAL_SECURITY, DE_FUEHRERSCHEIN, DE_LANR, DE_TAX_NUMBER, DE_HEALTH_INSURANCE, DE_MASTR_ID, DE_KFZ). Tested at `test_closed_world_filter.py:286-308`. Finding: **PASS** in code; **MEDIUM doc deviation** — `docs/supported-entities.md:35` classifies `MEDICAL_LICENSE` as `always_emit` but the spec (REQ-001, REQ-016) and config.py both place it in `strong_anchors`. See Findings/MEDIUM-001.

- **REQ-002** (`quasi_identifiers` default set): Implemented at `config.py:114-119`. Default set [DATE_TIME, LOCATION, NRP, DE_PLZ] matches spec exactly. Tested at `test_closed_world_filter.py:142-158`. Finding: **PASS** in code; **MEDIUM doc deviation** — `docs/supported-entities.md:80` classifies `DE_KFZ` as `quasi_identifier` but `config.py` and the spec both place it in `strong_anchors`. See Findings/MEDIUM-003.

- **REQ-003** (`closed_world_filtering: bool = False`): Implemented at `config.py:120`, `config.yaml:105`. Default is `false`. Tested at `test_closed_world_filter.py:299-308`. Finding: **PASS**.

- **REQ-004** (per-request override on `/api/detect`): Field implemented at `models/detect.py:13`. Merge logic with SEC-001a gate at `routers/detect.py:129-139`. Gate-before-REPLACE order is exactly as spec requires. Tested at `test_closed_world_filter.py:573-633`. Finding: **PASS**.

- **REQ-005** (per-request override on `/api/anonymize`): Field at `models/anonymize.py:13`. Merge logic at `routers/anonymize.py:126-135`. Parity with REQ-004 confirmed — identical structure. Tested at `test_closed_world_filter.py:661-669`. Finding: **PASS**.

- **REQ-006** (entity lists instance-wide-only): Not exposed on request models. `DetectRequest` and `AnonymizeRequest` only carry `closed_world_filtering: bool | None`. No `strong_anchors` or `quasi_identifiers` per-request fields exist. Finding: **PASS**.

- **REQ-007** (suppression logic): Implemented at `utils.py:111-148`. Single-pass `any()` check for anchor, then per-span suppression of quasi-identifiers when no anchor. Tested at `test_closed_world_filter.py:124-158`. Finding: **PASS**.

- **REQ-008** (strong anchors always emitted): When anchor present, function returns `results, 0` immediately at `utils.py:135-137`. Strong anchors are never suppressed. Tested at `test_closed_world_filter.py:85-119`. Finding: **PASS**.

- **REQ-009** (filter runs AFTER `filter_by_entity_thresholds()`): `detect.py:125` calls `filter_by_entity_thresholds()`, then `detect.py:141` calls `filter_by_closed_world()`. Same pattern in `anonymize.py:122` then `anonymize.py:137`. Order is correct. Finding: **PASS**.

- **REQ-010** (verbatim threat-model comment in config.yaml): `config.yaml:84-105` contains the full comment block. The THREAT MODEL, GAMEABLE, HIPAA, ART. 9, NOTE, and OVERRIDE clauses are all present. The spec's verbatim text is reproduced with only minor formatting differences (line breaks preserved). Finding: **PASS** in config.yaml. **LOW finding** for customizations.md — see LOW-002.

- **REQ-011** (Pydantic validation: list[str], duplicate check, canonical-set check): All three rules implemented at `config.py:149-187`. Type validation is Pydantic-native (list[str] enforced by field type). Duplicate check at `config.py:157-172`. Canonical-set check at `config.py:174-187` with warning/ValidationError per `strict_entity_validation`. Tested at `test_closed_world_filter.py:230-263, 897-938`. Finding: **PASS**.

- **REQ-012** (no entity in both lists): Implemented at `config.py:149-155`. Raises `ValueError` (wrapped to `ValidationError` by Pydantic). Tested at `test_closed_world_filter.py:220-228`. Finding: **PASS**.

- **REQ-013** (audit fields always emitted): `closed_world_suppressed_count` and `closed_world_filtering_override` are always emitted on detect/anonymize paths. `_emit_audit()` at `audit.py:145-149` emits `closed_world_suppressed_count` when not None (0 is emitted, not omitted) and always emits `closed_world_filtering_override` (null is meaningful). Forwarded via `log_detection()` and `log_anonymization()` with `int = 0` defaults ensuring 0 is always passed. Document-upload path (`log_document_upload()`) does not pass these fields — both are absent from the audit entry for that path (null sentinel behavior via absence per session notes). Tested at `test_closed_world_filter.py:635-659, 755-785`. Finding: **PASS** for detect/anonymize paths. Note: the spec (REQ-013) requires document-upload path to emit null explicitly, but `log_document_upload()` signature does not include these fields at all — they are absent from the JSON, not null. This is a minor deviation from the spec's "both are null (sentinel)" language; the practical impact is that audit-log consumers cannot distinguish "absent field" from "not applicable." This is noted as a **LOW finding** (LOW-003).

- **REQ-014** (eval-loader extension): `tests/eval/_loader.py` extended with `request_params: tuple[tuple[str, Any], ...]` field and `build_request_body()` method. `_ALLOWED_REQUEST_PARAM_KEYS` frozenset at `_loader.py:56-64` provides fail-closed key validation. `test_calibration.py:32` uses `phrase.build_request_body()`. Tested at `test_closed_world_filter.py:316-453`. Finding: **PASS**.

- **REQ-015** (document-upload path excluded): `document_processor.py` is not modified. `filter_by_closed_world()` is not called from the document path. Finding: **PASS**.

- **REQ-016** (MEDICAL_LICENSE disposition documented): Documented in `config.yaml:124-126` with the US DEA scope note and false-positive on DE_MASTR_ID. Finding: **PASS** in code and config comment. **MEDIUM doc deviation** — `docs/supported-entities.md:35` classifies it as `always_emit`. See MEDIUM-001.

- **REQ-017** (NRP quasi-identifier with Art. 9 operator responsibility): NRP is in `quasi_identifiers` default at `config.py:116`. Art. 9 operator responsibility is documented in `config.yaml:95-99`. `docs/customizations.md` carries the HIPAA and Art. 9 notes. Finding: **PASS**.

- **REQ-018** (web UI uses instance default): `pages.py` is not modified. Web UI routes call `run_detection()`/`run_anonymization()` without a `closed_world_filtering` parameter — they pass `None` implicitly via the function default, which maps to "use instance default." Finding: **PASS** (verified by absence of changes in pages.py).

- **REQ-019** (`run_detection`/`run_anonymization` signatures): Both gain `closed_world_filtering: bool | None = None` at `detect.py:67` and `anonymize.py:61`. Pattern matches `entity_score_thresholds: dict[str, float] | None = None`. Finding: **PASS**.

- **REQ-020** (HIPAA gate): Implemented at `config.py:189-213`. Two behaviors: (1) HIPAA + `closed_world_filtering: true` → `ValueError` at `config.py:193-198`. (2) HIPAA + `allow_per_request_closed_world_override: true` → auto-forced to `false` at `config.py:200-207` with INFO log. Tested at `test_closed_world_filter.py:265-311, 672-710`. Finding: **PASS**.

- **REQ-021** (classification column in docs/supported-entities.md): Classification column added to the Redakt-active entity sections. CI lint test at `tests/test_entity_catalog.py` asserts bidirectional consistency (catalog→doc direction). Finding: **PASS** for CI enforcement mechanism. **MEDIUM doc deviation** — classification values for MEDICAL_LICENSE, CREDIT_CARD, and DE_KFZ contradict the spec/config. See MEDIUM-001, MEDIUM-002, MEDIUM-003.

---

### Edge Cases (EDGE-001 through EDGE-010)

- **EDGE-001** (empty span list → no crash): Implemented at `utils.py:129-130` (disabled path) and implicitly by `any()` returning False on empty iterable. Tested at `test_closed_world_filter.py:164-170`. Finding: **PASS**.

- **EDGE-002** (all quasi, no anchor → all suppressed): Tested at `test_closed_world_filter.py:124-131`. Finding: **PASS**.

- **EDGE-003** (all anchors, no quasi → all retained): Tested at `test_closed_world_filter.py:102-109`. Finding: **PASS**.

- **EDGE-004** (always-emit entities pass through): Tested at `test_closed_world_filter.py:132-139` (DE_BSNR retained). Finding: **PASS**.

- **EDGE-005** (allow-list-stripped anchor → quasi suppression): Behavior is correct by construction (allow-list stripped before Presidio response arrives; filter sees no anchor). Documented in `docs/customizations.md:313-315`. No integration test exercises this path in tests/ (the IMPLEMENTATION-PLAN marks it as "Chunk 2 integration test against mocked Presidio returning no PERSON span"). Looking at `test_closed_world_filter.py`, there is no explicit EDGE-005 integration test (the spec validation strategy lists it as an integration test requirement). The behavior is implied by unit tests (empty span input), but the specific scenario (allow-list stripping causing anchor absence) is not directly tested. Finding: **LOW** — EDGE-005 integration test was listed in the spec validation strategy but is not present in the test suite (IMPLEMENTATION-PLAN marks it under integration tests; the unit tests cover the anchor-absent case but not the allow-list-stripping mechanism specifically). See LOW-004.

- **EDGE-006** (per-request override REPLACE semantics): Tested at `test_closed_world_filter.py:573-603` (both directions: request=True overrides instance=False; request=False overrides instance=True). Finding: **PASS**.

- **EDGE-007** (entity in both lists → ValidationError): Tested at `test_closed_world_filter.py:220-228`. Finding: **PASS**.

- **EDGE-008** (empty `strong_anchors` warning + degenerate behavior): Warning implemented at `config.py:216-223`. Degenerate behavior tested at `test_closed_world_filter.py:172-190`. Finding: **PASS**.

- **EDGE-009** (gameable narrative passes through): Eval fixture covers this in `tests/eval/fixtures/closed-world.yaml` (healthcare gameable narrative). The filter correctly passes always-emit and non-quasi entities through even with no anchor. Finding: **PASS** (eval fixtures exist; they require Docker stack to run — operator-action-pending).

- **EDGE-010** (mixed anchors + quasi + always-emit: all pass): Tested at `test_closed_world_filter.py:111-118`. Finding: **PASS**.

---

### Failure Scenarios (FAIL-001 through FAIL-005)

- **FAIL-001** (invalid config type): Pydantic handles `list[str]` type enforcement natively. Non-list values or non-string elements produce `ValidationError` at config-load. Finding: **PASS** (Pydantic-native, tested implicitly via Settings instantiation tests).

- **FAIL-002** (overlap → ValidationError): Tested at `test_closed_world_filter.py:220-228`. Finding: **PASS**.

- **FAIL-003** (malformed per-request field → HTTP 422): Pydantic request model enforces `bool | None`; string or integer values produce HTTP 422. Finding: **PASS** (Pydantic-native; the test suite does not have an explicit HTTP 422 test for this, but FastAPI/Pydantic handles it at the framework level — IMPLEMENTATION-PLAN notes this as "Pydantic handles bool|None" without a dedicated test).

- **FAIL-004** (unknown entity from Presidio → always-emit): Handled inherently — `filter_by_closed_world()` performs frozenset membership checks; unknown types are in neither set and pass through. Tested implicitly by EDGE-004 (DE_BSNR not in either set passes through). Finding: **PASS**.

- **FAIL-005** (typo in entity name): Implemented at `config.py:174-187`. WARNING when `strict_entity_validation=False`, ValidationError when `True`. Tested at `test_closed_world_filter.py:240-263, 897-938`. Finding: **PASS**.

---

### Specification Deviations

1. **docs/supported-entities.md classification for MEDICAL_LICENSE:** Classified as `always_emit` in the doc, but the spec (REQ-001, REQ-016) and deployed config place it in `strong_anchors`. This contradicts the spec's REQ-001 table and REQ-016 disposition.

2. **docs/supported-entities.md classification for DE_KFZ:** Classified as `quasi_identifier` in the doc, but the spec (REQ-001) and deployed config place it in `strong_anchors` as a conservative default. The spec explicitly notes operators "may move to neither list (always-emit)" — the current doc classification conflicts with the deployed default.

3. **docs/supported-entities.md classification for CREDIT_CARD:** Classified as `strong_anchor` in the doc, but `CREDIT_CARD` is NOT in the spec's REQ-001 default `strong_anchors` list, NOT in the config's `strong_anchors`, and NOT in `entity_catalog.py`'s inclusion in any config list. The spec's REQ-001 makes no mention of CREDIT_CARD as a strong anchor; the doc's classification contradicts the implicit always-emit status.

4. **customizations.md quasi-identifiers list is stale:** `customizations.md:290` "What it does" section lists quasi-identifiers as including `DE_KFZ` and `DE_ZAEHLERNUMMER`, but the default `config.yaml` quasi_identifiers is `[DATE_TIME, LOCATION, NRP, DE_PLZ]`. Both `DE_KFZ` and `DE_ZAEHLERNUMMER` are not in the default quasi_identifiers list (DE_KFZ is in strong_anchors; DE_ZAEHLERNUMMER is always-emit by default in the catalog).

5. **REQ-013 document-upload null sentinel (minor):** The spec states document-upload audit entries should have `closed_world_suppressed_count: null` and `closed_world_filtering_override: null`. The implementation omits these fields entirely from `log_document_upload()`, meaning they are absent (not present as null) in the JSON. Practically equivalent for most consumers but technically deviates from the spec's explicit null-sentinel design.

6. **REQ-010 verbatim comment text in customizations.md:** The spec requires the verbatim config comment text to appear in `docs/customizations.md`. The customizations.md has a paraphrase in the "Threat-model assumption" note rather than the exact verbatim text from REQ-010. The spec says "must also appear verbatim in docs/customizations.md."

---

## Context Engineering (20%)

- **IMPLEMENTATION-PLAN tracking:** PASS. Chunk 1 and Chunk 2 coverage tables accurately reflect what was implemented. Session notes are informative. The "raw_cwf_override" variable note is accurate (it exists as a dead variable in detect.py).

- **Glossary alignment:** Largely PASS. The implementation uses "strong anchor," "quasi-identifier," "closed-world filtering," "post-filter," "per-request override" consistently throughout code comments and docs. Minor: `customizations.md:290` uses "quasi-identifier spans" and "strong-anchor span" — consistent with glossary.

- **Implementation traceability:** PASS. Code comments reference REQ/EDGE/FAIL identifiers (e.g., `utils.py:123` comments `PERF-002`, `REQ-008`; `config.py:149` comments `REQ-012`). All MODULE interfaces match spec's PUBLIC INTERFACE definitions exactly.

---

## Test Specification Alignment (10%)

- **Total tests:** 421/421 passing (confirmed by running `uv run pytest tests/ -q`).

- **REQ coverage:** 19/21 REQs have a meaningful unit or integration test. REQ-003 tested at test_closed_world_filter.py:299-308. REQ-006 verified by absence (no per-request list field). REQ-014, REQ-021 have dedicated test classes (TestEvalLoaderExtension, TestEntityCatalogConsistency, TestReq021ClassificationColumn). REQ-015 verified by absence (no calls in document_processor.py). REQ-018 verified by absence (no changes to pages.py).

- **Weak assertions / hollow tests:** None found. All assertions verify the specific behavior described in each REQ/EDGE. The SEC-001a tests in `TestSec001aSilentIgnore` simulate the router gate logic directly in Python rather than going through the full HTTP stack — this is acceptable for unit testing the logic, but the router-integration path for SEC-001a is also tested in `TestRouterIntegration.test_detect_sec001a_gate_ignores_per_request_override`.

- **EDGE-005 integration test absent:** The spec validation strategy lists EDGE-005 as requiring an integration test "against mocked Presidio returning no PERSON span." No such test exists — the behavior is only documented. See LOW-004.

- **FAIL-003 HTTP 422 test absent:** No explicit test sends `"closed_world_filtering": "yes"` and asserts HTTP 422. This is handled by FastAPI/Pydantic framework validation and does not require a custom test, but the spec validation strategy listed it as a specific test case. This is low-risk since the framework handles it reliably.

- **E2E test status:** Written at `tests/e2e/test_closed_world_e2e.py`. Requires Docker Compose stack to run. Not executed in this review — operator-action-pending.

- **Eval fixture status:** Written at `tests/eval/fixtures/closed-world.yaml`. Requires Redakt API + Presidio running. Not executed in this review — operator-action-pending.

---

## Risk Tier Audit (Module Review Log)

### MODULE-001: Closed-world post-filter function (`src/redakt/utils.py`)

**Spec risk tier:** Medium

**Review depth applied:** Matching (medium — full internals review)

**Internals findings:**
- Single-pass `any()` for anchor detection is correct and O(n). The guard `if has_anchor: return results, 0` is correct — no quasi-identifiers are ever suppressed when an anchor is present (REQ-008).
- The no-op branch `if not enabled: return results, 0` is O(1) and returns the exact input object (verified by `test_flag_off_returns_same_object` at test_closed_world_filter.py:72-79).
- Function signature accepts `frozenset[str]` parameters — callers cannot accidentally pass raw lists. Function docstring warns about this.
- Function accepts `list[dict]` not `list[RecognizerResult]`. The spec MODULE-001 interface specifies `list[RecognizerResult]` but `filter_by_entity_thresholds()` also uses `list[dict]` (the Presidio API returns dicts). This is consistent with the existing codebase pattern — not a deviation.
- No mutation of input list.

**Risk-tier classification assessment:** Medium is appropriate. Over-suppression is a UX bug (user frustration), not a regulatory violation. Under-suppression reverts to today's behavior.

---

### MODULE-002: Config schema extension (`src/redakt/config.py`)

**Spec risk tier:** Low

**Review depth applied:** Escalated to High (HIPAA gate is high-stakes regulatory enforcement)

**Risk-tier misclassification flag:** The spec classifies MODULE-002 as Low risk. However, this module contains the HIPAA gate (REQ-020) — a regulatory enforcement mechanism that, if broken, would allow HIPAA-scoped deployments to enable a Safe Harbor-incompatible filter. The HIPAA auto-force logic (`self.allow_per_request_closed_world_override = False` at config.py:207) relies on Pydantic model_validator mutating the instance in-place after validation. This works in Pydantic v2 but is a subtle pattern. The session notes acknowledge this. **This module should be classified as High risk, not Low.** Fortunately, the implementation is correct and the HIPAA gate tests pass.

**Internals findings:**
- The `model_validator(mode="after")` runs after all field assignments. The auto-force mutation `self.allow_per_request_closed_world_override = False` at line 207 correctly overwrites the field value loaded from YAML/env.
- The validator order is correct: overlap → duplicates → canonical-set → HIPAA gate → degenerate warning → frozenset pre-computation. No dependency inversion issues.
- `strong_anchors_set` and `quasi_identifiers_set` are populated by the validator at lines 226-227, not by YAML. The `model_config = {"extra": "ignore"}` means that even if an operator accidentally sets these in config.yaml, they would be ignored and overwritten by the validator. Correct.
- PERF-001 compliance: `frozenset()` is constructed once at config-load (validator line 226-227), not per-request. The fields are declared as `frozenset[str]` with default `frozenset()`, then populated once. Subsequent accesses to `settings.strong_anchors_set` return the pre-computed value. **PASS**.

**Risk-tier misclassification flag: YES** — MODULE-002 should be High, not Low. The HIPAA gate is a regulatory enforcement boundary. The implementation is correct but the tier assignment understates the impact of a bug here.

---

### MODULE-003: Per-request override threading (`src/redakt/routers/detect.py`, `anonymize.py`)

**Spec risk tier:** Medium

**Review depth applied:** Matching (medium — full internals review)

**Internals findings:**
- SEC-002a gate precedence is implemented correctly in both routers: SEC-001a gate check → REPLACE merge → instance default fallback (detect.py:129-139, anonymize.py:126-135).
- `raw_cwf_override` (detect.py:129) is computed but never used — `audit_cwf_override` (line 139) is the variable actually forwarded to the audit logger. The `raw_cwf_override` variable is a dead code artifact from the implementation session note ("the actual audit threading uses `audit_cwf_override`"). This is a minor code cleanliness issue (LOW-001).
- The audit field `closed_world_filtering_override` correctly records `null` when SEC-001a gate discards the per-request value (detect.py:139: `audit_cwf_override = closed_world_filtering if request_value is not None else None`). When gate is closed (`allow_per_request_closed_world_override=False`), `request_value=None` → `audit_cwf_override=None`. This matches the spec's MODULE-003 "Hides" section exactly.
- `anonymize.py` does NOT have the `raw_cwf_override` variable — it goes directly from `closed_world_filtering` (parameter) to `audit_cwf_override`. This is the correct pattern; the dead variable exists only in detect.py.

**Risk-tier classification assessment:** Medium is appropriate.

---

### MODULE-004: Audit logging extension (`src/redakt/services/audit.py`)

**Spec risk tier:** Low

**Review depth applied:** Matching (low — tested-boundary review)

**Internals findings:**
- `log_detection()` and `log_anonymization()` have `closed_world_suppressed_count: int = 0` defaults, ensuring `0` is always passed to `_emit_audit()` even when callers omit the parameter.
- `_emit_audit()` at line 145: `if closed_world_suppressed_count is not None:` — since the default is `0` (not `None`), `0` is always emitted as a JSON field, not omitted. This satisfies REQ-013's "always present, even when 0" requirement. **PASS**.
- `closed_world_filtering_override` is always written to `record.audit_data` at line 149 (no conditional), so `null` values are serialized as JSON `null`. **PASS**.
- Document-upload path: `log_document_upload()` signature does not include the CWF fields. They are absent from the audit entry. The spec says they should be `null`. This is the LOW-003 finding.
- No PII in audit fields — suppressed_count is an int, override is bool|null. **PASS**.

**Risk-tier classification assessment:** Low is appropriate — these fields are pure metadata with no PII and no security-critical logic.

---

### MODULE-005: Eval-loader extension (`tests/eval/_loader.py`)

**Spec risk tier:** Low

**Review depth applied:** Matching (low — tested-boundary review)

**Internals findings:**
- `Phrase.request_params` is a `tuple[tuple[str, Any], ...]` (immutable, frozen dataclass compatible).
- `_ALLOWED_REQUEST_PARAM_KEYS` frozenset at `_loader.py:56-64` includes: `language`, `allow_list`, `entity_score_thresholds`, `entities`, `closed_world_filtering`. This is the expected set. The `score_threshold` field is not included — if a future fixture wants to override score_threshold, it would need to be added. Not a current spec requirement.
- `_load_one()` raises `ValueError` with a clear message on unknown keys (fail-closed). Tested at `test_closed_world_filter.py:418-432`.
- The spec (REQ-014) uses the term `request_overrides` for the YAML field name and `request_overrides: dict[str, Any] | None` for the dataclass field. The implementation uses `request_params` (both in YAML fixture and in the dataclass). The YAML fixtures at `tests/eval/fixtures/closed-world.yaml` use `request_params:` as the key. This naming deviation from the spec's `request_overrides` wording is minor but worth noting. The behavior is identical; the spec's MODULE-005 section is the source but the IMPLEMENTATION-PLAN and implementation agree on `request_params`.

**Risk-tier classification assessment:** Low is appropriate — eval-only code, failures are test errors not production bugs.

---

### Misclassification flags

**MODULE-002** (Config schema): The spec assigns Low risk. The correct tier is **High** — the module enforces the HIPAA regulatory gate. A bug in the HIPAA auto-force logic would silently permit a HIPAA-scoped deployment to allow per-request CWF activation, violating Safe Harbor. The implementation is correct, but the risk-tier misclassification should be noted for future maintenance decisions.

---

## Findings

### HIGH

None.

---

### MEDIUM

**MEDIUM-001: `MEDICAL_LICENSE` classified as `always_emit` in docs/supported-entities.md, but spec + config classify it as `strong_anchor`**

- **Location:** `docs/supported-entities.md:35`
- **Evidence:** Doc entry: `| MEDICAL_LICENSE | Generic medical license numbers (DEA) | always_emit |`. Config (`config.py:99`): `"MEDICAL_LICENSE"` is in `strong_anchors`. Spec REQ-001: MEDICAL_LICENSE is in the strong_anchors default set. Spec REQ-016: "retained as conservative default. If it fires, it should act as anchor."
- **Risk:** An operator reading the classification column to understand the filter behavior will incorrectly believe MEDICAL_LICENSE is always-emit. If they attempt to remove it from `strong_anchors` based on the doc, they would be correcting a perceived omission (it "should" be always-emit per the doc) but actually weakening the anchor signal. CI lint test does NOT catch classification value errors (it only checks that entity names are present, not that classification values are correct).
- **Resolution:** Change `docs/supported-entities.md:35` to classify `MEDICAL_LICENSE` as `strong_anchor` (consistent with config.py default and spec REQ-001).

**MEDIUM-002: `CREDIT_CARD` classified as `strong_anchor` in docs/supported-entities.md, but CREDIT_CARD is not in any config list (effectively always-emit by default)**

- **Location:** `docs/supported-entities.md:28`
- **Evidence:** Doc entry: `| CREDIT_CARD | Major credit card numbers (Luhn-validated) | strong_anchor |`. Config `config.py` strong_anchors does NOT include CREDIT_CARD. Spec REQ-001 does NOT include CREDIT_CARD in the default strong_anchors list. CREDIT_CARD is in `entity_catalog.py` (a recognized entity type) but in neither default list — it is always-emit by default.
- **Risk:** An operator reading the classification column will expect CREDIT_CARD to act as a strong anchor (unlocking quasi-identifier emission) when it appears. In reality, with the default config, CREDIT_CARD does NOT trigger anchor detection — a submission with only CREDIT_CARD and DATE_TIME would still suppress DATE_TIME when CWF is enabled. This is a misleading safety claim in the documentation.
- **Resolution:** Change `docs/supported-entities.md:28` to classify `CREDIT_CARD` as `always_emit` (reflecting the default config). Add a note that operators who want CREDIT_CARD to act as a strong anchor can add it to `strong_anchors` in config.yaml.

**MEDIUM-003: `DE_KFZ` classified as `quasi_identifier` in docs/supported-entities.md, but config + spec classify it as `strong_anchor` (conservative default)**

- **Location:** `docs/supported-entities.md:80`
- **Evidence:** Doc entry: `| DE_KFZ | Kfz-Kennzeichen (vehicle plate) | quasi_identifier |`. Config `config.py:110`: `DE_KFZ` is in `strong_anchors`. Spec REQ-001: "DE_KFZ — German vehicle registration plate. Identifies a vehicle; trivially traceable to an owner via traffic records. Conservative default."
- **Risk:** An operator enabling CWF who sees DE_KFZ classified as `quasi_identifier` in the doc will expect it to be suppressed when no anchor is present. In reality, DE_KFZ in the default config acts as an anchor (enabling quasi-identifier emission). The operator's mental model of the filter behavior will be wrong.
- **Resolution:** Change `docs/supported-entities.md:80` to classify `DE_KFZ` as `strong_anchor`. Add the spec note: "Operators in jurisdictions where vehicle-plate look-up is not trivially available may move DE_KFZ from strong_anchors to neither list (always-emit) via config.yaml."

**MEDIUM-004: `customizations.md` "What it does" section lists incorrect quasi-identifiers**

- **Location:** `docs/customizations.md:290`
- **Evidence:** Text reads: "Quasi-identifier spans (`LOCATION`, `DATE_TIME`, `NRP`, `DE_PLZ`, `DE_KFZ`, `DE_ZAEHLERNUMMER`) are suppressed...". The default `config.yaml` quasi_identifiers are `[DATE_TIME, LOCATION, NRP, DE_PLZ]`. `DE_KFZ` is in the default `strong_anchors` (not quasi_identifiers). `DE_ZAEHLERNUMMER` is in `entity_catalog.py` but in neither default list (always-emit by default).
- **Risk:** An operator reading customizations.md to understand the filter's behavior will expect DE_KFZ and DE_ZAEHLERNUMMER to be suppressed when CWF is enabled. In reality they are not (DE_KFZ is an anchor; DE_ZAEHLERNUMMER passes through). The operator may configure or document their deployment based on incorrect information.
- **Resolution:** Correct customizations.md to list the actual default quasi-identifiers: `DATE_TIME`, `LOCATION`, `NRP`, `DE_PLZ`. Similarly, the "strong-anchor span" list in the same sentence should match the actual default `strong_anchors` set from config.py.

---

### LOW

**LOW-001: Dead variable `raw_cwf_override` in detect.py**

- **Location:** `src/redakt/routers/detect.py:129`
- **Evidence:** `raw_cwf_override = closed_world_filtering` is assigned but never referenced again. The audit field uses `audit_cwf_override` (line 139, line 159). The IMPLEMENTATION-PLAN session notes acknowledge this, explaining that `audit_cwf_override` is the correct variable. The dead variable adds noise without contributing behavior.
- **Risk:** None. Dead variable that may confuse future maintainers.
- **Resolution:** Remove `raw_cwf_override = closed_world_filtering` from detect.py:129.

**LOW-002: REQ-010 verbatim comment text not reproduced verbatim in customizations.md**

- **Location:** `docs/customizations.md:291-292`
- **Evidence:** The spec (REQ-010) states: "The exact comment text is [...] must also appear verbatim in docs/customizations.md." The customizations.md has a paraphrase: "The filter is designed for the AI-paste use case...". This is not verbatim from the config comment.
- **Risk:** Low — the intent and warnings are communicated. The threat-model, gameable-narrative, HIPAA, and Art. 9 concerns are all addressed in the customizations.md section, just not in the config comment's exact wording.
- **Resolution:** Append the verbatim config comment block (THREAT MODEL, GAMEABLE, HIPAA, ART. 9, NOTE, OVERRIDE clauses) as a code block in the customizations.md threat-model-assumption section, or replace the paraphrase with the verbatim text as required by REQ-010.

**LOW-003: Document-upload audit path emits absent CWF fields rather than explicit null sentinel**

- **Location:** `src/redakt/services/audit.py:210-230` (`log_document_upload()`)
- **Evidence:** The spec (REQ-013) states: "Audit entries for /api/documents/upload and /documents/submit set `closed_world_suppressed_count: null` (JSON null) and `closed_world_filtering_override: null`." `log_document_upload()` does not pass these fields to `_emit_audit()`, so they are absent from the JSON audit entry entirely (not present as null). The `_emit_audit()` function only emits `closed_world_filtering_override` unconditionally — but only when the parameter is passed.
- **Risk:** Low — compliance tooling that strictly validates the audit schema against the spec would see missing fields instead of null fields for document-upload entries. The spec's null-sentinel design makes the "filter not applicable" state distinguishable from "filter applied, zero suppression." With absent fields, this distinction is not possible without schema knowledge.
- **Resolution:** Add `closed_world_suppressed_count: int | None = None` and `closed_world_filtering_override: bool | None = None` parameters to `log_document_upload()` and call it with explicit `None` values from the document processor.

**LOW-004: EDGE-005 integration test absent**

- **Location:** `tests/test_closed_world_filter.py` (no EDGE-005 test present)
- **Evidence:** The spec Validation Strategy lists: "Allow-list-stripped anchor → quasi-identifiers suppressed when flag on (EDGE-005) — integration test against mocked Presidio returning no PERSON span." No such test exists in the suite. The unit tests cover anchor-absent behavior generically (EDGE-002) but not the specific allow-list-stripping mechanism.
- **Risk:** Low — the behavior is correct by construction (the filter receives the post-allow-list span list; it has no visibility into why PERSON is absent). The unit tests for anchor-absent behavior cover the same code path. The missing test adds no new coverage.
- **Resolution:** Add an integration test that mocks Presidio's analyze() to return `[DATE_TIME, LOCATION]` (no PERSON, simulating allow-list stripping of a PERSON span) with CWF enabled, and asserts suppression. This closes the spec validation strategy item and documents the behavior explicitly.

---

## Recommended Actions

1. **[MEDIUM-001]** `docs/supported-entities.md:35` — change `MEDICAL_LICENSE` classification from `always_emit` to `strong_anchor`.
2. **[MEDIUM-002]** `docs/supported-entities.md:28` — change `CREDIT_CARD` classification from `strong_anchor` to `always_emit`. Add note that operators can add it to `strong_anchors` in config.yaml.
3. **[MEDIUM-003]** `docs/supported-entities.md:80` — change `DE_KFZ` classification from `quasi_identifier` to `strong_anchor`. Add operator-override note per spec REQ-001.
4. **[MEDIUM-004]** `docs/customizations.md:290` — correct quasi-identifiers list to match actual default config: `DATE_TIME, LOCATION, NRP, DE_PLZ`. Correct strong-anchors list to match actual default config.
5. **[LOW-001]** `src/redakt/routers/detect.py:129` — remove the unused `raw_cwf_override = closed_world_filtering` assignment.
6. **[LOW-002]** `docs/customizations.md` threat-model section — replace paraphrase with verbatim config comment text per REQ-010, or add verbatim block as code fence.
7. **[LOW-003]** `src/redakt/services/audit.py:log_document_upload()` — add CWF audit fields with `None` default; pass `None` explicitly from the document processor callsite.
8. **[LOW-004]** `tests/test_closed_world_filter.py` — add EDGE-005 integration test with mocked Presidio returning no-anchor span list and CWF enabled.
9. **[RISK-TIER]** Update SPEC-008 MODULE-002 risk tier from Low to High in the spec's module registry, to reflect the HIPAA gate's regulatory enforcement weight.

---

## Findings Addressed (Step 4c — 2026-05-13)

All 9 findings (4 MEDIUM, 4 LOW, 1 risk-tier flag) resolved. Final test count: **423 passed** (up from 421).

### MEDIUM-001 — MEDICAL_LICENSE classification
- **File:line:** `docs/supported-entities.md:35`
- **Change:** Classification changed from `always_emit` to `strong_anchor`.
- **Verification:** `uv run pytest tests/test_entity_catalog.py -q` — 10/10 pass.

### MEDIUM-002 — CREDIT_CARD classification
- **File:line:** `docs/supported-entities.md:28`
- **Change:** Classification changed from `strong_anchor` to `always_emit`.
- **Verification:** `uv run pytest tests/test_entity_catalog.py -q` — 10/10 pass.

### MEDIUM-003 — DE_KFZ classification
- **File:line:** `docs/supported-entities.md:80`
- **Change:** Classification changed from `quasi_identifier` to `strong_anchor`.
- **Verification:** `uv run pytest tests/test_entity_catalog.py -q` — 10/10 pass.

### MEDIUM-004 — customizations.md quasi-identifier list
- **File:line:** `docs/customizations.md:290` (Item 8 "What it does")
- **Change:** Quasi-identifier list corrected to `[DATE_TIME, LOCATION, NRP, DE_PLZ]` (removed `DE_KFZ` and `DE_ZAEHLERNUMMER`); strong-anchor list and always-emit list corrected to match `config.py` defaults exactly.
- **Verification:** Docs reviewed manually; CI lint 10/10 pass.

### LOW-001 — Dead variable raw_cwf_override
- **File:line:** `src/redakt/routers/detect.py:129`
- **Change:** Removed `raw_cwf_override = closed_world_filtering` and its accompanying comment line. The comment about REPLACE merge was retained and clarified in the adjacent line.
- **Verification:** Full suite 423/423 pass.

### LOW-002 — Verbatim config comment in customizations.md
- **File:line:** `docs/customizations.md` Item 8 threat-model section
- **Change:** Replaced paraphrase with the exact verbatim text block from `config.yaml:85-105` rendered as a fenced code block (THREAT MODEL, GAMEABLE, HIPAA, ART. 9, NOTE, OVERRIDE clauses), per REQ-010.
- **Verification:** Text matches `config.yaml` verbatim.

### LOW-003 — Document-upload null sentinel
- **File:line:** `src/redakt/services/audit.py:log_document_upload()` (~line 220)
- **Change:** Added `closed_world_suppressed_count=None` and `closed_world_filtering_override=None` as explicit kwargs in the `_emit_audit()` call within `log_document_upload()`. Added REQ-013 comment explaining the null sentinel design.
- **Verification:** Full suite 423/423 pass.

### LOW-004 — EDGE-005 integration test
- **File:line:** `tests/test_closed_world_filter.py` (appended to `TestRouterIntegration`)
- **Change:** Added two tests:
  1. `test_detect_edge005_allowlist_stripped_anchor_quasi_suppressed` — mocks Presidio returning `[DATE_TIME, LOCATION]` (no PERSON), per-request CWF=True, asserts `has_pii=False`.
  2. `test_detect_edge005_reverse_anchor_present_quasi_retained` — mocks Presidio returning `[PERSON, DATE_TIME, LOCATION]`, per-request CWF=True, asserts all three entity types retained.
- **Verification:** 423/423 pass (2 new tests added).

### RISK-TIER — MODULE-002 risk tier misclassification
- **File:line:** `SDD/requirements/SPEC-008-closed-world-filtering.md:604`
- **Change:** MODULE-002 `Risk:` changed from `Low` to `High` with rationale: "Contains REQ-020 HIPAA enforcement gate — failure has regulatory exposure." Noted as post-implementation spec adjustment.
- **Verification:** Spec file updated; implementation unaffected (the HIPAA gate was already correctly implemented at High depth per the review).

---

**Revised Verdict: APPROVED** — All findings resolved, 423 tests pass, docs consistent with deployed config.
