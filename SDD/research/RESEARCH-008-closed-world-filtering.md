# RESEARCH-008-closed-world-filtering

_Date: 2026-05-13 | Feature: Closed-world filtering for quasi-identifiers_

---

## Pre-Research Clarification

No CLARIFICATION-008 artifact — gate explicitly skipped via `--skip-clarify`. The task description above already externalizes the design concept with full acceptance examples, out-of-scope items, and explicit trade-offs to address. ADR-0007 (`SDD/adr/0007-closed-world-filtering-quasi-identifiers.md`) captures the architectural decision; this research document maps the existing codebase to that decision.

---

## System Data Flow

### Key entry points

- **`/api/detect`** — `src/redakt/routers/detect.py:134` (`@router.post("/detect")`) dispatches to `run_detection()` at line 54.
- **`/api/anonymize`** — `src/redakt/routers/anonymize.py:127` (`@router.post("/anonymize")`) dispatches to `run_anonymization()` at line 48.
- **Web UI detect/anonymize paths** — `src/redakt/routers/pages.py:53` calls `run_detection()` and `src/redakt/routers/pages.py:123` calls `run_anonymization()` — same shared functions, so the post-filter placed inside those functions covers these four call sites.
- **`/api/documents/upload` (FIFTH CALL SITE — CURRENTLY BYPASSES ALL POST-FILTERS)** — `src/redakt/routers/documents.py:62` (`POST /api/documents/upload`) and `src/redakt/routers/pages.py:180` (`POST /documents/submit`) dispatch to `process_document()` at `src/redakt/services/document_processor.py:182`. This path calls `presidio.analyze()` per chunk and `resolve_overlaps()` at lines 255–262 but does **not** call `filter_by_entity_thresholds()` and will not call `filter_by_closed_world()` under the current design. This is a **pre-existing inconsistency**: `entity_score_thresholds` already does not apply to document uploads today. The closed-world filter must explicitly address this path.

**Document-upload filter decision (open question for spec):** Three options:

- **(a) Extend into `process_document()`** — add both `filter_by_entity_thresholds()` and `filter_by_closed_world()` calls into the chunk-analysis path. Must specify: is the anchor-presence check per-chunk (anchor in chunk 1 does NOT protect quasi-identifiers in chunk 3) or document-global (collect all anchors across all chunks first, then suppress)? Document-global requires a two-pass design. Per-chunk matches the current architecture but contradicts the closed-world assumption for multi-chunk documents.
- **(b) Explicitly out-of-scope the document path** — document `closed_world_filtering` does not apply to `/api/documents/upload`. Add an operator-facing note. The behavior gap (text detect vs document upload) must be documented.
- **(c) Unify all post-filter logic into a shared `apply_post_filters(results, settings, overrides)` helper** — used by all three pipelines. Cleanest architecture but largest change.

**Recommendation for spec:** Option (b) for v1 with an explicit out-of-scope rationale and operator note; Option (c) as a follow-on ticket. The per-chunk anchor check problem (option a) is real enough to defer until the spec can resolve the document-global semantics properly. The research notes that the per-chunk scenario ("A PERSON in chunk 1 does not suppress quasi-identifiers in chunk 3") is explicitly called out as a closed-world assumption failure in §Security & Threat-Model Considerations — a document upload that spans multiple chunks is itself an unsafe context for this filter.

### Data transformation pipeline (detect path)

```
text + params
  → language resolution (auto-detect or manual)  [detect.py:72-81]
  → merge allow lists                             [detect.py:94, utils.py:59-80]
  → presidio.analyze() call                       [detect.py:97-114]
  → merge_entity_thresholds()                     [detect.py:116-117, utils.py:83-94]
  → filter_by_entity_thresholds()   ←— LAYER A   [detect.py:119, utils.py:97-108]
  → build DetectionResult                         [detect.py:121-131]
  → build response                                [detect.py:165-188]
```

**The closed-world post-filter inserts at LAYER A** — immediately after `filter_by_entity_thresholds()` returns at `detect.py:119` and at the parallel location `anonymize.py:116`. Both paths are identical structurally.

### Integration point (exact locations)

| File | Line | Current call | New filter inserts after | v1 in-scope? |
|------|------|--------------|--------------------------|--------------|
| `src/redakt/routers/detect.py` | 119 | `results = filter_by_entity_thresholds(results, merged_thresholds)` | add `results = filter_by_closed_world(results, ...)` at line 120 | YES |
| `src/redakt/routers/anonymize.py` | 116 | `results = filter_by_entity_thresholds(results, merged_thresholds)` | add `results = filter_by_closed_world(results, ...)` at line 117 | YES |
| `src/redakt/services/document_processor.py` | 262 | `resolved = resolve_overlaps(results)` (per-chunk) | Would insert after `resolve_overlaps()` — but per-chunk anchor semantics are ambiguous and `filter_by_entity_thresholds` also doesn't apply here today | **NO (v1 out-of-scope — see §Open Questions Q1)** |

The new function `filter_by_closed_world()` lives in `src/redakt/utils.py`, co-located with `filter_by_entity_thresholds`. The document-upload pipeline (`document_processor.py`) is explicitly out-of-scope for v1. This is a pre-existing inconsistency: `entity_score_thresholds` also does not apply to document uploads today.

### External dependencies

- Presidio Analyzer service (HTTP, port 5002) — unchanged. The closed-world filter operates entirely on Presidio's already-assembled span list.

---

## Stakeholder Mental Models

- **Operator (Pablo / Memodo)**: noise reduction for paste-into-AI workflows. "What is the weather in Munich on May 13, 2026?" should produce zero PII flags when no person-naming anchor is present. The flag is off by default so opt-in is explicit.
- **Engineering**: configurable entity class lists in `config.yaml`, off-by-default `closed_world_filtering` flag, per-request override mirroring `entity_score_thresholds`. New filter is a pure function in `utils.py` with no external dependencies.
- **End user (PV operator)**: fewer spurious redactions on weather queries, geographic questions, and generic date mentions in daily Copilot/ChatGPT paste workflows.
- **Future agent integration**: per-request override (`closed_world_filtering: false` sent in request body) lets an agent integration re-tighten the rule when the agent's context is not closed-world (e.g., the agent already has external knowledge about the person).

---

## Production Edge Cases

### Real false-positives observed today

- `"What is the weather in Munich, Germany on May 13, 2026?"` — flags `LOCATION` (Munich) and `DATE_TIME` (May 13, 2026) even though no person anchor exists. Closed-world flag enabled suppresses both.
- Generic date-only phrases: `"Versand voraussichtlich am 15.05.2026."` — has `DATE_TIME` but no anchor. Under closed-world, suppressed.
- DE_PLZ in address-lookup context: `"Bauvorhaben in 73230 Kirchheim/Teck"` — has `DE_PLZ` but no anchor. Under closed-world, suppressed.

### Structural edge cases (behavior contracts)

These edge cases are stated here as canonical behavior assertions (not only as test rows), so that spec REQ-form can reference them directly.

- **Empty span list:** `filter_by_closed_world([], enabled=True, ...)` returns `[]`. No crash.
- **All spans are strong anchors, no quasi-identifiers:** All retained. Anchor presence check passes; no quasi-identifier spans exist to suppress.
- **All spans are quasi-identifiers, no strong anchor:** All suppressed (when flag=True). Result is `[]`.
- **Single strong anchor + single quasi-identifier minimal pair:** Both retained. Anchor presence check passes; quasi-identifier passes through.
- **Only always-emit entities (e.g., `DE_BSNR`, `DE_HANDELSREGISTER`):** Always retained regardless of flag state. These are in neither `strong_anchors` nor `quasi_identifiers` — the filter does not touch them. No anchor check fires for these spans; they pass through.
- **Mixed strong anchors, quasi-identifiers, and always-emit entities:** All retained. Anchor check passes (strong anchor present); quasi-identifiers retained; always-emit entities unaffected.

### Gameable narratives (anchor-free but still joinable)

- `"Treatment confirmed for May 13, 2026 at the Munich clinic."` — no PERSON anchor → quasi-identifiers pass under closed-world. The description carries implicit joinability risk that the filter cannot detect. Explicitly documented in ADR-0007 as an accepted edge case for B2B PV workflows.
- Any narrative that uses role-based reference (`"the patient"`, `"der Kunde"`) instead of a name — no PERSON anchor fires → quasi-identifiers pass through. Healthcare workflows should not enable `closed_world_filtering`.

### Allow-list interaction edge case

If a strong-anchor span (e.g., `PERSON`) has its matching text on the allow list, Presidio will return it but the allow-list filter runs inside Presidio's `/analyze` call (passed as `allow_list` param). This means: if `"Stefan Berger"` is in the allow list, the PERSON span is suppressed by Presidio before reaching Redakt. The result list arriving at the closed-world filter has no PERSON strong anchor → quasi-identifiers would be dropped even though the human-readable text still contains a name. This is a **design edge case to address in the spec**: should the closed-world filter run on pre-allow-list results? Recommendation: no — the allow list reflects an explicit operator decision that a term is not PII; honoring the allow list before closed-world is correct behavior (an allow-listed name is not a PII anchor by operator policy).

**Behavior contract:** allow-list stripping of a strong-anchor span causes the closed-world filter to behave as if no anchor were present. Quasi-identifiers in the same submission are suppressed. This is correct behavior: the operator has declared the name non-PII; the filter respects that policy decision.

---

## Files That Matter

### Core logic

| File | Purpose | Key lines |
|------|---------|-----------|
| `src/redakt/routers/detect.py` | `/api/detect` endpoint; `run_detection()` | 54–131 (run_detection), 119 (filter insertion point) |
| `src/redakt/routers/anonymize.py` | `/api/anonymize` endpoint; `run_anonymization()` | 48–124 (run_anonymization), 116 (filter insertion point) |
| `src/redakt/routers/pages.py` | Web UI routes — reuses `run_detection` / `run_anonymization`; also `/documents/submit` (fifth call site, bypasses filter) | 53, 123 (detect/anonymize call sites), 180 (document submit — filter does NOT apply in v1) |
| `src/redakt/routers/documents.py` | `/api/documents/upload` (fifth call site — dispatches to `process_document()`, bypasses filter in v1) | 62 |
| `src/redakt/services/document_processor.py` | Document processing pipeline — calls `presidio.analyze()` per chunk, `resolve_overlaps()`; no `filter_by_entity_thresholds` or `filter_by_closed_world` in v1 | 182 (process_document), 253–262 (analyze_chunk — filter insertion point if v1 is extended) |
| `src/redakt/utils.py` | `filter_by_entity_thresholds` (precedent), `merge_entity_thresholds` | 83–108 |
| `src/redakt/config.py` | `Settings` class; YAML loading; `entity_score_thresholds` precedent | 52–111 |
| `src/redakt/models/detect.py` | `DetectRequest` — `entity_score_thresholds: dict[str, float] | None` field (per-request override pattern) | 10 |
| `src/redakt/models/anonymize.py` | `AnonymizeRequest` — same field | 10 |

### Tests

| Path | Pattern |
|------|---------|
| `tests/eval/fixtures/de.yaml` | YAML fixtures: `text`, `language`, `expect`, `notes`; some entries have `expect_clean: true` |
| `tests/eval/fixtures/generic.yaml` | Same format; covers cross-language entity types |
| `tests/eval/fixtures/benign.yaml` | All entries use `expect_clean: true` — pure negative/over-detection guards |
| `tests/eval/test_calibration.py` | Eval runner; issubset assertion and expect_clean branch |

### Configuration

| File | Purpose |
|------|---------|
| `config.yaml` | Runtime config (operator-tunable); currently has `entity_score_thresholds`, `allow_list` blocks |
| `src/redakt/config.py` | Pydantic `Settings`; YAML source reads `config.yaml` via `_YamlConfigSource` |

### Docs

| File | What to update |
|------|---------------|
| `docs/v1-feature-spec.md` | Add Feature 008 section |
| `docs/customizations.md` | Add closed-world filtering operator guidance with threat-model warning |
| `docs/supported-entities.md` | Classify entities into strong-anchor vs quasi-identifier table |

---

## Security & Threat-Model Considerations

### When the closed-world assumption holds

The Presidio Analyzer receives the full text of a single user submission. If the downstream consumer (LLM, copilot, human reviewer) also only sees the anonymized output and has no external data about the submitter, quasi-identifiers without anchors are not joinable and the closed-world assumption holds.

### When it fails (explicitly out-of-scope for this feature)

- **Agent workflows**: an agent that has already retrieved user profile data, CRM records, or email history before calling Redakt is not in a closed world. The agent's additional context can join `Munich + May 13` to a specific person. Operators enabling `closed_world_filtering` in agent-integrated deployments break the assumption silently.
- **Batch/async processing**: if Redakt is called per-chunk of a larger document and the chunks are later reassembled, the anchor-presence check is per-chunk only. A PERSON in chunk 1 does not suppress quasi-identifiers in chunk 3.
- **External knowledge in the LLM itself**: a foundation model trained on data containing the person's public records can join quasi-identifiers without any explicit anchor. The closed-world assumption ignores parametric knowledge in downstream models.

### HIPAA Safe Harbor incompatibility

HIPAA Safe Harbor requires unconditional removal of the 18 PHI categories (including all dates except year). Closed-world filtering explicitly does not meet this standard: it leaves dates and locations unredacted when no anchor is present. Redakt is GDPR-scoped, not Safe Harbor-scoped. This must be prominently noted in the config comment and operator docs.

### AuthZ / AuthN

Closed-world filtering is a post-filter policy layer with no authentication or authorization surface of its own. Access control is inherited from Redakt's existing endpoint security (FastAPI request handling, same `/api/detect` and `/api/anonymize` routes). No new authZ rules are required; the per-request override flag is treated as a trusted parameter exactly like `entity_score_thresholds` — it is caller-supplied and requires no elevated privilege.

### Gameability

Any narrative that omits a PERSON/EMAIL/PHONE/IBAN anchor but still contains joinable quasi-identifiers passes through under closed-world. This is accepted per ADR-0007 for the B2B PV use case. Healthcare, social-services, or any context where anchor-stripped quasi-identifier combinations carry re-identification risk should not enable the flag.

### GDPR Art. 9 perspective on NRP classification

`NRP` (Nationality, Religious belief, Political opinion) is GDPR Art. 9 special-category data. The closed-world rationale for classifying NRP as a quasi-identifier is: in isolation, NRP data does not identify a natural person; it is joinable with an anchor (a named person) to become a re-identification risk. GDPR Art. 9 does not require unconditional removal of special-category data — it requires lawful basis for *processing* it, which is an upstream concern at the API caller level. The closed-world filter operates on already-detected spans; it does not process the underlying text beyond what Presidio has already analyzed.

However, enabling `closed_world_filtering` with `NRP` in `quasi_identifiers` means that a religious mention or nationality indicator is suppressed only when no PERSON anchor is present. An operator who misjudges the closed-world assumption (e.g., their workflow is not actually closed-world) would miss an Art. 9 category mention. The spec review-panel security specialist should explicitly confirm the NRP default classification. The maximally conservative alternative is to move NRP to always-emit (it is never suppressed by the closed-world filter regardless of anchor presence). Redakt's GDPR scope is minimization of re-identification risk, not categorical prohibition — but the spec should make this tradeoff explicit.

### DE_PLZ classification rationale

`DE_PLZ` (German postal code) resolves to ~10,000–40,000 people per code area. In isolation it is not person-identifying, but in combination with `PERSON + DATE_TIME` it materially narrows the population. The default set classifies it as a quasi-identifier (matches joinability semantics). Operators who want unconditional PLZ redaction move it out of `quasi_identifiers` into neither list (it becomes an always-emit entity not subject to closed-world suppression).

---

## Existing ADR

ADR-0007 (`SDD/adr/0007-closed-world-filtering-quasi-identifiers.md`, status: Proposed) is authoritative for all architectural decisions in this feature. Key positions confirmed as authoritative:

1. Off-by-default, opt-in flag (`closed_world_filtering: false`).
2. Two configurable entity class lists: `strong_anchors` and `quasi_identifiers`.
3. Per-request override knob mirroring `entity_score_thresholds` (boolean flag only; entity-class lists are instance-only in v1 — see §Open Questions Q2).
4. Filter placement: same layer as allow-list filter (post-Presidio response, before response builder).
5. Applies to `/api/detect` and `/api/anonymize`. **Does NOT apply to `/api/documents/upload` in v1** (explicitly out-of-scope — see §Open Questions Q1).
6. Threat-model assumption documented in config comment.
7. DE_PLZ as quasi-identifier (joinability criterion, not size criterion).
8. HIPAA Safe Harbor incompatibility explicitly noted.
9. **Web UI uses instance default only** — per-request override is API-only (see §Open Questions Q5).
10. **Complete entity classification enumerated in this research** — ADR-0007's "plus any other identifier-grade types in the current ruleset" is now fully resolved; see §Configuration Schema Design complete entity table.

**ADR-0007 amended in-place (2026-05-13):** `DE_STEUER_ID` → `DE_TAX_ID`. The canonical Presidio/Redakt recognizer name is `DE_TAX_ID` (emitted by `presidio_analyzer/predefined_recognizers/country_specific/germany/de_tax_id_recognizer.py`, confirmed in `tests/eval/fixtures/de.yaml:5`, `docs/supported-entities.md:71`). ADR-0007 previously used the informal German name `DE_STEUER_ID`. A naming note and the corrected identifier have been applied directly to ADR-0007 §Context and §Decision item 1. The previous "No revisions needed to ADR-0007" claim in this research was incorrect and is hereby retracted.

This research confirms the layer placement (`detect.py:119`, `anonymize.py:116`) and per-request override pattern (`entity_score_thresholds` field in both request models at line 10 of each model file) as documented in ADR-0007.

---

## Configuration Schema Design

### Complete Entity Classification Table

All entity types from the active recognizer catalog are classified below. Every DE_* type is enumerated from `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/country_specific/germany/` (18 files, 18 entity types). Classification rationale is given for each. Types marked **debated** are flagged for spec review-panel decision.

#### Generic / cross-language entities

| Entity Type | Classification | Rationale |
|-------------|---------------|-----------|
| `PERSON` | **strong anchor** | Direct natural-person identifier. The primary joining anchor. |
| `EMAIL_ADDRESS` | **strong anchor** | Directly identifies a natural person or their mailbox. |
| `PHONE_NUMBER` | **strong anchor** | Directly identifies a subscriber (natural person or org). |
| `IBAN_CODE` | **strong anchor** | Directly tied to a bank account holder. |
| `DATE_TIME` | **quasi-identifier** | Joinable only with an anchor (birth date + name = high re-ID risk; date alone is not identifying). |
| `LOCATION` | **quasi-identifier** | Joinable with anchor (city + person = re-ID). In isolation: non-identifying. |
| `NRP` | **quasi-identifier** (debated — see GDPR Art. 9 note below) | Nationality/religion/politics in isolation does not identify a person, but raises Art. 9 special-category concerns. Default: quasi-identifier. Spec should confirm; always-emit is a defensible alternative. |
| `MEDICAL_LICENSE` | **strong anchor** (reserved — see note below) | US DEA license number identifies a practitioner. Included anticipating its possible future disablement (see §MEDICAL_LICENSE note). Currently fires on US DEA patterns and on `DE_MASTR_ID` substrings as a known false-positive. |
| `EU_VAT_ID` | **strong anchor** | VAT ID identifies a registered business entity; in sole-trader context identifies a natural person. |
| `BIC_CODE` | **strong anchor** | Identifies a financial institution; in personal-banking context associated with a specific account holder when combined with IBAN. Included in strong anchors as a conservative default. |
| `IP_ADDRESS` | **always-emit (neither)** | Not in the active German-workflow fixture set; Presidio does recognize it. Spec can classify; neither list means it's always emitted (not suppressed by closed-world). |
| `CRYPTO` | **always-emit (neither)** | Crypto wallet address — not common in PV/energy-sector workflow. Always-emit pending spec decision. |
| `US_SSN`, `US_BANK_NUMBER`, etc. | **always-emit (neither)** | US-scoped identifiers. Not in Redakt's active DE/EU entity set. Excluded from both lists; always-emit. |

#### DE-specific entities (all 18 from Germany recognizer directory)

| Entity Type | Classification | Rationale |
|-------------|---------------|-----------|
| `DE_TAX_ID` | **strong anchor** | German personal tax ID (`Steuer-IdNr.`) — directly identifies a natural person. |
| `DE_VAT_ID` | **strong anchor** | German business VAT ID (`Umsatzsteuer-IdNr.`) — identifies a registered entity; in sole-trader context a natural person. |
| `DE_ID_CARD` | **strong anchor** | German national identity card number — unambiguously identifies a natural person. |
| `DE_PASSPORT` | **strong anchor** | German passport number — unambiguously identifies a natural person. |
| `DE_SOCIAL_SECURITY` | **strong anchor** | Rentenversicherungsnummer (RVNR) — directly identifies a natural person. **Omitted from prior research draft; corrected here.** |
| `DE_FUEHRERSCHEIN` | **strong anchor** | German driver's license number — directly identifies a natural person (license holder). **Omitted from prior research draft; corrected here.** |
| `DE_LANR` | **strong anchor** | Lebenslange Arztnummer — lifetime doctor number; directly identifies a medical professional (natural person). **Omitted from prior research draft; corrected here.** |
| `DE_TAX_NUMBER` | **strong anchor** | Steuernummer (`10/123/12345` format) — identifies a business or natural person as a tax subject. Can be assigned to legal entities (not always a natural person), but defaulting to strong anchor is conservative and correct. **Omitted from prior research draft; corrected here.** |
| `DE_HEALTH_INSURANCE` | **strong anchor** | German health insurance number (Krankenversicherungsnummer) — directly identifies an insured natural person. |
| `DE_MASTR_ID` | **strong anchor** | Market master data registry ID for energy assets. Identifies a registered energy installation, which is associated with an owner (natural person or legal entity). Included as strong anchor because in the PV (solar) sector `DE_MASTR_ID` is the primary identifier for a customer's installation. |
| `DE_KFZ` | **strong anchor** (debated) | German vehicle registration plate (`Kfz-Kennzeichen`). Identifies a vehicle, not directly a natural person; however, a registration plate is trivially traceable to an owner via traffic records. Conservative default: strong anchor. Spec review-panel should confirm. |
| `DE_PLZ` | **quasi-identifier** | German postal code. Resolves to ~10K–40K people per code area. Not person-identifying alone; joinable with PERSON + DATE_TIME. See §DE_PLZ classification rationale. |
| `DE_BSNR` | **always-emit (neither)** | Betriebsstättennummer — practice/clinic identifier assigned to a medical practice, not a natural person. An institution ID. Emitted always (not a personal identifier). Spec can move to strong-anchor if workflow requires. |
| `DE_HANDELSREGISTER` | **always-emit (neither)** | Handelsregisternummer — company registry number. Identifies a legal entity, not a natural person. Always-emit. |
| `DE_MALO` | **always-emit (neither)** | Marktlokation — energy market location identifier for electricity metering points. Identifies a metering point, not a natural person. In PV context may indirectly reference an installation (related to `DE_MASTR_ID`), but is itself an asset identifier. |
| `DE_MELO` | **always-emit (neither)** | Messlokation — energy metering location identifier. Same rationale as `DE_MALO`. Asset identifier, not a natural-person identifier. |
| `DE_EEG_ANLAGE` | **always-emit (neither)** | EEG Anlagen-ID — energy plant identifier under the Renewable Energy Sources Act. Identifies an energy installation (asset). |
| `DE_ZAEHLERNUMMER` | **always-emit (neither)** | Electricity/gas meter number. Identifies a meter device (asset), not a natural person. |

**GDPR Art. 9 note on `NRP`:** Nationality, religion, and political opinion are Art. 9 special-category data. The closed-world rationale (suppress only when no anchor present) technically holds — GDPR Art. 9 protections apply to processing of these categories, not specifically to whether they are quasi-identifier joinable. However, an operator who enables `closed_world_filtering` and has `NRP` in the quasi-identifier list will suppress religion/political-opinion mentions when no named person is present. This is defensible (the closed-world assumption holds: no anchor = not joinable) but may surprise a compliance officer. The spec review-panel should confirm the `NRP` default classification; moving `NRP` to always-emit is the maximally conservative alternative.

**`MEDICAL_LICENSE` note:** `MedicalLicenseRecognizer` is US-DEA-scoped. It fires on US DEA license-number patterns and on `DE_MASTR_ID` substrings (known false-positive). A fixture note at `tests/eval/fixtures/generic.yaml:130` flags possible disablement for Memodo's PV workflow (no DEA use case). `MEDICAL_LICENSE` is **included in `strong_anchors`** as a conservative default: if it fires (on a US pattern), it should act as an anchor. If the recognizer is later disabled entirely, removing it from `strong_anchors` is a no-op (it never fires). The spec should note this disposition explicitly.

#### `SEPA_CREDITOR_ID`

| Entity Type | Classification | Rationale |
|-------------|---------------|-----------|
| `SEPA_CREDITOR_ID` | **strong anchor** | SEPA creditor identifier. Assigned to a business or natural person; in sole-trader or individual creditor context identifies a natural person. Conservative default: strong anchor. |

### New Settings fields

```python
# src/redakt/config.py additions to class Settings:

closed_world_filtering: bool = False

strong_anchors: list[str] = [
    # Generic person/contact identifiers
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IBAN_CODE",
    "EU_VAT_ID",
    "BIC_CODE",
    "SEPA_CREDITOR_ID",
    "MEDICAL_LICENSE",       # US DEA-scoped; retained as conservative default (see MEDICAL_LICENSE note)
    # German-specific personal identifiers
    "DE_TAX_ID",             # Steuer-IdNr. — direct natural-person identifier
    "DE_VAT_ID",             # Umsatzsteuer-IdNr.
    "DE_ID_CARD",
    "DE_PASSPORT",
    "DE_SOCIAL_SECURITY",    # Rentenversicherungsnummer
    "DE_FUEHRERSCHEIN",      # Driver's license
    "DE_LANR",               # Lifetime doctor number
    "DE_TAX_NUMBER",         # Steuernummer (business or person)
    "DE_HEALTH_INSURANCE",   # Krankenversicherungsnummer
    "DE_MASTR_ID",           # Energy installation registry ID (PV sector)
    "DE_KFZ",                # Vehicle registration (debated — see table; spec to confirm)
]

quasi_identifiers: list[str] = [
    "DATE_TIME",
    "LOCATION",
    "NRP",     # Art. 9 debated — spec to confirm; always-emit is alternative
    "DE_PLZ",
]

# always-emit (neither list): DE_BSNR, DE_HANDELSREGISTER, DE_MALO, DE_MELO,
# DE_EEG_ANLAGE, DE_ZAEHLERNUMMER — asset/institution identifiers, not natural-person IDs.
# These are NOT added to either list; they are always emitted by Presidio and never
# suppressed by the closed-world filter regardless of anchor presence.
```

### Per-request override

Add `closed_world_filtering: bool | None = None` to `DetectRequest` and `AnonymizeRequest` (models at `src/redakt/models/detect.py` and `src/redakt/models/anonymize.py`). `None` means "use instance default from settings". `True`/`False` override the instance flag for that request.

This exactly mirrors `entity_score_thresholds`: the instance value is in `Settings`, per-request value in the request model is `| None`, merge logic in the router (`run_detection` / `run_anonymization`) resolves the effective value.

### Per-request override scope — explicit open question for spec

**`closed_world_filtering` (the boolean flag):** per-request overridable, with REPLACE semantics (non-None value wins).

**`strong_anchors` and `quasi_identifiers` (the entity-class lists):** Per-request overridability of these lists is **NOT specified for v1**. This is an explicit open question for the spec phase.

Two options for the spec to choose between:
- **(a) v1: boolean flag only is per-request overridable.** `strong_anchors` and `quasi_identifiers` are instance-only (config.yaml). A per-request caller cannot change which entity types are strong anchors. Simpler API surface; fewer edge cases.
- **(b) All three are per-request overridable with REPLACE semantics.** Caller provides a complete `strong_anchors` list; the request-level list replaces the instance list entirely for that request. More powerful but introduces merge-ambiguity and increases attack surface (a caller can remove PERSON from strong anchors for one request).

**Recommended posture for spec:** Option (a) for v1. Justify: `strong_anchors` and `quasi_identifiers` are policy-level configurations; per-request mutation of policy lists is an anti-pattern analogous to per-request allow-list mutation (which also only supports append, not replace). Future versions may add MERGE-BY-DIFF semantics (`strong_anchors_add` / `strong_anchors_remove`) with documented security review.

### Merge semantics

```python
effective_cwf = (
    body.closed_world_filtering
    if body.closed_world_filtering is not None
    else settings.closed_world_filtering
)
```

Simple boolean override (no merge needed — it's a flag, not a map). Entity-class lists use instance values only (per spec option a above).

### config.yaml additions

```yaml
# --- Closed-world filtering ---
# THREAT MODEL: This filter only holds when the submission is the FULL
# context the downstream consumer sees. Agent workflows that combine the
# snippet with external knowledge (CRM, email history, model parametric
# knowledge) break the assumption. HIPAA Safe Harbor requires unconditional
# date removal — do not enable this flag in Safe Harbor contexts.
# NOTE: Does NOT apply to /api/documents/upload (document pipeline) in v1 —
# see RESEARCH-008 §System Data Flow (fifth call site) for rationale.
closed_world_filtering: false

strong_anchors:
  # Generic person/contact identifiers
  - PERSON
  - EMAIL_ADDRESS
  - PHONE_NUMBER
  - IBAN_CODE
  - EU_VAT_ID
  - BIC_CODE
  - SEPA_CREDITOR_ID
  - MEDICAL_LICENSE       # US DEA-scoped; retained as conservative default
  # German-specific personal identifiers
  - DE_TAX_ID             # Steuer-IdNr.
  - DE_VAT_ID             # Umsatzsteuer-IdNr.
  - DE_ID_CARD
  - DE_PASSPORT
  - DE_SOCIAL_SECURITY    # Rentenversicherungsnummer
  - DE_FUEHRERSCHEIN      # Driver's license
  - DE_LANR               # Lifetime doctor number
  - DE_TAX_NUMBER         # Steuernummer
  - DE_HEALTH_INSURANCE   # Krankenversicherungsnummer
  - DE_MASTR_ID           # Energy installation registry ID
  - DE_KFZ                # Vehicle registration (debated — spec to confirm)

quasi_identifiers:
  - DATE_TIME
  - LOCATION
  - NRP     # Art. 9 special-category (debated — spec to confirm; always-emit is alternative)
  - DE_PLZ

# always-emit (neither list — not listed above): DE_BSNR, DE_HANDELSREGISTER,
# DE_MALO, DE_MELO, DE_EEG_ANLAGE, DE_ZAEHLERNUMMER
```

---

## Testing Strategy

### Unit tests (in `tests/` — fast, mocked Presidio)

| Test scenario | Assertion |
|--------------|-----------|
| `closed_world_filtering=True`, spans = [DATE_TIME, LOCATION], no anchors | result = [] |
| `closed_world_filtering=True`, spans = [PERSON, DATE_TIME, LOCATION] | result = [PERSON, DATE_TIME, LOCATION] (all retained) |
| `closed_world_filtering=True`, spans = [EMAIL_ADDRESS, DATE_TIME] | result = [EMAIL_ADDRESS, DATE_TIME] (email is anchor) |
| `closed_world_filtering=False` (default), spans = [DATE_TIME], no anchors | result = [DATE_TIME] (flag off, no suppression) |
| Per-request override: instance=True, request override=False | quasi-identifiers pass through |
| Per-request override: instance=False, request override=True | quasi-identifiers suppressed (no anchor) |
| Mixed: spans = [PERSON, DATE_TIME, DE_PLZ], anchor present | all three retained |
| **Edge: empty span list + flag=True** | result = [] (no crash — no spans to process) |
| **Edge: all spans are quasi-identifiers, no anchor** | result = [] (all suppressed) |
| **Edge: all spans are strong anchors, no quasi-identifiers** | result = all spans (trivially all retained — anchor check passes, no QI to suppress) |
| **Edge: single anchor + single quasi-identifier minimal pair** | result = [anchor, quasi] — both retained |
| **Edge: allow-list stripped anchor — anchor text in allow list → anchor span absent from results** | quasi-identifiers dropped (operator allow-list decision honored; no anchor in result set) |
| **Edge: only DE_BSNR present (always-emit, neither list)** | result = [DE_BSNR] regardless of flag — always-emit entities are unaffected |

**Behavior contracts for edge cases (explicitly stated):**
- Empty span list → `[]` always. The filter does not crash on empty input.
- All spans are quasi-identifiers, no strong anchor → all suppressed (when flag=True).
- All spans are strong anchors → all retained regardless of flag state (strong anchors are never suppressed).
- Allow-list stripped anchor → quasi-identifiers suppressed (operator policy honored).

**Performance bound:** `filter_by_closed_world()` is O(n) over the span set (one set-membership check per span plus one set-intersection check for anchor presence). Composed with `filter_by_entity_thresholds()` (also O(n)) the post-filter chain remains O(n) in total span count. No new performance bound introduced beyond the existing post-filter chain. At `max_xlsx_cells: 50_000`, each cell is a separate Presidio call producing O(1) spans on average — the filter chain adds negligible overhead relative to the HTTP round-trip to Presidio Analyzer.

### Integration tests

- `/api/detect` with `closed_world_filtering=True` via config + weather query → `has_pii=False`
- `/api/detect` with `closed_world_filtering=True` + named-person treatment text → quasi-identifiers present
- `/api/anonymize` parity: same behavior as detect under both flag states
- Per-request override in request body overrides instance config

### Eval-suite fixtures (new file: `tests/eval/fixtures/closed_world.yaml`)

```yaml
# Acceptance example 1: flag enabled, no anchor → suppress
- text: "What is the weather in Munich, Germany on May 13, 2026?"
  language: en
  expect_clean: true
  closed_world_filtering: true
  notes: "No PERSON/EMAIL/PHONE/IBAN anchor → DATE_TIME and LOCATION suppressed under closed-world."

# Acceptance example 2: flag enabled, PERSON anchor present → quasi-identifiers retained
- text: "Stefan Berger was treated in Munich on May 13, 2026."
  language: en
  expect: [PERSON, LOCATION, DATE_TIME]
  closed_world_filtering: true
  notes: "PERSON anchor present → DATE_TIME and LOCATION emitted."

# Acceptance example 3: PV invoice with multiple anchors
- text: "Invoice for Stefan Berger, stefan.berger@example.com, +49 89 12345678, IBAN DE89 3704 0044 0532 0130 00."
  language: en
  expect: [PERSON, EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE]
  closed_world_filtering: true
  notes: "Multiple strong anchors present; any quasi-identifiers in the block would also be retained."

# Healthcare edge case: anchor-free clinical narrative
- text: "Treatment confirmed for May 13, 2026 at the Munich clinic."
  language: en
  expect_clean: true
  closed_world_filtering: true
  notes: "No anchor → quasi-identifiers suppressed. GAMEABLE: implicit person reference. Not safe for HIPAA/healthcare."
```

**Eval-loader extension design (explicit open question for spec):**

The existing eval loader (`tests/eval/_loader.py:21-28`) defines `Phrase(text, language, expect, expect_clean, notes, fixture)`. The test runner (`tests/eval/test_calibration.py:30-35`) constructs the request body as `{"text": phrase.text, "language": phrase.language}` — no per-fixture flag injection mechanism exists. The proposed `tests/eval/fixtures/closed_world.yaml` fixtures (which include `closed_world_filtering: true`) cannot run without a loader change.

Two options for the spec to choose between:
- **(a) Extend `Phrase` with `request_overrides: dict[str, Any] | None = None`** (recommended). More general than a `closed_world_filtering`-specific bool — supports future per-fixture flag toggles too. Loader reads any keys not in the existing schema as `request_overrides`. Test runner merges them into the POST body. Diff sketch: add `request_overrides: dict[str, Any] | None` field to `Phrase` dataclass; in the YAML loader, collect unrecognized keys into this field; in `test_calibration.py`, spread `request_overrides` into the request body dict.
- **(b) Separate fixture file with a separate test that sets the global flag.** A `tests/eval/test_closed_world.py` that sets `closed_world_filtering=true` globally and loads a `closed_world_fixtures.yaml` that omits the per-fixture key. Simpler but less forward-compatible.

**Recommended posture for spec:** Option (a) — the `request_overrides` generic field makes the loader extensible for any future per-fixture parameter (language overrides, entity-score-threshold overrides, etc.).

### Existing test patterns

- Unit tests in `tests/` use FastAPI `TestClient` with mocked Presidio responses.
- Eval tests in `tests/eval/test_calibration.py` hit the live stack at `localhost:8000` via `requests`.
- Fixture format: `text` (str), `language` (str), `expect` (list[str] or absent), `expect_clean` (bool), `notes` (str, optional).

---

## Documentation Needs

### `docs/v1-feature-spec.md`

Add a "Feature 008: Closed-world filtering for quasi-identifiers" section covering:
- Behavior description and acceptance examples
- Config schema: `closed_world_filtering`, `strong_anchors`, `quasi_identifiers`
- Per-request override semantics
- Threat-model limitations (same three bullets as in the config comment)

### `docs/customizations.md`

Add a changelog entry for Feature 008:
- How to enable: `closed_world_filtering: true` in `config.yaml`
- How to tune the entity lists
- Threat-model warning (verbatim from config comment — HIPAA Safe Harbor note)
- When NOT to use it (agent workflows, healthcare)

### `config.yaml`

Add new block with inline threat-model comment (see Configuration Schema Design section above).

### `docs/supported-entities.md`

Consider adding a column or section classifying each entity as strong-anchor vs. quasi-identifier, so operators understand the closed-world classification at a glance.

---

## Open Questions for Planning

These decisions are not resolved by ADR-0007 and become spec decisions in Step 3a. Each question is stated sharply with a recommended posture where applicable.

1. **Document-upload path (fifth call site)** — OPEN (unresolved, spec-blocking): Should `closed_world_filtering` apply to `/api/documents/upload`? If yes, is the anchor-presence check per-chunk or document-global? Recommended: v1 explicitly out-of-scope with operator note; Option (c) unification as follow-on. See §System Data Flow fifth call site for the full option analysis.

2. **Per-request override scope for entity-class lists** — OPEN (design decision): Should `strong_anchors` and `quasi_identifiers` be per-request overridable? Two options defined in §Per-request override scope. Recommended: Option (a) — boolean flag only, entity-class lists instance-only for v1.

3. **Audit logging interaction with SPEC-006** — OPEN (compliance decision): Under closed-world suppression, `log_detection()` and `log_anonymization()` log post-filter counts (e.g., `entity_count=0` for a submission where Presidio returned 5 spans but all quasi-identifiers were suppressed). The compliance officer cannot distinguish "Presidio found nothing" from "Redakt suppressed 5 quasi-identifiers." Two options the spec must choose between:
   - **(a) No change** — log post-filter state only. Rationale: logs what was surfaced to the caller, consistent with existing `entity_score_thresholds` behavior (which also suppresses silently). A GDPR DPA cannot infer what was dropped.
   - **(b) Add `closed_world_suppressed_count` audit field** — log the count of suppressed spans (not entity text, not entity types — just a count). This is privacy-preserving (count is not PII) and gives compliance visibility into suppression activity. SPEC-006 SEC-001 ("never log PII") is satisfied by logging only counts.
   Recommended posture for spec: Option (b) with `closed_world_suppressed_count: int` added to the audit entry. Justification: without a suppression signal, a misconfigured `strong_anchors` list silently drops detections with no operator-visible diagnostic. A count (not types, not text) is the minimal observable needed for compliance visibility and on-call debugging.

4. **Eval-loader extension** — OPEN (implementation decision): See §Testing Strategy for the two options. Recommended: Option (a) — generic `request_overrides: dict[str, Any] | None` field on `Phrase`.

5. **Web UI override exposure** — OPEN (product decision): The web UI submit routes (`pages.py:53`, `pages.py:123`) do not pass per-request overrides. If `closed_world_filtering` is configured as the instance default, all web UI submissions use that default. A web UI operator cannot turn closed-world off for one paste without an API call. Two options:
   - **(a) Web UI inherits instance default only** — per-request override is API-only. Simplest; acceptable for v1 where the toggle is an operator config, not a per-user control.
   - **(b) Web UI exposes a toggle** — checkbox in the anonymize/detect form. Requires form-field parsing in the pages router and client-side UI change.
   Recommended: Option (a) for v1. Web UI users get operator-configured default behavior. Document this explicitly in the spec.

6. **`NRP` as quasi-identifier** — OPEN (compliance confirmation needed): Classified as quasi-identifier in this research. GDPR Art. 9 perspective documented in §GDPR Art. 9 perspective on NRP classification. Spec review-panel security specialist should confirm; always-emit is the maximally conservative alternative.

7. **`DE_KFZ` classification** — OPEN (spec to confirm): Classified as strong-anchor (conservative default) in the entity table. A vehicle registration plate is traceable to an owner but is not itself a natural-person identifier. Spec review-panel should confirm or move to always-emit.

8. **`MEDICAL_LICENSE` disposition** — OPEN (pre-existing tech debt): Included in `strong_anchors` (conservative default). If the recognizer is disabled in a future cycle, it becomes a no-op in the list. The spec should note this disposition explicitly. See entity classification table for full rationale.

9. **`closed_world_filtering` in `run_detection` / `run_anonymization` signatures** — OPEN (implementation confirmation): Adding `closed_world_filtering: bool | None = None` is consistent with the existing `entity_score_thresholds: dict[str, float] | None = None` pattern. Spec should confirm the signature additions.

10. **Audit-log debug surface** — OPEN (on-call tooling): When a user reports "Redakt missed my PII" and `closed_world_filtering` is on, the on-call engineer needs a diagnostic path. `GET /api/detect?verbose=true` shows post-filter results. Without a `closed_world_suppressed_count` field (see Q3), the audit log does not reveal whether suppression occurred. This is linked to Q3 — if Option (b) is adopted for Q3, this concern is addressed.

---

## Summary of Filter Implementation Sketch

```python
# src/redakt/utils.py — new function, mirrors filter_by_entity_thresholds

def filter_by_closed_world(
    results: list[dict],
    enabled: bool,
    strong_anchors: list[str],
    quasi_identifiers: list[str],
) -> list[dict]:
    """Suppress quasi-identifier spans when no strong-anchor span is present.

    Only active when enabled=True. When disabled, returns results unchanged.
    Strong-anchor spans are always retained regardless of the flag.
    """
    if not enabled:
        return results
    found_types = {r["entity_type"] for r in results}
    has_anchor = bool(found_types & set(strong_anchors))
    if has_anchor:
        return results
    # No anchor: drop all quasi-identifiers
    qi_set = set(quasi_identifiers)
    return [r for r in results if r["entity_type"] not in qi_set]
```

Call site in `run_detection` (detect.py, after line 119):
```python
effective_cwf = (
    entity_closed_world_filtering  # per-request param (None if not overridden)
    if entity_closed_world_filtering is not None
    else settings.closed_world_filtering
)
results = filter_by_closed_world(
    results,
    enabled=effective_cwf,
    strong_anchors=settings.strong_anchors,
    quasi_identifiers=settings.quasi_identifiers,
)
```

Identical pattern in `run_anonymization` at anonymize.py after line 116.
