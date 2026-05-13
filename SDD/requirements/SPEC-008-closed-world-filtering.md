---
review_panel: [security, performance, data-modeling, api-contract, module-depth, reliability, privacy]
eval_required: false
cross_cutting_decisions: []
delivery_mode: whole-feature
---

# SPEC-008-closed-world-filtering

## Executive Summary

- **Based on Research:** RESEARCH-008-closed-world-filtering.md
- **Creation Date:** 2026-05-13
- **Author:** Claude (with Pablo Oliva)
- **Status:** Implemented

Closed-world filtering is a post-filter policy layer in Redakt that suppresses quasi-identifier spans (DATE_TIME, LOCATION, NRP, DE_PLZ) when no strong-anchor span (PERSON, EMAIL_ADDRESS, PHONE_NUMBER, etc.) is present in the same submission. It is off by default, explicitly opt-in, and per-request overridable. The threat model rests on the closed-world assumption: the text submission is the entirety of what the downstream consumer sees, so isolated quasi-identifiers cannot be joined against external data. The feature eliminates user-visible noise on anchor-free queries (weather, date lookups, geographic questions) in the Memodo PV paste-into-AI workflow while leaving anchor-present behavior completely unchanged.

Note on `review_panel`: `privacy` is included in addition to the six standard panels because GDPR Art. 9 special-category data (`NRP`) is classified as a quasi-identifier in the default set. The closed-world assumption's applicability to Art. 9 categories was reviewed by the privacy specialist across panel iterations 1–2 (2026-05-13); the resolution — retaining NRP in `quasi_identifiers` with a mandatory operator Art. 9 responsibility clause — is captured in REQ-017. The panel concluded with REVISE BEFORE PROCEEDING (iter-2) → final iteration (iter-3) → PROCEED. The privacy specialist gate is removed; the spec takes the position.

---

## Research Foundation

### Production Issues Addressed

- Noisy redactions on anchor-free queries: `"What is the weather in Munich, Germany on May 13, 2026?"` flags LOCATION and DATE_TIME despite containing no person-naming anchor (RESEARCH-008 §Production Edge Cases — Real false-positives observed today).
- Memodo PV paste-into-AI workflow false positives: generic date-only phrases (`"Versand voraussichtlich am 15.05.2026."`) and DE_PLZ in address-lookup context (`"Bauvorhaben in 73230 Kirchheim/Teck"`) are flagged when no strong anchor is present (RESEARCH-008 §Production Edge Cases).

### Stakeholder Validation

- **Product (Operator — Pablo / Memodo):** Wants noise reduction for the dominant paste-into-AI workflow. Queries without person anchors should produce zero PII flags. The flag must be off by default so opt-in is deliberate.
- **Engineering:** Configurable entity class lists in config.yaml, off-by-default boolean flag, per-request override mirroring `entity_score_thresholds`. New filter is a pure function in `utils.py` with no external dependencies.
- **End user (PV operator):** Fewer spurious redactions on weather queries, geographic questions, and generic date mentions in daily Copilot/ChatGPT paste workflows.
- **Future agent integration:** Per-request override (`closed_world_filtering: false` in request body) lets an agent re-tighten the rule when the agent's context is not closed-world (e.g., the agent has external CRM knowledge about the person).

### System Integration Points

All four text-path call sites are covered by placing the filter inside `run_detection()` and `run_anonymization()`:

| File | Line | Current call | New filter inserts after | v1 in-scope? |
|------|------|--------------|--------------------------|--------------|
| `src/redakt/routers/detect.py` | 119 | `results = filter_by_entity_thresholds(results, merged_thresholds)` | `results = filter_by_closed_world(results, ...)` at line 120 | YES |
| `src/redakt/routers/anonymize.py` | 116 | `results = filter_by_entity_thresholds(results, merged_thresholds)` | `results = filter_by_closed_world(results, ...)` at line 117 | YES |
| `src/redakt/routers/pages.py` | 53 | calls `run_detection()` | covered by insertion in `run_detection()` | YES (indirect) |
| `src/redakt/routers/pages.py` | 123 | calls `run_anonymization()` | covered by insertion in `run_anonymization()` | YES (indirect) |
| `src/redakt/services/document_processor.py` | 182 | `process_document()` — no `filter_by_entity_thresholds` today | explicitly out-of-scope; see REQ-015 | **NO (v1 out-of-scope)** |

The fifth call site (`/api/documents/upload` → `document_processor.py:182`) is an existing pre-filter inconsistency (`entity_score_thresholds` also does not apply there today). See REQ-015.

### Architectural Decisions (Inherited)

ADR-0007 (`SDD/adr/0007-closed-world-filtering-quasi-identifiers.md`) is authoritative for all cross-cutting decisions for this feature. Key inherited positions:

1. Off-by-default opt-in flag (`closed_world_filtering: false`).
2. Two configurable entity class lists: `strong_anchors` and `quasi_identifiers`. Default sets enumerated in this spec (see REQ-001, REQ-002), resolving ADR-0007's "plus any other identifier-grade types in the current ruleset" deferral.
3. Per-request override mirroring `entity_score_thresholds` — boolean flag only; entity-class lists are instance-wide-only (v1). See REQ-004, REQ-005.
4. Filter placement: same layer as allow-list filter (post-Presidio response, before response builder). See REQ-008.
5. Applies to `/api/detect` and `/api/anonymize` (the text pipeline). Does NOT apply to `/api/documents/upload` in v1. See REQ-015.
6. Threat-model assumption documented in config comment. See REQ-009.
7. DE_PLZ as quasi-identifier (joinability criterion). See entity classification table in REQ-001, REQ-002.
8. HIPAA Safe Harbor incompatibility explicitly noted.

**ADR-0007 amended in-place (2026-05-13):** `DE_STEUER_ID` → `DE_TAX_ID`. The canonical recognizer name is `DE_TAX_ID` (confirmed in `tests/eval/fixtures/de.yaml:5`, `docs/supported-entities.md:71`). This spec uses `DE_TAX_ID` throughout.

---

## Intent

### Problem Statement

Presidio is span-level by design — each recognizer scores its own match in isolation, with no document-level reasoning about whether a full-person anchor is present. The result is high-recall output that flags every quasi-identifier (dates, locations, postal codes, nationalities) regardless of whether the submission contains a person-identifying anchor. For Redakt's primary use case (employees paste a snippet into an AI tool), this produces noisy redactions on queries that cannot identify a natural person: a weather query, a delivery date, an address lookup. The noise creates friction that erodes user trust in the system.

### Solution Approach

A post-filter function (`filter_by_closed_world`) is added to `src/redakt/utils.py`, co-located with `filter_by_entity_thresholds`. It runs after `filter_by_entity_thresholds` in both `run_detection()` and `run_anonymization()`. When enabled, it inspects the assembled span list for at least one strong-anchor entity type; if none is present, all quasi-identifier spans are suppressed. Strong-anchor spans are always emitted regardless of the flag. The function is pure (no side effects), O(n) in span count, and has no external dependencies. An off-by-default flag `closed_world_filtering: false` in config.yaml gates the behavior. Per-request override of the boolean flag is supported via a new optional field on the request models, mirroring `entity_score_thresholds`. The entity-class lists (`strong_anchors`, `quasi_identifiers`) are instance-wide-only in v1.

### Expected Outcomes

- **Flag off (default):** behavior is byte-for-byte identical to today. All spans returned by Presidio that pass `filter_by_entity_thresholds` are emitted. No change for instances that have not opted in.
- **Flag on, anchor absent:** DATE_TIME, LOCATION, NRP, DE_PLZ (and any other entities in `quasi_identifiers`) are suppressed. Strong-anchor spans (and always-emit entities in neither list) pass through unchanged.
- **Flag on, anchor present:** behavior identical to today — all spans returned by Presidio that pass `filter_by_entity_thresholds` are emitted; the anchor check passes, no suppression occurs.
- **Per-request override on (request overrides instance-off):** caller supplies `closed_world_filtering: true` in request body; quasi-identifier suppression applies for that request only.
- **Per-request override off (request overrides instance-on):** caller supplies `closed_world_filtering: false`; all spans emitted for that request.

---

## Success Criteria

### Functional Requirements

#### Entity classification defaults

**REQ-001: Configurable `strong_anchors` list**
The `Settings` class in `src/redakt/config.py` adds a `strong_anchors: list[str]` field with the following default set (resolved from RESEARCH-008 §Complete Entity Classification Table; resolves ADR-0007's "plus any other identifier-grade types in the current ruleset" deferral):

```
PERSON, EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE, EU_VAT_ID, BIC_CODE, SEPA_CREDITOR_ID,
MEDICAL_LICENSE,
DE_TAX_ID, DE_VAT_ID, DE_ID_CARD, DE_PASSPORT, DE_SOCIAL_SECURITY, DE_FUEHRERSCHEIN,
DE_LANR, DE_TAX_NUMBER, DE_HEALTH_INSURANCE, DE_MASTR_ID, DE_KFZ
```

Each entity in this list is classified as a strong anchor per the rationale table below:

| Entity Type | Rationale |
|-------------|-----------|
| `PERSON` | Direct natural-person identifier. Primary joining anchor. |
| `EMAIL_ADDRESS` | Directly identifies a natural person or their mailbox. |
| `PHONE_NUMBER` | Directly identifies a subscriber (natural person or org). |
| `IBAN_CODE` | Directly tied to a bank account holder. |
| `EU_VAT_ID` | Identifies a registered business; in sole-trader context identifies a natural person. |
| `BIC_CODE` | Identifies a financial institution; in personal-banking context associated with account holder. Conservative default. |
| `SEPA_CREDITOR_ID` | SEPA creditor identifier; in sole-trader/individual creditor context identifies a natural person. |
| `MEDICAL_LICENSE` | US DEA-scoped; retained as conservative default. If it fires, it should act as anchor. When disabled, it is a no-op. See REQ-016. |
| `DE_TAX_ID` | German personal tax ID (Steuer-IdNr.) — directly identifies a natural person. |
| `DE_VAT_ID` | German business VAT ID (Umsatzsteuer-IdNr.) — identifies a registered entity; sole-trader = natural person. |
| `DE_ID_CARD` | German national identity card number — unambiguously identifies a natural person. |
| `DE_PASSPORT` | German passport number — unambiguously identifies a natural person. |
| `DE_SOCIAL_SECURITY` | Rentenversicherungsnummer (RVNR) — directly identifies a natural person. |
| `DE_FUEHRERSCHEIN` | German driver's license number — directly identifies a license holder (natural person). |
| `DE_LANR` | Lebenslange Arztnummer — lifetime doctor number; directly identifies a medical professional. |
| `DE_TAX_NUMBER` | Steuernummer — identifies a business or natural person as a tax subject. Conservative default. |
| `DE_HEALTH_INSURANCE` | German health insurance number (Krankenversicherungsnummer) — directly identifies an insured natural person. |
| `DE_MASTR_ID` | Market master data registry ID for energy assets. In PV sector, primary identifier for a customer's installation, associated with an owner. |
| `DE_KFZ` | German vehicle registration plate. Identifies a vehicle; trivially traceable to an owner via traffic records. Conservative default. Operators in jurisdictions where vehicle-plate look-up is not trivially available may move to neither list (always-emit). |

This list is configurable via `strong_anchors:` in `config.yaml`. Operators who want DE_KFZ as always-emit can remove it from this list.

**REQ-002: Configurable `quasi_identifiers` list**
The `Settings` class adds a `quasi_identifiers: list[str]` field with the following default set:

```
DATE_TIME, LOCATION, NRP, DE_PLZ
```

Rationale per entity:

| Entity Type | Rationale |
|-------------|-----------|
| `DATE_TIME` | Joinable only with an anchor (birth date + name = high re-ID risk; date alone is not identifying). |
| `LOCATION` | Joinable with anchor (city + person = re-ID). In isolation: non-identifying. |
| `NRP` | Nationality/religion/politics in isolation does not identify a natural person under the closed-world re-identification threat model. **GDPR Art. 9 classification (resolved):** NRP is treated as a quasi-identifier for re-identification suppression purposes — this is a defensible but operator-responsibility-bearing choice. See REQ-017 for the full lawful-basis position and residual-risk statement. Operators who cannot accept the residual Art. 9 risk must move NRP to the always-emit set (remove it from `quasi_identifiers`). |
| `DE_PLZ` | German postal code resolves to ~10K–40K people per code area. Not person-identifying alone; joinable with PERSON + DATE_TIME. |

This list is configurable via `quasi_identifiers:` in `config.yaml`. Operators wanting unconditional DE_PLZ redaction remove it from this list; it becomes an always-emit entity not subject to closed-world suppression.

**Always-emit entities (neither list):** `DE_BSNR`, `DE_HANDELSREGISTER`, `DE_MALO`, `DE_MELO`, `DE_EEG_ANLAGE`, `DE_ZAEHLERNUMMER`, `IP_ADDRESS`, `CRYPTO` — asset/institution identifiers, not natural-person identifiers. Not added to either list; always emitted regardless of flag state.

#### Feature flag

**REQ-003: Top-level `closed_world_filtering` flag in config.yaml**
A top-level `closed_world_filtering: false` boolean key is added to `config.yaml` and mapped to `Settings.closed_world_filtering: bool = False`. The default is `false`. Instances that have not opted in see zero behavioral change.

#### Per-request overrides

**REQ-004: Per-request override on `/api/detect`**
`DetectRequest` (at `src/redakt/models/detect.py:10`) gains an optional field `closed_world_filtering: bool | None = None`. `None` means "use the instance default from `Settings`." `True` or `False` overrides the instance flag for that single request (REPLACE semantics — non-None value wins). This mirrors the `entity_score_thresholds: dict[str, float] | None = None` field exactly. Merge logic in `run_detection()`:
```python
# SEC-001a gate must execute BEFORE the REPLACE merge — if overrides are disabled,
# treat the request value as if it was not sent (None), so the instance default always wins.
request_value = (
    body.closed_world_filtering
    if settings.allow_per_request_closed_world_override
    else None
)
effective_cwf = (
    request_value
    if request_value is not None
    else settings.closed_world_filtering
)
```
The SEC-001a gate (`allow_per_request_closed_world_override`) is checked first. When `false`, the per-request value is discarded before the REPLACE merge; the effective value is always the instance default. Implementers who copy only the REPLACE formula (without the SEC-001a guard) will produce incorrect behavior in deployments with `allow_per_request_closed_world_override: false`.

**Null-equals-absent semantics (explicit):** A client that omits the `closed_world_filtering` field entirely and a client that explicitly sends `"closed_world_filtering": null` receive identical behavior — both result in `body.closed_world_filtering == None`, which maps to "use instance default." There is no semantic distinction between absent and explicit null. This must be documented in the generated OpenAPI spec as a note on the field. Typed-codegen clients that treat `null` as "explicitly set" should be advised that the Redakt API does not differentiate.

**REQ-005: Per-request override on `/api/anonymize`**
`AnonymizeRequest` (at `src/redakt/models/anonymize.py:10`) gains the same `closed_world_filtering: bool | None = None` field with identical REPLACE semantics and null-equals-absent semantics as REQ-004. Parity with `/api/detect` is required.

**REQ-006 (resolved open question): Entity-class lists are instance-wide-only in v1**
`strong_anchors` and `quasi_identifiers` are NOT per-request overridable in v1. Only the boolean flag is per-request overridable. Rationale: entity-class lists are policy-level configuration; per-request mutation of policy lists is an anti-pattern analogous to per-request allow-list mutation (which only supports append, not replace). Per-request mutation would allow callers to remove PERSON from `strong_anchors` for one request, creating a security anti-pattern. Future v2 may add MERGE-BY-DIFF semantics (`strong_anchors_add` / `strong_anchors_remove`) with explicit security review. This resolves RESEARCH-008 Open Question Q2.

#### Filter behavior

**REQ-007: Suppression logic**
When `closed_world_filtering` is effectively `true` (after merging instance default and per-request override), the filter drops quasi-identifier spans if and only if no strong-anchor span is present in the assembled span list for that submission. "Assembled span list" means the list returned by `filter_by_entity_thresholds()` — i.e., after per-entity score floors have been applied. "Present" means at least one span whose `entity_type` is in the `strong_anchors` set. The assembled span list is the post-allow-list, post-`filter_by_entity_thresholds()` set. Allow-listed strong-anchor spans are absent from this list; their absence may cause the anchor check to fail. See EDGE-005.

**REQ-008: Strong anchors always emitted**
Strong-anchor spans are always emitted regardless of the flag state. If `closed_world_filtering` is `true` and the submission contains a PERSON span, that PERSON span is emitted. The quasi-identifier spans are also emitted (because the anchor check passes). Strong anchors are never suppressed by this filter.

**REQ-009: Filter runs AFTER `filter_by_entity_thresholds()`**
The new `filter_by_closed_world()` call inserts AFTER `filter_by_entity_thresholds()` at `detect.py:119` (new call at line 120) and AFTER `filter_by_entity_thresholds()` at `anonymize.py:116` (new call at line 117). The filter never runs before per-entity score floor filtering. The always-emit ordering is: allow-list filter (inside Presidio), `filter_by_entity_thresholds()`, `filter_by_closed_world()`.

#### Gate precedence and composition (consolidated)

**SEC-002a: Precedence rule for overlapping configuration gates**

Four policy gates interact at request time. The canonical precedence order (highest first) is:

1. **REQ-020 HIPAA auto-force** — when `"HIPAA"` is in `regulatory_scope`, `allow_per_request_closed_world_override` is forced to `false` at config-load. If `closed_world_filtering: true` in the same HIPAA config, a startup `ValidationError` prevents the service from starting. HIPAA enforcement overrides all other gates.
2. **SEC-001a operator gate** — `allow_per_request_closed_world_override: false` causes all per-request `closed_world_filtering` values to be discarded (treated as `None`) before the REPLACE merge. The effective value is always the instance default.
3. **Per-request override** — when `allow_per_request_closed_world_override: true` (the default), a non-None `closed_world_filtering` field in the request body replaces the instance default for that request only (REPLACE semantics).
4. **Instance default** — `Settings.closed_world_filtering` (from `config.yaml`). Used when no per-request override is present or when SEC-001a gate discards the request value.

**Truth table (8 rows covering the full 4-variable state space):**

| `regulatory_scope` has `"HIPAA"` | Instance flag (`closed_world_filtering`) | `allow_per_request_closed_world_override` | Per-request value | Effective behavior |
|-----------------------------------|------------------------------------------|-------------------------------------------|-------------------|--------------------|
| YES | `true` | any | any | **Service refuses to start** — REQ-020 `ValidationError` at config-load. |
| YES | `false` | `true` (explicit) | `true` or `false` | SEC-001a auto-forced to `false` (HIPAA gate). Per-request silently ignored. Effective = instance default (`false`). Filter disabled. |
| YES | `false` | `false` | `true` or `false` | Same — per-request silently ignored. Filter disabled. |
| YES | `false` | any | `None` | Filter disabled (instance default = `false`). |
| NO | `true` | `false` | `true` or `false` | Per-request silently ignored (SEC-001a gate). Effective = instance default (`true`). Filter runs. |
| NO | `true` | `true` | `true` or `false` | Per-request wins (REPLACE). Effective = per-request value. |
| NO | `false` | `true` | `true` or `false` | Per-request wins (REPLACE). Effective = per-request value. |
| NO | `false` | `true` | `None` | Instance default applies. Filter disabled. |

**References:** REQ-003 (instance flag), REQ-004/REQ-005 (per-request REPLACE merge), SEC-001a (operator gate), REQ-020 (HIPAA auto-force). The code snippet in REQ-004 implements rows 5–8; rows 1–4 are enforced at config-load before any request is handled.

#### Configuration quality

**REQ-010: Config comment documenting threat-model assumption**
The `config.yaml` block for `closed_world_filtering` includes an inline comment stating: (a) the closed-world assumption; (b) when it fails (agent workflows with external context, chunked document processing, LLM parametric knowledge); (c) HIPAA Safe Harbor incompatibility; (d) the gameable-narrative failure mode; (e) the NRP/Art. 9 operator responsibility; (f) that the filter does NOT apply to `/api/documents/upload` in v1; (g) the operator config gate for per-request overrides. The exact comment text is:
```yaml
# --- Closed-world filtering ---
# THREAT MODEL: This filter only holds when the submission is the FULL
# context the downstream consumer sees. Agent workflows that combine the
# snippet with external knowledge (CRM, email history, model parametric
# knowledge) break the assumption.
# GAMEABLE: Role-based references ("the patient", "the customer", "der Kunde")
# do not trigger the anchor check — quasi-identifiers in such narratives will
# pass through unredacted. Not safe for healthcare, social-services, or any
# context using role-based identification.
# HIPAA: Safe Harbor requires unconditional date removal — do not enable this
# flag in Safe Harbor contexts. See regulatory_scope config for enforcement.
# ART. 9: NRP (nationality, religion, politics) is classified as a
# quasi-identifier under this filter. Operators who enable closed-world
# filtering are responsible for documenting their Art. 9 lawful basis
# separately. Redakt's audit log (closed_world_suppressed_count) does not
# satisfy Art. 9 record-keeping on its own.
# NOTE: Does NOT apply to /api/documents/upload (document pipeline) in v1 —
# see RESEARCH-008 §System Data Flow (fifth call site) for rationale.
# OVERRIDE: Per-request closed_world_filtering field is enabled by default.
# Set allow_per_request_closed_world_override: false to disable per-request
# override at the deployment boundary (see SEC-001a).
closed_world_filtering: false
```

This verbatim comment text must also appear in `docs/customizations.md` in the closed-world filtering section, per REQ-020.

**REQ-011: Config schema validation**
The Pydantic `Settings` model validates that `strong_anchors` and `quasi_identifiers` are each a `list[str]` (non-None, homogeneous) with the following rules:

1. **Type check:** If either field is set to a non-list value or contains non-string entries in `config.yaml`, config-load raises a `ValidationError` at startup with a clear field-level error message. Graceful degradation (using defaults) is NOT acceptable — a misconfigured entity list is a silent correctness bug; fail-fast is required. See FAIL-001.

2. **Duplicate check:** If any entity-type string appears more than once within the same list (e.g., `strong_anchors: ["PERSON", "PERSON"]`), config-load raises a `ValidationError` listing the duplicate value(s). Duplicates imply different semantics that do not exist; fail-fast avoids operator confusion.

3. **Canonical-set validation:** Each entry in `strong_anchors` and `quasi_identifiers` is checked against the canonical entity-type constant. An entry that does not appear in the canonical set produces a startup `WARNING` log line naming the unrecognized type (e.g., `WARN: strong_anchors contains unrecognized entity type 'PEROSN' — it will never match a Presidio result; likely a typo`). Whether this escalates to a `ValidationError` is controlled by a new Settings field `strict_entity_validation: bool = False`; when `True`, unrecognized types cause a `ValidationError`. See FAIL-005.

   **Canonical-set source-of-truth (explicit):**
   - **Location:** `src/redakt/entity_catalog.py` — a single module containing `CANONICAL_ENTITY_TYPES: frozenset[str]`. This is the authoritative constant used for validation at config-load.
   - **Maintenance mechanism:** The constant is maintained manually alongside `docs/supported-entities.md`. A CI lint test (`tests/unit/test_entity_catalog.py`) asserts that every entity type in `docs/supported-entities.md`'s entity table is present in `CANONICAL_ENTITY_TYPES` and vice versa — the doc and the constant must not drift. The CI test is the enforcement mechanism.
   - **Precedence when doc and constant drift:** The constant (`entity_catalog.py`) wins for validation — startup validation runs against the constant, not the doc. When drift is detected by the CI lint test, the PR is blocked until both are reconciled. Operators who add a new entity type must update both `docs/supported-entities.md` (adding the row and `classification:` column per REQ-021) AND `entity_catalog.py` (adding the string to `CANONICAL_ENTITY_TYPES`).
   - **REQ-021 relationship:** `docs/supported-entities.md`'s `classification:` column (per REQ-021) is a superset of `entity_catalog.py` — the doc also carries the `classification:` metadata. The CI lint test validates both: entity names match AND each entity has a valid `classification:` value in the doc. The constant does not carry classification metadata (it is a flat `frozenset[str]`); classification is a doc-level concern surfaced at PR review time.
   - **Post-upgrade migration note for `strict_entity_validation: true` operators:** After a Redakt upgrade that adds new entity types to `CANONICAL_ENTITY_TYPES`, operators running with `strict_entity_validation: true` should consult the release notes and `docs/supported-entities.md` to confirm their `strong_anchors`/`quasi_identifiers` lists are consistent with the expanded canonical set. New entity types added to the canonical set do not affect existing operator configs (they are unknown at startup only if explicitly listed in the operator's config with a typo).

**REQ-012: No entity type may appear in both `strong_anchors` and `quasi_identifiers`**
At config-load time, if an entity type string appears in both lists, `Settings` validation raises a `ValidationError` listing the conflicting type(s). The `strong_anchors`-wins-silently alternative is explicitly rejected — operator intent is ambiguous, so fail-fast is correct. See EDGE-007.

#### Audit logging

**REQ-013 (resolved open question): Audit logging emits `closed_world_suppressed_count`**
When `filter_by_closed_world()` suppresses one or more spans, the audit entry for that request includes a `closed_world_suppressed_count: int` field carrying the count of suppressed spans. When the filter is disabled or suppresses zero spans, the field is `0` (always present in the audit entry, never absent). The field carries counts only — never entity type names, never original text, never anonymized text. SPEC-006 §SEC-001 ("audit log entries never contain PII") is satisfied: span counts are not PII. This resolves RESEARCH-008 Open Question Q3. Rationale: without a suppression signal, a misconfigured `strong_anchors` list silently drops detections with no operator-visible diagnostic; a count is the minimal observable needed for compliance visibility and on-call debugging.

**Per-request override audit coverage:** The audit entry also includes `closed_world_filtering_override: bool | null` indicating whether the per-request override was used (`true`/`false` if the caller set the field explicitly, `null` if the caller omitted it and the instance default was used). This field makes misuse of the relaxation knob detectable in audit logs.

**Document-upload path (REQ-015 out-of-scope):** Audit entries for `/api/documents/upload` and `/documents/submit` set `closed_world_suppressed_count: null` (JSON null, not `0`) and `closed_world_filtering_override: null`. The `null` value is a sentinel meaning "closed-world filter does not apply to this pipeline in v1" — it is distinguishable from `0` (filter applied, no spans suppressed) and from an absent field. Compliance tooling that aggregates `closed_world_suppressed_count` must treat `null` as "not applicable" rather than "zero suppression."

**Schema compatibility:** This addition to the SPEC-006 audit entry is a **backwards-compatible additive extension** — new fields are added, no existing fields are removed or renamed. However, downstream consumers that validate audit entries with a strict closed-set schema (Pydantic with `model_config = ConfigDict(extra='forbid')`, or JSON Schema with `"additionalProperties": false`) will fail validation. SPEC-006's audit-entry schema must be declared as **open-set** (additional fields permitted) before this change lands. If SPEC-006 currently declares a closed-set schema, that is a SPEC-006 amendment required as a dependency of this feature.

#### Eval-suite extension

**REQ-014 (resolved open question): Eval-loader extended with `request_overrides` field**
`tests/eval/_loader.py` is extended: the `Phrase` dataclass gains a `request_overrides: dict[str, Any] | None = None` field. The YAML loader populates `request_overrides` from a **reserved nested `request_overrides:` key** in each fixture entry (not from any unrecognized top-level key). Example fixture entry:
```yaml
- text: "Was ist das Wetter in München?"
  language: de
  expect_clean: true
  request_overrides:
    closed_world_filtering: true
```
Using a reserved nested key (rather than collecting all unrecognized top-level keys) prevents future top-level fixture metadata keys (e.g., `tags:`, `notes:`, `skip:`) from accidentally being collected into `request_overrides` and forwarded in request bodies. Future per-fixture request fields (e.g., `entity_score_thresholds`, `language_override`) are added as entries under `request_overrides:`, not as top-level keys. The test runner (`tests/eval/test_calibration.py`) merges `request_overrides` into the POST body when non-None. This resolves RESEARCH-008 Open Question Q4.

#### Document-upload path

**REQ-015 (resolved open question): Document-upload path explicitly out-of-scope in v1**
`filter_by_closed_world()` is NOT applied in `document_processor.py` in v1. Enabling `closed_world_filtering: true` in config.yaml has no effect on `/api/documents/upload` or `/documents/submit`. This is a deliberate scoping decision, not an oversight. Rationale: (a) `filter_by_entity_thresholds()` also does not apply to the document path today — this is a pre-existing inconsistency; (b) the per-chunk anchor-presence check ("a PERSON in chunk 1 does not suppress quasi-identifiers in chunk 3") contradicts the closed-world assumption for multi-chunk documents; (c) a document-global anchor check requires a two-pass design that is larger than this feature's scope. Operator documentation must state this limitation explicitly. A follow-on ticket (v2) should unify both post-filters into a shared `apply_post_filters(results, settings, overrides)` helper used by all three pipelines.

#### Entity catalog classification gate

**REQ-021: Canonical entity classification column in `docs/supported-entities.md`**
`docs/supported-entities.md` is updated with an explicit `classification:` column for every entity type in the Redakt/Presidio catalog. Valid classification values are `strong_anchor`, `quasi_identifier`, or `always_emit`. The default sets in REQ-001 and REQ-002 must be consistent with this column. PR reviews that add a new entity type to Redakt must classify it in this column before merging — the classification cannot default to `always_emit` by omission. This is a doc-and-process requirement, not a runtime code requirement. The "always-emit" class has no dedicated `config.yaml` list representation (it is implicit as "in neither list"), but the catalog column makes the classification explicit and operator-readable.

This requirement addresses the implicit-classification anti-pattern: a new entity type that is forgotten in both `strong_anchors` and `quasi_identifiers` defaults to always-emit silently. The catalog column makes that default an explicit documented decision rather than an accident.

#### MEDICAL_LICENSE disposition

**REQ-016: `MEDICAL_LICENSE` disposition documented**
`MEDICAL_LICENSE` is included in the `strong_anchors` default list as a conservative default. The implementation must document (in a config comment or inline code comment) that: (a) `MedicalLicenseRecognizer` is US DEA-scoped; (b) it produces a known false-positive on `DE_MASTR_ID` substrings; (c) if the recognizer is disabled entirely, removing it from `strong_anchors` is a no-op (it never fires, so the list entry is harmless). No code change is required for the recognizer itself — this is a documentation and classification decision only.

#### NRP classification — GDPR Art. 9 position (resolved)

**REQ-017: `NRP` classification is quasi-identifier with mandatory operator Art. 9 responsibility clause**

`NRP` (Nationality, Religious belief, Political opinion) is **retained in `quasi_identifiers`** as the default classification. This is a decisive, reasoned position — not a deferred gate. The resolution is as follows.

**Rationale for quasi-identifier classification (closed-world re-identification threat model):**
Under the closed-world assumption, NRP data in isolation (e.g., `"She is Muslim"` with no PERSON anchor) cannot be joined to identify a natural person without an external anchor. The re-identification risk that justifies suppression — joining nationality or religion to a named individual — only arises when a strong anchor (PERSON, EMAIL_ADDRESS, etc.) is present. When no anchor is present, suppressing NRP reduces noise without material re-identification risk reduction, since the downstream consumer cannot join the suppressed value to an identity. This is the same rationale as DATE_TIME and LOCATION.

**Residual Art. 9 risk — operator responsibility (this is NOT a free pass):**
GDPR Art. 9 grants special-category protection to NRP data **regardless of identifiability**. The closed-world re-identification rationale does not override Art. 9 — it only addresses re-identification risk, not the broader Art. 9 lawful-basis tracking obligation. Specifically:

- An operator who enables `closed_world_filtering: true` and has NRP in `quasi_identifiers` (the default) will suppress NRP spans when no anchor is present. If a downstream system subsequently processes that NRP text in a profiling or decision context, the operator has lost the Art. 9 audit trail that Redakt's PII detection was meant to surface.
- **Redakt's `closed_world_suppressed_count` audit field does NOT satisfy Art. 9 record-keeping.** It records that suppression occurred but not what category of data was suppressed or what lawful basis applied.
- **Operators enabling NRP suppression must document their Art. 9 lawful basis separately** in their GDPR Records of Processing Activities (RoPA). The config comment in REQ-010 states this obligation verbatim.

**The closed-world suppression rule is appropriate for re-identification quasi-identifiers. It is not a substitute for Art. 9 unconditional removal.** These are different regulatory concerns.

**Operator escape hatch:** Operators who cannot accept the residual Art. 9 risk — because their workflow does not satisfy the closed-world assumption for NRP data, or because their legal team requires unconditional NRP removal — MUST move `NRP` from `quasi_identifiers` to neither list (always-emit), so NRP is always emitted regardless of anchor presence. This is a single-line config change.

**HIPAA Safe Harbor note (cross-reference):** HIPAA Safe Harbor does not cover NRP specifically (it covers 18 PHI categories, none of which are religion or political opinion); however, healthcare operators must also evaluate Art. 9 (if EU-facing) or applicable US state privacy law before enabling NRP suppression.

**V1 composition gap (acknowledged):** Operators cannot simultaneously enable closed-world re-identification suppression for NRP AND maintain a separate Art. 9 audit trail for each suppressed NRP mention within Redakt. The v1 design is binary: either NRP is in `quasi_identifiers` (closed-world suppression, no per-category audit trail) or in neither list (always-emit, no closed-world suppression). There is no "suppress AND audit separately" path in v1. This limitation is inherent to the single-integer `closed_world_suppressed_count` audit field (which counts all quasi-identifiers, not by category). Operators who require both suppressions must implement Art. 9 record-keeping outside Redakt (in their RoPA, process documentation, or a separate compliance tool). A v2 path exists: adding `suppressed_by_category: dict[str, int]` to the audit entry (e.g., `{"NRP": 2, "DATE_TIME": 1}`) would give operators category-level visibility while preserving the re-id suppression — this is deferred to a future spec.

This resolves RESEARCH-008 Open Question Q6 and the panel's HIGH finding on REQ-017. The panel-gate language ("the privacy specialist must confirm") is removed — the spec takes the position.

#### Regulatory scope enforcement

**REQ-020: `regulatory_scope` config field for HIPAA Safe Harbor enforcement**
A new `regulatory_scope: list[str] = ["GDPR"]` field is added to `Settings` and `config.yaml`. Valid values include `"GDPR"` and `"HIPAA"`. When `"HIPAA"` is present in the list and `closed_world_filtering: true` is set, `Settings` validation raises a `ValidationError` at startup:
```
ValidationError: closed_world_filtering: true is incompatible with regulatory_scope: ["HIPAA"].
HIPAA Safe Harbor requires unconditional date removal; the closed-world filter suppresses
DATE_TIME only when no anchor is present, which does not satisfy Safe Harbor requirements.
Set closed_world_filtering: false or remove "HIPAA" from regulatory_scope.
```
This makes the Safe Harbor incompatibility a detectable runtime error rather than a documentation-only warning. The config comment in REQ-010 references this field. The default `["GDPR"]` does not trigger the ValidationError and is backwards-compatible with existing deployments. Operators who deploy in a GDPR-only context and are certain they are not in a HIPAA Safe Harbor scope may omit `"HIPAA"` from the list.

**Per-request override gating under HIPAA scope (extended):** The startup `ValidationError` covers the instance-default config path (`closed_world_filtering: true` in `config.yaml`). However, a deployment may have `closed_world_filtering: false` at startup (passes the check) but still allow per-request `closed_world_filtering: true` overrides via `allow_per_request_closed_world_override: true` (the default). This creates a defense-in-depth gap: a HIPAA-scoped deployment that relies on REQ-020 to prevent Safe Harbor incompatibility would still allow a caller to enable the filter on a per-request basis.

**Resolution:** When `"HIPAA"` is in `regulatory_scope`, the implementation MUST auto-force `allow_per_request_closed_world_override = false` — regardless of the operator's explicit `allow_per_request_closed_world_override` setting. This is enforced at config-load (Pydantic `@model_validator`), not at request time. A startup INFO log line confirms:
```
INFO: regulatory_scope includes HIPAA — per-request closed_world_filtering overrides are
forcibly disabled (allow_per_request_closed_world_override set to false). HIPAA Safe Harbor
compliance requires that per-request relaxation of PII controls is not possible.
```
If the operator also sets `allow_per_request_closed_world_override: false` explicitly, no conflict exists. If the operator sets `allow_per_request_closed_world_override: true` AND `regulatory_scope: ["HIPAA"]`, the `true` value is silently overridden to `false` with the above INFO log line (no `ValidationError` for this combination — it is not a fatal misconfiguration, it is an automatic safety enforcement). This ensures the HIPAA gate is complete: neither the instance default nor the per-request override can enable the closed-world filter in a HIPAA-scoped deployment.

**Scope limitation (explicit):** REQ-020's enforcement is HIPAA-only. Non-HIPAA healthcare contexts (e.g., German Krankenhaus under GDPR Art. 9, UK NHS, social services) do not trigger a runtime gate — these operators must rely on the config comment (REQ-010 GAMEABLE clause), EDGE-009 guidance, and REQ-017's NRP Art. 9 operator responsibility clause. This asymmetry is intentional: HIPAA has a specific Safe Harbor framework with enumerable requirements; other healthcare contexts have jurisdiction-specific regulations that Redakt cannot enumerate. The asymmetry is acknowledged, not hidden.

The threat-model paragraph from REQ-010's config comment (the gameable-narrative warning, HIPAA note, and Art. 9 operator responsibility) must also appear verbatim in `docs/customizations.md` in the closed-world filtering section. This is the second publication point for the threat-model framing; it ensures operators reading `docs/customizations.md` to make a deployment decision see the full threat model, not a summary. Any future update to the config comment text in REQ-010 must be reflected in `docs/customizations.md` in the same PR.

#### Web UI exposure

**REQ-018 (resolved open question): Web UI uses instance default; per-request override is API-only**
The web UI submit routes at `src/redakt/routers/pages.py:53` (detect) and `pages.py:123` (anonymize) do not expose a per-request `closed_world_filtering` toggle in v1. Web UI submissions use the instance default from `config.yaml`. Per-request override is API-only. Rationale: the closed-world toggle is an operator-configured policy, not a per-user per-paste control; instance-default is the correct granularity for web UI. A web UI toggle (checkbox in the form) is deferred to v2 if product deems it necessary. This resolves RESEARCH-008 Open Question Q5.

#### Signature confirmation

**REQ-019: Function signatures for `run_detection` and `run_anonymization`**
Both functions gain a `closed_world_filtering: bool | None = None` parameter, consistent with the existing `entity_score_thresholds: dict[str, float] | None = None` parameter pattern. The per-request override value from the request model is forwarded directly to these functions; merge logic (REPLACE semantics) resolves the effective boolean. This resolves RESEARCH-008 Open Question Q9.

---

### Non-Functional Requirements

**PERF-001: O(n) filter complexity, <1ms overhead**
`filter_by_closed_world()` has O(n) complexity over the span set — one set-membership check per span plus one set-intersection check for anchor presence. Total post-filter chain (allow-list + `filter_by_entity_thresholds()` + `filter_by_closed_world()`) remains O(n) in total span count. Post-filter overhead must be <1ms on a 100-span document. At `max_xlsx_cells: 50_000`, each cell is a separate Presidio call producing O(1) spans on average; the filter adds negligible overhead relative to the HTTP round-trip.

**Set pre-computation requirement (resolved):** `Settings` exposes pre-computed `strong_anchors_set: frozenset[str]` and `quasi_identifiers_set: frozenset[str]` properties, computed once at config-load from the `strong_anchors` and `quasi_identifiers` lists. The `filter_by_closed_world()` function receives these `frozenset` values (not the raw `list[str]`), eliminating per-call list-to-set conversion. This ensures the per-call overhead is O(1) fixed overhead (frozenset lookup), not O(k) list-to-set conversion where k = number of entity types in the lists. This matters when the document path expands in v2 (50,000 cells × per-call set conversion otherwise dominates).

**Tail behavior (resolved):** For span lists exceeding 10,000 spans (pathological input — e.g., a pasted log file with 10,000 date mentions), `filter_by_closed_world()` still completes in O(n) time. However, p99 latency for such inputs is outside the `<1ms` guarantee for 100-span documents — the `<1ms` bound applies to the 100-span case only. Pathological inputs (>10,000 spans) are not a v1 success criterion. The document-upload path (REQ-015) bypasses this filter in v1, so the 50,000-cell worst case does not hit this code path. A benchmark for a 10,000-span input is added to the performance validation suite (see Validation Strategy).

**PERF-002: No-op path when disabled**
When `closed_world_filtering` is effectively `false`, the filter returns the input list immediately without any span-list iteration. The no-op path is O(1).

**SEC-001: Per-request override trust model (explicit)**

The `closed_world_filtering` field in the request body is treated as a trusted parameter with the following explicit trust model:

**(a) Trust level — same as `entity_score_thresholds`:** The per-request override inherits the same trust model as `entity_score_thresholds`: the caller is trusted by the deployment. There is no separate authentication or authorization surface for this field. A caller who can reach `/api/detect` or `/api/anonymize` can send `closed_world_filtering: true`. No API key, bearer token, or IP-level gate is introduced by this spec beyond whatever Redakt's existing endpoint security provides.

**(b) Directional asymmetry — this is a relaxation knob:** Unlike `entity_score_thresholds` (which tightens PII detection by raising score floors), `closed_world_filtering: true` relaxes a privacy control — it suppresses quasi-identifier spans that would otherwise be emitted. This is the opposite direction of `entity_score_thresholds`. Operators must understand that per-request `closed_world_filtering: true` can only be issued by callers who already have access to the endpoint, but it reduces the PII output for that request.

**(c) Operator deployment posture:** Operators who deploy Redakt in an untrusted-caller context (e.g., an endpoint reachable by unauthenticated users, an internal tool with broad user access where quasi-identifier suppression must be unconditional) must NOT enable `closed_world_filtering` globally OR must disable the per-request override via the `allow_per_request_closed_world_override` flag (see SEC-001a). Redakt's design assumption for v1 is VPN-fronted / internal-only deployment; public-internet deployments with untrusted callers are out of scope for this trust model.

**(d) Audit visibility:** Every request that uses the per-request override is recorded in the audit log with `closed_world_filtering_override: true` or `closed_world_filtering_override: false` (per REQ-013). Operators relying on audit logs to detect misuse must ensure audit log retention and alerting are configured appropriately.

**SEC-001a: Operator config gate for per-request override**

A new `Settings` field `allow_per_request_closed_world_override: bool = True` is added to `config.yaml`. When set to `false`:
- The `closed_world_filtering` field in request bodies is silently ignored (treated as if the field was not sent).
- The effective value is always the instance default from `closed_world_filtering` in config.yaml.
- A startup INFO log line confirms: `"allow_per_request_closed_world_override: false — per-request closed_world_filtering overrides are disabled; instance default will always be used."` 

This gives operators who cannot accept the relaxation knob a deployment-level enforcement mechanism, rather than a documentation-only warning. The config-gate flag defaults to `True` (permissive) for backwards compatibility with environments that expect the override to work.

**SEC-002: Threat-model assumption documented in config comment**
The config comment per REQ-010 explicitly states the assumption and its failure cases. The comment is operator-facing and must be preserved verbatim (not summarized or truncated) in the final `config.yaml`.

**SEC-003: Verbose mode (`?verbose=true`) interaction with closed-world filter (v1 scope)**
In v1, `GET /api/detect?verbose=true` does NOT reveal which spans were suppressed by the closed-world filter — it reveals only the post-filter span set. The diagnostic path for understanding closed-world suppression in v1 is:
1. The `closed_world_suppressed_count` field in the audit log (REQ-013).
2. Disabling `closed_world_filtering` temporarily (per-request override) and comparing output.

Verbose mode in v1 does include the effective `closed_world_filtering` flag value for the request (true/false) so on-call engineers can confirm whether the filter is active. It does NOT include suppressed-span types or the pre-filter span list. Adding pre-filter span disclosure to verbose mode is explicitly out of scope for v1 and deferred to v2. This is a documented v1 limitation, not an oversight.

**COMPAT-001: Default behavior byte-for-byte identical to today**
With `closed_world_filtering: false` (the default), the filter is a no-op. The output of `/api/detect` and `/api/anonymize` must be byte-for-byte identical to the current production behavior for all existing test inputs. No regressions on any passing unit, integration, or eval test.

**REL-001: Determinism and retry-variance clarification**
The closed-world filter is **deterministic given a fixed Presidio Analyzer response** — for the same span list input, the filter always produces the same output. The filter has no internal state, no caching, and no non-determinism of its own.

However, if a client retries `/api/detect` after a transient failure, the Presidio Analyzer upstream may return a different span list on the second call (transformer-based NER scoring has model-level non-determinism at confidence-score boundaries). When the Presidio response changes between retries, the anchor check may flip (e.g., anchor present on attempt 1 → anchor absent on attempt 2 due to a borderline PERSON score falling below threshold), producing different `closed_world_suppressed_count` values across retry attempts.

**Operator guidance:** Do not interpret per-request `closed_world_suppressed_count` as a stable metric for individual requests. Use time-window aggregates for compliance reporting. Retry-time variance in `closed_world_suppressed_count` is a signal of Presidio upstream non-determinism, not a closed-world filter bug. This is inherent to the transformer-based NER pipeline and is not addressable at the Redakt layer.

---

## Edge Cases (Research-Backed)

**EDGE-001: Empty span list**
`filter_by_closed_world([], enabled=True, ...)` returns `[]`. The filter does not crash on empty input. No work to do; pass through immediately.

**EDGE-002: All spans are quasi-identifiers, no strong anchor**
When enabled (`True`): all spans suppressed; result is `[]`. When disabled: all spans pass through unchanged. Both states must be asserted.

**EDGE-003: All spans are strong anchors, no quasi-identifiers**
All spans retained regardless of flag state. The anchor check passes (strong anchor present); no quasi-identifier spans exist to suppress. The filter returns the input unchanged.

**EDGE-004: Only always-emit entities present (e.g., `DE_BSNR`, `DE_HANDELSREGISTER`)**
Entities in neither `strong_anchors` nor `quasi_identifiers` are unaffected by the filter in all states. The anchor check: always-emit entities do not satisfy the anchor check (they are not in `strong_anchors`). However, since they are also not in `quasi_identifiers`, they are never suppressed. Result: `[DE_BSNR]` passes through regardless of flag. No anchor → quasi-identifiers would be suppressed if any existed; always-emit entities continue to pass.

**EDGE-005: Allow-list-stripped strong anchor**
If a strong-anchor entity's text (e.g., `"Stefan Berger"`) appears on the allow list, Presidio's `/analyze` call suppresses the span before Redakt sees results. The assembled span list arriving at `filter_by_closed_world()` has no strong anchor. When the filter is enabled, quasi-identifiers in the same submission are suppressed. This is correct behavior: the operator has declared the name non-PII via the allow list; the filter respects that policy decision. "Allow-list semantics take precedence" — if the user allow-lists their own name, they are declaring it non-PII for that submission, and downstream quasi-identifier suppression is the consistent extension of that declaration. This edge case must be documented in `docs/customizations.md`.

**EDGE-006: Per-request override conflicts with instance default**
Request value wins (REPLACE semantics). `closed_world_filtering: true` in the request body overrides `closed_world_filtering: false` in config.yaml, and vice versa. No merging; no precedence conflict.

**EDGE-007: Entity type in BOTH `strong_anchors` and `quasi_identifiers`**
Config-load raises a `ValidationError` listing the conflicting type(s). Silent resolution (strong_anchors wins) is explicitly rejected — operator intent is ambiguous. See REQ-012.

**EDGE-008: `strong_anchors` or `quasi_identifiers` is empty in config**
If `strong_anchors` is an empty list, no entity type can satisfy the anchor check; the filter behaves as if no anchor is ever present. When enabled, all quasi-identifiers are always suppressed (effectively equivalent to unconditional suppression). If `quasi_identifiers` is an empty list, no entity type is subject to suppression; the filter is a no-op regardless of the flag.

**Degenerate-configuration detection (resolved — runtime warning required):** When `closed_world_filtering: true` AND `strong_anchors: []` (empty), `Settings` validation emits a startup `WARNING` log line:
```
WARN: closed_world_filtering is true but strong_anchors is empty — every submission
will suppress all quasi-identifiers regardless of content. This is likely a
misconfiguration. To disable closed-world filtering, set closed_world_filtering: false
instead of clearing strong_anchors.
```
This is a WARNING, not a `ValidationError`, because an intentional always-suppress configuration (e.g., an operator who wants unconditional quasi-identifier suppression as a policy choice) is technically valid, albeit unusual. Operators who explicitly intend this behavior can suppress the warning by acknowledging it is deliberate in `config.yaml` comments. The filter must not crash on either empty-list case.

**EDGE-009: Gameable anchor-free narrative ("Treatment confirmed for May 13, 2026 at the Munich clinic.")**
No PERSON anchor present → quasi-identifiers (DATE_TIME, LOCATION) pass through when the filter is enabled. The submission carries implicit joinability risk that the filter cannot detect. This is explicitly accepted per ADR-0007 for B2B PV workflows. Healthcare or social-services contexts should not enable `closed_world_filtering`. This behavior must appear in the eval fixtures and operator documentation. See RESEARCH-008 §Gameable narratives.

**Enforcement asymmetry (acknowledged):** REQ-020 enforces HIPAA incompatibility with a startup `ValidationError`. Non-HIPAA healthcare contexts (German Krankenhaus under GDPR Art. 9, UK NHS, social services, etc.) do not trigger a runtime gate — there is no `regulatory_scope: ["GDPR-HEALTHCARE"]` enforcement value. Operators in these contexts must rely on: (a) this EDGE-009 guidance; (b) the REQ-010 config comment GAMEABLE clause; (c) REQ-017's NRP Art. 9 operator responsibility clause. This asymmetry is intentional and acknowledged: HIPAA Safe Harbor is a specific, enumerable requirement; non-HIPAA healthcare regulation is jurisdiction-specific and cannot be enumerated by Redakt. The operator is responsible for evaluating their regulatory context before enabling the flag in any healthcare or social-services workflow.

**EDGE-010: Mixed strong anchors, quasi-identifiers, and always-emit entities**
When enabled: anchor check passes (at least one strong anchor present) → quasi-identifiers retained → always-emit entities pass through. All spans emitted. When disabled: all spans emitted (no-op). No entity type is accidentally suppressed.

---

## Failure Scenarios

**FAIL-001: Invalid config — non-list or non-string-element `strong_anchors` / `quasi_identifiers`**
- **Trigger:** Operator edits `config.yaml` and sets `strong_anchors: "PERSON"` (string instead of list) or `quasi_identifiers: [DATE_TIME, 42]` (non-string element).
- **Expected behavior:** `Settings` Pydantic validation raises `ValidationError` at startup. Application does not start. Error message cites the field name and expected type.
- **User communication:** Startup log shows the `ValidationError` with field-level detail. No HTTP server starts; no requests are served.
- **Recovery:** Operator corrects `config.yaml` to a valid YAML list of strings and restarts the service.

**FAIL-002: `strong_anchors` / `quasi_identifiers` overlap (same entity in both lists)**
- **Trigger:** Operator adds `DATE_TIME` to `strong_anchors` without removing it from `quasi_identifiers` (or vice versa).
- **Expected behavior:** `Settings` validation raises `ValidationError` at startup listing the conflicting type(s). See REQ-012.
- **Recovery:** Operator removes the duplicate from one list and restarts.

**FAIL-003: Per-request override field has wrong type**
- **Trigger:** API caller sends `"closed_world_filtering": "yes"` (string) or `"closed_world_filtering": 1` (integer) instead of a boolean.
- **Expected behavior:** FastAPI/Pydantic request validation rejects the request with HTTP 422 and a field-level error message indicating the field must be a boolean.
- **User communication:** HTTP 422 Unprocessable Entity with body `{"detail": [{"loc": ["body", "closed_world_filtering"], "msg": "value is not a valid boolean", ...}]}`.
- **Recovery:** Caller corrects the request to send `true` or `false` (JSON boolean).

**FAIL-004: Presidio Analyzer returns a span with an unrecognized entity type**
- **Trigger:** A future Presidio recognizer emits an entity type not in `strong_anchors` or `quasi_identifiers`.
- **Expected behavior:** The span is treated as always-emit (neither list) — it passes through regardless of flag. The filter's set-membership check returns False for both lists; the span is retained. No crash; no error.
- **User communication:** None needed. This is correct behavior (unknown entity types default to always-emit).

**FAIL-005: `strong_anchors` or `quasi_identifiers` contains an unrecognized entity type string**
- **Trigger:** Operator edits `config.yaml` and sets `strong_anchors: ["PEROSN", "EMAIL_ADDRESS"]` (typo). The string `"PEROSN"` is not in the canonical entity-type set.
- **Expected behavior (default `strict_entity_validation: false`):** `Settings` validation emits a startup `WARNING` log line naming the unrecognized type: `WARN: strong_anchors contains unrecognized entity type 'PEROSN' — it will never match a Presidio result; likely a typo`. The application starts and serves requests. The unrecognized type is harmless (it is never in a Presidio result) but silently ineffective.
- **Expected behavior (`strict_entity_validation: true`):** `Settings` validation raises a `ValidationError` at startup listing the unrecognized type(s). Application does not start.
- **User communication:** WARNING log (default) or startup `ValidationError` (strict mode) with field-level detail. Operator corrects the typo and restarts.
- **Recovery:** Operator corrects the entity type name to match the canonical set in `docs/supported-entities.md`.

---

## Implementation Constraints

### Context Requirements

- Maximum context utilization: <40% during implementation.
- Essential files for implementation (exact file:line refs from research):
  - `src/redakt/utils.py:83-108` — `filter_by_entity_thresholds()` and `merge_entity_thresholds()` (precedent for new filter function)
  - `src/redakt/config.py:52-111` — `Settings` class; YAML loading; `entity_score_thresholds` precedent field
  - `src/redakt/routers/detect.py:54-131` — `run_detection()` with filter insertion point at line 119
  - `src/redakt/routers/anonymize.py:48-124` — `run_anonymization()` with filter insertion point at line 116
  - `src/redakt/models/detect.py:10` — `DetectRequest` with `entity_score_thresholds` field (pattern for new field)
  - `src/redakt/models/anonymize.py:10` — `AnonymizeRequest` with same field
  - `config.yaml` — new `closed_world_filtering`, `strong_anchors`, `quasi_identifiers` blocks
  - `tests/eval/_loader.py:21-28` — `Phrase` dataclass (extend with `request_overrides`)
  - `tests/eval/test_calibration.py:30-35` — request body construction (extend to spread `request_overrides`)
- Files that can be delegated to subagents or explored independently:
  - `src/redakt/routers/pages.py` — web UI routes (read-only verify that they call `run_detection`/`run_anonymization`; no changes needed)
  - `docs/customizations.md`, `docs/v1-feature-spec.md`, `docs/supported-entities.md` — documentation updates

### Technical Constraints

- Mirror `entity_score_thresholds` pattern exactly for the per-request override field and merge logic.
- Post-filter MUST run after `filter_by_entity_thresholds()`, per REQ-009.
- `strong_anchors` and `quasi_identifiers` lists are READ-ONLY at request time — use instance values from `Settings` only.
- The filter function must be pure (no side effects, no mutation of the input list).
- Audit logging must receive the suppressed-span count before the result list is returned to the caller — the implementation must compute and forward the count as part of the filter call or immediately after.

---

## Modules

### MODULE-001: Closed-world post-filter function

**Public Interface (decided):**
```python
def filter_by_closed_world(
    results: list[RecognizerResult],
    enabled: bool,
    strong_anchors: frozenset[str],
    quasi_identifiers: frozenset[str],
) -> tuple[list[RecognizerResult], int]:
    """
    Filter quasi-identifier spans when no strong anchor is present.

    Returns a tuple of (filtered_results, suppressed_count).
    - filtered_results: spans to emit (input unchanged when enabled=False or anchor present)
    - suppressed_count: number of spans dropped by the closed-world rule (0 if disabled)

    When enabled=False, returns (results, 0) immediately — O(1) no-op.

    Parameters `strong_anchors` and `quasi_identifiers` are pre-computed frozenset values
    supplied by Settings.strong_anchors_set / Settings.quasi_identifiers_set (computed once
    at config-load). The filter never receives raw lists — callers must not pass list[str].
    """
```
Returns the filtered span list and the count of suppressed spans (`closed_world_suppressed_count`). The caller forwards the count to the audit logger. The function is pure and side-effect-free.

**Return type decision (resolved — no longer ambiguous):** The tuple return `-> tuple[list[RecognizerResult], int]` is the sole specified interface. The alternative (`-> list[RecognizerResult]` + separate `count_quasi_identifiers()` helper) is explicitly rejected for this module. Rationale: `filter_by_entity_thresholds()` (the precedent at `utils.py:97-108`) returns `list[RecognizerResult]` only because it does not need to emit a count — there is no audit requirement for `entity_thresholds_suppressed_count`. This module has an explicit audit requirement (REQ-013) to emit `closed_world_suppressed_count`. The count is an output of the same single-pass O(n) sweep that produces the filtered list; splitting into two functions would require either two passes or sharing mutable state. The tuple is the correct interface. The implementation must NOT use a separate count helper — it must return the tuple. This resolves MODULE-001 return-type ambiguity definitively.

**Hides:**
- The anchor-detection sweep (single O(n) pass computing `{r.entity_type for r in results} ∩ strong_anchors`)
- The suppression predicate (drop span if `entity_type in quasi_identifiers` and no anchor)
- The always-emit semantics for strong anchors and always-emit entities (neither set)
- Edge-case handling: empty span list, all-anchor, all-QI, always-emit-only
- The no-op branch when `enabled=False` (returns input unchanged, count=0)

Note: `strong_anchors` and `quasi_identifiers` are `frozenset[str]` values already at the call site — the function does NOT convert lists to sets internally. That conversion is handled once at config-load by `Settings` (see MODULE-002). Removing this from the function's hidden behavior means the function is a pure frozenset-membership check, not a list-conversion helper.

**Risk:** Medium — over-suppression is a UX bug (missed quasi-identifier redaction when filter should have been off) and under-suppression returns to today's behavior. Neither case is data loss. The pure-function design means failures are locally testable without mocking.

**Location:** `src/redakt/utils.py`, co-located with `filter_by_entity_thresholds`.

**Spec refs:** REQ-007, REQ-008, REQ-009, REQ-013, EDGE-001, EDGE-002, EDGE-003, EDGE-004, EDGE-005, EDGE-008, EDGE-009, EDGE-010, PERF-001, PERF-002, FAIL-004

### MODULE-002: Config schema extension

**Public Interface:** Six new keys in `config.yaml` and six new fields in the Pydantic `Settings` class:
```python
# Core feature fields (REQ-001, REQ-002, REQ-003)
closed_world_filtering: bool = False
strong_anchors: list[str] = [...]  # default set per REQ-001
quasi_identifiers: list[str] = [...]  # default set per REQ-002

# Regulatory and security fields added in fix-iterations (REQ-020, SEC-001a, REQ-011 rule 3)
regulatory_scope: list[str] = ["GDPR"]           # REQ-020: HIPAA incompatibility gate
allow_per_request_closed_world_override: bool = True  # SEC-001a: operator deployment gate
strict_entity_validation: bool = False           # REQ-011 rule 3: typo escalation to ValidationError
```
A Pydantic `@model_validator` enforces:
- REQ-012: no entity type may appear in both lists (`ValidationError` on conflict).
- REQ-011: valid `list[str]` for both lists; canonical-set check per `entity_catalog.py` (`WARNING` or `ValidationError` per `strict_entity_validation`).
- REQ-020: when `"HIPAA"` in `regulatory_scope` AND `closed_world_filtering: true` → `ValidationError` at startup.
- REQ-020: when `"HIPAA"` in `regulatory_scope` → auto-force `allow_per_request_closed_world_override = false`.

**Hides:** Pydantic validation rules, default-value materialization, the inline-comment text per REQ-010, set-precomputation of `strong_anchors` and `quasi_identifiers` as `frozenset[str]` values via `Settings.strong_anchors_set` and `Settings.quasi_identifiers_set` (computed once at config-load — mandatory per PERF-001, not optional; eliminates per-call list-to-set conversion). **Caching mechanism:** implemented as Pydantic v2 `@computed_field` with `@cached_property` semantics, OR as a private attribute populated by `@model_validator(mode='after')`. Plain `@property` is forbidden — it recomputes the frozenset on every access, defeating PERF-001. EDGE-007 (overlap ValidationError), FAIL-005 (unrecognized type warning/ValidationError path), SEC-002 (threat-model config comment verbatim text per REQ-010).

**Risk:** High — contains REQ-020 HIPAA enforcement gate; failure has regulatory exposure. A bug in the HIPAA auto-force logic would silently permit a HIPAA-scoped deployment to enable CWF or allow per-request CWF activation, violating Safe Harbor (45 CFR §164.514(b)). [Post-implementation spec adjustment 2026-05-13: risk tier corrected from Low to High per code review REVIEW-008 misclassification flag MODULE-002.]

**Spec refs:** REQ-001, REQ-002, REQ-003, REQ-010, REQ-011, REQ-012, REQ-016, REQ-017, REQ-020, EDGE-007, SEC-001a, SEC-002, FAIL-001, FAIL-002, FAIL-005

### MODULE-003: Per-request override threading

**Public Interface:** One new optional field per endpoint request model:
```python
# src/redakt/models/detect.py and src/redakt/models/anonymize.py
closed_world_filtering: bool | None = None
```
Plus updated `run_detection()` and `run_anonymization()` signatures per REQ-019:
```python
def run_detection(..., closed_world_filtering: bool | None = None, ...) -> DetectionResult:
def run_anonymization(..., closed_world_filtering: bool | None = None, ...) -> AnonymizationResult:
```
Merge logic (REPLACE semantics) resolves the effective boolean from the per-request value and the instance default.

**Hides:** Request-vs-instance-default merge semantics (REPLACE for the boolean), the wiring from request model field → function parameter → `filter_by_closed_world()` call → audit log fields (both `closed_world_suppressed_count` AND `closed_world_filtering_override`).

The `closed_world_filtering_override` audit field requires threading the raw per-request field value (not the resolved effective value) from the request model through to the audit logger. Specifically:
- If the caller set `closed_world_filtering: true` or `closed_world_filtering: false` explicitly in the request body, `closed_world_filtering_override` is `true` or `false` respectively.
- If the caller omitted the field (or sent `null`), `closed_world_filtering_override` is `null`.
- This raw value must be captured before the REPLACE merge resolves it into the effective boolean — the audit field records caller intent, not the resolved outcome.
- When `allow_per_request_closed_world_override: false` (SEC-001a), the per-request field is silently ignored; `closed_world_filtering_override` is still recorded as `null` (the caller's intent was overridden, not honored).

**Risk:** Medium — request-handling changes have potential for regression on the parity-with-today (flag off) case. The new field is `Optional` with a default of `None`, so existing callers that omit the field are unaffected.

**Spec refs:** REQ-004, REQ-005, REQ-006, REQ-013, REQ-018, REQ-019, EDGE-006, FAIL-003, COMPAT-001, SEC-001, SEC-001a, SEC-003

### MODULE-004: Audit logging extension

**Public Interface:** `log_detection()` and `log_anonymization()` (SPEC-006 audit logging) gain two new parameters:

```python
def log_detection(
    ...,
    closed_world_suppressed_count: int = 0,
    closed_world_filtering_override: bool | None = None,
) -> None: ...

def log_anonymization(
    ...,
    closed_world_suppressed_count: int = 0,
    closed_world_filtering_override: bool | None = None,
) -> None: ...
```

The routers pass:
- `closed_world_suppressed_count`: the integer count returned by `filter_by_closed_world()` (0 when disabled or no suppression; `null` for document-upload path per REQ-013 document-path sentinel).
- `closed_world_filtering_override`: the raw per-request boolean (or `None` if omitted/null), captured by MODULE-003 before REPLACE merge resolves the effective flag. This is `null` for document-upload path.

The audit entry always includes both fields. For document-upload path: both are `null` (sentinel).

**Hides:** The field serialization format in the audit entry (consistent with SPEC-006 audit entry schema), the always-present-even-when-zero behavior for `closed_world_suppressed_count` (callers need not check whether to pass 0 or omit it), the always-present-even-when-null behavior for `closed_world_filtering_override`.

**Risk:** Low — SPEC-006's existing audit schema is extended with two new fields. No PII involved. Both fields carry only metadata (counts and boolean flags). If SPEC-006's `log_detection` / `log_anonymization` functions are not easily extensible, the implementation may need to read SPEC-006 more carefully; this is a minor coupling risk.

**Spec refs:** REQ-013, SEC-001 (sub-clause d), SEC-001a, SPEC-006 §SEC-001 (PII-never-logged constraint — external ref)

### MODULE-005: Eval-loader extension

**Public Interface:** Extended `Phrase` dataclass:
```python
@dataclass
class Phrase:
    text: str
    language: str
    expect: list[str]
    expect_clean: bool
    notes: str
    fixture: str
    request_overrides: dict[str, Any] | None = None  # NEW
```
YAML loader collects unrecognized keys into `request_overrides`. Test runner merges `request_overrides` into the POST body when non-None.

**Hides:** Key-collection logic in the YAML loader, the merge step in `test_calibration.py`, the `Any` typing for forward-compatibility with future per-fixture fields.

**Risk:** Low — the eval runner is test-only code; failures surface as test errors, not production bugs. The new field is backwards-compatible (existing fixtures that omit `request_overrides` get `None`, and the merge step is a no-op for `None`).

**Justification (shallow by intent):** MODULE-005 is a thin seam, not a deep module — its "Hides" list covers trivial key-collection and merge logic. This shallowness is intentional: MODULE-005 is a forward-compat seam for future per-fixture request parameters; it would be re-implemented as a more general fixture-overrides mechanism in v2 if per-fixture overrides expand to cover additional request fields.

**Spec refs:** REQ-014

---

## Validation Strategy

### Automated Testing

#### Unit Tests (target: at least one test per REQ and per EDGE)

- [ ] Flag on, anchor absent, quasi-identifiers in span list → all quasi-identifiers suppressed, anchors absent (REQ-007, EDGE-002)
- [ ] Flag on, PERSON anchor present + quasi-identifiers → all spans retained (REQ-007, REQ-008)
- [ ] Flag on, EMAIL_ADDRESS anchor present + DATE_TIME → both retained (REQ-007, REQ-008 — email counts as anchor)
- [ ] Flag off (default) → all spans pass through unchanged (COMPAT-001, PERF-002)
- [ ] Flag on, only strong-anchor spans, no quasi-identifiers → all retained (REQ-008, EDGE-003)
- [ ] Flag on, mixed strong anchors + quasi-identifiers + always-emit entities → all pass (EDGE-010)
- [ ] Flag on, empty span list → `[]` returned, no crash (EDGE-001)
- [ ] Flag on, only always-emit entities (DE_BSNR) → DE_BSNR retained (EDGE-004)
- [ ] Per-request override: instance=False, request=True → quasi-identifiers suppressed (REQ-004, EDGE-006)
- [ ] Per-request override: instance=True, request=False → all spans pass (REQ-005, EDGE-006)
- [ ] Per-request override: request=None → instance default applies (REQ-004, REQ-005)
- [ ] `strong_anchors` empty + flag on → all quasi-identifiers always suppressed (EDGE-008)
- [ ] `quasi_identifiers` empty + flag on → no suppression; filter is no-op (EDGE-008)
- [ ] Suppressed count returned correctly: 2 quasi-identifier spans suppressed → count=2 (REQ-013)
- [ ] No suppression → count=0 (REQ-013)
- [ ] Config: non-list `strong_anchors` raises `ValidationError` at startup (REQ-011, FAIL-001)
- [ ] Config: non-string element in `quasi_identifiers` raises `ValidationError` (REQ-011, FAIL-001)
- [ ] Config: entity in both `strong_anchors` and `quasi_identifiers` raises `ValidationError` (REQ-012, FAIL-002)
- [ ] Request: `closed_world_filtering: "yes"` raises HTTP 422 with field error (FAIL-003)
- [ ] Config: unrecognized entity type `"PEROSN"` in `strong_anchors` with `strict_entity_validation: false` → WARNING logged, service starts (FAIL-005)
- [ ] Config: unrecognized entity type with `strict_entity_validation: true` → `ValidationError` at startup (FAIL-005)
- [ ] Config: `regulatory_scope: ["HIPAA"]` + `closed_world_filtering: true` → `ValidationError` at startup (REQ-020)
- [ ] Config: `regulatory_scope: ["HIPAA"]` + `closed_world_filtering: false` + `allow_per_request_closed_world_override: true` → `allow_per_request_closed_world_override` auto-forced to `false` at config-load; INFO log line present (REQ-020, SEC-001a)
- [ ] SEC-001a gate: `allow_per_request_closed_world_override: false` + per-request `closed_world_filtering: true` → request value silently ignored; effective = instance default; `closed_world_filtering_override` audit field = `null` (SEC-001a, REQ-013)
- [ ] MODULE-001 tuple return: function returns `tuple[list[RecognizerResult], int]` shape; suppressed-count is the second element, not a side-channel (MODULE-001 interface contract)
- [ ] REQ-017 escape hatch: `quasi_identifiers: ["DATE_TIME", "LOCATION", "DE_PLZ"]` (NRP removed) + flag on → NRP spans always emitted regardless of anchor presence (REQ-017)
- [ ] CI lint: `tests/unit/test_entity_catalog.py` asserts entity in `docs/supported-entities.md` but not in `CANONICAL_ENTITY_TYPES` → test fails (REQ-021, REQ-011 canonical-set source-of-truth)
- [ ] CI lint: entity in `CANONICAL_ENTITY_TYPES` but not in `docs/supported-entities.md` → test fails (REQ-021)
- [ ] CI lint: entity in `docs/supported-entities.md` with invalid `classification:` value (not `strong_anchor`, `quasi_identifier`, or `always_emit`) → test fails (REQ-021)
- [ ] PERF-001 caching: `Settings.strong_anchors_set` and `Settings.quasi_identifiers_set` are `frozenset` at the call site AND do not recompute on repeated access (benchmark: 1000 sequential accesses produce O(1) constant-time lookup with no per-access frozenset construction) (PERF-001 set pre-computation)

#### Integration Tests

- [ ] `/api/detect` with flag on (config) + weather query → `has_pii: false` (REQ-007, COMPAT-001 inverse)
- [ ] `/api/detect` with flag on + named-person treatment text → quasi-identifiers present in result (REQ-007, REQ-008)
- [ ] `/api/anonymize` parity: same suppression behavior as `/api/detect` on identical inputs (REQ-005, REQ-009)
- [ ] Per-request override in request body overrides config default in both directions (REQ-004, REQ-005)
- [ ] Allow-list-stripped anchor → quasi-identifiers suppressed when flag on (EDGE-005) — integration test against mocked Presidio returning no PERSON span
- [ ] Audit entry includes `closed_world_suppressed_count: 2` when 2 spans are suppressed (REQ-013, MODULE-004)
- [ ] Audit entry includes `closed_world_suppressed_count: 0` when filter is off (REQ-013)
- [ ] Audit entry includes `closed_world_filtering_override: true` when per-request override was sent as `true` (REQ-013)
- [ ] Audit entry includes `closed_world_filtering_override: null` when per-request field was omitted (REQ-013)
- [ ] Audit entry includes `closed_world_filtering_override: null` when SEC-001a silently ignored the per-request value (REQ-013, SEC-001a)
- [ ] Document-upload path (`/api/documents/upload`) with `closed_world_filtering: true` in config → endpoint behavior unchanged; `closed_world_suppressed_count` is `null` (not `0`) in audit entry (REQ-015)
- [ ] Web UI submit routes (`pages.py:53`, `pages.py:123`) use instance default and do not accept per-request `closed_world_filtering` toggle (REQ-018)

#### Eval Fixtures (`tests/eval/fixtures/closed_world.yaml` — new file)

- [ ] Munich weather query, flag on: `expect_clean: true` (EDGE-009 inverse — anchor absent, suppression fires, all clean)
- [ ] Stefan Berger treatment, flag on: `expect: [PERSON, LOCATION, DATE_TIME]` (REQ-007, REQ-008 — anchor present, quasi-IDs retained)
- [ ] PV invoice with PERSON + EMAIL_ADDRESS + PHONE_NUMBER + IBAN_CODE, flag on: `expect: [PERSON, EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE]`
- [ ] Healthcare gameable narrative, flag on: `expect_clean: true` (EDGE-009 — anchor free, quasi-IDs pass; `expect_clean` because no entity is detected after suppression)
- [ ] German weather query (`"Wie wird das Wetter am 15. Mai in München?"`), flag on: `expect_clean: true`
- [ ] DE_PLZ in address-lookup context, flag on: `expect_clean: true`

Note: these fixtures require the eval-loader extension (REQ-014 / MODULE-005) to pass `closed_world_filtering: true` per-fixture via `request_overrides`.

#### Performance Validation

- [ ] Benchmark: 100-span document, flag on → filter overhead < 1ms (PERF-001)
- [ ] Benchmark: 100-span document, flag off → O(1) no-op path (PERF-002)
- [ ] Benchmark: 10,000-span document, flag on → filter completes (no timeout / crash); latency outside 1ms guarantee but must not block event loop (PERF-001 tail behavior)
- [ ] Benchmark: set pre-computation at config-load → `strong_anchors_set` and `quasi_identifiers_set` are `frozenset` (not `list`) at the point `filter_by_closed_world()` is called (PERF-001 set pre-computation)

### Manual Verification

- [ ] Set `closed_world_filtering: true` in config.yaml; verify Munich weather query returns empty result via `curl /api/detect`.
- [ ] Set `closed_world_filtering: false` in config.yaml; verify per-request override `{"closed_world_filtering": true}` suppresses quasi-identifiers on same query.
- [ ] Verify config-comment text is preserved verbatim in `config.yaml` (REQ-010).
- [ ] Verify HTTP 422 on malformed `closed_world_filtering` value (FAIL-003).

### Stakeholder Sign-off

- [ ] **Operator (Pablo / Memodo):** Acknowledge the Art. 9 operator responsibility for NRP suppression per REQ-017 — confirm that enabling closed-world filtering for NRP in `quasi_identifiers` is a deliberate decision, and that the Art. 9 lawful basis will be documented separately in Memodo's RoPA if the flag is enabled in production. The privacy specialist gate is resolved by spec position (REQ-017); no further panel confirmation required.
- [ ] **Product (Pablo / Memodo PV team):** Accept Munich-weather and Stefan-Berger acceptance examples as behavioral specification.
- [ ] **Engineering:** Code review at Step 4b covers MODULE-001 through MODULE-005.
- [ ] **Engineering / Security review at Step 4b:** Verify SEC-001 (a)–(d) implementation matches the trust-model framing — specifically the SEC-001a config gate, the audit-field threading per REQ-013, and the REQ-020 HIPAA per-request auto-force. The panel has signed off; this is a code-review checklist item, not a panel gate.

---

## Dependencies and Risks

### External Dependencies

None new. Inherits from existing Presidio/FastAPI/Pydantic stack. `filter_by_closed_world()` has no external dependencies beyond the standard Python `set` operations.

### Identified Risks

**RISK-001: Over-suppression (false negatives in noisy-redaction reduction)**
Manifestation: filter suppresses quasi-identifiers that should have been emitted (e.g., operator has a non-standard strong anchor type not in the default list, so the anchor check never fires).
Mitigation: (a) default-off flag — over-suppression is impossible if the flag is not enabled; (b) per-request override allows callers to disable suppression for individual requests; (c) eval fixtures with anchor-present assertions catch regressions; (d) `closed_world_suppressed_count` in audit log makes suppression visible to operators.

**RISK-002: Gameable rule — anchor-free joinable PII passes through**
Manifestation: a narrative like `"Treatment confirmed for May 13, 2026 at the Munich clinic."` carries no PERSON anchor; quasi-identifiers pass through under the closed-world filter.
Mitigation: documented in ADR-0007 as accepted for B2B PV workflows; spec EDGE-009 acknowledges explicitly; eval fixture covers the healthcare-style case. Operators deploying in healthcare or social-services contexts must not enable the flag.

**RISK-003: Allow-list interaction surprises operators**
Manifestation: operator adds `"Stefan Berger"` to the allow list, enabling `closed_world_filtering`; quasi-identifiers in "Stefan Berger's invoice" are suppressed because the PERSON span is stripped before the anchor check.
Mitigation: documented in EDGE-005; `docs/customizations.md` update required; the behavior is intentional (allow-list semantics take precedence).

**RISK-004: NRP residual Art. 9 risk (resolved position — NRP retained as quasi-identifier)**
Manifestation: an operator enables `closed_world_filtering: true` with NRP in `quasi_identifiers` (the default), suppressing NRP mentions in anchor-free submissions. If the downstream system later uses that NRP text in a profiling or decision context, the operator has lost the GDPR Art. 9 audit trail that Redakt's PII detection was meant to surface.
Mitigation: REQ-017 takes a decisive position (NRP is retained in `quasi_identifiers`) with a mandatory operator responsibility clause — operators enabling NRP suppression must document their Art. 9 lawful basis separately in their RoPA. Redakt's `closed_world_suppressed_count` audit field does not satisfy Art. 9 record-keeping. Operators who cannot accept the residual Art. 9 risk must move `NRP` to the always-emit set (neither list) — a single-line config change. The implementation can treat NRP classification as operator-configurable with no code change required. The panel-gate ("privacy specialist must confirm") is removed from the spec; this risk is accepted with the documented mitigations.

**RISK-005: Audit logging coupling to SPEC-006**
Manifestation: `log_detection()` / `log_anonymization()` function signatures in SPEC-006 are not easily extensible; adding `closed_world_suppressed_count` requires non-trivial refactoring.
Mitigation: if the SPEC-006 audit functions are not easily extensible, the implementation may log the count as an additional structured field in the existing audit entry dict (not a new parameter) — this is a SPEC-006 schema extension, not a function signature change.
**Step 4 pre-implementation check (required):** Before implementing MODULE-004, verify that SPEC-006's `log_detection()` and `log_anonymization()` accept signature extension (via `**kwargs` or explicit additional parameters). If SPEC-006 declares a closed/frozen function signature, MODULE-004's design must change first (dict-field extension fallback). Do not skip this check — a closed SPEC-006 signature makes MODULE-004's specified interface unimplementable as drawn.

---

## Implementation Notes

### Suggested Approach

The filter is straightforward: add `filter_by_closed_world()` to `src/redakt/utils.py` after `filter_by_entity_thresholds()` (lines 97-108). The function body is approximately 10 lines (the research sketch is complete and accurate). The config extension adds three fields to `Settings` with a Pydantic validator for overlap detection. The request model extension adds one optional field per model. The router wiring adds the merge logic (4 lines) and the `filter_by_closed_world()` call at `detect.py:120` and `anonymize.py:117`. The audit logging extension threads the suppressed count from the filter call to `log_detection()` / `log_anonymization()`.

The eval-loader extension (MODULE-005) is the most structurally novel change — it requires touching `tests/eval/_loader.py`, `tests/eval/test_calibration.py`, and adding `tests/eval/fixtures/closed_world.yaml`. The diff is small but affects the test runner for all existing eval fixtures; regression-test all existing eval fixtures after the change.

### API Versioning Posture

Redakt currently has no versioned API surface (no `/v1/api/detect`). The `closed_world_filtering` field is introduced as a new optional request field on an unversioned endpoint. v2 additions (`strong_anchors_add` / `strong_anchors_remove` MERGE-BY-DIFF semantics) are backwards-compatible additive fields — old clients that omit them retain current behavior. If v3+ semantics require breaking changes to the request model, a versioning discussion and API version bump will be required at that time. This posture is acknowledged and accepted for v1; no API versioning change is required as part of this feature.

### Areas for Subagent Delegation

- Verification of the `run_detection()` and `run_anonymization()` exact signatures (to confirm the `entity_score_thresholds` pattern at lines 54 and 48) — a read-only Explore subagent can confirm without burning implementation budget.
- Config comment text drafting — the REQ-010 verbatim text is already specified; no delegation needed.
- `docs/customizations.md`, `docs/v1-feature-spec.md`, and `docs/supported-entities.md` update content — can be drafted by a documentation subagent after the implementation is complete.

### Critical Implementation Considerations

1. Filter MUST be co-located with `filter_by_entity_thresholds()` in `src/redakt/utils.py` (ADR-0007 §Decision item 4).
2. Strong anchors are emitted regardless of flag state (REQ-008) — the no-anchor branch only suppresses quasi-identifier spans, never strong-anchor spans.
3. Per-request override uses REPLACE semantics for the boolean (EDGE-006) — no merge, no fallback chain; non-None request value wins unconditionally. If `allow_per_request_closed_world_override: false` (SEC-001a), the request field is silently ignored before REPLACE logic runs.
4. Audit logging must receive the suppressed count and override flag value (REQ-013) — both must be forwarded to `log_detection()` / `log_anonymization()`.
5. The eval-loader extension is a Phase 1 deliverable — the `closed_world.yaml` fixtures cannot run without it; it must be implemented in the same chunk as the filter.
6. The document-upload path (`document_processor.py:182`) is explicitly out-of-scope (REQ-015) — no code changes in `documents.py` or `document_processor.py` in v1.
7. `filter_by_closed_world()` receives `frozenset[str]` values for `strong_anchors` and `quasi_identifiers` (pre-computed by `Settings` at config-load per PERF-001 set pre-computation requirement), not raw `list[str]`.
8. `filter_by_closed_world()` depends on `RecognizerResult.entity_type` attribute name (Presidio SDK ≥ 2.x). Re-validate this attribute name on any Presidio major version bump.

---

## Glossary Delta (new terms for UBIQUITOUS_LANGUAGE.md)

No new terms needed. All canonical terms (`strong anchor`, `quasi-identifier`, `closed-world assumption`, `closed-world filtering`, `post-filter`, `per-request override`) are already in `SDD/UBIQUITOUS_LANGUAGE.md` as of the Step 2a-2 glossary update (2026-05-13). The spec uses all six terms consistently with their glossary definitions.

The following existing glossary terms are directly exercised by this spec:
- **strong anchor** — REQ-001, MODULE-001
- **quasi-identifier** — REQ-002, MODULE-001
- **closed-world assumption** — REQ-010, SEC-002, ADR-0007 reference
- **closed-world filtering** — REQ-003, REQ-007, MODULE-001
- **post-filter** — REQ-009, MODULE-001
- **per-request override** — REQ-004, REQ-005, MODULE-003
