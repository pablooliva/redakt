# Customizations

Redakt customizations to Presidio, in chronological order. This document captures fork-side recognizer additions, Redakt-side policy decisions, and eval-fixture promotions that compose the Memodo cross-border expansion. Source-of-truth for fork commit SHAs is [`.presidio-pin`](../.presidio-pin); source-of-truth for the public entity catalog is [`docs/supported-entities.md`](./supported-entities.md); this doc is the why and the chronology that tie them together.

Earlier fork customizations (DE_PLZ street-suffix context, the DE_MASTR_ID + MEDICAL_LICENSE en-scoping, the DateRecognizer `dd.mm.yyyy` 0.95 split, the transformers/huggingface\_hub major caps, etc.) pre-date the cross-border push and are out of scope for v1 of this doc. The SHA chain in [`.presidio-pin`](../.presidio-pin) is the authoritative record of that earlier work; it also marks where this changelog begins.[^scope]

[^scope]: The cross-border push is the first coherent body of customization work that justified a published changelog. Pre-cross-border commits were a series of single-recognizer fixes whose rationale is captured inline in the `.presidio-pin` notes block. If we ever want a fuller retrospective, those notes are the natural starting point.

## Index by entity

| Entity | Item | Fork SHA |
|---|---|---|
| `EU_VAT_ID` | [Item 1](#item-1) | [`587957a`](https://github.com/pablooliva/presidio/commit/587957a) |
| DE_* (registration change, no new entity) | [Item 2](#item-2) | [`19d3c87`](https://github.com/pablooliva/presidio/commit/19d3c87) |
| `DE_EEG_ANLAGE` | [Item 3](#item-3) | [`798b266`](https://github.com/pablooliva/presidio/commit/798b266) |
| `DE_MALO` | [Item 3](#item-3) | [`798b266`](https://github.com/pablooliva/presidio/commit/798b266) |
| `DE_MELO` | [Item 3](#item-3) | [`798b266`](https://github.com/pablooliva/presidio/commit/798b266) |
| `DE_ZAEHLERNUMMER` | [Item 3](#item-3) | [`798b266`](https://github.com/pablooliva/presidio/commit/798b266) |
| `DATE_TIME` (EN long-form patterns) | [Item 4](#item-4) | [`184d0e1`](https://github.com/pablooliva/presidio/commit/184d0e1) |
| `BIC_CODE` | [Item 5](#item-5) | [`a01a3b3`](https://github.com/pablooliva/presidio/commit/a01a3b3) |
| `SEPA_CREDITOR_ID` | [Item 5](#item-5) | [`a01a3b3`](https://github.com/pablooliva/presidio/commit/a01a3b3) |

Items 6 and 7 are Redakt-only eval-fixture promotions — they exercise the entities above without introducing new ones.

---

<a id="item-1"></a>
## Item 1 — EU_VAT_ID generic recognizer (2026-05-11, fork `587957a`)

**Redakt commit:** `efc47a0`

A single `EuVatIdRecognizer` covering all 27 EU country prefixes, registered for both `en` and `de` at base score `0.5`:

```
(AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|GB|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK)[A-Z0-9]{8,12}
```

Per-prefix body lengths follow the VIES spec; lookaround anchors prevent matches from extending into adjacent alphanumeric tokens.

**Why one recognizer instead of per-country.** Memodo's footprint is a German HQ with IT, CZ, and NL subsidiaries plus regular B2B traffic from AT, CH, and PL suppliers. A single multi-prefix recognizer covers the IT/NL/CZ subsidiaries and the AT/PL neighbors transitively. The IT/NL/CZ country-specific recognizers Presidio ships were intentionally disregarded — the generic prefix subsumes them.

**Overlap with `DeVatIdRecognizer` is intentional.** `DeVatIdRecognizer` is unchanged and remains the `de`-only authority on DE-prefixed IDs. On a DE-prefix VAT span, both recognizers fire as separate entities; subset-matching in the eval suite tolerates the duplication, and the anonymization template picks one winner per span.

---

<a id="item-2"></a>
## Item 2 — DE recognizers registered under `en` (2026-05-12, fork `19d3c87`)

**Redakt commits:** `9b20114` + `84cd48e`

YAML-only change: `- en` added to `supported_languages` on every DE_* entry in `default_recognizers.yaml` (12 entries total — 9 enabled, 3 disabled). No new code, no new entity, no score changes. This closed the gap where English-speaking IT/CZ/NL subsidiary staff produced zero DE-entity detections.

**Score arithmetic preserves the safety claim on English.** Low-base context-gated DE_* recognizers (`DE_PLZ` 0.05, `DE_KFZ` 0.2–0.3, `DE_HEALTH_INSURANCE` 0.3, `DE_FUEHRERSCHEIN` 0.35 with the Redakt-side 0.5 floor) remain effectively dormant on English text because their CONTEXT lists are German-only — the `+0.35` substring boost never matches English tokens. High-base structural DE_* (`DE_VAT_ID`, `DE_TAX_ID`, `DE_MASTR_ID`, `DE_ID_CARD` strict, `DE_PASSPORT` strict) fires on shape alone and now surfaces on English correspondence mentioning German entities, which is the desired behavior.

**Live-verified:** `"Order 80331 units"` and `"Project M-AB 1234"` both return zero PII on `en` — the lemma-context machinery does its job.

**Carried-forward side-effect.** `MedicalLicenseRecognizer` (en-scoped USA DEA pattern) re-collides with `DE_MASTR_ID` on `EE9012345`-shaped substrings — the same Luhn-DEA / MaStR collision originally documented in fork `322eccf`, now visible on `en` as well. Subset-matching tolerates it. See [Open follow-ups](#open-follow-ups) for the disable-MEDICAL_LICENSE option.

**Eval:** 89/89 (81 cross-language eval + 8 REQ-011 floor contract).

---

<a id="item-3"></a>
## Item 3 — PV-industry German identifiers (2026-05-12, fork `798b266`)

**Redakt commit:** `7c1b2b9`

Four new recognizers landed in a single fork commit, all registered for `de` + `en` in `default_recognizers.yaml` (same en-symmetry as item 2):

### `DeEegAnlageRecognizer` (`DE_EEG_ANLAGE`)

```
\b[A-Z0-9]{33}\b
```

Base score `0.4`. The 33-char structural width alone clears the `0.35` default floor; CONTEXT (Anlagenschlüssel / EEG / Photovoltaik / …) adds the `+0.35` boost on labelled lines. Authority: BDEW Beschluss BK6-13-200.

### `DeMaloRecognizer` (`DE_MALO`)

```
\b\d{11}\b
```

Base score from the pattern is low (`\d{11}` matches phone numbers and order IDs), so detection is gated on `validate_result` implementing the BDEW Mod-10 weighted-digit-sum checksum:

> weights `2, 1, 2, 1, …`; digit-sum if product ≥ 10; `check = (10 − sum mod 10) mod 10`

`validate_result == True` boosts the score to `1.0` per Presidio's PESEL/SSN/ABA convention. The checksum filters ~90% of random 11-digit strings without needing a per-entity floor. Authority: BDEW MaLo-ID Anwendungshilfe.

### `DeMeloRecognizer` (`DE_MELO`)

```
\bDE[A-Z0-9]{31}\b
```

Base score `0.6`. The fixed `DE` country prefix tightens the surface relative to `DE_EEG_ANLAGE`. **Intentional overlap:** DE-prefixed 33-char spans fire BOTH `DE_MELO` and `DE_EEG_ANLAGE`; subset-matching tolerates the duplication and the consumer template chooses one winner per span. Authority: VDE-AR-N 4400.

### `DeZaehlernummerRecognizer` (`DE_ZAEHLERNUMMER`)

```
\b(?=[A-Z0-9]{8,15}\b)[A-Z]*\d[A-Z0-9]*\b
```

Base score `0.05` + CONTEXT (Zähler / Stromzähler / Gerätenummer / …) `+0.35` = `0.40`, just clearing the `0.35` default floor. The `≥1-digit` lookahead is the cheap structural anchor that eliminates pure-letter German prose (`ausgetauscht`, `Lieferadresse`, `Postanschrift`, `abcdefgh`) which would otherwise context-boost into matches when a Zähler-context word sat in the surrounding window. Pinned in CI by a negative anchor:

> `"Lieferadresse: Solarweg 12, 80331 München. Kein PV-Zubehör vorrätig."` → expects exactly `[DE_PLZ]`.

Same low-base + context-gated model as `DePlzRecognizer`.

**Eval:** 88/88 (+7 over the 81 baseline — 4 positives, 1 dual-firing MELO+EEG, 1 false-positive negative anchor, 2 expect_clean bare-noun guards).

---

<a id="item-4"></a>
## Item 4 — English long-form `DATE_TIME` patterns (2026-05-12, fork `184d0e1`)

**Redakt commit:** `681b8b3`

Four new patterns added to `DateRecognizer`. The same recognizer is auto-instantiated for both `en` and `de` root languages, so `de` also picks them up:

| Pattern | Example | Score |
|---|---|---|
| `Month DD, YYYY` | `March 28, 2026` | `0.95` |
| `Mon DD, YYYY` | `Mar 28, 2026` / `Mar. 28, 2026` | `0.85` |
| `DD Month YYYY` | `28 March 2026` | `0.95` |
| `Q[1-4] YYYY` | `Q3 2026` | `0.85` |

**Casing.** `PatternRecognizer` compiles with `re.IGNORECASE` in its `global_regex_flags` (fork `pattern_recognizer.py:47`), so a single Pascal-case alternation covers any input casing — verified live against `march 28, 2026` and `q1 2026` on the running analyzer container.

**Score arithmetic.** Same shape as the `dd.mm.yyyy` split from fork `ee93662`: 4-digit-year, named-month forms at `0.95` clear Redakt's `DATE_TIME: 0.95` consumer floor (which exists to drop NLP overfire on `today` / `next weekend`). Abbreviated 3-letter months and `Q[1-4] YYYY` stay at `0.85`, intentionally **below** that floor end-to-end — they're the regex-layer equivalent of `dd.mm.yy at 0.4`: structurally available, currently filtered by the default floor, surfacing again only when a request-level `entity_score_thresholds` lowers it. Live-verified at `DATE_TIME: 0.8` on `Mar 28, 2026` and `Q3 2026`.

**Out of scope.** Relative time (`next Monday`, `tomorrow`) stays NLP territory — no regex addition.

**Guardrails.** Day-range `([1-9]|0[1-9]|[1-2][0-9]|3[0-1])` and `Q[1-4]` anchor the negative cases: `March 32, 2026` and `Q5 2026` do not match. Pinned in fork unit tests + Redakt eval.

**Eval:** 93/93 (+5 over the 88 baseline — 3 positives, plus 2 expect_clean negatives: bare `March 2026` no-day form + `Section 32, 2026` day-out-of-range guardrail). Fork-side `test_date_recognizer.py` extended with 11 new parametrize entries; all 34 prior entries continue to produce their original counts and spans.

---

<a id="item-5"></a>
## Item 5 — Banking adjuncts: BIC + SEPA Creditor ID (2026-05-12, fork `a01a3b3`)

**Redakt commit:** `bdfd046`

Two new generic recognizers, both registered `en` + `de`:

### `BicSwiftRecognizer` (`BIC_CODE`)

```
(?-i:(?<![A-Z0-9])[A-Z]{4}<ISO-3166-1-alpha-2>[A-Z0-9]{2}(?:[A-Z0-9]{3})?(?![A-Z0-9]))
```

ISO 9362. Exactly 8 or 11 chars; ISO 3166-1 alpha-2 country slot at positions 5–6 (~249 codes) narrows the false-positive surface against common uppercase 8-letter words (`INTERNAL`, `MITARBEI`, `FRANKFUR` — non-ISO at positions 5–6, suppressed). Base score `0.85`.

### `SepaCreditorIdRecognizer` (`SEPA_CREDITOR_ID`)

```
(?-i:(?<![A-Z0-9])<ISO-3166-1-alpha-2>[0-9]{2}[A-Z0-9]{3}[A-Z0-9]{1,28}(?![A-Z0-9]))
```

EPC scheme. Total 8–35 chars; same ISO country-code anchor at positions 1–2. Base score `0.85`.

### Inline `(?-i:...)` is load-bearing

**Critical implementation detail, carry it forward:** both patterns are wrapped in inline `(?-i:...)` scoped flag groups, **not** a constructor-level `global_regex_flags=` override. Presidio's `RecognizerRegistry.__instantiate_recognizer` forcibly overwrites

```python
inst.global_regex_flags = self.global_regex_flags
```

at YAML load (fork `recognizer_registry.py:308`), so any constructor-level flag drop is silently discarded. Inline scoping is the only way the `IGNORECASE` drop survives. Without it, every 8-letter lowercase word matches the bare `[A-Z]{6}[A-Z0-9]{2}` shape under `IGNORECASE` and the recognizer becomes unusable on prose. Verified live: `"die rechnung deutdeff steht aus"` → 0 entities; `"Rechnung Nr. 12345 ist bezahlt"` → 0.

### Residual FPs anchored as documented limits

Where positions 5–6 (BIC) or 1–2 (SEPA CI) happen to spell a real ISO code at all-caps, the recognizer fires. `RECHNUNG` (`NU` = Niue), `INSTITUT` (`IT` = Italy) at ALL-CAPS are documented limits-of-detection in fork unit tests. In B2B prose these tokens appear in title case and the `IGNORECASE` drop suppresses them.

### Intentional overlap with `IBAN_CODE`

SEPA CI matches IBAN-shaped spans `≥ 15` chars (both fire; IBAN's `validate_result` boosts checksum-valid IBANs to `1.0` so `IBAN_CODE` wins by score; consumer template chooses per span). The `8–14` char range is the unambiguous SEPA-only zone where IBAN never matches.

### Out of scope

SEPA *mandate* references are intentionally not regex-recognized — too loose without unacceptable FP rates. See [Open follow-ups](#open-follow-ups).

**Eval:** 102/102 (+9 over the 93 baseline — 5 DE banking-adjunct fixtures + 4 EN, including paired lowercase-suppression anchors that lock the inline flag drop in place: `"Rechnung Nr. 12345 ist bezahlt"` (de) and `"please wire via swift code chasus33 to the new account"` (en) — both expect_clean). Fork-side unit tests: 36 BIC cases (DE/IT/NL/CZ/US 8- and 11-char positives; negatives for invalid country, wrong length, lowercase, mixed case; two `test_residual_fp_documented` anchors) + 26 SEPA CI cases (DE/FR/NL/IT/CZ with min/max length boundaries; negatives for invalid country, non-digit check positions, too short/long, lowercase, embedded).

---

<a id="item-6"></a>
## Item 6 — Memodo pilot phrases promoted to canonical eval (2026-05-13, Redakt-only)

**Redakt commit:** `6d54fd9` · No fork work, no image rebuild.

Five multi-PII paragraphs promoted verbatim from `tools/memodo_pilot.py` into a new "Memodo pilot integration phrases" section of `tests/eval/fixtures/de.yaml`:

- Phrase 01 — installer onboarding
- Phrase 03 — RMA ticket
- Phrase 06 — site visit with MaStR
- Phrase 08 — customer complaint callback
- Phrase 10 — multi-address order

**`expect:` sets are live-API ground truth, not policy-aspiration.** They were probed against the running analyzer after items 1–5 landed, at the default `REDAKT_ENTITY_SCORE_THRESHOLDS`. Two divergences from the pilot's aspirational sets are flagged for future model swaps:

- **Phrase 06 omits `PERSON`.** xlm-roberta CoNLL-03 DE absorbs `Hubert Maier` into the `Bauernhof Hubert` `LOCATION` span. A model swap that detangles person-inside-org may restore the `PERSON` detection.
- **Phrase 08 omits `DATE_TIME`.** `heute zwischen 16 und 18 Uhr` is relative time + time-of-day; neither `DateRecognizer` regex nor the NLP label catches it. Resolving this would need either a new regex for time-of-day (high FP risk) or an NLP model that emits a TIME label.

The `DE_VAT_ID` + `EU_VAT_ID` + `SEPA_CREDITOR_ID` three-way overlap on DE-prefixed VAT IDs (phrases 01, 10) is locked in as a positive contract per items 1 and 5.

**Brand / product / SKU / serial negatives are pinned by 4 standalone `expect_clean: true` anchors.** Subset-matching means positives alone can't enforce "must NOT fire", so these standalone fixtures are the actual brand-pin contract:

- Fronius Symo + serial `F1234567` (phrase 03 pair)
- JA Solar `JAM72S20-450` + Huawei `SUN2000-15KTL-M2` (phrase 06 pair)
- Internal System-ID `PV-2024-09812` (phrase 08 pair)
- Trina Vertex S+ 440W + SMA Sunny Tripower `25000TL-30` (phrase 10 pair)

**Eval:** 111/111 (+9 over the 102 baseline — 5 positives + 4 negatives).

---

<a id="item-7"></a>
## Item 7 — Multi-line address-block fixtures (2026-05-13, Redakt-only)

**Redakt commit:** `6f57222` · No fork work, no image rebuild.

Five newline-separated address-block fixtures capturing how Memodo invoices and quotes actually carry addresses:

```
<Header:>
<Company>
<Street + Nr>
<PLZ> <City>
<Country>
```

**DE** (`tests/eval/fixtures/de.yaml`):
- Single billing block (`Rechnungsadresse`)
- Combined billing + shipping (two PLZs separated by a blank line)
- Address block + inline contact card (`DE_PLZ` + `PERSON` + `PHONE_NUMBER` + `EMAIL_ADDRESS`)

**EN cross-border** (`tests/eval/fixtures/generic.yaml`):
- IT → DE invoice header where the DE-side PLZ fires under `en` registration but the IT-side PLZ stays clean — exercising the item-2 safety claim across a real multi-line layout
- CZ subsidiary shipping address + structured contact card (`PERSON` + `PHONE_NUMBER` + `EMAIL_ADDRESS`; no `DE_PLZ` — Czech postal codes have no German CONTEXT in the block)

**Key empirical finding pinned in the fixtures:** `DE_PLZ`'s `Rechnungsadresse` / `Lieferadresse` CONTEXT boost survives 3–4 intervening newlines and ~40–50 chars to reach the PLZ on the address line, both for single-block layouts and for two-block layouts separated by a blank line. This is the contract that lets address-block invoices anonymize correctly.

**LOCATION-divergence note in `notes:`.** Once contact lines follow the address block, München stops surfacing as `LOCATION` end-to-end. The note is captured per fixture so a future model swap that restores `LOCATION` saturation can extend `expect:` without surprise.

**Eval:** 116/116 (+5 over the 111 baseline).

---

## Cumulative impact

Counting from the 65-fixture pre-item-1 baseline:

| After | Fixtures | Δ | New entities |
|---|---|---|---|
| Item 1 | 81 | +16 | `EU_VAT_ID` |
| Item 2 | 81 | 0 | (registration symmetry) |
| Item 3 | 88 | +7 | `DE_EEG_ANLAGE`, `DE_MALO`, `DE_MELO`, `DE_ZAEHLERNUMMER` |
| Item 4 | 93 | +5 | (DATE_TIME patterns, no new entity) |
| Item 5 | 102 | +9 | `BIC_CODE`, `SEPA_CREDITOR_ID` |
| Item 6 | 111 | +9 | — |
| Item 7 | 116 | +5 | — |

Seven new entity types, en/de coverage symmetric for all banking and PV identifiers, Memodo pilot F1 projected past 95% (was 93.88%).

---

<a id="open-follow-ups"></a>
## Open follow-ups

Carried forward from working notes; intentionally unstarted.

1. **Consider disabling `MEDICAL_LICENSE` entirely.** The en-scoped `MedicalLicenseRecognizer` (USA DEA pattern) collides with `DE_MASTR_ID` on `EE`-prefixed spans because both rely on Luhn-like digit shapes — originally surfaced in fork `322eccf`, now visible on `en` text after item 2's registration change. Memodo has no DEA use case, so the entity could be removed from `default_recognizers.yaml` rather than tolerated via subset-matching. Cost is one YAML toggle; benefit is one fewer overlap to explain to new operators.

2. **SEPA *mandate* references intentionally not regex-recognized.** Mandate refs have no fixed structural shape — they range from short opaque tokens to free-form vendor strings — so any tight regex misses too many real cases and any loose regex matches too much prose. Pinned here as a deliberate non-decision so a future contributor doesn't re-litigate it without new evidence. If a structural anchor emerges (e.g., a vendor-specific prefix convention worth modeling), revisit.
