---
adr: 0001
title: Use a per-language Presidio NLP engine — spaCy en_core_web_lg for English, xlm-roberta-large-finetuned-conll03-german for German
status: Accepted
date: 2026-05-06
supersedes: null
superseded_by: null
tags: [cross-cutting, nlp, presidio, pii-detection]
---

# ADR 0001: Use a per-language Presidio NLP engine — spaCy en_core_web_lg for English, xlm-roberta-large-finetuned-conll03-german for German

## Status

Accepted (2026-05-06)

## Context

Redakt's analyzer currently runs a single Presidio `SpacyNlpEngine` instance configured with `spacy_multilingual.yaml` (`en_core_web_lg`, `de_core_news_lg`). This produces two recurring problems on the German path: (a) common nouns from a broader class of German identity/document/insurance terms (`Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`, `Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`, `Versicherungsnummer`) are mis-tagged as `PERSON` and over-redacted in production; (b) every spaCy German NER hit returns the constant default score 0.85 (`presidio_analyzer/nlp_engine/ner_model_configuration.py:63-64`), which collapses the score gradient that Redakt's per-entity threshold filter (`src/redakt/utils.py:97-110`) relies on for tuning. CLARIFICATION-007 §"Success Criteria" makes the broader-class non-flagging an exit criterion, and §"Open Questions" Q3 mandates "spaCy en stays the primary; transformer model TBD by research" for German.

The constraints binding the choice (CLARIFICATION-007 §"Constraints" and §"Out of Scope"): `en` + `de` are the production languages with lingua-py auto-detect; the recognizer-registry floor (currently-enabled country recognizers, established by Presidio-fork commits 71206f6 and d76d884) must remain enabled in current order with current scoring; the Redakt API contract is frozen; the per-entity threshold config shape (`dict[str, float]`) is frozen; spaCy must remain a dependency for lemma-aware enhancers and PhoneRecognizer context handling; and there are no hard caps on image size, per-request latency, or cold-start time (CLARIFICATION-007 Q4).

The alternative shapes considered before this decision (RESEARCH-007 §3.3, §4): keep spaCy everywhere and filter harder; replace spaCy with transformers for both languages (single-model and dual-model variants); split the analyzer into two containers and route per language at the Redakt layer; or asymmetric per-language routing inside one analyzer. The chosen architecture is the last; the wiring detail is constrained by RESEARCH-007's finding that Presidio's stock `NlpEngineProvider` cannot mix engine types per language.

## Decision

The Presidio analyzer runs a **per-language NLP engine** with the following composition:

- **English (`en`)**: `SpacyNlpEngine` with `en_core_web_lg`, configured exactly as today. No behavior change for English.
- **German (`de`)**: `TransformersNlpEngine` with `de_core_news_sm` for tokenization/lemmatization and `xlm-roberta-large-finetuned-conll03-german` for NER. CoNLL-03 label space (`PER`/`LOC`/`ORG`/`MISC`) maps to Presidio entities `PERSON`/`LOCATION`/`ORGANIZATION` with `MISC` dropped via `labels_to_ignore`. The model selection is **empirically validated against the bug class** by RESEARCH-007 §4.5 — a live HF-pipeline probe over 20 broader-class bare-noun phrases plus sentence-context controls confirms that the chosen model returns zero entities on all 10 named broader-class phrases and on 9 of 10 broader-class extras while preserving correct PER/ORG/LOC behavior in sentence context.

The two engines coexist inside a single Presidio analyzer container via a custom **`MultiNlpEngine`** subclass added to the Presidio fork. RESEARCH-007 §3.1 (citing `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py:87-114`) confirms that the stock `NlpEngineProvider` reads exactly one `nlp_engine_name` and instantiates one engine class for all configured `models[].lang_code` entries — there is no per-language engine map at the provider layer. `MultiNlpEngine` holds one `SpacyNlpEngine` (en) and one `TransformersNlpEngine` (de) and dispatches `process_text(text, language)` / `process_batch(...)` / `is_stopword(...)` / `get_nlp(...)` to the sub-engine that owns the requested language. The skeleton in RESEARCH-007 §3.4 shows the data-model fit; planning will refine. Estimated diff to the Presidio fork (revised after RESEARCH-007 §2.6 / §11.2): **~100 LoC for `MultiNlpEngine` + ~10 LoC for an `install_nlp_models.py` extension + ~80–150 LoC of unit tests = ~200–260 LoC total.** The install-script extension is required because `install_nlp_models.py:54-68` is hard-coded to dispatch only on `spacy | stanza | transformers` and would otherwise fail the Docker image build at `Dockerfile.transformers:30` under `nlp_engine_name: multi`.

Both spaCy and transformer model artifacts are baked into the analyzer image at build time via `presidio/presidio-analyzer/install_nlp_models.py` (called from `Dockerfile.transformers:30`). RESEARCH-007 §2.4 / §9.4 documents the rationale (deterministic deployments, healthcheck-clean cold start, no first-request multi-GB downloads) and the hot-reload alternative (`TRANSFORMERS_CACHE` mount) is rejected for this feature but documented should the operator preference flip later.

spaCy stays a hard dependency: the German `TransformersNlpEngine` still loads `de_core_news_sm` with parser+ner disabled but the lemmatizer kept (RESEARCH-007 §3.5, citing `transformers_nlp_engine.py:88` and `_doc_to_nlp_artifact` at `spacy_nlp_engine.py:200-213`, inherited verbatim by `TransformersNlpEngine`), so `LemmaContextAwareEnhancer` and `PhoneRecognizer` context-word handling continue to work unchanged.

The Redakt API contract, the per-entity threshold config shape, and the recognizer-registry floor are all preserved verbatim. Threshold *values* (`entity_score_thresholds`, `low_score_entity_names`, `low_confidence_score_multiplier`) are re-tuned empirically against graded transformer scores during implementation (CLARIFICATION-007 Q5c; RESEARCH-007 §6.5).

## Alternatives Considered

### Chosen — Per-language NLP engine via custom `MultiNlpEngine` (RESEARCH-007 §3.3 Option C)

Single analyzer container, single NLP YAML file, no change to Redakt or `src/redakt/services/presidio.py`. Each sub-engine sees its native NLP artifacts (en gets full spaCy tokens+ents+lemmas; de gets spaCy-tokens+lemmas-only, transformer NER). `NerModelConfiguration` can be set per-sub-engine, so `low_score_entity_names`/`low_confidence_score_multiplier` are tunable per language. Preserves CLARIFICATION-007 Q3 C ("spaCy en stays the primary, transformer for German") verbatim. Preserves English detection-set non-regression by construction — English is bit-for-bit identical to current production (RESEARCH-007 §5.3).

### Alternative B — Transformers-only, both languages (RESEARCH-007 §3.3 Option A)

Set `nlp_engine_name: transformers` with two model entries. Rejected because: violates CLARIFICATION-007 Q3 C explicitly ("spaCy en stays the primary"); risks English detection-set regression since spaCy `en_core_web_lg` and a generic English transformer don't flag the same entities; would require extra calibration work against `tests/eval/fixtures/{generic,benign,us,uk}.yaml` to verify the en non-regression bar (RESEARCH-007 §5.1 lists the 23-entity superset that must be preserved on English).

### Alternative C — Two analyzer containers, route per language at the Redakt layer (RESEARCH-007 §3.3 Option B)

Run two separate `presidio-analyzer` containers (one with `spacy_multilingual.yaml`, one with the German transformer YAML); have Redakt's `PresidioClient` pick the URL based on `language`. Rejected because: doubles operational surface (2 images, 2 containers, 2 health checks); requires changing `src/redakt/services/presidio.py:7-12` from a single URL to a per-language URL map and `src/redakt/config.py:11` from `str` to `dict[str, str]`; doubles cold-start cost; contradicts the project's "single Redakt API, single analyzer" architectural shape. Most operationally heavy, least invasive to the Presidio fork — viable as a fallback if the `MultiNlpEngine` modification proves blocked, but not preferred.

### Alternative D — Replace spaCy entirely (transformers everywhere, drop spaCy as a dependency)

Rejected outright: violates CLARIFICATION-007 §"Constraints" ("spaCy retained as a dependency for lemma-aware processing and phone-context recognizers") and §"Unacceptable failures" ("spaCy is removed as a dependency"). `LemmaContextAwareEnhancer` and `PhoneRecognizer` context handling read `nlp_artifacts.lemmas`, which only spaCy populates in the current Presidio surface (RESEARCH-007 §3.5).

### Alternative E — `flair/ner-german-large` for German NER

Highest reported accuracy (F1 92.31 on CoNLL-03 German revised; RESEARCH-007 §4.1). Rejected because: the model ships in flair-native format and requires `flair.models.SequenceTagger.load`, while Presidio's transformers wiring uses `spacy_huggingface_pipelines.hf_token_pipe`, which calls Hugging Face's `pipeline()` and `AutoModelForTokenClassification` (`presidio/presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py:99`, cited in RESEARCH-007 §0 finding 3 and §4.1). Adopting flair would require either a custom non-HF `NlpEngine` adapter or a recognizer-side glue path, doubling the fork-modification scope. Not worth the maintenance burden for this feature.

### Alternative F — `Davlan/bert-base-multilingual-cased-ner-hrl` for German NER

HF-compatible, 0.2B params, ~700 MB, labels `PER`/`LOC`/`ORG` (RESEARCH-007 §4.1). **Promoted to validated A/B target (was previously rejected on benchmark grounds).** The Step 2d live HF-pipeline probe (RESEARCH-007 §4.5) confirms this model is also empirically clean on all 10 broader-class bare-noun phrases and produces correct sentence-context PER/ORG/LOC behavior. It has minor ergonomic advantages over the chosen primary: cleaner tokenization (no `sentencepiece` fallback-heuristic warning), no `sentencepiece` Python-dep at install time, and ~700 MB versus ~2.2 GB on disk. Not chosen as primary because: per-language F1 numbers for German are not published; the chosen primary uses a stronger backbone (`xlm-roberta-large` vs `bert-base-multilingual-cased`) and is fine-tuned specifically on the German half of CoNLL-03, with the same training corpus that drives the flair model's 92.31 F1; per CLARIFICATION-007 Q4, no cost gate argues against the larger weights. **A/B-validated fallback** if the primary's image-size or CPU-latency profile turns out to be a real pressure point during calibration.

### Alternative G — `mschiesser/ner-bert-german` for German NER

**Rejected on bug-class evidence (was previously listed as documented fallback).** HF-compatible, 0.2B params, ~840 MB safetensors, F1 0.8829 overall (PER F1 0.9152) on wikiann-de (RESEARCH-007 §4.1). The original hypothesis was that wikiann-de training (Wikipedia-derived, capital-noun-rich) would calibrate it better against bare common nouns than CoNLL-03-only models. The Step 2d probe (RESEARCH-007 §4.5) refutes this empirically: this model **mis-tags 5 of 10 broader-class bare nouns as PER** with confidences 0.793–0.998 (`Personalausweis` 0.997, `Reisepassnummer` 0.85, `Bundespersonalausweis` 0.793, `Aufenthaltstitel` 0.998, `Mitarbeiterausweis` 0.994), and the remaining 5 as ORG (`Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`, `Sozialversicherungsnummer`, `Versicherungsnummer`). Adopting it would carry the same headline bug into the new system. Documented here for traceability so future contributors do not re-propose it without re-running the probe.

## Consequences

### Positive

- Fixes the German common-noun-as-`PERSON` over-detection class (CLARIFICATION-007 §"Success Criteria" exit criterion).
- Restores a usable confidence gradient on German NER, replacing spaCy's flat 0.85 default. Per-entity thresholds become a live tuning surface again (CLARIFICATION-007 §"Edge Cases").
- Preserves English detection-set non-regression by construction: `en` keeps `SpacyNlpEngine` + `en_core_web_lg` bit-for-bit (RESEARCH-007 §5.3). The 23-entity en superset (RESEARCH-007 §5.1) is unchanged.
- The Redakt API contract (`POST /api/detect`, `/api/anonymize`, `/api/deanonymize` request/response shapes), the per-entity threshold config shape (`dict[str, float]` in `src/redakt/config.py:14`), and the recognizer-registry floor (`presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml`) are all preserved verbatim.
- Single analyzer container, single NLP YAML — no change to `src/redakt/services/presidio.py` or `src/redakt/config.py` beyond threshold-value re-tuning.
- Future language additions (es, fr, ...) follow the same per-language pattern: extend `MultiNlpEngine`'s YAML with one entry per language, choosing engine type per language.

### Negative / Trade-offs accepted

- **Custom `MultiNlpEngine` subclass + `install_nlp_models.py` extension in the Presidio fork (~200–260 LoC including tests).** Honest scope (revised after RESEARCH-007 §2.6 / §11.2 / §3.3 Option C): ~100 LoC for `MultiNlpEngine`, ~10 LoC for the `install_nlp_models.py` build-pipeline extension that adds a `multi` branch to the `_download_model` dispatcher (`install_nlp_models.py:54-68`), and ~80–150 LoC of unit tests. Without the install-script extension, the Docker image build fails at `Dockerfile.transformers:30` on the first build under `nlp_engine_name: multi`. Both diffs land in the same fork PR. The `ConfigurationValidator.validate_nlp_configuration` path needs a new branch for the `multi` engine schema (RESEARCH-007 §3.3 Option C "Cons"). Test coverage on the fork side must include `process_text`, `process_batch`, `is_stopword`, `is_punct`, `get_supported_entities`, `get_supported_languages`, `get_nlp`, and `is_loaded` for both `en` and `de` language args (RESEARCH-007 §11.2).
- **Indefinite fork maintenance burden.** `MultiNlpEngine` is unlikely to be upstream-mergeable: upstream Presidio's single-engine-per-config-file stance is intentional, not an oversight (RESEARCH-007 §11.3). The fork carries the diff forever; every upstream merge re-applies it as conflicts. Mitigation: keep the Redakt-specific changes in clearly-delimited blocks centralized in as few files as possible.
- **Larger analyzer image.** The xlm-roberta-large weights are ~2.2 GB on disk per the HF model card sizing; combined with `de_core_news_sm` (~14 MB) and the existing English assets, the analyzer image grows materially. Per CLARIFICATION-007 Q4, no cap applies. Build-time CI minutes also grow (the 2.2 GB `huggingface_hub.snapshot_download` is cache-busted on every image build unless the layer is preserved).
- **Higher per-request latency on de-routed requests.** Transformer inference on CPU is markedly slower than spaCy. CPU-only deployment is the supported shape; no SLO (CLARIFICATION-007 §"Failure Boundaries").
- **Cold-start cost may grow (verify during implementation, not assumed).** The analyzer container loads two model families at boot. Healthcheck `start_period: 30s` (RESEARCH-007 §2.4) **may or may not** be sufficient — research did not measure cold load time under the new config. Cold-load for a 2.2 GB safetensors model is typically 5–20 seconds on modern CPU and en_core_web_lg loads in 3–5 seconds, so the plausible total is 10–30 seconds; the existing 30s `start_period` may suffice without change. Implementation should add a one-shot `time docker compose up presidio-analyzer` measurement and raise `start_period` to 60–90s only if the measurement exceeds 25s with margin. Models are baked at build time so first-request latency is not affected (RESEARCH-007 §9.1).
- **Per-entity thresholds must be re-calibrated.** Current values (`{"LOCATION": 0.90, "DATE_TIME": 0.95}` in `src/redakt/config.py:14`) were calibrated against the spaCy 0.85 constant; under graded transformer scores most legitimate German `LOCATION` hits will land 0.7–0.95 and the 0.90 floor will start dropping them (RESEARCH-007 §6.4). `low_score_entity_names` and `low_confidence_score_multiplier` are similarly empirical and re-tuned during implementation, not in this ADR (RESEARCH-007 §6.5).
- **Eval-suite blind spot must be closed in the same feature.** The current `expect.issubset(found)` semantic at `tests/eval/test_calibration.py:55` would let the German PERSON over-detection class continue to ride through unflagged (RESEARCH-007 §0 finding 4 and §8.2). New `expect_clean: true` fixtures for the broader class are added in `tests/eval/fixtures/de.yaml` so the fix surfaces in CI (RESEARCH-007 §7.3, §7.4, §8.3 — 10 starter phrases listed in §7.3, expanded to 15 phrases spanning 4 sub-classes in §7.4).

### Neutral observations

- Adds a third Presidio language path: spaCy-only (en), transformer + spaCy-aux (de), and the existing recognizer-registry layer (shared, language-tagged). No per-sentence or per-token language routing — that is explicitly out of scope (CLARIFICATION-007 §"Out of Scope" Q6 (i)).
- Code-switched text (a German paragraph with English names embedded) is best-effort: lingua-py picks one language per request and the matching engine runs. Users override via the explicit `language` parameter (CLARIFICATION-007 §"Edge Cases the User Already Knows About"). **Behavior change relative to today**: under uniform spaCy multilingual the failure mode was over-flagging; under asymmetric routing the failure mode flips to *missing* entities in the non-selected language (e.g., a German paragraph with English names routed to the German transformer may miss the English names). Users should set `language` explicitly when content is mixed; the operator-facing `docs/v1-feature-spec.md` will be updated accordingly (RESEARCH-007 §12.2).
- The chosen primary model `xlm-roberta-large-finetuned-conll03-german` flags `BIC` (the SWIFT bank identifier code term) as `ORG 0.998` even on the bare token (RESEARCH-007 §4.5). Defensible — `BIC` overwhelmingly appears in bank-name contexts in CoNLL-03 — but operators may want to filter via a German `ORGANIZATION` floor entry if it surfaces as an unwanted detection. Documented for traceability; not a model-change blocker.
- Future-set candidates for broader-class fixtures (RESEARCH-007 §7.4) include `Wohnsitzbescheinigung`, `Aufenthaltserlaubnis`, `Personenstandsurkunde`, `Rentenversicherungsnummer`, `Pflegeversicherungsnummer`, `Bankleitzahl`, `Kreditkartennummer`, `SEPA-Mandatsreferenz`, `Personalnummer`, `Arbeitgebernummer`, `Rechnungsnummer`, `Bestellnummer`. Implementation lands 15 fixtures spanning 4 sub-classes; the rest are deferred to future-iteration calibration as the corpus grows.
- Models baked at image build time means switching the German model during calibration A/B (e.g., to the `Davlan/bert-base-multilingual-cased-ner-hrl` validated A/B target) requires a `docker compose build presidio-analyzer` cycle that downloads the new weights — minutes per swap (RESEARCH-007 §9.3). Workable for the implementation phase; a `TRANSFORMERS_CACHE` named-volume alternative is documented (RESEARCH-007 §9.4) if iteration friction grows.
- This decision binds: future PII-detection work (every analyze/anonymize feature inherits the per-language engine map), future language additions (the pattern is "add language X with engine Y to `MultiNlpEngine`'s YAML"), the threshold-tuning regime (graded transformer scores → calibration drives floor values), and the analyzer image build / deployment shape.

## References

- `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md` — design-concept inputs, Q1–Q6 resolutions, broader-class enumeration, success criteria.
- `SDD/research/RESEARCH-007-transformers-nlp-backend.md` — full investigation:
  - §0 Executive findings (NlpEngineProvider limitation, model survey result, eval-suite blind spot, post-filter location).
  - §1 System data flow with file:line entry points.
  - §2 Existing Presidio fork state (current YAMLs, recognizer floor, transformers scaffold, Dockerfile.transformers, root compose wiring).
  - §3 Asymmetric routing — three wiring options (A/B/C), implementation skeleton for the chosen Option C, lemma-aware enhancer interplay.
  - §4 German transformer model survey (5 candidates, comparison table, recommendation, per-entity mapping).
  - §5 English baseline preservation (spaCy en superset, no en-side bug to bundle).
  - §6 Per-entity threshold mechanism (current state, what changes under graded scores).
  - §7 Calibration tool internals + recommended new fixture entries.
  - §8 Eval suite layout + the `issubset` semantic gap.
  - §9 Docker image / hot-reload story.
  - §13 Open research questions — status (all 4 resolved or explicitly deferred to calibration).
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py:87-114` — single-engine constraint that motivates `MultiNlpEngine`.
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py:73-100, 99` — spaCy+HF dual-pipe pattern; `hf_token_pipe` HF-compatibility constraint.
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/spacy_nlp_engine.py:200-213` — `process_text` / `_doc_to_nlp_artifact` reference (lemmas built at line 201).
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/ner_model_configuration.py:63-64` — spaCy default-score 0.85 source.
- `presidio/presidio-analyzer/presidio_analyzer/conf/spacy_multilingual.yaml` — current production NLP YAML.
- `presidio/presidio-analyzer/presidio_analyzer/conf/transformers.yaml` — existing transformers scaffold.
- `presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml` — recognizer-registry floor (`supported_languages: [en, de]`).
- `presidio/presidio-analyzer/Dockerfile.transformers:16-30` — image build steps; `RUN poetry run python install_nlp_models.py` at line 30.
- `presidio/presidio-analyzer/install_nlp_models.py:54-68` — `_download_model` dispatcher (must be extended for the `multi` engine name); `:91, 94-95` — build-time HF model bake-in via `snapshot_download` + `AutoModelForTokenClassification.from_pretrained`.
- `docker-compose.yml` (root) — analyzer build args; `dockerfile: Dockerfile.transformers` and `NLP_CONF_FILE` arg are the implementation toggles.
- `src/redakt/utils.py:97-110` — `filter_by_entity_thresholds` post-filter (Redakt-side, shape preserved).
- `src/redakt/config.py:13-14` — `default_score_threshold` (0.35), `entity_score_thresholds` (`dict[str, float]`).
- `tests/eval/test_calibration.py:46-60` — `expect_clean` vs `expect.issubset(found)` semantic.
- `tests/eval/fixtures/de.yaml` — destination for new `expect_clean: true` fixtures (broader class).
- HF model card: https://huggingface.co/xlm-roberta-large-finetuned-conll03-german
- HF model card (fallback): https://huggingface.co/mschiesser/ner-bert-german
