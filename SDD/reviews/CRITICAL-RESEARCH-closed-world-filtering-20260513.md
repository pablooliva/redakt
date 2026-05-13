# Research Critical Review: closed-world-filtering

**Reviewer:** sdd-critical-reviewer (Opus, adversarial)
**Target:** `SDD/research/RESEARCH-008-closed-world-filtering.md`
**Date:** 2026-05-13
**Mode:** Autonomous; `--skip-clarify` set

## Executive Summary

**Design Concept Fidelity gate: skipped** — `--skip-clarify` was explicitly set by the user invocation. No CLARIFICATION-008 artifact exists. The user's design concept was externalized via the task description itself (which contained acceptance examples, out-of-scope items, and explicit trade-offs). Downstream cost of this skip is bounded by the task description's crispness; if the spec phase surfaces ambiguity that the task description did not resolve, that is the cost being absorbed here.

The research is well-organized, internally consistent, and correctly anchored to ADR-0007. Line-number citations (`detect.py:119`, `anonymize.py:116`, `utils.py:97-108`, `config.py:57`, `models/detect.py:10`) verify against the current codebase. It correctly captures the gameability acceptance, threat model, allow-list interaction edge, HIPAA-Safe-Harbor incompatibility, and the existing `entity_score_thresholds` precedent.

**However, the research contains three HIGH-severity blind spots that will derail the spec phase if not addressed**: (1) it inventories four call sites for the post-filter but **misses a fifth: the document-upload pipeline** in `src/redakt/services/document_processor.py`, which bypasses both `filter_by_entity_thresholds` and the new filter entirely; (2) the `strong_anchors` default list **omits roughly half of the Presidio German country recognizers** without rationale; and (3) the unresolved `DE_STEUER_ID` vs. `DE_TAX_ID` discrepancy is logged as an "open question" rather than treated as an ADR-0007 amendment that must precede spec adoption.

**Verdict: REVISE BEFORE PROCEEDING.**

## Overall Severity

**HIGH** (3 HIGH, 5 MEDIUM, 3 LOW)

---

## Critical Gaps Found

### 1. **Missing call site: `/api/documents/upload` and the document-processing pipeline** (HIGH)

- **Evidence:** Research §System Data Flow lists "four call sites" (`/api/detect`, `/api/anonymize`, web `/detect/submit`, web `/anonymize/submit`) covered by inserting the filter inside `run_detection()` and `run_anonymization()`. But `src/redakt/routers/documents.py:62` (`POST /api/documents/upload`) and `src/redakt/routers/pages.py:180` (`POST /documents/submit`) **do not call `run_detection` or `run_anonymization`** — they go through `process_document()` at `src/redakt/services/document_processor.py:182`. Inspecting `document_processor.py:250-272`: it calls `presidio.analyze()` per chunk, applies `resolve_overlaps()`, then builds the unified placeholder map. **No call to `filter_by_entity_thresholds` exists in this path either**, which means `entity_score_thresholds` already doesn't apply to documents today (pre-existing inconsistency the research could have surfaced but didn't).
- **Risk:** Under the research's design, enabling `closed_world_filtering: true` will silently NOT apply to document uploads. A user pasting `"What is the weather in Munich on May 13, 2026?"` into the detect UI sees zero PII; uploading the same string in a `.txt` file still flags `LOCATION` and `DATE_TIME`. Operator confusion; documented behavior contradicted by reality. Worse: this is exactly the "per-chunk analysis" scenario the research's own threat-model section flags as breaking the closed-world assumption ("A PERSON in chunk 1 does not suppress quasi-identifiers in chunk 3"). The fact that this scenario is a real shipping code path — not just a theoretical concern — is not acknowledged.
- **Recommendation:** The spec phase must explicitly decide one of three options: (a) extend the filter into `process_document()` after the chunk-level analyze (which then forces a decision: is the anchor-presence check per-chunk or document-global?); (b) explicitly out-of-scope the document path with a documented rationale and an operator-facing note; (c) reach into the existing pre-existing `entity_score_thresholds` gap and unify both filters into a shared `apply_post_filters(results, settings, overrides)` helper used by all three pipelines. Option (c) is the cleanest architectural answer but the largest change. The research should explicitly enumerate this trade-off rather than silently inheriting the gap.

### 2. **`strong_anchors` default list is materially incomplete relative to the actual recognizer catalog** (HIGH)

- **Evidence:** The research's `strong_anchors` default at lines 175-191 lists 15 entities. The German country recognizers in `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/country_specific/germany/` define at least 19 distinct DE_* entity types: `DE_BSNR`, `DE_EEG_ANLAGE`, `DE_FUEHRERSCHEIN`, `DE_HANDELSREGISTER`, `DE_HEALTH_INSURANCE`, `DE_ID_CARD`, `DE_KFZ`, `DE_LANR`, `DE_MALO`, `DE_MASTR_ID`, `DE_MELO`, `DE_PASSPORT`, `DE_PLZ`, `DE_SOCIAL_SECURITY`, `DE_TAX_ID`, `DE_TAX_NUMBER`, `DE_VAT_ID`, `DE_ZAEHLERNUMMER`. The research includes 7 of these in `strong_anchors`. **The omissions are not flagged or justified**: `DE_FUEHRERSCHEIN` (driver's license — unambiguously identifies a natural person), `DE_SOCIAL_SECURITY` (RVNR — unambiguous person identifier), `DE_TAX_NUMBER` (Steuernummer — business/person identifier), `DE_LANR` (lifetime doctor number — strong professional identifier), `DE_BSNR` (practice/clinic identifier, weaker), `DE_HANDELSREGISTER` (company identifier; quasi at best), `DE_MELO` / `DE_MALO` / `DE_EEG_ANLAGE` / `DE_ZAEHLERNUMMER` (asset/installation identifiers; quasi at best, but in the energy-sector PV domain this is non-trivial). Open-question #3 acknowledges incompleteness for "DE_KFZ classification is borderline" but only that one. ADR-0007 says "plus any other identifier-grade types in the current ruleset" — the research's job was to enumerate that catalog and propose a classification for each. It did not.
- **Risk:** Spec ships with a half-complete default list. Operators enabling the flag will get inconsistent behavior: a submission with `"Stefan Berger's driver license is B072RRE2I35"` will flag `PERSON + DE_FUEHRERSCHEIN` but the absence of `DE_FUEHRERSCHEIN` from `strong_anchors` means a future `"DE_FUEHRERSCHEIN: B072RRE2I35, address Munich May 13"` will suppress `LOCATION + DATE_TIME` despite the driver's license being a strong anchor. This is a correctness bug, not a tuning concern. The omitted `DE_SOCIAL_SECURITY` (Rentenversicherungsnummer) is even more egregious — it's a direct natural-person identifier that any reasonable operator would assume is in `strong_anchors`.
- **Recommendation:** Spec phase must enumerate ALL DE_* (and EU_* / generic) entity types from the actual recognizer catalog (using `grep "supported_entity" presidio/.../country_specific/germany/`) and classify each into `strong_anchors`, `quasi_identifiers`, or "always-emit (neither list)". The classification must include a one-line rationale per entity. The research's current 4-bullet open-question #3 is insufficient — it should have been a table.

### 3. **`DE_STEUER_ID` vs. `DE_TAX_ID`: blocking ADR-0007 amendment, not "open question"** (HIGH)

- **Evidence:** ADR-0007 line 41 says `DE_STEUER_ID`. The research (lines 181, 201, 238, 357) correctly identifies that the codebase uses `DE_TAX_ID` everywhere (verified: `tests/eval/fixtures/de.yaml:5`, `tests/eval/fixtures/generic.yaml:114`, `docs/supported-entities.md:71`, `presidio/presidio-analyzer/.../de_tax_id_recognizer.py:57`). The research logs it as "Open Question #1 for Planning" and proposes "canonicalize on `DE_TAX_ID`". But ADR-0007 is the authoritative architectural decision and **the research itself states "No revisions needed to ADR-0007"** at line 162.
- **Risk:** If ADR-0007 is treated as authoritative and not amended, the spec will inherit the wrong identifier. If the spec phase deviates from ADR-0007 without amending the ADR, the ADR becomes stale documentation and the SDD chain-of-custody breaks. Either ADR-0007 needs an in-place edit (acceptable for status `Proposed`) or a superseding ADR-0008 needs to be created. The "open question" framing dodges this responsibility.
- **Recommendation:** Step 2d (fix-research) should explicitly amend ADR-0007 in place — its status is `Proposed`, so direct edit is appropriate. The amendment is a single token: `DE_STEUER_ID` → `DE_TAX_ID`. The research's "no revisions needed" claim at line 162 should be retracted and replaced with "ADR-0007 amended in place: DE_STEUER_ID → DE_TAX_ID, justified by codebase canonical naming." Failing to do this hands the spec a false dichotomy ("which name wins?") that has already been answered.

### 4. **Per-request override semantics for entity-class lists not specified** (MEDIUM)

- **Evidence:** Research §Per-request override (lines 204-219) defines per-request override only for the scalar boolean `closed_world_filtering`. The merge formula is replace-when-non-None. But ADR-0007 says "Expose a per-request override knob mirroring how `entity_score_thresholds` works today, so callers (and future agent integrations) can re-tighten without flipping the global default." The "knob" in `entity_score_thresholds` is a *map* with merge-by-key (research line 83-94, verified at `utils.py:91-93`). The research does not specify whether `strong_anchors` and `quasi_identifiers` are also per-request overridable, nor whether their override semantics is REPLACE (entire list) or MERGE (union / per-key delete). This was explicitly flagged as a possible HIGH finding in the review prompt.
- **Risk:** Spec phase will argue. An agent integration that wants to add `LOCATION` to strong_anchors for one request has no defined path. Worse: an operator using closed-world for invoice text but per-request relaxing it for one chatbot subroute has no clear API.
- **Recommendation:** Spec must explicitly decide. Recommended posture: keep `strong_anchors` and `quasi_identifiers` instance-only for v1 (no per-request override). Justify by symmetry with `allow_list` (instance-level list, per-request appends) only if the spec intends the same merge semantics. Otherwise, document that v1 explicitly does not allow per-request entity-class list overrides and that future iterations may add them with documented merge semantics.

### 5. **Audit logging interaction underspecified** (MEDIUM)

- **Evidence:** Research open-question #6 says "The entity types/counts logged reflect the post-filter state. This is correct behavior (we log what was surfaced to the caller). No change needed." Verified at `src/redakt/routers/detect.py:157` and `src/redakt/routers/anonymize.py:151`: `log_detection` and `log_anonymization` run AFTER `filter_by_entity_thresholds`, so per the research's filter placement they will also run after the new closed-world filter. The audit entries (per `SPEC-006` REQ-012 at line 86 of `SDD/requirements/SPEC-006-audit-logging.md`) include `entity_count` and `entities_found`. **Under closed-world suppression, both will read zero for a submission that Presidio originally flagged with 5 spans.** The compliance officer has no audit trail of what closed-world dropped.
- **Risk:** Two failure modes: (a) compliance audit becomes blind to suppression activity — a GDPR DPA asking "what fraction of submissions had quasi-identifiers suppressed?" cannot be answered from logs; (b) a misconfigured `strong_anchors` list silently drops detections without any operator-visible signal. The research's "no change needed" defense ("we log what was surfaced to the caller") is one defensible answer, but it is not the only defensible answer — the alternative (log pre-filter + post-filter counts, or log a `closed_world_suppressed_count` field) is at least worth considering and explicitly rejecting.
- **Recommendation:** Spec must explicitly decide. If "no change" stays the answer, it must justify against a hypothetical compliance audit. If a `closed_world_suppressed_count` (or `closed_world_suppressed_types` deduped list) audit field is added, SPEC-006 SEC-001 ("Audit log entries never contain PII") must be re-verified — entity type names are not PII so this is fine. The decision needs to be a documented choice, not a silent default.

### 6. **Eval-suite loader extension specified as "open question," not designed** (MEDIUM)

- **Evidence:** Research §Eval-suite fixtures shows fixtures with `closed_world_filtering: true` per-entry. Open-question #2 acknowledges "the existing eval loader (`tests/eval/_loader.py`) and test runner (`tests/eval/test_calibration.py`) don't have a per-fixture override mechanism for boolean flags." Verified: `tests/eval/_loader.py:21-28` defines `Phrase(text, language, expect, expect_clean, notes, fixture)` and `tests/eval/test_calibration.py:30-35` constructs the request body as `{"text": phrase.text, "language": phrase.language}` — no per-fixture flag injection mechanism exists.
- **Risk:** The spec inherits an underspecified test mechanism. The proposed `tests/eval/fixtures/closed_world.yaml` cannot actually run without a loader change.
- **Recommendation:** Spec must commit to a specific approach. Recommended: extend `Phrase` with an optional `request_overrides: dict[str, Any] | None = None` field (more general than just a `closed_world_filtering` bool — supports future per-fixture flag toggles too). Loader reads any keys not in the existing schema as request_overrides. Test runner merges them into the POST body. The research's "this is an open question" should have been "this is the proposed loader extension, here is the diff sketch."

### 7. **Web-UI submit paths do not pass per-request overrides** (MEDIUM)

- **Evidence:** Verified at `src/redakt/routers/pages.py:53-59` (detect_submit) and `pages.py:123-129` (anonymize_submit): the form-based web UI submit routes do not pass `entity_score_thresholds` or any per-request override into `run_detection` / `run_anonymization`. So the existing per-request override pattern is API-only; the web UI inherits only the instance defaults. The research does not address whether `closed_world_filtering` should be exposed as a form field in the web UI or remain API-only.
- **Risk:** A web-UI operator cannot turn closed-world filtering off for a one-shot submission. Either acceptable (instance-default suffices for UI) or a gap (operator wants per-paste control). The research doesn't acknowledge this asymmetry.
- **Recommendation:** Spec must explicitly state: "The web UI uses the instance default only; per-request override is API-only" or "The web UI exposes a toggle for closed-world filtering" with a rationale.

### 8. **Stakeholder coverage thin: GDPR/legal not consulted** (MEDIUM)

- **Evidence:** Research §Stakeholder Mental Models lists operator (Pablo), engineering, end-user, and future agent integration. Notably absent: **GDPR compliance perspective**. The research's HIPAA Safe Harbor incompatibility analysis is thoughtful, but GDPR itself has Art. 5(1)(c) (data minimization) and Art. 9 (special categories — including NRP which is classified as a quasi-identifier and includes religious / political / health-adjacent attributes). A GDPR-aware perspective would ask: "Under what conditions does an off-by-default closed-world filter constitute appropriate data minimization?" and "Does suppressing NRP under a closed-world assumption interact with Art. 9 categorical protections?" The research treats `NRP` casually in open-question #5 ("NRP in isolation does not identify a natural person") — but Art. 9 doesn't require identifiability for some of its scope.
- **Risk:** A compliance officer reviewing this design might flag the NRP-as-quasi-identifier classification as inappropriate under Art. 9. The closed-world flag relaxes protection conditional on the operator's threat-model judgment — but if the operator misjudges, the resulting GDPR exposure is on Redakt.
- **Recommendation:** Spec must include an explicit Art. 9 note for NRP. Recommended posture: NRP is always-emit (move out of `quasi_identifiers`) by default, with operator override available. This is a defensible compliance posture even if the closed-world threat-model framing technically permits NRP suppression.

### 9. **Performance bound not quantified** (LOW)

- **Evidence:** Research §Open Questions does not address performance. The filter sketch (lines 378-398) is O(n) on the span list, fine for typical paste submissions. But chained with `filter_by_entity_thresholds`, allow-list filter (inside Presidio), and `resolve_overlaps` (in document path), the cumulative post-filter cost on a large document (e.g., 50K cells xlsx → 50K Presidio calls) is not characterized. The research's `max_xlsx_cells: 50_000` (verified at `src/redakt/config.py:81`) suggests this scenario is real.
- **Risk:** Low — the filter is genuinely O(n). But the cumulative chain is the right thing to measure.
- **Recommendation:** Spec should include a one-line note: "Filter is O(n_spans); composed with existing filters the post-filter chain remains linear in total span count. No new performance bound introduced." That's all that's needed, but it should be said.

### 10. **Empty-span / no-anchor / no-QI edge cases listed in tests but not in edge-case section** (LOW)

- **Evidence:** Research §Production Edge Cases discusses real false-positives, gameable narratives, and allow-list interaction. But the basic structural edges (empty span list, all-anchor span list, all-QI span list, single-anchor + single-QI minimal pair) are deferred to §Testing Strategy where they appear as test rows. The edge-case section is the canonical place to enumerate them — placing them only under "tests" buries them.
- **Risk:** Spec reviewer scanning §Edge Cases may miss them; spec may neglect to state the behavior contract in REQ-form.
- **Recommendation:** Lift "empty span list", "all spans are strong anchors", "all spans are quasi-identifiers" into §Production Edge Cases as explicit behavior assertions, not only as test rows.

### 11. **`MEDICAL_LICENSE` in strong_anchors not reconciled with its known false-positive on `DE_MASTR_ID`** (LOW)

- **Evidence:** Research includes `MEDICAL_LICENSE` in `strong_anchors`. Open-question #4 mentions a fixture note (verified at `tests/eval/fixtures/generic.yaml:130`) that `MedicalLicenseRecognizer` is USA-DEA-scoped, falsely fires on a `DE_MASTR_ID` substring, and "follow-up may disable MEDICAL_LICENSE entirely." If MEDICAL_LICENSE is going to be disabled, including it in strong_anchors creates a phantom anchor — never fires, list looks bigger than it is.
- **Risk:** Operator-facing config confusion; the list looks more thorough than its effective coverage.
- **Recommendation:** Spec should explicitly state the disposition: "MEDICAL_LICENSE is included in strong_anchors anticipating its future disablement; current behavior is unchanged (it does fire on US DEA patterns and on the DE_MASTR_ID substring as a known false-positive)." OR remove MEDICAL_LICENSE from the default list with a deferred-decision note. Either is fine; silence is not.

---

## Questionable Assumptions

1. **"The new function `filter_by_closed_world()` lives in `src/redakt/utils.py`, co-located with `filter_by_entity_thresholds`"** (research line 43) — defensible but inherits the architectural ambiguity that `utils.py` is now becoming a "Redakt-side post-filter module" without that being explicitly named. As post-filter complexity grows (this is the third — allow-list, entity-thresholds, closed-world), the naming `utils.py` becomes misleading. Alternative: rename to `post_filters.py` or `policy.py`. Severity: LOW. This is a future-tech-debt concern, not a v1 blocker.

2. **"No new authZ rules are required"** (research line 137) — defensible. The per-request override is treated as trusted user input. But there's a soft assumption that an agent caller cannot use `closed_world_filtering: true` to *suppress* detections they want suppressed for downstream amplification. The research's threat model frames closed-world as a relaxation; the override allows callers to ENABLE that relaxation. An adversarial caller could thus achieve less anonymization than the operator-default policy. Severity: LOW. The mitigation is operator policy (don't deploy with `closed_world_filtering: false` default + caller-controllable override if you don't trust callers), but the research could surface this explicitly.

3. **"Per-request override mirroring how `entity_score_thresholds` works today"** (ADR-0007 §Decision item 3, research line 56) — the mirror is imperfect because `entity_score_thresholds` is a *tightening* knob (raises floors → drops more) while `closed_world_filtering: true` is a *relaxation* knob (suppresses more spans → emits less). Calling both "per-request overrides mirroring entity_score_thresholds" obscures the directional difference. Severity: LOW. Recommend the spec call out the directional difference.

---

## Missing Perspectives

- **GDPR/legal compliance**: See finding #8 above. Art. 5(1)(c) and Art. 9 are not addressed.
- **Support / on-call**: When closed-world filtering silently suppresses detections and a user reports "Redakt missed my PII," how does the on-call diagnose this? `verbose=true` on `/api/detect` shows post-filter results — but without an audit field for "spans suppressed by closed-world," there is no debug surface. Touches finding #5.
- **The actual end-user (PV operator paste workflow)**: The "Operator (Pablo / Memodo)" stakeholder is conflated with Pablo's three roles. The actual end-user — a Memodo PV employee pasting customer correspondence into Copilot — does not appear as a distinct perspective. They have no insight into whether closed-world is on or off, no UI indication that a quasi-identifier was suppressed, and no path to dispute the suppression. Whether this matters is a product call, but it should at least be acknowledged.

---

## Vocabulary Alignment

**Consistent throughout.** The research uses "closed-world filtering", "strong anchor", "quasi-identifier", "closed-world assumption", and "post-filter" as defined in `SDD/UBIQUITOUS_LANGUAGE.md` (entries on lines 37-55, 91-94). One minor drift: research line 75 ("an anchor entity") uses the explicit-rejected synonym from the glossary entry ("Synonyms to avoid: 'anchor entity'"). This is a single occurrence in a parenthetical explanation, not a substantive drift. Recommend replacing "an anchor entity (e.g., `PERSON`)" with "a strong-anchor span (e.g., `PERSON`)" at line 75 to keep the glossary clean.

---

## Recommended Actions Before Proceeding

1. **(HIGH, blocking)** Decide and document the `/api/documents/upload` path: in-scope (with per-chunk vs document-global semantics specified) or explicitly out-of-scope (with operator-facing note).
2. **(HIGH, blocking)** Enumerate ALL DE_* / EU_* / generic entity types from the actual recognizer catalog. Build a complete entity-classification table (each entity → strong_anchor | quasi_identifier | always-emit), with one-line rationale. Resolve `DE_FUEHRERSCHEIN`, `DE_SOCIAL_SECURITY`, `DE_TAX_NUMBER`, `DE_LANR`, `DE_BSNR`, `DE_HANDELSREGISTER`, `DE_MELO`, `DE_MALO`, `DE_EEG_ANLAGE`, `DE_ZAEHLERNUMMER` explicitly.
3. **(HIGH, blocking)** Amend ADR-0007 in place: `DE_STEUER_ID` → `DE_TAX_ID`. ADR-0007 status is `Proposed`, so direct edit is appropriate. Retract the "no revisions needed" claim at research line 162.
4. **(MEDIUM)** Specify whether `strong_anchors` and `quasi_identifiers` are per-request overridable, and if so what merge semantics (replace vs. add/remove deltas).
5. **(MEDIUM)** Make an explicit audit-logging decision: either "no closed-world suppression telemetry" (current research stance) WITH rationale-against-the-alternative, or add a `closed_world_suppressed_count` audit field. Don't default silently.
6. **(MEDIUM)** Commit to a specific eval-loader extension design (recommend: generic `request_overrides: dict[str, Any] | None` field on `Phrase`).
7. **(MEDIUM)** Decide and document whether the web UI exposes the `closed_world_filtering` toggle or stays instance-default-only.
8. **(MEDIUM)** Add a GDPR Art. 9 analysis for `NRP` classification; consider always-emit as the default.
9. **(LOW)** Lift basic structural edge cases (empty span list, all-anchor, all-QI) into the explicit edge-case section, not only the test table.
10. **(LOW)** Reconcile `MEDICAL_LICENSE` strong_anchors inclusion with its known false-positive and possible disablement.
11. **(LOW)** Fix vocabulary drift at research line 75 ("an anchor entity" → "a strong-anchor span").

---

## Verdict

**REVISE BEFORE PROCEEDING.**

The research is well-organized and the core architectural decisions (filter placement, off-by-default flag, per-request override pattern, threat-model framing) are sound. But three HIGH findings — the missed document-upload path, the materially incomplete strong_anchors list, and the unamended ADR-0007 — are not "go fix in spec" issues; they're "go fix in research before the spec inherits the gaps." Each will create churn in the spec phase if left unaddressed, and the document-upload finding in particular is a correctness gap that would mislead any operator enabling the flag. Step 2d fix-research should address findings 1, 2, and 3 at minimum; findings 4-8 can be moved to spec-phase decisions if the research is updated to flag them as explicit unresolved decisions rather than silent defaults.

---

## Findings Addressed

**Resolved by Step 2d subagent on 2026-05-13.** All 11 findings (3 HIGH, 5 MEDIUM, 3 LOW) addressed. Specific edits below.

### Finding 1 — HIGH: Missing fifth call site (`/api/documents/upload`)

**Resolution:** Added fifth call site to `RESEARCH-008 §System Data Flow — Key entry points`. Detailed the `document_processor.py:182` path, confirmed it bypasses both `filter_by_entity_thresholds` AND the new closed-world filter. Added three-option decision framework (extend into `process_document()` per-chunk vs document-global vs explicit out-of-scope). Recommended v1 out-of-scope with operator note. Added to §Integration point table with explicit "NO (v1 out-of-scope)" marker. Added as §Open Questions Q1. Updated §Files That Matter table to include `documents.py:62` and `document_processor.py:182`. Updated §Existing ADR item 5 to state "Does NOT apply to `/api/documents/upload` in v1". The pre-existing `entity_score_thresholds` inconsistency (also not applied in document path) is surfaced explicitly.

### Finding 2 — HIGH: `strong_anchors` default list materially incomplete

**Resolution:** Added complete `§Complete Entity Classification Table` to `RESEARCH-008 §Configuration Schema Design`. All 18 DE_* entity types from the recognizer catalog are enumerated with classification (strong anchor / quasi-identifier / always-emit) and one-line rationale. Additions to `strong_anchors` that were omitted in the prior draft: `DE_SOCIAL_SECURITY` (Rentenversicherungsnummer), `DE_FUEHRERSCHEIN` (driver's license), `DE_LANR` (lifetime doctor number), `DE_TAX_NUMBER` (Steuernummer). Added 8 always-emit entity types: `DE_BSNR`, `DE_HANDELSREGISTER`, `DE_MALO`, `DE_MELO`, `DE_EEG_ANLAGE`, `DE_ZAEHLERNUMMER` (asset/institution IDs — not personal identifiers). `DE_KFZ` flagged as debated. Updated `strong_anchors` Python and YAML code blocks to reflect the complete list. Updated `§Open Questions Q7` (DE_KFZ) and `Q8` (MEDICAL_LICENSE) as sharper per-spec questions.

### Finding 3 — HIGH: `DE_STEUER_ID` vs. `DE_TAX_ID` — ADR-0007 must be amended

**Resolution:** ADR-0007 amended in-place at two locations: (1) added a naming note paragraph to §Context explaining the rename from `DE_STEUER_ID` → `DE_TAX_ID` and citing codebase evidence; (2) changed `DE_STEUER_ID` → `DE_TAX_ID` in §Decision item 1. Research §Existing ADR "No revisions needed to ADR-0007" claim retracted and replaced with "ADR-0007 amended in-place (2026-05-13): DE_STEUER_ID → DE_TAX_ID." The contradiction (open question vs. "no revisions needed") is resolved.

### Finding 4 — MEDIUM: Per-request override semantics for entity-class lists

**Resolution:** Added `§Per-request override scope — explicit open question for spec` to `RESEARCH-008 §Configuration Schema Design`. States explicitly: `closed_world_filtering` (boolean) is per-request overridable with REPLACE semantics. `strong_anchors` and `quasi_identifiers` are NOT per-request overridable in v1. Two options enumerated; Option (a) v1-boolean-only recommended with rationale. Merge semantics note updated to reflect entity-class lists use instance values only. Added as §Open Questions Q2.

### Finding 5 — MEDIUM: Audit-logging interaction with SPEC-006

**Resolution:** Added §Open Questions Q3 with explicit two-option framing: (a) no change (log post-filter counts only) vs. (b) add `closed_world_suppressed_count` audit field. Recommended Option (b) with rationale (compliance visibility, on-call debugging, privacy-preserving — count is not PII). SPEC-006 SEC-001 compliance verified for the recommended option. Also added §Open Questions Q10 (on-call debug surface) as linked question.

### Finding 6 — MEDIUM: Eval-loader extension design not committed

**Resolution:** Replaced `§Testing Strategy` eval loader "Note" with an explicit `§Eval-loader extension design (explicit open question for spec)` subsection. Two options enumerated: (a) generic `request_overrides: dict[str, Any] | None` on `Phrase` (recommended); (b) separate test file with global flag. Diff sketch provided for Option (a). Added as §Open Questions Q4.

### Finding 7 — MEDIUM: Web UI override exposure asymmetry

**Resolution:** Added §Open Questions Q5 with explicit two-option framing. Stated that web UI submit routes (`pages.py:53`, `pages.py:123`) do not pass per-request overrides — this is API-only in v1. Option (a) web UI inherits instance default only (recommended for v1); Option (b) web UI toggle (future). Updated §Existing ADR item 9 to state "Web UI uses instance default only — per-request override is API-only."

### Finding 8 — MEDIUM: GDPR Art. 9 perspective on NRP classification

**Resolution:** Added `§GDPR Art. 9 perspective on NRP classification` to `RESEARCH-008 §Security & Threat-Model Considerations`. Explains Art. 9 scope, why NRP as quasi-identifier is defensible but warrants spec review-panel confirmation. Documents the always-emit alternative as maximally conservative. Added GDPR Art. 9 note to the entity classification table NRP row. Added as §Open Questions Q6.

### Finding 9 — LOW: Performance bound documentation

**Resolution:** Added `§Performance bound` paragraph to `RESEARCH-008 §Testing Strategy` (after unit test table). States: `filter_by_closed_world()` is O(n) over span set; composed with `filter_by_entity_thresholds()` the chain remains O(n) in total span count. References `max_xlsx_cells: 50_000` scenario. No new performance bound introduced.

### Finding 10 — LOW: Edge-case section completeness

**Resolution:** Added `§Structural edge cases (behavior contracts)` to `RESEARCH-008 §Production Edge Cases`. Six edge cases enumerated as explicit behavior assertions: empty span list, all-strong-anchors, all-quasi-identifiers, single-anchor + single-QI minimal pair, only-always-emit entities, mixed. Also updated §Testing Strategy unit test table to include all six edge cases as test rows. Edge cases now appear in BOTH places (canonical behavior contract in Edge Cases section; test coverage in Testing section).

### Finding 11 — LOW: `MEDICAL_LICENSE` phantom-anchor reconciliation

**Resolution:** `MEDICAL_LICENSE` included in `strong_anchors` with explicit rationale in the entity classification table (conservative default; US DEA-scoped; known false-positive on `DE_MASTR_ID` substring; retained because if it fires it should anchor). Spec disposition stated: "if the recognizer is later disabled entirely, removing it from `strong_anchors` is a no-op." Added as §Open Questions Q8.

### Finding 12 — LOW: Vocabulary drift ("anchor entity" at research line 75)

**Resolution:** `RESEARCH-008 §Production Edge Cases — Allow-list interaction edge case` updated. "an anchor entity (e.g., `PERSON`)" replaced with "a strong-anchor span (e.g., `PERSON`)" and "no PERSON anchor" replaced with "no PERSON strong anchor." Consistent with UBIQUITOUS_LANGUAGE.md §strong anchor synonyms-to-avoid: "anchor entity."
