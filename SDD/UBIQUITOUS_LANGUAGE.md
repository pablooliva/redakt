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

### graded scores
Transformer NER scores that vary continuously per detection (typically 0.4–1.0), in contrast to spaCy's flat 0.85 default. The shift to graded scores motivates re-tuning per-entity floors and `low_confidence_score_multiplier` values that were calibrated against the constant.
- *Synonyms to avoid:* "continuous scores", "real scores" (judgemental).
- *Reference:* RESEARCH-007 §6.4, §14; `presidio_analyzer/nlp_engine/ner_model_configuration.py:63-64` (`default_score: 0.85` source — the `Field(default=0.85, ge=0.0, le=1.0, ...)` line).

---

## Actions (operations / verbs)

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
