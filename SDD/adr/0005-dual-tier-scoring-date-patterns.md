---
adr: 0005
title: Use dual-tier scoring (0.95 canonical / 0.85 ambiguous) for DateRecognizer pattern additions
status: Accepted
date: 2026-05-12
supersedes: null
superseded_by: null
tags: [cross-cutting, presidio, pii-detection, score-arithmetic, recognizer-authorship]
---

# ADR 0005: Use dual-tier scoring (0.95 canonical / 0.85 ambiguous) for DateRecognizer pattern additions

## Status

Accepted (2026-05-12)

Captured retroactively on 2026-05-13 from `docs/customizations.md` (Item 4) and fork commit `184d0e1`.

## Context

Redakt's default `entity_score_thresholds` sets `DATE_TIME: 0.95`. The floor exists because spaCy's NLP-driven `DATE_TIME` detections overfire on bare temporal words (`today`, `tomorrow`, `next weekend`) at a constant 0.85 — the 0.95 floor is the cheapest way to drop the NLP overfire while preserving regex-driven detections at higher scores. This calibration was anchored before the cross-border push (fork commit `ee93662` split `DateRecognizer`'s `dd.mm.yyyy` pattern: 4-digit-year form at 0.95, 2-digit form at 0.4).

Memodo pilot phrase 07 (`"…originally promised by March 28, 2026."`) surfaced an English `DATE_TIME` recall gap — the existing `dd.mm.yyyy` patterns are German-shaped; English long-form dates didn't match anything in `DateRecognizer` and weren't caught by the NLP backend either at the 0.95 floor.

The cross-cutting question this decision answered: **when adding regex patterns to `DateRecognizer` (or any recognizer where multiple pattern shapes have materially different incidental-match risk), do we score them uniformly and let the floor sort it out, or do we encode the consumer-floor interaction in the per-pattern score?**

This generalizes beyond `DateRecognizer`. Any future recognizer where pattern strength varies (e.g., currency amounts with vs without currency symbol; phone numbers with vs without country code; ID numbers with vs without checksum) faces the same question.

## Decision

Use a **dual-tier scoring convention** for `DateRecognizer` pattern additions:

- **0.95** for unambiguous canonical forms (fully spelled-out month + 4-digit year + day): `Month DD, YYYY` and `DD Month YYYY`. Clears the default `DATE_TIME: 0.95` consumer floor end-to-end. Always-on at default config.

- **0.85** for forms with higher incidental-match risk (abbreviated 3-letter month; no-day quarter form): `Mon DD, YYYY` and `Q[1-4] YYYY`. Intentionally **below** the default floor — surfaces only when a request-level `entity_score_thresholds` lowers it. The regex-layer equivalent of fork `ee93662`'s `dd.mm.yy at 0.4`.

| Pattern | Example | Score | Behavior at default config |
|---|---|---|---|
| `Month DD, YYYY` | `March 28, 2026` | 0.95 | Always detected |
| `DD Month YYYY` | `28 March 2026` | 0.95 | Always detected |
| `Mon DD, YYYY` | `Mar 28, 2026` | 0.85 | Available-on-demand only |
| `Q[1-4] YYYY` | `Q3 2026` | 0.85 | Available-on-demand only |

`PatternRecognizer` compiles with `re.IGNORECASE` in its `global_regex_flags` (fork `pattern_recognizer.py:47`), so a single Pascal-case alternation covers any input casing — `march 28, 2026` and `q1 2026` are verified-live matches.

Day-range `([1-9]|0[1-9]|[1-2][0-9]|3[0-1])` and `Q[1-4]` guardrails anchor the negative cases: `March 32, 2026` and `Q5 2026` do not match. Bare `March 2026` (no day) doesn't match either (pinned in eval as `expect_clean`).

**Cross-cutting principle:** *regex patterns score relative to their incidental-match risk, not their structural completeness.* A pattern that would match real but ambiguous prose (a proper-noun month abbreviation; a quarter that overlaps with project-quarter labels) sits below the consumer floor; a pattern that only matches unambiguously canonical dates sits above it.

## Alternatives Considered

### Chosen — Dual-tier 0.95 / 0.85

Encodes the consumer-floor interaction at recognizer-authorship time, where the pattern's incidental-match risk is best understood. Future pattern additions inherit the rule: weigh incidental-match risk, place above or below the default floor accordingly.

### Single score per pattern, calibrated empirically post-merge

Rejected: collapses the canonical/ambiguous distinction; future pattern additions would need to re-litigate the consumer-floor interaction every time someone adds a pattern; calibration-tool tuning per pattern is more work than encoding the tier at authorship.

### Single high score (0.95) for all four

Rejected: `Mar` overlaps with proper noun (`Mar` as a person's name fragment in some locales); `Q3` overlaps with project quarters, equipment series codes (`Q3 2026 capacity`), and academic-quarter references. Forcing these to 0.95 means they fire at default config and operators have to filter them per-instance. The dual-tier puts the burden on operators who *want* abbreviated-month detection (rare) rather than on operators who don't (default).

### Single low score (0.85) for all four

Rejected: canonical forms (`March 28, 2026`) then require operator threshold-lowering to be useful at all. Pilot phrase 07 — the bug driving the addition — wouldn't be fixed at default config.

### Add to NLP recognizers instead of regex

Rejected: relative-time (`next Monday`, `tomorrow`) is appropriately NLP territory because it requires semantic understanding; absolute long-form dates are appropriately regex territory because their structure is fully specified. The cross-border push intentionally keeps the NLP/regex boundary stable.

## Consequences

### Positive

- Default-config users get high-confidence date detection on canonical English long-form dates without tuning. Pilot phrase 07 closes.
- Power-users (or specific request flows) can opt into ambiguous forms by lowering `DATE_TIME` per request to 0.8 or 0.85 — verified live at `DATE_TIME: 0.8` on `Mar 28, 2026` and `Q3 2026`.
- **Sets a recognizer-authorship convention** that future date patterns and analogous multi-tier regex patterns inherit: ISO 8601 with timezone (canonical → 0.95), `MM/DD` no-year (ambiguous → 0.85), etc. The same logic generalizes to other recognizers (phone numbers with/without country code, currency with/without symbol).
- Eval-suite pinning: 93/93 (+5 over the 88 baseline) — including 2 expect_clean negatives (`Section 32, 2026` day-out-of-range, bare `March 2026` no-day) anchoring the guardrails.

### Negative / Trade-offs accepted

- Adds a second tier of "structurally available but floor-gated" patterns that operators reading the recognizer source need to know about. Documented in `docs/customizations.md` Item 4; the doc is the durable record.
- The 0.95 vs 0.85 split is judgement, not calculation. Future contributors adding a pattern at e.g. 0.90 (between the tiers) need to choose: does it clear the floor at default, or not? The convention forces a binary choice; intermediate scores erode the contract.
- Relative time (`next Monday`, `tomorrow`, `last week`) is NOT addressed by this ADR. Remains NLP territory with the floor-driven filtering issues that already exist.

### Neutral observations

- `DateRecognizer` is auto-instantiated for both `en` and `de` root languages (no per-language registration in `default_recognizers.yaml`); pattern additions automatically apply to both. Verified live; documented in `docs/customizations.md` Item 4.
- This decision binds: future `DateRecognizer` pattern additions; the broader cross-cutting principle that regex-pattern scores encode incidental-match risk, not pattern shape completeness.

## References

- `docs/customizations.md` — Item 4 (per-pattern regex, score arithmetic, live-verification commands, guardrail negative cases).
- `.presidio-pin` — `184d0e1` notes block (per-pattern rationale, IGNORECASE verification, day-range / Q-range guardrails).
- Fork commit `184d0e1` — pattern additions + `test_date_recognizer.py` parametrize entries.
- Fork commit `ee93662` — prior dual-tier split (`dd.mm.yyyy` at 0.95, `dd.mm.yy` at 0.4) that this ADR codifies as a general pattern.
- `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/date_recognizer.py` — recognizer source.
- `presidio/presidio-analyzer/presidio_analyzer/pattern_recognizer.py:47` — `global_regex_flags` / `re.IGNORECASE` compilation source.
- `src/redakt/config.py` — `entity_score_thresholds` default (`DATE_TIME: 0.95`).
- `tests/eval/fixtures/generic.yaml` + `tests/eval/fixtures/de.yaml` — pattern-addition eval fixtures (positives + 2 expect_clean guardrails).
