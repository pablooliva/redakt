# Implementation Compaction — transformers-nlp-backend — Step 4a chunks 1A/1B — 2026-05-06 12:44:58

## Session Context

- **Compaction trigger:** Environmental blocker (Docker BuildKit layer export hung 30+ min on `/Volumes/Crucial Data/...` external-drive virtiofs mount). NOT a safety-net trip; not a code defect.
- **Implementation focus:** SDD-007 transformers-nlp-backend, Step 4a, just past chunk 1B partial-commit.
- **Specification reference:** `SDD/requirements/SPEC-007-transformers-nlp-backend.md`.
- **Session duration:** ~2.5 hours from research start to chunk 1B commit; ~30 min stuck on layer export thereafter.

## Recent Changes

**Presidio fork** (branch `feature/redakt-007-multi-nlp-engine`):

- `1070180b` (chunk 1A): `MultiNlpEngine` class + tests (15/15 passing)
  - `presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py` (~285 LOC)
  - `presidio-analyzer/presidio_analyzer/nlp_engine/__init__.py` (export)
  - `presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py` (register `multi`)
  - `presidio-analyzer/tests/test_multi_nlp_engine.py` (15 tests, mock-only)
  - `presidio-analyzer/tests/conftest.py` (skip branch for `multi` in session-scoped `nlp_engines` fixture)

- `d604514` (chunk 1B partial): Multi engine config + Docker plumbing
  - `presidio-analyzer/install_nlp_models.py` (engine_name `multi` branch with HF revision pinning + SHA-256 digest manifest read/write/verify)
  - `presidio-analyzer/Dockerfile.multi` (HEALTHCHECK wired to `/health`)
  - `presidio-analyzer/presidio_analyzer/conf/multi.yaml` (en spaCy `en_core_web_lg`, de transformers `xlm-roberta-large-finetuned-conll03-german` @ revision `1fbcc7a00a69ce5ab754623154a8e9cc6ba868e2` + auxiliary spaCy `de_core_news_sm`)
  - `presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json` (placeholder `{}` — first-build mode, populates on first successful build)
  - `presidio-analyzer/scripts/smoke_test_multi.py` (offline validation script)

**Redakt** (branch `feature/007-transformers-nlp-backend`):

- `de077bf`: SDD-007 research artifacts (CLARIFICATION, RESEARCH, ADR 0001, glossary, critical review)
- `d484d8a`: SDD-007 planning (SPEC, panel reviews iter 1+2, critical-spec review)
- `0c08ed2`: SDD-007 chunk 1A tracker (IMPLEMENTATION-PLAN init + chunk 1A subsection)
- `3fc10b1`: SDD-007 chunk 1B tracker (`docker-compose.yml` retargeted to `Dockerfile.multi`; chunk 1B partial-commit subsection)

## Implementation Progress

- **Completed (per IMPLEMENTATION-PLAN):**
  - REQ-001 (MultiNlpEngine class): Complete
  - REQ-002 (engine name registration): Complete
  - REQ-003 (multi.yaml): Complete
  - REQ-004 (install_nlp_models.py extension): Complete (build's compute steps verified end-to-end)
  - REQ-005 (Dockerfile.multi + docker-compose retarget): Complete (image layer export deferred)
  - REQ-005a (two-phase startup `/health`): Complete (Behavior B — Presidio's eager engine load during Flask app init blocks the bind until `MultiNlpEngine.load()` returns; HEALTHCHECK in Dockerfile.multi probes `/health`)
  - REQ-013 (HF model integrity / digest manifest): Complete (revision pin wired, manifest read/write/verify implemented; placeholder `{}` baseline populates on first successful image tag)

- **Blocked / pending:**
  - **Image build tagging** — BuildKit step #19 "exporting layers" hung 30+ min. Build's compute steps (1–18) all completed successfully with model downloads + digest baseline write. The new image is NOT tagged in the local registry; the running `redakt-presidio-analyzer-1` container is the OLD spaCy multilingual config (4 hours old).

  - **REQ-006 / REQ-007 (threshold calibration) — chunk 2 NOT STARTED:** depends on a tagged, runnable analyzer image. Calibration's four-bar stopping condition is well-defined (negative + held-out positive + score-distribution annotation + reproducibility ±0.05) and autonomously executable once the stack runs.

  - REQ-008/009/009b (calibration corpus + fixtures) — chunk 3 NOT STARTED.
  - REQ-010/010a/011 (API contract gates + recognizer registry floor) — chunk 3 NOT STARTED.
  - REQ-012/014/015/016 (code-switched docs + auto-detect routing test + cold-start measurement) — chunk 4 NOT STARTED.
  - REQ-017 (Presidio upstream merge gate) — chunk 5 NOT STARTED.
  - All FAIL-001..006, PERF-001..003, SEC-001..004, PRIV-001..002, REL-001..003 — NOT STARTED.

## Tests Status

- **Chunk 1A unit tests:** 15/15 passing (`uv run pytest tests/test_multi_nlp_engine.py -v` from `presidio/presidio-analyzer/`).
- **Image build smoke (Dockerfile.multi):** all 13 compute steps green; layer export hung. No image tagged.
- **No integration / E2E tests run** — depends on running stack.
- **No calibration run** — depends on running stack.

## Critical Learnings

- **Presidio's stock `NlpEngineProvider` does NOT support per-language engine type mixing.** RESEARCH-007 §3 documented this; chunk 1A's `MultiNlpEngine` is the workaround. Chunk 1A's 15 unit tests validate the dispatch contract.
- **xlm-roberta-large-finetuned-conll03-german is empirically validated** against 10 broader-class German nouns (zero false positives) per RESEARCH-007 §4.5 (live HF probe at fix-step 2d).
- **`mschiesser/ner-bert-german` was disqualified** by live probe (5/10 broader-class phrases mis-tagged as PER 0.793–0.998) — DO NOT use as a fallback.
- **`Davlan/bert-base-multilingual-cased-ner-hrl` was promoted to A/B fallback** (live-clean, smaller, no `sentencepiece` dep).
- **`flair/ner-german-large` is incompatible** with Presidio's `hf_token_pipe` (flair-native weights). Don't try.
- **`expect_clean: true` is supported by `tests/eval/test_calibration.py:46-50`** (verified in research §8.2 — no harness extension needed for chunk 3).
- **REQ-006 four-bar stopping condition** (negative + held-out positive + score-distribution annotation + reproducibility ±0.05) is mechanical — autonomously executable.
- **Two-repo discipline** is being honored — Presidio fork is at `./presidio/` with its own git; Redakt is at the project root. The Presidio gitlink in Redakt is intentionally left dirty.
- **External-drive mount is hostile to BuildKit layer export.** Project is on `/Volumes/Crucial Data/...` which mounts via virtiofs in Docker Desktop. Layer export hung repeatedly with no log progress for 30+ min.

## Critical Review Status

- Research critical review: `SDD/reviews/CRITICAL-RESEARCH-transformers-nlp-backend-20260506.md` — all 2 HIGH + 4 MEDIUM + 4 LOW resolved at Step 2d (live HF probes).
- Spec panel review iter 1: `SDD/reviews/PANEL-SPEC-transformers-nlp-backend-20260506.md` — 4 MEDIUM resolved at Step 3c iter 1; 6 LOW deferred and resolved at Step 3e.
- Spec panel review iter 2: `SDD/reviews/PANEL-SPEC-transformers-nlp-backend-20260506-iter2.md` — 0 MEDIUM, 2 LOW resolved at Step 3e.
- Spec critical review: `SDD/reviews/CRITICAL-SPEC-transformers-nlp-backend-20260506.md` — 4 MEDIUM + 7 LOW resolved at Step 3e (incl. MODULE-001 Risk medium → HIGH).
- Implementation critical review (Step 4d) — NOT YET RUN; depends on chunks 2–5 completing.

## Critical References

- Spec: `SDD/requirements/SPEC-007-transformers-nlp-backend.md` (~890 lines)
- Research: `SDD/research/RESEARCH-007-transformers-nlp-backend.md` (~918 lines)
- ADR: `SDD/adr/0001-presidio-per-language-nlp-engine.md`
- IMPLEMENTATION-PLAN: `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md`
- CLARIFICATION: `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md`

## Next Session Priorities

**Essential Files to Reload:**

- `SDD/requirements/SPEC-007-transformers-nlp-backend.md` (entire, but esp. REQ-006 / REQ-007 / REQ-008 / REQ-009 / REQ-009b / REQ-010 / REQ-010a / REQ-011 for chunks 2 + 3)
- `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md`
- `SDD/orchestration/progress.md`
- `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml`
- `tools/calibration_report.py`
- `src/redakt/config.py:14` (where `entity_score_thresholds` is defined)
- `tests/eval/fixtures/de.yaml` and `tests/eval/test_calibration.py:46-50`

**Current Focus:**

- Chunk 2 (threshold calibration + REQ-006/007/008) and chunk 3 (eval fixtures + REQ-009/009b/010/010a/011) are the next implementation chunks.
- Chunk 2 cannot start until the analyzer image is built and the new container is running.

**Implementation Priorities (when resumed):**

1. **Get the analyzer image tagged.** Three viable paths to surface to Pablo:
   - **(a)** Move the project to a non-external-drive path (e.g., `~/Code/redakt/`) and rebuild — virtiofs slowness on `/Volumes/Crucial Data/` is the root cause. Internal SSD bind-mounts complete layer export in seconds for ~3 GB images.
   - **(b)** Run `docker compose build presidio-analyzer` overnight on the current path — buildkit's compute steps already cached, only the layer flush remains. Wall-clock can stretch but should eventually complete.
   - **(c)** Bypass Docker for chunk 2 only: modify `tools/calibration_report.py` to accept an in-process `AnalyzerEngine` instance instead of HTTP calls to localhost:8000. Calibration values would be identical because Presidio's behavior is engine-instance-agnostic. Adds scope outside the SPEC; would need an addendum REQ. Not preferred.
2. After image is tagged: `docker compose up presidio-analyzer` → confirm `/health` returns 200 → run `tools/calibration_report.py --raw --out` → tune REQ-006 / REQ-007 values per the four-bar stopping condition.
3. Chunk 3: add 15 `expect_clean: true` fixtures (REQ-009) + 3 held-out positive/long-doc fixtures (REQ-009b) → run `uv run pytest tests/eval/` → expect 59/59 PASS.
4. Chunks 4 + 5 unblocked once chunk 2 + 3 land.

**Specification Validation Remaining:**

- [ ] REQ-006, REQ-007, REQ-008 (chunk 2)
- [ ] REQ-009, REQ-009b, REQ-010, REQ-010a, REQ-011 (chunk 3)
- [ ] REQ-012, REQ-014, REQ-015, REQ-016 (chunk 4 — edge cases + auto-detect routing test + cold-start measurement)
- [ ] REQ-017 (chunk 5 — Presidio upstream merge gate)
- [ ] FAIL-001 through FAIL-006 (chunks 4–5)
- [ ] PERF-001 / PERF-002 / PERF-003 (chunk 5)
- [ ] SEC-001 / SEC-002 / SEC-003 / SEC-004 (chunk 5)
- [ ] PRIV-001 / PRIV-002 (chunk 5)
- [ ] REL-001 / REL-002 / REL-003 (chunk 5)
- [ ] EDGE-001 through EDGE-008 (verified by tests in chunks 3–4)
- [ ] Step 4b (code review with risk-tiered depth — MODULE-001 is HIGH)
- [ ] Step 4d (implementation critical review)
- [ ] Step 4f (implementation completion)
- [ ] Step 4g (LangSmith eval scaffolding — `eval_required: true` in spec frontmatter)

## Other Notes

- **Resume command pattern:** the user runs `/sdd-flow continue` after the Docker image is tagged. Phase Detection priority will see the latest progress block as `## Awaiting Environment Decision` and re-prompt with the resume options. If the user resolves the environment by moving the project, they should `git -C presidio` work just stays on the `feature/redakt-007-multi-nlp-engine` branch (no rebase needed).
- **Don't blow away the BuildKit cache** before resuming — it has all 13 compute steps including the ~2 GB transformer download. Re-running build from cache will skip straight to layer export, where the hang lives. Cache reset would mean re-downloading ~3 GB of models.
