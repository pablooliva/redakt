# Implementation Critical Review: closed-world-filtering

**Reviewer:** sdd-critical-reviewer (Opus, adversarial generalist)
**Date:** 2026-05-13
**Target:** SDD-008 implementation (post-Step-4c fix)
**Companion review:** `SDD/reviews/REVIEW-008-closed-world-filtering-20260513.md` (Step 4b spec-driven; APPROVED post-4c)
**Tests verified (reported):** 423/423 passing

---

## Executive Summary

The implementation, post-4c, meets the letter of SPEC-008 — every REQ/EDGE/FAIL traceably maps to working code, the HIPAA gate fires, and the filter logic is correct. Step 4b's adversarial angle was largely confined to documentation correctness; this review attacks the *runtime, environment, and parser surface* that 4b did not.

The adversarial probe turns up one **HIGH** finding (a regulatory-gate bypass via case-insensitive `regulatory_scope` parsing under environment-variable / YAML configurations), four **MEDIUM** findings (silent type coercion of the per-request override field, an unvalidated `regulatory_scope` list that lets `["GDPR", "HIPAA"]` be expressed inconsistently across env/YAML, the absence of any test asserting the mutation-in-validator pattern survives `BaseSettings` semantics under env override, and an under-defended eval-loader that accepts non-dict `request_params`), and four **LOW** findings (CI lint blind to *misclassification* values, silent absorption of audit emission exceptions, a no-op identity-return that diverges from the documented contract, and a misalignment between `_emit_audit`'s conditional and its docstring).

**HIGH=1 · MEDIUM=4 · LOW=4 · Total=9 findings.**

The core filter logic is solid. The risk surface is at the *boundary* — request parsing, env-var binding, audit serialization — which is where adversarial inputs land. **Verdict: REVISIONS REQUIRED** before merging to production.

---

## Verdict

**REVISIONS REQUIRED**

The HIPAA gate bypass (HIGH-001) is the load-bearing finding. The implementation correctly enforces `"HIPAA" in self.regulatory_scope`, but an operator who sets `REDAKT_REGULATORY_SCOPE='["hipaa"]'` or writes `regulatory_scope: [Hipaa]` in YAML will have the gate silently *not fire*. For a regulatory enforcement boundary documented as "Safe Harbor-incompatible," this is the kind of failure mode that should be defended in code, not by operator vigilance.

---

## Specification Deviations

1. **`regulatory_scope` is case-sensitive in code but undocumented as such in spec/config**
   - Specified: REQ-020 says "include 'HIPAA' to enforce the gate." The intent is clearly a scope token, not a string with case semantics.
   - Implemented: `config.py:190` uses `"HIPAA" in self.regulatory_scope` — exact-string membership. `["hipaa"]`, `["Hipaa"]`, `["HIPAA "]` (trailing space) all bypass the gate.
   - Impact: A regulatory-enforcement gate that silently does nothing on a typo. Worst-case: an operator copies the doc, types `hipaa` (lowercase, plausible since the YAML uses lowercase keys elsewhere), believes the gate is active, enables `closed_world_filtering: true`, ships HIPAA-incompatible filtering in a HIPAA-scoped deployment.
   - Severity: **HIGH** (see HIGH-001).

2. **`closed_world_filtering_override` audit field on the document-upload path is `null` per REQ-013 — but the field's *semantics* on that path are now ambiguous**
   - Specified: REQ-013 wants null as a sentinel meaning "filter does not apply."
   - Implemented: The document-upload path emits `closed_world_filtering_override: null` AND `closed_world_suppressed_count: null` (post-4c LOW-003 fix). But the field set on this path is identical to the set on a detect/anonymize call where the caller omitted the field — a downstream audit-log consumer cannot distinguish "filter is structurally inapplicable" from "filter applied and the caller didn't override." If REQ-013's null-sentinel design was meant to be distinguishable, this is broken; if not, the post-4c fix added field noise.
   - Impact: Audit-log analytics that count "filter overrides used" cannot reliably exclude the document-upload pipeline from the denominator.
   - Severity: **LOW** (deferred to LOW-004).

3. **`_emit_audit`'s docstring/comment claims "null is meaningful" but conditional silently skips emission of `closed_world_suppressed_count` when None**
   - Specified: REQ-013 — "always emit both fields, including null."
   - Implemented: `audit.py:145-146` — `if closed_world_suppressed_count is not None: record.audit_data["closed_world_suppressed_count"] = ...`. When None, the field is absent, not null. `closed_world_filtering_override` IS unconditionally emitted (line 149). The two fields are now treated asymmetrically.
   - Impact: Auditors querying `closed_world_suppressed_count` will see field absent on the document-upload path (in contradiction with the LOW-003 fix's stated intent). The mismatch between the audit-fields comment (lines 143-149) and the actual conditional is a latent maintenance trap.
   - Severity: **LOW** (see LOW-004).

---

## Technical Vulnerabilities

### HIGH-001 — HIPAA gate bypass via case-sensitive scope membership

- **Location:** `src/redakt/config.py:190` (`if "HIPAA" in self.regulatory_scope:`)
- **Attack/failure vector:**
  - YAML: `regulatory_scope: [hipaa]` → `"HIPAA" not in ["hipaa"]` → gate skipped.
  - Env: `REDAKT_REGULATORY_SCOPE='["Hipaa"]'` → gate skipped.
  - YAML: `regulatory_scope: ["HIPAA "]` (trailing space from manual edit) → gate skipped.
  - YAML: `regulatory_scope: ["HIPAA", "HIPAA"]` → gate fires but `["HIPAA", "HIPAA"]` is silently accepted with no warning about the duplicate.
- **Why this matters:** REQ-020 declares HIPAA Safe Harbor incompatibility a *regulatory enforcement* boundary. A regulatory gate that silently fails on a casing typo is a class-1 compliance vulnerability — the operator believes protection is active while it is not. The implementation's HIPAA test fixture (`test_hipaa_with_cwf_true_raises`) only uses the canonical `"HIPAA"` string; no negative test exists for `"hipaa"`, `"Hipaa"`, `"HIPPA"` (common typo), or `"HIPAA "`.
- **Fix:**
  - Normalize scope tokens at validator entry: `self.regulatory_scope = [s.strip().upper() for s in self.regulatory_scope]`.
  - Validate each token against a canonical set (e.g., `{"GDPR", "HIPAA", "CCPA"}`) and either raise (`strict_entity_validation`-style) or WARN on unknown tokens (defends against `"HIPPA"` typo).
  - Add explicit negative tests: lowercase, mixed case, whitespace, common typo.
- **Severity:** **HIGH**

### MEDIUM-001 — Pydantic silently coerces stringy values for `closed_world_filtering` in request body

- **Location:** `src/redakt/models/detect.py:13` and `src/redakt/models/anonymize.py:13` — `closed_world_filtering: bool | None = None`
- **Attack/failure vector:** Pydantic v2's default coercion for `bool` accepts:
  - `"true"`, `"True"`, `"TRUE"`, `"yes"`, `"y"`, `"on"`, `1`, `1.0` → coerced to `True`
  - `"false"`, `"False"`, `0`, `0.0` → coerced to `False`
  - `null` (JSON), absent key → `None` (correct)
  - `"yes please"`, `"maybe"`, `2` → ValidationError → HTTP 422 (correct)

  In particular, `{"closed_world_filtering": 1}` and `{"closed_world_filtering": "true"}` are *accepted* and interpreted as `True`. This contradicts the spec language for FAIL-003 ("Malformed per-request field → HTTP 422 (Pydantic handles bool|None)"), which the IMPLEMENTATION-PLAN's FAIL-003 entry asserts is covered. A truthy-int from a JS client computing `enabled ? 1 : 0` would silently flip the filter on.

  No test in `test_closed_world_filter.py` asserts the HTTP 422 outcome for malformed types. The framework reliance is correct in the limit, but the spec's intent ("strict bool|None") is not enforced.
- **Why this matters:** The override field is the only *operator-controlled* part of a SEC-001a-gated security boundary. Silent coercion of stringy values means a misconfigured client can flip the filter on accidentally — not catastrophic (the gate may still reject it), but a regression away from the "explicit boolean only" intent.
- **Fix:**
  - Either (a) use `Field(strict=True)` on the override field to disable coercion, or (b) explicitly test HTTP 422 for `"yes"`, `1`, `"on"` and document the coercion behavior in the spec.
  - Recommended: option (a) — strict mode aligns with the spec's "bool | None" wording.
- **Severity:** **MEDIUM**

### MEDIUM-002 — `regulatory_scope` accepts arbitrary list contents with no canonical validation

- **Location:** `src/redakt/config.py:129` — `regulatory_scope: list[str] = ["GDPR"]`
- **Attack/failure vector:**
  - `regulatory_scope: ["GDPR", "GDPR"]` → accepted (no dedup, no warning).
  - `regulatory_scope: ["nonsense"]` → accepted (no validation against a canonical set).
  - `regulatory_scope: []` → accepted (no scope → no enforcement; the test `test_empty_regulatory_scope_raises` is misnamed — it asserts the *default* contains GDPR, not that empty lists raise).
  - `regulatory_scope: ["HIPAA", "GDPR"]` → HIPAA gate fires (correct), but operator may not realize both scopes are active.
- **Why this matters:** This is a regulatory enforcement input. Unlike `strong_anchors` and `quasi_identifiers` — which get `strict_entity_validation` and canonical-set checking — `regulatory_scope` has no validation. A typo of `"HIPPA"` lands silently as a no-op (worst case: operator thinks they enabled HIPAA enforcement). The codebase already has a model for fail-fast canonical validation (`CANONICAL_ENTITY_TYPES`); the same pattern should apply here.
- **Fix:** Define `CANONICAL_REGULATORY_SCOPES = frozenset({"GDPR", "HIPAA", "CCPA"})` and validate at the model validator. Apply the same `strict_entity_validation` gate (or a parallel `strict_regulatory_validation`). The empty-list case should also raise or warn explicitly.
- **Severity:** **MEDIUM**

### MEDIUM-003 — `model_validator(mode="after")` mutation of `allow_per_request_closed_world_override` has no defense against Pydantic future-version semantics

- **Location:** `src/redakt/config.py:207` — `self.allow_per_request_closed_world_override = False`
- **Attack/failure vector:** Pydantic v2's `BaseSettings` does not have `validate_assignment=True` set (`config.py:136-142` shows only `env_prefix`, `env_nested_delimiter`, `env_file`, `env_file_encoding`, `extra=ignore`). The HIPAA auto-force pattern relies on direct attribute assignment from inside `mode="after"`. This works *today* but:
  - If `validate_assignment=True` were ever added, the assignment would trigger the validator recursively. Without a guard, infinite recursion or a second mutation event.
  - If a future pydantic-settings release tightens semantics (e.g., freezing the model after validator return), the mutation could silently fail with no error.
  - The session notes in IMPLEMENTATION-PLAN acknowledge this is "a subtle pattern" but the codebase has no defensive test asserting that the mutation actually takes effect *after env-var override*.

  Test gap: `test_hipaa_auto_forces_override_to_false` passes `allow_per_request_closed_world_override=True` via constructor kwargs, but there is no test asserting the auto-force still works when the value comes from `REDAKT_ALLOW_PER_REQUEST_CLOSED_WORLD_OVERRIDE=true` or from `config.yaml`.
- **Why this matters:** This is the safety floor for HIPAA — the test of "the gate cannot be bypassed by a determined caller." A future Pydantic upgrade or an env-var-vs-validator interaction that breaks the auto-force is a regression with regulatory teeth.
- **Fix:**
  - Add an integration test that loads Settings via env vars or a temporary YAML file with `regulatory_scope: [HIPAA]` + `allow_per_request_closed_world_override: true`, then asserts the override field is False after validation.
  - Consider replacing the mutation pattern with a computed `@property` on the override field that returns `False` whenever HIPAA is in scope — this is impossible-to-bypass-by-construction.
- **Severity:** **MEDIUM**

### MEDIUM-004 — Eval-loader `request_params` accepts non-dict YAML structures silently

- **Location:** `tests/eval/_loader.py:77` — `raw_params: dict[str, Any] = record.get("request_params") or {}`
- **Attack/failure vector:**
  - `request_params: null` → `None or {} == {}` → empty params, no validation triggered. Fine.
  - `request_params: []` → `[]` is falsy → `or {}` substitutes. **Silent data loss** if the operator wrote a list of dicts by mistake.
  - `request_params: "closed_world_filtering"` → string is truthy → `set("closed_world_filtering")` iterates characters → produces `{'c', 'l', 'o', 's', ...}` → set difference vs ALLOWED_KEYS — error message will be nonsensical, but it does fail. Marginally OK.
  - `request_params: 42` → `set(42)` → TypeError, crashes the loader with an unhelpful traceback.
  - `request_params: {true: true}` (boolean key) → YAML accepts; `set({True: True})` works; `{True} - ALLOWED_KEYS` evaluates `True` vs strings, which compares as False — so `True` ends up in `unknown`. Confusing but safe.
- **Why this matters:** The loader is the security boundary for eval fixture content. Eval fixtures are run against live Redakt + Presidio; a malformed fixture that the loader silently absorbs becomes a flaky test or a meaningless calibration result. The post-4c fix made *unknown keys* fail-closed; the type of `request_params` itself is still open.
- **Fix:**
  - Add an explicit `isinstance(raw_params, dict)` check before the unknown-key validation; raise `ValueError` with a clear message for non-dict shapes.
  - Document the expected shape in the docstring at the top of `_loader.py`.
- **Severity:** **MEDIUM**

---

## Test Gaps

### LOW-001 — CI lint test (`tests/test_entity_catalog.py`) does not verify classification *values*

- **Location:** `tests/test_entity_catalog.py:67-77` and the rest of the file.
- **What's not covered:** The lint test asserts that every entity in `CANONICAL_ENTITY_TYPES` appears as a backtick-wrapped name in `docs/supported-entities.md`, and that every backtick-wrapped name in the doc is in the catalog. **It does not check that the `Classification` column value (`strong_anchor` / `quasi_identifier` / `always_emit`) matches the config's actual classification.** The 4b-found MEDIUM findings (MEDICAL_LICENSE, CREDIT_CARD, DE_KFZ misclassifications) were *exactly* the failure mode this lint should have caught. Post-4c, the doc has been fixed — but the lint test has not been strengthened to *prevent recurrence*.
- **Risk:** A future doc edit (or a future config edit) that introduces a classification mismatch will slip past CI again. The doc → config divergence is a documented past failure; the future-proofing fix is absent.
- **Suggested test:**
  - Parse the Classification column in `docs/supported-entities.md` (table rows containing `strong_anchor|quasi_identifier|always_emit`).
  - For each row, assert the entity is in the matching `config.py` default list (or absent from both for `always_emit`).
  - This makes MEDIUM-001/002/003 *unreproducible* in future edits.
- **Severity:** **LOW** (the immediate misclassifications are fixed; the regression-prevention test is missing).

### LOW-002 — No explicit HTTP 422 negative test for malformed `closed_world_filtering` field values

- **Location:** `tests/test_closed_world_filter.py` — no test asserts FAIL-003.
- **What's not covered:** The spec's FAIL-003 requires "Malformed per-request field → HTTP 422." The IMPLEMENTATION-PLAN claims "Pydantic handles bool | None" — but Pydantic's default coercion accepts `"true"`, `1`, `0`, etc. (see MEDIUM-001). No test asserts:
  - `{"closed_world_filtering": "yes"}` → HTTP 422 (currently: accepted, coerced to True).
  - `{"closed_world_filtering": 1}` → HTTP 422 (currently: accepted, coerced to True).
  - `{"closed_world_filtering": "tru"}` (typo) → HTTP 422 (this *should* reject).
  - `{"closed_world_filtering": null}` → uses instance default (asserted nowhere; equivalent to absent).
- **Risk:** The spec's FAIL-003 is asserted-by-claim, not asserted-by-test. A regression in Pydantic's strictness or in the model decl would not be caught by the suite.
- **Suggested test:** Parametrize a test with malformed payloads and assert HTTP 422 for each. If MEDIUM-001's fix (strict=True) is applied, also test that `"true"` and `1` are rejected.
- **Severity:** **LOW**

### LOW-003 — No end-to-end test combining config reload + filter + audit emission

- **Location:** `tests/test_closed_world_filter.py` — no such test exists.
- **What's not covered:** The implementation has three coordinated boundaries — config validator (HIPAA gate, frozenset pre-compute, override auto-force), router (gate-precedence, audit field threading), audit logger (field emission). Each is tested in isolation; nothing tests the *cross-module sequence*:
  1. Settings loaded with HIPAA scope.
  2. Verify override auto-force triggered.
  3. Make a request with `closed_world_filtering: true` (per-request).
  4. Verify the audit log shows `closed_world_filtering_override: null` AND `closed_world_suppressed_count: 0` AND the filter was not applied.
- **Risk:** A bug that breaks any of (validator mutation, router gate check, audit emission) would only show in production where the HIPAA gate is supposed to be active. The HIPAA gate is the single most regulatorily-charged code path; it deserves a real cross-module test.
- **Suggested test:** Add a `TestHipaaEndToEnd` class that constructs a real `Settings` with HIPAA scope, posts a request asking to enable CWF, captures the audit log, and asserts all three boundaries behaved correctly.
- **Severity:** **LOW**

### LOW-004 — `_emit_audit` conditional vs. comment divergence (audit field emission asymmetry)

- **Location:** `src/redakt/services/audit.py:143-149`
- **What's not covered:**
  - Lines 145-146: `if closed_world_suppressed_count is not None: record.audit_data["closed_world_suppressed_count"] = closed_world_suppressed_count` — conditional emission.
  - Line 149: `record.audit_data["closed_world_filtering_override"] = closed_world_filtering_override` — unconditional emission.

  The comment block at lines 143-149 says "always emit when provided" for `suppressed_count` and "always emit the field (null is meaningful)" for `override`. The behavior is asymmetric: `suppressed_count: None` → field absent; `override: None` → field present as null.

  The post-4c LOW-003 fix added explicit `closed_world_suppressed_count=None` to the document-upload caller, expecting the field to appear as null. **It does not.** The `None` value causes the field to be *omitted entirely* due to the conditional at line 145. The post-4c fix produces a different result than its commit message implied.

  No test asserts what the document-upload audit JSON actually contains.
- **Risk:** The LOW-003 fix's stated goal ("null sentinel compliance for document-upload audit path") is not achieved. Compliance auditors expecting `closed_world_suppressed_count: null` in document-upload entries will see the field missing.
- **Suggested test:** Capture the JSON output of a `log_document_upload()` call and assert that *both* CWF fields are present (either both as null, or both absent — make a decision and enforce it).
- **Severity:** **LOW** (functional impact small; consistency/contract impact medium)

---

## Module-level adversarial findings

### MODULE-001 (filter_by_closed_world) — adversarial probe

- **Pure function, immutable inputs, frozenset O(1) membership** — sound. No mutable state. No race condition.
- **Tuple-return contract:** `(filtered_spans, suppressed_count)`. Every caller (`detect.py:139`, `anonymize.py:137`) unpacks correctly. A future caller forgetting to unpack and treating the tuple as a list would: `len(result) == 2` (the tuple length), `result[0]` is the list, iterating `for r in result` would yield `[<list>, <int>]` — type errors downstream. The mistake is loud, not silent. Acceptable.
- **`None` handling:** `filter_by_closed_world(None, ...)` would crash on `any(r["entity_type"] in ...)`. The callers always pass `results` from `filter_by_entity_thresholds()` which returns a list. But: if Presidio returns malformed JSON that doesn't yield a list, an earlier exception fires. The filter does not defensively guard `results is None`; not a defect by itself, but the docstring should specify the contract.
- **EDGE-001 (empty list) — the disabled path returns `(results, 0)` immediately, the enabled path falls through to `any()` which returns False on empty, then `has_anchor=False`, then `filtered=[]` and `suppressed_count=0`. Two different code paths, both correct.
- **Adversarial probe: O(n²)?** No. The inner loop is `r["entity_type"] in strong_anchors` (O(1) frozenset) and `r["entity_type"] in quasi_identifiers` (O(1) frozenset). The outer iteration is O(n). Total O(n). PERF-001 holds at scale.
- **No-op identity return:** When `enabled=False`, `return results, 0` returns the same list object (verified by `test_flag_off_returns_same_object`). If a downstream caller mutates `results`, it mutates the input. Not a defect — Presidio results are not retained across requests — but worth a docstring note.

**Assessment:** Robust. No adversarial findings.

### MODULE-002 (Config schema) — high-risk attention

Per the 4c spec update (MODULE-002 risk-tier: Low → High), this module gets adversarial-with-high-risk-attention scrutiny.

- **HIPAA gate at `config.py:189-207`:** This is the regulatory enforcement boundary.
  - **HIGH-001 (above): case-sensitive HIPAA string matching.** Documented above as the primary HIGH finding.
  - **MEDIUM-002 (above): no canonical validation of `regulatory_scope`.** Documented above.
  - **MEDIUM-003 (above): mutation-in-validator pattern has no integration test under env-var binding.** Documented above.
  - **Validator order:** overlap → duplicates → canonical → HIPAA gate → degenerate warning → frozenset. The HIPAA gate runs AFTER canonical-set check. **Probe: can a typo'd HIPAA scope (e.g., `"HIPPA"`) be caught by the canonical-set check?** No — `regulatory_scope` is not run through `CANONICAL_ENTITY_TYPES`. The canonical-set check is entity-only. The HIPAA gate fires only on exact string match. **There is no validation that catches HIPAA typos.**

- **Frozenset pre-computation at `config.py:226-227`:** Atomic with respect to the validator. The `frozenset()` construction is done in `mode="after"`, after all field assignments. No race condition. But the `strong_anchors_set` field is declared as a regular field with default `frozenset()` — this means it is *visible* at the model level. If an attacker could inject `strong_anchors_set` via YAML or env vars and `extra="ignore"` were ever changed to `"allow"`, they could pre-seed the frozenset. Currently defended by `"extra": "ignore"`. Document this assumption.

- **Validator can be triggered multiple times in Pydantic v2 if `validate_assignment=True`** — see MEDIUM-003.

### MODULE-003 (Router threading) — adversarial probe

- **Gate precedence at `detect.py:127-137` and `anonymize.py:124-135`:**
  - `request_value = closed_world_filtering if settings.allow_per_request_closed_world_override else None` — gate first, then merge.
  - `effective_cwf = request_value if request_value is not None else settings.closed_world_filtering` — REPLACE semantics.
  - `audit_cwf_override = closed_world_filtering if request_value is not None else None` — audit captures the *honored* value, not the *requested* value.
- **Probe: can a caller force CWF active under HIPAA?** Trace:
  1. HIPAA in scope → validator auto-forces `allow_per_request_closed_world_override = False`.
  2. Router: `request_value = closed_world_filtering if False else None` → `request_value = None`.
  3. `effective_cwf = None if None is not None else settings.closed_world_filtering` → `settings.closed_world_filtering`.
  4. HIPAA also means `closed_world_filtering: true` was rejected at validator startup → instance default is False.
  5. **Therefore `effective_cwf` is False regardless of caller intent.** Gate holds.
- **Probe: HIPAA + `regulatory_scope: ["hipaa"]` (lowercase)?** See HIGH-001 — gate does not fire. `allow_per_request_closed_world_override` retains its YAML/env value (e.g., True). Caller can set `closed_world_filtering: true` per request. Filter applies. **HIPAA enforcement defeated by casing.**
- **Probe: a request body with `closed_world_filtering` at top level vs nested under `request_options`?** The current model puts it at top level. There is no `request_options` nesting; spec doesn't suggest there should be. Pydantic rejects unknown nested keys silently (model has no `request_options` field; `extra` is not configured on `DetectRequest`, defaulting to Pydantic v2's "ignore"). A caller using a nested structure gets default (None) for the override — instance default applies. Safe-by-default.

### MODULE-004 (Audit) — adversarial probe

- **`_emit_audit` exception handling at lines 151-163:** Wraps `audit_logger.handle(record)` in `try/except Exception`. Any exception logs a WARNING and proceeds. **The detect/anonymize request succeeds even if audit emission fails.**
- **Probe: is this a compliance vulnerability?** Maybe. The DPO would want detect/anonymize requests to be auditable. If audit emission silently fails (e.g., disk full, JSON encoding error on a future field), the request returns 200 with no audit record. The WARNING goes to the app logger, not the audit logger — easy to miss.
- **Probe: can `exc_info=True` leak PII?** The comment at line 154 claims "the traceback can only reference audit metadata." That depends on the stack frames. The audit data is `{action, entity_count, entities_found, language_detected, source, allow_list_count?, file_type?, file_size_bytes?, operator?, closed_world_suppressed_count?, closed_world_filtering_override?}` — all metadata, no PII. The claim is correct *given the current code*. If a future maintainer adds a field that contains PII or a stringified original text, this assumption silently breaks.
- **Suggested defense:** Add a `# DO NOT add PII fields to record.audit_data — exc_info=True would leak them` comment at the function signature.
- **No finding** — current behavior is correct; this is a maintenance note.

### MODULE-005 (Eval loader) — adversarial probe

- See MEDIUM-004 above. The `request_params` type is not defensively validated. Otherwise sound.

---

## Recommended Actions Before Merge

1. **[HIGH-001]** `src/redakt/config.py:190` — Normalize `regulatory_scope` tokens at validator entry (`.strip().upper()`) and validate against a canonical scope frozenset. Add negative tests for `"hipaa"`, `"Hipaa"`, `"HIPAA "`, and `"HIPPA"` (typo).

2. **[MEDIUM-001]** `src/redakt/models/detect.py:13` and `src/redakt/models/anonymize.py:13` — Use `Field(strict=True)` (or `model_config = ConfigDict(strict=True)`) to disable Pydantic's coercion for `closed_world_filtering`. Add HTTP 422 tests for `"true"`, `1`, `0`, `"yes"`.

3. **[MEDIUM-002]** `src/redakt/config.py:129` — Add `CANONICAL_REGULATORY_SCOPES` frozenset and validate `regulatory_scope` against it. Apply `strict_entity_validation` gate (or a parallel `strict_regulatory_validation`) to typos.

4. **[MEDIUM-003]** `tests/test_closed_world_filter.py` — Add an integration test that loads `Settings` with `regulatory_scope: [HIPAA]` from a temporary YAML file (not constructor kwargs) and asserts `allow_per_request_closed_world_override == False`. Repeats the assertion with env-var binding.

5. **[MEDIUM-004]** `tests/eval/_loader.py:77` — Add `isinstance(raw_params, dict)` check before unknown-key validation; raise `ValueError` for non-dict shapes.

6. **[LOW-001]** `tests/test_entity_catalog.py` — Extend CI lint to verify the Classification column *value* matches the config's actual default list (catalog-doc-config bidirectional consistency).

7. **[LOW-002]** `tests/test_closed_world_filter.py` — Add parametrized HTTP 422 tests for malformed `closed_world_filtering` values (FAIL-003 evidence).

8. **[LOW-003]** `tests/test_closed_world_filter.py` — Add a `TestHipaaEndToEnd` cross-module test: HIPAA-scoped settings + per-request override request + audit log capture + assertion of all three boundaries.

9. **[LOW-004]** `src/redakt/services/audit.py:145` — Resolve the asymmetry between `closed_world_suppressed_count` (conditional) and `closed_world_filtering_override` (unconditional). Pick one semantics (always emit as null OR always omit on None) and apply consistently. Update tests to lock in the choice.

---

## Findings Summary

| # | Severity | Title |
|---|----------|-------|
| HIGH-001 | HIGH | HIPAA gate bypass via case-sensitive `regulatory_scope` membership |
| MEDIUM-001 | MEDIUM | Pydantic silently coerces stringy values for per-request `closed_world_filtering` |
| MEDIUM-002 | MEDIUM | `regulatory_scope` accepts arbitrary list contents with no canonical validation |
| MEDIUM-003 | MEDIUM | `model_validator` mutation pattern lacks defensive integration test under env-var binding |
| MEDIUM-004 | MEDIUM | Eval-loader `request_params` accepts non-dict YAML structures silently |
| LOW-001 | LOW | CI lint test does not verify Classification column *values* |
| LOW-002 | LOW | No explicit HTTP 422 negative test for malformed `closed_world_filtering` values |
| LOW-003 | LOW | No end-to-end cross-module test combining HIPAA scope + per-request + audit emission |
| LOW-004 | LOW | `_emit_audit` asymmetry between suppressed_count (conditional) and override (unconditional) |

**HIGH=1, MEDIUM=4, LOW=4. Total=9.**

---

## What I Specifically Checked

- `src/redakt/utils.py:filter_by_closed_world` — full body, tuple return, both code paths, edge inputs (empty list, None).
- `src/redakt/config.py` — Settings declaration, model_validator body (overlap, duplicate, canonical, HIPAA, degenerate, frozenset), `model_config`, settings_customise_sources, env precedence.
- `src/redakt/routers/detect.py` and `anonymize.py` — gate precedence, REPLACE merge, audit field threading, exception handling (`ValueError` → HTTP 422).
- `src/redakt/services/audit.py` — `_emit_audit` conditionals, `log_detection`/`log_anonymization`/`log_document_upload` signatures and kwarg passing, exception handling.
- `src/redakt/models/detect.py` and `anonymize.py` — Pydantic field declarations.
- `tests/eval/_loader.py` — `_load_one` validation logic, `request_params` type handling.
- `tests/test_entity_catalog.py` — bidirectional consistency assertions, what they do and do not cover.
- `tests/test_closed_world_filter.py` — sampled 12+ tests across all 8 test classes; verified the SEC-001a tests truly exercise the router path (`TestRouterIntegration`) and that the in-class SEC-001a tests (`TestSec001aSilentIgnore`) replicate router logic in pure Python (acceptable for unit testing the logic, but not a router test).
- `config.yaml` — actual deployed config; verified threat-model comment block is present verbatim and `regulatory_scope: ["GDPR"]` is the live default.
- `src/redakt/services/document_processor.py` — confirmed `filter_by_closed_world` is NOT invoked from the document pipeline (REQ-015 holds by omission). Confirmed `log_document_upload` is called from `routers/documents.py:142` and `routers/pages.py:259` (web doc upload).
- `src/redakt/entity_catalog.py` — verified `CANONICAL_ENTITY_TYPES` is a frozenset and matches the lint test expectations.

---

**End of Critical Review.**

---

## Findings Addressed

**Date resolved:** 2026-05-13  
**Step:** 4e (Address Implementation Critical Review Findings)  
**Test suite before:** 423/423 passing  
**Test suite after:** 471/471 passing (48 new tests added)

### HIGH-001 — HIPAA gate bypass via case-sensitive `regulatory_scope` membership

**Status:** RESOLVED

**Code change:** `src/redakt/config.py` — added normalization and canonical validation of `regulatory_scope` tokens at the top of `validate_closed_world_config` (before any gate check):
- `self.regulatory_scope = [s.strip().upper() for s in self.regulatory_scope]` normalizes all tokens.
- `CANONICAL_REGULATORY_SCOPES = frozenset({"GDPR", "HIPAA", "CCPA"})` defines the allowed set.
- Unknown tokens (including `"HIPPA"` typo) raise `ValueError` in strict mode or emit `logger.warning()` in non-strict mode — same pattern as entity-type validation.

**Tests added** (`TestHighOne_RegulatoryScope_Normalization`):
- `test_lowercase_hipaa_triggers_gate` — `["hipaa"]` triggers ValidationError
- `test_mixed_case_hipaa_triggers_gate` — `["Hipaa"]` triggers ValidationError
- `test_whitespace_padded_hipaa_triggers_gate` — `["HIPAA "]` triggers ValidationError
- `test_lowercase_hipaa_forces_override_false` — `["hipaa"]` auto-forces override to False
- `test_hippa_typo_rejected_strict` — `["HIPPA"]` raises in strict mode
- `test_hippa_typo_warns_non_strict` — `["HIPPA"]` warns in non-strict mode
- `test_scope_tokens_normalized_in_settings` — `["gdpr"]` normalizes to `"GDPR"` in the stored list

---

### MEDIUM-001 — Pydantic silently coerces stringy values for `closed_world_filtering`

**Status:** RESOLVED

**Code changes:**
- `src/redakt/models/detect.py` — `closed_world_filtering: bool | None = None` → `closed_world_filtering: StrictBool | None = None` (imports `from pydantic import StrictBool`)
- `src/redakt/models/anonymize.py` — same change

**Tests added** (`TestMediumOne_StrictBool_Override`):
- `test_detect_rejects_coercible_closed_world_value` — parametrized over `"true"`, `"false"`, `"True"`, `"False"`, `"yes"`, `"no"`, `"on"`, `"off"`, `1`, `0`, `1.0`, `0.0` — all → HTTP 422
- `test_anonymize_rejects_coercible_closed_world_value` — same for /api/anonymize
- `test_detect_accepts_null_closed_world_value` — `null` → 200
- `test_detect_accepts_true_closed_world_value` — JSON `true` → 200
- `test_detect_accepts_false_closed_world_value` — JSON `false` → 200

---

### MEDIUM-002 — `regulatory_scope` accepts arbitrary list contents with no canonical validation

**Status:** RESOLVED (addressed jointly with HIGH-001)

**Code change:** `src/redakt/config.py` — `CANONICAL_REGULATORY_SCOPES` frozenset defined as class attribute; validator iterates over tokens after normalization and fails/warns on unknowns. The same `strict_entity_validation` gate controls fail-closed vs warn behavior.

---

### MEDIUM-003 — `model_validator` mutation pattern lacks defensive integration test under env-var binding

**Status:** RESOLVED

**Tests added** (`TestMediumThree_HipaaEnvVarIntegration`):
- `test_hipaa_auto_force_survives_explicit_override_kwarg` — constructor kwarg path
- `test_hipaa_auto_force_survives_env_var_override` — env var path (`REDAKT_REGULATORY_SCOPE='["HIPAA"]'` + `REDAKT_ALLOW_PER_REQUEST_CLOSED_WORLD_OVERRIDE=true`); uses `monkeypatch.setattr` on `_CONFIG_YAML_PATH` to exclude YAML interference
- `test_hipaa_auto_force_survives_yaml_config` — YAML file path; uses `monkeypatch.setattr` on `config_module._CONFIG_YAML_PATH` to point to a temp YAML file

---

### MEDIUM-004 — Eval-loader `request_params` accepts non-dict YAML structures silently

**Status:** RESOLVED

**Code change:** `tests/eval/_loader.py` line 77 — replaced `raw_params: dict[str, Any] = record.get("request_params") or {}` with an explicit `isinstance(raw_params_value, dict)` guard that raises `ValueError` with a clear message for lists, strings, integers, and other non-dict types. `null` and empty list (`[]`) both fall through to `{}`.

**Tests added** (`TestMediumFour_EvalLoaderNonDictParams`):
- `test_list_request_params_raises` — list-of-dicts shape → ValueError
- `test_string_request_params_raises` — string → ValueError
- `test_integer_request_params_raises` — integer → ValueError
- `test_null_request_params_is_valid` — null → empty params, no error

---

### LOW-001 — CI lint test does not verify Classification column values

**Status:** RESOLVED

**Tests added** (`TestLowOne_ClassificationColumnLint`):
- `test_strong_anchors_classified_correctly_in_doc` — parses Classification column; asserts each default strong_anchor is `strong_anchor` in the doc
- `test_quasi_identifiers_classified_correctly_in_doc` — asserts each default quasi_identifier is `quasi_identifier` in the doc

---

### LOW-002 — No explicit HTTP 422 negative test for malformed `closed_world_filtering` values

**Status:** RESOLVED (addressed by MEDIUM-001 tests — the `TestMediumOne_StrictBool_Override` parametrized tests cover all coercible values and assert HTTP 422)

---

### LOW-003 — No end-to-end cross-module test combining HIPAA scope + per-request + audit

**Status:** RESOLVED

**Tests added** (`TestLowThree_HipaaEndToEnd`):
- `test_hipaa_end_to_end_gate_holds` — patches `redakt.routers.detect.settings` with a HIPAA-scoped `Settings` instance; sends `closed_world_filtering: true` per-request; asserts HTTP 200 (gate discards value), asserts audit log contains both CWF fields

---

### LOW-004 — `_emit_audit` asymmetry between suppressed_count (conditional) and override (unconditional)

**Status:** RESOLVED

**Code change:** `src/redakt/services/audit.py` lines 143-149 — replaced conditional `if closed_world_suppressed_count is not None:` emission with unconditional `record.audit_data["closed_world_suppressed_count"] = closed_world_suppressed_count`, matching the behavior of `closed_world_filtering_override`. Both fields are now always emitted; `None` serializes as JSON `null`.

**Tests added** (`TestLowFour_AuditEmissionSymmetry`):
- `test_suppressed_count_none_emits_null_not_absent` — `log_document_upload()` call (which passes `None`); asserts field present in JSON with value `null`
- `test_suppressed_count_zero_emits_zero` — asserts value `0` is emitted, not omitted
- `test_override_field_always_emitted_null` — asserts `closed_world_filtering_override: null` present
- `test_both_fields_present_on_document_upload_path` — asserts BOTH fields present on the document-upload audit path

---

**All 9 findings resolved. Test suite: 471/471 passing.**
