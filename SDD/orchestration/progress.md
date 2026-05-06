# SDD Flow — Feature 007: Transformers NLP Backend

**Started:** 2026-05-06
**Mode:** Autonomous (per user preference; auto mode active)
**Branch:** feature/007-transformers-nlp-backend

## Resolved Identifiers
- `[###]` = `007`
- `[feature-name]` = `transformers-nlp-backend`
- `[YYYY-MM-DD]` = `2026-05-06`

## Step 0 — Scope Assessment

In progress: spawning general-purpose subagent.

**Verdict (2026-05-06):** Single SDD cycle. One architectural concern (NLP backend swap) executed via YAML config + Dockerfile selection in `presidio/presidio-analyzer/`, plus a calibration/threshold pass against the existing 41 eval fixtures. No API contract change, no new layers; cross-cutting decision is captured in a single ADR. No decomposition file written.

## Step 1.5 — Pre-Research Clarification (Resolved)

`/research-clarify` ran interactively (2026-05-06). Six branches walked: English non-regression bar, German over-detection scope, plan B if no model satisfies both languages, cost envelope, scope edges, code-switching.

Key resolved decisions:

- **Q1:** English non-regression = detection-set non-regression (option #2). Score noise inside that envelope is OK; nothing previously flagged may be dropped.
- **Q2:** Exit criterion is the **broader class** of German identity/document/insurance common nouns (not just the 5 named). Those nouns should produce **zero entity flags** of any kind.
- **Q3:** Plan B = **asymmetric routing** (option C). Transformers for `de`, spaCy for `en`. Two engines coexist via `NlpEngineProvider`'s per-language engine map.
- **Q4:** **No hard caps** on image size, latency, or cold-start. Research selects on accuracy.
- **Q5:** New CI fixtures for de class: in scope. Calibration corpus expansion: in scope. Global threshold knob retune: in scope. Frontend: out of scope. Recognizer registry: existing floor preserved.
- **Q6:** Code-switched text: accept the limitation (option i). Document and move on.

Artifact: `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md` — Status: Resolved.

Open questions are research-resolvable (Presidio API capabilities, model selection, threshold values), not user-decision-blocked. **Gate satisfied.** Resuming autonomous flow at Step 2 (Research).

## Step 2 — Research Phase

### Step 2a — Research investigation subagent (in progress)

Spawned 2026-05-06 10:01:17. Counter file: `SDD/orchestration/counters/2a-1-2026-05-06_10-01-17.md`. Outputs: `SDD/research/RESEARCH-007-transformers-nlp-backend.md`.

### Step 2a — Research investigation findings

Completed 2026-05-06. Counter at completion: Reads 10/10 (limit reached but not exceeded), Nested subagents 0/4 (none used; substituted Bash `cat` for compact-file batch reads and WebFetch for HF model surveys, neither of which counts toward the safety net). Single advisor consultation used to course-correct toward the model survey before writing.

**Deliverable:** `SDD/research/RESEARCH-007-transformers-nlp-backend.md` (~1700 lines). 18 sections covering all 14 research targets in the prompt, plus an executive findings section up top.

**Key findings planning must internalize:**

1. **`NlpEngineProvider` cannot mix engine types per language** (confirmed at `presidio/.../nlp_engine_provider.py:87-114`). The CLARIFICATION's stated implementation — "Two engines coexist via `NlpEngineProvider`'s per-language engine map" — is wrong as written. The design intent (Q3 C asymmetric routing) is unchanged; the wiring needs revision. Three viable options documented, recommendation = Option C (custom `MultiNlpEngine` subclass inside the Presidio fork, ~150 LoC).
2. **Recommended German model: `xlm-roberta-large-finetuned-conll03-german`.** flair/ner-german-large would have been the accuracy winner (F1 92.31) but is flair-native, incompatible with Presidio's `hf_token_pipe`. Fallback A/B candidate: `mschiesser/ner-bert-german` (F1 0.8829, wikiann-de training).
3. **Eval suite is structurally weak at over-detection** — `expect.issubset(found)` (`tests/eval/test_calibration.py:55`) only catches missing entities. The headline bug (Personalausweis -> PERSON(0.85)) is invisible in the current 41/41 PASS line. Adding `expect_clean: true` fixtures for the broader class is the only mechanism that surfaces the fix.
4. **Per-entity threshold filter lives in Redakt** (`src/redakt/utils.py:97-110`), shape unchanged (`dict[str, float]`). Only values + `low_score_entity_names`/multiplier need empirical re-tuning.
5. **Models baked at image build time** via `install_nlp_models.py`; not hot-reload-friendly. Per Q4 (no caps) this is acceptable. Documented rationale + alternative (`TRANSFORMERS_CACHE` mount).
6. **No prior ADR exists** (`SDD/adr/` is empty). This becomes ADR 0001.

**Open questions resolved:**
- open Q1 (per-language engine map) — NO; workaround documented.
- open Q2 (lemma-aware enhancers under transformers) — works as-is because TransformersNlpEngine disables spaCy parser+ner but keeps the lemmatizer.
- open Q3 (low_score_entity_names values) — explicitly deferred to calibration (empirical, not a research output).
- open Q4 (model selection) — resolved.

**Glossary candidates** consolidated in §14 of the research document; ready for `research-complete` to land in `SDD/UBIQUITOUS_LANGUAGE.md`.

**No code changes, no tests, no git operations performed.** Read-only investigation as required.

### Step 2a — Research-complete subagent

Spawned 2026-05-06 10:16:16. Counter file: `SDD/orchestration/counters/2a-2-2026-05-06_10-16-16.md`. Validated `RESEARCH-007-transformers-nlp-backend.md` against the `/sdd:research-complete` checklist. Final counter: Reads 4/10, Nested subagents 0/4.

**Validation result:** Research document is complete. All required sections covered with file:line citations:

- §1 System Data Flow — entry points, transformations, external deps, integration points all anchored.
- §11 Stakeholder Mental Models — Pablo (operator + engineer + end-user roles), AI agents covered; Support marked NA with rationale (internal tool, sole stakeholder).
- §12 Production Edge Cases — historical issues from `reports/post-fix-2.md`, support patterns NA (internal tool), error log patterns documented.
- §15 Files That Matter — core logic, test-coverage gaps explicitly called out (issubset weakness in §8.2), configuration files indexed.
- §16 Security — auth/authz documented as unchanged, data-privacy invariants preserved, input validation unchanged.
- §17 Testing Strategy — unit, integration, edge cases (German common-noun fixtures, code-switched text) all defined.
- §18 Documentation Needs — user, developer, configuration documentation requirements specified.

**No checklist gaps required edits to the research document.** It stands as is.

**Glossary created:** `SDD/UBIQUITOUS_LANGUAGE.md` seeded with 12 terms grouped by domain area (Entities, Actions, States/configuration, Roles, Events). Sources: CLARIFICATION-007 "Glossary candidates" + RESEARCH-007 §14, plus closely-related code-grounded terms (`default score threshold`, `low_score_entity_names / low_confidence_score_multiplier`, `operator`). Every entry cites a file:line or research/clarification section. Events bucket is intentionally empty; will accrue with workflow features.

Research phase complete. RESEARCH-007-transformers-nlp-backend.md finalized. Glossary created. Ready for `/planning-start`.

### Step 2b — ADR capture (cross-cutting-adr, Trigger C, autonomous)

Spawned 2026-05-06 10:19:44. Counter file: `SDD/orchestration/counters/2b-1-2026-05-06_10-19-44.md`. Final counter: Reads 3/10, Nested subagents 0/4. No advisor consultation needed — scope test was unambiguous (the per-language NLP engine choice binds all future PII-detection work, future language additions, the threshold-tuning regime, and analyzer image build/deployment shape) and the ADR template is fully grounded in RESEARCH-007 evidence.

**Scope-test verdict:** PASS. ADR-worthy. Per CLARIFICATION-007's explicit framing, captured as **one combined ADR** covering both (a) the engine architecture (per-language, single container, custom `MultiNlpEngine` subclass in the Presidio fork — chosen over Presidio's stock provider because RESEARCH-007 §3.1 confirmed `NlpEngineProvider` cannot mix engine types per language) and (b) the model choices (English: keep spaCy `en_core_web_lg`; German: `xlm-roberta-large-finetuned-conll03-german`, with `mschiesser/ner-bert-german` documented as the calibration A/B fallback).

**Files written:**

- `SDD/adr/0001-presidio-per-language-nlp-engine.md` — Status: Accepted (2026-05-06). Covers Context, Decision, six Alternatives Considered (Option A transformers-only / Option B two analyzer containers / Option D drop spaCy / flair-ner-german-large / Davlan-bert-base-multilingual-cased-ner-hrl rejections, plus the `mschiesser/ner-bert-german` documented-fallback), Consequences (positive / negative / neutral), and References. Every claim cites a RESEARCH-007 §section or file:line; no fabricated evidence.
- `SDD/adr/README.md` — index regenerated per the cross-cutting-adr skill template; lists ADR 0001 in the Index table.

**ADR identity:**

- Number: 0001 (first ADR in `SDD/adr/`; directory was empty before this step, confirmed via `ls`).
- Slug: `presidio-per-language-nlp-engine`.
- Tags: `cross-cutting, nlp, presidio, pii-detection`.
- Supersedes / superseded_by: null.

**No code changes, no tests, no git operations performed.** ADR-write only. Ready for `/planning-start`.

### Step 2c — Research critical review

Spawned 2026-05-06 10:24:30. Counter file: `SDD/orchestration/counters/2c-1-2026-05-06_10-24-30.md`. Final counter: Reads 8/10, Nested subagents 0/4.

**Output:** `SDD/reviews/CRITICAL-RESEARCH-transformers-nlp-backend-20260506.md`.

**Severity counts:** 2 HIGH, 4 MEDIUM, 4 LOW.

**Top findings:**

1. **[HIGH] `install_nlp_models.py` build-pipeline gap.** The script's `_download_model` only branches on `spacy | stanza | transformers` and raises `ValueError` on anything else (`install_nlp_models.py:54-68`). Under Option C's `nlp_engine_name: multi`, the Docker image build fails at the `poetry run python install_nlp_models.py` step (`Dockerfile.transformers:32`). Research never flags this; planning would discover it only after the first build fails.
2. **[HIGH] German model selection is benchmark-only.** `xlm-roberta-large-finetuned-conll03-german` was selected on backbone family + corpus identity grounds, never probed against the 5 named over-detection phrases or any member of the broader class. Research §4.1's "Common-noun behavior" column is "Not documented" for every CoNLL-03 candidate. The bug being fixed could survive the model swap.

**Other findings:** narrow broader-class fixture set (10 phrases hits Q5b's lower bound but doesn't engage the class boundary); citation errors (5 of 7 spot-checked file:line references are off, including `ner_model_configuration.py:55` → actual `:63`, `install_nlp_models.py:79` → actual `:91`, `_doc_to_nlp_artifact` cite is in the wrong file); soft `~150 LoC` estimate that excludes the install_nlp_models.py extension and tests; under-documented code-switched text behavior change; unverified cold-start time; ADR overstates research evidence on chosen model.

**Verdict:** PROCEED WITH FIXES. Research is fundamentally sound on the load-bearing technical question (NlpEngineProvider single-engine constraint, MultiNlpEngine wiring, eval-suite blind spot are all verified). The HIGH findings are tractable in 2d without restructuring; the MEDIUM findings are mostly citation cleanup and scoping clarifications. None of the gaps invalidate the chosen architecture.

### Step 2d — Research findings addressed

Spawned 2026-05-06 10:33:05. Counter file: `SDD/orchestration/counters/2d-1-2026-05-06_10-33-05.md`.

**Severity counts resolved: 2 HIGH, 4 MEDIUM, 4 LOW — all addressed.** Per-finding fix log appended to `SDD/reviews/CRITICAL-RESEARCH-transformers-nlp-backend-20260506.md` under `## Findings Addressed`.

Resolution highlights:

- **HIGH 1 (build-pipeline gap):** Verified `install_nlp_models.py:54-68` `else: raise ValueError` blocker, added new RESEARCH-007 §2.6 documenting the gap and the ~10 LoC fix path; updated §3.3 Option C "Cons", §9.1, §11.2, §15 index, ADR Decision and Negative sections.
- **HIGH 2 (model unverified against bug class):** Used Resolution A — ran a live HF-pipeline probe over 20 broader-class phrases against `xlm-roberta-large-finetuned-conll03-german`, `Davlan/bert-base-multilingual-cased-ner-hrl`, and `mschiesser/ner-bert-german`. Results documented in new RESEARCH-007 §4.5. **`xlm-roberta-large-finetuned-conll03-german` empirically validated** (zero entities on 10 named broader-class phrases + correct sentence-context behavior). **`mschiesser/ner-bert-german` empirically disqualified** (mis-tags 5 of 10 phrases as PER 0.793–0.998). **`Davlan/bert-base-multilingual-cased-ner-hrl` promoted from rejected to validated A/B target.** ADR §"Decision" upgraded with empirical-validation language; §Alternatives F and G rewritten accordingly.
- **MEDIUM (broader-class boundary):** Added RESEARCH-007 §7.4 with explicit class boundary spec, 4 sub-classes (identity/document, insurance, financial, employment), 15 fixtures spanning all 4, future-set candidates documented in ADR Neutral section.
- **MEDIUM (citation errors):** Corrected all spot-checked off-by-N references (`ner_model_configuration.py:55→63-64`, `install_nlp_models.py:79→91, 79-82→94-95, 62→56/87`, `Dockerfile.transformers:32→30`, `_doc_to_nlp_artifact` cite moved from `transformers_nlp_engine.py:187-198` to `spacy_nlp_engine.py:200-213`, dslim/bert-base-NER row in §4.1 corrected to docstring-only-example).
- **MEDIUM (LoC estimate):** Revised `~150 LoC` to `~200–260 LoC` total (~100 LoC `MultiNlpEngine` + ~10 LoC install_nlp_models + ~80–150 LoC tests) in RESEARCH-007 §3.3 Option C and §11.2; ADR Decision and Negative sections updated.
- **MEDIUM (Option C vs B framing):** Rebalanced §3.3 Option B/C cons to honestly represent operational surface; added phasing alternative paragraph.
- **LOW (code-switched-text behavior change):** Added detailed paragraph to §12.2 documenting that asymmetric routing flips the failure mode from over-flagging (today) to under-flagging (new); ADR Neutral observation extended; operator-facing doc note flagged for §18.1.
- **LOW (start_period:30s unverified):** Reframed in §2.4 and ADR Negative section from "trade-off accepted" to "verify during implementation"; added one-shot timing measurement to implementation calibration plan.
- **LOW (ADR overstates evidence):** ADR Decision rewritten to lead with the empirical validation in RESEARCH-007 §4.5 (no longer asserts the model on backbone-family grounds alone).
- **LOW (PhoneRecognizer German triggers):** Added one-line note to §3.5 flagging the latent question; out of scope, documented for implementation calibration.

**Missing perspectives addressed:**
- Presidio upstream maintainer mental model added as RESEARCH-007 §11.3 (and ADR Negative section).
- Docker image-build-operator concerns acknowledged in ADR Negative (build-time CI minutes).
- Security review concerns: existing §16.4 is unchanged but in-scope; no further changes required by the review's own framing ("out of scope for research, but worth a brief mention").

**ADR updates applied:** Yes — 4 sections updated (Context citation fix, Decision rewritten with empirical validation + revised LoC, Alternatives F/G swapped between rejected/validated, Negative + Neutral expanded). No supersession needed; the ADR remains 0001 / Accepted with the same recommended primary model — the empirical evidence supports the decision rather than overturns it.

**Resolution: A (live model probe).** Setup took ~5 minutes (uv-on-the-fly install of transformers/torch/sentencepiece, ~3 GB of model downloads); ran in foreground; total compute time including all three candidates ~10 minutes. Temp probe script discarded; results captured verbatim in RESEARCH-007 §4.5.

**No code changes, no tests, no git operations performed.** Research-document and ADR text fixes only. Final counter: Reads 9/10, Nested subagents 0/4. Ready for /sdd:commit at Step 2e.
