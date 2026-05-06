# Specification Critical Review: transformers-nlp-backend

**Date:** 2026-05-06
**Reviewer:** Step 3d critical-review subagent (adversarial generalist)
**Spec under review:** `SDD/requirements/SPEC-007-transformers-nlp-backend.md` (post panel iter 1 fix; panel iter 2 verdict: PROCEED)
**Inputs:** RESEARCH-007, CLARIFICATION-007, ADR 0001, UBIQUITOUS_LANGUAGE.md, PANEL-SPEC iter 1 + iter 2

---

### Severity: MEDIUM

### Executive Summary

SPEC-007 is a structurally mature spec — the panel found 0 HIGH and the iter 2 review accepts the iter 1 fixes as substantive (artifact-digest manifest, two-phase startup contract, measurement-driven `start_period`, model-load-once invariant). The architecture (custom `MultiNlpEngine` in the fork, asymmetric routing, build-time-baked weights) is sound and well-traced. However, the spec under-specifies the **calibration loop's stopping condition / acceptance for tuned values** and several **verification mechanisms named at the prose level are not wired to concrete artifacts** (e.g., REQ-010 "API contract preservation" is gated by `tests/eval/` fixtures that use `issubset`, the very assertion shape the feature is closing as inadequate; REQ-011 recognizer-floor preservation is gated by a YAML diff between `main` and the feature branch, but `default_recognizers.yaml` is in the fork repo and the spec never says how the diff is captured for review). The most important single finding (top-of-list below): **REQ-006/007 calibration acceptance is circular** — "all fixtures stay PASS" is the gate, but the fixtures that decide PASS are themselves added by the same PR (REQ-009), and the threshold values that decide PASS are tuned against those same fixtures. The exit criterion is "Pablo declares it good." For an enterprise PII tool, this is the kind of soft gate that re-runs of the same calibration cannot reproduce.

### Ambiguities That Will Cause Problems

1. **REQ-006 + REQ-007 calibration loop has no defined stopping condition** [MEDIUM]
   - Quote: REQ-006 (line 118): "with the new defaults committed, all 41 existing fixtures stay PASS, the 15 new `expect_clean: true` fixtures stay PASS, and any German `LOCATION` / `DATE_TIME` hits that legitimately fire (e.g., `Berlin`, `morgen`) pass through Redakt's post-filter."
   - Possible interpretations: (a) the implementer iterates threshold values until those three bullets all hold, then commits — any value satisfying the bullets is "correct"; (b) there is a unique, derivable set of values; (c) Pablo manually inspects the calibration report and declares thresholds good.
   - The implementation order (Implementation Notes step 6, line 525): "Re-tune `entity_score_thresholds` (Redakt) and `low_score_entity_names` / `low_confidence_score_multiplier` (analyzer-side, `de` row). **Iterate until** all 41 existing fixtures stay PASS and the `expect_clean` fixtures … stay PASS." Iterate until they pass — but the fixtures are also new in this same PR (REQ-009). The threshold values are tuned against the very fixtures that decide whether they pass. There is no held-out set, no calibration vs. validation split, no monotonicity check, no required range or step size for the threshold sweep.
   - Also: "any German `LOCATION` / `DATE_TIME` hits that legitimately fire" — what counts as "legitimately"? `Berlin` and `morgen` are the only examples. No required test for legitimate-hit pass-through.
   - Recommendation: Add an explicit acceptance for REQ-006/007 that requires (a) at least one positive German LOCATION fixture and one positive German DATE_TIME fixture in `tests/eval/fixtures/de.yaml` whose entities must be in the post-filter `found` set (not just `issubset`-passed), (b) the calibration report committed alongside the threshold values must show the score distribution that justifies the chosen floor (e.g., "DE LOC chosen at 0.85 because the calibration corpus shows the bottom of the legitimate-hit distribution at 0.87 and the top of the noise distribution at 0.78"), and (c) re-running the calibration against the committed corpus reproduces the same threshold recommendations within ±0.05.

2. **REQ-008 "broader class" expansion target count vs. REQ-009 enumerated 15 — disparity with the `Personalausweis` headline test** [LOW]
   - Quote: REQ-008 (line 124): "The expansion totals **15 phrases** spanning all 4 sub-classes per RESEARCH-007 §7.4 (10 named + 5 sub-class extras)."
   - The 15 are enumerated in REQ-009, all bare nouns. Is 15 sufficient to falsify the bug class? The CLARIFICATION (Q5b) said "expand with ~10–20 German document/insurance/ID nouns" — 15 lands inside that range. But the spec doesn't say *why* 15 is the right number, and §7.4 of the research isn't quoted. If at calibration time the implementer encounters a new common noun that fires PERSON (e.g., a noun not in the 15), the spec doesn't say whether to add it to the corpus, document it as out-of-scope, or treat it as a model-swap trigger.
   - Recommendation: add a one-line note that any common-noun-as-PERSON discovery during calibration that's not in the 15 must be added to `de.yaml` as `expect_clean: true` before the feature lands.

3. **REQ-010 "API contract preservation" — gated by `tests/eval/` fixtures that use the bug-blind assertion the feature is fixing** [MEDIUM]
   - Quote: REQ-010 acceptance (line 130): "existing 41 eval fixtures pass without fixture-format modification; `tests/` (unit + integration) and `tests/e2e/` are green; OpenAPI spec at `/openapi.json` diff'd against `main` shows zero schema changes."
   - The 41 eval fixtures use `expect.issubset(found)` (research §8.2, also restated in research §0.4). Passing the existing 41 only proves no detection-set regression; it does **not** prove the API request/response shape, status codes, or headers are preserved. The OpenAPI schema diff catches schema changes, but not, e.g., a status-code change inside a 200 (different envelope shape) or a header behavior change (e.g., a new `X-Redakt-...` header). There is no specific test in the validation strategy that asserts the request body shape is unchanged on a representative request — the OpenAPI diff is the only structural gate.
   - The unit/integration tests under `tests/` are pre-existing; they pass today against the current API. The spec doesn't say whether they cover all three endpoints' full response envelope (status, headers, body shape) or whether the OpenAPI generated from FastAPI is exhaustive (FastAPI's auto-OpenAPI does NOT include custom headers added via middleware unless explicitly declared).
   - Recommendation: Add an explicit sub-REQ requiring a contract test (or extending an existing one) that asserts: for each of the three endpoints, a representative `200` response on `main` and on the feature branch produces byte-identical JSON envelopes (apart from `placeholder_to_original` content) AND identical response headers. This is the only way to make REQ-010 mechanically verifiable beyond the OpenAPI schema.

4. **REQ-011 recognizer-floor preservation — diff captured against what tree?** [LOW]
   - Quote: REQ-011 acceptance (line 139): "a diff of `presidio/.../conf/default_recognizers.yaml` between `main` and the feature branch shows additions only (or no changes)."
   - `presidio/` is a separate git repo per CLAUDE.md ("not a submodule"), forked from microsoft/presidio. The "feature branch" referenced for the Redakt repo and the equivalent branch in the Presidio fork repo are not the same branch. The spec doesn't say which branch in the fork repo to diff against, nor does it specify how the diff is captured for review (commit it, paste it in the implementation report, run a CI check). Implementer judgment will fill this in, with no consistent record.
   - Recommendation: Specify the diff target in both repos (Redakt: `main`; Presidio fork: the fork's tracking branch, e.g., `redakt-main`) and require the diff output to be included in the implementation report under `reports/`.

### Missing Specifications

5. **No coverage of `language auto-detect path` correctness under asymmetric routing** [MEDIUM]
   - Quote: CLARIFICATION-007 (line 37): "Both languages still resolve via existing language auto-detect (lingua-py based routing)." Glossary entry: "language auto-detect path — existing lingua-py based per-request language detection that selects the active engine."
   - The spec mentions auto-detect in EDGE-001 (code-switched text — accepted limitation), EDGE-004 (lingua-py mis-detection — accepted limitation), and REQ-012 (documentation). There is **no positive REQ** that asserts the auto-detect path correctly routes a `language: auto` request to the correct sub-engine in `MultiNlpEngine`, and **no test in the Validation Strategy** that exercises an `auto` request end-to-end. The MultiNlpEngine receives a language keyword from upstream — by the time it dispatches, the language has already been resolved by Redakt. But the integration between Redakt's resolved language and the Presidio analyzer's sub-engine selection is the new behavior surface, and it's not tested.
   - Why it matters: a regression in the resolution chain (e.g., Redakt sends `language: en`, MultiNlpEngine routes to spaCy en, but the dispatch keyword in `process_text` is the wrong string after normalization) would produce silent wrong-engine routing. The unit tests for `MultiNlpEngine.process_text(text, "en"|"de")` (Validation Strategy line 441) cover the dispatch in isolation, but there is no integration test that asserts: "POST /api/detect with German text and `language: auto` → Redakt resolves de via lingua → Presidio analyzer routes to TransformersNlpEngine → result transcript matches the German pipeline."
   - Suggested addition: Add a sub-REQ to REQ-001 or a new REQ-016: "An end-to-end integration test exercises `POST /api/detect` with `language: auto` for both an unambiguous German input and an unambiguous English input; asserts the language-resolved by Redakt matches the sub-engine that ran (verifiable via `?verbose=true` `analysis_explanation` fields, which carry the recognizer-side language)."

6. **No coverage of model warm-up / first-request latency vs. PERF-001 anchors** [LOW]
   - Quote: PERF-001 (line 184): "Reproducible latency baseline (anchored). To make future latency regressions detectable, the post-implementation calibration report MUST capture per-request latency (median over N≥5 runs, with N recorded) for these specific anchor inputs:"
   - The first request after a transformer model is loaded (even after `MultiNlpEngine.load()` completes) often has materially higher latency than subsequent requests because of CUDA-style runtime JIT, cuDNN-style autotune, PyTorch graph caching, or simple OS-level page-cache warm-up. With N≥5 runs and median, this is partly absorbed (the first cold request is dominated by p50), but the spec doesn't say whether the runs include a warm-up request that's discarded, or whether the first measurement captures the warm-up cost.
   - Why it matters: production users hitting the analyzer right after restart will see the warm-up latency, not the median. The PERF-001 baseline understates real-world worst-case if warm-up runs are discarded; overstates the steady-state if they're not.
   - Suggested addition: PERF-001 should specify: (a) capture both "first request after `load()` completes" (warm-up) and "median of next N≥5 requests" (steady-state), (b) record both numbers in the report.

7. **No acceptance test for the spec's claim that `MultiNlpEngine` lazy-loads not** [LOW]
   - Quote: REQ-001 (line 88): "A unit test confirms that two consecutive `process_text` calls do not re-invoke the underlying spaCy / transformers loaders (verified by patching the loaders and asserting call count == 1 from the `load()` step only)."
   - This is good. But it covers only the unit-test-mock path. It does not cover the production code path of "is the call to `process_text` actually receiving an already-loaded `nlp` object?" — i.e., a behavioral integration test. The acceptance is mockable but doesn't catch a bug where `MultiNlpEngine.__init__` accidentally re-instantiates the inner engine on every call.
   - Suggested addition: Add a second acceptance — a startup-time log-line probe (or equivalent) that confirms the model-load timestamps in the analyzer logs occur exactly once at boot, before the HTTP server binds.

8. **No acceptance for REQ-005a's "MUST NOT serve `/health` 200 with a partial engine state" behavior under partial-load** [LOW]
   - Quote: REQ-005a (line 108): "Until `is_loaded()` returns True for all languages, `/health` either returns 503 (if reachable) or, more typically, the HTTP server has not yet been bound to the port — both are acceptable."
   - Both are acceptable, but "both" is two distinct behaviors. The acceptance test (line 112) "confirms `/health` does not return 200 until `MultiNlpEngine.is_loaded() == True` for both `en` and `de`" is satisfied by either — but a docker-compose orchestrator's `healthcheck` config has different retry semantics for "503 returned" vs. "connection refused." If the actual production behavior is "connection refused for 25s, then 200" but the implementer's test environment shows "503 for 25s, then 200," the spec accepts both as passing while the orchestrator's behavior may differ.
   - Suggested addition: REQ-005a acceptance should specify which of the two behaviors the implementation produces (one is implementation-correct, not both) and require the docker-compose `healthcheck` to be tested against that specific behavior.

### Research Disconnects

9. **Research §0.4 explicitly says the existing 41 fixtures' green CI line is invisible to the over-detection bug. REQ-010 then uses those same 41 fixtures as the regression gate.**
   - Research finding (§0 bullet 4): "The current eval suite is structurally weak at catching over-detection. `tests/eval/test_calibration.py:55` enforces `expected.issubset(found)` — i.e. it asserts only that *every expected entity is found*, not that *unexpected entities are absent*."
   - REQ-010 acceptance (line 130) lists "existing 41 eval fixtures pass without fixture-format modification" as the API-contract-preservation gate. The research already said this gate is bug-blind for over-detection; the spec uses it for a different purpose (API contract preservation), but conflating "no detection regression" and "no API contract regression" via the same fixture set is exactly the kind of conflation the panel didn't catch and the implementer will lean on.
   - The 15 new `expect_clean: true` fixtures (REQ-009) close the over-detection blind spot for the *broader class*, but they don't add coverage for *under-detection regression on English* (CLARIFICATION-007 line 47: "Any English PERSON / EMAIL / PHONE entity previously flagged by spaCy is no longer flagged after the swap" — unacceptable failure). The `issubset` assertion catches this for entities that are flagged in the existing fixtures, but not for any entity type or content not represented in the existing 41. Since the English path is bit-for-bit identical (per spec line 30), this is structural — but the spec asserts this, doesn't test it.
   - Recommendation: Add a test that captures the English path's full entity-output snapshot pre- and post-feature, and asserts byte-identical output (because the English engine is unchanged). This makes the "bit-for-bit identical" claim mechanically verified.

10. **Research §11.3 (fork maintenance) is captured in RISK-003 but the spec doesn't operationalize the "one-line CI check that `MultiNlpEngine` still imports under the latest upstream Presidio" mitigation.**
    - Risk-003 (line 500): "Mitigation: keep diffs in clearly-delimited blocks … one-line CI check that `MultiNlpEngine` still imports under the latest upstream Presidio."
    - The "one-line CI check" is named as a mitigation but never specified as a deliverable (no REQ, no test in Validation Strategy). It will not be built unless someone reads the risks section and decides to.
    - Recommendation: Promote it to a sub-REQ ("REQ-017: Upstream-merge regression CI check") or explicitly mark it as out-of-scope for this feature with a tracking issue.

### Risk Reassessment

11. **MODULE-001 `MultiNlpEngine` Risk: Medium → should be HIGH**
    - Justification given (line 335): "On the request path; the entire analyzer depends on `MultiNlpEngine.process_text` for every detect call. Failures are recoverable via container restart; no irreversible side effects."
    - The "recoverable via container restart" framing is correct for *crash* failures. But the dominant risk for this module is *silent wrong-engine routing* — a bug where German text is processed by the spaCy English engine (or vice versa) produces wrong-but-valid output that is not detectable from the response (no exception, no error log) and is not caught by the existing `issubset` fixtures. The blast radius is "every German request silently over-detects PERSON for the lifetime of the bug." This is exactly the production risk the feature is designed to fix; an implementation bug in the dispatch logic re-introduces it under a new mechanism.
    - The Risk-Tiered Code Review at Step 4b uses MODULE risk tiers to decide review depth. Medium → less intensive review than HIGH. For a dispatch module where a one-character bug (`if language == "en"` vs `if language == "de"`) flips behavior to wrong-but-valid, HIGH is the right tier.
    - Recommendation: Re-tier MODULE-001 to HIGH. Update the justification: "On the request path. Failures may be silent (wrong-engine routing produces valid-shaped but wrong-content output, undetectable by existing `issubset` fixtures). The new `expect_clean` fixtures (REQ-009) catch the specific German over-detection class but do not catch a hypothetical en-routes-to-de swap. HIGH justified by silent-failure mode + production blast radius."

12. **MODULE-006 Threshold defaults Risk: Medium → consider HIGH**
    - Justification given (line 403): "Wrong values cause silent under- or over-redaction in production. Mitigation: REQ-006 / REQ-007 acceptance hinges on the full fixture set passing AND the `expect_clean` fixtures staying PASS — both bars catch wrong-direction tuning."
    - The mitigation is the calibration acceptance, but per finding #1 above, the calibration acceptance is circular (thresholds tuned against the fixtures that decide pass). A stronger framing: thresholds in production config are user-visible (env-var override is exposed via `REDAKT_ENTITY_SCORE_THRESHOLDS` per REQ-010), the values are committed defaults, and a wrong default ships silently to all instances.
    - This is borderline. If finding #1 is addressed (real held-out test for legitimate-hit pass-through), Medium is defensible. If not, HIGH is justified.
    - Recommendation: Re-tier conditional on finding #1. If finding #1 is accepted and addressed, MODULE-006 stays Medium. If not, raise to HIGH.

13. **RISK-001 (HIGH) "Transformer model download / availability" — mitigation completeness**
    - Mitigation (line 494): "pin model revision (REQ-013); document `Davlan/bert-base-multilingual-cased-ner-hrl` as the validated A/B fallback (ADR 0001 §Alternative F); CI catches build failures immediately."
    - Missing: HF Hub *rate limits* at build time. CI builds (especially after a clean checkout or cache invalidation) hit `huggingface_hub.snapshot_download`; HF Hub's anonymous rate limit is per-IP and modest. If CI runs many parallel jobs from one IP (common in monorepo CI), the build can fail with HTTP 429. REQ-013's revision pin doesn't help here. The fork's `install_nlp_models.py` doesn't appear to use a HF token; the spec doesn't require one.
    - Recommendation: Add a sentence to RISK-001's mitigation: "If CI builds hit HF Hub rate limits, configure `HUGGINGFACE_HUB_TOKEN` in CI environment and document this in `Dockerfile.transformers` setup notes." Or move this to the implementer's checklist. Currently neither.

### Recommended Actions Before Proceeding

1. **[MEDIUM] Address calibration loop circularity (finding #1)** — add a concrete acceptance for REQ-006/REQ-007 that requires (a) at least one positive DE LOCATION and DE DATE_TIME fixture in `tests/eval/fixtures/de.yaml` whose entities the post-filter must include in `found`, (b) the committed calibration report shows the score distribution that justifies each threshold, and (c) re-running calibration against the committed corpus reproduces threshold recommendations within ±0.05.

2. **[MEDIUM] Address API-contract conflation (finding #3 + #9)** — add a contract test asserting byte-identical response envelopes (status, headers, body) on representative requests pre- and post-feature for all three endpoints. The OpenAPI diff alone is insufficient.

3. **[MEDIUM] Add a positive auto-detect routing test (finding #5)** — sub-REQ for an integration test that asserts `language: auto` end-to-end correctly routes German input to the transformers sub-engine and English input to the spaCy sub-engine, verified via `?verbose=true` analysis explanations.

4. **[MEDIUM] Re-tier MODULE-001 risk to HIGH (finding #11)** — silent wrong-engine routing is the dominant production risk and is undetectable by existing `issubset` fixtures; the `expect_clean` fixtures from REQ-009 catch the German over-detection class but not a hypothetical engine-swap bug. HIGH justified by silent-failure mode.

5. **[LOW] Specify REQ-011 diff target across both repos (finding #4)** — name the Redakt branch and the Presidio fork branch to diff against; require the diff output in the implementation report.

6. **[LOW] Operationalize "broader-class extension" rule (finding #2)** — one-line note: any common-noun-as-PERSON discovery during calibration not in the 15 must be added to `de.yaml` as `expect_clean: true` before the feature lands.

7. **[LOW] Specify warm-up vs. steady-state latency capture (finding #6)** — PERF-001 should require both "first-request post-`load()`" and "median of next N≥5" to be captured.

8. **[LOW] Clarify REQ-005a's two-acceptable-behaviors split (finding #8)** — pick which of "503 returned" vs. "connection refused" the implementation produces; tie healthcheck retry semantics to that specific behavior.

9. **[LOW] Operationalize RISK-003 mitigation (finding #10)** — promote the "one-line CI check that `MultiNlpEngine` still imports under the latest upstream Presidio" to a sub-REQ or explicitly mark it out-of-scope.

10. **[LOW] Add HF rate-limit mitigation to RISK-001 (finding #13)** — note `HUGGINGFACE_HUB_TOKEN` configuration for CI environments.

11. **[LOW] Add behavioral acceptance for model-load-once (finding #7)** — startup-time log-line probe confirms model-load timestamps occur exactly once at boot, before HTTP server bind.

### Severity counts

- **HIGH:** 0
- **MEDIUM:** 4 (findings #1, #3, #5, #11)
- **LOW:** 7 (findings #2, #4, #6, #7, #8, #10, #13)

Note: findings #9 and #12 are framed as research-disconnect / risk-reassessment notes that fold into the MEDIUM/LOW recommendations above; not double-counted.

### Proceed/Hold Decision

**PROCEED WITH FIXES**

Rationale: 0 HIGH findings; the architecture is sound and the panel iter 2 PROCEED verdict stands. The 4 MEDIUM findings are localized acceptance/test-coverage issues, not architectural problems — each is addressable inline with the existing structure (no spec restructuring needed). The most consequential MEDIUM (calibration circularity, finding #1) is structural to how the spec defines "done" and should be addressed before implementation begins, because the implementer's interpretation of "iterate until pass" determines whether the feature reproducibly catches the bug class on re-runs. The MODULE-001 risk re-tier (finding #11) directly affects Step 4b code-review depth and should land before 4b begins. The remaining MEDIUM and all LOW findings can be batched into a Step 3e combined critical-review fix step alongside the deferred iter 1 / iter 2 panel LOWs.

---

**End of CRITICAL-SPEC-007 review.**

---

## Findings Addressed (Iteration combined-3e)

All 4 MEDIUM and 7 LOW findings from this critical review are addressed below; severity counts after fix: HIGH 0, MEDIUM 0, LOW 0.

### Finding #1 — REQ-006 + REQ-007 calibration loop has no defined stopping condition
Severity: MEDIUM
Resolution: REQ-006 rewritten with an explicit four-bar **calibration protocol (stopping condition)**: (1) negative bar — all 41 existing fixtures + 15 `expect_clean` fixtures stay PASS; (2) **held-out positive bar** — at least one DE LOCATION and one DE DATE_TIME positive fixture (added per the new REQ-009b) MUST produce expected entities in `found` via a true-positive harness assertion (distinct from `expect_clean` and from `issubset`-only); (3) **score-distribution justification** — the calibration report committed alongside thresholds MUST include a per-tuned-entity annotation showing the legitimate-hit floor vs. noise-top distribution that justified the chosen value (concrete format example given); (4) **reproducibility within ±0.05** — re-running calibration against the committed corpus and committed threshold values MUST reproduce the report's recommended floor within 0.05. Pablo's review remains required for sign-off but cannot waive any of (1)–(4). REQ-007 was updated to share the same four-bar acceptance jointly. The "iterate until pass" interpretation is closed; "Pablo declares it good" is no longer a sufficient exit. RISK-004 mitigation strengthened by reference. MODULE-006's mitigation language updated to cite the four-bar bidirectional bar.
Spec location: REQ-006 (rewritten with four-bar protocol); REQ-007 (updated to cite REQ-006 jointly); REQ-009b (new fixtures supplying the held-out positive bar); MODULE-006 (mitigation updated); Implementation Notes step 6 (rewritten).

### Finding #2 — REQ-008 broader-class extension target count rationale
Severity: LOW
Resolution: REQ-009 acceptance gained a "Broader-class extension rule (acceptance addendum)" paragraph stating: any common-noun-as-PERSON over-detection encountered during step 6 calibration that is NOT in the 15 enumerated nouns MUST be added to `tests/eval/fixtures/de.yaml` as `expect_clean: true` BEFORE the feature lands. Out-of-scope deferral or undocumented model-swap triggers are not permitted; the rule is "if calibration discovers it, the corpus must record it." This makes the broader-class corpus self-extending and prevents silent drift.
Spec location: REQ-009 (rule paragraph appended).

### Finding #3 + #9 — REQ-010 API contract preservation is bug-blind / over-detection blind spot conflation
Severity: MEDIUM
Resolution: New REQ-010a added: an explicit "API-shape regression test (byte-identical envelope + headers)" requirement, distinct from `tests/eval/` fixtures and distinct from the OpenAPI schema diff. Captures snapshots under `tests/contracts/` from `main`, runs the same fixed inputs against the feature branch, asserts byte-identical JSON envelopes for top-level keys, status codes, and response headers (apart from `placeholder_to_original` content; its *shape* must be identical), and explicitly asserts the absence of newly-introduced headers (which FastAPI's auto-OpenAPI does NOT cover for middleware-added headers). REQ-010 amended with a "Note" explicitly stating the eval-fixture green line is structurally weak at over-detection (per RESEARCH-007 §0.4) and is included for *detection-set non-regression* coverage, NOT as a contract-shape gate; the contract-shape gate is REQ-010a. Both REQ-010 and REQ-010a gate merge.
Spec location: REQ-010 (note paragraph + cross-link to REQ-010a); REQ-010a (new); Validation Strategy / Integration Tests (new line).

### Finding #4 — REQ-011 recognizer-floor preservation diff target unspecified
Severity: LOW
Resolution: REQ-011 acceptance now names both diff targets explicitly: (a) Redakt repo `main` vs. `feature/007-transformers-nlp-backend`; (b) Presidio fork repo's tracking branch (`main` of `git@github.com:pablooliva/presidio.git`) vs. the fork's feature branch corresponding to this work. Both diffs are captured via `git diff --no-color` and committed under `reports/req-011-recognizer-diffs.md`. If the fork-side branch name differs from the Redakt-side, the implementation report names the exact fork-side branch.
Spec location: REQ-011 (acceptance section restructured).

### Finding #5 — No coverage of `language: auto` end-to-end routing
Severity: MEDIUM
Resolution: New REQ-016 added: "End-to-end `language: auto` routing test (positive coverage)". Requires an integration test that POSTs an unambiguously German short sentence to `/api/detect?verbose=true` with `language: auto` and asserts the recognizer-side language reported is `de` and the entity output matches the German pipeline; symmetrically for English. The two assertions are inverted as a regression-detection sanity check — a hypothetical engine-swap bug produces a deterministic failure with a meaningful diff. Verified by an experimental implementation flip during development (revert before merge). REQ-016 is named as the structural mitigation for MODULE-001's HIGH risk tier and is referenced from MODULE-001 Spec refs.
Spec location: REQ-016 (new); MODULE-001 Spec refs (REQ-016 added); Validation Strategy / Integration Tests (new line).

### Finding #6 — No coverage of model warm-up / first-request latency
Severity: LOW
Resolution: PERF-001's "Reproducible latency baseline" rewritten with an explicit "Warm-up vs. steady-state capture" requirement. For each anchor, the report MUST capture two numbers: (a) **warm-up** — single run, the first request after `MultiNlpEngine.load()` completes, no warm-up discard (production restart worst-case); (b) **steady-state** — median over N≥5 runs *after* the warm-up run (warm-up NOT included in N). Both numbers appear in the report, e.g., `Personalausweis — warm-up: 4.2s; steady-state median (N=5): 0.9s`. The split prevents understating real-world worst-case (warm-up alone overstates steady-state) and prevents overstating it (median including warm-up under-counts the cold first request).
Spec location: PERF-001 (rewritten "Reproducible latency baseline" section).

### Finding #7 — No behavioral acceptance for model-load-once beyond unit-test mock
Severity: LOW
Resolution: PERF-002 extended with a "Behavioral acceptance for the model-load-once invariant" paragraph. The implementation MUST produce a structured startup-log line per model load (e.g., `LOADED en_core_web_lg at <ts>`, `LOADED de_core_news_sm at <ts>`, `LOADED xlm-roberta-large-finetuned-conll03-german at <ts>`). The implementation report includes a captured analyzer-startup log excerpt confirming each line appears exactly once and all three appear before the HTTP server binds (i.e., before any `/health` 200 is served). One-time-during-implementation verification, complementing the existing REQ-001 unit-test-mock acceptance.
Spec location: PERF-002 (paragraph appended).

### Finding #8 — REQ-005a's "503 OR connection-refused" two-acceptable-behaviors split
Severity: LOW
Resolution: REQ-005a clarified: the implementation MUST exhibit **one** of two specific behaviors (A — server bound, `/health` returns 503; B — server has not yet bound, orchestrator gets connection-refused) and the docker-compose `healthcheck` retry semantics MUST match the chosen behavior. The implementation report documents which behavior was selected and why (typically B because Presidio constructs the engine eagerly during Flask app initialization). The compose `healthcheck`'s `start_period`, `interval`, and `retries` are tuned for the chosen behavior. This converts "both acceptable" into "pick one and tie healthcheck retry semantics to it."
Spec location: REQ-005a (bullet about partial-load behavior rewritten with sub-bullets).

### Finding #10 — RISK-003 mitigation "one-line CI check" not operationalized
Severity: LOW
Resolution: New REQ-017 added: "Upstream-merge regression CI check (`MultiNlpEngine` import smoke)". A small CI job (one shell step or a tiny new workflow file) periodically (or on push to a designated tracking branch) checks out the latest upstream `microsoft/presidio` `main`, applies the fork's `MultiNlpEngine` patch on top, and runs `python -c "from presidio_analyzer.nlp_engine.multi_nlp_engine import MultiNlpEngine"` as a smoke check. Failure produces a maintainer-visible signal but does NOT block production deploys (production fork pin unchanged). If implementing the CI step is infeasible within this feature's scope, REQ-017 MAY be marked "deferred to follow-up" with explicit operator sign-off in the implementation report — silent omission is not acceptable. RISK-003's mitigation text was updated to cross-link REQ-017 (mitigation now operationalized as a deliverable, not a Risks-section-only aspiration).
Spec location: REQ-017 (new); RISK-003 (mitigation paragraph updated to cite REQ-017).

### Finding #11 — MODULE-001 risk Medium → HIGH (silent wrong-engine routing)
Severity: MEDIUM (risk re-tier)
Resolution: MODULE-001 Risk re-tiered from Medium to **HIGH** with rewritten justification explicitly naming silent wrong-engine routing as the dominant production risk: a one-character bug in dispatch logic (`if language == "en"` vs `if language == "de"`) flips behavior to wrong-but-valid output, producing no exception or error log, undetectable by `expect.issubset(found)` fixtures. The new `expect_clean: true` fixtures (REQ-009) catch the German-side over-detection class but do NOT catch a hypothetical engine-swap bug. The new positive auto-detect routing test (REQ-016) is named as the structural mitigation for the silent-failure mode. Justification ends with: "HIGH justified by silent-failure mode + production blast radius. This Risk tier propagates to `/sdd:code-review` Step 4b which scales review depth." Spec refs updated to include REQ-010a + REQ-016.
Spec location: MODULE-001 Risk (rewritten); MODULE-001 Spec refs (REQ-010a, REQ-016 added).

### Finding #12 — MODULE-006 risk reassessment (conditional on #1)
Severity: not separately counted (folded into LOW disposition)
Resolution: With Finding #1 fully addressed via REQ-006's four-bar protocol (held-out positive bar, score-distribution justification, reproducibility within ±0.05), MODULE-006 stays at **Medium**. The mitigation paragraph in MODULE-006 was updated to cite the four-bar bidirectional bar — "the original Medium framing's 'circular acceptance' critique is closed by bars 2–4." The conditional re-tier to HIGH is not triggered because Finding #1 is accepted and addressed.
Spec location: MODULE-006 Risk (mitigation paragraph rewritten).

### Finding #13 — RISK-001 missing HF Hub rate-limit mitigation
Severity: LOW
Resolution: RISK-001's mitigation paragraph extended with an explicit HF rate-limit mitigation: anonymous HF Hub egress is rate-limited per-IP and modest; CI builds running parallel jobs from one IP can hit HTTP 429 even with a pinned revision. Mitigation: configure `HUGGINGFACE_HUB_TOKEN` (or `HF_TOKEN`) in the CI environment for authenticated downloads (higher per-account rate limit); the token is read by `huggingface_hub.snapshot_download` automatically when present. The env-var requirement is documented in `presidio/Dockerfile.transformers`'s setup notes / `docs/presidio-integration.md` per Implementation Notes step 9. The token is build-time only and is NOT baked into the image.
Spec location: RISK-001 (mitigation paragraph extended); Implementation Notes step 9 (docs update item).
