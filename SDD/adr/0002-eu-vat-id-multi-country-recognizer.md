---
adr: 0002
title: Use a single multi-country EU_VAT_ID recognizer over per-country EU VAT recognizers
status: Accepted
date: 2026-05-11
supersedes: null
superseded_by: null
tags: [cross-cutting, presidio, pii-detection, recognizer-authorship]
---

# ADR 0002: Use a single multi-country EU_VAT_ID recognizer over per-country EU VAT recognizers

## Status

Accepted (2026-05-11)

Captured retroactively on 2026-05-13 from `docs/customizations.md` (Item 1) and fork commit `587957a`.

## Context

Memodo's B2B PV-wholesale footprint is a German HQ with subsidiaries in Italy, Czechia, and the Netherlands, plus regular cross-border traffic from Austrian, Polish, and Swiss suppliers. Pre-cross-border-push, Presidio's `DeVatIdRecognizer` covered only DE-prefixed VAT IDs; the 26 other EU prefixes that flow through Memodo correspondence (`IT…`, `CZ…`, `NL…`, `AT…`, `PL…`, `FR…`, …) produced zero detections. Presidio ships per-country recognizers for some EU member states (`IT_VAT_CODE` for Italy's Partita IVA) but not for the full 27.

The cross-cutting question this decision answered: when a single structural pattern covers an entire class of regional identifiers (here, all EU VAT IDs share the `<2-letter-country>` + 8–12 alphanumeric body shape per the VIES spec), do we (a) build 26 per-country recognizers, (b) extend Presidio's shipped recognizers piecewise, or (c) author one umbrella recognizer with a country-prefix alternation? The choice sets precedent for any future multi-region identifier class (EU-wide banking identifiers, multi-country tax IDs, regional vehicle plates).

## Decision

Add a single `EuVatIdRecognizer` matching all 27 EU country prefixes via a single alternation, registered for both `en` and `de` at base score `0.5`:

```
(AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|GB|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK)[A-Z0-9]{8,12}
```

Per-prefix body lengths follow the VIES spec; lookaround anchors prevent matches from extending into adjacent alphanumeric tokens. The IT/NL/CZ country-specific recognizers Presidio ships were intentionally disregarded — the umbrella recognizer subsumes them.

**Intentional overlap with `DeVatIdRecognizer`.** On DE-prefixed VAT spans, both `EU_VAT_ID` and `DE_VAT_ID` fire as separate entities. `DeVatIdRecognizer` is unchanged and remains the `de`-only authority on DE prefixes; subset-matching in the eval suite tolerates the duplication; the anonymization template picks one winner per span.

## Alternatives Considered

### Chosen — Single multi-country recognizer

One alternation across all 27 prefixes, one base score, one registration. Covers IT/NL/CZ subsidiaries and AT/PL/CH-adjacent suppliers transitively. Per-prefix body-length constraints from VIES live inside the same recognizer; no proliferation of files or registrations.

### Per-country recognizers for each EU member

Rejected: combinatorial maintenance burden — 27 recognizers (or more, after counting the GB-after-Brexit and pre-Brexit dual). Presidio only ships `IT_VAT_CODE`; the rest would need to be authored from scratch. Adds 26 entries to `default_recognizers.yaml` for no detection-quality gain, since the structural pattern is identical across countries and per-country checksum validation is not part of the in-scope contract.

### Stay with `DeVatIdRecognizer` only; rely on operator-side custom recognizers

Rejected: leaves 26 EU prefixes uncovered out of the box; every Memodo-shaped deployment would re-author the same recognizer locally; loses the cross-instance reusability that justifies the fork.

### Hybrid — umbrella recognizer + per-country checksum validators

Considered for future work but rejected for v1: per-country VAT checksum algorithms exist (modulus 11 for AT, MOD 97-10 for BE, custom for FR, etc.) and would push detection to score 1.0 on checksum-valid spans, but the validators are 27 distinct algorithms and the structural-only recognizer already clears the default 0.35 floor at base 0.5. Documented as a future enhancement, not adopted now.

## Consequences

### Positive

- One recognizer covers all 27 EU prefixes; symmetric coverage across all Memodo subsidiary and supplier traffic in a single commit.
- Future EU expansion (Memodo onboarding a new EU country) needs zero new recognizer code. The umbrella absorbs new members transitively.
- Sets a reusable pattern: **umbrella recognizers over structurally-shared regional identifier classes are preferred to per-country proliferation**. Future candidates inheriting this pattern: EU-wide banking identifiers, multi-country tax-resident IDs.
- Per-prefix body-length constraints (from VIES) keep the FP surface tight despite the broad country alternation.

### Negative / Trade-offs accepted

- Coarser than per-country: no per-country checksum validation. A structurally valid but checksum-invalid VAT (e.g., a transposed-digit typo) still fires at 0.5. Acceptable given Redakt's goal is anonymization, not validation.
- Intentional overlap with `DeVatIdRecognizer` on DE prefixes: two entities per span. Subset-matching in the eval suite tolerates it, but operators reading raw detection output see both. Documented in `docs/supported-entities.md` Notes.
- Base score 0.5 (rather than 0.85) keeps the recognizer below structural-near-certainty entities; operators raising thresholds aggressively may need a per-entity floor.

### Neutral observations

- This decision binds future cross-border recognizer work: when a structural pattern covers a regional class, prefer one umbrella recognizer + country-prefix alternation. Re-litigate only if per-country checksum validation becomes contractually required.

## References

- `docs/customizations.md` — Item 1 (entity index, regex, rationale).
- `.presidio-pin` — `587957a` notes block (full per-prefix body-length rationale, lookaround anchor justification).
- Fork commit `587957a` — `EuVatIdRecognizer` source + registration.
- VIES VAT number format specification — per-prefix body-length constraints.
- `docs/supported-entities.md` — `EU_VAT_ID` row + Notes "Overlap is expected" entry.
