# Specification Critical Review: closed-world-filtering

**Reviewer:** sdd-critical-reviewer (Opus, adversarial generalist)
**Target:** SDD/requirements/SPEC-008-closed-world-filtering.md (post-panel iter 3)
**Companion review:** SDD/reviews/PANEL-SPEC-closed-world-filtering-20260513.md (panel verdict: PROCEED at iter 3 with 3 LOW remaining)
**Date:** 2026-05-13

## Executive Summary

SPEC-008 went through three panel-fix iterations to retire two HIGH and fourteen MEDIUM findings. The iter-3 panel concluded PROCEED with 3 LOW findings remaining. As a generalist adversarial reviewer, I look for cross-cutting issues the seven specialists may have under-weighted: traceability, module-to-REQ coverage, precedence ambiguity across overlapping gates, and stale-text regressions that survived the iter-3 cross-reference sweep. I find that the cross-reference sweep that closed the iter-2 stale-text cluster did not finish the job: two panel-gate references survive at lines 126 and 704; three new `Settings` fields introduced during fix-iterations (`regulatory_scope`, `allow_per_request_closed_world_override`, `strict_entity_validation`) are absent from MODULE-002's Public Interface listing despite being normative; seven REQ/EDGE/SEC/FAIL identifiers are unreferenced by any module Spec refs (including the entire REQ-020 HIPAA-enforcement runtime path); and the precedence among the four overlapping configuration gates (instance flag, per-request override, SEC-001a operator gate, REQ-020 HIPAA auto-force) is never consolidated into a single decision rule. Validation Strategy gaps the iter-3 panel flagged as LOW are actually broader than reported. None of these rise to HIGH (the spec's design is sound and ships), but two — module Spec-refs incompleteness and the missing precedence consolidation — are MEDIUM and will cause implementation arguments during Step 4. The spec is shippable with a one-pass cleanup; without the cleanup an implementer reading MODULE-002 may not know to wire REQ-020's startup gate at all.

## Overall Severity

MEDIUM

## Ambiguities That Will Cause Implementation Arguments

1. **[Precedence among four overlapping gates — never consolidated]** — Spec defines four overlapping policy gates that interact at request time: (a) `Settings.closed_world_filtering` instance default (REQ-003), (b) per-request `closed_world_filtering: bool | None` (REQ-004/REQ-005), (c) `Settings.allow_per_request_closed_world_override` (SEC-001a), and (d) `Settings.regulatory_scope: ["HIPAA"]` auto-forcing (c) to `false` at startup (REQ-020 § "Per-request override gating under HIPAA scope"). The spec describes each in its own section but never publishes a consolidated precedence rule or decision tree.
   - Possible interpretations of the (HIPAA scope=on) + (instance flag=on) + (per-request=true) case: (A) REQ-020 startup `ValidationError` fires first → no service runs → request never evaluated; (B) startup passes, but SEC-001a auto-forced to false → per-request silently ignored → effective=instance=true → filter runs anyway; (C) the precedence is REQ-020 first, then SEC-001a, then per-request, then instance — but there is no canonical listing. An implementer who places the SEC-001a "silently ignore" branch before the instance-flag check vs after will produce different effective behavior in some cells of the truth table.
   - Compounding: REQ-020 says "the startup `ValidationError` covers the instance-default config path (`closed_world_filtering: true` in `config.yaml`)" — meaning (HIPAA + instance flag = true) is a fatal config combination, the service does not start. Then the same REQ says "auto-force `allow_per_request_closed_world_override = false`" — meaning (HIPAA + instance flag = false + per-request = true) is gracefully degraded. These two enforcement modes for the same regulatory scope are correct as designed but the spec never tabulates them together.
   - Recommendation: Add a "Precedence and gate composition (consolidated)" sub-section near REQ-009 (suppression logic) containing a 4-column truth table: `regulatory_scope=HIPAA`, instance flag, per-request override, `allow_per_request_closed_world_override` → effective behavior + outcome (filter runs / filter no-op / service refuses to start / per-request silently ignored). Eight rows max. Cite REQ-020, SEC-001a, REQ-004/005 in each cell. This single addition would resolve the multi-section reading burden and close MEDIUM Finding 1 in this review.

2. **[REQ-013 line 239 — "SPEC-006 SEC-001" reference collides with SPEC-008's own SEC-001]** — REQ-013 line 239 says "SPEC-006 SEC-001 ('audit log entries never contain PII') is satisfied." SPEC-008 also has its own SEC-001 (per-request override trust model). A reader who follows the cross-reference to "SEC-001" within SPEC-008 lands on the trust-model clause, not the PII-never-logged constraint. The prefix "SPEC-006" is the qualifier but it is easy to miss in flowing prose. MODULE-004's Spec refs line 610 writes `SEC-001 (d), SEC-001a (SPEC-006)` — the trailing `(SPEC-006)` is ambiguous about whether it qualifies just `SEC-001a` or both identifiers. (Panel iter-3 flagged the parenthetical formatting as LOW; the namespace collision is a separate issue.)
   - Recommendation: When citing SPEC-006's SEC-001, write `SPEC-006 §SEC-001` consistently. The within-spec SEC-001 should be cited as just `SEC-001` (no prefix). Apply this naming convention as a one-pass edit.

3. **[REQ-007 "Assembled span list" semantics + EDGE-005 allow-list interaction edge]** — REQ-007 defines "Assembled span list" as "the list returned by `filter_by_entity_thresholds()` — i.e., after per-entity score floors have been applied." EDGE-005 says the allow-list filter runs inside Presidio's `/analyze` call. The unstated invariant — that the input to `filter_by_closed_world()` has ALREADY had both (a) allow-list and (b) `entity_score_thresholds` applied — is correct, but the precedence is split between REQ-007 (mentions thresholds) and EDGE-005 (mentions allow-list). A reader expecting the complete pre-filter pipeline in REQ-007 sees only thresholds and may forget the allow-list semantic.
   - Recommendation: REQ-007 add one sentence: "The assembled span list is the post-allow-list, post-`filter_by_entity_thresholds()` set. Allow-listed strong-anchor spans are absent from this list; their absence may cause the anchor check to fail. See EDGE-005."

4. **[MODULE-001 `enabled` parameter — relationship to upstream merge logic is implicit]** — MODULE-001's function signature takes `enabled: bool`. The spec is clear that the caller resolves the effective flag via the REPLACE merge from REQ-004 ("effective_cwf = body.closed_world_filtering if not None else settings.closed_world_filtering"). What it does NOT make explicit is that the SEC-001a "silently ignore" gate must execute BEFORE the REPLACE merge, not after — otherwise a HIPAA-gated deployment with a per-request `closed_world_filtering: true` would still produce `effective_cwf=true`. MODULE-003 line 576 mentions this in passing ("silently ignored; closed_world_filtering_override is still recorded as null"), and Critical Implementation Consideration #3 line 760 also mentions it. But the canonical merge formula in REQ-004 lines 159–164 does NOT include the SEC-001a gate. An implementer who follows REQ-004's snippet verbatim will produce the wrong precedence.
   - Recommendation: Update REQ-004's code snippet (lines 159–164) to include the SEC-001a gate: `request_value = body.closed_world_filtering if settings.allow_per_request_closed_world_override else None; effective_cwf = request_value if request_value is not None else settings.closed_world_filtering`. Then the merge formula is self-contained and an implementer copying it gets correct behavior.

## Missing Specifications

1. **[MODULE-002 Public Interface omits three newly-mandated Settings fields]** — MODULE-002's Public Interface block lines 542–547 declares exactly three Settings fields: `closed_world_filtering`, `strong_anchors`, `quasi_identifiers`. Fix-iterations 1–3 introduced three additional Settings fields, all of which live in `config.py` per the spec's normative text: `regulatory_scope: list[str] = ["GDPR"]` (REQ-020, line 297), `allow_per_request_closed_world_override: bool = True` (SEC-001a, line 359), and `strict_entity_validation: bool = False` (REQ-011 rule 3, line 224). None appear in MODULE-002's Public Interface listing, and none appear in MODULE-002's Spec refs line 554 (`REQ-001, REQ-002, REQ-003, REQ-010, REQ-011, REQ-012, REQ-016, FAIL-001, FAIL-002`).
   - Why it matters: An implementer reading MODULE-002 to know "what config fields do I add to `Settings`?" gets the iter-0 answer (three fields), not the iter-3 answer (six fields). Two of the missing fields (`regulatory_scope` and `allow_per_request_closed_world_override`) carry runtime validation logic — REQ-020's HIPAA `ValidationError` and the auto-force-on-HIPAA Pydantic `@model_validator` both belong to MODULE-002. If the implementer trusts MODULE-002's Public Interface as authoritative they will miss the runtime gate entirely.
   - Suggested addition: Update MODULE-002 Public Interface lines 542–547 to list six fields. Update line 548 to mention the additional validators: REQ-020 HIPAA gate, SEC-001a auto-force when HIPAA in scope, FAIL-005 / REQ-011 rule 3 canonical-set drift behavior. Update Spec refs line 554 to add REQ-020, SEC-001a, FAIL-005.

2. **[Module Spec-refs orphans — seven identifiers unreferenced]** — Scanning every REQ/EDGE/SEC/COMPAT/REL/FAIL identifier against the five module Spec refs lists, the following are normative but orphan (not referenced by any module):
   - **REQ-017** (NRP classification + Art. 9 operator responsibility) — doc/policy; OK as orphan since it's a policy classification rule with no runtime code. But MODULE-002 contains the default `quasi_identifiers` list that materializes REQ-017's classification; the linkage is implicit.
   - **REQ-020** (regulatory_scope HIPAA enforcement) — has runtime code (Pydantic validator), MUST be in MODULE-002 Spec refs. Currently absent.
   - **REQ-021** (canonical entity classification column in docs) — doc/process requirement, no runtime code. But the CI lint test it mandates (`tests/unit/test_entity_catalog.py`) is testable infrastructure; there is no MODULE-006 for the CI lint nor any module that owns it. Orphan by construction.
   - **EDGE-005** (allow-list-stripped strong anchor) — described as behavior contract; should appear in MODULE-001 Spec refs (the filter is the agent of the behavior). Currently absent.
   - **EDGE-007** (entity in both lists) — should be in MODULE-002 Spec refs (config validation). Implicitly covered via REQ-012 reference, but the explicit EDGE id should be there.
   - **SEC-002** (threat-model assumption documented in config comment) — overlaps with REQ-010; SEC-002 is a brief restatement of the same constraint. Could be merged with REQ-010 or referenced from MODULE-002.
   - **SEC-003** (verbose-mode interaction) — describes v1 scope; no implementation path. Probably belongs in MODULE-003 (the router thread that owns `?verbose=true`).
   - **REL-001** (determinism / retry-variance) — operator-guidance only; no implementation surface. Defensibly orphan.
   - **FAIL-005** (unrecognized entity type — typo path) — has runtime code (Pydantic validator), MUST be in MODULE-002 Spec refs. Currently absent.
   - Suggested addition: One-line fix per module. MODULE-001 Spec refs adds EDGE-005. MODULE-002 Spec refs adds REQ-020, EDGE-007, SEC-002, FAIL-005, REQ-017 (for the `quasi_identifiers` default materialization). MODULE-003 Spec refs adds SEC-003.

3. **[Validation Strategy — gaps broader than panel iter-3 reported]** — Panel iter-3 flagged two LOW: missing tests for REQ-020 HIPAA enforcement and for `closed_world_filtering_override` audit field. Generalist scan finds the gap list is wider:
   - **REQ-015** (document-upload path explicitly bypasses filter) — no integration test asserting that `/api/documents/upload` is unaffected by `closed_world_filtering: true` in config.yaml. This is the only mechanism guaranteeing the v1 scope decision is enforceable; a regression that wires the filter into `document_processor.py` would silently violate REQ-015.
   - **REQ-017** (NRP escape hatch via moving to neither list) — no test asserting `quasi_identifiers: [DATE_TIME, LOCATION, DE_PLZ]` (NRP removed) + flag on → NRP spans are always emitted regardless of anchor presence.
   - **REQ-018** (Web UI uses instance default) — no test asserting that the `pages.py:53` / `pages.py:123` paths inherit the instance default and do NOT accept a per-request override.
   - **FAIL-005** (typo warning vs strict-mode ValidationError) — no test in the unit-test list. Mentioned implicitly under "REQ-011 contents" but not enumerated.
   - **SEC-001a** (operator config gate) — no test asserting that `allow_per_request_closed_world_override: false` causes the request field to be silently ignored AND that `closed_world_filtering_override` is logged as `null` in that case.
   - **REQ-021** (CI lint at `tests/unit/test_entity_catalog.py`) — no test fixture description for the lint test's drift detection (catalog has entity not in doc; doc has entity not in catalog; doc has entity with invalid `classification:` value).
   - **MODULE-001 tuple return** — no test asserting that the function returns the tuple shape `(filtered_list, count)` rather than a list with side-channel count. The interface is decided (lines 522–523) but the contract is untested.
   - Why it matters: The Validation Strategy section is the spec's enumeration of "what counts as DONE." Tests not on the list will get skipped at Step 4b. The iter-1→3 expansion of normative surface (REQ-020, REQ-021, SEC-001a, SEC-003, REQ-011 rule 3 canonical-set, REQ-013 override field) was tracked across normative sections but never reflected in the Validation Strategy — the same iter-2 "section-by-section editing" pattern the panel called out earlier.
   - Suggested addition: Append ~8 enumerated test bullets to the Unit Tests and Integration Tests subsections covering the above. The panel's 2 LOW findings on this topic should be MEDIUM, given the breadth.

4. **[Frozenset pre-computation lifecycle — when does it happen?]** — PERF-001 line 338 says `Settings.strong_anchors_set` and `Settings.quasi_identifiers_set` are "computed once at config-load." MODULE-002 line 550 says set-precomputation happens "via properties." These two statements are at tension: `@property` in Python recomputes on every access; "computed once at config-load" requires either `@cached_property`, a model_validator that sets a private attribute, or eager computation in `__init__`. Pydantic v2 supports `computed_field` but that also recomputes per access unless explicitly cached. The spec does not pin the mechanism.
   - Why it matters: An implementer who uses naive `@property` defeats PERF-001 (every per-call lookup recomputes the frozenset from the list, which is the very thing the iter-1 fix removed). A subtle bug; will not surface in unit tests because the function behavior is correct; will surface as a microbenchmark regression at the 50K-cell document scale (which is precisely the v2 scope-expansion case PERF-001 line 338 names as the motivation).
   - Suggested addition: MODULE-002 line 550 specify: "implemented as Pydantic v2 `@computed_field` with `@cached_property` semantics, OR as a private attribute populated by `@model_validator(mode='after')`. Plain `@property` is forbidden because it recomputes per access." Add a Validation Strategy bullet: "Benchmark `Settings.strong_anchors_set` lookup is O(1) constant time across 1000 sequential accesses (no per-access frozenset construction)."

5. **[`closed_world.yaml` eval fixture file — schema not specified beyond example bullets]** — Validation Strategy Eval Fixtures sub-section (lines 674–683) describes 6 fixture phrases but does not specify how `request_overrides` maps to YAML keys. REQ-014 line 250 says "any unrecognized fixture keys" get collected — but the fixture writer needs to know whether to write `closed_world_filtering: true` as a top-level key (which the loader collects automatically) or under a nested `request_overrides:` key (which would require explicit support). The note at line 683 just says "via `request_overrides`" without showing a sample YAML row.
   - Why it matters: A test author writing the new fixtures will have to invent the schema convention. If REQ-014's "any unrecognized fixture keys" is too permissive, future top-level fixture keys (e.g., a future `tags:` field for fixture organization) will accidentally be collected into `request_overrides` and sent as request bodies, breaking unrelated tests.
   - Suggested addition: REQ-014 specify either (a) a closed allow-list of keys collected into `request_overrides` (today: `closed_world_filtering`) requiring future additions to update the loader, OR (b) a reserved `request_overrides:` nested key per fixture entry. Option (b) is safer.

## Research Disconnects

- **DE_KFZ classification still marked "Review-panel privacy specialist should confirm" in REQ-001 line 126** — Research §Configuration Schema Design line 239 also marks DE_KFZ as "debated — Spec review-panel should confirm." Spec iter-3 panel concluded PROCEED. The gate language survived three fix iterations. The panel's iter-2 stale-text sweep covered RISK-004, Stakeholder Sign-off (NRP), MODULE-002, and the review_panel note — but did NOT cover REQ-001's DE_KFZ row. This is a literal iter-2-class regression that survived iter-3.
  - Disposition: either remove the gate language (DE_KFZ confirmed as strong anchor) OR move DE_KFZ to neither list (always-emit). Research's "conservative default: strong anchor" reading is acceptable as a final disposition; just delete the "Review-panel privacy specialist should confirm" suffix.

- **REQ-001 row vs glossary set count drift** — REQ-001 lines 98–101 enumerate 19 entities in `strong_anchors`. Glossary `strong anchor` definition (UBIQUITOUS_LANGUAGE.md:38) enumerates 15 entities and omits `SEPA_CREDITOR_ID`, `DE_SOCIAL_SECURITY`, `DE_FUEHRERSCHEIN`, `DE_LANR`, `DE_TAX_NUMBER`. The omitted entities are exactly the four "Omitted from prior research draft; corrected here" entries in Research §DE-specific entities table (lines 233–236) plus SEPA. Spec is the post-fix authoritative source; glossary lags.
  - Disposition: Glossary `strong anchor` default-set listing must be updated to match REQ-001's 19-entity list, or replaced with a cross-reference ("Default set: see SPEC-008 REQ-001"). This is a glossary maintenance task, not a SPEC-008 edit, but the Glossary Delta section (lines 769–779) claims "No new terms needed" and asserts consistency — that consistency claim is currently false for `strong anchor`.

- **Research Q1 (document-upload extension) — REQ-015 captures the v1 out-of-scope position cleanly. No disconnect.**

- **Research §Production Edge Cases (Munich weather, PV invoice, Versand-DATE_TIME, DE_PLZ in address)** — All four motivating cases are covered in eval fixtures (lines 676–682) or implicit in REQ-007. No disconnect.

## Internal Contradictions / Cross-Iteration Cruft

1. **[REQ-001 line 126 — DE_KFZ "Review-panel privacy specialist should confirm"]** — Survives from iter-0. Should have been swept in iter-3's cross-reference pass. The DE_KFZ row in REQ-001's rationale table is the LAST place in the spec that asks the panel to ratify a classification; the panel has finished (verdict PROCEED). Either DE_KFZ is in the default `strong_anchors` set (iter-3's reality) or it is not; the spec must commit.
   - Recommended sweep edit (line 126): Replace "Conservative default. Review-panel privacy specialist should confirm." with "Conservative default. Operators in jurisdictions where vehicle-plate look-up is not trivially available may move to neither list (always-emit)."

2. **[Validation Strategy line 704 — "Security specialist (review panel): Confirm SEC-001"]** — Survives from iter-0. Iter-3 swept the privacy-specialist gate at line 701 but did not sweep the security-specialist gate at line 704. SEC-001 was substantively rewritten in iter-1 (HIGH-2 resolution) with sub-clauses (a)–(d) plus SEC-001a config gate. The panel has signed off (verdict PROCEED). Yet line 704 still asks the security specialist to "confirm" SEC-001.
   - Recommended sweep edit (line 704): Replace with: "**Engineering / Security review at Step 4b:** Verify SEC-001 (a)–(d) implementation matches the trust-model framing — specifically the SEC-001a config gate, the audit-field threading per REQ-013, and the REQ-020 HIPAA per-request auto-force." This converts the stale panel-gate into a code-review checklist item.

3. **[Note on `review_panel` line 19 — slight tense glitch]** — Line 19 reads "The panel concluded with REVISE BEFORE PROCEEDING (iter-2) → final iteration (iter-3). The privacy specialist gate is removed; the spec takes the position." The arrow "→ final iteration (iter-3)" reads as if iter-3 is in the future but iter-3 has happened (verdict PROCEED). Minor. Recommended: "→ final iteration (iter-3) → PROCEED."

4. **[REQ-013 line 239 — within-spec SEC-001 collision with SPEC-006 §SEC-001]** — Same observation as Ambiguity #2 above. Cross-iteration cruft because the within-spec SEC-001 expanded into (a)–(d) sub-clauses during iter-1, increasing the namespace collision risk for any external reader.

5. **[MODULE-002 Hides line 550 — "computed once at config-load" vs `@property` mechanism]** — Ambiguity #4 above. Internal contradiction: "computed once" + "via properties" cannot both be true under plain `@property` semantics. The fix in iter-2/iter-3 mandated frozenset pre-computation but did not pin the Pydantic mechanism for "computed once" caching.

6. **[Validation Strategy is iter-0-shaped]** — The unit tests, integration tests, manual verification bullets list iter-0 normative surface (REQs 001–019). The iter-1/2/3 new normative surface (REQ-020, REQ-021, SEC-001a, SEC-003, REQ-011 rule 3, REQ-013 override field) is largely uncovered. Panel iter-3 flagged 2 of these as LOW; I am classifying the full list as MEDIUM #4 above.

## Risk Reassessment

- **RISK-001 (over-suppression):** Spec lists four mitigations including the audit log and per-request override. Severity is correctly LOW. However, the operator-visible diagnostic depends on `closed_world_suppressed_count` being present in audit entries on every text-path call, which depends on MODULE-004 being implemented correctly. The audit field is the only post-deployment signal — if MODULE-004 forgets to thread the override field (panel iter-2 MED-A3, now resolved on paper), or if the SEC-001a "silently-ignored" case under-records the override (line 576 says it logs `null`), an operator cannot distinguish "filter never applied" from "per-request relaxation was attempted but blocked." Severity could be MEDIUM if the iter-3 audit-threading wiring is implemented sloppily; the spec itself is fine.

- **RISK-002 (gameable rule):** Correctly LOW. EDGE-009 documents; operator guidance is consistent.

- **RISK-005 (audit logging coupling to SPEC-006):** Spec line 734 names a fallback path ("log as additional structured field in the existing audit entry dict, not a new parameter"). This is a real coupling. The MODULE-004 signature lines 587–597 assume SPEC-006's `log_detection` / `log_anonymization` accept new keyword parameters; if SPEC-006 codifies a frozen function signature, MODULE-004's contract is unimplementable as drawn. RISK-005's Mitigation is the only place this is discussed; MODULE-004 itself does not say "if SPEC-006 forbids signature extension, fall back to dict extension." Risk severity could be MEDIUM if SPEC-006 is closed-signature; the spec defers verification.
  - Recommendation: Add a Step 4 pre-implementation check: verify SPEC-006's `log_detection` / `log_anonymization` accept signature extension (kwargs or explicit params) BEFORE implementing MODULE-004. If SPEC-006 is closed, MODULE-004's design must change first.

- **[New RISK candidate not enumerated]:** **Operator forgets to update `docs/customizations.md`** — REQ-010 says the config comment text must be mirrored verbatim. REQ-020 says the threat-model paragraph must be mirrored verbatim. The spec lacks a mechanism to enforce the mirroring beyond the description; there is no test, no CI lint, no PR-template requirement. A future operator who edits the config comment in `config.yaml` without re-editing `docs/customizations.md` introduces silent doc drift. Severity LOW; recommendation: add a one-line note to REQ-010 or REQ-021 about CI lint OR accept the manual-mirror discipline as a documentation policy.

## Recommended Actions Before Proceeding

1. **[MEDIUM] [REQ-004, REQ-020, SEC-001a]** Add a "Precedence and gate composition (consolidated)" sub-section with a 4-column truth table covering the four gates (instance flag, per-request override, SEC-001a operator gate, REQ-020 HIPAA enforcement). Eight rows. This single addition resolves the multi-section reading burden and is the highest-impact fix.

2. **[MEDIUM] [MODULE-002]** Update Public Interface to list all six `Settings` fields (`closed_world_filtering`, `strong_anchors`, `quasi_identifiers`, `regulatory_scope`, `allow_per_request_closed_world_override`, `strict_entity_validation`). Update Spec refs to add REQ-017, REQ-020, EDGE-007, FAIL-005, SEC-002. Pin the frozenset-cache mechanism (`@cached_property` or `@model_validator`-set private attribute; not plain `@property`).

3. **[MEDIUM] [Validation Strategy]** Append enumerated tests for REQ-015 (document-upload bypass), REQ-017 (NRP escape hatch), REQ-018 (Web UI instance default), REQ-020 (HIPAA startup ValidationError + per-request auto-force), SEC-001a (silent-ignore + audit-field=null), FAIL-005 (typo warn vs strict ValidationError), REQ-021 (CI lint drift detection), MODULE-001 tuple-return interface. Total ~8 new bullets.

4. **[MEDIUM] [REQ-004 line 159–164]** Update the merge-formula code snippet to include the SEC-001a gate check before the REPLACE merge, so an implementer copying the snippet verbatim produces correct gate-precedence behavior.

5. **[LOW] [REQ-001 line 126, Stakeholder Sign-off line 704]** Cross-reference sweep for residual panel-gate language: remove "Review-panel privacy specialist should confirm" from DE_KFZ row; rewrite "Security specialist (review panel): Confirm SEC-001" as a Step 4b engineering checklist item.

6. **[LOW] [REQ-013, MODULE-004]** Disambiguate "SPEC-006 SEC-001" vs SPEC-008's within-spec SEC-001. Apply `SPEC-006 §SEC-001` convention for external refs; bare `SEC-001` for within-spec refs.

7. **[LOW] [REQ-007]** Add one sentence clarifying that the "assembled span list" is post-allow-list AND post-thresholds, not just post-thresholds.

8. **[LOW] [REQ-014]** Specify whether `request_overrides` keys are collected from any unrecognized YAML top-level field (current text) or from a reserved `request_overrides:` nested key (safer). Recommend nested key.

9. **[LOW] [Glossary]** UBIQUITOUS_LANGUAGE.md `strong anchor` default-set listing lags REQ-001 (missing 4–5 entities). Update glossary or replace with cross-reference. Spec's Glossary Delta section claim of "No new terms needed" is true but the existing-term content is stale.

10. **[LOW] [RISK-005 / MODULE-004]** Add Step 4 pre-implementation check: verify SPEC-006 `log_detection`/`log_anonymization` accept signature extension before implementing MODULE-004.

## Verdict

**PROCEED WITH CAUTION**

Rationale: The spec's design is sound and shippable. The two HIGH findings from iter-1 are genuinely resolved, the iter-2 stale-text cluster largely swept, and the iter-3 fix landed clean. None of my findings rise to HIGH. However, four MEDIUM findings (gate-precedence consolidation, MODULE-002 incomplete public interface, Validation Strategy iter-0-shaped, REQ-004 merge snippet missing SEC-001a) will cause implementation arguments at Step 4 and produce real defects if not addressed: specifically, the MODULE-002 omission means an implementer reading the module section may miss the REQ-020 HIPAA runtime gate entirely. The recommended path is a single-pass cleanup (Steps 3e or 4b) covering items 1–4 above. Items 5–10 (LOW) can be picked up at Step 4b code review or Step 4d evaluation without blocking the flow. The flow does not need another panel iteration; the issues are generalist not specialist, and a fix-subagent can resolve them in <30 minutes of focused editing.

---

## Findings Addressed — Step 3e

**Date:** 2026-05-13
**Subagent:** Step 3e address-findings subagent

All 10 findings (4 MEDIUM, 6 LOW) are resolved. Specific spec changes for each:

### MEDIUM Findings

**MEDIUM-1 (Gate precedence never consolidated)**
Resolution: Added `SEC-002a: Precedence rule for overlapping configuration gates` sub-section under the filter behavior section. Contains full 4-variable state-space truth table (8 rows) with columns: HIPAA flag, instance flag, `allow_per_request_closed_world_override`, per-request value → effective behavior. Cites REQ-003, REQ-004/005, SEC-001a, REQ-020 in each relevant row. Canonical precedence order (HIPAA auto-force > SEC-001a gate > per-request override > instance default) is explicitly stated.

**MEDIUM-2 (MODULE-002 Public Interface stale — only 3 of 6 fields)**
Resolution: Updated MODULE-002 Public Interface to list all six `Settings` fields with their governing REQ/SEC references. Added `@model_validator` contract listing all four validation rules (REQ-012 overlap, REQ-011 canonical-set, REQ-020 HIPAA start gate, REQ-020 HIPAA auto-force). Updated MODULE-002 Spec refs to add: REQ-017, REQ-020, EDGE-007, SEC-001a, SEC-002, FAIL-005. Pinned frozenset caching mechanism in MODULE-002 "Hides": `@computed_field` with `@cached_property` OR `@model_validator`-set private attribute; plain `@property` explicitly forbidden.

**MEDIUM-3 (Validation Strategy iter-0-shaped)**
Resolution: Added 13 new enumerated test bullets to Unit Tests covering: FAIL-005 typo warn/strict paths, REQ-020 HIPAA startup ValidationError, REQ-020 HIPAA auto-force of `allow_per_request_closed_world_override`, SEC-001a silent-ignore + `closed_world_filtering_override=null` audit field, MODULE-001 tuple-return interface contract, REQ-017 NRP escape-hatch, REQ-021 CI lint (3 drift scenarios), PERF-001 frozenset O(1) caching benchmark. Added 6 new integration test bullets covering: `closed_world_filtering_override` audit field threading (3 cases), REQ-015 document-upload path bypass, REQ-018 web UI instance-default-only.

**MEDIUM-4 (REQ-004 merge snippet missing SEC-001a gate)**
Resolution: Rewrote REQ-004 code snippet to include SEC-001a gate check before the REPLACE merge (`request_value = body.closed_world_filtering if settings.allow_per_request_closed_world_override else None`). Added explanatory note: implementers copying the snippet verbatim now get correct gate-precedence behavior.

### LOW Findings

**LOW-1 (REQ-001 line 126 — DE_KFZ residual panel-gate language)**
Resolution: Replaced "Conservative default. Review-panel privacy specialist should confirm." with "Conservative default. Operators in jurisdictions where vehicle-plate look-up is not trivially available may move to neither list (always-emit)." Panel gate is removed; spec takes the position.

**LOW-2 (Stakeholder Sign-off — security specialist panel-gate)**
Resolution: Replaced "Security specialist (review panel): Confirm SEC-001" with "Engineering / Security review at Step 4b: Verify SEC-001 (a)–(d) implementation matches the trust-model framing — specifically the SEC-001a config gate, the audit-field threading per REQ-013, and the REQ-020 HIPAA per-request auto-force."

**LOW-3 (REQ-013 / MODULE-004 — SPEC-006 §SEC-001 namespace collision)**
Resolution: Applied `SPEC-006 §SEC-001` convention for the external cross-reference in REQ-013. MODULE-004 Spec refs rewritten to use clear external/internal distinction: `SEC-001 (sub-clause d), SEC-001a, SPEC-006 §SEC-001 (PII-never-logged constraint — external ref)`.

**LOW-4 (REQ-007 — assembled span list missing allow-list clause)**
Resolution: Added sentence to REQ-007: "The assembled span list is the post-allow-list, post-`filter_by_entity_thresholds()` set. Allow-listed strong-anchor spans are absent from this list; their absence may cause the anchor check to fail. See EDGE-005."

**LOW-5 (REQ-014 — request_overrides schema unspecified)**
Resolution: Rewrote REQ-014 to specify a reserved nested `request_overrides:` key per fixture entry (not any-unrecognized-top-level-key collection). Includes example YAML. Explains why the nested approach prevents future top-level metadata keys from accidentally being forwarded as request fields.

**LOW-6 (Glossary — `strong anchor` default-set listing lags REQ-001)**
Resolution: Updated `SDD/UBIQUITOUS_LANGUAGE.md` `strong anchor` entry to list all 19 entities matching SPEC-008 REQ-001 (added `DE_SOCIAL_SECURITY`, `DE_FUEHRERSCHEIN`, `DE_LANR`, `DE_TAX_NUMBER` which were missing; corrected ordering). Added cross-reference: "For the authoritative list and per-entity rationale, see SPEC-008 REQ-001."

### Additional fixes (from cruft / internal-contradiction findings)

**Line 19 tense glitch:** Fixed "→ final iteration (iter-3)" to "→ final iteration (iter-3) → PROCEED" so the panel history accurately reflects completed verdict.

**PERF-001 / MODULE-002 frozenset caching contradiction:** Resolved in MODULE-002 "Hides" — "computed once at config-load via properties" now specifies the mechanism (`@cached_property` or `@model_validator`-set private attribute; plain `@property` forbidden).

**RISK-005 Step 4 pre-implementation check:** Added explicit pre-implementation check to RISK-005: verify SPEC-006's `log_detection`/`log_anonymization` accept signature extension before implementing MODULE-004. Documents fallback (dict-field extension).

**MODULE-001 Spec refs:** Added EDGE-005 to MODULE-001 Spec refs (previously orphan).

**MODULE-003 Spec refs:** Added SEC-003 to MODULE-003 Spec refs (previously orphan).
