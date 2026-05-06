# Research Critical Review: transformers-nlp-backend

**Feature:** 007 — transformers-nlp-backend
**Reviewer:** research critical-review subagent (Step 2c, adversarial)
**Date:** 2026-05-06
**Inputs reviewed:**
- `SDD/research/RESEARCH-007-transformers-nlp-backend.md` (918 lines)
- `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md` (159 lines)
- `SDD/UBIQUITOUS_LANGUAGE.md` (101 lines)
- `SDD/adr/0001-presidio-per-language-nlp-engine.md` (127 lines)

**Code spot-checks performed:**
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py` (cited :87-114)
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py` (cited :73-100, :88, :99, :117-126, :43-46, :67, :187-198)
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/spacy_nlp_engine.py` (line search for `_doc_to_nlp_artifact`, lemmas)
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/ner_model_configuration.py` (cited :55 for `default_score: 0.85`)
- `presidio/presidio-analyzer/install_nlp_models.py` (cited :62, :79-82)
- `presidio/presidio-analyzer/presidio_analyzer/input_validation/schemas.py`
- `presidio/presidio-analyzer/presidio_analyzer/conf/spacy_multilingual.yaml`
- `src/redakt/utils.py` (cited :97-110)
- `tests/eval/test_calibration.py` (cited :46-60, :55)
- `tests/eval/fixtures/de.yaml`
- `presidio/` git log for commits 71206f6 and d76d884

---

## Severity: MEDIUM

Roll-up: 2 HIGH, 4 MEDIUM, 4 LOW.

---

## Executive Summary

The research is structurally sound: the load-bearing claim — that Presidio's `NlpEngineProvider` cannot mix engine types per language — is verified at the cited file:line, the recommended `MultiNlpEngine` (Option C) wiring is correctly motivated, and the eval-suite blind spot (issubset semantic) is a real, concrete finding that the ADR builds on cleanly.

Two HIGH issues, however, materially threaten the implementation plan:

1. **`install_nlp_models.py` is not multi-engine-aware.** Its `_download_model` raises `ValueError(f"Unsupported nlp engine: {engine_name}")` for any `engine_name` other than `spacy`/`stanza`/`transformers` (line 67-68 of the actual file). Under the recommended Option C the YAML's `nlp_engine_name: multi` makes the Docker image build fail at the `poetry run python install_nlp_models.py --conf_file ${NLP_CONF_FILE}` step (`Dockerfile.transformers:32`). Research never flags this — the build pipeline is broken on day one of implementation. (See Gap 1.)

2. **The German model selection is benchmark-only.** The recommended `xlm-roberta-large-finetuned-conll03-german` was selected on (a) HF compatibility, (b) backbone family (xlm-roberta-large like the rejected flair model), and (c) training corpus identity (CoNLL-03 German). The research did **not** probe the model on any of the 5 named over-detection phrases, nor on any member of the broader class. The model's HF card (per research's own table) does not document common-noun-as-PERSON behavior. CoNLL-03 is entity-rich news prose; Wikipedia/wikiann coverage of bare common nouns is markedly different. The bug being fixed could survive the model swap. (See Gap 2.)

Beyond these, several citation errors damage traceability (line 55 vs actual 63 for `default_score`; lines 79-82 vs actual 91/94/95 for `snapshot_download`; lines 187-198 cited as belonging to `transformers_nlp_engine.py` but actually live in `spacy_nlp_engine.py:200-213`). These don't change the conclusions but they degrade the document as a planning input — every line:file pair the planning subagent follows will need re-verification.

Recommended verdict: **PROCEED WITH FIXES** before /sdd:plan starts.

---

## Design Concept Fidelity Verdict

### Branches addressed (CLARIFICATION-walked)

| Branch | Status | Where in research |
|---|---|---|
| Q1 (English non-regression bar — detection-set non-regression) | Resolved | §5.1, §5.3 |
| Q2a (German exit criterion — broader class) | Resolved (with caveat — see Gap 3) | §7.3, §12.1 |
| Q2b ("no longer appear" — zero entity flags) | Resolved | §7.3, §12.1 |
| Q3 (asymmetric routing — Option C) | Resolved (with caveat — see Questionable Assumption 1) | §3 |
| Q4a/b/c (cost envelope — no caps) | Reflected | §0 finding 2; §2.4; §9.4 |
| Q5a (new CI fixtures — in scope) | Resolved | §7.3, §8.3 |
| Q5b (calibration corpus expansion) | Resolved | §7.3 |
| Q5c (global threshold knob retune — fully in scope) | Reflected; values deferred to calibration | §6.4, §6.5 |
| Q5d (frontend out of scope) | Respected | (no drift) |
| Q5e (recognizer registry floor — preserve) | Reflected | §2.2 |
| Q6 (code-switched text — accept the limitation) | Reflected | §12.2, §17.3 |

No silent drops.

### Open questions

| Open Q | Status |
|---|---|
| open Q1 (per-language engine map) | Resolved (negatively) — research clearly says NlpEngineProvider doesn't support it; proposes MultiNlpEngine. |
| open Q2 (lemma-aware enhancers under transformers) | Resolved — §3.5. Lemma path verified by grepping spacy_nlp_engine.py (lemmas indeed built from token.lemma_, line 201). |
| open Q3 (low_score_entity_names values under graded scores) | Explicitly deferred to calibration — §6.5. Acceptable. |
| open Q4 (German model selection) | Resolved — but on benchmark + corpus-identity grounds only, not on bug-class probing. See Gap 2. |

### Constraints honored

- `en + de` auto-detect: reflected (§1, §5).
- Recognizer registry floor: reflected (§2.2). Research lists currently-enabled per-language sets verbatim and notes the explicitly-disabled ones; commits 71206f6 and d76d884 are named (citation accurate).
- API contract preserved: reflected (§1.4).
- Per-entity threshold shape (`dict[str, float]`): reflected (§1.4, §6.2).
- spaCy retained: reflected (§3.5 — small `de_core_news_sm` keeps the lemmatizer alive).
- No frontend changes: respected.
- No per-token / per-sentence routing: respected.

### Out-of-scope respected

No drift into HTMX/Jinja, presidio-image-redactor, presidio-cli, GPU deployment, or per-token language detection.

### Vocabulary aligned

Research uses canonical terms from CLARIFICATION's glossary candidates. The glossary file (`SDD/UBIQUITOUS_LANGUAGE.md`) was already populated with the same terms. Minor drift: research §2.2 says "country recognizers per language (after fork commits 71206f6 and d76d884)"; commit 71206f6 is the `UsMbiRecognizer.__init__` kwarg fix and d76d884 is the actual enablement, but the wording bundles them. Cosmetic, not a finding.

---

## Critical Gaps Found

### 1. `install_nlp_models.py` build-pipeline gap [HIGH]

**Description.** The Dockerfile.transformers image build runs `poetry run python install_nlp_models.py --conf_file ${NLP_CONF_FILE}` (research §2.4). `install_nlp_models.py:54-68` (actual file content):

```python
def _download_model(engine_name, model_name):
    if engine_name == "spacy":
        spacy_download(model_name)
    elif engine_name == "stanza":
        ...
    elif engine_name == "transformers":
        _install_transformers_spacy_models(model_name)
    else:
        raise ValueError(f"Unsupported nlp engine: {engine_name}")
```

Under Option C (recommended), the YAML carries `nlp_engine_name: multi`. The script reads `nlp_configuration["nlp_engine_name"]` (line 47) and passes `"multi"` to `_download_model`, hitting the `else` branch at line 68. **Image build fails.**

A second-order issue: the loop at line 46-49 iterates `nlp_configuration["models"]` and unconditionally passes `model["model_name"]` (a single dict per entry) to `_download_model(engine_name, model_name)`. Under the proposed multi YAML schema (research §3.4) each model entry has its own `engine` key — `model["engine"]` is `"spacy"` for the en row and `"transformers"` for the de row. install_nlp_models has to be extended both at the dispatch level and at the iteration level. Research never says so.

**Evidence missing.** Research §2.4 cites `install_nlp_models.py:79` for `huggingface_hub.snapshot_download` (actual line: 91) and §9.1 says "downloaded at image build via `huggingface_hub.snapshot_download` + `AutoModelForTokenClassification.from_pretrained` (`install_nlp_models.py:79-82`)" (actual lines: 91, 94, 95). Off by 12 lines — almost certainly the research read an older/different revision of the file or hallucinated the line numbers without re-checking. Either way, the actual content of the function — and its `else: raise` branch — was not surfaced.

**Risk.** First implementation step (build the image) breaks. Planning will discover this only when the docker build fails, after sinking time into the YAML and `MultiNlpEngine` module. Diff to install_nlp_models.py is small but unscoped.

**Recommendation for 2d.** Add a paragraph to research §3 (preferably §3.3 Option C "Cons" or §3.4 implementation skeleton, and a corresponding §9.1 note) calling out:
- `install_nlp_models.py:54-68` only knows `spacy | stanza | transformers`; add a `multi` branch that iterates `models[]` and dispatches each entry by its per-row `engine` key.
- The diff is ~10 LoC but must land in the same fork PR as the `MultiNlpEngine` module.
- Update the §0 LoC estimate from "~150 LoC" to "~150 LoC (+ ~10 LoC in install_nlp_models.py)".

---

### 2. German model selection lacks bug-class verification [HIGH]

**Description.** Research §4 selects `xlm-roberta-large-finetuned-conll03-german` over alternates on three grounds:
1. HF compatibility (rules out flair).
2. Same backbone family as the highest-F1 flair model.
3. Same training corpus (CoNLL-03 German).

The research **did not** verify that the recommended model actually fixes the bug. Specifically:
- It was not run against any of the 5 named over-detection phrases (`Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`).
- It was not run against any member of the broader class enumerated in CLARIFICATION (`Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`, `Versicherungsnummer`).
- Research §4.1's "Common-noun behavior" column reads "Not documented" for every CoNLL-03-trained candidate. Research §4.1 then reasons by speculation: *"CoNLL-03-trained models generally do well on capitalized German common nouns being NOT classified as PER … German capitalizes all nouns; only the model's broader corpus signal distinguishes PER from common nouns."* That's a hypothesis, not evidence.

CoNLL-03 German is news prose with rich entity coverage. Common nouns like *Personalausweis* (personal ID card) do appear in German news, but typically in inflected/compound forms tied to bureaucratic context — not as standalone tokens. A model trained on CoNLL-03 has been rewarded for tagging capitalized words in news headlines as named entities. Whether the broader corpus signal is strong enough to suppress *bare* `"Personalausweis"` is precisely the question the bug poses, and it's the question the research left unanswered.

**Evidence missing.** No HF inference call against the bug phrases; no Hugging Face Inference API spot-check; no probe against `mschiesser/ner-bert-german` (the wikiann fallback that research itself flags as plausibly better-calibrated for noisy German prose).

**Risk.** Implementation builds the image, runs calibration, finds `"Personalausweis"` still flags as `PER` at 0.7-0.95 → `PERSON` post-mapping. The bug survives. The fix becomes "and now also calibrate the per-entity floor for PERSON to 0.99" — which is the same dead-end the project is in today, just with graded scores instead of flat ones. Research has effectively pre-committed planning to a model that may not solve the user's stated problem.

**Recommendation for 2d.**
- Add a §4.5 ("Bug-class spot-check") that runs both `xlm-roberta-large-finetuned-conll03-german` and `mschiesser/ner-bert-german` against the 10 broader-class phrases via HF Inference API or a local one-off script. Report what each model tags. If the primary recommendation tags any of them as `PER`/`LOC`/`ORG` with confidence > the prospective Redakt floor (~0.5), elevate `mschiesser/ner-bert-german` to primary or reconsider.
- If the spot-check is genuinely infeasible at research time, demote the recommendation language: §4.2 should read "**Primary candidate (must verify on bug class during implementation)**" rather than "**Recommended primary**", and §4 §0 should warn that the model selection is an implementation-phase decision pending an empirical probe. The ADR's "Decision" section currently presents this model as the chosen one; that overstates the research evidence.

---

### 3. Broader-class enumeration is silently narrow [MEDIUM]

**Description.** CLARIFICATION Q2a defines the success criterion as the *broader class* of German identity/document/insurance common nouns — not the 5 named phrases. Research §7.3 lists 10 entries for the new `expect_clean: true` fixtures. Of those:
- 5 are the original named phrases (`Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`).
- 4 are the CLARIFICATION-named extras (`Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`).
- 1 is research-added (`Versicherungsnummer`).

CLARIFICATION uses the phrase "research must verify the fix generalizes beyond the 5 named phrases" (§"Edge Cases") and Q5b reads "expand with ~10–20 German document/insurance/ID nouns for verification." Research's 10 entries hits the lower bound but doesn't engage with the *class boundary* — what makes a noun a member, what doesn't, and what the test set should sample.

Examples that are obvious members but missing: `Geburtsurkunde` (birth certificate), `Heiratsurkunde` (marriage certificate), `Meldebescheinigung` (residence registration), `Steuernummer` (tax number — distinct from `Steuer-IdNr.`), `Kontonummer` (account number), `BIC`, `Mitgliedsnummer`, `Kundennummer`, `Auftragsnummer`. Not flagging these means the eval signal lights up on a narrow slice of the bureaucratic-noun space; the next undocumented German common noun in production gets the same `PERSON` mis-tag, the calibration report still passes, and the user discovers it manually.

**Evidence missing.** Research never constructs a class-boundary specification (e.g., "any compound noun ending in `-nummer`, `-ausweis`, `-bescheinigung`, `-urkunde` referring to identity/document/insurance/account artifacts, in nominal form without numeric suffix"). It treats the CLARIFICATION enumeration as the class boundary, which it isn't (CLARIFICATION says "etc., to be enumerated during research").

**Risk.** Lower than Gap 2 because new fixtures can be added in any future PR. But the user's stated bar is "broader class," not "5 + a few"; calling Q2a resolved in §13 is overstated.

**Recommendation for 2d.** Add a §7.4 "Class boundary specification" to research enumerating:
- The morphological pattern (compound noun + designating suffix).
- A target sample of 15–20 phrases drawn from at least 4 sub-classes (identity/document, insurance, financial, employment). 10 in fixtures, the rest as a documented future-expansion set in the ADR's "Consequences/Neutral observations" section.
- An explicit note that the calibration-time check (`uv run python tools/calibration_report.py --raw --out`) must spot-check any nominal-form German PII-adjacent common noun, not just the canonical 10.

---

### 4. Citation errors degrade traceability [MEDIUM]

**Description.** Multiple line:file references in the research point to the wrong lines or the wrong file. Each is small but they compound:

| Research claim | What research said | What's actually true |
|---|---|---|
| `default_score: 0.85` source | `presidio_analyzer/nlp_engine/ner_model_configuration.py:55` (§2.1 note 3 and the glossary's `graded scores` reference) | Line 63-64 (the `Field(default=0.85, ...)` line). Line 55 is `aggregation_strategy`. |
| `huggingface_hub.snapshot_download` invocation | `install_nlp_models.py:79` (§1.3, §2.4) | Line 91. |
| `AutoModelForTokenClassification.from_pretrained` | `install_nlp_models.py:79-82` (§9.1) | Lines 94-95. The `_install_transformers_spacy_models` function spans lines 71-95. |
| spaCy download invocation | `install_nlp_models.py:62` (§9.1) | Line 56. (Line 62 is the engine_name dispatch.) |
| `_doc_to_nlp_artifact` definition | "inherited from `SpacyNlpEngine`, lines 187-198" (§3.2) | Actually `spacy_nlp_engine.py:200-213`. The reference is to the wrong file (`transformers_nlp_engine.py`) and the wrong lines (file is only 138 lines long). |
| `transformers_nlp_engine.py:67` "what TransformersNlpEngine defaults to per docstring" (§4.1, dslim/bert-base-NER row) | Defaults are in __init__ at line 60-69; line 67 is `}` not `dslim/bert-base-NER`. The default model name is actually `obi/deid_roberta_i2b2` (line 66), not `dslim/bert-base-NER`. `dslim/bert-base-NER` only appears in the docstring example. |
| `filter_by_entity_thresholds` | `src/redakt/utils.py:97-110` (§0 finding 5) | Function spans lines 97-108; line 109 is blank, line 111 is the next function. Range is slightly long but defensible. |

**Risk.** Each line:file reference the planning subagent follows will need re-checking. The doc claims "60+ file:line references" with "every concrete claim about code behavior is anchored" (§ end). On a 7-of-7 sample I verified, 5 had off-by-N errors. That's a >70% miss rate on the spot-check.

**Recommendation for 2d.** Run a citation pass against the actual fork code at the current revision. Update at minimum: §1 table line for `nlp_engine_provider.py` (range is fine), §2.1 (`ner_model_configuration.py:55` → `:63`), §1.3 / §2.4 / §9.1 (install_nlp_models.py line numbers), §3.2 (`_doc_to_nlp_artifact` is in `spacy_nlp_engine.py`, not `transformers_nlp_engine.py`), §4.1 (the `dslim/bert-base-NER` row's "what TransformersNlpEngine defaults to per docstring" claim — actual default is `obi/deid_roberta_i2b2`, and `dslim/bert-base-NER` appears only in the docstring example; rephrase). Fix the glossary's `graded scores` reference too (line 40 of `SDD/UBIQUITOUS_LANGUAGE.md`).

---

### 5. `~150 LoC` estimate for MultiNlpEngine is unverified [MEDIUM]

**Description.** Research §3.3 Option C and §11.2 cite "~150 LoC" for the new MultiNlpEngine module + provider registration + YAML schema branch. There's no derivation. Spot-counting from the research's own §3.4 skeleton:
- Class definition + 9 methods (`__init__`, `load`, `is_loaded`, `process_text`, `process_batch`, `is_stopword`, `is_punct`, `get_supported_entities`, `get_supported_languages`, `get_nlp`): ~50 LoC at most when fleshed out with docstrings and error handling.
- `nlp_engines` tuple registration in `nlp_engine_provider.py`: 1 LoC.
- Validator branch in `schemas.py` (currently `validate_nlp_configuration` is 25 lines of dict-shape checks at lines 47-73): ~15 LoC if a per-row `engine` key is validated. Or 0 LoC if the existing validator is left as-is (it doesn't enforce engine-name registration).
- YAML schema doc/comments in conf: ~30 LoC.
- Plus the install_nlp_models.py extension flagged in Gap 1: ~10 LoC.

That comes to ~100 LoC + tests. The `~150` is plausible but unanchored. More importantly, it doesn't include the install_nlp_models.py change (Gap 1) or the unit-test surface (research §17.1 lists 5 test cases for MultiNlpEngine, plausibly another 80-150 LoC of test code).

**Risk.** Planning inherits a soft cost estimate that excludes the `install_nlp_models` extension and excludes test code. Underestimates implementation effort by 30-50%.

**Recommendation for 2d.** Re-state §3.3 / §11.2 as "~100 LoC implementation + ~80-150 LoC tests + ~10 LoC `install_nlp_models.py` extension; total ~200-260 LoC across the Presidio fork." Or remove the number entirely and let planning estimate.

---

### 6. Code-switched-text limitation under-documented [LOW]

**Description.** CLARIFICATION Q6 accepted the limitation but research §12.2 documents it in a single sentence: *"Code-switched text (e.g., German paragraph with English names embedded). Whichever language lingua-py picks gets the engine. Users override via `language` parameter. Documented; no test coverage required."*

This is fine as a research-level statement, but it understates an important interaction effect: under asymmetric routing, code-switched text fails *differently* than under the current uniform spaCy multilingual setup. Today, a German paragraph with English names goes through `de_core_news_lg`; spaCy German has flat 0.85 scores and over-flags PERSON. Tomorrow, the same text either (a) gets routed to the German transformer (lingua picks `de`), in which case English names may be missed because the transformer's training data is German news, or (b) gets routed to spaCy English (lingua picks `en`), in which case German PII is missed because the transformer never runs. Either failure mode is worse than today's "everything is over-flagged" baseline for code-switched content.

Research §17.3 mentions a code-switched test case but only as a non-crash assertion. No discussion of detection-set non-regression on the code-switched mixed inputs in the existing eval fixtures (`tests/eval/fixtures/generic.yaml` has at least one — *"Anna Schmidt arbeitet bei der Beispiel AG in Berlin."*, which research §17.3 itself flags as a fixture that "should still flag PERSON").

**Risk.** Low. CLARIFICATION explicitly accepted the limitation. But the research doesn't quantify *how much* worse the new behavior is on code-switched text relative to today — it could be a quietly-noticeable production regression.

**Recommendation for 2d.** Add a sentence to §12.2 (or §17.3) noting that asymmetric routing may *worsen* detection on code-switched text relative to the current uniform-spaCy baseline, even though the limitation is accepted. Suggest the operator-side documentation (`docs/v1-feature-spec.md` per §18.1) explicitly warn: "for mixed-language paragraphs, set `language` explicitly to the language with the dominant PII content."

---

### 7. `start_period: 30s` healthcheck not verified at scale [LOW]

**Description.** Research §2.4 notes the analyzer container's `docker-compose.yml:31-37` healthcheck has `start_period: 30s` and §0 finding 2 says model bake-in is necessary partly because runtime download "would extend cold start to many minutes." The ADR's "Negative" section repeats this and says the start_period "is likely insufficient and will need extending during implementation."

But: research never measures or even estimates how long an xlm-roberta-large + de_core_news_sm + en_core_web_lg cold load actually takes from disk. Loading a 2.2 GB transformer (memory-mapped via safetensors) typically lands in 5-20 seconds on a modern CPU; en_core_web_lg loads in ~3-5 seconds. So total cold start could be 10-30s, in which case the existing 30s start_period might be fine, *or* it could be 30-90s on a more memory-constrained host. Research punts on the measurement.

**Risk.** Low; this is a tunable. But it's a "to be tuned during implementation" item that could easily be measured at research time with a one-shot Docker build + `time docker compose up presidio-analyzer`.

**Recommendation for 2d.** Either measure the cold start time on the typical dev host and report it in §2.4 / §9, or move the `start_period` extension out of "Negative trade-offs accepted" in the ADR and into a "Verify during implementation" item.

---

### 8. ADR overstates research evidence on chosen model [LOW]

**Description.** ADR §"Decision" reads: *"German (de): TransformersNlpEngine with de_core_news_sm for tokenization/lemmatization and xlm-roberta-large-finetuned-conll03-german for NER."* And ADR §"Alternative F" rejects `Davlan/bert-base-multilingual-cased-ner-hrl` partly because "the chosen primary uses a stronger backbone (xlm-roberta-large vs bert-base-multilingual-cased) and is fine-tuned specifically on the German half of CoNLL-03, with the same training corpus that drives the flair model's 92.31 F1."

But the research didn't verify (a) that the German half of xlm-roberta-large-finetuned-conll03-german actually tracks the flair model's German performance — it inferred from backbone identity — or (b) that this model fixes the bug class. ADR's confidence in the decision exceeds the research's confidence in the evidence. See Gap 2.

**Risk.** Low at the ADR level (Accepted status can be revised). But ADR 0001 is the project's first cross-cutting ADR; setting a precedent of "ADR claims things research only inferred" is bad for the SDD process.

**Recommendation for 2d.** Either:
- Reword ADR §"Decision" to "**candidate primary** xlm-roberta-large-finetuned-conll03-german, pending bug-class verification during implementation," with `mschiesser/ner-bert-german` as the documented A/B partner; or
- Bring the research evidence up to the ADR's confidence by performing the spot-check in Gap 2 and updating §4 accordingly.

---

## Questionable Assumptions

### 1. "Custom MultiNlpEngine in the Presidio fork is the cleanest path" [MEDIUM]

Research §3.3 Option C is recommended over Option B (two analyzer containers, route in Redakt) on grounds that B "doubles operational surface (2 images, 2 containers, 2 health checks)," "doubles cold-start cost," and requires `src/redakt/services/presidio.py` to become a per-language URL map.

This framing under-counts Option B's advantages and over-states Option C's costs:

- **Option B's image cost is half each**, not 2x — each container only carries one model family. Total disk usage may be similar or smaller than Option C's single-image-with-everything.
- **Option B requires no Presidio fork modification**, which means the fork stays closer to upstream — a real advantage given the project carries a fork already and every fork-side change is a future merge cost.
- **Option B's "per-language URL map" change to Redakt is trivial** (~5 LoC in `src/redakt/services/presidio.py:7-12` and the corresponding config field), arguably less invasive than Option C's ~150-260 LoC fork extension (Gap 5).
- **Option B's two health checks** is not actually a doubling of operational surface — Docker Compose already orchestrates many containers; adding one more is mechanical.

The strongest argument for Option C is that *English bit-for-bit preservation is automatic* — and that's a real advantage for the detection-set non-regression bar. But it's not enumerated in §3.3 Option C "Pros" with the right weight; instead Option B is rejected on operational-surface grounds that don't reflect the actual cost.

**Alternative possibility.** Option B might be the right starting point — implement the asymmetric routing in 2 weeks rather than 4-5 weeks, validate the German fix, and only then invest in the fork-modification path if maintenance burden materializes. Research §3.3 calls this out indirectly ("Useful as a 'phase 0' while the fork-modification path is being prototyped") but doesn't follow through.

**Recommendation.** Add to research §3.3 a "phasing" paragraph: Option B as a 2-week phase 0 to validate the model + new fixtures + threshold re-tuning end-to-end, then Option C as a phase 1 "consolidate to single container" follow-up if the team chooses. Or, if planning insists on a single deliverable, balance the Option B pros more honestly so the rejection is on its actual merits (English bit-for-bit) not on inflated operational costs.

### 2. "spaCy German parser+ner disabled but lemmatizer kept is sufficient for German PhoneRecognizer" [LOW]

Research §3.5 asserts that lemma-aware enhancers work under TransformersNlpEngine because "spaCy's parser/ner are disabled but the lemmatizer remains" and "`_doc_to_nlp_artifact` builds `lemmas = [token.lemma_ for token in doc]`."

Verified by grep: `spacy_nlp_engine.py:201` does build `lemmas` from `token.lemma_`, and `transformers_nlp_engine.py:88` does `disable=["parser", "ner"]` (not the lemmatizer). So far so good.

But: the **claim that this is sufficient for German `PhoneRecognizer` context handling** is unverified. PhoneRecognizer's context-word matching uses a list of trigger words (e.g., "phone", "tel"). For German, these need to be German words ("Telefon", "Mobil") and they're matched against `nlp_artifacts.lemmas`. The research doesn't verify that `de_core_news_sm`'s lemmatizer correctly lemmatizes "Telefonnummer" → "Telefon" or that PhoneRecognizer actually loads German trigger words.

**Alternative possibility.** PhoneRecognizer may be using English-only context words even for German text, which is a pre-existing latent bug independent of this feature — but the feature could surface it because the conversation about "preserving lemma-aware behavior" assumes the German path actually has working lemma-aware behavior.

**Recommendation.** Add to §3.5: a one-line note that says "PhoneRecognizer's context-word list is English by default; verify during implementation that German PII regex hits aren't context-degraded by the absence of a German trigger list. Out of scope but flagged."

---

## Missing Perspectives

- **Presidio upstream maintainer.** Adding `MultiNlpEngine` to the fork creates a permanent merge cost when pulling from microsoft/presidio. A perspective on whether this would ever be upstream-mergeable (it probably wouldn't, because upstream's stance is single-engine-per-config-file is intentional simplicity) is missing. If it's not upstream-mergeable, the fork-modification cost is forever, not one-time. Research §11.2 mentions this implicitly ("Engineering (the future maintainer; Pablo wearing a different hat)") but doesn't engage with the upstream-merge question. **Recommendation.** Add to ADR §"Consequences/Neutral observations" a note that `MultiNlpEngine` is unlikely to be upstream-mergeable — fork carries it indefinitely.

- **Docker image build operator.** Image size grows from current ~2 GB (spaCy) to ~5 GB (spaCy en_core_web_lg + de_core_news_sm + xlm-roberta-large + transformers wheels). Research §18.1 notes "~2-3 GB image growth" — likely accurate, but build time growth is unmentioned. `huggingface_hub.snapshot_download` of a 2.2 GB model is cache-busted on every CI image build unless the layer is preserved; CI minutes go up materially. Not a feature blocker, but worth surfacing.

- **Security review.** Research §16.4 covers model supply chain at one paragraph (no `revision=` pinning today; flag for ADR). But there's no consideration of whether the analyzer container should run with read-only root filesystem, network egress disabled at runtime (since models are baked in), or the actual cgroup memory limit needed for a transformer-loaded process. Out of scope for research, but worth a brief mention so the planning subagent doesn't assume "security is fine, no changes needed."

---

## Recommended Actions Before Proceeding

1. **[HIGH]** Surface and document the `install_nlp_models.py` build-pipeline gap (Gap 1). Add to research §3.3 / §3.4 / §9.1; update LoC estimate.
2. **[HIGH]** Either spot-check the recommended German model on the bug-class phrases (Gap 2), or demote the recommendation language and flag it as an implementation-phase decision.
3. **[MEDIUM]** Specify a class boundary for the broader-class fixtures (Gap 3); add 5-10 phrases that span sub-classes beyond the canonical 10.
4. **[MEDIUM]** Run a citation pass and fix the line-number errors (Gap 4). Particularly: `ner_model_configuration.py:55` → `:63-64`, `install_nlp_models.py:79` → `:91`, `_doc_to_nlp_artifact` cite in `spacy_nlp_engine.py:200-213` not `transformers_nlp_engine.py`, `dslim/bert-base-NER` is docstring-example-only.
5. **[MEDIUM]** Tighten the LoC estimate to account for `install_nlp_models.py` and tests (Gap 5).
6. **[LOW]** Add a note about code-switched-text behavior change (Gap 6).
7. **[LOW]** Either measure cold-start time or remove healthcheck `start_period` from the "trade-offs accepted" list (Gap 7).
8. **[LOW]** Reword ADR §"Decision" to reflect the evidence level on the model choice, or upgrade the evidence (Gap 8).

---

## Proceed/Hold Decision

**PROCEED WITH FIXES.**

The research is fundamentally sound on the load-bearing technical question (NlpEngineProvider single-engine constraint, MultiNlpEngine wiring, lemma-aware path preservation, eval-suite blind spot). The two HIGH findings — install_nlp_models.py gap and bug-class verification gap — are tractable in 2d without restructuring the document, and the MEDIUM findings are mostly citation cleanup and scoping clarifications. None of the gaps invalidate the chosen architecture; they harden the planning input.

If only one HIGH is fixed in 2d, fix Gap 2 (bug-class verification) — Gap 1 will surface immediately on first build and is low-cost to fix when it does, but Gap 2 could ride into production undetected.

---

## Findings Addressed

This section is appended by the **research-fix subagent (Step 2d, 2026-05-06)** documenting how each finding from the critical review was resolved. All severities (2 HIGH, 4 MEDIUM, 4 LOW) are addressed below.

### Gap 1 — `install_nlp_models.py` build-pipeline gap
**Severity:** HIGH
**Resolution:** Verified the `_download_model` `else: raise ValueError` blocker at the cited file:line range. Added a new sub-section **RESEARCH-007 §2.6 "Build-pipeline gap: `install_nlp_models.py` does not know about Option C"** with full function body verbatim, planning input (the ~10 LoC `multi` branch fix), and updated LoC accounting. Also propagated the gap forward to RESEARCH-007 §0 finding 2 (now explicitly mentions the build-pipeline blocker), §3.3 Option C "Cons" (LoC scope expanded to ~200–260), §9.1 (cross-references §2.6), §11.2 (test-coverage list expanded for the install branch), and §15 index (install_nlp_models.py row rewritten with correct line numbers and the dispatcher-extension note). ADR §Decision and §Negative sections also updated with the install-script-extension scope and the `Dockerfile.transformers:30` correction.
**Location of change:** RESEARCH-007 §0 finding 2 (revised); §2.6 (new); §3.3 Option C "Cons" (revised LoC); §9.1 (gap cross-reference); §11.2 (test list); §15 (index row); ADR §Decision (paragraph 2 rewritten with revised LoC accounting), ADR §"Negative / Trade-offs accepted" (first bullet rewritten to include install-script extension), ADR §References (citation corrected).

### Gap 2 — German model selection lacks bug-class verification
**Severity:** HIGH
**Resolution:** **Used Resolution A (live model probe).** Set up a temp HF-pipeline probe via `uv run --no-project --with "transformers,torch,sentencepiece,protobuf,huggingface_hub" python -c ...` and ran three candidate models against (a) the 5 named over-detection phrases, (b) the 4 CLARIFICATION-named extras + 1 research-added (`Versicherungsnummer`), (c) 10 broader-class extras spanning sub-classes 1–4 of the new §7.4 boundary spec, (d) 2 sentence-context controls. Results captured verbatim in **RESEARCH-007 §4.5 "Bug-class probe results (live HF-pipeline runs, 2026-05-06)"** with three result tables. Key findings: `xlm-roberta-large-finetuned-conll03-german` is empirically clean on all 10 named phrases + 9 of 10 extras (only `BIC` flags as ORG, defensible) + correct sentence-context PER/ORG/LOC; `Davlan/bert-base-multilingual-cased-ner-hrl` is also empirically clean (promoted to validated A/B target); `mschiesser/ner-bert-german` mis-tags 5 of 10 named phrases as PER 0.793–0.998 (rejected on bug-class evidence). The §4.1 comparison table's "Common-noun behavior" column is now populated with verbatim probe outcomes per model. §4.2 and §4.3 are rewritten to reflect the new evidence-grounded ordering. Temp probe script discarded post-capture (not committed). The ADR §Decision now leads with the empirical-validation language (also fulfills Gap 8); ADR §Alternative F is rewritten as "promoted to validated A/B target"; ADR §Alternative G is rewritten as "rejected on bug-class evidence". Recommendation **does not change** (xlm-roberta-large remains primary) — but it is now evidence-grounded rather than benchmark-only.
**Location of change:** RESEARCH-007 §0 finding 3 (rewritten with §4.5 reference); §4.1 (table "Common-noun behavior" column populated; `dslim/bert-base-NER` row corrected per Gap 4); §4.2 (rewritten); §4.3 (rewritten); §4.5 (new); §13 (status table for open Q4 updated); ADR §Decision (paragraph 1 rewritten), §Alternative F (rewritten), §Alternative G (rewritten).

### Gap 3 — Broader-class enumeration is silently narrow
**Severity:** MEDIUM
**Resolution:** Added **RESEARCH-007 §7.4 "Class boundary specification (broader-class definition for testing)"** with: a working membership criterion ("German nominal-form common noun designating an identity document, insurance document, financial-account artifact, or employment/membership token"); 4 sub-classes (identity/document, insurance, financial, employment); per-sub-class probed-clean members; per-sub-class future-set candidates (12 additional phrases listed: `Wohnsitzbescheinigung`, `Aufenthaltserlaubnis`, `Personenstandsurkunde`, `Rentenversicherungsnummer`, `Pflegeversicherungsnummer`, `Bankleitzahl`, `Kreditkartennummer`, `SEPA-Mandatsreferenz`, `Personalnummer`, `Arbeitgebernummer`, `Rechnungsnummer`, `Bestellnummer`); a recommended-fixture-set extension that brings §7.3's 10 phrases to 15 spanning all 4 sub-classes; an operator-side spot-check note that calibration must check any nominal-form German PII-adjacent common noun. The ADR §Neutral section enumerates the 12 future-set candidates and notes the §7.4 reference.
**Location of change:** RESEARCH-007 §7.4 (new); §4.5 closing paragraph (cross-reference to §7.4); ADR §"Neutral observations" (future-set candidates listed).

### Gap 4 — Citation errors degrade traceability
**Severity:** MEDIUM
**Resolution:** Ran a citation pass against the actual fork code at the current revision. Verified and fixed the following references throughout RESEARCH-007 and the ADR:
- `ner_model_configuration.py:55` → `:63-64` (the `Field(default=0.85, ge=0.0, le=1.0, ...)` line). Fixed in RESEARCH-007 §2.1, §15 index; ADR §Context, ADR §References; UBIQUITOUS_LANGUAGE.md §"graded scores" entry.
- `install_nlp_models.py:79` → `:91` (snapshot_download); `:79-82` → `:94-95` (AutoModelForTokenClassification.from_pretrained, with note that `_install_transformers_spacy_models` spans 71-95). Fixed in RESEARCH-007 §0 finding 2, §1.3, §2.4, §9.1, §15 index; ADR §References.
- `install_nlp_models.py:62` → `:56` (spacy engine path) and `:87` (transformers engine path inside `_install_transformers_spacy_models`). Fixed in RESEARCH-007 §2.4, §9.1, §15 index.
- `Dockerfile.transformers:32` → `:30` (the `RUN poetry run python install_nlp_models.py` step). Fixed in RESEARCH-007 §0 finding 2, §2.6, §9.1; ADR §Decision, ADR §"Negative / Trade-offs accepted", ADR §References.
- `_doc_to_nlp_artifact` cite moved from `transformers_nlp_engine.py:187-198` (wrong file; file is only 138 lines long) to **`spacy_nlp_engine.py:200-213`** (with `lemmas = [token.lemma_ for token in doc]` on line 201, inherited verbatim by `TransformersNlpEngine`). Fixed in RESEARCH-007 §3.5, §15 index; ADR §Decision (paragraph 4), ADR §References.
- §4.1 row for `dslim/bert-base-NER`: the "what `TransformersNlpEngine` defaults to per docstring" claim corrected. The actual `__init__` default model is `obi/deid_roberta_i2b2` at line 66; `dslim/bert-base-NER` appears only in the docstring example at line 36. The §4.1 row now correctly states this. Also reflected in §15 index row for `transformers_nlp_engine.py`.
- The "60+ file:line references" boilerplate in the §End-of-research note has been bumped to "70+" with a note that all citations were verified against the current fork revision in Step 2d.
**Location of change:** RESEARCH-007 §0 finding 2, §1.3, §2.1, §2.4, §3.5, §4.1 (table row), §9.1, §15 index, §End-of-research; ADR §Context, §Decision, §"Negative / Trade-offs accepted" first bullet, §References; UBIQUITOUS_LANGUAGE.md §"graded scores" reference.

### Gap 5 — `~150 LoC` estimate for MultiNlpEngine is unverified
**Severity:** MEDIUM
**Resolution:** Tightened the LoC accounting in **RESEARCH-007 §3.3 Option C "Cons"** to: `~100 LoC for MultiNlpEngine itself + ~10 LoC for the install_nlp_models.py extension (§2.6) + ~80–150 LoC of unit tests = ~200–260 LoC total in the fork`. Same accounting applied to RESEARCH-007 §11.2 and to ADR §Decision (paragraph 2) and ADR §"Negative / Trade-offs accepted" (first bullet). The §11.2 test list now also includes the `is_punct`, `get_supported_languages`, `get_nlp`, and `is_loaded` methods that were elided in the original list, plus tests for the install-script branch (`multi` with one spacy + one transformers entry; rejection of unknown per-row engine; rejection of `models[]` entry without `engine`).
**Location of change:** RESEARCH-007 §3.3 Option C "Cons" (revised); §11.2 (revised); §2.6 LoC paragraph (new); ADR §Decision paragraph 2 (revised); ADR §"Negative / Trade-offs accepted" first bullet (revised).

### Gap 6 — Code-switched-text limitation under-documented
**Severity:** LOW
**Resolution:** Added a paragraph to **RESEARCH-007 §12.2** explicitly noting that asymmetric routing flips the failure mode for code-switched text from over-flagging (today's uniform-spaCy baseline) to under-flagging (entities in the non-selected language are missed). Added the operator-side mitigation: "for mixed-language paragraphs, set `language` explicitly to the language with the dominant PII content; do not rely on auto-detect." Cross-referenced from RESEARCH-007 §17.3 (test-strategy edge cases). The same behavior-change note added to ADR §"Neutral observations".
**Location of change:** RESEARCH-007 §12.2 (paragraph added); §17.3 (cross-reference); ADR §"Neutral observations" (second bullet expanded).

### Gap 7 — `start_period: 30s` healthcheck not verified at scale
**Severity:** LOW
**Resolution:** Reframed in **RESEARCH-007 §2.4** from "the start_period is likely insufficient" to a "verify during implementation, may not need changing" item. Added concrete reasoning (cold-load 5–20s for a 2.2 GB safetensors model; 3–5s for en_core_web_lg; plausible total 10–30s; existing 30s `start_period` may suffice). Added a one-shot timing measurement to the implementation plan (`time docker compose up presidio-analyzer`, captured for the calibration report). Same correction applied to ADR §"Negative / Trade-offs accepted" — moved from "is likely insufficient and will need extending" (assumed) to "may or may not be sufficient — verify during implementation" (measured) with a 60–90s upper bound only if measurement exceeds 25s with margin.
**Location of change:** RESEARCH-007 §2.4 (paragraph added); ADR §"Negative / Trade-offs accepted" cold-start bullet (revised).

### Gap 8 — ADR overstates research evidence on chosen model
**Severity:** LOW
**Resolution:** Resolved by upgrading the research evidence (Gap 2 Resolution A) rather than demoting the ADR language. The ADR §Decision paragraph 1 now reads: "The model selection is empirically validated against the bug class by RESEARCH-007 §4.5 — a live HF-pipeline probe over 20 broader-class bare-noun phrases plus sentence-context controls confirms that the chosen model returns zero entities on all 10 named broader-class phrases…". This brings the ADR's confidence in line with the research's confidence — both now stand on the same empirical evidence rather than the ADR overshooting on backbone-family inference.
**Location of change:** ADR §Decision (paragraph 1 expanded with empirical-validation language); ADR §"Alternative F" (Davlan promoted from rejected to validated A/B target); ADR §"Alternative G" (mschiesser demoted from documented-fallback to rejected on bug-class evidence).

### Questionable Assumption 1 — "Custom MultiNlpEngine in the Presidio fork is the cleanest path"
**Severity:** MEDIUM (under-counted Option B advantages, over-stated Option C costs)
**Resolution:** Rebalanced **RESEARCH-007 §3.3** Option B and Option C cons:
- Option B "Pros" expanded to honestly reflect: no fork code change keeps the fork closer to upstream (lower future merge cost); image size is split, not doubled (each container only carries one model family); the Redakt-side change is small (~5–10 LoC).
- Option B "Cons" reframed: not "doubles operational surface" (mechanical) but "two containers / two health checks / two cold-start paths to manage; two `docker compose build` cycles per model swap".
- Option C "Net" paragraph adds an explicit phasing alternative: Option B as a 2-week phase-0 to validate model + new fixtures + threshold re-tuning end-to-end, then Option C as phase-1 if maintenance burden materializes. Research recommends Option C as a single deliverable on grounds that the §4.5 probe has already de-risked the model choice.
**Location of change:** RESEARCH-007 §3.3 Option B (Pros + Cons rewritten); Option C (Net paragraph extended with phasing alternative).

### Questionable Assumption 2 — "spaCy German parser+ner disabled but lemmatizer kept is sufficient for German PhoneRecognizer"
**Severity:** LOW
**Resolution:** Added a one-line note to **RESEARCH-007 §3.5** flagging that PhoneRecognizer's context-word list is English-only by default, and that whether German PII regex hits are context-degraded by the absence of a German trigger list is a pre-existing latent question independent of this feature. Out of scope for this feature; flagged for implementation calibration.
**Location of change:** RESEARCH-007 §3.5 (paragraph appended).

### Missing Perspectives — Presidio upstream maintainer
**Severity:** Implicit (review-flagged as missing)
**Resolution:** Added new **RESEARCH-007 §11.3 "Presidio upstream maintainer (cross-cutting concern)"** explaining that `MultiNlpEngine` is unlikely to be upstream-mergeable (upstream's single-engine-per-config-file stance is intentional simplicity), so the fork carries the diff indefinitely. Added mitigation pattern (delimited blocks, centralized files, per-feature CHANGES log). Same observation reflected as ADR §"Negative / Trade-offs accepted" second bullet ("Indefinite fork maintenance burden").
**Location of change:** RESEARCH-007 §11.3 (new); ADR §"Negative / Trade-offs accepted" second bullet (new).

### Missing Perspectives — Docker image build operator
**Severity:** Implicit (review-flagged as missing)
**Resolution:** Acknowledged as a build-time CI minutes growth in ADR §"Negative / Trade-offs accepted" larger-image bullet (the 2.2 GB `huggingface_hub.snapshot_download` is cache-busted on every image build unless the layer is preserved). Not promoted to a separate RESEARCH-007 section because the existing §9 already covers the rebuild story; the CI-minutes implication is a one-line addition that lands cleanly in the ADR.
**Location of change:** ADR §"Negative / Trade-offs accepted" image-size bullet (revised).

### Missing Perspectives — Security review
**Severity:** Implicit (review-flagged as missing, "out of scope for research, but worth a brief mention")
**Resolution:** Acknowledged as out of scope per the review's own framing. RESEARCH-007 §16.4 already flags HF model pinning via `revision=` for the planning ADR; no further changes required by the review.
**Location of change:** No change — review-confirmed out of scope.

---

**Summary:** All 10 findings (2 HIGH, 4 MEDIUM, 4 LOW) plus 2 Questionable Assumptions plus 3 Missing Perspectives are addressed. RESEARCH-007 grew by 1 new sub-section (§2.6), 1 new sub-section (§4.5), 1 new sub-section (§7.4), 1 new sub-section (§11.3); roughly 30 in-place edits across §0, §1.3, §2.1, §2.4, §3.2, §3.3, §3.5, §4.1, §4.2, §4.3, §9.1, §11.2, §12.2, §13, §14, §15, §17.3, §End-of-research. ADR 0001 had 4 sections updated (Context citation, Decision rewritten, Alternatives F/G swapped, Negative + Neutral expanded) and the References list cleaned up. UBIQUITOUS_LANGUAGE.md had 1 in-place edit. No supersession ADR was needed; the original ADR's recommendation stands and is now empirically grounded rather than overshooting research evidence.
