---
adr: 0004
title: Accept industry-vertical recognizers in the Presidio fork's DE baseline (PV/energy)
status: Accepted
date: 2026-05-12
supersedes: null
superseded_by: null
tags: [cross-cutting, presidio, pii-detection, fork-scope, recognizer-authorship]
---

# ADR 0004: Accept industry-vertical recognizers in the Presidio fork's DE baseline (PV/energy)

## Status

Accepted (2026-05-12)

Captured retroactively on 2026-05-13 from `docs/customizations.md` (Item 3) and fork commit `798b266`.

## Context

Memodo is a B2B photovoltaic-wholesale business. PV correspondence carries industry-specific identifiers that don't fit the "government-issued PII" frame Presidio's predefined recognizers traditionally target:

- **MaLo-ID** (`DE_MALO`, BDEW MaLo-ID Anwendungshilfe) — 11-digit market-location identifier with a BDEW Mod-10 weighted-digit-sum checksum.
- **MeLo-ID** (`DE_MELO`, VDE-AR-N 4400) — 33-char DE-prefixed metering-location identifier.
- **Anlagenschlüssel** (`DE_EEG_ANLAGE`, BDEW Beschluss BK6-13-200) — 33-char EEG-plant identifier.
- **Zählernummer** (`DE_ZAEHLERNUMMER`) — 8–15-char alphanumeric meter number; vendor-defined, no checksum.

These identifiers uniquely identify Memodo's customer base in PV correspondence in the same way that tax IDs and personal IDs do in general B2B correspondence. The cross-cutting question this decision answered: **what's in scope for the Presidio fork's DE baseline?** Specifically — does the fork accept industry-specific recognizers, or do verticals belong on the operator's side as custom YAML?

This is a fork-scope decision, not a per-recognizer one. The same question will arise for future verticals (healthcare-specific IDs beyond LANR/BSNR, telecom-specific IDs, finance-specific IDs beyond the banking adjuncts in ADR 0006). The decision here sets the precedent.

## Decision

**Industry-vertical recognizers are in scope for fork-side additions when the operator's actual traffic carries them at material density.** Four PV-industry recognizers landed in fork commit `798b266`, all dual-registered en+de per ADR 0003:

| Recognizer | Pattern | Base score | Promotion mechanism |
|---|---|---|---|
| `DeEegAnlageRecognizer` | `\b[A-Z0-9]{33}\b` | 0.4 | Structural width clears 0.35 floor; CONTEXT +0.35 boosts labelled lines. |
| `DeMaloRecognizer` | `\b\d{11}\b` | low (matches phone numbers) | `validate_result == True` (Mod-10 weighted-digit-sum checksum) promotes to **1.0** per Presidio's PESEL/SSN/ABA convention. |
| `DeMeloRecognizer` | `\bDE[A-Z0-9]{31}\b` | 0.6 | Fixed `DE` prefix tightens the surface. |
| `DeZaehlernummerRecognizer` | `\b(?=[A-Z0-9]{8,15}\b)[A-Z]*\d[A-Z0-9]*\b` | 0.05 | CONTEXT (`Zähler`, `Stromzähler`, `Gerätenummer`) +0.35 = 0.40, clearing 0.35 floor. ≥1-digit lookahead eliminates pure-letter German prose. Same model as `DePlzRecognizer`. |

Two cross-cutting sub-decisions are baked in and bind future recognizer work:

1. **Industry-vertical recognizers are first-class fork residents** (not operator-side custom YAML). Future verticals follow this path.

2. **Intentional structural overlap is tolerated and resolved by the consumer template.** `DE_MELO` and `DE_EEG_ANLAGE` both fire on DE-prefixed 33-char spans; subset-matching in the eval suite tolerates the duplication; the anonymization template picks one winner per span. This generalizes the policy already implicit between `EU_VAT_ID` and `DE_VAT_ID` (ADR 0002) and between `SEPA_CREDITOR_ID` and `IBAN_CODE` (ADR 0006).

## Alternatives Considered

### Chosen — Vertical recognizers in fork

Each Memodo-shaped deployment inherits PV coverage out of the box. Cross-border English PV traffic also covered via en registration (ADR 0003). Checksum validation lives where the pattern lives. One source of truth.

### Operator-side custom recognizer YAML

Rejected: each deployment would re-author the same four recognizers; pattern duplication across instances; loses checksum validation (every operator would need to re-implement `DeMaloRecognizer.validate_result`); makes recognizer updates an operator-side concern instead of a fork-version-bump concern.

### Recognize PV identifiers as opaque `CUSTOM_ID`

Rejected: collapses four distinct entity types into one generic bucket; loses per-entity tuning (operators can't raise the `DE_ZAEHLERNUMMER` floor independently of `DE_MALO`); loses BDEW Mod-10 checksum on `DE_MALO` (its 90%-FP-filter is the whole point); loses the per-entity anonymization template (`<DE_MALO>` vs `<DE_MELO>` is more legible than `<CUSTOM_ID>`).

### Defer to a future "Presidio plugin" architecture

Rejected: no such architecture exists in Presidio's roadmap; would block the cross-border push indefinitely; fork-side recognizers are the supported extension path today.

## Consequences

### Positive

- PV correspondence anonymizes correctly out of the box for any Memodo-shaped deployment, including cross-border English traffic.
- `DE_MALO` at score 1.0 (post-checksum) is a strong contract: structurally valid 11-digit spans that *also* pass Mod-10 are near-certain MaLo-IDs, distinguishable from phone numbers and order IDs.
- `DE_ZAEHLERNUMMER`'s low-base + context-gated arithmetic mirrors `DE_PLZ`'s established pattern — future low-information identifiers can be added the same way without re-deriving the safety argument.
- Sets fork-scope precedent: **industry verticals belong in the fork when there's operator demand**. Future verticals (healthcare beyond LANR/BSNR, telecom, finance) follow this path rather than living in operator-side YAML.

### Negative / Trade-offs accepted

- Fork carries four more recognizers indefinitely. Every Presidio upstream merge re-applies them as conflicts. Same maintenance argument as ADR 0001's `MultiNlpEngine` — accepted cost.
- Intentional `DE_MELO` ↔ `DE_EEG_ANLAGE` overlap means DE-prefixed 33-char spans return two entities per span. Subset-matching in the eval suite tolerates this; operators reading raw detection output see both.
- `DE_ZAEHLERNUMMER` is the most permissive of the four (any 8–15 alphanumeric with ≥1 digit). The CONTEXT-gating + 0.05 base score keeps the bare-pattern false-positive rate near zero, but the recognizer is structurally fragile: a future CONTEXT-list change in an unrelated PR could lift the score over the 0.35 floor on unintended spans. Pinned in CI by a negative anchor (`"Lieferadresse: Solarweg 12, 80331 München. Kein PV-Zubehör vorrätig."` expects exactly `[DE_PLZ]`).

### Neutral observations

- The Mod-10 checksum implementation in `DeMaloRecognizer.validate_result` is the only checksum among the four. The other three rely on pattern + CONTEXT. If a future vertical request comes with a published checksum (similar to BDEW MaLo-ID Anwendungshilfe), the `validate_result → 1.0` promotion is the preferred mechanism over higher base scores.
- This decision binds: every future industry-vertical recognizer addition to the fork; the precedent that "operator demand at material density" is the gating criterion (not e.g. "is it in Presidio's upstream roadmap" — it almost never is for verticals).

## References

- `docs/customizations.md` — Item 3 (per-recognizer regex, score arithmetic, eval-fixture counts, intentional-overlap rationale, negative anchor pinning).
- `.presidio-pin` — `798b266` notes block (BDEW + VDE-AR-N citations, full score-arithmetic derivation, Mod-10 checksum formula).
- Fork commit `798b266` — four recognizer sources + `default_recognizers.yaml` registrations.
- ADR 0003 — dual-registration policy (these four follow it).
- ADR 0002 — intentional structural overlap precedent (extended here to within-DE overlaps).
- BDEW Beschluss BK6-13-200 — `DE_EEG_ANLAGE` specification.
- BDEW MaLo-ID Anwendungshilfe — `DE_MALO` Mod-10 checksum specification.
- VDE-AR-N 4400 — `DE_MELO` specification.
- `docs/supported-entities.md` — DE section catalog rows for all four.
