---
adr: 0007
title: Closed-world filtering — anchor-conditional emission for quasi-identifier entities
status: Proposed
date: 2026-05-13
supersedes: null
superseded_by: null
tags: [cross-cutting, redakt-policy, threat-model, post-filter, quasi-identifiers]
---

# ADR 0007: Closed-world filtering — anchor-conditional emission for quasi-identifier entities

## Status

Proposed (2026-05-13)

Captured before implementation to anchor the SDD-flow cycle that will design and land the feature. Status will move to **Accepted** when the implementation merges and the spec is signed off.

## Context

Presidio is span-level by design — each recognizer scores its own pattern/NLP match in isolation. There is no document-level reasoning step that says "this whole text contains no person-naming anchor, therefore the date isn't PII." The architecture is deliberately high-recall: flag everything that looks like an identifier, let downstream policy decide.

**Naming note (2026-05-13):** The German tax-ID entity was originally written as `DE_STEUER_ID` in this ADR. The canonical Redakt/Presidio recognizer name is `DE_TAX_ID` (the name emitted by `de_tax_id_recognizer.py`), confirmed across `tests/eval/fixtures/de.yaml`, `docs/supported-entities.md`, and `docs/customizations.md`. This ADR was amended in-place to use `DE_TAX_ID` throughout, superseding the erroneous `DE_STEUER_ID` form. The `SDD/research/RESEARCH-008-closed-world-filtering.md` "No revisions needed to ADR-0007" claim has been retracted in the research document accordingly.

This produces user-visible noise in Redakt's primary workflow (employees paste a text snippet, receive an anonymized version, paste it into an external AI tool):

- `"What is the weather in Munich, Germany on May 13, 2026?"` flags `LOCATION` and `DATE_TIME` despite having no person-naming anchor. The submission cannot identify a natural person because no identifier-grade signal is present — `Munich` and `May 13, 2026` are joinable quasi-identifiers only against external data the downstream consumer does not have.
- `"Stefan Berger was treated in Munich on May 13, 2026."` correctly flags `PERSON` + `LOCATION` + `DATE_TIME`. The `PERSON` is the joining anchor; `LOCATION` and `DATE_TIME` increase identifiability once the anchor is present.

The privacy literature calls this the **closed-world assumption**: when the submission is the entirety of what the consumer sees, isolated quasi-identifiers cannot be joined against external data and the basis for redacting them collapses. For Memodo's direct paste-into-Copilot/ChatGPT workflow this assumption mostly holds; for a future agent integration that mixes the snippet with the agent's own context, it does not.

The cross-cutting question this decision answers: **does Redakt apply enterprise policy on top of Presidio's high-recall span output to gate quasi-identifier emission on the presence of a strong anchor, or does it stay strictly Presidio-faithful and leave document-level reasoning to clients?**

This generalizes beyond DATE_TIME / LOCATION: any future quasi-identifier addition (NRP, profession, employer, vehicle registration, partial postal codes) faces the same question.

## Decision

**Adopt closed-world filtering as an off-by-default, opt-in policy layer in Redakt.** Presidio remains high-recall and unchanged; Redakt post-filters its output before responding to the client.

Concretely:

1. Classify entity types into two configurable sets:
   - **Strong anchors** — identify a natural person on their own. Default set: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `DE_VAT_ID`, `DE_TAX_ID`, `MEDICAL_LICENSE`, plus any other identifier-grade types in the current ruleset. Always emitted regardless of the flag.
   - **Quasi-identifiers** — PII only when joinable with an anchor. Default set: `DATE_TIME`, `LOCATION`, `NRP`, `DE_PLZ`.

2. Add a top-level `config.yaml` flag `closed_world_filtering: false` (off by default). When enabled, after Presidio returns spans, drop every quasi-identifier span unless at least one strong-anchor span is present somewhere in the same submission.

3. Expose a per-request override knob mirroring how `entity_score_thresholds` works today, so callers (and future agent integrations) can re-tighten without flipping the global default.

4. Locate the filter at the same layer as the existing allow-list filter — late in the detect path, after Presidio's response is assembled. Apply uniformly across `/api/detect` and `/api/anonymize`.

5. Document the threat-model assumption in the config comment: closed-world only holds when the submission is the full context the downstream consumer sees. Agent workflows that combine the snippet with external knowledge break the assumption.

**Cross-cutting principle:** *Presidio recognizes spans; Redakt applies enterprise policy on top of them.* Document-level reasoning that cannot be expressed inside a span-scoped recognizer belongs in a Redakt post-filter, not in a Presidio fork.

## Alternatives Considered

### Chosen — Anchor-conditional post-filter in Redakt, off by default, per-request override

Sits at the right layer (Redakt policy, not Presidio recognition), preserves Presidio's high-recall contract, and is gated behind explicit operator opt-in so the threat-model assumption is a deliberate choice. Per-request override means a future agent integration can re-tighten without operators having to flip the global default.

### On by default

Rejected: the closed-world assumption is a threat-model choice, not a fact. Defaulting it on would silently relax PII protection for instances whose actual workflow does not match the assumption (e.g., agent integrations, downstream systems with their own context). Off-by-default makes the choice explicit and visible in `config.yaml`.

### Express the rule inside a Presidio recognizer or context-enhancer

Rejected: Presidio recognizers and context enhancers are span-scoped; document-level reasoning ("is any anchor present anywhere in the text?") is not expressible without forking the analyzer pipeline. Even if achievable, it would conflate Presidio's high-recall recognition role with Redakt's policy role, and would push the threat-model choice into the upstream-tracked fork where it does not belong.

### Score-threshold tuning only (raise `DATE_TIME` / `LOCATION` floors further)

Rejected: thresholds are scalar and context-free. Raising `DATE_TIME` to suppress noise on weather queries also suppresses legitimate detections in named-person narratives. The signal we need is conditional on document-level context, which threshold tuning cannot express.

### Allow-list tuning per term

Rejected: requires anticipating every quasi-identifier surface form per instance; does not generalize; loses the threat-model framing entirely.

### Drop quasi-identifier detection wholesale

Rejected: incorrect for the named-anchor case where quasi-identifiers materially increase re-identification risk. The whole point of the closed-world rule is that quasi-identifiers are conditional, not unconditional.

## Consequences

### Positive

- Default-config behavior is unchanged — instances that have not opted in see no behavioral change. Off-by-default is a strong upgrade-safety property.
- Opted-in instances get materially less noisy redactions on the dominant paste-into-AI workflow when no anchor is present, while preserving anchor-present redaction behavior unchanged.
- Establishes a **scope boundary** between Presidio and Redakt: Presidio is the recognizer surface, Redakt is the policy surface. Future document-level rules (e.g., "suppress LOCATION when it appears in a quoted geographic question") inherit the same placement.
- Per-request override means agent integrations can re-tighten without operators flipping the global default.

### Negative / Trade-offs accepted

- **The closed-world assumption is a threat-model choice, not a fact.** It holds for direct paste-into-AI workflows but fails for agent workflows that mix the snippet with external knowledge the downstream consumer brings. Operators enabling the flag are taking on the responsibility of verifying their workflow actually matches the assumption.
- **The rule is gameable in one direction.** A narrative like `"Treatment confirmed for May 13, 2026 at the Munich clinic."` carries no strong-anchor entity and would pass quasi-identifiers through under closed-world filtering. Acceptable for B2B PV correspondence (which almost always carries an anchor); an edge case for healthcare-style anchor-stripped narratives. Document explicitly so operators can decide.
- **HIPAA Safe Harbor would not accept this rule** — it explicitly requires unconditional date removal on the theory that anchor removal is exactly when joining attacks become the threat. Redakt is GDPR-scoped, not Safe Harbor-scoped, but capturing this here is the worked example of why the closed-world relaxation is not free.
- **`DE_PLZ` classification is a judgement call.** A German postal code resolves to ~10K–40K people in a city and is a quasi-identifier by joinability; structurally it is also distinctive enough that some operators will want it always-redacted. The default set classifies it as a quasi-identifier (matches actual joinability risk); operators who want always-on behavior move it out of the quasi-identifier list in their `config.yaml`.
- Adds a new section to `config.yaml` (`strong_anchors:` / `quasi_identifiers:` / `closed_world_filtering:`) that operators need to know about and that future entity additions need to be classified into.

### Neutral observations

- The filter is post-Presidio, so it composes cleanly with `entity_score_thresholds` and `allow_list`: thresholds and allow-list run first (current behavior), closed-world filter runs last (new behavior).
- Default `entity_score_thresholds` already sets `LOCATION: 0.90` and `DATE_TIME: 0.95` — closed-world filtering does not replace those floors, it composes with them.
- This decision binds: future quasi-identifier additions must be classified into `strong_anchors` vs `quasi_identifiers` at the time they land; the convention is captured here.

## References

- `docs/v1-feature-spec.md` — V1 feature specification (will be updated by the SDD flow that lands this).
- `docs/customizations.md` — operator-facing customization changelog.
- `src/redakt/config.py:57` — `entity_score_thresholds` default.
- `src/redakt/config.py:60` — `allow_list` default (same layer the new filter lives at).
- Presidio docs (`presidio/docs/`) — span-level recognizer architecture; context for why document-level reasoning lives in Redakt.
- Privacy literature — closed-world assumption / k-anonymity / quasi-identifier joining attacks (background framing; no specific citation pinned here).

## Update 2026-05-18 — shipped default flipped to enabled

The shipped `config.yaml` instance default for `closed_world_filtering` is changed from `false` to `true`. The Decision section above retains the original wording because it captures the *initial shipping* posture (off, so the feature could land without changing behavior, then be activated after end-to-end verification).

**Verification completed before activation:**
- Unit + integration suite: 471/471 passing (commits `31b8d1b` core feature; `2a42457` baseline pin).
- E2E (Playwright against the Docker compose stack): 8/8 passing.
- Eval suite: 120/120 passing — including the four acceptance fixtures that explicitly exercise closed-world on, off, and the gameable healthcare narrative.
- The HIPAA scope gate, the `allow_per_request_closed_world_override` operator gate, and the `StrictBool` per-request override were exercised end-to-end.

**What did not change:**
- The Pydantic schema default in `Settings.closed_world_filtering` remains `False`. The schema default is the safety floor — if an operator removes the key from `config.yaml`, deployments fall back to the safe path. The test `test_default_settings_load_cleanly` asserts this floor via `Settings.model_fields["closed_world_filtering"].default is False`.
- The "Alternatives Considered → On by default" rationale above (rejected as a Redakt-platform principle) still applies to forks and downstream redistributions whose deployment context does not match the closed-world assumption. Operators inheriting this `config.yaml` who run agent workflows or downstream systems with their own context should explicitly set `closed_world_filtering: false`.
- The eval suite's COMPAT-001 baseline (pre-activation behavior) is preserved at request-construction time via `Phrase.build_request_body()`'s baseline pin (`tests/eval/_loader.py`). The pre-activation contract remains testable independently of the shipped default.

**Rationale for activation:**
- The dominant deployment context (Memodo PV operator → paste-into-AI workflow) matches the closed-world assumption: the submission *is* the entirety of what the downstream consumer sees.
- The eval suite shows that with the flag on, 12 anchor-absent phrases (e.g., "Versand voraussichtlich am 15.05.2026.", "Postleitzahl 80331 München.", "Order is scheduled for 28 March 2026 delivery") correctly suppress noisy quasi-identifier redactions — the UX win the feature was built for.
- The HIPAA gate auto-disables closed-world filtering when `regulatory_scope` contains `HIPAA`, so the activation is incompatible with deployments that would actually violate Safe Harbor. The gate is enforced at config-load time.

**Status of this ADR:** Accepted, amended in place. Not Superseded — the original rationale, the alternatives analysis, and the consequences remain authoritative. Only the shipped default value has changed.
