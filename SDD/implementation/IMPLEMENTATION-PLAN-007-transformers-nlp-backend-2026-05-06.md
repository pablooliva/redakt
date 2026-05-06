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

- [x] **REQ-001** — `MultiNlpEngine` subclass in the Presidio fork — **Complete** (chunk 1A)
- [x] **REQ-002** — Engine-name registration with `NlpEngineProvider` — **Complete** (chunk 1A)
- [ ] **REQ-003** — New analyzer NLP YAML for the multi engine — Not Started
- [ ] **REQ-004** — `install_nlp_models.py` extension for the `multi` engine — Not Started
- [ ] **REQ-005** — Dockerfile + docker-compose wiring — Not Started
- [ ] **REQ-005a** — Two-phase startup contract (readiness probe wired to `is_loaded()`) — Not Started
- [ ] **REQ-006** — Per-entity score floor re-tune (Redakt-side) — Not Started
- [ ] **REQ-007** — Global threshold knob re-tune (analyzer-side, per language) — Not Started
- [ ] **REQ-008** — Calibration corpus expansion (broader class) — Not Started
- [ ] **REQ-009** — New CI fixtures for `broader class` over-detection — Not Started
- [ ] **REQ-009b** — Held-out positive fixtures (DE LOCATION, DE DATE_TIME) and long-document anchor — Not Started
- [ ] **REQ-010** — API contract preservation — Not Started
- [ ] **REQ-010a** — API-shape regression test (byte-identical envelope + headers) — Not Started
- [ ] **REQ-011** — Recognizer-registry floor preservation — Not Started
- [ ] **REQ-012** — Documentation of code-switched-text limitation — Not Started
- [ ] **REQ-013** — HF model revision pinning + artifact-level integrity verification — Not Started
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

- [ ] **FAIL-001** — Transformer model download fails at image build — Not Started
- [ ] **FAIL-002** — Any sub-engine load failure at runtime (en or de; spaCy or transformer) — Not Started
- [ ] **FAIL-003** — `MultiNlpEngine` receives a request for an unconfigured language — Partially covered in chunk 1A unit tests (`test_process_text_unsupported_language_raises_clear_error`); end-to-end coverage deferred to chunk 1B/4.
- [ ] **FAIL-004** — Calibration corpus / fixtures not present at runtime — Not Started
- [ ] **FAIL-005** — Build-time install dispatcher silently passes on a bad row — Not Started
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

## Notes

- Two-repo discipline: chunk 1A's code lands in the Presidio fork (`./presidio/`), not the Redakt repo. The Redakt-side commit for chunk 1A is this tracker file plus the progress entry.
- Fork-side diffs are wrapped in `# === redakt: MultiNlpEngine ===` markers per Implementation Constraints, easing future upstream-Presidio merges.
- Counter usage for chunk 1A: 10/10 reads, 0/4 nested subagents.
