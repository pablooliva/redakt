# IMPLEMENTATION SUMMARY — SDD-007 transformers-nlp-backend

**Feature ID:** 007
**Feature name:** transformers-nlp-backend
**Generated:** 2026-05-06_16-23-50
**Status:** Complete ✓
**Branch (Redakt):** `feature/007-transformers-nlp-backend`
**Branch (Presidio fork):** `feature/redakt-007-multi-nlp-engine`

---

## Feature Overview

SDD-007 introduces **asymmetric per-language NLP routing** (`asymmetric routing`) to Redakt's Presidio analyzer. A new `MultiNlpEngine` subclass — added to the Presidio fork (`./presidio/`) — dispatches `process_text` / `process_batch` to per-language sub-engines:

- **English (`en`):** spaCy `en_core_web_lg` (preserved verbatim from prior config).
- **German (`de`):** transformer pipeline `FacebookAI/xlm-roberta-large-finetuned-conll03-german`, pinned to commit SHA `1fbcc7a00a69ce5ab754623154a8e9cc6ba868e2`. spaCy `de_core_news_sm` is loaded alongside as the auxiliary tokenizer/lemmatizer for the transformers wrapper.

This swap fixes the German common-noun-as-`PERSON` over-detection class (the **broader class**) — `Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, etc. — by routing German text through a model that does not produce spurious PER hits on bare ID-document nouns. English behavior is bit-for-bit identical to the prior deployment by construction. The Redakt API contract is preserved verbatim (REQ-010 + REQ-010a contract gates).

The supply-chain trust anchor is a checked-in **digest manifest** (`presidio/.../conf/multi.model_digests.json`, 14 SHA-256 entries for the pinned revision) that `install_nlp_models.py` verifies on every build. Threshold tuning landed without any value change — the chunk-1B placeholders survived the four-bar stopping condition under Spec Amendment 2026-05-06 (Option A).

---

## Requirements Completion Matrix

### Functional Requirements (REQ-001 → REQ-017)

| REQ | Description | Status | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `MultiNlpEngine` subclass | Complete | `presidio_analyzer/nlp_engine/multi_nlp_engine.py:91-341`; 19 unit tests. |
| REQ-002 | NlpEngineProvider registration (`multi`) | Complete | `nlp_engine_provider.py:43-49`; schema validator docstring annotation per F-E. |
| REQ-003 | `multi.yaml` config | Complete | `presidio_analyzer/conf/multi.yaml`. |
| REQ-004 | `install_nlp_models.py` extension | Complete | `install_nlp_models.py:81-90` + `_install_multi_engine_models` (177-283). |
| REQ-005 | Dockerfile + compose wiring | Complete | `Dockerfile.multi`, `docker-compose.yml:25-49`. |
| REQ-005a | Two-phase startup contract | Complete | Behavior B; `is_loaded()` aggregation in `multi_nlp_engine.py:223-232`. |
| REQ-006 | Per-entity score floor re-tune (Redakt) | Complete | Four-bar verification in `reports/calibration-007-after.md` (entity-conditional Bar 2). |
| REQ-007 | Global threshold knob re-tune (analyzer DE row) | Complete | DE row knobs retained from chunk-1B; EN frozen. |
| REQ-008 | Calibration corpus expansion | Complete | 15 broader-class + 1 long-doc anchor exercised by `tools/calibration_report.py`. |
| REQ-009 | New CI fixtures (broader class) | Complete | 15 `expect_clean: true` entries in `tests/eval/fixtures/de.yaml`. |
| REQ-009b | Held-out positive + long-doc anchor | Complete | DE LOCATION + 557-token anchor; DE DATE_TIME dropped per Amendment. |
| REQ-010 | API contract preservation | Complete | `tests/contracts/openapi-baseline.json` + `test_openapi_diff.py` (2 tests). |
| REQ-010a | API-shape regression test | Complete | `test_api_shape.py` 5 tests + 5 snapshot baselines; tamper test verified. |
| REQ-011 | Recognizer-registry floor preservation | Complete | `test_recognizer_registry_floor.py` 8 parametrized tests. |
| REQ-012 | Code-switched-text docs | Complete | `README.md`, `docs/v1-feature-spec.md`, `docs/presidio-integration.md`. |
| REQ-013 | HF revision pinning + digest manifest | Complete | Build-time + runtime forwarding (chunk 4c); 14-entry manifest + tamper test (chunk 4e). |
| REQ-014 | Cold-start measurement gate | Complete | 9 s measured; `start_period: 30s` per formula. |
| REQ-015 | Pre-deploy in-Redakt probe | Complete | `reports/req-015-probe.md` matches RESEARCH-007 §4.5. |
| REQ-016 | `language: auto` E2E routing test | Complete | `tests/integration/test_auto_detect_routing.py` 3 tests. |
| REQ-017 | Upstream-merge regression CI smoke | Complete | `presidio/presidio-analyzer/scripts/upstream-merge-check.sh`. |

### Edge Cases (EDGE-001 → EDGE-008)

| EDGE | Description | Status | Evidence |
| --- | --- | --- | --- |
| EDGE-001 | Code-switched text (failure-mode flip) | Covered | F-M code-switched fixture in `tests/eval/fixtures/de.yaml`; REQ-012 docs. |
| EDGE-002 | German common nouns from broader class | Covered | 15 `expect_clean: true` fixtures + REQ-015 probe Set A + Set B. |
| EDGE-003 | Common-noun + adjacent number | Covered | Existing `de.yaml` PII fixtures (`Personalausweis Nummer L01X00T47.`, etc.) stay PASS. |
| EDGE-004 | Lingua-py mis-detection | Covered | REQ-012 docs (override via explicit `language`); integration test exercises override path. |
| EDGE-005 | PERSON name that *is* a German common noun | Covered | `Anna Schmidt arbeitet bei der Beispiel AG in Berlin.` fixture stays PASS; REQ-015 probe Set C. |
| EDGE-006 | Long German text exceeding tokenizer max | Covered | 557-token long-doc fixture; PERF-001 baseline 1.262 s exercises `stride: 16` windowing. |
| EDGE-007 | Empty text input | Covered | Existing Redakt request validation; analyzer never reached. |
| EDGE-008 | Defensible `BIC` ORG flag | Covered | REQ-015 probe transcript Set B `BIC → ORG(0.40)`. |

### Failure Scenarios (FAIL-001 → FAIL-006)

| FAIL | Description | Status | Evidence |
| --- | --- | --- | --- |
| FAIL-001 | Transformer model download fails at build | Implemented | `_install_multi_engine_models` raises ImportError + propagates HF errors. |
| FAIL-002 | Sub-engine load failure at runtime | Implemented | `test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` parametrized en + de; REQ-005a Behavior B exits process. |
| FAIL-003 | Unconfigured-language request | Implemented | `test_process_text_unsupported_language_raises_clear_error`. |
| FAIL-004 | Calibration corpus / fixtures absent at runtime | Implemented | Structural — calibration is dev-time only; production image excludes fixtures. |
| FAIL-005 | Build-time install dispatcher passes bad row | Implemented | `tests/test_install_nlp_models_multi.py` 7 tests covering all rejection branches. |
| FAIL-006 | Calibration diverges from §4.5 probe | Implemented | REQ-015 transcript matches §4.5 byte-for-byte; fallback action not exercised. |

### Non-Functional Requirements

| Group | ID | Description | Status |
| --- | --- | --- | --- |
| PERF | PERF-001 | Reproducible latency baseline (anchored) | Met |
| PERF | PERF-002 | Cold-start expectations + model-load-once | Met |
| PERF | PERF-003 | Image size (documentation only) | Met |
| SEC | SEC-001 | No new PII storage paths | Validated |
| SEC | SEC-002 | Recognizer-registry floor preserved | Validated |
| SEC | SEC-003 | Model supply-chain trust boundary | Validated |
| SEC | SEC-004 | Internal-only Presidio service surface | Validated |
| PRIV | PRIV-001 | No PII at rest, no PII in audit log | Validated |
| PRIV | PRIV-002 | Calibration corpus is synthetic | Validated |
| REL | REL-001 | Build-time failure surface | Validated |
| REL | REL-002 | Runtime failure surface (no silent fallback) | Validated |
| REL | REL-003 | Calibration data is dev-time only | Validated |

---

## Implementation Artifacts

### Presidio fork (`./presidio/`)

**New files:**

- `presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py` — `MultiNlpEngine` class (~342 LOC).
- `presidio-analyzer/presidio_analyzer/conf/multi.yaml` — per-language NLP config; pinned HF revision.
- `presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json` — 14 SHA-256 entries for the pinned revision.
- `presidio-analyzer/Dockerfile.multi` — sibling of `Dockerfile.transformers` defaulting to `multi.yaml`.
- `presidio-analyzer/scripts/smoke_test_multi.py` — offline config-shape smoke test.
- `presidio-analyzer/scripts/upstream-merge-check.sh` — REQ-017 CI gate (runs 31 unit tests + smoke).
- `MULTI_ENGINE.md` — operator-facing doc for the fork's `MultiNlpEngine` integration.

**Modified files:**

- `presidio-analyzer/presidio_analyzer/nlp_engine/__init__.py` — `MultiNlpEngine` export.
- `presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py` — `multi` engine registration in default tuple.
- `presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py` — chunk 4c F-1 patch: forward per-row `revision` into `hf_token_pipe`'s `pipe_config["revision"]` (`# === redakt: ... ===` markers).
- `presidio-analyzer/presidio_analyzer/input_validation/schemas.py` — F-E docstring annotation (multi-engine `engine`/`revision` keys validated downstream).
- `presidio-analyzer/install_nlp_models.py` — `multi` branch + per-row engine dispatch + digest manifest read/write/verify (atomic-rename pattern per F-I).
- `presidio-analyzer/tests/conftest.py` — skip `multi` engine in session-scoped fixture.

**Test files (Presidio fork):**

- `presidio-analyzer/tests/test_multi_nlp_engine.py` — 19 tests (15 chunk-1A + 2 chunk-5 FAIL-002 + 2 chunk-4c REQ-013 runtime-revision; chunk-4e F-F retry-after-failure semantics).
- `presidio-analyzer/tests/test_install_nlp_models_multi.py` — 12 tests (7 chunk-5 FAIL-005 + 5 chunk-4e tamper / round-trip / NEW / MISSING / empty-placeholder).

### Redakt repo

**New files:**

- `tests/contracts/__init__.py` + `conftest.py` — package marker + `client` fixture.
- `tests/contracts/openapi-baseline.json` — captured `/openapi.json` snapshot.
- `tests/contracts/test_openapi_diff.py` — 2 tests (baseline-exists guard + live-vs-baseline equality).
- `tests/contracts/snapshot_detect_en.json`, `snapshot_detect_de.json`, `snapshot_anonymize_en.json`, `snapshot_anonymize_de.json`, `snapshot_deanonymize.json` — 5 baselines.
- `tests/contracts/test_api_shape.py` — 5 tests (parametrized over en/de × {detect, anonymize}; deanonymize once).
- `tests/contracts/recognizers-baseline.json` — 24 en + 17 de recognizer entries (introspected from live registry).
- `tests/contracts/test_recognizer_registry_floor.py` — 8 parametrized tests over en/de × 4 properties.
- `tests/integration/__init__.py` + `conftest.py` — package marker + fixture.
- `tests/integration/test_auto_detect_routing.py` — 3 tests covering REQ-016 (DE auto-route, EN auto-route, swap fingerprint sanity).
- `.presidio-pin` — F-J two-repo SHA traceability file.

**Modified files (Redakt):**

- `docker-compose.yml` — `dockerfile: Dockerfile.multi`, `args.NLP_CONF_FILE`, healthcheck `start_period: 30s` per F-D (revised from chunk-1B placeholder 90s).
- `pyproject.toml` — `--ignore=tests/contracts` and `--ignore=tests/integration` in pytest `addopts`.
- `tests/eval/fixtures/de.yaml` — 18 new entries: 15 broader-class `expect_clean: true` + 1 DE LOCATION held-out + 1 long-doc anchor + 1 code-switched (F-M); top-of-section extension-rule comment per F-G.
- `tests/conftest.py` — F-O clarifying NOTE on `SAMPLE_PRESIDIO_RESULTS` (0.85 score literals are backend-agnostic).
- `README.md` — code-switched-text note + single-arch build path (F-H) + HF token plumbing (F-L).
- `docs/v1-feature-spec.md` — code-switched-text limitation subsection under Feature 4.
- `docs/presidio-integration.md` — `MultiNlpEngine` as production default; alternatives retained.

**SDD artifacts (Redakt):**

- `SDD/research/RESEARCH-007-transformers-nlp-backend.md`
- `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md`
- `SDD/requirements/SPEC-007-transformers-nlp-backend.md`
- `SDD/adr/0001-presidio-per-language-nlp-engine.md`
- `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md`
- `SDD/reviews/REVIEW-007-transformers-nlp-backend-20260506.md`
- `SDD/reviews/CRITICAL-IMPL-transformers-nlp-backend-20260506.md`
- `SDD/orchestration/progress.md` (per-step entries appended)
- `SDD/orchestration/counters/4*-*-*.md` (subagent counter audit trail)

**Local-only (gitignored) artifacts:**

- `reports/calibration-007-before.md`, `reports/calibration-007-after.md`
- `reports/req-011-recognizer-diffs.md`
- `reports/req-013-tamper.md` (F-A / F-N tamper-test transcript)
- `reports/req-015-probe.md`

---

## Technical Implementation Details

### Architecture Decisions

- **Custom `MultiNlpEngine` subclass (deep module per MODULE-001).** Per-language dispatch happens inside the engine; callers continue to invoke `nlp_engine.process_text(text, language)` unchanged. Information-hiding boundary is the per-language sub-engine selection. Public surface mirrors `NlpEngine`'s contract: `__init__(models, ner_model_configuration=None)`, `load()`, `is_loaded()`, `process_text(text, language)`, `process_batch(texts, language, **kw)`, `is_stopword`, `is_punct`, `get_supported_entities`, `get_supported_languages`, `get_nlp(language)`.
- **Engine-name `multi` registration via `NlpEngineProvider`.** New engine name is added to the default `nlp_engines` tuple. `ConfigurationValidator.validate_nlp_configuration` accepts the `multi.yaml` shape via the existing open-schema validator; per-row `engine` and `revision` keys are validated downstream by `_validate_multi_row` (build-time) and `MultiNlpEngine._validate_row` (runtime). F-E docstring annotation calls out the downstream-validation contract for future schema-tightening.
- **Two-phase startup contract (Behavior B).** Presidio's `AnalyzerEngineProvider.create_engine()` runs synchronously during Flask app initialization; if `MultiNlpEngine.load()` raises, the import fails and the HTTP server never binds. Healthcheck interprets connection-refused as "not ready, keep retrying" until `start_period` (30s) elapses. No `app.py` modification was required.
- **Digest manifest as supply-chain trust anchor.** `multi.model_digests.json` lists per-file SHA-256 for every weight/tokenizer/config artifact at the pinned revision. `install_nlp_models.py` reads on every build, recomputes digests, fails the build on mismatch. Atomic write via `os.replace` after `.tmp` (F-I).
- **Two-repo discipline.** Fork-side diffs are wrapped in `# === redakt: ... ===` markers per Implementation Constraints; `.presidio-pin` (F-J) records the fork branch + commit SHA range to be updated alongside future Redakt commits that touch the analyzer integration.

### Key Algorithms

- **`MultiNlpEngine.load()` one-shot retry-after-failure (chunk 4e F-F).** `_load_call_count` increments AFTER the sub-engine load loop completes successfully, so a transient failure can be retried in-process. Production behavior on the happy path is unchanged (`_load_call_count == 1` after a clean load); the deployed shape (Docker exits → restart policy) still uses process-restart as the documented recovery path. Removes a footgun for SDK / single-process embedders.
- **Four-bar stopping condition (REQ-006, entity-conditional Bar 2 per Amendment 2026-05-06).** (1) Negative bar — all `expect_clean` and `issubset` fixtures green; (2) Held-out positive bar — for every DE-covered entity, at least one positive fixture surfaces the expected entity in `found` (DE LOCATION; DE DATE_TIME excluded by amendment); (3) Score-distribution annotation per tuned threshold (N/A — no thresholds moved); (4) Reproducibility within ±0.05 (trivial — no movement).
- **Engine-swap fingerprint detection (REQ-016).** DE-routed transformer engine emits LOCATION at score ≥ 0.95; EN-routed spaCy emits PERSON within 0.01 of 0.85 (`ner_strength` constant). Cross-routed probes (DE text via `language: en`, EN text via `language: de`) produce qualitatively different score profiles, which the integration tests exploit to detect routing inversions.

### Dependencies

External / library dependencies introduced or sharpened:

- **Hugging Face Hub** (build-time only) — `huggingface_hub.snapshot_download` for transformer weights; pinned revision per REQ-013; manifest is the trust anchor.
- **`transformers`** Python package (already required by Presidio's `transformers` extra).
- **`torch`** (CPU-only).
- **`sentencepiece`** + **`protobuf`** — required by `xlm-roberta-large-finetuned-conll03-german` tokenizer.
- **`spacy_huggingface_pipelines`** (Presidio dep; provides `hf_token_pipe`).
- **`de_core_news_sm`** spaCy model (~14 MB, baked at image build).
- **`en_core_web_lg`** spaCy model (already baked; unchanged).

No new Redakt-side runtime dependencies. `pyproject.toml` only adds test-tree exclusion entries (`--ignore=tests/contracts`, `--ignore=tests/integration`).

---

## Subagent Delegation Summary

Counter files retained at `SDD/orchestration/counters/` for full audit trail. Total subagents: **26** across phases 2 (research/planning helpers), 3 (planning), and 4 (implementation chunks 1A through 4f).

| Phase | Counter file prefix | Count |
| --- | --- | --- |
| Phase 2 (research) | `2a-*`, `2b-*`, `2c-*`, `2d-*` | 5 |
| Phase 3 (planning) | `3a-*`, `3b-*`, `3c-*`, `3c-fix-*`, `3d-*`, `3e-*`, `3e-amend-*` | 7 |
| Phase 4a (implementation chunks) | `4a-1A`, `4a-1B`, `4a-1B-commit`, `4a-2`, `4a-2-retry`, `4a-3`, `4a-4`, `4a-5` | 8 |
| Phase 4b (code review) | `4b-1` | 1 |
| Phase 4c (review fix) | `4c-1` | 1 |
| Phase 4d (critical implementation review) | `4d-1` | 1 |
| Phase 4e (critical fix) | `4e-1` | 1 |
| Phase 4f (this finalization) | `4f-1` | 1 |
| **Total** | | **26** |

No bail-outs. Every counter file shows Reads ≤ ceiling and Nested subagents ≤ 4.

---

## Quality Metrics

### Test Sweep at Step 4f Finalization

| Suite | Count | Pass | Notes |
| --- | --- | --- | --- |
| Redakt unit + integration (`tests/`) | 350 | 350 | Default suite, excludes live-stack via `pyproject.toml addopts`. |
| Redakt eval fixtures (`tests/eval/`) | 59 | 59 | 41 + 15 broader-class + 2 REQ-009b + 1 code-switched. |
| Redakt contracts (`tests/contracts/`) | 15 | 15 | OpenAPI diff (2) + API shape (5) + recognizer floor (8). |
| Redakt integration (`tests/integration/`) | 3 | 3 | `language: auto` × {DE, EN, swap-detect}. |
| Presidio fork `tests/test_multi_nlp_engine.py` | 19 | 19 | 15 + 2 FAIL-002 + 2 chunk-4c. |
| Presidio fork `tests/test_install_nlp_models_multi.py` | 12 | 12 | 7 FAIL-005 + 5 tamper / round-trip. |
| **Total** | **458** | **458** | 100% pass. |

### Test Type Coverage

- **Unit tests:** PRESENT (chunk 1A `MultiNlpEngine` 15 + chunk 5 install dispatcher 7 + chunk 4e tamper 5 + chunk 5 FAIL-002 2 + chunk 4c REQ-013 runtime 2).
- **Integration tests:** PRESENT (chunk 4 `tests/integration/test_auto_detect_routing.py` 3).
- **Contract tests:** PRESENT (chunk 3 OpenAPI + API shape + recognizer floor 15).
- **Eval fixtures:** 59 (chunk 2 retry + chunk 4e F-M).
- **E2E / Playwright tests:** **N/A** — feature is API-side only; no UI / HTMX / JS changes per REQ-012 (frontend explicitly out of scope per CLARIFICATION Q5d).

---

## Deployment Readiness

### Environment Variables

No new Redakt runtime environment variables. The feature is config-driven via `multi.yaml`; per-language `engine` / `model_name` / `revision` are baked at image build via `install_nlp_models.py`.

Operator-facing build-time options (documented in README per F-H + F-L):

- `DOCKER_DEFAULT_PLATFORM=linux/arm64` (or `linux/amd64`) — pin single-arch build to avoid the ~36 GB multi-arch inflation on macOS.
- `HUGGINGFACE_HUB_TOKEN` (or `HF_TOKEN`) — optional, build-time only. Pass via BuildKit secret: `docker buildx build --secret id=hf_token,env=HUGGINGFACE_HUB_TOKEN ...`. Default build path is anonymous; production deploys that rebuild frequently should configure the token.

### Configuration Files

- `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml` — per-language NLP config.
- `presidio/presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json` — 14 SHA-256 entries (REQ-013 trust anchor).
- `docker-compose.yml` — retargeted to `Dockerfile.multi` with `start_period: 30s`.
- `.presidio-pin` (Redakt repo root) — fork branch + commit SHA range for two-repo SHA traceability.

### Database / Schema Changes

**None.** Redakt is stateless by design (CLAUDE.md: backend never persists PII). No DB migration, no schema change.

### API Contract

**Preserved verbatim.** REQ-010 + REQ-010a + REQ-011 contract gates assert byte-identical envelopes, headers, and recognizer-registry floor. `git log main..HEAD -- src/redakt/` is empty for SDD-007 — zero changes to Redakt source under `src/redakt/`. Only configuration (`docker-compose.yml`), dev tooling (`pyproject.toml`), tests, fixtures, and docs changed on the Redakt side.

---

## Monitoring & Observability

### Latency Baselines (PERF-001)

Captured at chunk 4 (median of N=5 warm requests):

| Anchor | Text | Median latency |
| --- | --- | --- |
| Short bare-noun (DE) | `Personalausweis` | 0.079 s |
| Sentence-context PII (EN) | `My name is John Smith.` | 0.005 s |
| Long-document anchor (DE 557 tokens) | REQ-009b long-doc fixture | 1.262 s |

The DE long-document anchor sits inside the RESEARCH-007 §4 / CLARIFICATION-007 Q4 0.5–3 s expectation envelope. No SLO is set per spec.

### Model-Load-Once Invariant Log

`MultiNlpEngine.load()` emits one structured log line per sub-engine: `LOADED <model> at <ts>`. Captured at chunk 4:

```
13:04:58  gunicorn boot
13:05:01.6  LOADED en_core_web_lg
13:05:05.7  LOADED de_core_news_sm
13:05:05.7  LOADED FacebookAI/xlm-roberta-large-finetuned-conll03-german
            recognizer registry load
            first /health 200
```

Each `LOADED` line appears exactly once and all three appear before the HTTP server begins serving.

### `/health` Probe Behavior

- Connection-refused while `MultiNlpEngine.load()` runs (Behavior B).
- 200 only after all sub-engines report loaded.
- Process exits non-zero on `load()` raise; restart policy retries.
- Healthcheck `start_period: 30s` matches REQ-014 formula `max(30s, ceil(2 × 9s))` with `interval: 15s` × `retries: 20 = 5 min` post-`start_period` headroom for colder-cache scenarios.

---

## Rollback Plan

### Fast rollback (revert to spaCy multilingual)

1. **Redakt repo:** `git revert` the chunk-1B and chunk-4e `docker-compose.yml` updates (or directly edit `dockerfile: Dockerfile.transformers`, `args.NLP_CONF_FILE: presidio_analyzer/conf/spacy_multilingual.yaml`, `start_period: 90s`).
2. **Presidio fork:** No revert required for fork — the `MultiNlpEngine` class and `multi.yaml` are inert when `docker-compose.yml` does not select them via `dockerfile` + `NLP_CONF_FILE`. The fork can stay on `feature/redakt-007-multi-nlp-engine`.
3. **Image rebuild:** `docker compose build presidio-analyzer && docker compose up -d presidio-analyzer`. Healthcheck reaches green within `start_period`.

### Full rollback (delete the feature)

1. **Redakt repo:** `git revert` chunks 1B, 2-retry, 3, 4, 5, 4c, 4e on `feature/007-transformers-nlp-backend`. Delete `tests/contracts/`, `tests/integration/`, the new fixtures in `tests/eval/fixtures/de.yaml`, the `.presidio-pin` file. Restore `docker-compose.yml` and `pyproject.toml` to main-branch contents.
2. **Presidio fork:** Branch revert via `git checkout main && git branch -D feature/redakt-007-multi-nlp-engine`. The fork-side commits are isolated to a feature branch; main is unchanged.
3. **Image rebuild:** As above.

No data migration is required for either rollback path. Backend is stateless; no PII at rest; client-side PII mappings are short-lived per the Redakt design.

---

## Lessons Learned

### Option A pivot (Spec Amendment 2026-05-06)

The original chunk 2 attempt (compaction file `SDD/orchestration/compacted/implementation-compacted-2026-05-06_13-45-37.md`) bailed out at iteration 0 with a deliberate spec-level handoff: REQ-006 Bar 1 (`T > 0.85`) and Bar 2 (admit a DE held-out DATE_TIME positive at score ≤ 0.8) were conjunction-impossible for `DATE_TIME` because xlm-roberta CoNLL-03 has no DATE label and `DateRecognizer` ceilings at 0.6 / 0.8. Pablo selected Option A: drop the DE DATE_TIME held-out positive, keep DE LOCATION, rewrite Bar 2 entity-conditional. Lesson: **early identification of conjunction-impossible spec constraints saves a calibration cycle.** When a calibration bar's preconditions can't be met by model design, the spec needs an amendment, not iteration on knobs.

### BuildKit layer export hang on virtiofs

Chunk 1B's image build completed all 13 BuildKit RUN/COPY steps but stalled at layer export due to virtiofs i/o latency on the external-drive Docker context. Chunk 2's first build attempt re-triggered from cache (no model re-download) and completed the export cleanly. Lesson: **on macOS Docker Desktop with virtiofs storage, expect non-trivial layer-export time on the first build of a multi-GB image.** Subsequent builds amortize the cost via the BuildKit cache.

### Runtime revision-pin gap discovered post-review

The chunk 1B implementation correctly forwarded `revision` to `snapshot_download` AND to build-time `from_pretrained` calls. But upstream Presidio's `TransformersNlpEngine.load()` calls `from_pretrained(model_name)` without `revision=` — the runtime path used the cached snapshot's "main" alias. In the baked-image case there's exactly one cached snapshot per repo_id, so it resolved to the pinned revision in practice — but the contract was hollow. The Step 4b code review caught this as F-1 MEDIUM and chunk 4c landed a small two-file fork patch (5 LoC of production code). Lesson: **build-time pinning ≠ runtime pinning for transformer-pipeline configs.** Both call sites need explicit `revision=` forwarding.

### Empty digest manifest committed as `{}` placeholder

Chunk 1B committed `multi.model_digests.json` as the literal one-line empty placeholder `{}`. The dispatcher's `_load_digest_manifest` treats empty as "first-build baseline mode," meaning every build against the committed state writes a fresh baseline rather than verifying. Step 4d (critical review F-A) caught this as a HIGH-severity finding — REQ-013's headline supply-chain trust anchor was structurally inert in source. Step 4e populated the manifest from the running analyzer container (14 SHA-256 entries) and captured the tamper-test transcript at `reports/req-013-tamper.md`. Lesson: **for SDD specs that claim "verified once during implementation," require captured artifacts (transcripts, populated config files), not just chunk-tracker prose.** Step 4d's adversarial-generalist lens (vs. Step 4b's spec-aligned lens) caught the artifact-vs-prose gap.

### Step 4d adversarial review was load-bearing

Step 4b code review APPROVED the implementation with only 1 MEDIUM + 3 LOW findings — all spec-aligned and risk-tiered. Step 4d's critical review surfaced 1 HIGH + 4 MEDIUM + 5 LOW that 4b had under-weighted. The HIGH was the empty-manifest finding above; the MEDIUMs included `start_period: 90s` post-hoc rationalization (F-D), broader-class extension rule documentation-only (F-G), multi-arch image weight (F-H), partial-load process-exit not integration-tested (F-K), tamper-test not durably captured (F-N). Lesson: **two distinct review lenses (spec-aligned vs. adversarial-generalist) are complementary, not redundant.** SDD-007 would have shipped with REQ-013 structurally inert without Step 4d.

---

## Next Steps

- **Ready for `/sdd:commit` (Step 4i).** Step 4f is documentation-finalization only. The orchestrator runs the final commit wrapping the Step 4f deliverables (this summary + tracker + spec amendment + glossary + progress) per the SDD commit-style preference (no Claude attribution).
- **LangSmith eval scaffolding follows at Step 4g.** Per the SDD-flow integration plan, regression-eval-capture runs after 4f; this summary's Quality Metrics + Latency Baselines provide the regression anchors.
- **Future maintenance hooks** are documented in IMPLEMENTATION-PLAN's "Future maintenance" section: REQ-009 broader-class extension rule, single-arch image build, FAIL-002 partial-load process-exit verification, REQ-013 tamper-test evidence, HF Hub token plumbing, two-repo SHA traceability via `.presidio-pin`.

---

**End of IMPLEMENTATION-SUMMARY-007.**
