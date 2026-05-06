---
review_panel: [security, performance, privacy, reliability, module-depth]
eval_required: true
cross_cutting_decisions: [presidio_nlp_engine_per_language]
delivery_mode: whole-feature
---

# SPEC-007: Transformers NLP Backend (asymmetric routing)

**Feature:** 007 — transformers-nlp-backend
**Creation Date:** 2026-05-06
**Author:** Claude (with Pablo)
**Status:** Draft (planning)
**Branch:** feature/007-transformers-nlp-backend
**Inputs:**
- `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md`
- `SDD/research/RESEARCH-007-transformers-nlp-backend.md`
- `SDD/adr/0001-presidio-per-language-nlp-engine.md`
- `SDD/UBIQUITOUS_LANGUAGE.md`
- `SDD/reviews/CRITICAL-RESEARCH-transformers-nlp-backend-20260506.md`

---

## Executive Summary

Replace the Presidio analyzer's German NLP backend with a transformer model while keeping spaCy `en_core_web_lg` for English. The two engines coexist inside a single analyzer container via a custom **`MultiNlpEngine`** subclass added to the Presidio fork (Option C in RESEARCH-007 §3.3). The chosen German NER model is **`xlm-roberta-large-finetuned-conll03-german`**, empirically validated against the bug class (RESEARCH-007 §4.5). `Davlan/bert-base-multilingual-cased-ner-hrl` is the documented A/B fallback.

This swap fixes the **broader class** of German common-noun-as-`PERSON` over-detection (10 named phrases plus the broader sub-classes enumerated in RESEARCH-007 §7.4) and restores **graded scores** to German NER, replacing spaCy's flat 0.85 default. The Redakt API contract, the per-entity score floor shape (`dict[str, float]`), and the recognizer-registry floor (Presidio-fork commits 71206f6 / d76d884) are preserved verbatim. spaCy stays a hard dependency for lemma-aware enhancers and PhoneRecognizer context handling.

`detection-set non-regression` for English is automatic by construction — the English path is bit-for-bit identical to today (spaCy `en_core_web_lg`). The German path produces no entity flags on the broader class while preserving correct sentence-context PER/ORG/LOC behavior. Per-entity score floors and the `low_score_entity_names` / `low_confidence_score_multiplier` knobs are re-tuned empirically against graded scores during calibration.

---

## Research Foundation

This spec is derived from RESEARCH-007 (~1070 lines, post-fix) and CLARIFICATION-007. Key findings carried forward:

1. **Presidio's `NlpEngineProvider` cannot mix engine types per language** (`presidio/.../nlp_engine_provider.py:87-114`). The CLARIFICATION's hint about a "per-language engine map at the provider layer" is wrong; a custom `MultiNlpEngine` is the wiring (RESEARCH-007 §3.1, §3.3, §3.4; ADR 0001 §Decision).
2. **`install_nlp_models.py` build-pipeline gap** — the existing `_download_model` dispatcher only branches on `spacy | stanza | transformers` and raises `ValueError` otherwise (`install_nlp_models.py:54-68`). Under `nlp_engine_name: multi`, the image build fails at `Dockerfile.transformers:30` unless the dispatcher learns a `multi` branch (RESEARCH-007 §2.6).
3. **German model selection is empirically validated.** `xlm-roberta-large-finetuned-conll03-german` returns zero entities on all 10 named broader-class bare nouns and 9 of 10 broader-extras (only `BIC` flags ORG, defensible). Sentence-context PER/ORG/LOC behavior preserved. `mschiesser/ner-bert-german` was demoted to "rejected on bug-class evidence" because it mis-tags 5 of 10 named phrases as PER 0.793–0.998 (RESEARCH-007 §4.5).
4. **Eval suite is structurally weak at over-detection** — `tests/eval/test_calibration.py:55` uses `expected.issubset(found)`, which only catches *missing* entities. The headline bug rides through unflagged in the current 41/41 PASS line. The only branch that catches over-detection is `expect_clean: true` (test_calibration.py:46-50). New `expect_clean: true` fixtures for the broader class are required to convert the fix into a CI signal (RESEARCH-007 §8.2, §7.3, §7.4).
5. **Per-entity score floor lives in Redakt.** `src/redakt/utils.py:97-110` (`filter_by_entity_thresholds`) is unchanged in shape (`dict[str, float]`); only values are re-tuned (RESEARCH-007 §6).
6. **Models are baked at image build time** via `install_nlp_models.py` invoked from `Dockerfile.transformers:30`. No runtime download. The `TRANSFORMERS_CACHE` mount alternative is documented and rejected for this feature (RESEARCH-007 §2.4, §9.4).
7. **No prior NLP-backend ADR existed.** ADR 0001 captures the per-language NLP engine decision (RESEARCH-007 §10.1; ADR 0001).

The critical review (`SDD/reviews/CRITICAL-RESEARCH-...md`) flagged 2 HIGH + 4 MEDIUM + 4 LOW findings; all were addressed in research's `## Findings Addressed` section and folded into ADR 0001 before this spec was written.

**Stakeholder validation:** Pablo (the `operator`, in the combined Product + Engineering + end-user role per CLARIFICATION-007 §"Users and Goals") authored CLARIFICATION-007 and signed off on its six resolved decisions. Support: NA (Redakt is an enterprise-internal tool with no external support channel; the operator is the sole stakeholder).

---

## Intent

### What success looks like

The `operator` runs `tools/calibration_report.py --raw --out` and observes:

- All 41 existing fixtures stay green (no regression).
- The 15 new `expect_clean: true` `broader class` fixtures (10 named + 5 sub-class extras per RESEARCH-007 §7.4) report `redakt: —` (no entity flags).
- The pre-`broader class` calibration baseline (`reports/post-fix-2.md`) is supplanted by a post-implementation report demonstrating the same `de` PII fixtures still flag the country recognizer hits expected, but no longer ride a spurious `PERSON(0.85)`.
- German `LOCATION` and `DATE_TIME` hits in calibration land on a continuous score gradient (RESEARCH-007 §6.4), and re-tuned per-entity floors (`graded scores` regime) keep `benign` fixtures clean while letting through legitimate German PII.
- English fixtures (`generic`, `benign`, `us`, `uk`) flag bit-for-bit the same set of entity types as today (`detection-set non-regression`).

### What this spec is NOT trying to do

- Change the Redakt API contract (request/response shape, status codes, headers) for `/api/detect`, `/api/anonymize`, `/api/deanonymize`.
- Change the per-entity score floor shape (`dict[str, float]`).
- Disable, reorder, or rescore any currently-enabled `country recognizer` from the recognizer-registry floor (Presidio-fork commits 71206f6 / d76d884).
- Remove spaCy as a dependency.
- Touch the Redakt frontend (HTMX/Jinja).
- Add per-sentence or per-token language routing (out of scope per CLARIFICATION-007 Q6).
- Deploy on GPU (CPU-only is supported per CLARIFICATION-007 Q4b).

---

## Success Criteria

### Functional Requirements

#### REQ-001: `MultiNlpEngine` subclass in the Presidio fork
A new class `MultiNlpEngine` (sub-class of `NlpEngine`) lives at `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py`. It holds two underlying NLP engine instances — one `SpacyNlpEngine` (configured with `en_core_web_lg` for `en`) and one `TransformersNlpEngine` (configured with `de_core_news_sm` + `xlm-roberta-large-finetuned-conll03-german` for `de`) — and dispatches `process_text(text, language)` and `process_batch(texts, language, **kw)` to the sub-engine that owns the requested language. Public surface: `__init__(models, ner_model_configuration=None)`, `load()`, `is_loaded()`, `process_text(text, language)`, `process_batch(texts, language, **kw)`, `is_stopword(word, lang)`, `is_punct(word, lang)`, `get_supported_entities()`, `get_supported_languages()`, `get_nlp(language)`.

**Model-load-once invariant.** All sub-engine model artifacts (`en_core_web_lg`, `de_core_news_sm`, `xlm-roberta-large-finetuned-conll03-german`) are loaded **exactly once** during analyzer startup, via a single `MultiNlpEngine.load()` invocation from `AnalyzerEngineProvider.create_engine()`. `process_text` and `process_batch` MUST NOT trigger model load on the request path — they assume `is_loaded()` is True and dispatch directly. If `process_text` is called before `load()` has completed, it MUST raise (not lazy-load), so that the cold-start cost is paid up front and not amortized across user-visible requests.

**Acceptance:**
- Instantiating with both engines configured produces correct entity output for both languages on the existing 41 eval fixtures.
- A unit test confirms that calling `process_text` before `load()` raises a clear error (does not lazy-load).
- A unit test confirms that two consecutive `process_text` calls do not re-invoke the underlying spaCy / transformers loaders (verified by patching the loaders and asserting call count == 1 from the `load()` step only).

**Spec refs:** §Modules MODULE-001, REQ-005a, PERF-002.

#### REQ-002: Engine-name registration with `NlpEngineProvider`
`MultiNlpEngine` is registered with `NlpEngineProvider`'s `nlp_engines` dictionary under engine name `multi`, so it is selectable via the existing YAML config schema (`nlp_engine_name: multi`). The registration lives in `presidio/.../nlp_engine_provider.py`. `ConfigurationValidator.validate_nlp_configuration` (`presidio_analyzer/input_validation/schemas.py`) is extended with a `multi` schema branch (or annotated to skip detailed validation for `multi`). Acceptance: `NlpEngineProvider.create_engine()` builds a `MultiNlpEngine` instance from a `nlp_engine_name: multi` YAML without raising. **Spec refs:** MODULE-001.

#### REQ-003: New analyzer NLP YAML for the multi engine
A new file `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml` declares the multi-engine config: top-level `nlp_engine_name: multi`; per-row `models[]` entries each carrying `lang_code`, an `engine` key (`spacy` | `transformers`), `model_name` (string for spacy, dict-of-`{spacy, transformers}` for transformers), and a per-row `ner_model_configuration` block. The `en` row sets `engine: spacy`, `model_name: en_core_web_lg`, and inherits the current `spacy_multilingual.yaml` mapping (PER/PERSON/NORP/FAC/LOC/LOCATION/GPE/ORG/ORGANIZATION/DATE/TIME), with `low_score_entity_names: [ORG, ORGANIZATION]`, `low_confidence_score_multiplier: 0.4`. The `de` row sets `engine: transformers`, `model_name: { spacy: de_core_news_sm, transformers: xlm-roberta-large-finetuned-conll03-german }`, `aggregation_strategy: max`, `stride: 16`, `alignment_mode: expand`, `model_to_presidio_entity_mapping: { PER: PERSON, LOC: LOCATION, ORG: ORGANIZATION }`, `labels_to_ignore: [O, MISC]`, with the `de`-side `low_score_entity_names` / `low_confidence_score_multiplier` set to calibrated values from REQ-007. Acceptance: `AnalyzerEngineProvider.create_engine()` constructs a working analyzer from this YAML. **Spec refs:** MODULE-002.

#### REQ-004: `install_nlp_models.py` extension for the `multi` engine
The build-time install script gains a `multi` branch in its dispatch path (currently `install_nlp_models.py:54-68` raises `ValueError` for any unknown engine). When `nlp_engine_name == "multi"`, the script iterates `nlp_configuration["models"]` and dispatches each row by its per-row `engine` key — calling `_download_model("spacy", row["model_name"])` for spacy rows and `_download_model("transformers", row["model_name"])` for transformers rows. Validation: a row missing the `engine` key raises a clear error; an unknown per-row `engine` value raises a clear error. Acceptance: `docker compose build presidio-analyzer` succeeds against `multi.yaml` and the resulting image contains all required model artifacts. **Spec refs:** MODULE-003, FAIL-001.

#### REQ-005: Dockerfile + docker-compose wiring
Root-level `docker-compose.yml`'s `presidio-analyzer` service is updated to: (a) set `dockerfile: Dockerfile.transformers` (currently absent — defaults to `Dockerfile`); (b) set `args.NLP_CONF_FILE: presidio_analyzer/conf/multi.yaml`. `Dockerfile.transformers` itself is not modified beyond what may be needed to support the new YAML; the existing `RUN poetry run python install_nlp_models.py --conf_file ${NLP_CONF_FILE}` step at line 30 already does the right thing once REQ-004 lands. Acceptance: `docker compose up presidio-analyzer` produces a running analyzer container that responds 200 to its `/health` endpoint within `start_period`. **Spec refs:** MODULE-007, FAIL-001.

#### REQ-005a: Two-phase startup contract (readiness probe wired to `is_loaded()`)
The analyzer's `/health` endpoint MUST return 200 only after `MultiNlpEngine.is_loaded()` returns True for **every** configured language (`en` AND `de`). Concretely:
- `MultiNlpEngine.is_loaded()` returns True iff every sub-engine in `self._sub_engines` reports loaded (`SpacyNlpEngine` for en with `en_core_web_lg` loaded; `TransformersNlpEngine` for de with both `de_core_news_sm` and `xlm-roberta-large-finetuned-conll03-german` loaded). Partial-load returns False.
- The Presidio analyzer process invokes `MultiNlpEngine.load()` exactly once during startup (via `AnalyzerEngineProvider.create_engine()`), before the HTTP server begins serving `/health`. If `load()` raises (any sub-engine fails), the startup process exits non-zero so Docker's restart policy picks it up — the container does not come up half-loaded.
- Until `is_loaded()` returns True for all languages, `/health` MUST exhibit **one** of the two following behaviors (the implementer chooses based on the actual Presidio analyzer startup model — see below) and the docker-compose `healthcheck` retry semantics MUST match the chosen behavior:
  - **(Behavior A) HTTP server bound but `/health` returns 503.** This requires the Flask/HTTP server to bind early but expose a readiness flag tied to `MultiNlpEngine.is_loaded()`. The compose `healthcheck` interprets 503 as "not ready, keep retrying."
  - **(Behavior B) HTTP server has not yet bound to the port; the orchestrator gets connection-refused.** This is the natural Presidio behavior when `AnalyzerEngineProvider.create_engine()` runs synchronously during Flask app initialization — if `load()` raises, the import fails and the server never binds. The compose `healthcheck` interprets connection-refused as "not ready, keep retrying."
  - The implementation report documents which behavior was selected and why (typically: B, because Presidio constructs the engine eagerly during Flask app initialization, blocking the bind until `load()` completes). The compose `healthcheck`'s `start_period`, `interval`, and `retries` are tuned for the chosen behavior.
- The container MUST NOT serve `/health` 200 with a partial engine state.
- **No silent fallback:** the analyzer never serves traffic with `is_loaded() == False` for a configured language. This is the structural anchor for FAIL-002.

**Acceptance:**
- A unit/integration test confirms `/health` does not return 200 until `MultiNlpEngine.is_loaded() == True` for both `en` and `de`. (Implementation may simulate this by patching one sub-engine's loader to delay or fail.)
- A simulated sub-engine-load failure (mock the spaCy or transformers loader to raise) causes the analyzer process to exit non-zero, not to serve `/health` 200. Verified once during implementation.

**Spec refs:** MODULE-001, MODULE-007, FAIL-002.

#### REQ-006: Per-entity score floor re-tune (Redakt-side)
`src/redakt/config.py:14`'s `entity_score_thresholds` default values are re-tuned empirically against `graded scores` produced by the new German transformer pipeline. The shape stays `dict[str, float]` (frozen per CLARIFICATION-007 §"Constraints").

**Calibration protocol (stopping condition).** The threshold re-tune is **not** complete merely when "all fixtures stay PASS" — that bar is circular because the thresholds are tuned against the same fixture set that decides pass. The protocol REQUIRES all of the following to hold simultaneously before threshold values are committed:

1. **Negative bar (existing):** all 41 existing fixtures stay PASS (no detection-set regression) AND all 15 new `expect_clean: true` `broader class` fixtures (REQ-009) stay PASS (no over-detection on bare common nouns).
2. **Held-out positive bar (new — entity-conditional, amended 2026-05-06):** for every Presidio entity type that has model coverage on the configured DE engine (i.e., the entities the transformer can emit: `PERSON` via `PER`, `LOCATION` via `LOC`, `ORGANIZATION` via `ORG`; PLUS regex-only entities with held-out fixtures within their score ceilings), at least one positive fixture in `tests/eval/fixtures/de.yaml` MUST produce a `found` set containing the expected entity type (verified by the harness branch that asserts presence — i.e., a *true-positive* assertion, distinct from `expect_clean` and from `issubset`-only). This catches threshold values that drop legitimate hits. Concretely, after the 2026-05-06 amendment: a positive German `LOCATION` fixture (added per REQ-009b — see below) MUST satisfy this bar. **DE `DATE_TIME` is excluded from this bar by Amendment 2026-05-06** — `xlm-roberta-large-finetuned-conll03-german` has no DATE label, and `DateRecognizer`'s 0.6 / 0.8 score ceiling is documented as a model-design limitation in REQ-009b's amendment block. New entities added to the DE coverage set (e.g., via a future model swap) re-engage this bar automatically.
3. **Score-distribution justification (new):** the calibration report committed alongside the threshold values MUST include, for each threshold value tuned, the score distribution that justifies the chosen floor. Concrete format: a one-line annotation per tuned entity such as "`DE LOCATION` floor chosen at `0.85` because the calibration corpus shows the bottom of the legitimate-hit distribution at `0.87` (true positives — `Berlin`, `München`, `Hamburg`) and the top of the noise distribution at `0.78` (false positives — bare nouns `Personalausweis`, `Reisepassnummer`)." A threshold without a corresponding line in the report MUST NOT be committed.
4. **Reproducibility (new):** re-running `tools/calibration_report.py --raw --out` against the committed corpus and the committed threshold values MUST reproduce the same threshold *recommendations* within ±0.05 (i.e., the report's recommended floor for each tuned entity falls within 0.05 of the committed value). This protects against a one-shot tune that doesn't replay.

If any of (1)–(4) fails, threshold values are NOT committed; the implementer iterates. The stopping condition is the conjunction of all four bars, not "Pablo declares it good." Pablo's review remains required for sign-off on the report, but cannot waive any of (1)–(4).

Documentation: the new values appear in `src/redakt/config.py` (committed), in the calibration report under `reports/`, and in `.env.example` if shipped.

**Spec refs:** MODULE-005, MODULE-006, REQ-009b.

#### REQ-007: Global threshold knob re-tune (analyzer-side, per language)
The `de` row of `multi.yaml` carries re-tuned `low_score_entity_names` and `low_confidence_score_multiplier` values calibrated against the new graded German transformer scores (CLARIFICATION-007 Q5c, in scope). The `en` row carries today's `[ORG, ORGANIZATION]` / `0.4` values unchanged (English path is bit-for-bit preserved per ADR 0001 §Decision). Calibration acceptance: governed by the same four-bar stopping condition as REQ-006 — bars (1)–(4) apply to both Redakt-side `entity_score_thresholds` and analyzer-side `low_score_entity_names` / `low_confidence_score_multiplier` jointly (they form a single calibration surface). The calibration report MUST also annotate the analyzer-side `low_confidence_score_multiplier` choice with a score-distribution rationale (REQ-006 bar 3 applies). **Spec refs:** MODULE-006, REQ-006, REQ-009b.

#### REQ-008: Calibration corpus expansion (broader class)
The implicit `calibration corpus` (`tests/eval/fixtures/*.yaml`) is expanded by the additions made under REQ-009 — the calibration tool walks all fixtures, so adding `expect_clean: true` fixtures simultaneously expands both calibration coverage and CI coverage (RESEARCH-007 §7.2). The expansion totals **15 phrases** spanning all 4 sub-classes per RESEARCH-007 §7.4 (10 named + 5 sub-class extras). Acceptance: `tools/calibration_report.py --raw --out` after implementation lists each new phrase under `## [PASS] de — {noun}` with `redakt: —` and `raw: —`. **Spec refs:** MODULE-004, MODULE-005, EDGE-002.

#### REQ-009: New CI fixtures for `broader class` over-detection
Add 15 new `expect_clean: true` entries to `tests/eval/fixtures/de.yaml` per RESEARCH-007 §7.3 + §7.4. The 10 named: `Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`, `Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`, `Versicherungsnummer`. Plus 5 sub-class extras: `Geburtsurkunde` (identity/document), `Steuernummer` (financial), `Kontonummer` (financial), `Mitgliedsnummer` (employment/membership), `Kundennummer` (employment/membership). Acceptance: `uv run pytest tests/eval/` produces 56/56 PASS (41 existing + 15 new). **Sub-REQ-009a (harness):** `tests/eval/_loader.py` and `tests/eval/test_calibration.py` already support `expect_clean: true` (verified in research §8.2 — the assertion `if phrase.expect_clean: assert found == []` exists at test_calibration.py:46-50). No harness extension is required. If during implementation any harness-side blocker surfaces, it lands in the same PR; the failure mode must be a meaningful pytest failure (`AssertionError` listing the entities found), not a silent pass.

**Broader-class extension rule (acceptance addendum).** If, during step 6 calibration, the implementer encounters a German common-noun-as-`PERSON` over-detection that is **not** in the 15 enumerated above, that noun MUST be added to `tests/eval/fixtures/de.yaml` as an `expect_clean: true` entry **before** the feature lands. Out-of-scope deferral or undocumented model-swap triggers are not permitted; the rule is "if calibration discovers it, the corpus must record it." This makes the broader-class corpus self-extending and prevents silent fixture drift. **Spec refs:** MODULE-005, EDGE-002.

#### REQ-009b: Held-out positive fixtures (DE LOCATION) and long-document anchor

**Amendment 2026-05-06 (Option A).** This REQ originally enumerated three fixtures: (1) DE LOCATION positive, (2) DE DATE_TIME positive, and (3) a long-document anchor. The DE DATE_TIME positive (item 2) is **dropped** by this amendment. **Why:** the chosen DE engine — `xlm-roberta-large-finetuned-conll03-german` — is a CoNLL-03 model whose label set is `PER / LOC / ORG / MISC`; it has **no DATE label** and therefore cannot fire DATE_TIME on DE-routed traffic. DE DATE_TIME is regex-only via `DateRecognizer`, whose ceilings are 0.6 (`dd.mm.yyyy` and similar civilian formats) and 0.8 (full ISO 8601 datetime) — see `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/date_recognizer.py`. Meanwhile, EN benign fixtures (`Munich today?`, `Paris this afternoon?`) carry DATE_TIME at 0.85 from `en_core_web_lg` SpacyRecognizer's `ner_strength` constant. The score-source asymmetry (EN spaCy 0.85 vs. DE regex 0.6/0.8) made REQ-006 Bar 1 (`T > 0.85` to keep EN benign clean) and REQ-006 Bar 2 (`T ≤ 0.8` to admit a DE held-out DATE_TIME positive) a **conjunction-impossible** intersection at the empty set. Documented as a model-design limitation, not a model swap. The prior wording — "DE DATE_TIME positive: a sentence-context fixture such as `Der Termin ist morgen um 14 Uhr.`, with `expected_entities: [DATE_TIME]`" — is preserved here for audit traceability only and is no longer normative. Reference: `SDD/orchestration/compacted/implementation-compacted-2026-05-06_13-45-37.md` (full diagnosis, probe outputs, score table). REQ-006 Bar 2 is rewritten in this same amendment to be entity-conditional.

Add two new fixtures to `tests/eval/fixtures/de.yaml`:

1. **DE LOCATION positive:** a sentence-context fixture such as `Sie wohnt in Berlin und arbeitet in München.`, with `expected_entities: [LOCATION, LOCATION]`. The harness MUST assert that `LOCATION` is present in `found` (not merely `issubset`-passed against an empty expected set). This is the held-out positive anchor for REQ-006 bar 2 (and remains the **only** held-out positive after the 2026-05-06 amendment — DE DATE_TIME was dropped).
2. **Long-document anchor (>500 transformer tokens):** a German-language fixture whose tokenized length under `xlm-roberta-large-finetuned-conll03-german`'s tokenizer exceeds 500 tokens. Use the following 557-token German prose paragraph (the ~200-word base paragraph below, repeated three times concatenated; tokenized length 557 confirmed inside `redakt-presidio-analyzer-1` per the compaction file's "Long-doc anchor proof-of-tokenization" section):

   > Das Projekt befindet sich in einer entscheidenden Phase. Die Anforderungen wurden in den letzten Wochen zusammen mit den Fachbereichen erarbeitet. Wir haben die Dokumentation überarbeitet und neue Kapitel zur Architektur ergänzt. Im Rahmen der Konferenz stellten die Entwicklerinnen und Entwickler erste Ergebnisse vor. Die Diskussionen in den Workshops zeigten ein breites Interesse an dem Thema. Wir planen weitere Schulungen, um die Mitarbeitenden auf den neuen Stand zu bringen. Auch die Sicherheitsaspekte werden ausführlich behandelt und in einem eigenen Kapitel beschrieben. Die Tests werden durch automatisierte Verfahren unterstützt, sodass eine hohe Qualität gewährleistet bleibt. Über kommende Änderungen werden wir Sie regelmäßig informieren. Bei Fragen wenden Sie sich bitte an die zuständigen Ansprechpersonen im Bereich Forschung und Entwicklung.

   Record the token count (557) in the fixture comment or in the calibration report. This fixture is referenced by EDGE-006 ("at least one fixture with German text >500 tokens") and PERF-001's long-document anchor.

**Acceptance:**
- `tests/eval/fixtures/de.yaml` contains two new entries matching (1) and (2); `uv run pytest tests/eval/` is green (the eval suite total becomes **58 = 41 existing + 15 broader-class clean + 2 held-out positive/long-doc**).
- The harness asserts the held-out positive entity is present in `found` for fixture (1). The "must contain" branch on the harness (`tests/eval/test_calibration.py:52-58`'s `missing = [e for e in expected if e not in found]; assert not missing`) is now used by **DE LOCATION only**.
- The long-document fixture (2) is exercised by `tools/calibration_report.py --raw --out` and the resulting transcript captured in `reports/`.

**Spec refs:** MODULE-005, REQ-006, REQ-007, PERF-001, EDGE-006.

#### REQ-010: API contract preservation
The Redakt API endpoints `POST /api/detect`, `POST /api/anonymize`, `POST /api/deanonymize` keep their current request/response shapes, status codes, and headers. The per-request `entity_score_thresholds` body field stays `dict[str, float]`. The instance-level `entity_score_thresholds` config key stays `dict[str, float]` and the env-var override `REDAKT_ENTITY_SCORE_THRESHOLDS` keeps its JSON-string format. Acceptance: existing 41 eval fixtures pass without fixture-format modification; `tests/` (unit + integration) and `tests/e2e/` are green; OpenAPI spec at `/openapi.json` diff'd against `main` shows zero schema changes.

**Note:** the eval-fixture green line uses `expect.issubset(found)` (per RESEARCH-007 §0.4 / §8.2) and is structurally weak at catching over-detection. It is included here for *detection-set non-regression* coverage, not as a contract-shape gate. The contract-shape gate is REQ-010a (below).

**Spec refs:** MODULE-001 (downstream consumer), REQ-010a, SEC-001.

#### REQ-010a: API-shape regression test (byte-identical envelope + headers)
A new contract test (added under `tests/` or extending an existing integration test) MUST assert byte-identical request/response shapes for representative `200`-status requests on each of the three endpoints, distinct from the `tests/eval/` fixtures and distinct from the OpenAPI schema diff. Concretely:

1. **Snapshot baseline.** Capture a representative `200` response on `main` for each of `POST /api/detect`, `POST /api/anonymize`, `POST /api/deanonymize` against a fixed input (suggested: an English short sentence with a clear PERSON entity, plus a German fixture from `de.yaml`). Persist the snapshot under `tests/contracts/` as JSON.
2. **Feature-branch comparison.** The contract test runs the same fixed inputs against the feature branch and asserts byte-identical JSON envelopes for top-level keys, status codes, and response headers (apart from the `placeholder_to_original` mapping content for `/api/anonymize`, which is allowed to differ; its *shape* — `dict[str, str]` — must be identical).
3. **Header coverage.** The test explicitly asserts the response `Content-Type`, any `X-Redakt-*` headers (none expected to be added or removed), and the absence of newly-introduced headers. This catches changes that FastAPI's auto-OpenAPI does NOT include (custom middleware-added headers).
4. **Failure mode.** If any envelope key, status, or header diverges, the test fails with a precise diff identifying the offending field; not a fuzzy mismatch.

**Acceptance:**
- The contract test is added in the same PR as the feature; passes on the feature branch.
- The OpenAPI diff (REQ-010) and the contract test (REQ-010a) BOTH gate merge. Either signal alone is insufficient.
- A simulated tamper test (manually adding a stray header in a feature branch experiment) causes the contract test to fail — verified once during implementation.

**Spec refs:** MODULE-001 (downstream consumer), REQ-010, SEC-001.

#### REQ-011: Recognizer-registry floor preservation
All `country recognizer` instances currently enabled per Presidio-fork commits 71206f6 and d76d884 stay enabled, in current order, with current scoring (full list in RESEARCH-007 §2.2 / ADR 0001 §Context):
- en (US): `UsBankRecognizer`, `UsLicenseRecognizer`, `UsItinRecognizer`, `UsPassportRecognizer`, `UsSsnRecognizer`, `UsMbiRecognizer`, `UsNpiRecognizer`, `AbaRoutingRecognizer`.
- en (UK): `NhsRecognizer`, `UkNinoRecognizer`, `UkPassportRecognizer`, `UkPostcodeRecognizer`, `UkVehicleRegistrationRecognizer`.
- de: `DeTaxIdRecognizer`, `DeVatIdRecognizer`, `DePassportRecognizer`, `DeIdCardRecognizer`, `DeHealthInsuranceRecognizer`, `DeKfzRecognizer`, `DeFuehrerscheinRecognizer`, `DePlzRecognizer`.
- generic: `CryptoRecognizer`, `DateRecognizer`, `EmailRecognizer`, `IbanRecognizer`, `IpRecognizer`, `MedicalLicenseRecognizer`, `MacAddressRecognizer`, `PhoneRecognizer`, `UrlRecognizer`, `CreditCardRecognizer`.

Recognizers explicitly disabled in the fork (e.g., `DeTaxNumberRecognizer`, `DeSocialSecurityRecognizer`, `DeHandelsregisterRecognizer`, all `Au*`/`Ng*`/`In*`/`Kr*Recognizer`, `HuggingFaceNerRecognizer`) **stay disabled.** New recognizers may be added if calibration surfaces a gap, but no removals/disables/reorderings/rescorings of currently-enabled recognizers.

**Acceptance:**
- A diff of `presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml` between (a) the Redakt repo's `main` branch and the feature branch `feature/007-transformers-nlp-backend` AND (b) the Presidio fork repo's tracking branch (`main` of `git@github.com:pablooliva/presidio.git`, which mirrors upstream's `main` plus the fork's commits 71206f6 / d76d884) and the same fork's feature branch corresponding to this work shows **additions only (or no changes).**
- Both diffs are captured (using `git diff --no-color`) and committed under `reports/req-011-recognizer-diffs.md` (or pasted into the implementation report) so the review record is auditable. The diff outputs are part of the PR review evidence — not regenerated ad-hoc.
- If the fork's feature work happens on a branch other than the Redakt feature-branch name (e.g., `redakt-multinlpengine`), the implementation report names the exact fork-side branch.

**Spec refs:** MODULE-002, SEC-002.

#### REQ-012: Documentation of code-switched-text limitation
`docs/v1-feature-spec.md` (or the appropriate operator-facing doc) is updated with a note: "For mixed-language text (e.g., a German paragraph with English names), set the `language` parameter explicitly to the language with the dominant PII content; do not rely on auto-detect. Under `asymmetric routing`, `language: auto` picks one engine per request via lingua-py and the non-selected language's PII may be missed." (RESEARCH-007 §12.2; ADR 0001 §Neutral observations.) Additionally, `docs/presidio-integration.md`'s "NLP Engine Options" section (currently lines 196-212) is updated to reflect that Redakt now uses `MultiNlpEngine` (`asymmetric routing`), not pure `spacy_multilingual`. **Spec refs:** MODULE-008, EDGE-001.

#### REQ-013: HF model revision pinning + artifact-level integrity verification
The HF model reference for `xlm-roberta-large-finetuned-conll03-german` is pinned **declaratively via a YAML `revision` key** in the per-row `models[]` entry of `multi.yaml` (extension to the multi-YAML schema; see MODULE-002 Public Interface). The install dispatcher (MODULE-003) honors this pin via the extended `_download_model(..., revision=)` signature and forwards it to both `huggingface_hub.snapshot_download(revision=...)` and `AutoModelForTokenClassification.from_pretrained(revision=...)`. The function-arg-only path is rejected — pinning must be visible in the YAML, not buried in the install script.

**Artifact-level integrity verification (supply-chain).** Revision pinning alone protects against HF Hub's *advertised* state mutating; it does not protect against HF Hub serving a tampered artifact under that revision name. To address this, the spec requires a known-good artifact baseline:

1. On the first known-good build, `install_nlp_models.py` records the SHA-256 of every weight file produced by `huggingface_hub.snapshot_download` into a checked-in manifest at `presidio/presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json` (per-file: `{path: sha256}`), keyed by `(model_name, revision)`.
2. On every subsequent build, the dispatcher recomputes the SHA-256 of each downloaded file and compares against the manifest. Any mismatch fails the build with a clear error identifying the file and expected vs. actual digest.
3. The manifest is the trust anchor; updating it is a deliberate, reviewable commit.

**Acceptance:**
- The `revision` key is present in `multi.yaml`'s `de` row and is read by `install_nlp_models.py`.
- After the first build, `multi.model_digests.json` exists, is checked in, and lists every weight file with its SHA-256.
- A second `docker compose build presidio-analyzer` against the same `revision` and same manifest succeeds and reports digest match for every file.
- A simulated tamper test (manually flipping a byte of a downloaded weight before the digest check, or pointing the dispatcher at a different revision while keeping the manifest unchanged) causes the build to fail with a clear digest-mismatch error — verified once during implementation.

**Note (build-time cost).** Recomputing SHA-256 on every build is linear in total weight-file size (~2.2 GB across multiple safetensors / pytorch_model.bin shards). The added per-build CPU cost is on the order of tens of seconds — acceptable for a build-time integrity check; called out so future CI optimization work has the right framing (the check is correct as specified, the cost is the price of the property).

**Spec refs:** MODULE-002, MODULE-003, SEC-003.

#### REQ-014: Cold-start measurement gate (with hardware-class binding and explicit safety margin)
Implementation captures a one-shot `time docker compose up presidio-analyzer` measurement with the new image (from cold-cache, OS page cache cleared) and records the result alongside the calibration report (`reports/...`). The measurement MUST be performed on either:

- **(a)** the same hardware class as the deployment target (record CPU model, core count, RAM, and disk type in the report so the binding is auditable), OR
- **(b)** a developer-class machine, in which case the measurement is treated as a lower bound and a **2× safety margin** is applied when deriving `start_period`.

The healthcheck `start_period` value in `docker-compose.yml` is set to `max(30s, ceil(2 × measured_cold_start_seconds))` if option (b) is taken, or `max(30s, ceil(1.3 × measured_cold_start_seconds))` if option (a) is taken (the smaller margin reflects reduced hardware-variance risk). The `start_period` is recorded in the implementation report alongside the measurement and the option chosen.

**Acceptance:**
- The timing measurement is captured in the implementation report along with the hardware description and the option (a/b) chosen.
- `start_period` in `docker-compose.yml` matches the formula for the chosen option, and the report shows the arithmetic.
- Healthcheck reaches healthy state on first cold start, locally and (if the deployment target differs) on the deployment host.

**Spec refs:** MODULE-007, FAIL-002, PERF-002.

#### REQ-015: Pre-deploy in-Redakt model probe
Before declaring implementation done, the 20 phrases probed in RESEARCH-007 §4.5 (Sets A + B = 10 named + 10 broader-extras) are re-run through the live Redakt API at `POST /api/detect?verbose=true` and the result transcript captured. If any phrase that was empirically clean in §4.5 now flags an entity through Redakt, fall back to `Davlan/bert-base-multilingual-cased-ner-hrl` (the validated A/B target — ADR 0001 §Alternative F) and re-run. Acceptance: in-Redakt probe transcript is captured and committed under `reports/`; matches the §4.5 expectation (zero entities on all 10 named phrases; only `BIC` flags ORG among extras; sentence-context controls preserve PER/ORG/LOC). **Spec refs:** MODULE-001, MODULE-004.

#### REQ-016: End-to-end `language: auto` routing test (positive coverage)
The `asymmetric routing` design hinges on the existing `language auto-detect path` (lingua-py based) correctly resolving the request language and the analyzer's `MultiNlpEngine` correctly dispatching that resolved language to the right sub-engine. Today this surface is mentioned only by reference (CLARIFICATION-007 §"Constraints"; EDGE-001, EDGE-004, REQ-012) but has no positive REQ and no test that asserts an `auto`-routed request reaches the correct sub-engine. Without such a test, a regression in the resolution chain (e.g., Redakt sends `language: en`, normalization corrupts the keyword, `MultiNlpEngine` routes silently to the wrong sub-engine) produces wrong-but-valid output undetectable by `expect.issubset(found)` fixtures.

**Test requirement.** Add an end-to-end integration test (under `tests/e2e/` or `tests/` integration layer; whichever exercises the full request pipeline) that:

1. POSTs an unambiguously German short sentence (e.g., `Sie wohnt in Berlin und arbeitet in München.`) to `/api/detect?verbose=true` with `language: auto`. Asserts: response status 200; `analysis_explanation` (or equivalent verbose field) reports the recognizer-side language as `de`; the entity output matches what the German pipeline (transformer-backed) produces for that input.
2. POSTs an unambiguously English short sentence (e.g., `Anna Schmidt works at Acme Corp in New York.`) to `/api/detect?verbose=true` with `language: auto`. Asserts: response status 200; `analysis_explanation` reports the recognizer-side language as `en`; the entity output matches what the English pipeline (spaCy-backed) produces.
3. The two assertions are inverted as a regression-detection sanity check — if `MultiNlpEngine` accidentally swaps `en` ↔ `de` dispatch, the German fixture will produce English-pipeline output (or vice versa) and the test fails with a clear diff.

**Acceptance:**
- The new test passes on the feature branch.
- The test is structured so a hypothetical engine-swap bug (e.g., a one-character flip in `MultiNlpEngine._sub_engines` keys) causes a deterministic failure with a meaningful message — verified by an experimental implementation flip during development (revert before merge).
- This test is the structural mitigation for MODULE-001's HIGH risk tier (silent wrong-engine routing).

**Spec refs:** MODULE-001, REQ-001, REQ-010.

#### REQ-017: Upstream-merge regression CI check (`MultiNlpEngine` import smoke)
Per RISK-003's mitigation (originally captured as "one-line CI check that `MultiNlpEngine` still imports under the latest upstream Presidio"), this REQ promotes that mitigation to a deliverable. A small CI job (one shell step in the existing CI workflow, or a tiny new workflow file) MUST:

1. Periodically (or on push to a designated tracking branch) check out the latest upstream `microsoft/presidio` `main` AND apply the fork's `MultiNlpEngine` patch on top.
2. Run a smoke check: `python -c "from presidio_analyzer.nlp_engine.multi_nlp_engine import MultiNlpEngine"` (or equivalent). Failure indicates upstream changed something incompatible with the fork patch.
3. The CI job's failure does NOT block production deploys (the production fork pin is unchanged), but it produces a maintainer-visible signal.

**Acceptance:**
- The CI step exists in the fork repo's CI configuration; can be a single shell line or a 5–10 line workflow snippet.
- A documented failure path: when the smoke fails, the maintainer (Pablo) is the named owner of the upstream-merge response; resolution lives outside this feature.
- If implementing the CI step is infeasible within this feature's scope (e.g., the fork repo lacks a CI runner configuration), this REQ MAY be marked "deferred to follow-up" in the implementation report — but only with explicit operator sign-off; silent omission is not acceptable.

**Spec refs:** MODULE-001 (fork-side), RISK-003.

### Performance (PERF) — informational baselines, no SLOs

#### PERF-001: Per-request latency expectations (bound to specific calibration phrases)
Per-request latency on the `de` path (transformer inference on CPU) increases substantially relative to spaCy. Baseline expectation per RESEARCH-007 §4 (model survey, `xlm-roberta-large` ~2.2 GB on disk, transformer inference latency CPU-bound): single-request p50 in the **0.5–3 second** range for typical short prose; long-document p50 (>500 tokens) dominated by `stride: 16` window count. **No hard SLO** per CLARIFICATION-007 Q4.

**Reproducible latency baseline (anchored).** To make future latency regressions detectable, the post-implementation calibration report MUST capture per-request latency for these specific anchor inputs:

- **Short anchor (`de` short prose):** the bare-noun fixture `Personalausweis` (one of the new `expect_clean: true` fixtures from REQ-009) — minimal input, exercises the transformer pipeline at the lower bound of input size.
- **Sentence-context anchor (`de` representative PII):** the existing fixture `Personalausweis Nummer L01X00T47.` from `tests/eval/fixtures/de.yaml` — representative of real-world short-PII input.
- **Long-document anchor (`de` >500 tokens):** the long-text fixture added per REQ-009b (item 3) — exercises `stride: 16` windowing. (This anchor is now an explicitly-named fixture per REQ-009b; EDGE-006's "at least one fixture" requirement is satisfied by REQ-009b's concrete fixture.)

**Warm-up vs. steady-state capture.** For each anchor, the report MUST capture **two** numbers, separately, to characterize both production-restart-worst-case and steady-state behavior:

- **Warm-up (first request after `MultiNlpEngine.load()` completes):** a single run, no warm-up discard. This is what production users hit on the first request after a container restart — driven by PyTorch graph caching, OS page-cache warm-up, and any `transformers` lazy-init cost.
- **Steady-state (median over N≥5 runs *after* the warm-up run):** N is recorded; the median of these N runs is the steady-state baseline. Warm-up run is NOT included in the N.

Both numbers appear in the report alongside each anchor, e.g.: `Personalausweis — warm-up: 4.2s; steady-state median (N=5): 0.9s`. The two numbers together prevent the baseline from understating real-world worst-case (warm-up alone would overstate steady-state) or overstating it (median including warm-up under-counts the cold first request).

The same three anchors and the warm-up / steady-state split are re-measured on every future change that touches the `de` NLP path. Documentation only (no SLO), but the anchors convert "wide range" into a stable comparison baseline.

**Spec refs:** MODULE-001, REQ-009, REQ-009b, EDGE-006.

#### PERF-002: Cold-start expectations and model-load-once
Container cold start increases because the analyzer loads three model families at boot (`en_core_web_lg`, `de_core_news_sm`, `xlm-roberta-large-finetuned-conll03-german`). Plausible total per RESEARCH-007 §2.4: 10–30 seconds. All three are loaded **exactly once** during startup (per REQ-001's model-load-once invariant) — the cold-start cost is paid up front, not amortized across requests. `MultiNlpEngine.process_text` does NOT trigger model load on the request path. Healthcheck `start_period` is set per REQ-014's measurement-driven formula.

**Behavioral acceptance for the model-load-once invariant.** REQ-001's existing acceptance is unit-test-mock based (patching loaders and asserting call count == 1). To complement that with a behavioral signal that survives mock-removal, the implementation MUST also produce a **structured startup-log line** identifying each model load with a timestamp — e.g., `LOADED en_core_web_lg at <ts>`, `LOADED de_core_news_sm at <ts>`, `LOADED xlm-roberta-large-finetuned-conll03-german at <ts>`. The implementation report includes a captured analyzer-startup log excerpt confirming each line appears exactly once and all three appear before the HTTP server binds (i.e., before any `/health` 200 is served). This is a one-time-during-implementation verification, not a CI-enforced check.

**Restart traffic-spike acknowledgement.** The analyzer is not horizontally scaled (single container per MODULE-007). On restart (graceful or crash-recovery), the 10–30s cold-load window blocks Redakt's `de` request path until `MultiNlpEngine.is_loaded() == True` for all languages — REQ-005a's "no partial 200" contract converts this to either `/health` 503 or connection-refused at the orchestrator. Redakt-side, this surfaces as 5xx / timeouts on the affected requests. Operator-level mitigations (e.g., orderly redeploy with health-gated cutover, blue/green rollover) are **out of scope** for this feature; they are noted here so the operator-facing characteristic is documented and not a surprise. The analyzer is not designed to serve traffic during cold-start; the API contract makes this visible (REQ-005a + REQ-014 together).

**Spec refs:** MODULE-007, REQ-001, REQ-005a, REQ-014.

#### PERF-003: Image size growth
Analyzer image grows materially due to the ~2.2 GB transformer weights baked in. CLARIFICATION-007 Q4 sets no cap. Build-time CI minutes also grow (the snapshot_download is cache-busted on every image rebuild unless the layer is preserved). Documentation only. **Spec refs:** MODULE-007.

### Security (SEC)

#### SEC-001: No new PII storage paths
The transformer model runs read-only at inference; HF `pipeline()` doesn't transmit text outside the analyzer container. Audit logging continues to record metadata only — entity counts, types, language, source — never the original text or actual PII (`src/redakt/services/audit.py:log_detection`, RESEARCH-007 §16.2). API contract preservation (REQ-010) keeps the existing input-validation surface (`src/redakt/utils.py:39-55` allow-list validation; `config.py:18` `max_text_length: 512_000`) unchanged.

**Input-size compute scaling note.** Transformer inference cost on the `de` path is approximately linear in input length × stride density (`stride: 16` per REQ-003 / EDGE-006). A worst-case 512_000-character German input fans out to many overlapping transformer windows — the existing `max_text_length: 512_000` ceiling (Redakt-side) is the relevant DoS-amplification ceiling. No new input-validation surface is introduced by this feature; the analyzer's per-request compute budget is implicitly bounded by Redakt's input-length cap. PERF-001's long-document anchor (REQ-009b item 3) captures the latency profile at this scale class, providing a baseline against which abuse-pattern requests can be measured.

**Spec refs:** MODULE-001, REQ-010.

#### SEC-002: Recognizer-registry floor preserved
Per REQ-011. The recognizer floor encodes the country-PII detection contract; loosening it would silently degrade detection coverage. Acceptance: see REQ-011. **Spec refs:** MODULE-002, REQ-011.

#### SEC-003: Model supply-chain trust boundary
Model weights are baked at image build time via `huggingface_hub.snapshot_download` and `AutoModelForTokenClassification.from_pretrained` (`install_nlp_models.py:91, 94-95`). The trust boundary is the HF Hub at build time. REQ-013 pins the model `revision` declaratively in `multi.yaml` AND verifies an artifact-level SHA-256 digest manifest (`multi.model_digests.json`) on every build to detect tampering or accidental drift in HF-served bytes under the pinned revision. The manifest is the supply-chain trust anchor; revision pinning alone is insufficient because HF Hub can mutate the bytes served under a given revision. Build-time download is the only network egress to HF Hub; runtime is offline-after-build. **Spec refs:** MODULE-003, REQ-013.

#### SEC-004: Internal-only Presidio service surface
The Presidio Analyzer container is reachable only on the internal compose network (`docker-compose.yml:21-25`); no external port. Unchanged by this feature (RESEARCH-007 §16.1). **Spec refs:** MODULE-007.

### Privacy

#### PRIV-001: No PII at rest, no PII in audit log
Same as SEC-001. The transformer-driven NLP changes how PII is *detected* but not how it is *stored* or *logged*. Audit log behavior (`audit.log_detection`) is byte-for-byte preserved. **Spec refs:** MODULE-001, SEC-001.

#### PRIV-002: Client-side PII mapping unchanged
The anonymize endpoint still returns the placeholder-to-original mapping to the browser (or AI agent) for client-side deanonymization. Backend stays stateless. No PII at rest. Unchanged by this feature. **Spec refs:** MODULE-001 (no change).

### Reliability

#### REL-001: Build-time failure surface
The HF model download and the `install_nlp_models.py` dispatch (REQ-004) are the principal new failure surfaces. Failures must be loud and fail-fast (FAIL-001). **Spec refs:** MODULE-003, FAIL-001.

#### REL-002: Runtime failure surface
At runtime, model files are loaded from disk inside the image — no network dependency. The principal new failure mode is "auxiliary spaCy German model fails to load" (FAIL-002) or "MultiNlpEngine receives a request for an unconfigured language" (FAIL-003). Both must produce clear errors, not silent degraded state. **Spec refs:** MODULE-001, FAIL-002, FAIL-003.

#### REL-003: Calibration data is development-time only
The `calibration corpus` is a development-time tool, not a request-path dependency. If fixtures are missing at runtime, the request path is unaffected (FAIL-004). **Spec refs:** MODULE-004.

---

## Edge Cases

#### EDGE-001: Code-switched text (`asymmetric routing` failure-mode flip)
**Scenario:** A request body contains a German paragraph with English names embedded (or vice versa) and `language: auto`. **Behavior:** lingua-py picks one language; the matching engine runs. Under today's uniform-spaCy multilingual setup, this would over-flag both languages' entities; under `asymmetric routing`, it produces an under-flagging failure mode — entities in the non-selected language are missed (RESEARCH-007 §12.2; ADR 0001 §Neutral observations). **Resolution:** accepted limitation per CLARIFICATION-007 Q6; documented in REQ-012; users override via the explicit `language` parameter. No test coverage required beyond non-crash. **Spec refs:** MODULE-001, MODULE-008, REQ-012.

#### EDGE-002: German common nouns from the broader class
**Scenario:** A bare `broader class` noun (e.g., `Personalausweis`) is submitted with `language: de`. **Expected behavior:** zero entity flags of any kind (CLARIFICATION-007 Q2 exit criterion). **Validation:** REQ-008 (calibration), REQ-009 (CI fixtures), REQ-015 (pre-deploy in-Redakt probe). **Spec refs:** MODULE-001, MODULE-005, REQ-008, REQ-009, REQ-015.

#### EDGE-003: Common-noun + adjacent number
**Scenario:** A real PII fixture like `Steuer-IdNr. 12345678901` or `Personalausweis Nummer L01X00T47.` is submitted. **Expected behavior:** the `country recognizer` for the relevant document fires on the numeric pattern (DE_TAX_ID, DE_ID_CARD); the bare noun does NOT contribute a spurious `PERSON` flag. RESEARCH-007 §4.5 sentence-context probe confirms `Hans Müllers Personalausweis ist abgelaufen.` flags only `Hans Müllers` as PER, not `Personalausweis`. **Validation:** the existing `de.yaml` PII fixtures (`Personalausweis Nummer L01X00T47.`, `Krankenversicherungsnummer A123456787.`, `Reisepassnummer C01X00T47.`) all stay PASS under `expect.issubset(found)`, AND the `redakt:` line in the post-implementation calibration report no longer carries the `PERSON(0.85)` over-flag. **Spec refs:** MODULE-001, MODULE-002, REQ-011.

#### EDGE-004: Lingua-py mis-detection
**Scenario:** Lingua-py auto-detect returns the "wrong" language for a paragraph (e.g., a short English snippet classified as German). **Behavior:** the chosen engine runs deterministically; no fallback chaining. Users can override with explicit `language`. RESEARCH-007 §1.3 documents lingua's existing en/de/es config and minimum-2-languages requirement. **Resolution:** accepted limitation; existing behavior unchanged. **Spec refs:** MODULE-001, REQ-012.

#### EDGE-005: PERSON name that *is* a German common noun
**Scenario:** A surname like `Schmidt` (also "blacksmith"), `Müller` (also "miller"), `Bauer` (also "farmer"), submitted in sentence context. **Expected behavior:** the transformer disambiguates from sentence context. RESEARCH-007 §4.5 control: `Anna Schmidt arbeitet bei der Beispiel AG in Berlin.` correctly returns `PER AnnaSchmidt 1.0`, `ORG BeispielAG 1.0`, `LOC Berlin. 1.0`. **Validation:** existing `generic.yaml` fixture covering this stays PASS; `detection-set non-regression` envelope is preserved on `de` for this case. **Spec refs:** MODULE-001, MODULE-005.

#### EDGE-006: Long German text exceeding tokenizer max length
**Scenario:** A `de`-routed request with text >512 transformer tokens. **Expected behavior:** the HF pipeline's `stride: 16` (configured in `multi.yaml` per REQ-003) windows the input and aggregates entities across overlapping windows. `aggregation_strategy: max` collapses sub-token spans. **Validation:** the concrete >500-token German fixture is added per REQ-009b (item 3) and exercised during calibration; result transcript captured. The "at least one" requirement is satisfied by REQ-009b's explicit fixture rather than implicit backfill. **Spec refs:** MODULE-001, MODULE-002, REQ-009b, PERF-001.

#### EDGE-007: Empty text input
**Scenario:** `POST /api/detect` with empty string. **Behavior:** `src/redakt/routers/detect.py:67-72` short-circuits empty text before reaching Presidio; `MultiNlpEngine.process_text` is not invoked. Unchanged by this feature. **Spec refs:** MODULE-001 (no-op path).

#### EDGE-008: Defensible `BIC` ORG flag
**Scenario:** A request body containing the bare token `BIC` (SWIFT bank-identifier-code term) is submitted with `language: de`. **Behavior:** the transformer flags `BIC` as ORG 0.998 (RESEARCH-007 §4.5 Set B). This is defensible (BIC overwhelmingly appears in bank-name contexts in CoNLL-03 training data) but may surface as an unwanted detection in production. **Resolution:** documented; if it becomes a customer issue, the next step is a `de`-side ORG floor entry (e.g., `entity_score_thresholds: {"ORGANIZATION": 0.99}` for `de`), not a model swap. Out of scope for this feature; flagged for future-iteration calibration. **Spec refs:** MODULE-001, MODULE-006.

---

## Failure Scenarios

#### FAIL-001: Transformer model download fails at image build
**Trigger:** HF Hub unreachable, model revision deleted, network failure during `huggingface_hub.snapshot_download`, or `install_nlp_models.py` dispatch fails (engine name unknown — REQ-004 not landed). **Expected behavior:** `docker compose build presidio-analyzer` exits non-zero with a clear error message identifying the failed model and the cause. No partial-image deploy. CI catches this immediately. **Mitigation:** REQ-013 pins model revision; A/B fallback to `Davlan/bert-base-multilingual-cased-ner-hrl` documented (ADR 0001 §Alternative F) if HF Hub serves the primary model unreliably. **Spec refs:** MODULE-003.

#### FAIL-002: Any sub-engine load failure at runtime (en or de; spaCy or transformer)
**Trigger:** Any one of the configured sub-engines fails to load at analyzer startup. Concrete cases (non-exhaustive):
- `en_core_web_lg` model file missing or corrupt.
- `de_core_news_sm` model file missing or corrupt (auxiliary spaCy German model — required for the `de` row's lemma/punct surface).
- `xlm-roberta-large-finetuned-conll03-german` weight files missing, corrupt, or failing the artifact-digest check (REQ-013).
- `transformers` / `torch` import failure inside the analyzer container.
- HF tokenizer fails to instantiate (e.g., `sentencepiece` missing).

**Expected behavior:** the analyzer process exits non-zero during startup before the HTTP server binds; Docker's restart policy may retry, but it will keep failing as long as the underlying cause persists. The healthcheck stays unhealthy past `start_period`; logs identify which sub-engine failed and why. **No silent fallback** to a degraded state — `MultiNlpEngine.is_loaded()` MUST return False if any sub-engine is unloaded, and `/health` MUST NOT return 200 in that state (REQ-005a). Partial-engine startup is not allowed: if any of `{en/spaCy, de/spaCy-aux, de/transformer}` fails to load, the analyzer fails as a whole. Fail loud, fail fast.

**Validation:** unit tests for `MultiNlpEngine.load()` parametrized across the three sub-engine slots — each test mocks one loader to raise and asserts (a) `load()` propagates a clear exception, (b) `is_loaded()` returns False, and (c) the analyzer process exit path (or `/health` 503) is exercised in an integration test for at least one of the cases. **Spec refs:** MODULE-001, REQ-005a.

#### FAIL-003: `MultiNlpEngine` receives a request for an unconfigured language
**Trigger:** A `language` value not in `MultiNlpEngine.get_supported_languages()` reaches `process_text(text, language)`. **Expected behavior:** `MultiNlpEngine` raises `ValueError` with a clear "unsupported language: <lang>" message. Redakt's request validation already constrains `language ∈ settings.supported_languages` before reaching Presidio (`detect.py:run_detection`), so this is a defense-in-depth case. **Acceptance:** unit test in `MultiNlpEngine` for the unconfigured-language path. The Redakt-side response stays consistent with the existing API contract (HTTP 422 from Pydantic validation if upstream; if it slips through, HTTP 500 with no PII in the message body). **Spec refs:** MODULE-001, REQ-010.

#### FAIL-004: Calibration corpus / fixtures not present at runtime
**Trigger:** `tests/eval/fixtures/` not bundled into a deployment artifact. **Expected behavior:** non-blocking; the calibration tool and eval suite are development-time only. The Redakt request path is unaffected. **Validation:** none required (request-path independence is structural). **Spec refs:** MODULE-004 (development-only).

#### FAIL-005: Build-time install dispatcher silently passes on a bad row
**Trigger:** A `models[]` row with a typo'd `engine: spcy` (instead of `spacy`) lands in `multi.yaml`. **Expected behavior:** REQ-004's extended dispatcher rejects unknown per-row engine values with a clear error (not a silent skip that produces an image lacking the expected model artifact). **Validation:** unit test in `install_nlp_models.py`'s test module exercises the unknown-engine and missing-engine-key cases. **Spec refs:** MODULE-003, REQ-004.

#### FAIL-006: Calibration results diverge from §4.5 probe
**Trigger:** REQ-015 in-Redakt probe shows entity flags on phrases that were empirically clean in RESEARCH-007 §4.5. **Expected behavior:** stop, fall back to `Davlan/bert-base-multilingual-cased-ner-hrl` per REQ-015, re-run. **Validation:** REQ-015's transcript shows convergence with the §4.5 expectation before implementation is declared done. **Spec refs:** MODULE-001, REQ-015.

---

## Implementation Constraints

- **No API contract changes.** Frozen per CLARIFICATION-007 §"Constraints" and REQ-010.
- **No frontend changes.** Out of scope per CLARIFICATION-007 Q5d.
- **Per-entity score floor shape stays `dict[str, float]`.** Frozen per CLARIFICATION-007.
- **spaCy stays a hard dependency.** Required by `LemmaContextAwareEnhancer` and `PhoneRecognizer` context handling (RESEARCH-007 §3.5).
- **Recognizer-registry floor preserved.** REQ-011.
- **No per-sentence or per-token language routing.** Out of scope per CLARIFICATION-007 Q6 (i).
- **No GPU deployment shape.** CPU-only is the target per CLARIFICATION-007 Q4b.
- **CPU-only operation.** Models loaded with default device; no `device=cuda` overrides.
- **Model artifacts baked at image build time.** No runtime download; the `TRANSFORMERS_CACHE` mount alternative is documented but not adopted (RESEARCH-007 §9.4).
- **Redakt-side code is touched minimally** — `src/redakt/config.py:14` defaults are the only Redakt-side production code change; everything else is in the Presidio fork (`presidio/.../`), Docker config, fixtures, and docs.
- **Fork-side diffs are clearly delimited.** Per RESEARCH-007 §11.3, `MultiNlpEngine` and the `install_nlp_models.py` extension are wrapped in `# === redakt: MultiNlpEngine ===` style markers and centralized in as few files as possible to ease future upstream-Presidio merges.

---

## Modules

Every REQ/EDGE/FAIL is mapped to at least one MODULE-XXX via `Spec refs` in this section.

### MODULE-001: `MultiNlpEngine` (deep)

**Public Interface:**
- `MultiNlpEngine(models: list[dict], ner_model_configuration: NerModelConfiguration | None = None)` — constructor.
- `load() -> None` — load all sub-engines.
- `is_loaded() -> bool` — True iff every sub-engine is loaded.
- `process_text(text: str, language: str) -> NlpArtifacts` — dispatch by language.
- `process_batch(texts, language, **kw) -> Iterator[tuple[str, NlpArtifacts]]` — dispatch by language.
- `is_stopword(word: str, language: str) -> bool` — dispatch by language.
- `is_punct(word: str, language: str) -> bool` — dispatch by language.
- `get_supported_entities() -> list[str]` — union across sub-engines.
- `get_supported_languages() -> list[str]` — keys of internal sub-engine map.
- `get_nlp(language: str) -> Language` — return the underlying spaCy `Language` for that sub-engine.

**Hides:**
- Per-language engine routing logic (the `self._sub_engines[language]` dispatch).
- Cross-engine load coordination: `load()` and `is_loaded()` together guarantee atomic two-phase startup — `load()` is invoked exactly once at analyzer startup and either succeeds for all sub-engines or raises (no partial state); `is_loaded()` returns True only when every sub-engine reports loaded; `process_text` / `process_batch` do not lazy-load on the request path (REQ-001 model-load-once invariant; REQ-005a readiness contract).
- The pipeline-shape difference between spaCy (`tokenizer + tagger + lemmatizer + parser + ner`) and transformers (`spaCy tokenizer + lemmatizer` + `hf_token_pipe` for NER).
- The auxiliary `de_core_news_sm` spaCy model load that powers the German lemma-aware enhancer path (`LemmaContextAwareEnhancer` reads `nlp_artifacts.lemmas`).
- Per-sub-engine `NerModelConfiguration` differences (e.g., `low_score_entity_names: [ORG, ORGANIZATION]` for en, calibrated values for de).

**Risk:** **HIGH.** On the request path; the entire analyzer depends on `MultiNlpEngine.process_text` for every detect call. Crash failures are recoverable via container restart with no irreversible side effects, but the dominant production risk is **silent wrong-engine routing**: a one-character bug in the dispatch logic (`if language == "en"` vs `if language == "de"`) flips behavior to wrong-but-valid output that produces no exception and no error log. Existing `expect.issubset(found)` fixtures cannot detect this — they only catch missing entities. The new `expect_clean: true` fixtures (REQ-009) catch the German-side broader-class over-detection class but do **not** catch a hypothetical en-routes-to-de (or de-routes-to-en) swap. The new positive auto-detect routing test (REQ-016) is the structural mitigation for the silent-failure mode. HIGH justified by silent-failure mode + production blast radius (every misrouted request silently mis-detects PII for the lifetime of the bug). This Risk tier propagates to `/sdd:code-review` Step 4b which scales review depth.

**Spec refs:** REQ-001, REQ-002, REQ-005a, REQ-010, REQ-010a, REQ-015, REQ-016, EDGE-001, EDGE-002, EDGE-003, EDGE-004, EDGE-005, EDGE-006, EDGE-007, EDGE-008, FAIL-002, FAIL-003, FAIL-006, SEC-001, PRIV-001, REL-002, PERF-001, PERF-002.

---

### MODULE-002: Multi-engine config schema (`multi.yaml` + validator branch + digest manifest) (shallow — justified)

**Public Interface:** two declarative artifacts under `presidio/presidio-analyzer/presidio_analyzer/conf/`:
- `multi.yaml` — top-level `nlp_engine_name: multi`. Per-row `models[]`: `lang_code`, `engine`, `model_name`, optional `revision`, `ner_model_configuration`.
- `multi.model_digests.json` — checked-in supply-chain trust anchor (REQ-013). Per-file SHA-256 digests of model weights, keyed by `(model_name, revision)`. Updated by deliberate, reviewable commit only (never auto-overwritten in CI).

Plus the `multi` branch in `ConfigurationValidator.validate_nlp_configuration`.

**Hides:** Nothing structural — the files are configuration data. The structural depth lives in `MultiNlpEngine` (MODULE-001) and the install dispatcher (MODULE-003). MODULE-003 is responsible for *reading and writing* the digest manifest at build time; MODULE-002 *owns* it as source-controlled config.

**Justification for shallow:** Configuration files are intrinsically declarative. Imposing module depth on a YAML produces ceremony without information hiding. The `ConfigurationValidator` branch is a small predicate, not a unit of logic worth deepening.

**Risk:** Low. Schema mistakes surface at load time with clear errors.

**Spec refs:** REQ-003, REQ-007, REQ-011, REQ-013, EDGE-003, EDGE-006, SEC-002.

---

### MODULE-003: `install_nlp_models.py` dispatcher extension (medium-deep)

**Public Interface:** `_download_model(engine_name: str, model_name: Union[str, Dict[str, str]], revision: str | None = None) -> None` (extended signature; `revision` parameter added for REQ-013). New `multi` branch in the dispatch path that iterates `nlp_configuration["models"]` and calls `_download_model(row["engine"], row["model_name"], row.get("revision"))` per row.

**Hides:** Per-engine download orchestration — spaCy via `spacy.cli.download`, HF via `huggingface_hub.snapshot_download` + `AutoModelForTokenClassification.from_pretrained`. Cache validation. Revision-pinning logic. **Digest-manifest read/write logic** — the dispatcher reads `multi.model_digests.json` (owned by MODULE-002 as source-controlled config) on every build, recomputes per-file SHA-256 of downloaded weights, fails the build on mismatch, and (on the first known-good build) writes a fresh manifest for operator review. The split is: MODULE-002 owns the file in source control; MODULE-003 owns the read/write/verify logic.

**Risk:** Medium. Build-time only — failures surface in CI before any runtime test, so the blast radius is bounded. But silent passes (FAIL-005) are dangerous because they produce images lacking expected model artifacts.

**Spec refs:** REQ-004, REQ-013, FAIL-001, FAIL-005, REL-001, SEC-003.

---

### MODULE-004: `calibration corpus` (shallow — justified)

**Public Interface:** the union of phrases in `tests/eval/fixtures/*.yaml`, walked by `tools/calibration_report.py:116` via `tests/eval/_loader.load_all_phrases()`. No separate corpus file.

**Hides:** Nothing — the corpus is the data itself.

**Justification for shallow:** Single source of truth (fixtures) feeds both CI and calibration. Depth would mean introducing a separate corpus file that drifts from fixtures; rejected by design (RESEARCH-007 §7.2).

**Risk:** Low. Calibration is a development-time tool; missing fixtures don't affect the request path (FAIL-004).

**Spec refs:** REQ-008, REQ-015, EDGE-002, REL-003.

---

### MODULE-005: Eval fixtures + harness (medium)

**Public Interface:** `tests/eval/fixtures/de.yaml` gains 15 new entries with `expect_clean: true`. The pytest harness (`tests/eval/test_calibration.py`, `_loader.py`) consumes them via the existing `expect_clean` branch (verified at `test_calibration.py:46-50`).

**Hides:** Per-fixture comparison logic (`expect.issubset(found)` for the normal branch; `found == []` for `expect_clean`). Fixture parametrization (`@pytest.mark.parametrize` at `test_calibration.py:38`). Conftest's session-scoped Redakt-health skip (`tests/eval/conftest.py:31-36`).

**Risk:** Medium. Test infra is the only place where the over-detection bug becomes a CI signal; structural mistakes here re-introduce the `issubset` blind spot the feature is closing.

**Spec refs:** REQ-006, REQ-007, REQ-008, REQ-009, REQ-009b, EDGE-002, EDGE-003, EDGE-005.

---

### MODULE-006: Threshold defaults (Redakt + analyzer) (shallow — justified)

**Public Interface:** Configuration values:
- Redakt-side: `src/redakt/config.py:14`'s `entity_score_thresholds: dict[str, float]` defaults.
- Analyzer-side: `multi.yaml`'s per-row `ner_model_configuration` blocks, specifically `low_score_entity_names` and `low_confidence_score_multiplier` for the `de` row.

**Hides:** Nothing structural — the values themselves are the artifact.

**Justification for shallow:** The values are calibration outputs, not abstractions. Depth would mean wrapping them in a class for ceremony.

**Risk:** Medium. Wrong values cause silent under- or over-redaction in production. Mitigation: REQ-006 / REQ-007 acceptance now hinges on a four-bar stopping condition — (1) negative bar (existing fixtures + `expect_clean` fixtures stay PASS), (2) held-out positive bar (entity-conditional per Amendment 2026-05-06; concretely REQ-009b's DE LOCATION true-positive assertion — DE DATE_TIME excluded by amendment), (3) score-distribution justification in the committed calibration report, (4) reproducibility within ±0.05. The bidirectional bar plus held-out positives plus written rationale catches wrong-direction tuning AND prevents a one-shot tune that doesn't replay (the original Medium framing's "circular acceptance" critique is closed by bars 2–4).

**Spec refs:** REQ-006, REQ-007, REQ-009b, EDGE-008.

---

### MODULE-007: Docker / compose wiring (shallow — justified)

**Public Interface:** root `docker-compose.yml` `presidio-analyzer` service block (`dockerfile: Dockerfile.transformers`, `args.NLP_CONF_FILE: presidio_analyzer/conf/multi.yaml`, optionally bumped `start_period`). `Dockerfile.transformers` itself is unchanged in this feature.

**Hides:** Nothing. Configuration.

**Justification for shallow:** Compose wiring is declarative. Depth would be ceremony.

**Risk:** Medium. Wiring mistakes prevent the whole stack from starting; the failure surface is loud (REQ-005 acceptance: container responds 200 to `/health`).

**Spec refs:** REQ-005, REQ-005a, REQ-014, PERF-002, PERF-003, SEC-004.

---

### MODULE-008: Documentation (shallow — justified)

**Public Interface:** updated `docs/v1-feature-spec.md` (code-switched-text note) and `docs/presidio-integration.md` (NLP Engine Options section reflecting `MultiNlpEngine` / `asymmetric routing`).

**Hides:** Nothing. Documentation.

**Justification for shallow:** Operator-facing docs are prose, not abstractions.

**Risk:** Low.

**Spec refs:** REQ-012, EDGE-001.

---

## Validation Strategy

### Unit Tests (Presidio fork side)

- **MODULE-001 / REQ-001:** `MultiNlpEngine.process_text(text, "en")` dispatches to the spaCy sub-engine; `process_text(text, "de")` dispatches to the transformers sub-engine. `is_stopword`, `is_punct`, `get_supported_entities`, `get_supported_languages`, `get_nlp`, `is_loaded` per language.
- **MODULE-001 / FAIL-002:** `MultiNlpEngine.load()` raises a clear exception when a sub-engine fails to load (mock the spacy/transformers loader to raise).
- **MODULE-001 / FAIL-003:** `MultiNlpEngine.process_text(text, "fr")` raises `ValueError` with a clear "unsupported language" message.
- **MODULE-003 / REQ-004:** `_download_model` with `engine_name="multi"` iterates `nlp_configuration["models"]` correctly; one spacy + one transformers row.
- **MODULE-003 / FAIL-005:** `_download_model` rejects unknown per-row engine values; rejects `models[]` rows missing the `engine` key.

### Integration Tests

- **MODULE-002 / REQ-003:** `AnalyzerEngineProvider.create_engine()` constructs a working analyzer from `multi.yaml` (no exception; engine.is_loaded() True for both languages).
- **MODULE-007 / REQ-005:** `docker compose build presidio-analyzer && docker compose up presidio-analyzer` produces a healthy container (HTTP 200 on `/health` within `start_period`).
- **MODULE-005 / REQ-009 / REQ-009b / REQ-010:** `uv run pytest tests/eval/` returns 58/58 PASS (41 existing + 15 new `expect_clean: true` broader-class + 2 new held-out positive / long-document anchor per REQ-009b — DE LOCATION + long-doc only; DE DATE_TIME dropped per Amendment 2026-05-06). API contract preservation (REQ-010): `tests/` (unit + integration, ignoring eval and e2e) green; `tests/e2e/` green; OpenAPI schema diff zero.
- **MODULE-001 (downstream consumer) / REQ-010a:** API-shape regression contract test passes — byte-identical JSON envelope + headers across `POST /api/detect`, `POST /api/anonymize`, `POST /api/deanonymize` for representative inputs (snapshot under `tests/contracts/`).
- **MODULE-001 / REQ-016:** end-to-end `language: auto` routing test passes — German input routes to the transformer sub-engine, English input routes to the spaCy sub-engine, verified via `?verbose=true` analysis explanations.
- **MODULE-002 / REQ-011:** `default_recognizers.yaml` diff between `main` and feature branch (Redakt repo AND fork repo) shows additions only (or no change); diffs captured under `reports/req-011-recognizer-diffs.md`.

### Edge Case Tests

- **EDGE-002:** the 15 `expect_clean: true` fixtures (REQ-009) cover the broader-class set; pass = no entities flagged.
- **EDGE-003:** existing `de.yaml` PII fixtures (`Personalausweis Nummer L01X00T47.`, `Krankenversicherungsnummer A123456787.`, `Reisepassnummer C01X00T47.`) stay PASS, AND post-implementation calibration report's `redakt:` line for these phrases no longer carries `PERSON(0.85)` — verified by diff against `reports/post-fix-2.md`.
- **EDGE-005:** existing `generic.yaml` fixture `Anna Schmidt arbeitet bei der Beispiel AG in Berlin.` stays PASS (lingua-py classifies as `de`; transformer flags PERSON on `Anna Schmidt`; LOC and ORG are extras within the issubset envelope).
- **EDGE-006:** the long-document fixture from REQ-009b (item 3) exceeds 500 transformer tokens; tokenized length recorded in fixture or report; calibration result transcript captured.
- **EDGE-007:** existing test for empty-text short-circuit continues to pass.
- **EDGE-008:** `BIC` flagged as ORG; documented (no test required — defensible behavior).

### Performance Validation

- **PERF-001 / PERF-002 / PERF-003:** capture single-request latency p50 on `de` path, container cold-start time, and image size in the post-implementation calibration report. No SLO; numbers are baseline documentation.
- **REQ-014:** cold-start measurement drives `start_period` adjustment if needed.

### Manual Verification (operator-driven)

- **`tools/calibration_report.py --raw --out` against the same corpus** before and after implementation. The "before" baseline is `reports/post-fix-2.md`. The "after" report is committed alongside the feature branch under `reports/`. Operator (Pablo) reviews:
  - All 41 existing fixtures stay PASS.
  - All 15 new `expect_clean: true` fixtures stay PASS with `redakt: —`.
  - The headline-bug `de.yaml` fixtures no longer carry the spurious PERSON(0.85).
  - Per-entity floor and `low_score_entity_names`/multiplier values align with the new `graded scores` distribution.
- **REQ-015 in-Redakt probe** transcript matches the §4.5 expectation.

---

## Dependencies and Risks

### External / library dependencies

- **Hugging Face Hub** (build-time only) — `huggingface_hub.snapshot_download` for transformer weights. Trust boundary at build time; revision pinned per REQ-013.
- **`transformers`** Python package (already required by Presidio's `transformers` extra).
- **`torch`** (CPU-only).
- **`sentencepiece`** + **`protobuf`** (required by `xlm-roberta-large-finetuned-conll03-german` tokenizer; the model emits a `Tokenizer does not support real words, using fallback heuristic` warning that is harmless per RESEARCH-007 §4.5 closing notes).
- **`spacy_huggingface_pipelines`** (Presidio dep; provides `hf_token_pipe`).
- **`de_core_news_sm`** spaCy model (~14 MB, baked at image build).
- **`en_core_web_lg`** spaCy model (already baked; unchanged).

### Risks

#### RISK-001 (HIGH): Transformer model download / availability
**Trigger:** HF Hub rate-limit, outage, or model-revision deletion at image build time. **Impact:** `docker compose build presidio-analyzer` fails. **Mitigation:** pin model revision (REQ-013); document `Davlan/bert-base-multilingual-cased-ner-hrl` as the validated A/B fallback (ADR 0001 §Alternative F); CI catches build failures immediately. **HF rate-limit mitigation:** anonymous HF Hub egress is rate-limited per-IP and modest; CI builds running many parallel jobs from one IP can hit HTTP 429 even with a pinned revision. Mitigation: configure `HUGGINGFACE_HUB_TOKEN` (or `HF_TOKEN`) in the CI environment for authenticated downloads (higher per-account rate limit); the token is read by `huggingface_hub.snapshot_download` automatically when present. Document the env-var requirement in `presidio/Dockerfile.transformers`'s setup notes / `docs/presidio-integration.md` so operators with private CI runners know to provision it. The token is build-time only and is NOT baked into the image.

#### RISK-002 (MEDIUM): Calibration drift from RESEARCH-007 §4.5
**Trigger:** Wiring the model into the full Presidio pipeline (`spacy_huggingface_pipelines.hf_token_pipe`, `aggregation_strategy: max`, `stride: 16`) produces detection behavior that diverges from the standalone HF-pipeline probe. **Impact:** broader-class fix doesn't materialize. **Mitigation:** REQ-015 (in-Redakt re-probe of the 20 phrases) gates implementation completion; FAIL-006 specifies fallback behavior.

#### RISK-003 (MEDIUM): Indefinite Presidio-fork maintenance
**Trigger:** Every upstream Presidio merge re-applies `MultiNlpEngine` + `install_nlp_models.py` extension as conflicts. Upstream is unlikely to accept `MultiNlpEngine` because the single-engine-per-config-file stance is intentional simplicity (RESEARCH-007 §11.3). **Impact:** ongoing maintenance cost. **Mitigation:** keep diffs in clearly-delimited blocks (`# === redakt: MultiNlpEngine ===` markers); centralize in as few files as possible; document in fork's `docs/` change-log; **the "one-line CI check that `MultiNlpEngine` still imports under the latest upstream Presidio" is now operationalized as REQ-017** (promoted from a Risk-only mitigation to a deliverable so it actually ships).

#### RISK-004 (MEDIUM): Threshold re-tuning produces silent regressions
**Trigger:** Empirical re-tuning under `graded scores` (REQ-006, REQ-007) lands on values that drop legitimate German LOCATION / DATE_TIME hits or let through `broader class` over-flags. **Impact:** silent under- or over-redaction in production. **Mitigation:** acceptance for REQ-006/007 hinges on the full fixture set passing AND the `expect_clean` fixtures staying PASS — bidirectional bar catches wrong-direction tuning. Calibration report committed alongside threshold changes; never change thresholds without a corresponding report.

#### RISK-005 (LOW): Cold-start exceeds healthcheck `start_period`
**Trigger:** Loading three model families at boot (en_core_web_lg + de_core_news_sm + xlm-roberta-large) exceeds the existing 30s `start_period`. **Impact:** healthcheck stays unhealthy; compose marks the analyzer container failed. **Mitigation:** REQ-014 measures cold-start; raise `start_period` to 60–90s if measurement requires.

#### RISK-006 (LOW): `BIC` ORG flag surfaces as customer issue
**Trigger:** A user-facing redaction over-flags the term `BIC`. **Impact:** customer reports unwanted detection. **Mitigation:** documented in EDGE-008; resolution is a `de`-side ORG floor entry, not a model swap. Out of scope for this feature.

#### RISK-007 (LOW): Code-switched-text behavior change misunderstood
**Trigger:** Operator or user expects today's uniform-spaCy multilingual behavior on mixed-language paragraphs. **Impact:** confusion about why English names are missed in a German paragraph (or vice versa). **Mitigation:** REQ-012 explicitly documents this in operator-facing docs; the failure mode flip is called out in ADR 0001 §Neutral observations.

---

## Amendments

### Amendment 2026-05-06 (Option A) — DE DATE_TIME held-out positive dropped; REQ-006 Bar 2 made entity-conditional

**Scope.** Spec-only edit. No ADR amendment. No `multi.yaml` change. No `src/redakt/config.py` change. No EN-row change. All other Step 3e fixes preserved.

**Changes.** (1) REQ-009b: dropped the DE DATE_TIME held-out positive fixture; kept DE LOCATION held-out positive and the long-document anchor (now using the explicit 557-token German prose paragraph from the compaction file). Acceptance count updated from `41 + 15 + 3 = 59` to `41 + 15 + 2 = 58` total fixtures. The harness "must contain" branch is now used by **DE LOCATION only**. (2) REQ-006 Bar 2: rewritten to be entity-conditional — held-out positives apply only to entity types with model coverage on the configured DE engine (`PERSON` / `LOCATION` / `ORGANIZATION` via xlm-roberta CoNLL-03 PER/LOC/ORG; plus regex-only entities with held-out fixtures within their score ceilings). DE DATE_TIME is explicitly excluded by this amendment.

**Rationale.** The chosen DE engine `xlm-roberta-large-finetuned-conll03-german` has no DATE label by model design (CoNLL-03 label set is PER/LOC/ORG/MISC). DE DATE_TIME is therefore regex-only via `DateRecognizer` (`presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/date_recognizer.py`), with score ceilings of 0.6 (civilian formats) and 0.8 (full ISO 8601 datetime). EN benign fixtures carry DATE_TIME at 0.85 from `en_core_web_lg` SpacyRecognizer's `ner_strength` constant. The score-source asymmetry (EN spaCy 0.85 vs. DE regex 0.6 / 0.8) makes REQ-006 Bar 1 (`T > 0.85`) and Bar 2 (`T ≤ 0.8` to admit a DE held-out DATE_TIME positive) intersect at the empty set. The original feature goal — German common-noun-as-`PERSON` over-detection — is already met by xlm-roberta alone (all 15 broader-class nouns produce zero raw entities at any threshold). The held-out DATE_TIME positive bar was protecting an empty path; removing it restores feasibility without weakening the safety net for entities the model actually covers.

**Reference.** `SDD/orchestration/compacted/implementation-compacted-2026-05-06_13-45-37.md` — full diagnosis with score-ceiling table, probe outputs, threshold inequality derivation, and the 557-token German long-doc anchor proof-of-tokenization.

---

## Implementation Notes

### Suggested implementation order

1. **MODULE-001:** Land `MultiNlpEngine` in the Presidio fork with full unit-test coverage (`process_text`, `process_batch`, `is_stopword`, `is_punct`, `get_supported_entities`, `get_supported_languages`, `get_nlp`, `is_loaded`, `load` failure mode, unconfigured-language failure mode). Register with `NlpEngineProvider`. Extend `ConfigurationValidator` for the `multi` schema.
2. **MODULE-003:** Extend `install_nlp_models.py` with the `multi` branch and per-row engine dispatch. Add unit tests for unknown-engine and missing-engine-key cases. Add `revision=` parameter for REQ-013.
3. **MODULE-002:** Author `multi.yaml` with the en row (today's spaCy en config) + de row (placeholder thresholds; will be re-tuned in step 6). Pin the HF model revision.
4. **MODULE-007:** Wire `docker-compose.yml` to `Dockerfile.transformers` + `multi.yaml`. Run `docker compose build presidio-analyzer` and verify a clean build. Run `docker compose up presidio-analyzer` and verify health.
5. **REQ-015:** Run the in-Redakt 20-phrase probe. If divergent from §4.5, fall back to `Davlan/bert-base-multilingual-cased-ner-hrl` (REQ-013 + REQ-003 swap, rebuild).
6. **MODULE-006:** Run `tools/calibration_report.py --raw --out`. Read the `graded scores` distribution. Re-tune `entity_score_thresholds` (Redakt) and `low_score_entity_names` / `low_confidence_score_multiplier` (analyzer-side, `de` row). Iterate until **all four bars** of REQ-006's stopping condition hold: (1) full fixture set PASS including `expect_clean` from step 7; (2) held-out positive bar (entity-conditional per Amendment 2026-05-06) — for every DE-covered entity, at least one positive fixture produces the expected entity in `found`; concretely the DE LOCATION fixture per REQ-009b (DE DATE_TIME excluded by amendment); (3) calibration report committed with score-distribution annotation per tuned threshold; (4) re-run reproducibility within ±0.05. If any bar fails, do not commit thresholds — iterate or change approach.
7. **MODULE-005:** Add the 15 new `expect_clean: true` fixtures to `tests/eval/fixtures/de.yaml` per REQ-009. Add the 2 new fixtures from REQ-009b (held-out DE LOCATION positive + long-document anchor; DE DATE_TIME positive dropped per Amendment 2026-05-06). The "must contain" branch on the harness (`tests/eval/test_calibration.py:52-58`) already exists and is used by DE LOCATION only. Run `uv run pytest tests/eval/` and verify 58/58 PASS.
8. **REQ-014:** Capture `time docker compose up presidio-analyzer` cold-start. Adjust `start_period` per the REQ-014 formula. **REQ-016:** add the end-to-end `language: auto` routing test (de + en); verify a flipped-dispatch experiment fails it. **REQ-010a:** capture pre-feature snapshots, write the contract test, verify byte-identical envelopes. **PERF-002 behavioral acceptance:** capture an analyzer-startup log excerpt confirming each model's `LOADED ...` line appears once before `/health` 200 is served.
9. **MODULE-008:** Update `docs/v1-feature-spec.md` and `docs/presidio-integration.md` with the code-switched-text note and the `MultiNlpEngine` description; document `HUGGINGFACE_HUB_TOKEN` for CI environments per RISK-001.
10. **REQ-017:** Add the upstream-merge regression CI smoke check to the fork repo (or document deferral with operator sign-off if infeasible in this feature's scope).
11. **Final calibration report:** Commit the post-implementation `reports/calibration-...md` alongside the feature, including PERF-001 warm-up + steady-state numbers per anchor, REQ-014 hardware/option/arithmetic record, REQ-011 recognizer diff, REQ-006 score-distribution annotations.

### Subagent delegation

- **Suitable for delegation (read-only or scoped):**
  - Model probe re-run for REQ-015 (HF pipeline probe + in-Redakt probe).
  - Calibration report parsing and threshold-distribution analysis.
  - `default_recognizers.yaml` diff verification (REQ-011 acceptance).
  - Cold-start timing capture (REQ-014).
  - OpenAPI schema diff (REQ-010 acceptance).

- **Stays in main context:**
  - `MultiNlpEngine` source authoring.
  - `install_nlp_models.py` extension authoring.
  - Threshold re-tuning decisions (REQ-006, REQ-007).
  - `multi.yaml` authoring and revision pinning (REQ-013).

### Critical implementation note

`MultiNlpEngine` must satisfy the `NlpEngine` protocol that the recognizer registry and `AnalyzerEngine` both call into as if it were a single engine. The dispatch happens *inside* `MultiNlpEngine`, never at the caller. Any code path that currently calls `nlp_engine.process_text(text, language)` continues to work unchanged — there is no "unwrap to the right sub-engine" call in caller code. This is the structural reason `MultiNlpEngine` is the deep module (MODULE-001) and the per-language wrapping is information hiding.

### Subagent context budget

Target `<40%` context per subagent. The Presidio fork modules (`MultiNlpEngine`, `install_nlp_models.py` extension) are scoped to a few files each. Calibration is iterative; one report-iteration per subagent invocation keeps context tight.

---

**End of SPEC-007.**
