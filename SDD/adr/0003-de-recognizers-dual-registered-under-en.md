---
adr: 0003
title: Dual-register country-specific recognizers under en for cross-border subsidiary traffic
status: Accepted
date: 2026-05-12
supersedes: null
superseded_by: null
tags: [cross-cutting, presidio, pii-detection, language-routing, recognizer-authorship]
---

# ADR 0003: Dual-register country-specific recognizers under `en` for cross-border subsidiary traffic

## Status

Accepted (2026-05-12)

Captured retroactively on 2026-05-13 from `docs/customizations.md` (Item 2) and fork commit `19d3c87`.

## Context

Memodo's IT/CZ/NL subsidiaries communicate predominantly in English, both internally and with the German HQ. Pre-2026-05-12, every DE_* recognizer in Presidio's `default_recognizers.yaml` carried `supported_languages: [de]` only. The lingua-py auto-detect (per ADR 0001) correctly routes English correspondence to the `en` engine path; the analyzer then sees zero DE_* recognizers registered for `en` and returns zero PII even on text that explicitly mentions German VAT IDs, postal codes, tax numbers, etc.

Two cross-cutting concerns drive the question:

1. **Language-registration policy.** Is language scoping a coarse safety filter ("DE recognizers only when the user *meant* German") or a fine routing signal ("DE recognizers when the *content* is German")? Presidio's default leans the first way; Memodo's actual traffic shape — English wrappers around German identifiers — argues the second.

2. **False-positive containment on cross-language registration.** Naive dual-registration risks polluting English text with low-base DE_* matches that should stay context-gated. The score-arithmetic safety argument needs to be made explicit so future contributors don't re-litigate it for each new country.

## Decision

Add `- en` to `supported_languages` on every DE_* entry in `presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml` — 12 entries total (9 enabled, 3 disabled). YAML-only change; no recognizer code touched.

**Score-arithmetic safety argument** (the load-bearing rationale):

- **Low-base context-gated DE_*** (`DE_PLZ` 0.05, `DE_KFZ` 0.2–0.3, `DE_HEALTH_INSURANCE` 0.3, `DE_FUEHRERSCHEIN` 0.35 with the Redakt-side 0.5 floor) remain effectively dormant on English text. Their CONTEXT lists are German-only (Rechnungsadresse, Lieferadresse, Krankenkasse, Führerschein, …), so the LemmaContextAwareEnhancer's `+0.35` substring boost never matches English tokens. Pattern-only scores stay below the default 0.35 floor. Live-verified: `"Order 80331 units"` and `"Project M-AB 1234"` both return zero PII on `en`.

- **High-base structural DE_*** (`DE_VAT_ID`, `DE_TAX_ID`, `DE_MASTR_ID`, `DE_ID_CARD` strict, `DE_PASSPORT` strict, plus `DE_MELO` post-item-3) fire on shape alone. These are the entities that *should* surface on English correspondence mentioning German entities — that's the whole point of the dual-registration. Their patterns are structurally distinctive enough that incidental matches in English prose are rare.

The asymmetry is implicit in the score-arithmetic, not in the registration: every DE_* recognizer is dual-registered; the per-recognizer base score and CONTEXT-language pairing determines whether it actually fires on `en` text.

## Alternatives Considered

### Chosen — Dual-register every DE_* under `en` + `de`

Single YAML change, no recognizer code, score-arithmetic provides the safety claim. Symmetric across enabled and disabled entries (the 3 disabled ones get `- en` too, so re-enabling later doesn't require a second registration pass).

### Require explicit `language: de` per request

Rejected: pushes the language-detection burden to subsidiary users who don't know to set it; lingua-py auto-detect returns `en` for English correspondence (correctly); breaks the "user pastes text, gets sensible defaults" contract that motivates the whole tool.

### Drop language scoping entirely (every recognizer matches every language)

Rejected: breaks isolation between countries — UK, Italian, French, Korean recognizers would all fire on every request. Inflates FP surface dramatically. The `de`/`en` cross-registration is intentional and narrowly scoped; "drop scoping entirely" is a much larger blast radius.

### Asymmetric — only high-base DE_* under `en`, leave low-base ones `de`-only

Rejected: arbitrary cutoff threshold ("how high is high?"); creates two registration tiers operators must keep in sync; the score-arithmetic already handles the safety argument cleanly for low-base entities, so the asymmetry adds complexity without protection.

### Operator-side custom recognizer YAML

Rejected: every Memodo-shaped deployment would re-author the same registration overlay locally; loses the cross-instance reusability that justifies the fork.

## Consequences

### Positive

- Cross-border English-language traffic from subsidiaries now surfaces DE entities at default config. Memodo pilot phrases 01, 03, 10 (multi-PII English-wrapper paragraphs) anonymize correctly.
- Score-arithmetic safety argument means the change is invisible on English prose without German content (verified — 0 PII on `"Order 80331 units"`).
- **Sets a registration policy that binds future country additions.** When IT, CZ, or NL recognizers land, they follow the same dual-registration pattern (`supported_languages: [it, en]`, etc.). Future contributors don't need to re-derive the language-routing decision per country.

### Negative / Trade-offs accepted

- The `MedicalLicenseRecognizer` ↔ `DE_MASTR_ID` Luhn-DEA collision (originally documented in fork `322eccf` for `de` only) is now visible on `en` as well. Both fire on `EE9012345`-shaped substrings. Subset-matching tolerates it; one open follow-up in `docs/customizations.md` is to disable `MEDICAL_LICENSE` entirely (Memodo has no DEA use case).
- The 3 disabled DE_* entries also carry the `- en` registration. Re-enabling them later activates them on both languages simultaneously; future contributors enabling a disabled entry must verify the en-side score-arithmetic claim holds for that specific recognizer.
- REQ-011 recognizer-floor contract: additions are tolerated (the de baseline is unchanged; the en baseline gains new entries). Verified at 89/89 (81 eval + 8 floor contract) post-merge.

### Neutral observations

- This decision implicitly binds: the lemma-context machinery (CONTEXT lists must remain language-pure for the safety argument to hold); any future change to LemmaContextAwareEnhancer's substring-boost mechanism (currently `+0.35`) must re-verify the low-base safety claim.
- Code-switched text (German paragraph with embedded English names, or vice versa) behavior is unchanged from ADR 0001's note: lingua-py picks one language per request, the matching engine + recognizers run, the non-selected language's NLP entities may be missed. Users override via explicit `language` param.

## References

- `docs/customizations.md` — Item 2 (registration change, score-arithmetic safety argument, live-verified test phrases).
- `.presidio-pin` — `19d3c87` notes block (per-recognizer score breakdown, live-verification commands).
- Fork commit `19d3c87` — YAML diff (12 entries × `- en`).
- ADR 0001 — per-language NLP engine routing (the upstream architectural shape this decision composes with).
- `presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml` — registration source-of-truth.
- `docs/supported-entities.md` — DE section preamble documents the dual-registration policy and the score-arithmetic gating.
