# IMPLEMENTATION-PLAN-007 — transformers-nlp-backend

## Metadata

- **Feature ID:** 007
- **Feature name:** transformers-nlp-backend
- **Specification:** [SDD/requirements/SPEC-007-transformers-nlp-backend.md](../requirements/SPEC-007-transformers-nlp-backend.md)
- **ADR:** [SDD/adr/0001-presidio-per-language-nlp-engine.md](../adr/0001-presidio-per-language-nlp-engine.md)
- **Started:** 2026-05-06
- **Author:** Claude
- **Status:** In Progress
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
- [ ] **REQ-006** — Per-entity score floor re-tune (Redakt-side) — Not Started
- [ ] **REQ-007** — Global threshold knob re-tune (analyzer-side, per language) — Not Started
- [ ] **REQ-008** — Calibration corpus expansion (broader class) — Not Started
- [ ] **REQ-009** — New CI fixtures for `broader class` over-detection — Not Started
- [ ] **REQ-009b** — Held-out positive fixtures (DE LOCATION, DE DATE_TIME) and long-document anchor — Not Started
- [ ] **REQ-010** — API contract preservation — Not Started
- [ ] **REQ-010a** — API-shape regression test (byte-identical envelope + headers) — Not Started
- [ ] **REQ-011** — Recognizer-registry floor preservation — Not Started
- [ ] **REQ-012** — Documentation of code-switched-text limitation — Not Started
- [x] **REQ-013** — HF model revision pinning + artifact-level integrity verification — **Complete** (chunk 1B; YAML `revision` key wired into `install_nlp_models.py`; baseline manifest captured at first build; verification mode active on subsequent builds. `from_pretrained(revision=...)` is also forwarded in install. Runtime `from_pretrained` in upstream-Presidio's `TransformersNlpEngine` does NOT yet honor the YAML revision — gap noted below; deferred to chunk 4.)
- [ ] **REQ-014** — Cold-start measurement gate (with hardware-class binding and explicit safety margin) — Not Started
- [ ] **REQ-015** — Pre-deploy in-Redakt model probe — Not Started
- [ ] **REQ-016** — End-to-end `language: auto` routing test (positive coverage) — Not Started
- [ ] **REQ-017** — Upstream-merge regression CI check (`MultiNlpEngine` import smoke) — Not Started

### Edge Cases (EDGE)

- [ ] **EDGE-001** — Code-switched text (`asymmetric routing` failure-mode flip) — Not Started
- [ ] **EDGE-002** — German common nouns from the broader class — Not Started
- [ ] **EDGE-003** — Common-noun + adjacent number — Not Started
- [ ] **EDGE-004** — Lingua-py mis-detection — Not Started
- [ ] **EDGE-005** — PERSON name that *is* a German common noun — Not Started
- [ ] **EDGE-006** — Long German text exceeding tokenizer max length — Not Started
- [ ] **EDGE-007** — Empty text input — Not Started
- [ ] **EDGE-008** — Defensible `BIC` ORG flag — Not Started

### Failure Scenarios (FAIL)

- [x] **FAIL-001** — Transformer model download fails at image build — **Complete** (chunk 1B; `install_nlp_models._install_multi_engine_models` raises `ImportError` if transformers extra missing, propagates `huggingface_hub` errors. Verified once during chunk-1B image build.)
- [ ] **FAIL-002** — Any sub-engine load failure at runtime (en or de; spaCy or transformer) — Not Started
- [ ] **FAIL-003** — `MultiNlpEngine` receives a request for an unconfigured language — Partially covered in chunk 1A unit tests (`test_process_text_unsupported_language_raises_clear_error`); end-to-end coverage deferred to chunk 1B/4.
- [ ] **FAIL-004** — Calibration corpus / fixtures not present at runtime — Not Started
- [x] **FAIL-005** — Build-time install dispatcher silently passes on a bad row — **Complete** (chunk 1B; `_validate_multi_row` rejects unknown / missing `engine` and missing `model_name` / `lang_code` with clear errors before any download is attempted.)
- [ ] **FAIL-006** — Calibration results diverge from §4.5 probe — Not Started

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

## Notes

- Two-repo discipline: chunk 1A's code lands in the Presidio fork (`./presidio/`), not the Redakt repo. The Redakt-side commit for chunk 1A is this tracker file plus the progress entry. Chunk 1B follows the same split — Presidio fork takes `multi.yaml`, `install_nlp_models.py`, `Dockerfile.multi`, `multi_nlp_engine.py` (`.nlp` property), `multi.model_digests.json`, `scripts/smoke_test_multi.py`; Redakt takes `docker-compose.yml` and the SDD tracker/progress updates.
- Fork-side diffs are wrapped in `# === redakt: ... ===` markers per Implementation Constraints, easing future upstream-Presidio merges.
- Counter usage for chunk 1A: 10/10 reads, 0/4 nested subagents.
