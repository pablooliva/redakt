---
adr: 0006
title: Wrap case-sensitive recognizer patterns in inline `(?-i:...)` and anchor structurally loose patterns on ISO 3166-1 alpha-2
status: Accepted
date: 2026-05-12
supersedes: null
superseded_by: null
tags: [cross-cutting, presidio, pii-detection, recognizer-authorship, fork-quirk]
---

# ADR 0006: Wrap case-sensitive recognizer patterns in inline `(?-i:...)` and anchor structurally loose patterns on ISO 3166-1 alpha-2

## Status

Accepted (2026-05-12)

Captured retroactively on 2026-05-13 from `docs/customizations.md` (Item 5) and fork commit `a01a3b3`.

## Context

Item 5 (BIC + SEPA Creditor ID) surfaces two related fork-wide recognizer-authorship conventions worth codifying. Both apply to **any** future recognizer that fits the pattern, not just to BIC/SEPA.

### Concern 1: case-sensitivity in a Presidio fork that defaults to IGNORECASE

`BIC_CODE` (ISO 9362) and `SEPA_CREDITOR_ID` (EPC scheme) use uppercase-alphanumeric patterns: `[A-Z]{4}<country>[A-Z0-9]{2}(?:[A-Z0-9]{3})?` and `<country>[0-9]{2}[A-Z0-9]{3}[A-Z0-9]{1,28}` respectively. Under Presidio's default `re.IGNORECASE` (set in `pattern_recognizer.py:47` `global_regex_flags`), these patterns match every lowercase 8-letter word in German/English prose — `"rechnung"`, `"internal"`, `"mitarbei"`. The recognizer becomes unusable.

The natural fix — drop `IGNORECASE` for these specific recognizers — runs into a fork quirk: `RecognizerRegistry.__instantiate_recognizer` (fork `recognizer_registry.py:308`) executes

```python
inst.global_regex_flags = self.global_regex_flags
```

at YAML load. Any constructor-level `global_regex_flags=` override is silently overwritten with the registry-level value. The recognizer is left case-insensitive regardless of what its `__init__` declared.

This is a structural fork quirk: it's not fixable upstream without breaking compatibility (the registry intentionally normalizes flags across all loaded recognizers). Every future case-sensitive recognizer will hit it.

### Concern 2: false-positive narrowing on structurally-loose alphanumeric patterns

Both BIC and SEPA CI use country-prefix alphanumeric shapes (`[A-Z]{4}<country>[A-Z0-9]{2}…`, `<country>[0-9]{2}[A-Z0-9]{3}[A-Z0-9]{1,28}`). A bare `[A-Z]{8}` would match every uppercase 8-letter word — far too permissive. The 2-letter country slot is the cheapest structural FP-narrower available: ~249 valid ISO 3166-1 alpha-2 codes out of 676 possible 2-letter combinations (63% reduction in match surface). Common uppercase 8-letter words that *don't* contain a valid country code at the right position (`INTERNAL` — positions 5–6 = `RN`, not assigned; `MITARBEI` — `RB`, not assigned; `FRANKFUR` — `KF`, not assigned) are suppressed for free.

The same anchor applies to: `EU_VAT_ID` (positions 1–2, ADR 0002), `DE_VAT_ID` (DE prefix), `DE_MELO` (DE prefix, ADR 0004), IBAN_CODE (positions 1–2, upstream). It's already implicit across the recognizer family; this ADR makes it a named convention so future contributors apply it consistently.

## Decision

Two cross-cutting recognizer-authorship conventions, both binding fork-wide for future work:

### Convention 1 — Inline `(?-i:...)` flag scoping for case-sensitive patterns

Wrap any case-sensitive pattern in an inline scoped flag group:

```
(?-i:<pattern>)
```

This is the **only** mechanism that survives `RecognizerRegistry.__instantiate_recognizer`'s flag overwrite (fork `recognizer_registry.py:308`). Constructor-level `global_regex_flags=` does not survive. Registry-level overrides are global (would affect every recognizer in the registry, including those that legitimately want `IGNORECASE`).

Verified live: without the inline drop, `"die rechnung deutdeff steht aus"` returns `BIC_CODE`; with the drop, 0 entities. `"Rechnung Nr. 12345 ist bezahlt"` → 0 entities (no spurious BIC match).

### Convention 2 — ISO 3166-1 alpha-2 country anchor for structurally loose patterns

When a recognizer's pattern legitimately contains a country code (BIC positions 5–6; SEPA CI positions 1–2; VAT IDs positions 1–2; IBAN positions 1–2), constrain that slot to the ISO 3166-1 alpha-2 list (~249 codes) rather than a bare `[A-Z]{2}`. The anchor narrows the false-positive surface by ~63% for free.

Residual FPs are anchored as documented limits in fork unit tests (`test_residual_fp_documented`): `RECHNUNG` (`NU` = Niue, ISO-valid) and `INSTITUT` (`IT` = Italy, ISO-valid) at all-caps fire BIC. In practice these tokens appear in title case in B2B prose; the inline IGNORECASE drop (Convention 1) suppresses them. The combination of the two conventions is what makes the recognizer usable.

### Patterns landed under both conventions

| Recognizer | Pattern | Base score |
|---|---|---|
| `BicSwiftRecognizer` | `(?-i:(?<![A-Z0-9])[A-Z]{4}<ISO-alpha-2>[A-Z0-9]{2}(?:[A-Z0-9]{3})?(?![A-Z0-9]))` | 0.85 |
| `SepaCreditorIdRecognizer` | `(?-i:(?<![A-Z0-9])<ISO-alpha-2>[0-9]{2}[A-Z0-9]{3}[A-Z0-9]{1,28}(?![A-Z0-9]))` | 0.85 |

Both dual-registered en+de per ADR 0003.

**Intentional overlap with `IBAN_CODE`.** SEPA CI matches IBAN-shaped spans ≥ 15 chars (both fire; IBAN's `validate_result` boosts checksum-valid IBANs to 1.0 so `IBAN_CODE` wins by score; consumer template chooses per span). The 8–14 char range is the unambiguous SEPA-only zone where IBAN never matches. Generalizes the within-DE overlap policy from ADR 0004.

## Alternatives Considered

### Chosen — Inline `(?-i:...)` + ISO country anchor

Solves both concerns at recognizer-authorship time. Survives the registry flag-overwrite. Per-pattern, no cross-recognizer side-effects. Sets a convention that future case-sensitive or country-prefixed recognizers inherit.

### Constructor-level `global_regex_flags=` override

Rejected: doesn't survive `RecognizerRegistry.__instantiate_recognizer`'s overwrite (fork `recognizer_registry.py:308`). Silently broken — the recognizer compiles, loads, and fires on lowercase prose, with no error message. The failure mode is "recognizer is useless"; future contributors hit it and re-discover the registry quirk from scratch. This ADR exists partly to prevent that re-discovery.

### Registry-level flag override (drop `IGNORECASE` globally)

Rejected: affects every recognizer in the registry. Many legitimately want `IGNORECASE` (e.g., `EmailRecognizer`, most NLP-context recognizers). Global drop would silently regress them.

### Higher base score to filter FP word-matches via floor

Rejected: pushes the problem onto operator-side threshold config; doesn't solve the root cause (recognizer matches lowercase 8-letter prose at all); inflates the per-entity floor for legitimate BIC matches that don't need it.

### Bare `[A-Z]{2}` country slot (no ISO anchor)

Rejected: 63% wider match surface; every uppercase 8-letter word fires `BIC_CODE`. The ISO anchor is cheap and obvious in retrospect; codified here so future country-prefixed recognizers don't omit it.

### SEPA mandate references via regex

Considered and rejected as a separate decision (carried as open follow-up in `docs/customizations.md`): mandate refs have no fixed structural shape — they range from short opaque tokens to free-form vendor strings — so any tight regex misses too many real cases and any loose regex matches too much prose. No regex layer is the right answer for this entity. Future contributors should not re-litigate without new evidence (e.g., a vendor-specific prefix convention worth modeling).

## Consequences

### Positive

- Two case-sensitive recognizers land cleanly without breaking lowercase prose. Verified by paired `expect_clean` anchors in the eval suite: `"please wire via swift code chasus33 to the new account"` (en) and `"Rechnung Nr. 12345 ist bezahlt"` (de) — both expect 0 entities; the inline flag drop is what makes them pass.
- ISO country-code anchor is a sharp, narrow, well-defined FP-narrower reusable for any future country-prefixed recognizer.
- **Future case-sensitive recognizers inherit Convention 1; future country-prefixed recognizers inherit Convention 2.** Both conventions are now part of the fork's recognizer-authorship contract and survive in `docs/customizations.md` Item 5 + this ADR for handover.
- Eval-suite pinning: 102/102 (+9 over the 93 baseline). Fork-side unit tests: 36 BIC cases + 26 SEPA CI cases, including `test_residual_fp_documented` anchors for `RECHNUNG`/`INSTITUT` as named limits.

### Negative / Trade-offs accepted

- Future contributors must remember Convention 1's inline-scoping requirement. If forgotten, the recognizer silently FPs on lowercase prose with no error message. Mitigation: this ADR + `docs/customizations.md` Item 5 + an inline comment at each recognizer source citing `recognizer_registry.py:308`.
- Residual FPs `RECHNUNG`/`INSTITUT` at all-caps remain. Documented as named limits; not worth working around (rare in B2B prose; the IGNORECASE drop handles the title-case forms that actually appear).
- Intentional `SEPA_CREDITOR_ID` ↔ `IBAN_CODE` overlap means IBAN-shaped spans ≥ 15 chars return two entities. Subset-matching tolerates it; same policy as ADR 0002 and ADR 0004.

### Neutral observations

- SEPA mandate references intentionally not regex-recognized. Pinned here as a deliberate non-decision (and in `docs/customizations.md` Open follow-ups). Revisit only if a structural anchor emerges.
- This decision binds: every future case-sensitive recognizer added to the Presidio fork (Convention 1); every future recognizer whose pattern legitimately contains a country code (Convention 2). It also generalizes the intentional-structural-overlap policy from ADR 0004 to the cross-recognizer case (SEPA CI ↔ IBAN).

## References

- `docs/customizations.md` — Item 5 (full pattern, score arithmetic, IBAN overlap policy, paired lowercase-suppression eval anchors, residual-FP documentation).
- `.presidio-pin` — `a01a3b3` notes block (registry quirk citation, live-verification commands, ISO country-code surface math).
- Fork commit `a01a3b3` — `BicSwiftRecognizer` + `SepaCreditorIdRecognizer` source, registrations, unit tests.
- Fork `presidio-analyzer/presidio_analyzer/recognizer_registry/recognizer_registry.py:308` — the `inst.global_regex_flags = self.global_regex_flags` overwrite that motivates Convention 1.
- Fork `presidio-analyzer/presidio_analyzer/pattern_recognizer.py:47` — `global_regex_flags = re.IGNORECASE` default.
- ADR 0002 — country-prefix anchoring precedent (`EU_VAT_ID` positions 1–2).
- ADR 0003 — dual-registration policy (both recognizers registered en+de).
- ADR 0004 — intentional structural overlap toleration (extended here to cross-recognizer overlap).
- ISO 9362 — BIC specification.
- EPC SEPA Creditor Identifier scheme — `SEPA_CREDITOR_ID` specification.
- `docs/supported-entities.md` — `BIC_CODE` + `SEPA_CREDITOR_ID` catalog rows + Notes "Overlap is expected".
