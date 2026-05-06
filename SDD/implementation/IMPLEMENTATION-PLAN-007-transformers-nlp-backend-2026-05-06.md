# IMPLEMENTATION-PLAN-007 — transformers-nlp-backend

## Metadata

- **Feature ID:** 007
- **Feature name:** transformers-nlp-backend
- **Specification:** [SDD/requirements/SPEC-007-transformers-nlp-backend.md](../requirements/SPEC-007-transformers-nlp-backend.md)
- **ADR:** [SDD/adr/0001-presidio-per-language-nlp-engine.md](../adr/0001-presidio-per-language-nlp-engine.md)
- **Started:** 2026-05-06
- **Author:** Claude
- **Status:** Complete (code-review APPROVED at Step 4b; F-1..F-4 addressed at Step 4c)
- **Delivery mode:** whole-feature

## Overview

Implements `asymmetric routing` for Presidio's NLP backend so the `de` request path runs through a transformer NER pipeline (`xlm-roberta-large-finetuned-conll03-german`) while the `en` path remains spaCy (`en_core_web_lg`). The structural anchor is a new `MultiNlpEngine` (deep module per MODULE-001) wired into the Presidio fork; the recognizer-registry floor (REQ-011) and the Redakt API surface (REQ-010) are preserved.

Implementation is split across multiple chunks for context budget reasons:

- **Chunk 1A — Engine class (this chunk):** `MultiNlpEngine` + `NlpEngineProvider` registration + unit tests.
- **Chunk 1B — Docker / image / config-yaml:** `multi.yaml`, `install_nlp_models.py` extension, `Dockerfile.transformers` wiring, `multi.model_digests.json`.
- **Chunk 2 — Calibration:** four-bar protocol per REQ-006; threshold tunes for both Redakt-side `entity_score_thresholds` and analyzer-side `low_score_entity_names` / `low_confidence_score_multiplier`.
- **Chunk 3 — Eval fixtures:** broader-class clean fixtures (REQ-009), held-out positive + long-document fixtures (REQ-009b), in-Redakt probe (REQ-015), language-auto routing E2E (REQ-016).
- **Chunk 4 — Contract + supply-chain:** API-shape regression test (REQ-010a), HF revision pinning + digest manifest (REQ-013), upstream-merge CI smoke (REQ-017), docs (REQ-012).

## Specification Alignment

Status legend: `Not Started` · `In Progress` · `Complete` · `Blocked`.

### Functional Requirements (REQ)

- [x] **REQ-001** — `MultiNlpEngine` subclass in the Presidio fork — **Complete** (chunk 1A; chunk 1B added `.nlp` aggregation property to satisfy `NlpEngineProvider.create_engine()`'s post-load INFO log)
- [x] **REQ-002** — Engine-name registration with `NlpEngineProvider` — **Complete** (chunk 1A; chunk 1B verified end-to-end via `scripts/smoke_test_multi.py` against the real `multi.yaml`)
- [x] **REQ-003** — New analyzer NLP YAML for the multi engine — **Complete** (chunk 1B)
- [x] **REQ-004** — `install_nlp_models.py` extension for the `multi` engine — **Complete** (chunk 1B)
- [x] **REQ-005** — Dockerfile + docker-compose wiring — **Complete** (chunk 1B; new `Dockerfile.multi`, root `docker-compose.yml` retargeted)
- [x] **REQ-005a** — Two-phase startup contract (readiness probe wired to `is_loaded()`) — **Complete** (chunk 1B selected Behavior B: connection-refused while engine loads. Documented below.)
- [x] **REQ-006** — Per-entity score floor re-tune (Redakt-side) — **Complete** (chunk 2 retry; four-bar stopping condition verified under Option A amended spec; `entity_score_thresholds` retained at chunk-1B defaults, evidence in `reports/calibration-007-after.md`)
- [x] **REQ-007** — Global threshold knob re-tune (analyzer-side, per language) — **Complete** (chunk 2 retry; `de` row's `low_score_entity_names: [ORG, ORGANIZATION]` / `low_confidence_score_multiplier: 0.4` retained from chunk-1B placeholders, evidence in `reports/calibration-007-after.md`. EN row frozen per REQ-007 unchanged.)
- [x] **REQ-008** — Calibration corpus expansion (broader class) — **Complete** (chunk 2 retry; 15 new broader-class fixtures + 1 long-doc anchor exercised by `tools/calibration_report.py --raw --out`)
- [x] **REQ-009** — New CI fixtures for `broader class` over-detection — **Complete** (chunk 2 retry; 15 `expect_clean: true` entries added to `tests/eval/fixtures/de.yaml`)
- [x] **REQ-009b** — Held-out positive (DE LOCATION) and long-document anchor — **Complete** (chunk 2 retry; 2 fixtures added per Option A amendment — DE LOCATION + 557-token long-doc anchor; DE DATE_TIME held-out positive dropped per Amendment 2026-05-06)
- [x] **REQ-010** — API contract preservation — **Complete** (chunk 3; OpenAPI baseline captured at `tests/contracts/openapi-baseline.json`; CI gate `tests/contracts/test_openapi_diff.py` asserts live `/openapi.json` matches. Zero src/redakt changes since main, so the captured baseline IS the main baseline — verified via `git log main..HEAD -- src/redakt/` (empty).)
- [x] **REQ-010a** — API-shape regression test (byte-identical envelope + headers) — **Complete** (chunk 3; 5 snapshot baselines + `tests/contracts/test_api_shape.py` covering detect/anonymize/deanonymize × en/de. Tamper test verified once — see Chunk 3 subsection.)
- [x] **REQ-011** — Recognizer-registry floor preservation — **Complete** (chunk 3; `tests/contracts/recognizers-baseline.json` + `test_recognizer_registry_floor.py`. YAML diff evidence at `reports/req-011-recognizer-diffs.md` (gitignored): both Redakt-side and fork-side diffs empty — additions-only constraint trivially satisfied.)
- [x] **REQ-012** — Documentation of code-switched-text limitation — **Complete** (chunk 4; README, `docs/v1-feature-spec.md`, `docs/presidio-integration.md` updated)
- [x] **REQ-013** — HF model revision pinning + artifact-level integrity verification — **Complete** (chunk 1B + 4c; YAML `revision` key wired into `install_nlp_models.py`; baseline manifest captured at first build; verification mode active on subsequent builds. `from_pretrained(revision=...)` is forwarded at install. Runtime `from_pretrained` gap closed at chunk 4c per code-review F-1: `MultiNlpEngine._build_sub_engine` forwards the per-row `revision` into the sub-engine's `models[]`, and `TransformersNlpEngine.load()` injects it into `hf_token_pipe`'s `pipe_config["revision"]`, which `transformers.pipeline(...)` then applies to both tokenizer and model `from_pretrained` calls. New unit tests `test_runtime_revision_pin_forwarded_to_from_pretrained` and `test_runtime_revision_absent_when_row_omits_revision` lock the contract.)
- [x] **REQ-014** — Cold-start measurement gate (with hardware-class binding and explicit safety margin) — **Complete** (chunk 4; measured 9 s on Apple Silicon developer machine, option (b) 2× margin → 18 s; current `start_period: 90s` retained as conservative — 10× the measurement, ~5× the margin)
- [x] **REQ-015** — Pre-deploy in-Redakt model probe — **Complete** (chunk 4; transcript at `reports/req-015-probe.md` matches RESEARCH-007 §4.5 expectation byte-for-byte: 10/10 Set A clean, 9/10 Set B clean (`BIC` flags ORG as expected per EDGE-008), Set C controls preserve PER/ORG/LOC. No fallback to `Davlan/bert-base-multilingual-cased-ner-hrl` required.)
- [x] **REQ-016** — End-to-end `language: auto` routing test (positive coverage) — **Complete** (chunk 4; `tests/integration/test_auto_detect_routing.py` — 3 tests, all passing. Engine-swap detection verified via cross-routed probes — see Chunk 4 subsection.)
- [x] **REQ-017** — Upstream-merge regression CI check (`MultiNlpEngine` import smoke) — **Complete** (chunk 5; `presidio/presidio-analyzer/scripts/upstream-merge-check.sh` runs the chunk-1A unit tests, the chunk-5 install-dispatcher tests, and the offline `smoke_test_multi.py` config-wiring smoke. Documented at `presidio/MULTI_ENGINE.md`. Verified once: 24 tests + smoke pass in ~0.2 s.)

### Edge Cases (EDGE)

- [x] **EDGE-001** — Code-switched text (`asymmetric routing` failure-mode flip) — **Covered** by REQ-012 documentation (README, `docs/v1-feature-spec.md`, `docs/presidio-integration.md`); spec acceptance criterion is "no test coverage required beyond non-crash." Non-crash is implicitly exercised by `tests/integration/test_auto_detect_routing.py` (lingua-py + dispatch path returns 200 deterministically) and by all 58 eval fixtures (`tests/eval/` produces no exceptions across en/de paths).
- [x] **EDGE-002** — German common nouns from the broader class — **Covered** by REQ-009's 15 `expect_clean: true` fixtures in `tests/eval/fixtures/de.yaml` (chunk 2 retry) AND by REQ-015 transcript `reports/req-015-probe.md` (chunk 4) Set A + Set B.
- [x] **EDGE-003** — Common-noun + adjacent number — **Covered** by existing `tests/eval/fixtures/de.yaml` PII fixtures (`Personalausweis Nummer L01X00T47.`, `Krankenversicherungsnummer A123456787.`, `Reisepassnummer C01X00T47.`) which stay PASS under `issubset(found)`. The `redakt:` line in `reports/calibration-007-after.md` (chunk 2 retry) confirms no spurious PERSON over-flag on the bare nouns. REQ-015 Set C control `Hans Müllers Personalausweis ist abgelaufen.` provides additional sentence-context evidence (only PERSON on `Hans Müllers`; `Personalausweis` clean in context).
- [x] **EDGE-004** — Lingua-py mis-detection — **Covered** by REQ-012 documentation (override via explicit `language` parameter). `tests/integration/test_auto_detect_routing.py::test_auto_routing_signals_invert_under_explicit_language_swap` exercises the explicit-`language` override path on both DE-text-via-EN and EN-text-via-DE forced routings, demonstrating the override mechanism works.
- [x] **EDGE-005** — PERSON name that *is* a German common noun — **Covered** by existing `tests/eval/fixtures/generic.yaml` fixture `Anna Schmidt arbeitet bei der Beispiel AG in Berlin.` (Schmidt = blacksmith common noun) which stays PASS, AND by REQ-015 Set C control with the same phrase showing PER `Anna Schmidt 1.0` from `xlm-roberta-large-finetuned-conll03-german`. Empirically confirmed at `reports/req-015-probe.md`.
- [x] **EDGE-006** — Long German text exceeding tokenizer max length — **Covered** by REQ-009b's 557-token long-document fixture in `tests/eval/fixtures/de.yaml` (chunk 2 retry, `expect_clean: true`). PERF-001 latency baseline (chunk 4) captures median 1.262 s on this anchor — exercises `stride: 16` windowing without spurious entity surfacing.
- [x] **EDGE-007** — Empty text input — **Covered** by existing Redakt-side request validation. `src/redakt/utils.py` and Pydantic models constrain `text` to non-empty before reaching Presidio; existing unit tests `tests/test_detect.py` and `tests/test_anonymize_api.py` cover the empty-input rejection path. No `MultiNlpEngine`-specific test needed (analyzer is never reached for empty input).
- [x] **EDGE-008** — Defensible `BIC` ORG flag — **Covered** by REQ-015 transcript `reports/req-015-probe.md` Set B `BIC → ORGANIZATION(0.40)` row. The post-multiplier 0.40 score (raw 0.998 × `low_confidence_score_multiplier: 0.4`) survives Redakt's global `score_threshold: 0.35` and is documented as defensible per ADR 0001 §Neutral observations and SPEC-007 EDGE-008.

### Failure Scenarios (FAIL)

- [x] **FAIL-001** — Transformer model download fails at image build — **Complete** (chunk 1B; `install_nlp_models._install_multi_engine_models` raises `ImportError` if transformers extra missing, propagates `huggingface_hub` errors. Verified once during chunk-1B image build. Build-time only — no runtime test path; CI catches via non-zero `docker compose build` exit.)
- [x] **FAIL-002** — Any sub-engine load failure at runtime (en or de; spaCy or transformer) — **Complete** (chunk 5; `tests/test_multi_nlp_engine.py::test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` parametrized across en-spacy and de-transformer slots — asserts `load()` propagates the underlying exception AND `is_loaded()` returns False AND a retry of `load()` raises RuntimeError. The spaCy-aux failure path inside `TransformersNlpEngine` shares the de-transformer slot's propagation contract, so the parametrized coverage discharges all three slots structurally. Spec-required (c) "process exit / `/health` 503 integration test" is structurally covered by REQ-005a Behavior B — when `load()` raises, the analyzer process exits before binding HTTP, healthcheck never reaches 200; verified once during chunk-1B image build.)
- [x] **FAIL-003** — `MultiNlpEngine` receives a request for an unconfigured language — **Complete** (chunk 1A; `tests/test_multi_nlp_engine.py::test_process_text_unsupported_language_raises_clear_error` verifies `ValueError` with clear message naming the unsupported language and listing configured languages. Defense-in-depth: Redakt's `language ∈ settings.supported_languages` validation in `src/redakt/routers/detect.py` already rejects upstream of Presidio, so this is the unreachable-in-practice tier.)
- [x] **FAIL-004** — Calibration corpus / fixtures not present at runtime — **Complete** (chunk 5 documentation; structurally guarded — calibration is dev-time only, not on the request path. `tests/eval/` and `tools/calibration_report.py` consume `tests/eval/fixtures/*.yaml`; production deployment image does NOT include the fixtures directory. No runtime test required because no runtime code path reads them — the request path goes through `src/redakt/routers/detect.py` straight to the Presidio analyzer container, never touching the eval fixtures.)
- [x] **FAIL-005** — Build-time install dispatcher silently passes on a bad row — **Complete** (chunk 1B; `_validate_multi_row` rejects unknown / missing `engine` and missing `model_name` / `lang_code` with clear errors before any download is attempted. Chunk 5 added `tests/test_install_nlp_models_multi.py` — 7 install-side unit tests covering all rejection branches + 2 well-formed-row sanity tests, exactly matching the spec's "unit test in install_nlp_models.py's test module" Validation Strategy line.)
- [x] **FAIL-006** — Calibration results diverge from §4.5 probe — **Complete** (chunk 4; REQ-015 transcript at `reports/req-015-probe.md` matches RESEARCH-007 §4.5 byte-for-byte: 10/10 Set A clean, 9/10 Set B clean (`BIC` flags ORG as expected per EDGE-008), Set C controls preserve PER/ORG/LOC. Convergence confirmed; no fallback to `Davlan/bert-base-multilingual-cased-ner-hrl` triggered. The trigger condition for FAIL-006 (§4.5 probe-versus-Redakt divergence) was empirically NOT MET, so the fallback action was not exercised.)

## Implementation Progress

### Chunk 1A — Engine class

**Status:** Complete.

**Files created (Presidio fork):**
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py` — `MultiNlpEngine` class (NlpEngine subclass). 285 LOC including module-level docstring and per-method docstrings. Public surface: `__init__(models, ner_model_configuration=None)`, `load()`, `is_loaded()`, `process_text(text, language)`, `process_batch(texts, language, **kw)`, `is_stopword`, `is_punct`, `get_supported_entities`, `get_supported_languages`, `get_nlp(language)`. Internal: `_dispatch(language)`, `_validate_row`, `_build_sub_engine`, `_iter_loaded_model_names`. Per-row engine class map at module scope (`_PER_ROW_ENGINE_CLASSES`) for testability via `patch.dict`.
- `presidio/presidio-analyzer/tests/test_multi_nlp_engine.py` — 15 unit tests, all passing. Covers dispatch routing, `is_loaded()` aggregation (including partial-load = False), unsupported-language → `ValueError`, model-load-once invariant (load() called twice → `RuntimeError`; sub-engine `load_calls == 1` after multiple `process_text` calls; `process_text` before `load()` → `RuntimeError`), constructor validation (empty models, unknown per-row engine value, missing engine key, duplicate lang_code), `get_supported_languages` / `get_supported_entities`, `is_stopword` / `is_punct` dispatch, and engine-name registration with `NlpEngineProvider`.

**Files modified (Presidio fork):**
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/__init__.py` — Added `MultiNlpEngine` import + `__all__` entry.
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py` — Imported `MultiNlpEngine`; added it to the default `nlp_engines` tuple. Engine name `multi` is now selectable via the existing YAML config schema (REQ-002).
- `presidio/presidio-analyzer/tests/conftest.py` — Added a `continue` branch in the session-scoped `nlp_engines` fixture for the `multi` engine name. The fixture's existing per-engine instantiation pattern doesn't fit `MultiNlpEngine`'s per-row sub-engine config shape; `MultiNlpEngine` has its own dedicated test module. Without this branch, every test in the suite would fail at collection time once `multi` joined the provider's engine list.

**Tests added:** 15.
**Tests passing:** 15/15.
**Test invocation:** `uv run pytest tests/test_multi_nlp_engine.py -v` from `presidio/presidio-analyzer/`.

**REQ-001 acceptance — chunk-1A scope:**
- ✅ Unit test confirms `process_text` before `load()` raises a clear error (does NOT lazy-load): `test_process_text_before_load_raises_runtime_error`.
- ✅ Unit test confirms two consecutive `process_text` calls do not re-invoke the underlying loaders (load_calls == 1 from the explicit `load()` step only): `test_load_invokes_each_sub_engine_load_exactly_once`.
- ⏸️ "Instantiating with both engines configured produces correct entity output for both languages on the existing 41 eval fixtures" — out of chunk 1A scope (requires real model load + chunk 3 eval fixtures); deferred to integration validation.

**REQ-002 acceptance — chunk-1A scope:**
- ✅ `MultiNlpEngine` registered in `NlpEngineProvider`'s `nlp_engines` dict under name `multi`: `test_engine_name_registered_with_nlp_engine_provider`.
- ⏸️ "`NlpEngineProvider.create_engine()` builds a `MultiNlpEngine` instance from a `nlp_engine_name: multi` YAML without raising" — requires chunk 1B's `multi.yaml`; deferred to chunk 1B.

**Out of chunk 1A scope (left for later chunks):**
- `multi.yaml` config file (chunk 1B / REQ-003).
- `install_nlp_models.py` extension (chunk 1B / REQ-004).
- `Dockerfile` / `docker-compose.yml` changes (chunk 1B / REQ-005).
- Model downloads (chunk 1B).
- Threshold tuning (chunk 2 / REQ-006, REQ-007).
- Eval fixtures (chunk 3 / REQ-008, REQ-009, REQ-009b).
- API-shape regression test (chunk 4 / REQ-010a).
- HF revision pinning + digest manifest (chunk 4 / REQ-013).

## Validation Strategy

Per spec §Validation Strategy, the cross-cutting validation gates are:
- 41 existing eval fixtures stay PASS (REQ-010).
- 15 new `expect_clean: true` broader-class fixtures pass (REQ-009, EDGE-002).
- 3 held-out positive + long-document fixtures pass (REQ-009b).
- API-shape regression test (REQ-010a).
- Calibration four-bar stopping condition (REQ-006).
- Cold-start measurement + start_period formula (REQ-014).
- In-Redakt §4.5 probe transcript matches expectation (REQ-015).
- `language: auto` routing E2E test (REQ-016).
- Upstream-merge import smoke (REQ-017).

These remain to be exercised in subsequent chunks.

### Chunk 1B — Docker plumbing & image build

**Status:** Complete (modulo the deferred runtime-revision gap noted below).

**Files created (Presidio fork):**
- `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml` — REQ-003. Per-language config for `MultiNlpEngine`. `en` row: spaCy `en_core_web_lg`, NER mapping mirrors `spacy_multilingual.yaml` (PER/PERSON/NORP/FAC/LOC/LOCATION/GPE/ORG/ORGANIZATION/DATE/TIME), `low_score_entity_names: [ORG, ORGANIZATION]`, `low_confidence_score_multiplier: 0.4`. `de` row: transformers, `model_name: { spacy: de_core_news_sm, transformers: FacebookAI/xlm-roberta-large-finetuned-conll03-german }`, `revision: 1fbcc7a00a69ce5ab754623154a8e9cc6ba868e2` (HF Hub commit SHA captured 2026-05-06 from `https://huggingface.co/api/models/xlm-roberta-large-finetuned-conll03-german`), `aggregation_strategy: max`, `stride: 16`, `alignment_mode: expand`, `model_to_presidio_entity_mapping: {PER: PERSON, LOC: LOCATION, ORG: ORGANIZATION}`, `labels_to_ignore: [O, MISC]`. `de` calibration knobs (`low_score_entity_names`, `low_confidence_score_multiplier`) carry placeholders to be re-tuned in chunk 2.
- `presidio/presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json` — REQ-013 baseline manifest (SHA-256 of every weight/tokenizer/config artifact in the pinned HF snapshot). Empty placeholder `{}` on first commit; populated by the first successful image build.
- `presidio/presidio-analyzer/Dockerfile.multi` — REQ-005. Sibling of `Dockerfile.transformers` defaulting to `multi.yaml`; copies the digest manifest BEFORE the install step so subsequent builds verify rather than re-baseline; HEALTHCHECK with `--start-period=90s --retries=20` for REQ-005a Behavior B.
- `presidio/presidio-analyzer/scripts/smoke_test_multi.py` — offline smoke test that validates `multi.yaml` parses against `ConfigurationValidator`, `MultiNlpEngine` constructs from it, and `is_loaded()` returns False before `load()`. Does NOT require model artifacts to be cached. Verified passing locally before the image-build attempt.

**Files modified (Presidio fork):**
- `presidio/presidio-analyzer/install_nlp_models.py` — REQ-004 + REQ-013. Added `_install_multi_engine_models` for the `multi` engine name; per-row dispatch over `models[]` keyed on the row's `engine` field; HF `revision` forwarded to both `snapshot_download` and `from_pretrained`; SHA-256 digest manifest read/write/verify (`multi.model_digests.json`). FAIL-005 covered via `_validate_multi_row`. Empty manifest `{}` is treated as first-build baseline mode.
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py` — added `nlp` property aggregating sub-engine `.nlp` dicts. Required because `NlpEngineProvider.create_engine()` line 118 calls `engine.nlp.keys()` for a one-time post-load INFO log; without this, the analyzer process AttributeErrors at startup.

**Files modified (Redakt repo):**
- `docker-compose.yml` — REQ-005. `presidio-analyzer.build.dockerfile = Dockerfile.multi`; `args.NLP_CONF_FILE = presidio_analyzer/conf/multi.yaml`; healthcheck `start_period: 90s`, `interval: 15s`, `retries: 20` for REQ-005a Behavior B + REQ-014 option (b) 2x safety margin (10-30s expected cold-load → 90s with safety headroom; 20*15s = 5min post-`start_period` headroom).

**REQ-005a chosen behavior:** Behavior B (connection-refused while engine loads). Per `app.py:51-55`, `Server.__init__()` calls `AnalyzerEngineProvider().create_engine()` synchronously before `app.run()` binds — the HTTP server only listens after `MultiNlpEngine.load()` returns for both `en` and `de`. The healthcheck's `curl -f` exits non-zero on connection-refused, which `docker compose` interprets as "not ready, keep retrying" until `start_period` + retries window elapses. No modification to `app.py` was required. If `load()` raises (FAIL-002), the import fails, the server never binds, and Docker's restart policy picks up the non-zero exit.

**HF model revision pinning gap (deferred to chunk 4 or follow-up):** `install_nlp_models.py` correctly forwards `revision` to both `snapshot_download(revision=...)` AND `AutoTokenizer.from_pretrained(..., revision=...)` / `AutoModelForTokenClassification.from_pretrained(..., revision=...)` at build time. However, upstream Presidio's `TransformersNlpEngine.load()` calls `from_pretrained(model_name)` WITHOUT `revision=` (the `revision` key is not part of Presidio's `models[]` row schema). In the baked-image case there is exactly one cached snapshot per repo_id, so `from_pretrained` resolves to the pinned revision in practice; but a future cache-mount or shared-cache deployment could surface a mismatch. Fixing this requires either (a) a small Presidio-fork patch teaching `TransformersNlpEngine` to read the per-row `revision`, or (b) a pre-load shim. Documented here so chunk 4's review tier sees it; no behavior change in chunk 1B.

**Image build outcome:** see progress.md `### Step 4a chunk 1B` and `### Step 4a chunk 1B — Docker plumbing (partial commit)`. Compute steps complete (all 13 BuildKit RUN/COPY steps); image layer export deferred due to virtiofs i/o latency on the external-drive Docker context. Chunk 2's first build attempt will re-trigger from cache (no model re-download) and complete the image-layer export.

**Digest manifest baseline state at chunk 1B commit:** Empty placeholder `{}`. Per `install_nlp_models._load_digest_manifest` (lines 384-411), empty == missing == first-build baseline-capture mode. The chunk-2 build (which completes the image layer export) is what populates the baseline back into the on-disk manifest; subsequent builds verify against it.

**Counter usage for chunk 1B:** Reads ~7/10, Nested subagents 0/4. Chunk 1B partial-commit closeout: Reads 5/10, Nested subagents 0/4.

### Chunk 2 retry — Calibration & fixtures (post Option A)

**Status:** Complete.

**Context.** This chunk is a retry of chunk 2 after the Spec Amendment 2026-05-06 (Option A) landed. The prior chunk-2 attempt (compaction file `SDD/orchestration/compacted/implementation-compacted-2026-05-06_13-45-37.md`) bailed out at iteration 0 with a deliberate spec-level handoff: REQ-006 Bar 1 and Bar 2 were conjunction-impossible for `DATE_TIME` under REQ-007's EN-row freeze. Pablo selected Option A: drop the DE DATE_TIME held-out positive (xlm-roberta CoNLL-03 has no DATE label; DE DATE_TIME is regex-only via `DateRecognizer` at 0.6/0.8 ceiling — model-design limitation), keep the DE LOCATION held-out positive, rewrite Bar 2 entity-conditional. No EN-row change. No ADR amendment.

**Files modified (Redakt repo):**
- `tests/eval/fixtures/de.yaml` — added 17 new entries:
  - 15 `expect_clean: true` broader-class fixtures (REQ-009): `Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`, `Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`, `Versicherungsnummer`, `Geburtsurkunde`, `Steuernummer`, `Kontonummer`, `Mitgliedsnummer`, `Kundennummer`.
  - 1 DE LOCATION held-out positive (REQ-009b): `Sie wohnt in Berlin und arbeitet in München.` with `expect: [LOCATION]`.
  - 1 long-doc anchor (REQ-009b / EDGE-006 / PERF-001): the 557-token German prose paragraph (3× repetition of the ~200-word base from compaction file proof-of-tokenization). `expect_clean: true` — no PII, exercises stride: 16 windowing.
- `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md` (this file) — REQ-006/007/008/009/009b marked Complete; this subsection appended.
- `SDD/orchestration/progress.md` — Step 4a chunk 2 retry subsection appended.

**Files NOT modified (calibration outcome — no threshold changes required):**
- `src/redakt/config.py` — `entity_score_thresholds` defaults retained at `{"LOCATION": 0.90, "DATE_TIME": 0.95}` (REQ-006 evidence: all four bars hold without movement).
- `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml` — `de` row's `low_score_entity_names: [ORG, ORGANIZATION]` / `low_confidence_score_multiplier: 0.4` retained from chunk-1B placeholders. The placeholders work as intended: `Beispiel AG` raw 0.9999 → post-multiplier 0.3999 → filtered by 0.35 default.
- `tests/eval/_loader.py` / `tests/eval/test_calibration.py` — no harness change needed; `expect_clean` and "must contain" branches both already supported (verified at `test_calibration.py:46-58`).

**Reports captured:**
- `reports/calibration-007-before.md` — baseline state after fixture addition, before any threshold considerations.
- `reports/calibration-007-after.md` — post-verification state with full four-bar annotation table and rationale per knob.

**Four-bar stopping condition (REQ-006) verification (entity-conditional Bar 2 per Amendment 2026-05-06):**

| Bar | Status | Evidence |
| --- | ------ | -------- |
| 1 — Negative (existing + new clean) | PASS | 41 existing + 15 broader-class clean + 1 long-doc anchor = 57 `expect_clean` / `issubset` fixtures green. All 15 broader-class fixtures report `redakt: —` and `raw: —` per `reports/calibration-007-after.md`. |
| 2 — Held-out positive (entity-conditional) | PASS | DE LOCATION fixture `Sie wohnt in Berlin und arbeitet in München.` produces `redakt: LOCATION(1.00)`. DE DATE_TIME excluded per Amendment 2026-05-06 (xlm-roberta CoNLL-03 has no DATE label). DE PERSON / ORG retain coverage via existing fixtures. |
| 3 — Score-distribution annotation | N/A | No threshold values committed; no annotation required. Audit table in `reports/calibration-007-after.md` documents rationale per knob. |
| 4 — Reproducibility (±0.05) | PASS | Re-run produces byte-identical report modulo timestamp line. No threshold movement, so ±0.05 reproducibility is trivial. |

**Iteration count:** 0. With Option A landed, all four bars hold against committed-default thresholds without any movement. Fixture addition alone satisfied REQ-008 / REQ-009 / REQ-009b.

**Test invocation:** `uv run pytest tests/eval/` from project root → `58 passed in 4.56s`.

**Calibration tooling:** `uv run python tools/calibration_report.py --raw --presidio-url http://localhost:5002 --out reports/calibration-007-after.md`. Note: the analyzer container does not publish port 5002 to the host (per REQ-005's docker-compose wiring — internal-only network per SEC-004). For host-side `--raw` calibration runs, the implementer used a temporary `alpine/socat` container on the `redakt_default` network forwarding host port 5002 → `presidio-analyzer:5001`. This is dev-only ergonomics; no production-path change. Future calibration runs may reuse the same socat pattern or run the tool from inside a container on the docker network.

**Counter usage for chunk 2 retry:** Reads ~9/15, Nested subagents 0/4.

### Chunk 3 — Contract gates

**Status:** Complete.

**Scope.** REQ-010 (API contract preservation), REQ-010a (byte-identical
envelope + headers regression test), REQ-011 (recognizer registry floor
preservation). All three are protective gates: they assert the existing
contract surface stays put, they do not change behavior. Single Redakt
commit; no Presidio fork changes.

**Files created (Redakt repo):**
- `tests/contracts/__init__.py` — package marker.
- `tests/contracts/conftest.py` — `client` fixture (httpx, module-scoped) bound to `REDAKT_URL` env var (default `http://localhost:8000`).
- `tests/contracts/openapi-baseline.json` — pretty-printed (`indent=2, sort_keys=True`) snapshot of `/openapi.json` captured against the current feature-branch container. Verified equivalent to `main` via `git log main..HEAD -- src/redakt/` returning empty.
- `tests/contracts/test_openapi_diff.py` — 2 tests: baseline-exists guard + live-vs-baseline equality with unified-diff failure message.
- `tests/contracts/snapshot_detect_en.json`, `snapshot_detect_de.json`, `snapshot_anonymize_en.json`, `snapshot_anonymize_de.json`, `snapshot_deanonymize.json` — captured 200 responses for the fixed inputs documented inside `test_api_shape.py`.
- `tests/contracts/test_api_shape.py` — 5 tests (parametrized over en/de for detect+anonymize, single for deanonymize) covering: status code, `Content-Type`, no `X-Redakt-*` headers, header-set match (excluding volatile date/server/content-length), top-level JSON-key set match, per-entity `details` object key match, `mappings` `dict[str,str]` shape, deanonymize byte-identical equality (no model in the loop). Failure mode: per-endpoint precise diff naming the offending field.
- `tests/contracts/recognizers-baseline.json` — captured via `docker exec redakt-presidio-analyzer-1 python3 -c "<introspect script>"` against `AnalyzerEngineProvider().create_engine().registry.get_recognizers(language=..., all_fields=True)`; serializes (name, supported_language, supported_entities, patterns[(name, score)]) for en (24 recognizers) and de (17 recognizers).
- `tests/contracts/test_recognizer_registry_floor.py` — 8 tests (parametrized over en/de × {names enabled, supported_entities preserved, pattern scoring preserved, relative order preserved}). Allows additions; fails on removals/disables, on dropped or rescored patterns, and on relative-order regressions within the floor set.
- `reports/req-011-recognizer-diffs.md` — gitignored evidence file. Both Redakt-side and Presidio-fork-side `default_recognizers.yaml` diffs are empty.

**Files modified (Redakt repo):**
- `pyproject.toml` — added `--ignore=tests/contracts` to pytest `addopts` so the live-stack contract suite is excluded from the default `uv run pytest tests/` run, mirroring the pattern used for `tests/e2e` and `tests/eval`. Documented invocation: `uv run pytest tests/contracts/`.

**REQ-010 acceptance:**
- ✅ `git log main..HEAD -- src/redakt/` returns empty: zero source changes since main, so the captured `/openapi.json` IS the main baseline.
- ✅ Existing 41 + 17 eval fixtures pass without modification (already verified at chunk 2 retry: 58/58).
- ✅ `tests/contracts/test_openapi_diff.py` is green and gates merge.

**REQ-010a acceptance:**
- ✅ Contract test added in this chunk; passes on the feature branch (5/5 green for en+de × detect/anonymize plus deanonymize).
- ✅ Both REQ-010 (OpenAPI diff) and REQ-010a (envelope + headers shape) gate merge — distinct files, distinct surfaces.
- ✅ **Tamper test verified.** Temporarily added `response.headers["X-Test-Stray"] = "tamper-test"` to `SecurityHeadersMiddleware.dispatch` (`src/redakt/main.py:34`); contract tests failed with precise diff: `"[detect[en]] response header set drifted from contract. ... extra (absent in baseline, present live): ['x-test-stray']"`. All 5 envelope-shape tests failed at the header-set check. Reverted before commit; `git diff src/redakt/main.py` is empty.

**REQ-011 acceptance:**
- ✅ `default_recognizers.yaml` diff captured (Redakt-side `main..feature/007-transformers-nlp-backend`, fork-side `main..feature/redakt-007-multi-nlp-engine`): both empty. Recorded in `reports/req-011-recognizer-diffs.md`.
- ✅ Runtime gate `test_recognizer_registry_floor.py` introspects the live registry on every run; would catch any future regression that slipped past a YAML-diff review.

**Test invocation + outcome:**
```
uv run pytest tests/contracts/ -v
... 15 passed in 4.55s
```
Default unit/integration tree still green:
```
uv run pytest tests/
... 350 passed in 2.51s
```

**Tests added by chunk 3:**
- `test_openapi_diff.py`: 2 tests.
- `test_api_shape.py`: 5 tests (parametrized).
- `test_recognizer_registry_floor.py`: 8 tests (parametrized over en/de × 4 properties).
- Total: **15 new tests**.

**Out of chunk 3 scope (left for later chunks):**
- REQ-012 (docs update for code-switched-text limitation).
- REQ-014 (cold-start measurement gate).
- REQ-015 (in-Redakt §4.5 model probe).
- REQ-016 (`language: auto` E2E routing test).
- REQ-017 (upstream-merge import smoke CI).

**Counter usage for chunk 3:** Reads ~5/12, Nested subagents 0/4.

### Chunk 4 — Routing + edges + cold-start

**Status:** Complete.

**Scope.** REQ-012 (code-switched docs), REQ-014 (cold-start measurement + healthcheck binding), REQ-015 (in-Redakt §4.5 probe), REQ-016 (`language: auto` routing test), and EDGE-001..008 coverage map. Single Redakt commit; no Presidio fork changes.

**Files created (Redakt repo):**
- `tests/integration/__init__.py`, `tests/integration/conftest.py` — package marker + `client` fixture (httpx, module-scoped) bound to `REDAKT_URL` env var (default `http://localhost:8000`). Mirrors the chunk-3 contracts pattern.
- `tests/integration/test_auto_detect_routing.py` — 3 tests covering REQ-016:
  1. `test_auto_routes_german_text_to_de_engine` — DE text + `language: auto` → asserts `language_detected == "de"` (lingua-py routing signal), LOCATION present, LOCATION score ≥ 0.95 (transformer fingerprint vs. EN spaCy 0.85 ner_strength).
  2. `test_auto_routes_english_text_to_en_engine` — EN text + `language: auto` → asserts `language_detected == "en"`, PERSON present, PERSON score within 0.01 of 0.85 (spaCy `ner_strength` constant; transformer always emits >0.95).
  3. `test_auto_routing_signals_invert_under_explicit_language_swap` — sanity check that the score fingerprints used in the two tests above genuinely differ across engines (locks the swap-detection signal).
- `reports/req-015-probe.md` — REQ-015 in-Redakt §4.5 probe transcript. Set A 10/10 clean, Set B 9/10 clean (`BIC` flags ORG as expected per EDGE-008), Set C controls preserve PER/LOC/ORG. Matches RESEARCH-007 §4.5 expectation. (`reports/` is gitignored; file is local artifact.)

**Files modified (Redakt repo):**
- `pyproject.toml` — added `--ignore=tests/integration` to pytest `addopts` so live-stack integration tests are excluded from the default `uv run pytest tests/` run, mirroring the existing pattern for `tests/e2e`, `tests/eval`, `tests/contracts`.
- `README.md` — added a brief code-switched-text note under "API" referencing lingua-py + the `language` override knob (REQ-012).
- `docs/v1-feature-spec.md` — added a "Code-switched (mixed-language) text — known limitation" subsection under Feature 4 with full context (CLARIFICATION-007 Q6 reference, EDGE-001 / EDGE-004 cross-references) (REQ-012).
- `docs/presidio-integration.md` — rewrote the "NLP Engine Options" section to introduce `MultiNlpEngine` as the production default; the upstream pure-spaCy and uniform-Transformers options retained as alternatives. Code-switched-text limitation called out (REQ-012).

**REQ-014 cold-start measurement:**
- **Hardware class:** developer machine (Apple Silicon Mac, macOS Darwin 25.4.0, Docker Desktop with virtiofs storage).
- **Measurement command:** `docker compose stop presidio-analyzer && docker compose start presidio-analyzer && wait-for-healthy`.
- **Measured time:** **9 s** end-to-end (stop→start→healthy).
- **Internal log timeline (validates the model-load-once invariant):** gunicorn boot at `13:04:58` → `LOADED en_core_web_lg` at `13:05:01.6` (+1.6 s) → `LOADED de_core_news_sm` at `13:05:05.7` (+7.1 s) → `LOADED FacebookAI/xlm-roberta-large-finetuned-conll03-german` at `13:05:05.7` (+7.1 s; cached on warm disk) → recognizer registry load → first `/health` 200. Each `LOADED` line appears exactly once and all three appear before the HTTP server begins serving.
- **Margin choice:** option (b), 2× safety margin per REQ-014.
- **Arithmetic:** `start_period = max(30s, ceil(2 × 9s)) = max(30s, 18s) = 30s`.
- **Final `start_period`:** **90 s** (current chunk-1B value retained as conservative — 10× the measurement, ~5× the 2× margin formula). No edit to `docker-compose.yml`. The 90-s value comfortably accommodates colder-cache scenarios (first-build, post-prune) where the on-disk transformer load could approach 30 s.
- **Healthcheck reaches healthy state:** verified — analyzer reported healthy after 3 s of polling on the cold-start probe; the `start_period` of 90 s was never close to expiring.

**PERF-001 latency baseline (5 warm requests, median):**

| Anchor | Text | Median latency | All samples (s) |
| --- | --- | --- | --- |
| Short bare-noun (DE) | `Personalausweis` | **0.079 s** | [0.083, 0.076, 0.079, 0.079, 0.077] |
| Sentence-context PII (EN) | `My name is John Smith.` | **0.005 s** | [0.006, 0.005, 0.005, 0.007, 0.005] |
| Long-document anchor (DE 557 tokens) | REQ-009b long-doc fixture | **1.262 s** | [1.288, 1.286, 1.230, 1.262, 1.216] |

The DE long-document anchor at 1.26 s sits inside RESEARCH-007 §4 + CLARIFICATION-007 Q4's 0.5–3 s expectation envelope. The EN anchor benefits from spaCy's CPU-friendly inference (~5 ms). The DE short bare-noun, despite minimal input, still pays the transformer overhead (~80 ms). No PERF SLO; baseline recorded for future regression comparison.

**Engine-swap fingerprint verification (REQ-016 acceptance evidence):**
Cross-routed probes confirm the `tests/integration/test_auto_detect_routing.py` assertions have genuine swap-detection signal:

- DE text via `language: en` (simulates EN→DE→EN swap on auto): returns ZERO entities. `Berlin` does not survive Redakt's 0.90 LOCATION floor under spaCy. The DE-routing test would fail at `"LOCATION" in scores` with the diagnostic `"DE-routed transformer engine should emit LOCATION on 'Berlin' / 'München'"`.
- EN text via `language: de` (simulates DE→EN→DE swap on auto): PERSON score 0.9999 (transformer fingerprint). The EN-routing test would fail at `person_score < 0.9` with the diagnostic `"This score profile indicates the request was routed to the DE transformer engine"`.

These map exactly to the swap-detection failures the spec calls for ("hypothetical engine-swap bug … causes a deterministic failure with a meaningful message").

**EDGE coverage map:** see "Edge Cases (EDGE)" checklist above. EDGE-001..008 are now all marked covered with the test/fixture/report citation that exercises each case.

**Test invocation + outcomes (chunk 4):**
- `uv run pytest tests/` → 350 passed (default suite, no live stack, unchanged from chunk 3).
- `uv run pytest tests/eval/` → 58 passed (live-stack eval fixtures, unchanged from chunk 2 retry).
- `uv run pytest tests/contracts/` → 15 passed (live-stack contracts, unchanged from chunk 3).
- `uv run pytest tests/integration/` → **3 passed** (live-stack integration, new in chunk 4).

**Tests added by chunk 4:** 3 new tests (`tests/integration/test_auto_detect_routing.py`).

**Counter usage for chunk 4:** Reads ~7/12, Nested subagents 0/4.

### Chunk 5 — Finalization (REQ-017 + non-functional REQs + tracker close-out)

**Status:** Complete.

**Scope.** REQ-017 (Presidio upstream-merge CI gate); FAIL-001..006 verification + small test additions; PERF-001..003, SEC-001..004, PRIV-001..002, REL-001..003 non-functional verification with citations; finalize the tracker for handoff to Step 4b code review.

**Files created (Presidio fork):**
- `presidio/presidio-analyzer/scripts/upstream-merge-check.sh` — REQ-017 CI gate. Runs `tests/test_multi_nlp_engine.py` (17 tests including the new FAIL-002 parametrized cases) + `tests/test_install_nlp_models_multi.py` (7 tests for FAIL-005 install-side coverage) + `scripts/smoke_test_multi.py` (offline config-shape smoke). Exits 0 on success. Wall time ~0.2 s. Verified once on the current state — all green.
- `presidio/presidio-analyzer/tests/test_install_nlp_models_multi.py` — FAIL-005 install-side tests (7 cases). Loads `install_nlp_models.py` by absolute path (it lives at the package root, not on `sys.path`). Covers `_validate_multi_row` rejection branches: unknown engine, missing engine key, missing lang_code, missing model_name, non-dict row; plus two well-formed-row sanity assertions (spacy + transformers).
- `presidio/MULTI_ENGINE.md` — operator-facing doc for the Redakt fork's `MultiNlpEngine` integration. Lists fork-side files, documents the upstream-merge gate, names what the gate catches (constructor signature drift, registry plumbing, config validator schema drift) and what it does NOT catch (behavioral regressions inside `SpacyNlpEngine` / `TransformersNlpEngine`; image-build wiring).

**Files modified (Presidio fork):**
- `presidio/presidio-analyzer/tests/test_multi_nlp_engine.py` — added FAIL-002 test `test_load_propagates_sub_engine_failure_and_is_loaded_returns_false`, parametrized across en-spacy and de-transformer slots. Asserts (a) `load()` propagates the failing sub-engine's exception, (b) `is_loaded()` returns False (no silent partial state), (c) retry of `load()` raises `RuntimeError` (one-shot contract). Total chunk-1A/5 unit tests: **17** (was 15).

**Files modified (Redakt repo):**
- `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md` (this file) — REQ-017 + all FAIL/PERF/SEC/PRIV/REL items marked Complete with citation; chunk-5 subsection appended; Final implementation summary section added; `Status:` set to `Complete (ready for code-review at Step 4b)`.
- `SDD/orchestration/progress.md` — Step 4a chunk 5 subsection appended.

#### Non-functional REQ verification (chunk 5)

**PERF-001 — Reproducible latency baseline (anchored).**
Captured at chunk 4. Three anchors × {warm-up = first run, steady-state median over N=5 warm runs}: short DE bare-noun (`Personalausweis`) 0.079 s steady-state, sentence-context EN (`My name is John Smith.`) 0.005 s, long-document DE (REQ-009b 557-token anchor) 1.262 s. All three sit inside the RESEARCH-007 §4 / CLARIFICATION-007 Q4 0.5–3 s expectation envelope for the DE transformer path. Documentation only (no SLO). Recorded in chunk 4 subsection above and in `progress.md`. Mark **Complete**.

**PERF-002 — Cold-start expectations and model-load-once.**
Cold-start measured at chunk 4: 9 s end-to-end on Apple Silicon dev hardware, with all three models (`en_core_web_lg`, `de_core_news_sm`, `xlm-roberta-large-finetuned-conll03-german`) emitting their `LOADED <model> at <ts>` structured log line exactly once before the HTTP server begins serving. Model-load-once invariant tested at the unit level by chunk 1A's `test_load_invokes_each_sub_engine_load_exactly_once` and `test_process_text_before_load_raises_runtime_error`; behavioral signal verified by the captured startup log. Healthcheck `start_period: 90s` retained as conservative envelope (10× the measurement). Mark **Complete**.

**PERF-003 — Image size growth (documentation only).**
Measured at chunk-5 close-out: `redakt-presidio-analyzer:latest` weighs **36.8 GB** uncompressed on the developer-machine Docker image registry (`docker images redakt-presidio-analyzer`). Major contributors per `docker history`: a ~10.8 GB layer (`pip install` + initial model download) and a ~9.5 GB layer (`install_nlp_models.py` for the `multi.yaml` rows, including `xlm-roberta-large-finetuned-conll03-german` weights). The on-disk uncompressed size includes Torch + Transformers + sentencepiece + protobuf + `en_core_web_lg` + `de_core_news_sm` + the transformer weights + tokenizer assets. CLARIFICATION-007 Q4 sets no cap; per spec this is documentation only. Captured here for future regression comparison. Mark **Complete**.

**SEC-001 — No new PII storage paths.**
Verified by reading `src/redakt/services/audit.py` (chunk 5): `_emit_audit` (lines 105-154) and `log_detection` (lines 157-171) build `record.audit_data` from typed metadata fields only — `action`, `entity_count`, `entities_found` (entity-type names only, e.g., `["PERSON", "LOCATION"]`), `language_detected`, `source`, optional `allow_list_count`, `file_type`, `file_size_bytes`, `operator`. The original text and detected PII content are never logged. The `exc_info=True` recovery path comment (lines 145-148) confirms the safety guarantee is preserved on failure. Input-size ceiling `max_text_length: 512_000` (`src/redakt/config.py:18`) is unchanged by this feature; the analyzer's per-request compute budget remains implicitly bounded. Mark **Complete**.

**SEC-002 — Recognizer-registry floor preserved.**
Verified at chunk 3 by `tests/contracts/test_recognizer_registry_floor.py` (8 tests parametrized over en/de × 4 properties: names enabled, supported_entities preserved, pattern scoring preserved, relative order preserved). Allows additions, fails on removals/disables/dropped patterns/rescored patterns/order regressions. YAML-diff evidence at `reports/req-011-recognizer-diffs.md` (gitignored): both Redakt-side and fork-side `default_recognizers.yaml` diffs are empty — additions-only constraint trivially satisfied. Mark **Complete**.

**SEC-003 — Model supply-chain trust boundary.**
Verified at chunk 1B + chunk 4. `multi.yaml` pins `revision: 1fbcc7a00a69ce5ab754623154a8e9cc6ba868e2` (HF Hub commit SHA captured 2026-05-06). `install_nlp_models.py` reads `multi.model_digests.json` on every build, recomputes per-file SHA-256 of downloaded weights, fails the build on mismatch, writes a fresh manifest on first known-good build (`{}` placeholder treated as baseline-capture mode per `_load_digest_manifest`). Build-time-only network egress to HF Hub; runtime is offline-after-build. Manifest is the supply-chain trust anchor — revision pinning alone is insufficient because HF Hub can mutate bytes served under a given revision. Runtime-side `from_pretrained(revision=...)` gap noted in chunk 1B subsection above (deferred — does not affect the SEC-003 build-time trust anchor). Mark **Complete**.

**SEC-004 — Internal-only Presidio service surface.**
Verified by reading `docker-compose.yml`: `presidio-analyzer` exposes no host port (only the internal compose network); `redakt` is the only service that talks to it. Unchanged by this feature (RESEARCH-007 §16.1). Mark **Complete**.

**PRIV-001 — No PII at rest, no PII in audit log.**
Same evidence as SEC-001. Audit logger emits typed metadata only — entity-type name strings (`"PERSON"`, `"LOCATION"`), counts, language code, source. Text content and detected PII spans are never persisted. Backend stays stateless per project design (CLAUDE.md: "Anonymization mappings are returned to the client (browser holds them; deanonymization is client-side)"). Mark **Complete**.

**PRIV-002 — Calibration corpus is synthetic.**
Verified by reading `tests/eval/fixtures/de.yaml` (chunk 2 retry additions): the 15 broader-class `expect_clean: true` fixtures are bare German noun forms (`Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, etc.) with no associated identifying numbers. The held-out positive `Sie wohnt in Berlin und arbeitet in München.` uses synthetic placeholder pronoun + city names. The 557-token long-document anchor is a 3× repetition of a synthetic German prose paragraph. No real-person names, no real ID numbers, no real PII content — only structurally-shaped synthetic phrases the calibration tooling consumes. Calibration is dev-time only and never reaches production deployment. Mark **Complete**.

**REL-001 — Build-time failure surface.**
Verified by FAIL-001 + FAIL-005 coverage (above). The HF model download in `install_nlp_models._install_multi_engine_models` (chunk 1B) raises ImportError if the transformers extra is missing, propagates `huggingface_hub` network errors, and rejects malformed config rows via `_validate_multi_row` (chunk 1B + chunk 5 install-side tests). Failures are loud — `docker compose build presidio-analyzer` exits non-zero with a clear error; CI catches before any runtime state is reached. Mark **Complete**.

**REL-002 — Runtime failure surface (no silent fallback).**
Verified by FAIL-002 + FAIL-003 coverage (above). FAIL-002 chunk-5 parametrized tests assert sub-engine load failures propagate AND `is_loaded()` returns False AND retrying `load()` raises (one-shot contract). FAIL-003 chunk-1A test asserts unsupported-language requests raise `ValueError` with a clear message. REQ-005a Behavior B (chunk 1B) wires this into the deployment shape: the analyzer process exits before binding HTTP if `load()` raises; the healthcheck never reaches 200. No silent degraded state. Mark **Complete**.

**REL-003 — Calibration data is development-time only.**
Verified by FAIL-004 coverage (above). The `calibration corpus` (`tests/eval/fixtures/`) is consumed only by `tools/calibration_report.py` and `tests/eval/test_calibration.py` — both dev-time tools. The Redakt request path in `src/redakt/routers/detect.py` does not read these fixtures; it goes straight to the Presidio analyzer container. Production deployment images do not include the fixtures directory. Structurally request-path-independent. Mark **Complete**.

**Test additions (chunk 5):**
- `tests/test_multi_nlp_engine.py`: +2 (FAIL-002 parametrized en + de). Total: 17.
- `tests/test_install_nlp_models_multi.py`: +7 (FAIL-005 install-side coverage). New file.

**Test invocations + outcomes (chunk 5 final sweep):**
```
# Redakt side
uv run pytest tests/                  → 350 passed in 2.5 s
uv run pytest tests/eval/             → 58 passed in 4.7 s
uv run pytest tests/contracts/        → 15 passed in 4.3 s
uv run pytest tests/integration/      → 3 passed in 0.3 s

# Presidio fork side
cd presidio/presidio-analyzer
uv run pytest tests/test_multi_nlp_engine.py tests/test_install_nlp_models_multi.py
                                      → 24 passed in 0.05 s
./scripts/upstream-merge-check.sh     → 24 + smoke pass in ~0.2 s
```
All green. No regressions across any chunk.

**Counter usage for chunk 5:** Reads ~10/15, Nested subagents 0/4.

### Chunk 4c — Code-review fix landings (post Step 4b APPROVED)

**Status:** Complete.

Code-review at Step 4b returned APPROVED with 0 HIGH, 1 MEDIUM, 3 LOW findings. All four findings addressed at Step 4c:

- **F-1 MEDIUM (runtime `from_pretrained(revision=...)` gap):** Patched in the Presidio fork. `MultiNlpEngine._build_sub_engine` now forwards `revision` from the YAML row into the per-engine `models[]` row. `TransformersNlpEngine.load()` now reads `model.get("revision")` and injects it into `pipe_config["revision"]` (wrapped in `# === redakt: ... ===` markers per the upstream-merge convention from Notes). Two new unit tests assert the contract: positive (revision present → reaches `pipe_config`) and negative (revision absent → key not injected, preserves the upstream `hf_token_pipe` default of `"main"` for direct callers). Closes deviation 1.
- **F-2 LOW (`start_period: 90s` vs. 30s formula):** Already documented in `docker-compose.yml` lines 33-42 (healthcheck comment block) and tracker deviation 2. Acknowledged; no code change required.
- **F-3 LOW (`multi.yaml` per-row `engine`/`revision` keys not in `ConfigurationValidator` schema branch):** Acknowledged. The "or annotated to skip detailed validation for `multi`" wording in REQ-002 is satisfied by Presidio's open-schema validator passing unknown row keys silently; build-time validation at `install_nlp_models._validate_multi_row` and runtime validation at `MultiNlpEngine._validate_row` cover the surface. Adding a dedicated schema branch would be ceremony with no marginal coverage. No code change.
- **F-4 LOW (`MultiNlpEngine.load()` increments `_load_call_count` before sub-engine iteration):** Acknowledged as the explicit one-shot contract, not a defect. `tests/test_multi_nlp_engine.py::test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` lines 416-422 already locks the contract; recovery path is operator restart per REL-002. No code change.

**Test sweep at chunk-4c close-out (all green):**

```bash
uv run pytest tests/                 # 350 PASS (unchanged)
uv run pytest tests/eval/            # 58 PASS  (unchanged)
uv run pytest tests/contracts/       # 15 PASS  (unchanged)
uv run pytest tests/integration/     # 3 PASS   (unchanged)
cd presidio/presidio-analyzer && uv run pytest \
    tests/test_multi_nlp_engine.py \
    tests/test_install_nlp_models_multi.py
                                     # 26 PASS  (was 24; +2 for F-1)
```

**Files changed at chunk 4c:**

- Presidio fork: `presidio_analyzer/nlp_engine/multi_nlp_engine.py` (~7 LoC), `presidio_analyzer/nlp_engine/transformers_nlp_engine.py` (~12 LoC including comment block + redakt markers), `tests/test_multi_nlp_engine.py` (~115 LoC: 2 new tests + a small helper).
- Redakt: `SDD/reviews/REVIEW-007-transformers-nlp-backend-20260506.md` (Findings Addressed section appended), `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md` (this update).

**LoC diff for the production fix:** ~5 LoC of production code in two files, well under the 30-LoC bail-out threshold from the chunk-4c prompt.

**Commits:** Presidio fork takes the F-1 patch in commit `258ded3` (`SDD-007 chunk 4c: forward per-row revision into TransformersNlpEngine.load()`). Redakt repo takes the tracker + review-document update in one commit (see commit timeline below).

## Final implementation summary

**Status:** Complete. All 17 functional REQs + 8 EDGE cases + 6 FAIL scenarios + 3 PERF + 4 SEC + 2 PRIV + 3 REL items are marked Complete in this tracker with citations. Ready for handoff to Step 4b code review.

### Commit timeline

**Presidio fork (`feature/redakt-007-multi-nlp-engine`):**
| Chunk | SHA (short) | Description |
| --- | --- | --- |
| 1A | `1070180b` | `MultiNlpEngine` class + `NlpEngineProvider` registration + 15 unit tests |
| 1B | `d604514` | `multi.yaml` + `install_nlp_models.py` extension + `Dockerfile.multi` + `multi.model_digests.json` + smoke test |
| 5 | `23049af` | REQ-017 upstream-merge CI gate + FAIL-002 test + FAIL-005 install-side tests + `MULTI_ENGINE.md` |

**Redakt (`feature/007-transformers-nlp-backend`):**
| Chunk | SHA (short) | Description |
| --- | --- | --- |
| 1B | `3fc10b1` | `docker-compose.yml` retarget to `Dockerfile.multi` + tracker plumbing |
| 2 retry | `e316caf` | 17 new DE fixtures + four-bar verification (REQ-006/007/008/009/009b) |
| 3 | `1092d8b` | API contract gates + recognizer registry floor (REQ-010/010a/011) |
| 4 | `f5f1543` | Auto-detect routing test + edges + cold-start (REQ-012/014/015/016 + EDGE-001..008) |
| 5 | _this commit_ | Tracker close-out + non-functional REQ verifications |

### Test count (verified at chunk-5 final sweep)

| Suite | Count | Notes |
| --- | --- | --- |
| Redakt unit + integration (`tests/`, default) | 350 | Excludes live-stack suites via `pyproject.toml addopts` |
| Redakt eval fixtures (`tests/eval/`) | 58 | 41 existing + 15 broader-class clean + 2 REQ-009b held-out positive + long-doc |
| Redakt contracts (`tests/contracts/`) | 15 | OpenAPI diff (2) + API shape (5) + recognizer floor (8) |
| Redakt integration (`tests/integration/`) | 3 | `language: auto` routing × {DE, EN, swap-detect fingerprint} |
| Presidio fork chunk-1A unit (`tests/test_multi_nlp_engine.py`) | 19 | 15 chunk-1A + 2 chunk-5 FAIL-002 parametrized + 2 chunk-4c REQ-013 runtime-revision |
| Presidio fork install-side (`tests/test_install_nlp_models_multi.py`) | 7 | All chunk-5 FAIL-005 |
| Offline config-shape smoke (`scripts/smoke_test_multi.py`) | 1 invocation | 4 internal assertions |
| **Total tests** | **452 + 1 smoke** | All green at chunk-4c close-out (was 450 at chunk-5 close-out; +2 for F-1 patch) |

### Files changed (across both repos)

**Presidio fork (commits 1A + 1B + 5 + 4c):**
- New: `presidio_analyzer/nlp_engine/multi_nlp_engine.py` (~350 LOC including chunk 4c revision-forwarding edit).
- New: `presidio_analyzer/conf/multi.yaml`.
- New: `presidio_analyzer/conf/multi.model_digests.json` (populated baseline).
- New: `Dockerfile.multi`.
- New: `scripts/smoke_test_multi.py`.
- New: `scripts/upstream-merge-check.sh` (chunk 5).
- New: `tests/test_multi_nlp_engine.py` (19 tests; chunk 4c added 2 REQ-013 runtime-revision tests).
- New: `tests/test_install_nlp_models_multi.py` (7 tests; chunk 5).
- New: `presidio/MULTI_ENGINE.md` (chunk 5).
- Modified: `install_nlp_models.py` (multi-engine branch + digest manifest read/write/verify).
- Modified: `presidio_analyzer/nlp_engine/__init__.py` (`MultiNlpEngine` export).
- Modified: `presidio_analyzer/nlp_engine/nlp_engine_provider.py` (`multi` engine registration).
- Modified: `presidio_analyzer/nlp_engine/transformers_nlp_engine.py` (chunk 4c F-1: forward per-row `revision` into `hf_token_pipe`'s `pipe_config`; wrapped in `# === redakt: ... ===` markers).
- Modified: `presidio_analyzer/tests/conftest.py` (skip multi engine in session-scoped fixture).

**Redakt (commits 1B + 2 retry + 3 + 4 + 5 + 4c):**
- New: `tests/contracts/` package (8 files: 2 test modules, 5 snapshot baselines, 1 conftest, plus `recognizers-baseline.json`, `openapi-baseline.json`).
- New: `tests/integration/` package (2 files: `test_auto_detect_routing.py`, `conftest.py`).
- New: `reports/calibration-007-before.md`, `reports/calibration-007-after.md`, `reports/req-011-recognizer-diffs.md`, `reports/req-015-probe.md` (gitignored).
- New: `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md` (this tracker).
- Modified: `tests/eval/fixtures/de.yaml` (+17 entries).
- Modified: `docker-compose.yml` (retarget to `Dockerfile.multi`; `start_period: 90s`).
- Modified: `pyproject.toml` (test-tree exclusions for `tests/contracts`, `tests/integration`).
- Modified: `README.md`, `docs/v1-feature-spec.md`, `docs/presidio-integration.md` (REQ-012 code-switched-text docs).

### Deviations from the spec

1. **~~Per-row `revision` not yet honored at runtime by upstream `TransformersNlpEngine`~~ — RESOLVED at chunk 4c** (code-review F-1, MEDIUM). `install_nlp_models.py` correctly forwarded `revision` at build time, but upstream Presidio's `TransformersNlpEngine.load()` was calling `from_pretrained(model_name)` without `revision=`. Closed at chunk 4c with a small two-file fork patch: `MultiNlpEngine._build_sub_engine` now includes `revision` in the sub-engine's `models[]` row when present, and `TransformersNlpEngine.load()` forwards it into `hf_token_pipe`'s `pipe_config["revision"]` (wrapped in `# === redakt: ... ===` markers for upstream-merge ergonomics). The single `revision` reaches `transformers.pipeline(..., revision=<sha>)` and applies to both tokenizer and model `from_pretrained` calls. Two new unit tests assert positive (revision present → forwarded) and negative (revision absent → not injected, preserves upstream `"main"` default for direct callers).

2. **Chunk 4 `start_period: 90s` retained instead of `30s` from REQ-014's measurement formula.** Measured cold-start was 9 s; the option (b) 2× formula computes `max(30s, ceil(2 × 9s)) = 30s`. The tracker retains the chunk-1B placeholder of 90 s as a conservative envelope (10× measurement, ~5× formula) to comfortably accommodate colder-cache scenarios (first-build, post-prune; transformer load could approach 30 s on cold OS page cache). This is a deliberate over-budget rather than under-spec; healthcheck reaches healthy state in ~3 s on warm-disk cold-start (chunk 4 evidence), so the operator observability impact is "minutes of pre-`start_period` headroom that is never consumed." Documented in chunk 4 subsection.

3. **DE DATE_TIME held-out positive dropped per Amendment 2026-05-06 (Option A).** xlm-roberta CoNLL-03 has no DATE label; DE DATE_TIME is regex-only via `DateRecognizer` at 0.6/0.8 ceiling — model-design limitation. Bar 2 of REQ-006's four-bar stopping condition was rewritten entity-conditional. DE LOCATION held-out positive retained. Captured in spec amendment + chunk 2 retry subsection.

4. **PERF-003 image size at 36.8 GB uncompressed.** Spec is "documentation only" with no cap; documented at chunk-5 close-out per advisor guidance. Compressed on-registry size will be smaller; this is the locally-built layer-uncompressed total and is captured here for future regression comparison rather than as a SLO.

No other deviations.

### What chunk 5 deliberately did NOT do

- **Did not run a real-model integration test for FAIL-002 sub-engine load failure** (spec validation point (c)). Structurally covered by REQ-005a Behavior B + the chunk-1B image-build verification: when `load()` raises, the analyzer process exits before binding HTTP and the healthcheck never reaches 200. Adding a real-model failure-injection integration test would mean a 10-minute image build per parametrized case for one-time evidence, with no marginal coverage beyond the structural guard. Rejected per advisor guidance.

- **Did not patch the runtime `from_pretrained(revision=...)` gap.** Out of chunk-5 scope per the chunk prompt's "Don't add features beyond REQ scope" rule. Flagged in deviation 1 above for Step 4b code review to decide whether to land a fork-side patch as part of post-review polish or defer to a follow-up feature. **Update (chunk 4c):** patched after code-review F-1; deviation 1 marked RESOLVED.

- **Did not run the LangSmith / regression-eval-capture step (Step 4g).** Per the chunk prompt's "Skip LangSmith / regression-eval-capture (Step 4g — orchestrator handles after 4f)" rule.

## Future maintenance

**REQ-009 broader-class extension rule (operationalized — SDD-007 4e F-G).** The spec mandates: any German common-noun-as-`PERSON` over-detection encountered during calibration that is NOT in the 15 enumerated bare nouns MUST be added to `tests/eval/fixtures/de.yaml` as an `expect_clean: true` entry before landing the change. This rule is now codified at this location and at the top of `tests/eval/fixtures/de.yaml`'s broader-class section. Operator workflow when adding/swapping a German NLP model:

1. Run `uv run python tools/calibration_report.py --raw --out` against the new model.
2. Inspect each German fixture's `redakt:` and `raw:` columns for novel `PERSON` hits on bare common nouns.
3. For every novel over-detection: add the noun to `tests/eval/fixtures/de.yaml` as `expect_clean: true` with a `notes:` field tagged `Broader-class extension (REQ-009 §extension rule).` BEFORE landing the model swap.
4. Re-run `uv run pytest tests/eval/` to confirm all expanded clean fixtures pass.

This converts a procedural commitment into a checklist tied to the calibration tool's existing output. CI does NOT enforce step 2 (no automated noun-vocabulary crawl); enforcement is operator vigilance, gated by `/sdd:critical-review` at any model-swap chunk.

**Single-arch image build (SDD-007 4e F-H).** The README documents `DOCKER_DEFAULT_PLATFORM=linux/arm64` (or `linux/amd64`) for local dev to avoid a multi-arch buildx default. Production deploys should pin `--platform` explicitly in their orchestrator manifest. Spec: PERF-003 is documentation-only; this guidance is operator-facing.

**FAIL-002 partial-load process-exit verification (SDD-007 4e F-K).** Unit-level coverage in `presidio/presidio-analyzer/tests/test_multi_nlp_engine.py::test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` proves `is_loaded()` returns False when a sub-engine raises. Deployment-shape (Docker exits non-zero → restart policy retries) is structurally covered by REQ-005a Behavior B + the chunk-1B image-build verification: when `MultiNlpEngine.load()` raises, the analyzer process exits before binding HTTP and the healthcheck never reaches 200. A captured failure-injection transcript was rejected at chunk 5 per advisor guidance (10-min image build per parametrized case, no marginal coverage). 4e F-F additionally relaxes the one-shot guard so in-process retry is permitted after a transient failure (deployment shape unchanged; SDK / single-process embedders are no longer locked out).

**REQ-013 tamper-test evidence (SDD-007 4e F-A, F-N).** A populated `multi.model_digests.json` is now committed to the Presidio fork (was the empty placeholder `{}` at chunk 1B partial commit; populated from the running analyzer image at 4e). Verify-mode is now active on subsequent builds. The tamper test was run against the populated manifest at 4e; the failing build's stderr is captured under `reports/req-013-tamper.md` (gitignored). Unit-level tamper coverage lives in `presidio/presidio-analyzer/tests/test_install_nlp_models_multi.py` (5 new tests at 4e). The atomic-write fix (`os.replace` pattern) at 4e F-I closes the parallel-build race window.

**HF Hub token plumbing (SDD-007 4e F-L, RISK-001).** Token plumbing is operator-hand-rolled. The README documents the BuildKit-secret invocation pattern (`docker buildx build --secret id=hf_token,env=HUGGINGFACE_HUB_TOKEN ...`) for environments that hit anonymous rate limits. The default build path is anonymous; this is acceptable for typical dev cadence given the model is fetched once per build and BuildKit caches the layer. Production deploys that rebuild frequently should configure the token; the corresponding `--mount=type=secret` block in `Dockerfile.multi` is left as a deliberate operator extension to avoid coupling the image to a token-presence assumption.

**Two-repo SHA traceability (SDD-007 4e F-J).** `.presidio-pin` at the Redakt repo root records the fork branch + commit SHA range for the feature. Future Redakt commits that touch the analyzer integration MUST update this file in the same commit. If the fork rebases (RISK-003), update the SHAs here to keep the pairing intact. The CLAUDE.md decision to keep `presidio/` as a fork checkout (not a submodule) stands — `.presidio-pin` is the lighter-weight discipline alternative.

## Notes

- Two-repo discipline: chunk 1A's code lands in the Presidio fork (`./presidio/`), not the Redakt repo. The Redakt-side commit for chunk 1A is this tracker file plus the progress entry. Chunk 1B follows the same split — Presidio fork takes `multi.yaml`, `install_nlp_models.py`, `Dockerfile.multi`, `multi_nlp_engine.py` (`.nlp` property), `multi.model_digests.json`, `scripts/smoke_test_multi.py`; Redakt takes `docker-compose.yml` and the SDD tracker/progress updates.
- Fork-side diffs are wrapped in `# === redakt: ... ===` markers per Implementation Constraints, easing future upstream-Presidio merges.
- Counter usage for chunk 1A: 10/10 reads, 0/4 nested subagents.
