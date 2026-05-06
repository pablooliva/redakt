# CLARIFICATION-007-transformers-nlp-backend

## Metadata
- **Date:** 2026-05-06
- **Interviewer:** Claude (Opus)
- **Interviewee:** Pablo Oliva
- **Status:** Resolved

## Clarified Problem Statement

Redakt's Presidio analyzer currently uses a spaCy multilingual NLP engine (`en_core_web_lg` for English, `de_core_news_lg` for German). The German NER over-detects common nouns as `PERSON` — observable both on five named phrases (`Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`) and, by user judgment, on a broader class of German identity/document/insurance common nouns. Each over-detection becomes an over-redaction in production. spaCy German also returns a flat 0.85 confidence on every NER hit, leaving no gradient for per-entity threshold tuning. The feature replaces the German NER with a transformer-based model while keeping spaCy English as-is, resolving the over-detection without regressing English detection coverage.

## Users and Goals

- **Enterprise end-users (humans):** paste text into Redakt, get anonymized output to use in AI tools without leaking PII. Goal: have German common nouns NOT redacted incorrectly.
- **AI agents:** call the same REST endpoints with text; receive entity findings. Goal: same as humans — German false positives stop.
- **Operator (Pablo):** runs `tools/calibration_report.py` to tune thresholds. Goal: have a usable confidence gradient for German entities so per-entity thresholds actually do work.

## Inputs and Triggers

- Existing Redakt API: `POST /api/detect`, `POST /api/anonymize`, `POST /api/deanonymize`. Inputs unchanged.
- Calibration: `tools/calibration_report.py` (operator-driven).
- Eval CI: `uv run pytest tests/eval/` (existing 41 fixtures + new fixtures added in scope per 5A).

## Outputs and Effects

- Same API request/response shapes. Same threshold-config shape (`dict[str, float]`).
- Different NLP behavior under the hood: per-language engine selection — spaCy for `en`, transformer for `de`.
- Calibration report's `redakt:` line for the broader class of German common nouns shows zero entity flags of any kind.
- Existing 41 eval fixtures stay green; new German-noun fixtures added.

## Success Criteria (User's Words)

- **All 41 existing eval fixtures pass** under the existing assertion semantics.
- **The 5 named over-detection cases AND the broader class** (German common nouns referring to identity / document / insurance terms — `Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`, etc., to be enumerated during research) **produce zero entity flags of any kind** in the calibration report. Not just "no longer flagged as PERSON" — they should pass through as untouched text. Country recognizers must not fire on bare nouns either (they shouldn't — they regex on numbers — but research must verify).
- **English detection-set non-regression on en fixtures.** Set of entities the transformer/spaCy combo flags must be a *superset* of (or equal to) what the current spaCy multilingual run flags. Scores may move freely inside that envelope; reduction in score is acceptable. Loss of any previously-flagged entity is **not** acceptable.
- **Both languages still resolve via existing language auto-detect** (lingua-py based routing). No API contract changes. Per-entity threshold shape (`dict[str, float]`) unchanged.

## Failure Boundaries

- **Tolerable failures:**
  - Code-switched text (mixed-language paragraphs) is best-effort. Whichever language auto-detect picks is the engine that runs. Users can override with explicit `language` parameter. Documented limitation.
  - Transformer per-request latency >> spaCy. CPU-only deployment is acceptable; no SLO.
  - Image size grows materially beyond ~3 GB. No hard cap.
  - Cold-start time grows. Not a constraint.
- **Unacceptable failures:**
  - Any English PERSON / EMAIL / PHONE entity previously flagged by spaCy is no longer flagged after the swap.
  - Any currently-enabled country recognizer (the floor set by commits 71206f6 / d76d884 on the presidio fork) gets disabled, reordered, or rescored.
  - Redakt API contract changes (request/response shape, status codes, headers).
  - Per-entity threshold config shape changes (must remain `dict[str, float]`).
  - spaCy is removed as a dependency (lemma-aware enhancer and PhoneRecognizer context handling still rely on it).

## Edge Cases the User Already Knows About

- **German common-noun-as-PERSON class** (the bug being fixed): research must verify the fix generalizes beyond the 5 named phrases.
- **Code-switched text:** best-effort, whichever language wins the lingua-py vote runs. Accepted limitation.
- **Country recognizers on bare nouns:** must not fire. Research confirms (regex-based, gate on numeric patterns).
- **Transformer score gradient vs spaCy's flat 0.85:** the existing `entity_score_thresholds` (LOCATION 0.90, DATE_TIME 0.95) were calibrated against the constant. Under graded transformer scores, those thresholds will start dropping legitimate matches. Re-tune is in scope.

## Constraints

- **Must have:**
  - `en` + `de` as production languages with lingua-py auto-detect.
  - Existing recognizer registry as the floor (currently-enabled country recognizers stay enabled, in current order, with current scoring; new ones may be added).
  - API contract preserved.
  - Per-entity threshold config shape preserved (`dict[str, float]`).
  - spaCy retained as a dependency for lemma-aware processing and phone-context recognizers.
- **Must not have:**
  - Frontend (HTMX/Jinja) changes — out of scope.
  - Removal of spaCy.
  - Per-sentence or per-token language routing.
- **Strong preferences:**
  - Hot-reload-friendly when feasible; if model files must be baked into the image, document the reason.
- **No hard caps on:**
  - Image size — research selects on accuracy alone.
  - Per-request latency — CPU-only is acceptable.
  - Cold-start time.

## Out of Scope

- Redakt frontend (HTMX/Jinja).
- Redakt API contract changes.
- Per-entity threshold shape (the `dict[str, float]` map structure stays — values may change).
- Removing spaCy as a dependency.
- `presidio-image-redactor`, `presidio-structured`, `presidio-cli` sub-services (Redakt does not use these).
- Per-sentence or per-token language detection (Q6 (i)).
- GPU deployment shape (Q4b: CPU-only acceptable).

## Stakeholders

- **Pablo Oliva (project owner / sole stakeholder):** aligned. Enterprise-internal deployment, no external sign-offs needed for this NLP-backend swap.

## Branches Walked

- **Problem:** Confirmed — German PERSON over-detection of common nouns; spaCy German has no usable score gradient.
- **Users / roles:** Confirmed — enterprise users, AI agents, operator (Pablo).
- **Inputs / triggers:** Confirmed unchanged — same API endpoints, calibration tool, eval CI.
- **Outputs / effects:** Confirmed — same response shape; different engine internals; calibration report demonstrates the fix.
- **Success — English non-regression bar (Q1):** **Detection-set non-regression** (option #2). Set of flagged entities must be superset of spaCy's. Scores may move freely.
- **Success — German exit criterion (Q2a):** **Broader class of German common nouns**, not strictly the 5 named phrases. Calibration corpus expansion is in scope.
- **Success — what "no longer appear" means (Q2b):** **Zero entity flags of any kind** on those nouns. Country recognizers must not fire either.
- **Failure — plan B if transformers can't satisfy both languages cleanly (Q3):** **Asymmetric routing** (option C). Transformers for German, spaCy for English. Two engines coexist via `NlpEngineProvider`'s per-language engine map.
- **Cost envelope (Q4a/b/c):** No hard cap on image size, per-request latency, or cold-start time. Research surfaces options ranked by accuracy.
- **Eval fixture suite (Q5a):** **In scope** — add 5–10 new CI fixtures specifically targeting the German common-noun-as-PERSON class.
- **Calibration corpus (Q5b):** **In scope** — expand with ~10–20 German document/insurance/ID nouns for verification.
- **Threshold knob retune (Q5c):** **Fully in scope** — `low_score_entity_names` and `low_confidence_score_multiplier` may be re-tuned globally, plus per-entity thresholds.
- **Frontend (Q5d):** Out of scope. No HTMX/Jinja changes.
- **Recognizer registry floor (Q5e):** Confirmed — currently-enabled country recognizers stay; new ones may be added.
- **Edge case — code-switched text (Q6):** **Accept the limitation** (option i). Whichever language auto-detect picks runs; users can override with explicit `language`. Documented as a known limitation.

## Open Questions (Still Ambiguous)

None for design intent. A small set of research-resolvable questions inherited downstream:

- Whether Presidio's `NlpEngineProvider` supports a per-language engine map with mixed engine types (one spaCy, one transformers) cleanly. *Research target — not a user decision.*
- How a small spaCy German model (e.g., `de_core_news_sm`) interplays with the German transformer NER pipeline for lemma-aware recognizers. *Research target.*
- What `low_score_entity_names` and `low_confidence_score_multiplier` defaults should be set to under graded transformer scores — answered empirically by calibration. *Calibration-driven, not a user decision.*
- Specific German transformer model selection — `flair/ner-german-large` vs `Davlan/bert-base-multilingual-cased-ner-hrl` vs `xlm-roberta-large-finetuned-conll03-german`. *Research target — pick on accuracy, no cost gate.*

## Notes for /research-start

**Glossary candidates** (for `SDD/UBIQUITOUS_LANGUAGE.md`):

- **asymmetric routing** — per-language NLP engine selection (spaCy for en, transformers for de).
- **detection-set non-regression** — non-regression measured by the set of flagged entities, not by score levels.
- **calibration corpus** — the set of phrases `tools/calibration_report.py` runs through both Presidio and Redakt for tuning visibility.
- **country recognizer** — regex-based Presidio recognizer keyed to a specific country's ID/document patterns (e.g., `DE_ID_NUMBER`).
- **language auto-detect path** — existing lingua-py based per-request language detection that selects the active engine.
- **broader class** — the user-defined class of German identity/document/insurance common nouns that should never be flagged as any entity.

**Codebase areas to investigate first:**

- `presidio/presidio-analyzer/presidio_analyzer/conf/transformers.yaml` (existing scaffold for English transformer engine).
- `presidio/presidio-analyzer/presidio_analyzer/conf/spacy_multilingual.yaml` (current production config).
- `presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml` (top-level `supported_languages: [en, de]`).
- `presidio/presidio-analyzer/Dockerfile.transformers` (transformer image build).
- `docker-compose.yml` (analyzer image selection at root level).
- `tools/calibration_report.py` (calibration corpus + report generation).
- `tests/eval/fixtures/*.yaml` (existing 41 fixtures).
- `reports/post-fix-2.md` (current calibration baseline).
- The `presidio-analyzer` Python module: `NlpEngineProvider`, `TransformersNlpEngine`, `SpacyNlpEngine`, the per-language engine config schema.
- Recent fork commits 71206f6 and d76d884 (country recognizer wiring — must be preserved).

**Model candidates to compare during research:**

- **German NER:** `flair/ner-german-large`, `Davlan/bert-base-multilingual-cased-ner-hrl`, `xlm-roberta-large-finetuned-conll03-german` (or its German-specific siblings). Plus any other strong German NER on Hugging Face surfacing in research.
- **English NER (default keeps spaCy):** asymmetric routing per Q3 C says spaCy en stays the primary. But the existing transformers.yaml ships `StanfordAIMI/stanford-deidentifier-base` for English — research should note whether it's worth running for English alongside spaCy (e.g., as a recognizer that augments spaCy's PERSON output) or whether spaCy en is sufficient. **Default assumption: spaCy en stays as-is, transformer is German-only.**

**Stakeholder perspectives to capture:** Pablo's only. Enterprise-internal tool, no external review needed.

**Architecture decision to ADR (cross-cutting):**

> "Presidio NLP engine = per-language: spaCy `en_core_web_lg` for English, transformer (model TBD by research) for German. Coexists via `NlpEngineProvider`'s per-language engine map."

This likely supersedes or amends a prior NLP-backend ADR if one exists; research must check `SDD/adr/` for any earlier decision and decide between supersession and amendment.

## Status

**Resolved.** All major design-concept branches walked. Open questions are research-resolvable, not user-decision-blocked. Ready for `/research-start`.
