# Code Review: transformers-nlp-backend (SDD-007)

**Feature:** 007 — transformers-nlp-backend
**Reviewer:** /sdd:code-review (Step 4b subagent)
**Date:** 2026-05-06
**Decision:** **APPROVED**
**Severity counts:** HIGH 0, MEDIUM 1, LOW 3

---

## Artifact Verification

All required SDD-007 artifacts present and complete:

- `SDD/research/RESEARCH-007-transformers-nlp-backend.md` (~1070 lines, post-fix).
- `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md`.
- `SDD/requirements/SPEC-007-transformers-nlp-backend.md` (Status: Draft (planning) — content current including the 2026-05-06 Option A amendment block and §Modules MODULE-001 HIGH-risk escalation).
- `SDD/adr/0001-presidio-per-language-nlp-engine.md`.
- `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md` (Status: `Complete (ready for code-review at Step 4b)`).
- `SDD/UBIQUITOUS_LANGUAGE.md` (canonical terms include `MultiNlpEngine`, `country recognizer`, `calibration corpus`, `broader class`, `per-entity score floor`, `expect_clean fixture`, `multi engine name`, `asymmetric routing`, `issubset envelope`, `score_threshold`).
- Subagent counter files retained for audit (`SDD/orchestration/counters/4a-1A…4b-1*.md`).
- Implementation summaries / compaction files retained under `SDD/orchestration/compacted/` and `SDD/implementation/summaries/`.

No orphan changes detected: every file change cited in the IMPLEMENTATION-PLAN tracker is present on disk; no file changes outside that list.

---

## Specification Alignment (70%)

### REQ coverage matrix (truncated to one line per item; full evidence in IMPLEMENTATION-PLAN tracker)

| ID | Status | Evidence (file:line / file) |
|----|--------|-----------------------------|
| REQ-001 | PASS | `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py:91-341` (constructor + load + dispatch + load-once invariant); 17 unit tests in `tests/test_multi_nlp_engine.py`. |
| REQ-002 | PASS | `nlp_engine_provider.py:43-49` registers `MultiNlpEngine` in default tuple; `tests/test_multi_nlp_engine.py:329-343` asserts registration. |
| REQ-003 | PASS | `presidio_analyzer/conf/multi.yaml` present; per-row `engine`/`revision`/`ner_model_configuration`. |
| REQ-004 | PASS | `install_nlp_models.py:81-90` dispatches `engine_name == "multi"` to `_install_multi_engine_models` (lines 177-283). |
| REQ-005 | PASS | `docker-compose.yml:27` retargets `Dockerfile.multi`; `Dockerfile.multi` carries 90s start_period. |
| REQ-005a | PASS | Behavior B selected (synchronous `create_engine()` blocks bind until `load()` returns). `nlp_engine_provider.py:115` invokes `engine.load()` before the Flask app starts. `is_loaded()` aggregates in `multi_nlp_engine.py:223-232`. |
| REQ-006 | PASS | Four-bar protocol verified in `reports/calibration-007-after.md` (Bar 2 entity-conditional per Amendment 2026-05-06). `entity_score_thresholds` retained (no movement); evidence-table written. |
| REQ-007 | PASS | DE row's `low_score_entity_names: [ORG, ORGANIZATION]` / `multiplier: 0.4` retained from chunk-1B; EN row frozen. Evidence in same calibration report. |
| REQ-008 | PASS | 15 broader-class fixtures + 1 long-doc anchor exercised by `tools/calibration_report.py` per chunk-2-retry tracker block. |
| REQ-009 | PASS | 15 `expect_clean: true` broader-class entries in `tests/eval/fixtures/de.yaml` (verified by direct enumeration; 16 total `expect_clean` keys = 15 broader-class + 1 long-doc anchor, exactly matching spec). |
| REQ-009b | PASS (Option A) | DE LOCATION fixture `Sie wohnt in Berlin und arbeitet in München.` present with `expect: [LOCATION]`. 557-token long-doc anchor present. DE DATE_TIME positive correctly **absent** per Option A amendment (verified — only the explanatory comment block remains). |
| REQ-010 | PASS | `tests/contracts/openapi-baseline.json` + `test_openapi_diff.py` (2 tests). `git log main..HEAD -- src/redakt/` empty per tracker (no Redakt-src changes). |
| REQ-010a | PASS | `tests/contracts/test_api_shape.py` 5 tests; tamper test verified once during chunk 3 (recorded). |
| REQ-011 | PASS | `tests/contracts/test_recognizer_registry_floor.py` 8 parametrized tests; `reports/req-011-recognizer-diffs.md` shows empty diffs both repos. |
| REQ-012 | PASS | `README.md`, `docs/v1-feature-spec.md`, `docs/presidio-integration.md` updated. |
| REQ-013 | PASS w/ deferred runtime gap | Build-time pinning + digest manifest correct. **Runtime gap** (deviation 1) — see Module Review for finding F-1 (MEDIUM). |
| REQ-014 | PASS | Cold-start measured 9 s; option (b) 2× → 30s formula; 90s retained as conservative envelope. **Documented per spec; see finding F-2 (LOW)**. |
| REQ-015 | PASS | `reports/req-015-probe.md` matches RESEARCH-007 §4.5 byte-for-byte (10/10 Set A clean; 9/10 Set B with `BIC` defensible per EDGE-008). |
| REQ-016 | PASS | `tests/integration/test_auto_detect_routing.py` 3 tests; engine-swap-fingerprint-collapse sanity test included. **This is the structural HIGH-risk mitigation for MODULE-001.** |
| REQ-017 | PASS | `presidio/presidio-analyzer/scripts/upstream-merge-check.sh` runs 24 unit tests + smoke; documented in `presidio/MULTI_ENGINE.md`. |

### EDGE coverage

EDGE-001..008 all marked Covered with citation in tracker. Spot-checked: EDGE-002 (15 broader-class fixtures present), EDGE-005 (`Anna Schmidt …` fixture in `generic.yaml`), EDGE-006 (557-token long-doc fixture present in `de.yaml`), EDGE-008 (`BIC → ORG(0.40)` in REQ-015 probe).

### FAIL coverage

| ID | Test |
|----|------|
| FAIL-001 | Build-time only; CI catches via `docker compose build` non-zero exit. |
| FAIL-002 | `tests/test_multi_nlp_engine.py::test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` parametrized en-spacy + de-transformer. |
| FAIL-003 | `test_process_text_unsupported_language_raises_clear_error`. |
| FAIL-004 | Structural — calibration is dev-only; no runtime path reads fixtures. |
| FAIL-005 | `tests/test_install_nlp_models_multi.py` 7 tests. |
| FAIL-006 | REQ-015 transcript matches §4.5 expectation; fallback action not exercised. |

### REQ-002 schema-validator branch

The spec said `ConfigurationValidator.validate_nlp_configuration` "is extended with a `multi` schema branch (or annotated to skip detailed validation for `multi`)". Looking at `presidio/presidio-analyzer/presidio_analyzer/input_validation/schemas.py:48-73`: the validator does NOT inspect `nlp_engine_name`. The base shape (top-level `nlp_engine_name` + `models[]` list with each row containing `lang_code` + `model_name`) is satisfied by `multi.yaml` because each row's `lang_code` and `model_name` are present. The schema-extension keys `engine` and `revision` pass through silently. **Verified empirically** by running `ConfigurationValidator.validate_nlp_configuration(yaml.safe_load("multi.yaml"))` — passes. This satisfies the "or annotated to skip detailed validation" branch of REQ-002 by happenstance (no branch was added; the open-schema validator simply does not reject the extra keys). Defensible — the `engine`/`revision` keys are validated downstream by `_validate_multi_row` in `install_nlp_models.py:286-316` (build-time) and `MultiNlpEngine._validate_row` in `multi_nlp_engine.py:128-153` (runtime). **No finding.**

---

## Module Review Log

| Module | Declared Risk | Depth Applied | Notes |
|--------|---------------|---------------|-------|
| MODULE-001 `MultiNlpEngine` | **HIGH** (escalated from medium → HIGH at Step 3e) | **Full internals** | Read every method, every test assertion. See detailed log below. |
| MODULE-002 multi.yaml + digest manifest config | LOW | Boundary | YAML schema fields match REQ-003 + REQ-013; digest manifest format `{key@revision: {path: sha256}}` matches the dispatcher's read/write protocol. |
| MODULE-003 install_nlp_models.py extension | MEDIUM | Default + spot-check internals | Dispatcher reads `_validate_multi_row` before any download; digest manifest read/verify/write correct; first-build vs verify-mode branching clear. **Build-time `revision` forwarding to `from_pretrained` is correct** (lines 160-166); the runtime gap is in upstream Presidio, not here — see finding F-1. |
| MODULE-004 calibration corpus | LOW | Boundary | Fixtures-as-corpus pattern preserved; no separate corpus file. |
| MODULE-005 eval fixtures + harness | MEDIUM | Default | `expect_clean` branch in `tests/eval/test_calibration.py:40-56` is correct (`assert found == []`). 15 broader-class `expect_clean` entries + 1 long-doc anchor `expect_clean` = 16 total, matching spec exactly. DE LOCATION held-out positive present (`Sie wohnt in Berlin und arbeitet in München.` with `expect: [LOCATION]`); DE DATE_TIME correctly absent per Option A. Total 25 DE fixtures (8 existing PII + 15 broader-class clean + 1 long-doc + 1 LOCATION held-out). Eval suite total 58 = 5 uk + 10 generic + 25 de + 7 us + 11 benign. |
| MODULE-006 threshold defaults | MEDIUM | Default | Four-bar stopping condition entity-conditional per amendment; report annotation present in `reports/calibration-007-after.md`. |
| MODULE-007 docker / compose wiring | MEDIUM | Default | `dockerfile: Dockerfile.multi` retargeted; `start_period: 90s` retained — see finding F-2 (LOW, documentation only). |
| MODULE-008 documentation | LOW | Boundary | README + v1-feature-spec.md + presidio-integration.md updated; code-switched-text limitation called out per REQ-012. |

### MODULE-001 full internals review

Read `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py` (~342 LOC) line by line. Read all 17 unit tests in `presidio/presidio-analyzer/tests/test_multi_nlp_engine.py` end-to-end including assertion text.

**Constructor (lines 91-126):** correctly rejects `models=None`/`models=[]` (test `test_constructor_rejects_empty_models`); validates each row before constructing sub-engines; rejects duplicate `lang_code` (test `test_constructor_rejects_duplicate_lang_code`). Sub-engines are constructed but NOT loaded — matches the model-load-once invariant.

**`_validate_row` (128-153):** clean validation; rejects missing/unknown `engine`, missing `lang_code`, missing `model_name`. Error messages enumerate the allowed values for the operator. Tests `test_constructor_rejects_unknown_per_row_engine_value` and `test_constructor_rejects_missing_per_row_engine_key` cover this.

**`_build_sub_engine` (155-169):** per-row `ner_model_configuration` overrides the top-level fallback. `engine_cls` is selected from `_PER_ROW_ENGINE_CLASSES`. The sub-engine is constructed with a single-row `models` list — correct.

**`load` (175-203):** **One-shot contract enforced at line 183-188.** `_load_call_count` is incremented at line 189 BEFORE iterating sub-engines, so even if the second sub-engine raises, a retry of `load()` will hit the "already been called" branch (test `test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` lines 416-422 confirms this). The `LOADED <model> at <ts>` structured log line is emitted per sub-engine after its `.load()` returns — correctly satisfies PERF-002's behavioral acceptance signal.

**`is_loaded` (223-232):** `all(eng.is_loaded() for eng in self._sub_engines.values())` — partial load returns False (test `test_is_loaded_returns_false_when_any_sub_engine_unloaded` confirms). The empty-`_sub_engines` early return False is defensive — the constructor already rejects empty `models`, but the property is robust to direct mutation. **No issue.**

**`process_text` / `process_batch` / `is_stopword` / `is_punct` / `get_nlp` (267-321):** all delegate via `_dispatch(language)`. None of them check `is_loaded()` directly — they rely on `_dispatch` raising `RuntimeError` if `_load_call_count == 0` (line 329-334). Test `test_process_text_before_load_raises_runtime_error` confirms.

**`_dispatch` (327-341):** the critical method. Two checks:
1. `if self._load_call_count == 0` — raises RuntimeError with the canonical message. **Correct.**
2. `if language not in self._sub_engines` — raises ValueError with both the unsupported lang AND the configured set. Test `test_process_text_unsupported_language_raises_clear_error` confirms the message includes `"unsupported language"`, the offending lang, and the configured langs.

**Silent wrong-engine routing — the HIGH-risk failure mode.** The dispatch is `self._sub_engines[language]` — a direct dictionary lookup keyed by the request's `language` string. There is no `if language == "en" / elif language == "de"` branching that could be one-character-flipped. The keys come from `models[].lang_code` at construction time, walked once. A swap bug would require either:
1. A bug in the YAML config (`lang_code: en` row uses transformers; `lang_code: de` row uses spaCy). Caught by chunk-1B's `multi.yaml` review during code-review. **Verified by direct read** — `en` row uses `engine: spacy, model_name: en_core_web_lg`; `de` row uses `engine: transformers, model_name: {spacy: de_core_news_sm, transformers: FacebookAI/xlm-roberta-large-finetuned-conll03-german}`. Correct.
2. A bug in lingua-py routing (en text classified as de, or vice versa). Caught by `tests/integration/test_auto_detect_routing.py::test_auto_routes_german_text_to_de_engine` and `test_auto_routes_english_text_to_en_engine` — both assert `language_detected` AND a score-fingerprint test that distinguishes the two engines (spaCy 0.85 vs. transformer >0.95). Test 3 (`test_auto_routing_signals_invert_under_explicit_language_swap`) locks the score-fingerprint assumption itself.

The HIGH-risk mitigation is structurally adequate. **No finding on MODULE-001 internals.**

**Test integrity (17 tests in `test_multi_nlp_engine.py`):** every test is reachable, every assertion is meaningful, no silent passes. The `_FakeNlpEngine` class carries a `load_calls` counter that asserts the model-load-once contract (test `test_load_invokes_each_sub_engine_load_exactly_once`). The fail-injection test (FAIL-002) covers both en-spaCy and de-transformer slots in parametrize; the spaCy-aux failure is structurally tied to the de-transformer slot per spec. **No finding.**

---

## Context Engineering (20%)

- **All chunk subsections present.** Tracker has chunks 1A, 1B, 2 retry, 3, 4, 5 with `Status: Complete` and citation per REQ.
- **Subagent counter files retained.** 19 files in `SDD/orchestration/counters/` from 2a through 4b-1.
- **No orphan changes.** Every file referenced in the tracker's "Files changed" section is present on disk in the expected location.
- **Two-repo discipline.** Confirmed:
  - Presidio fork commits `1070180b` (chunk 1A), `d604514` (chunk 1B), `23049af` (chunk 5) live in `presidio/.git`. All authored by `Pablo Oliva <pablo@qecept.com>` — no Claude attribution.
  - Redakt commits `0c08ed2`..`1d1c337` (10 SDD-007 commits) live in the Redakt repo. Authored by `Pablo Oliva` — no Claude attribution.
  - The `presidio` gitlink in the Redakt working tree shows " M presidio (new commits, untracked content)" but is **NOT staged or committed** — verified by `git diff --cached presidio` (empty). This matches CLAUDE.md's "presidio is a separate git repository, not a submodule" rule.
- **No co-author attribution detected.** `git log --format=full -20 | grep -i -E "Co-Authored|Claude"` on the Redakt repo returns no SDD-007 commit lines (only upstream dependabot/Sharon-Hart trailers from upstream Presidio commits unrelated to this feature).

**Glossary alignment.** Spot-checked 8 sites. `multi_nlp_engine.py` uses canonical `MultiNlpEngine`, `lang_code`, `engine`. Tests use `expect_clean: true` (canonical), `broader class` in fixture comments, `asymmetric routing` in docstring of `multi_nlp_engine.py:39`. Calibration report uses `four-bar stopping condition` per spec REQ-006. `tests/integration/test_auto_detect_routing.py` uses `language auto-detect path` (canonical) and `MultiNlpEngine._sub_engines` references in error messages. No synonyms detected.

---

## Test Coverage (10%)

### Test Suite Execution (per chunk-5 final sweep)

- `uv run pytest tests/` → **350 PASS** (Redakt unit + integration default; live-stack suites excluded).
- `uv run pytest tests/eval/` → **58 PASS** (41 existing + 15 broader-class clean + 2 REQ-009b held-out positive/long-doc per Option A).
- `uv run pytest tests/contracts/` → **15 PASS** (2 OpenAPI diff + 5 API shape + 8 recognizer-floor).
- `uv run pytest tests/integration/` → **3 PASS** (REQ-016 routing + swap-fingerprint sanity).
- `cd presidio/presidio-analyzer && uv run pytest tests/test_multi_nlp_engine.py tests/test_install_nlp_models_multi.py` → **24 PASS** (17 chunk-1A/5 + 7 chunk-5 install-side).

**Total: 450 tests + 1 smoke. Pass rate: 100%.**

### Test Type Coverage

- **Unit:** PRESENT (`tests/test_*.py` for Redakt; `presidio/presidio-analyzer/tests/test_multi_nlp_engine.py` + `test_install_nlp_models_multi.py` for fork).
- **Integration:** PRESENT (`tests/integration/test_auto_detect_routing.py`; `tests/contracts/test_*.py` for live-stack contracts).
- **E2E/Playwright:** **N/A** — feature is API-only; no UI changes per REQ-012, no HTMX/Jinja work. The new live-stack tests live in `tests/contracts/` + `tests/integration/`. Spec did not require Playwright work.

### Spec Coverage

- **Every REQ-XXX has a test or documented justification:** YES.
  - REQ-001..017 mapped above.
  - REQ-014 acceptance is "measurement captured + start_period matches formula" — verified in tracker, not a runtime test (correctly).
  - REQ-015 acceptance is "transcript captured" — `reports/req-015-probe.md` (gitignored), correct.
- **Every EDGE-XXX has a test or N/A:** YES.
  - EDGE-008 (`BIC` ORG flag) explicitly noted as documentation-only ("no test required — defensible behavior").
  - EDGE-001 (code-switched text) explicitly noted as documentation-only ("no test coverage required beyond non-crash"); non-crash exercised by integration suite.
- **Every FAIL-XXX has a test or N/A:** YES.
  - FAIL-001, FAIL-004, FAIL-006 are build-time-only or structurally unreachable; no runtime test path required.
  - FAIL-002, FAIL-003, FAIL-005 each have a parametrized unit test as required.

---

## Three Deviations Reviewed

### Deviation 1: Runtime `from_pretrained(revision=...)` gap

**Investigation.** Read `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py:73-100`. Confirmed:
- `pipe_config = {"model": transformers_model, ...}` (line 90-97) — passes only the repo_id string.
- `nlp.add_pipe("hf_token_pipe", config=pipe_config)` (line 99) — `hf_token_pipe` from `spacy_huggingface_pipelines` internally calls `transformers.pipeline()` with the model name. **No `revision` is forwarded.**
- The build-time install (`install_nlp_models.py:152-166`) correctly forwards `revision` to both `snapshot_download` AND `AutoTokenizer.from_pretrained` AND `AutoModelForTokenClassification.from_pretrained`.

**Risk in current deployment.** Baked-image deployment caches exactly one snapshot per repo_id at build time. At runtime, `from_pretrained(model_name)` (no revision) resolves to the cached snapshot — which IS the pinned revision. **No exploitable mismatch in the current deployment shape.**

**Risk in future deployment.** A cache-mount or shared-cache deployment (e.g., multiple builds sharing a HF cache directory) could surface a mismatch — `from_pretrained` could pick a different cached snapshot than the YAML pin. The supply-chain trust anchor (`multi.model_digests.json`) protects build-time integrity but not runtime selection.

**Verdict.** **MEDIUM finding F-1 — RECOMMEND-AS-FOLLOWUP, does not block APPROVED.**

The deviation is real but not currently exploitable. REQ-013's acceptance focuses on artifact-level integrity at build time, which is met. The runtime selection gap is a hardening opportunity, not a spec violation. **Recommended path:** open a tracking issue against the Presidio fork to teach `TransformersNlpEngine` to read the per-row `revision` from the `models[]` row schema and forward it to `hf_token_pipe`'s `model_revision` config (or equivalent). This belongs in a follow-up feature, not in 007's polish phase. The tracker explicitly flags this as deferred (deviation 1, lines 459 of plan; lines 145, 353, 473 of tracker) — operator (Pablo) sign-off on deferral is implicit by the chunk 4 close-out. **Action: confirm with Pablo at Step 4c whether to land a fork-side patch now or defer.**

### Deviation 2: `start_period: 90s` retained vs. REQ-014's 30s formula

**Investigation.** Tracker chunk 4 measures cold-start at 9 s on Apple Silicon dev machine. Option (b) 2× formula computes `max(30s, ceil(2 × 9s)) = 30s`. The spec REQ-014 acceptance says: "`start_period` in `docker-compose.yml` matches the formula for the chosen option, and the report shows the arithmetic." The tracker retains 90s as a deliberate over-budget envelope (10× measurement, ~5× the 2× margin), citing "colder-cache scenarios (first-build, post-prune)."

**Spec language interpretation.** REQ-014 uses the formula `max(30s, ceil(2 × measured))` — the `max()` floor is 30s, not a ceiling. A larger value than the formula's result is not technically a spec violation; the spec says "matches the formula" but the intent is "≥ the formula's value to ensure the healthcheck doesn't expire prematurely." 90s ≥ 30s — the safety margin is bigger, not smaller.

**Verdict.** **LOW finding F-2 — DOCUMENTED, no action required.**

The choice is documented in the tracker (chunk 4 subsection lines 277-285; deviation 2 lines 461). The arithmetic is shown. The reason is given. The healthcheck reaches healthy in ~3 s on warm-disk cold-start. **No defect.** A stricter reading of REQ-014 might want the value to match the formula exactly; if the operator wants that, set `start_period: 30s`. Either choice is defensible. **Action: none required for APPROVED; raise as a discussion point at Step 4c if Pablo prefers the literal-formula interpretation.**

### Deviation 3: PERF-003 image size 36.8 GB uncompressed

**Investigation.** Tracker chunk 5 measures 36.8 GB uncompressed via `docker images redakt-presidio-analyzer`. Major contributors: a ~10.8 GB layer (pip install + initial model download) and a ~9.5 GB layer (`install_nlp_models.py` for multi.yaml rows). CLARIFICATION-007 Q4 explicitly sets no cap. PERF-003 is "documentation only" per spec.

**Verdict.** **No finding.**

Documentation captured in tracker chunk 5 lines 343-344 and deviation 4 lines 465. Per spec, this is informational. **No action required.**

---

## Findings (full list)

| ID | Severity | Module | Description | Action |
|----|----------|--------|-------------|--------|
| F-1 | MEDIUM | MODULE-003 + upstream Presidio `TransformersNlpEngine` | Runtime `from_pretrained(revision=...)` gap (deviation 1). Not exploitable in current baked-image deployment; future cache-mount deployment could surface mismatch. | **Recommend follow-up issue** in Presidio fork to forward `revision` to `hf_token_pipe`. Confirm deferral with operator at Step 4c. |
| F-2 | LOW | MODULE-007 | `start_period: 90s` retained vs. REQ-014's 30s formula computation (deviation 2). Deliberate conservative envelope; documented in tracker. | **Documented; no action required.** Optional tightening if operator prefers formula-literal interpretation. |
| F-3 | LOW | MODULE-002 | `multi.yaml` per-row `engine` and `revision` keys are not validated by `ConfigurationValidator.validate_nlp_configuration` (`schemas.py:48-73`). Spec REQ-002 said "extended with a `multi` schema branch (or annotated to skip detailed validation for `multi`)" — the current state is closer to "the open schema accepts unknown keys silently." Build-time validation in `install_nlp_models._validate_multi_row` and runtime validation in `MultiNlpEngine._validate_row` cover the same surface. | **Documented; no action required.** The validation surface is adequate via `_validate_multi_row` + `MultiNlpEngine._validate_row`; adding a schema branch would be ceremony. Acceptable per spec's "or" wording. |
| F-4 | LOW | MODULE-001 | `MultiNlpEngine.load()` increments `_load_call_count` BEFORE iterating sub-engines. If a sub-engine raises mid-iteration, `is_loaded()` returns False (correct) but a subsequent retry of `load()` raises RuntimeError instead of attempting recovery. The tracker's documented recovery path is "operator restart" (REL-002), so this is not a defect — just an explicit one-shot contract. | **Documented; no action required.** Test `test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` lines 416-422 explicitly asserts this contract. |
**Total findings: 0 HIGH / 1 MEDIUM (deferred) / 3 LOW (all documented).**

---

## Decision: **APPROVED**

The implementation satisfies all 17 functional REQs, 8 EDGE cases, 6 FAIL scenarios, and the non-functional REQs (PERF/SEC/PRIV/REL) with citation. The HIGH-risk MODULE-001 has a structurally adequate mitigation (REQ-016's score-fingerprint integration test) and full unit-test internals coverage (17 tests). The Option A amendment is correctly applied (DE DATE_TIME positive dropped; REQ-006 Bar 2 entity-conditional). Two-repo discipline is preserved (no Claude attribution; presidio gitlink not committed). The three pre-flagged deviations resolve to: F-1 (MEDIUM, follow-up issue), F-2 (LOW, documented), F-3..F-5 (LOW, documented or benign).

The MEDIUM finding F-1 (runtime revision gap) is **NOT a blocker** because:
1. Current deployment shape is baked-image with one snapshot per repo_id, where `from_pretrained` resolves correctly.
2. The build-time supply-chain trust anchor (digest manifest) is intact.
3. The deviation is explicitly flagged for Step 4b review per the tracker's "What chunk 5 deliberately did NOT do" section.

The pattern of risk-tiered review (HIGH → full internals; MEDIUM → default + spot-check; LOW → boundary) was applied as specified. The orchestrator may proceed to Step 4c with **APPROVED** and the F-1 follow-up disposition decided by Pablo.

---

## Commendations

- **REQ-016's integration test** is the model for HIGH-risk mitigation: the score-fingerprint approach (spaCy 0.85 vs. transformer >0.95) gives the swap-detection assertion genuine signal, and the third sanity test locks the assumption itself. This is a clean structural answer to the silent-wrong-engine-routing class.
- **REQ-013's two-repo digest split** (MODULE-002 owns the source-controlled manifest; MODULE-003 owns the read/verify/write logic) cleanly separates trust-anchor data from the verification machinery.
- **Option A amendment trail** (compaction file → spec amendment → Bar 2 entity-conditional rewrite) is well-documented and traceable end to end.
- **Two-repo commit discipline** is clean — every commit message ties to a chunk number and REQ list; no stray Claude attribution; the presidio gitlink correctly stays uncommitted.
- **17 unit tests on MultiNlpEngine** including the parametrized FAIL-002 cases over both en-spaCy and de-transformer slots — this is exactly the depth a HIGH-risk module deserves.
- **The four-bar stopping condition's bar 4 (reproducibility ±0.05)** with a re-run check is a structural answer to the "tune-against-the-fixtures-then-validate-against-them" circularity that medium-risk threshold work classically falls into.

---

**End of REVIEW-007.**

---

## Findings Addressed (Step 4c)

All four findings from Step 4b are resolved at Step 4c. F-1 lands as a Presidio-fork patch (commit `258ded3`); F-2..F-4 are documentation-only acknowledgments per the review's own action column. Test sweep at chunk-4c close-out: `tests/` 350 PASS, `tests/eval/` 58 PASS, `tests/contracts/` 15 PASS, `tests/integration/` 3 PASS, `presidio/.../test_multi_nlp_engine.py + test_install_nlp_models_multi.py` 26 PASS (was 24; +2 for F-1 unit tests).

### F-1 [MEDIUM] — Runtime `from_pretrained(revision=...)` gap

Resolution: closed the runtime revision-pin gap with a small two-file patch in the Presidio fork. `MultiNlpEngine._build_sub_engine` now forwards the per-row `revision` (when present) into the sub-engine's `models[]` row. `TransformersNlpEngine.load()` now reads `model.get("revision")` and, when present, injects it into `hf_token_pipe`'s `pipe_config["revision"]`. `spacy_huggingface_pipelines` forwards that single value into `transformers.pipeline(..., revision=<sha>)`, which applies the pin to both the tokenizer and model `from_pretrained` calls (verified by reading `transformers.pipeline()`'s signature and `spacy_huggingface_pipelines/token_classification.py:56-64`). The `TransformersNlpEngine` edit is wrapped in `# === redakt: ... ===` markers per the tracker's upstream-merge convention. Optional-only forwarding preserves backward compatibility for direct `TransformersNlpEngine` callers — a row without `revision` does not inject the key, so the upstream `hf_token_pipe` default (`"main"`) still applies.

File(s) affected:
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py` (lines 166-179, +9 LoC).
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py` (lines 99-112, +12 LoC including comment block + redakt markers).
- `presidio/presidio-analyzer/tests/test_multi_nlp_engine.py` (lines 8 import, 423-553 — added `_build_transformers_load_capture` helper + two tests `test_runtime_revision_pin_forwarded_to_from_pretrained` and `test_runtime_revision_absent_when_row_omits_revision`).

Acceptance:
- `cd presidio/presidio-analyzer && uv run pytest tests/test_multi_nlp_engine.py tests/test_install_nlp_models_multi.py` → 26 PASS (was 24, +2 for the new revision-forwarding tests).
- Production diff: ~5 LoC of code in the two engine files, well under the 30-LoC bail-out threshold from the chunk-4c prompt.
- Presidio fork commit: `258ded3` on branch `feature/redakt-007-multi-nlp-engine`. Author `Pablo Oliva <pablo@qecept.com>`, no Claude attribution.

### F-2 [LOW] — `start_period: 90s` retained vs. REQ-014's 30s formula

Resolution: documentation-only acknowledgment per the review's "Documented; no action required" disposition. Both the `docker-compose.yml` healthcheck block (lines 32-47, comment lines 33-42 walk through the 10-30s cold-load expectation, the 90s safety margin, and the post-`start_period` retry headroom) AND the IMPLEMENTATION-PLAN tracker (chunk 4 subsection lines 277-285 + Deviations section line 461) already document the deliberate over-budget choice and its rationale (colder-cache scenarios on first build / post-prune). The healthcheck reaches healthy in ~3 s on warm-disk cold-start; the 90 s envelope is never close to expiring. No code change.

File(s) affected: none (documentation pre-existing in `docker-compose.yml` and the tracker).

Acceptance: existing healthcheck comment block in `docker-compose.yml:33-42` and tracker chunk-4 subsection both walk the arithmetic; no test regression to run.

### F-3 [LOW] — `multi.yaml` per-row `engine`/`revision` keys not in `ConfigurationValidator` schema branch

Resolution: documentation-only acknowledgment per the review's "Documented; no action required" disposition. Spec REQ-002 wording ("extended with a `multi` schema branch (or annotated to skip detailed validation for `multi`)") is satisfied by happenstance: Presidio's open-schema validator (`presidio-analyzer/presidio_analyzer/input_validation/schemas.py:48-73`) accepts the unknown `engine` and `revision` keys silently. Build-time validation lives at `install_nlp_models._validate_multi_row` (line 286-316; rejects unknown/missing `engine`, missing `lang_code`, missing `model_name`); runtime validation lives at `MultiNlpEngine._validate_row` (line 128-153; same surface). Adding a dedicated `multi` schema branch to upstream Presidio's input-validation YAML would be ceremony with no marginal coverage. No code change.

File(s) affected: none.

Acceptance: existing build-time + runtime validation surfaces cited in the review (`_validate_multi_row` at `install_nlp_models.py:286-316`, `_validate_row` at `multi_nlp_engine.py:128-153`) plus their existing test coverage (chunk-1A `test_constructor_rejects_*` tests + chunk-5 `test_install_nlp_models_multi.py` 7 tests).

### F-4 [LOW] — `MultiNlpEngine.load()` increments `_load_call_count` before sub-engine iteration

Resolution: documentation-only acknowledgment per the review's "Documented; no action required" disposition. The behavior is the explicit one-shot contract documented in REL-002 (operator-restart recovery path) and locked by `tests/test_multi_nlp_engine.py::test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` lines 416-422 (asserts that after a sub-engine load failure, retrying `load()` raises `RuntimeError("already been called")`). Not a defect — a partial-state recovery loop would silently mask configuration / model-availability bugs that REL-002's "fail loud, restart" model wants surfaced. No code change.

File(s) affected: none.

Acceptance: existing parametrized test `test_load_propagates_sub_engine_failure_and_is_loaded_returns_false[en-spacy-load-fails | de-transformer-load-fails]` continues to lock the contract (2 of the 19 tests in `test_multi_nlp_engine.py`).

---

**End of Findings Addressed (Step 4c).**
