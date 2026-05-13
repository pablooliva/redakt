# Ubiquitous Language

Project-wide glossary of domain terms shared between user, code, and AI.
Goal: every conversation, spec, ADR, and code identifier uses the same name for the same thing.

Maintenance is **incremental**: terms persist across feature cycles. Only add a term that is grounded in the codebase or in a research/clarification artifact (cite file:line or document section). Do not invent terms.

---

## Entities (things in the domain)

### NLP engine
Presidio's abstraction for tokenization + lemma + NER. Three implementations ship in upstream Presidio: `SpacyNlpEngine`, `StanzaNlpEngine`, `TransformersNlpEngine`. Feature 007 adds a fourth, `MultiNlpEngine`, that dispatches to a sub-engine per language.
- *Synonyms to avoid:* "NER engine" (NER is only one of its responsibilities), "language model" (too broad).
- *Reference:* `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py:87-114`; RESEARCH-007 §3, §14.

### country recognizer
Regex-based Presidio recognizer keyed to a specific country's ID/document patterns. Examples: `DeIdCardRecognizer`, `UkNhsRecognizer`, `UsSsnRecognizer`. Country recognizers regex on numeric/format patterns, so they do not fire on bare common nouns.
- *Synonyms to avoid:* "country pattern", "ID recognizer" (ambiguous with non-country IDs like `IbanRecognizer`).
- *Reference:* `presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml`; RESEARCH-007 §2.2.

### calibration corpus
The set of phrases `tools/calibration_report.py` runs through both Presidio (raw) and Redakt (post-filter) for tuning visibility. Implicit: it is exactly the union of all `tests/eval/fixtures/*.yaml` phrases — there is no separate calibration corpus.
- *Synonyms to avoid:* "calibration set", "tuning set", "eval corpus" (the eval suite uses the same phrases but with different assertions).
- *Reference:* `tools/calibration_report.py:116`; `tests/eval/_loader.py:65-72`; RESEARCH-007 §7.

### broader class
The user-defined class of German identity/document/insurance common nouns that should never be flagged as any entity. Members enumerated so far: `Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`, `Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`, `Versicherungsnummer`. Pablo's exit criterion (Q2): zero entity flags of any kind on these bare nouns.
- *Synonyms to avoid:* "common nouns" (too broad — applies to any language), "German false-positive class" (vague).
- *Reference:* CLARIFICATION-007 §"Edge Cases" / Q2a; RESEARCH-007 §7.3, §14.

### per-entity score floor
Instance + per-request `dict[str, float]` map enforced by Redakt's post-filter, distinct from Presidio's global `score_threshold`. Drops any result whose `entity_type` has a per-entity floor and whose `score` is below that floor. Entities not in the map are unaffected. Current values: `{"LOCATION": 0.90, "DATE_TIME": 0.95}`.
- *Synonyms to avoid:* "entity threshold" (the field name is `entity_score_thresholds` but "threshold" is also used for Presidio's global `score_threshold`; "floor" disambiguates), "minimum confidence".
- *Reference:* `src/redakt/config.py:14`; `src/redakt/utils.py:97-110`; RESEARCH-007 §6.

### strong anchor
An entity type that identifies a natural person on its own, without requiring combination with any other entity. When at least one strong-anchor span is present in a submission, closed-world filtering retains all quasi-identifier spans. Default set (19 entities, per SPEC-008 REQ-001): `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `EU_VAT_ID`, `BIC_CODE`, `SEPA_CREDITOR_ID`, `MEDICAL_LICENSE`, `DE_TAX_ID`, `DE_VAT_ID`, `DE_ID_CARD`, `DE_PASSPORT`, `DE_SOCIAL_SECURITY`, `DE_FUEHRERSCHEIN`, `DE_LANR`, `DE_TAX_NUMBER`, `DE_HEALTH_INSURANCE`, `DE_MASTR_ID`, `DE_KFZ`. Configurable via `strong_anchors:` in `config.yaml`. For the authoritative list and per-entity rationale, see SPEC-008 REQ-001.
- *Synonyms to avoid:* "anchor entity" (imprecise — anchors are entity types, not individual span instances), "identifier entity" (collides with Presidio's broader use of the word).
- *Reference:* `SDD/research/RESEARCH-008-closed-world-filtering.md` §Configuration Schema Design; `SDD/adr/0007-closed-world-filtering-quasi-identifiers.md` §Decision.

### quasi-identifier
An entity type that constitutes PII only when joinable with a strong anchor — in isolation it does not identify a natural person. Under closed-world filtering, quasi-identifier spans are suppressed when no strong-anchor span is present in the same submission. Default set: `DATE_TIME`, `LOCATION`, `NRP`, `DE_PLZ`. Configurable via `quasi_identifiers:` in `config.yaml`.
- *Synonyms to avoid:* "indirect identifier" (used in k-anonymity literature but not in this codebase), "weak identifier" (vague about the conditional nature).
- *Reference:* `SDD/research/RESEARCH-008-closed-world-filtering.md` §Configuration Schema Design; `SDD/adr/0007-closed-world-filtering-quasi-identifiers.md` §Decision; privacy literature on k-anonymity / quasi-identifier joining attacks.

### always-emit entity
An entity type that belongs to neither the `strong_anchors` nor the `quasi_identifiers` list. Always-emit entities pass through `filter_by_closed_world()` unchanged regardless of flag state: they do NOT satisfy the anchor check (they are not strong anchors), but they are also NOT subject to suppression (they are not quasi-identifiers). Current always-emit set: `DE_BSNR`, `DE_HANDELSREGISTER`, `DE_MALO`, `DE_MELO`, `DE_EEG_ANLAGE`, `DE_ZAEHLERNUMMER`, `IP_ADDRESS`, `CRYPTO`. These are asset or institution identifiers, not natural-person identifiers, and carry no closing-world suppression risk.
- *Synonyms to avoid:* "pass-through entity" (vague), "neutral entity" (implies no PII risk — these are still emitted as PII detections), "uncategorized entity" (implies the classification is missing — it is deliberate).
- *Reference:* `SDD/requirements/SPEC-008-closed-world-filtering.md` REQ-002, MODULE-001, EDGE-004; `SDD/adr/0007-closed-world-filtering-quasi-identifiers.md` §Decision.

### closed-world assumption
The threat-model premise that the text submission is the entirety of what the downstream consumer sees — no external data is available to join quasi-identifiers against. When this holds, quasi-identifiers without a strong anchor cannot re-identify a natural person. When it fails (agent workflows with external context, chunked document processing, LLM parametric knowledge), the closed-world filtering relaxation is unsafe. Must be documented in `config.yaml` alongside the `closed_world_filtering` flag.
- *Synonyms to avoid:* "isolation assumption" (non-standard), "no-external-context assumption" (verbose).
- *Reference:* `SDD/adr/0007-closed-world-filtering-quasi-identifiers.md` §Context; RESEARCH-008 §Security & Threat-Model Considerations.

### closed-world filtering
The Redakt post-filter policy that suppresses quasi-identifier spans when no strong-anchor span is present in the same submission. Off by default (`closed_world_filtering: false` in `config.yaml`); opt-in per instance and overridable per request. Operates after `filter_by_entity_thresholds()` in both `run_detection()` (`detect.py:119`) and `run_anonymization()` (`anonymize.py:116`). Composed with, not replacing, the allow-list filter and per-entity score floors.
- *Synonyms to avoid:* "anchor filtering" (describes mechanism, not the threat-model concept), "quasi-identifier suppression" (partial — suppression only occurs in the anchor-absent case).
- *Reference:* `SDD/research/RESEARCH-008-closed-world-filtering.md` §System Data Flow; `SDD/adr/0007-closed-world-filtering-quasi-identifiers.md` §Decision.

### graded scores
Transformer NER scores that vary continuously per detection (typically 0.4–1.0), in contrast to spaCy's flat 0.85 default. The shift to graded scores motivates re-tuning per-entity floors and `low_confidence_score_multiplier` values that were calibrated against the constant.
- *Synonyms to avoid:* "continuous scores", "real scores" (judgemental).
- *Reference:* RESEARCH-007 §6.4, §14; `presidio_analyzer/nlp_engine/ner_model_configuration.py:63-64` (`default_score: 0.85` source — the `Field(default=0.85, ge=0.0, le=1.0, ...)` line).

### expect_clean fixture
A `tests/eval/fixtures/*.yaml` entry carrying `expect_clean: true`. Asserts `found == []` — i.e., **zero entities of any type** must flag for the phrase to PASS. Distinct from the default `issubset` branch, which only catches missing entities. The `expect_clean` branch is the only mechanism in the eval suite that catches over-detection, which is why the broader-class fix is gated on adding `expect_clean` fixtures (SPEC-007 REQ-009, MODULE-005).
- *Synonyms to avoid:* "clean fixture", "negative fixture" (vague), "false-positive fixture" (the assertion is about over-detection, not specifically false positives).
- *Reference:* `tests/eval/test_calibration.py:46-50`; SPEC-007 REQ-009; RESEARCH-007 §8.2.

### code-switched fixture
A `tests/eval/fixtures/de.yaml` entry that mixes English and German tokens in one phrase (e.g., `"Anna Smith works in München für die Beispiel GmbH."` with `language: de` and `expect: [LOCATION]`). Concretizes EDGE-001's "no test coverage required beyond non-crash" into a behaviorally-verified assertion: the DE transformer pipeline tokenizes mixed text without raising AND the German LOCATION (`München`) is found despite the English subject + company-name span. Added at Step 4e per critical-review finding F-M; the positive-bar (`expect: [LOCATION]`) is preferred over `expect_clean: true` because the latter would pass vacuously if windowing silently dropped all spans.
- *Synonyms to avoid:* "mixed-language fixture" (less precise — code-switching is the specific linguistic phenomenon), "bilingual fixture".
- *Reference:* `tests/eval/fixtures/de.yaml` (Anna Smith fixture); SDD-007 Step 4e Findings Addressed F-M; SPEC-007 EDGE-001.

### multi engine name
The string literal `multi` used as `nlp_engine_name: multi` in the analyzer YAML and as a dispatch key in `install_nlp_models.py`. Selects the `MultiNlpEngine` implementation when `NlpEngineProvider.create_engine()` reads the YAML. Coined by SPEC-007 REQ-002 and REQ-004; introduced alongside the `multi.yaml` config file at `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml`.
- *Synonyms to avoid:* "mixed engine name" (we already use `asymmetric routing` for the architectural pattern; `multi` is the configuration key), "per-language engine name".
- *Reference:* SPEC-007 REQ-002, REQ-003, REQ-004, MODULE-002; RESEARCH-007 §3.3 Option C.

### digest manifest
The supply-chain trust anchor for SDD-007's HF model integrity verification: a JSON file (`presidio/presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json`) listing per-file SHA-256 digests for every weight / tokenizer / config artifact at the pinned HF revision. `install_nlp_models.py` reads on every build; an empty manifest (`{}`) triggers first-build baseline-capture mode, a populated manifest triggers verify mode (build fails on per-file mismatch). Atomic write via `os.replace` after `.tmp` to be parallel-CI-safe. Required by REQ-013; HIGH-severity F-A finding at Step 4d (the empty placeholder shipped at chunk 1B was caught and populated at chunk 4e — 14 entries for the pinned `xlm-roberta-large-finetuned-conll03-german@1fbcc7a0...`).
- *Synonyms to avoid:* "checksum file" (manifest is the precise term — it lists multiple files, not a single checksum), "model fingerprint" (vague).
- *Reference:* `presidio/presidio-analyzer/install_nlp_models.py` (`_load_digest_manifest`, `_write_digest_manifest`, `_verify_digest_manifest`); SPEC-007 REQ-013, SEC-003.

### revision pin
The HF Hub commit SHA recorded in `multi.yaml`'s `de` row under `revision:` (currently `1fbcc7a00a69ce5ab754623154a8e9cc6ba868e2`). The pin is forwarded into `huggingface_hub.snapshot_download(revision=...)` at build time AND into `from_pretrained(revision=...)` at both build and runtime via the chunk-4c F-1 patch (`MultiNlpEngine._build_sub_engine` → `TransformersNlpEngine.load()` → `pipe_config["revision"]`). Revision pinning alone is insufficient because HF Hub can mutate bytes served under a given revision — the `digest manifest` is the byte-level trust anchor; revision pin is the addressing mechanism that selects which bytes to verify.
- *Synonyms to avoid:* "model version" (a revision is a commit SHA, not a semantic version), "checkpoint pin" (vague).
- *Reference:* `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml` (`revision:` key); SPEC-007 REQ-013, RISK-001.

---

## Actions (operations / verbs)

### post-filter
Redakt-side processing applied to Presidio's span results after the analyzer returns, before the response is built. The current post-filter chain is: allow-list filter (inside Presidio's `/analyze` call), `filter_by_entity_thresholds()`, and (when enabled) `filter_by_closed_world()`. New document-level policy rules that cannot be expressed inside a span-scoped Presidio recognizer belong in this layer.
- *Synonyms to avoid:* "output filter" (vague about placement), "Presidio filter" (the post-filter is entirely Redakt-side; Presidio is upstream of it).
- *Reference:* `src/redakt/routers/detect.py:116-120`; `src/redakt/routers/anonymize.py:113-117`; `SDD/adr/0007-closed-world-filtering-quasi-identifiers.md` §Decision item 4.

### per-request override
A request-body field that overrides the instance-wide `config.yaml` value for the duration of a single request. Pattern established by `entity_score_thresholds: dict[str, float] | None = None` in `DetectRequest` and `AnonymizeRequest`; `closed_world_filtering: bool | None = None` is its boolean sibling. `None` means "use the instance default"; a non-None value takes precedence. Resolution logic in the router: `effective = request_value if request_value is not None else settings_value`.
- *Synonyms to avoid:* "request-level flag" (implies only booleans; the pattern covers maps too), "override param" (too generic).
- *Reference:* `src/redakt/models/detect.py:10`; `src/redakt/models/anonymize.py:10`; RESEARCH-008 §Configuration Schema Design (Per-request override sub-section).

### asymmetric routing
Per-language NLP engine selection: spaCy `en_core_web_lg` for English, transformer (`xlm-roberta-large-finetuned-conll03-german` per RESEARCH-007 §4.2) for German. Coexists in a single analyzer container via a custom `MultiNlpEngine` (RESEARCH-007 §3.3 Option C, recommended).
- *Synonyms to avoid:* "per-language routing" (ambiguous with per-sentence routing, which is explicitly out of scope per CLARIFICATION-007 Q6), "mixed engine".
- *Reference:* CLARIFICATION-007 Q3 C; RESEARCH-007 §3, §14.

### language auto-detect path
The existing lingua-py-based per-request language detection that selects the active engine when the caller passes `language: auto`. Implementation: `src/redakt/services/language.py:detect_language`. Lingua is configured to require ≥ 2 languages; supports en/de/es per project config.
- *Synonyms to avoid:* "language detection" (could mean lingua, or Presidio's own language-id, or content negotiation), "auto language".
- *Reference:* `src/redakt/services/language.py:80-102`; `pyproject.toml:8` (lingua-language-detector dep); RESEARCH-007 §1.2.

### detection-set non-regression
The non-regression bar for English: the set of entity *types* flagged on en fixtures by the new system must be a superset of (or equal to) the set flagged by the current spaCy multilingual run. Score values may move freely inside that envelope; loss of any previously-flagged entity is unacceptable. Distinct from "score non-regression" (not the bar) and from "exact-match non-regression" (also not the bar).
- *Synonyms to avoid:* "non-regression" (unqualified — there are multiple bars), "coverage parity".
- *Reference:* CLARIFICATION-007 Q1; RESEARCH-007 §5.1, §14.

### issubset assertion
The eval suite's permissive check (`expected.issubset(found)`): asserts every entity in `expect` appears in `found`, but tolerates *extra* unexpected entities. Concretely: it does NOT catch over-detection. The complementary `expect_clean: true` branch (`found == []`) is the only assertion in the suite that catches over-detection, which is why the broader-class bug is invisible in the current 41/41 PASS line until `expect_clean` fixtures land.
- *Synonyms to avoid:* "subset check", "permissive assertion" (vague).
- *Reference:* `tests/eval/test_calibration.py:46-60` (especially line 55); RESEARCH-007 §8.2, §14.

### four-bar stopping condition
The calibration acceptance protocol for REQ-006 / REQ-007 threshold tuning. Tuning iterations stop only when ALL four bars hold: (1) **Negative bar** — every `expect_clean` and `issubset` fixture passes; (2) **Held-out positive bar** — for every entity type the configured engine covers, at least one positive fixture surfaces the expected entity in `found` (entity-conditional per Spec Amendment 2026-05-06: DE DATE_TIME excluded because xlm-roberta CoNLL-03 has no DATE label); (3) **Score-distribution annotation** — calibration report committed alongside threshold changes documents the distribution per tuned knob; (4) **Reproducibility** — re-run produces values within ±0.05. SDD-007's chunk 2 retry hit all four bars at iteration 0 — fixture addition alone satisfied REQ-008 / REQ-009 / REQ-009b without any threshold movement.
- *Synonyms to avoid:* "calibration check", "four-fold protocol" (vague), "tuning gate" (collides with CI gate terminology).
- *Reference:* SPEC-007 REQ-006; `reports/calibration-007-after.md` four-bar table; Amendment 2026-05-06.

---

## States / configuration

### default score threshold
Presidio's global score floor passed on every `/analyze` call. Redakt sets it to `0.35` via `settings.default_score_threshold`. Distinct from per-entity score floors (Redakt-side) and from `default_score` in Presidio's `NerModelConfiguration` (which is the score *assigned* to bare NER hits when the model itself doesn't produce one — defaults to 0.85).
- *Synonyms to avoid:* "score threshold" (ambiguous between this global value and per-entity floors), "min confidence".
- *Reference:* `src/redakt/config.py:13`; `src/redakt/services/presidio.py:24`; RESEARCH-007 §1.2.

### low_score_entity_names / low_confidence_score_multiplier
Two coupled knobs in Presidio's `NerModelConfiguration`. Listed entity names get their model score multiplied by the multiplier *inside Presidio*, before Redakt's post-filter sees them. Current values: `low_score_entity_names: [ORG, ORGANIZATION]`, `low_confidence_score_multiplier: 0.4`. Effect: spaCy ORG hits at 0.85 become 0.34, below Presidio's 0.35 cutoff, so ORG/ORGANIZATION are effectively suppressed from spaCy. Under graded transformer scores, both knobs need empirical re-tuning.
- *Synonyms to avoid:* "score dampening", "entity penalty".
- *Reference:* `presidio/presidio-analyzer/presidio_analyzer/conf/spacy_multilingual.yaml:27-30`; `presidio_analyzer/nlp_engine/ner_model_configuration.py`; RESEARCH-007 §6.3.

---

## Roles

### operator
Pablo, in the role of running calibration and tuning thresholds via `tools/calibration_report.py`. Sole stakeholder; enterprise-internal deployment; no external sign-offs needed. Wears multiple hats (operator, engineer, end-user) but the term picks out the calibration-and-deployment context.
- *Synonyms to avoid:* "admin" (no admin UI exists), "DevOps".
- *Reference:* CLARIFICATION-007 §"Users and Goals"; RESEARCH-007 §11.1.

---

## Events

*(none yet — this glossary will accumulate event terms as workflow features land.)*

---

## Cross-references

- This glossary is created from RESEARCH-007 §14 and CLARIFICATION-007's "Glossary candidates".
- ADR 0001 (planning will create) will use these names verbatim.
- Future research/clarification docs append new terms here; do not rename existing ones without superseding the affected ADR.
