# Implementation Compaction - transformers-nlp-backend - chunk 2 - 2026-05-06 13:45 UTC

## Session Context
- Compaction trigger: **Structural impossibility — bars 1 and 2 of REQ-006 are conjunction-impossible for `DATE_TIME` under REQ-007's EN-row freeze.** Diagnosed at iteration 0 (no fixtures written, no thresholds tuned).
- Implementation focus: chunk 2 — calibration / threshold tuning + new DE fixtures (REQ-006 / REQ-007 / REQ-008 / REQ-009 / REQ-009b).

## Recent Changes
- **None.** No fixture YAML, no `src/redakt/config.py`, no `multi.yaml`, and no commits were made. The bail-out is deliberate and protects the four-bar stopping condition from a wrong-direction tune.

## Implementation Progress
- Completed in 2: none.
- In progress: REQ-006 (blocked, see below).
- Blocked: REQ-006 four-bar stopping condition cannot be satisfied for `DATE_TIME` simultaneously with REQ-007's EN-row freeze under the current spec text. The held-out positive bar (Bar 2) and the negative bar (Bar 1) intersect at the empty set.

## Tests Status
- `pytest tests/eval/`: 41/41 passing on `main` baseline (current placeholders).
- Four-bar status:
  - **Bar 1 (negative):** would PASS for the 15 new `expect_clean: true` `broader class` fixtures (raw probes confirm zero entities for all 15 names below). Would also PASS for the 41 existing fixtures if thresholds are unchanged. **WOULD FAIL** for 2 existing EN benign fixtures (`Munich today?`, `Paris this afternoon?`) if `DATE_TIME` threshold drops to admit a DE held-out positive.
  - **Bar 2 (held-out positive):** **CANNOT PASS** for `DATE_TIME` at any global threshold T where (T ≤ 0.8) AND (T > 0.85). The intersection is empty.
  - **Bar 3 (score-distribution):** would be writable for `LOCATION` (legitimate bottom 0.99996, noise distribution empty); blocked for `DATE_TIME` because no value is committable.
  - **Bar 4 (reproducibility ±0.05):** moot until Bars 1–3 hold.

## Calibration State
- Threshold values currently in `src/redakt/config.py`: `{"LOCATION": 0.90, "DATE_TIME": 0.95}` (unchanged from `main`).
- `multi.yaml` `de.low_score_entity_names`: `[ORG, ORGANIZATION]` (placeholder); `de.low_confidence_score_multiplier`: `0.4` (placeholder). Both unchanged.
- `multi.yaml` `en.low_score_entity_names`: `[ORG, ORGANIZATION]` (frozen per REQ-007); `en.low_confidence_score_multiplier`: `0.4` (frozen).
- Iterations completed: **0** (this is a 0-iteration analytical bail, not a "ran 15 iterations and could not converge").
- Calibration reports written: **none** (writing them would imply commitment to threshold values that cannot be derived).

## Critical Diagnosis (the bail rationale)

### Score-ceiling structure
| Source                                                                                  | DATE_TIME score on DE date input |
| --------------------------------------------------------------------------------------- | -------------------------------- |
| EN `en_core_web_lg` SpacyRecognizer (DATE label, applied for `language=en` requests)    | 0.85 (`ner_strength` constant)   |
| `DateRecognizer` ISO 8601 datetime pattern (`2025-03-15T14:30:00Z`)                     | 0.8                              |
| `DateRecognizer` `dd.mm.yyyy` / `mm/dd/yyyy` / etc. (the common DE/EN civilian formats) | 0.6                              |
| `DateRecognizer` `mm/yyyy`                                                              | 0.2                              |
| xlm-roberta-large-finetuned-conll03-german (CoNLL-03 labels: PER, LOC, ORG, MISC)       | **no DATE label** — never fires  |
| `de_core_news_sm` (auxiliary spaCy in the DE row)                                       | not surfaced via `TransformersNlpEngine` mapping |

### The threshold inequality
For `DATE_TIME` global threshold `T` (`entity_score_thresholds["DATE_TIME"]`):
- **Bar 1 requires** `T > 0.85` (otherwise existing EN benign fixtures `Munich today?` and `Paris this afternoon?` regress — DATE_TIME from EN spaCy at 0.85 stops being filtered, so the `expect_clean: true` assertion fails).
- **Bar 2 requires** `T ≤ 0.8` for ISO 8601 datetime, OR `T ≤ 0.6` for normal DE date formats (otherwise the held-out DE DATE_TIME positive's only available raw score is filtered out, so the "must contain DATE_TIME" assertion fails).
- **Intersection:** `(T > 0.85)` AND `(T ≤ 0.8)` = `∅`.

This is a 0-iteration analytical impossibility, not a "iterate harder" case. There is no value of `T` that resolves it.

### Probes run

1. **DE broader-class raw scores (all 15) — confirms Bar 1 negative side is fine for DE-routed traffic:**
```
Personalausweis: []
Reisepassnummer: []
Krankenversicherungsnummer: []
Führerschein: []
Steuer-IdNr.: []
Sozialversicherungsnummer: []
Bundespersonalausweis: []
Aufenthaltstitel: []
Mitarbeiterausweis: []
Versicherungsnummer: []
Geburtsurkunde: []
Steuernummer: []
Kontonummer: []
Mitgliedsnummer: []
Kundennummer: []
```
All 15 produce zero raw entities through the analyzer at `score_threshold=0.0`. The xlm-roberta-large-finetuned-conll03-german model does NOT exhibit the German common-noun-as-PERSON over-detection bug that motivated the broader-class fixtures.

2. **DE DATE_TIME positive sweep — confirms the 0.6 / 0.8 ceiling:**
```
2025-03-15            -> DATE_TIME 0.6
2025-03-15T14:30:00Z  -> DATE_TIME 0.8
2025-03-15T14:30      -> []  (incomplete ISO datetime — needs seconds)
Datum: 15.03.2025     -> DATE_TIME 0.6
15. März 2025          -> []  (German textual month — no recognizer matches)
Montag, 15. März 2025  -> []  (German weekday + textual month)
14:30 Uhr             -> []  (time-only, no date — no recognizer matches)
01.01.2025            -> DATE_TIME 0.6
31/12/2025            -> DATE_TIME 0.6
Q1 2025               -> []  (quarter format — no recognizer matches)
Sie kommt am Mittwoch, 15. März 2025, um 14 Uhr.  -> []
März 2025              -> []
```
3. **EN benign DATE_TIME source — confirms 0.85 spaCy DATE label:**
```
What is the weather in Munich today? (en) -> LOCATION 0.85, DATE_TIME 0.85
How hot is it in Paris this afternoon? (en) -> LOCATION 0.85, DATE_TIME 0.85
```
SpacyRecognizer's `ner_strength = 0.85` (default constant at `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/nlp_engine_recognizers/spacy_recognizer.py:41`).

4. **DE benign DATE_TIME — confirms DE-routed traffic DOES NOT hit the same 0.85:**
```
Wie ist das Wetter heute in München? (de) -> raw=[], redakt=[]
Was kostet ein Kaffee in Berlin? (de)     -> raw=[], redakt=[]
Kannst du mir bei einem Code-Review helfen? (de) -> raw=[], redakt=[]
```
DE is unaffected because the transformer doesn't fire DATE_TIME at all. **The conflict is purely on EN-routed traffic.**

5. **Spec REQ-009b example text is itself broken on the new model:**
```
Der Termin ist morgen um 14 Uhr. (de) -> []
```
`morgen um 14 Uhr` is German colloquial time, and neither `DateRecognizer` (no matching regex pattern) nor xlm-roberta (no DATE label) detects it. The spec used "such as" so the implementer would have substituted, but the substitution space is constrained by the 0.6 / 0.8 ceilings above.

## Critical Learnings

- **The German common-noun-as-PERSON over-detection bug is *gone* on xlm-roberta-large-finetuned-conll03-german.** All 15 enumerated `broader class` nouns produce zero raw entities. REQ-008 / REQ-009 fixture additions are still valuable as CI guards against future regressions, but they don't drive any threshold tune — they're already clean at any threshold.
- **The `de` row's `low_score_entity_names` / `low_confidence_score_multiplier` placeholders (currently `[ORG, ORGANIZATION] / 0.4`) are working as intended.** Probe `Anna Schmidt arbeitet bei der Beispiel AG in Berlin.` (de) shows ORG `BeispielAG` at 0.3999 (= 0.9999 × 0.4), which Redakt's 0.35 default filters cleanly. No re-tune needed for ORG.
- **DATE_TIME on the DE path is regex-only** because the chosen transformer (xlm-roberta CoNLL-03) doesn't have a DATE label. This was not surfaced as a constraint at spec time. RESEARCH-007 §4 surveyed model accuracy for PER/ORG/LOC but did not interrogate DATE coverage; CLARIFICATION-007 Q5c set "calibrate against graded scores" without analyzing the score-source asymmetry between EN (spaCy NER 0.85) and DE (regex 0.6/0.8). REQ-007's "EN row unchanged" decision and REQ-006 Bar 2's "held-out DE DATE_TIME positive" requirement were not cross-checked.
- **Bar 2's "must contain" assertion is already supported** by `tests/eval/test_calibration.py:52-58` (`missing = [e for e in expected if e not in found]; assert not missing`). No harness extension was required and none was made.

## Critical References

- Spec: `SDD/requirements/SPEC-007-transformers-nlp-backend.md` — see REQ-006 (four-bar stopping condition), REQ-007 (EN-row freeze), REQ-009b (held-out positive fixtures).
- ADR: `SDD/adr/0001-presidio-per-language-nlp-engine.md` line 38 (threshold values *are* re-tunable empirically), line 76 ("English bit-for-bit preserved by construction").
- IMPLEMENTATION-PLAN: `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md`.
- DateRecognizer source (the score-ceiling truth): `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/date_recognizer.py` lines 16–82.
- SpacyRecognizer 0.85 source: `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/nlp_engine_recognizers/spacy_recognizer.py:41`.
- Threshold-config home: `src/redakt/config.py:14` (`{"LOCATION": 0.90, "DATE_TIME": 0.95}`).
- multi.yaml: `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml`.

## Next Session Priorities

### This is a SPEC-level handoff, not an implementation-iteration handoff.
The recommended next step is a minimal amendment to REQ-007 + ADR 0001, **not** "try the multilingual fallback model" (ADR 0001 §Alternative G). The model isn't the bug; the threshold space is.

### Recommended spec amendment (minimum scope)

**Amend REQ-007** to permit extending the `en` row's `low_score_entity_names` from `[ORG, ORGANIZATION]` to `[ORG, ORGANIZATION, DATE, TIME]`. Multiplier stays `0.4`. Math:

- EN `en_core_web_lg` DATE / TIME labels currently emit 0.85.
- Post-multiplier: `0.85 × 0.4 = 0.34`.
- Redakt's `default_score_threshold = 0.35` (`src/redakt/config.py:13`) filters `0.34`.
- Net effect: existing EN benign fixtures stay clean (filtering happens via the multiplier instead of via the per-entity threshold).

This unlocks the implementation:
- `entity_score_thresholds["DATE_TIME"]` can drop to `0.55` (or any value in `[0.55, 0.79]`).
- ISO 8601 datetime DE held-out positive at 0.8 PASSES.
- DE common date formats at 0.6 PASS.
- EN DATE_TIME post-multiplier at 0.34 STILL FILTERED — EN benign Bar 1 preserved.
- DE expect_clean fixtures: still empty (xlm-roberta has no DATE label) — preserved.

**Amend ADR 0001 line 76** with a footnote: "`bit-for-bit preserved` refers to engine choice (`en_core_web_lg`), entity surface (the 23-entity superset per RESEARCH-007 §5.1), and `default_recognizers.yaml`. Entity-confidence scoring of `DATE` / `TIME` from `en_core_web_lg`'s NER is multiplied by 0.4 (per `low_score_entity_names` semantics) — these entities still appear as candidates and are selectable by lowering `entity_score_thresholds`. Detection-set non-regression on `tests/eval/fixtures/{generic,benign,us,uk}.yaml` is the operational gate, not literal byte-equality of scores."

### Implementation downstream of the amendment

After the spec amendment lands, chunk 2 work fans out cleanly:

1. **`presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml` `en` row:**
   ```yaml
   low_score_entity_names:
     - ORG
     - ORGANIZATION
     - DATE
     - TIME
   low_confidence_score_multiplier: 0.4
   ```
2. **`src/redakt/config.py:14`:**
   ```python
   entity_score_thresholds: dict[str, float] = {"LOCATION": 0.90, "DATE_TIME": 0.55}
   ```
3. **`tests/eval/fixtures/de.yaml`:** add the 15 broader-class `expect_clean: true` entries (REQ-009) + 3 held-out positives (REQ-009b). For the DE DATE_TIME positive, use:
   ```yaml
   - text: "Treffen am 2025-03-15T14:30:00Z."
     language: de
     expect: [DATE_TIME]
     notes: "ISO 8601 datetime — DateRecognizer 0.8 raw; passes Redakt's 0.55 DATE_TIME floor."
   ```
   For the DE LOCATION positive, the spec's `Sie wohnt in Berlin und arbeitet in München.` works at the harness level (the `missing` check collapses dup `LOCATION` to one), but `Berlin und Hamburg sind große Städte.` is empirically cleaner (both LOCATIONs detected). Either works for the assertion.
4. **Calibration reports:** before/after captured via `tools/calibration_report.py --raw --out`. Annotate per Bar 3.
5. **Long-document anchor:** synthetic German prose totaling 557 tokens (3 repetitions of the 200-word paragraph below); confirmed via `xlm-roberta-large-finetuned-conll03-german` tokenizer.

### Long-doc anchor proof-of-tokenization (already computed in this session)

The following ~200-word German paragraph repeated 3 times produces 557 tokens under the model's tokenizer (computed inside `redakt-presidio-analyzer-1`):

> Das Projekt befindet sich in einer entscheidenden Phase. Die Anforderungen wurden in den letzten Wochen zusammen mit den Fachbereichen erarbeitet. Wir haben die Dokumentation überarbeitet und neue Kapitel zur Architektur ergänzt. Im Rahmen der Konferenz stellten die Entwicklerinnen und Entwickler erste Ergebnisse vor. Die Diskussionen in den Workshops zeigten ein breites Interesse an dem Thema. Wir planen weitere Schulungen, um die Mitarbeitenden auf den neuen Stand zu bringen. Auch die Sicherheitsaspekte werden ausführlich behandelt und in einem eigenen Kapitel beschrieben. Die Tests werden durch automatisierte Verfahren unterstützt, sodass eine hohe Qualität gewährleistet bleibt. Über kommende Änderungen werden wir Sie regelmäßig informieren. Bei Fragen wenden Sie sich bitte an die zuständigen Ansprechpersonen im Bereich Forschung und Entwicklung.

Use this as the long-doc fixture body verbatim (3 repetitions concatenated; record the 557 token count in the fixture comment). When the spec amendment lands and chunk 2 is restarted, this paragraph saves ~5 minutes of re-derivation.

## Essential Files to Reload

- `SDD/requirements/SPEC-007-transformers-nlp-backend.md` (REQ-006, REQ-007, REQ-009, REQ-009b)
- `SDD/adr/0001-presidio-per-language-nlp-engine.md` (lines 38, 76)
- `tests/eval/test_calibration.py` (already supports `expect_clean` and "must contain")
- `tests/eval/_loader.py` (Phrase dataclass)
- `tests/eval/fixtures/de.yaml`, `tests/eval/fixtures/benign.yaml` (existing fixture format)
- `presidio/presidio-analyzer/presidio_analyzer/conf/multi.yaml`
- `src/redakt/config.py`
- `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/date_recognizer.py`
- `tools/calibration_report.py`

## Implementation Priorities (after the spec amendment)

1. Apply the agreed-upon EN-row extension (`DATE`, `TIME` added to `low_score_entity_names`) in `multi.yaml`; restart `presidio-analyzer`; verify the 41 existing fixtures stay PASS via `pytest tests/eval/`.
2. Drop `entity_score_thresholds["DATE_TIME"]` to `0.55`; restart `redakt`; re-verify pytest still green.
3. Add the 15 broader-class `expect_clean: true` fixtures (REQ-009) and 3 held-out positives (REQ-009b). Re-run pytest — should be 59/59 PASS.
4. Capture before/after calibration reports. Annotate per Bar 3.
5. Verify Bar 4 reproducibility (re-run calibration_report twice, confirm thresholds stable).
6. Commit per the two-repo discipline in the original chunk-2 brief.

## Specification Validation Remaining

- [ ] REQ-006 — blocked on spec amendment for DATE_TIME; will resolve via 0.55 threshold + EN-row low-score extension.
- [ ] REQ-007 — blocked on EN-row freeze loosening; ADR 0001 footnote clarification.
- [ ] REQ-008 — fixtures designed but not written.
- [ ] REQ-009 — fixtures designed but not written.
- [ ] REQ-009b — fixtures designed (DATE_TIME text revised to ISO 8601, LOCATION kept as spec text); not written.

## Counter usage at bail point

- Reads: 13/15 (orientation + diagnosis only; no fixture or config writes).
- Nested subagents: 0/4.

## Bounded handoff

This is a **deliberate spec-level handoff at iteration 0**, not a "tried hard, gave up after 15 iterations" bail. The next session should NOT attempt to re-iterate the calibration without first resolving the REQ-007 / ADR 0001 amendment, because no value of `entity_score_thresholds["DATE_TIME"]` can satisfy Bars 1 and 2 simultaneously under the current spec.
