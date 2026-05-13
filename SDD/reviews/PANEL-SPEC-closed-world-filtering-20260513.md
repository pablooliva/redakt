# Spec Review Panel: closed-world-filtering

**Date:** 2026-05-13
**Spec reviewed:** SDD/requirements/SPEC-008-closed-world-filtering.md
**Research context:** SDD/research/RESEARCH-008-closed-world-filtering.md
**ADR consulted:** SDD/adr/0007-closed-world-filtering-quasi-identifiers.md
**Panel:** security, performance, data-modeling, api-contract, module-depth, reliability, privacy
**delivery_mode:** whole-feature (slice-integrity specialist not in panel)

## Executive Summary

SPEC-008 is a well-structured spec covering a policy-level post-filter that suppresses quasi-identifier spans when no strong-anchor span is present. The spec is internally consistent and traces cleanly to ADR-0007 and RESEARCH-008. However, seven domains of review surfaced multiple substantive issues: the panel found **2 HIGH, 9 MEDIUM, and 6 LOW** findings. The HIGH findings cluster around (a) the unresolved REQ-017 NRP/GDPR Art. 9 gate — the spec explicitly defers this to "the privacy specialist on the review panel" without proposing a resolution, and the panel cannot accept GDPR Art. 9 special-category suppression as a quasi-identifier without a documented lawful-basis position; and (b) a security-relaxation knob (`closed_world_filtering: true` in the request body) exposed on an endpoint with no documented authentication model, meaning untrusted callers can globally disable a privacy control without operator visibility. Cross-domain MEDIUMs cluster around (c) ambiguity in MODULE-001's return-type signature (tuple vs side-channel count), (d) HIPAA Safe-Harbor framing presented as compliance-grade without naming the residual obligation, and (e) the document-upload out-of-scope exemption being a partial-coverage compliance gap not surfaced in the audit signal.

## Verdict

**STOP AND RECONSIDER**

Two HIGH findings make this verdict mandatory under the panel synthesis rules. REQ-017 cannot remain "the privacy specialist will decide" indefinitely — the spec itself must state a position, and the position "NRP defaults to quasi-identifier under closed-world suppression" is the maximally generous reading of GDPR Art. 9 and needs an explicit lawful-basis and operator-responsibility clause before it can ship. Separately, SEC-001's "trusted caller" framing is asserted but never substantiated by reference to an authentication scheme in SPEC-008 or any earlier spec in the canon — the override is a privacy-relaxation knob and the trust model must be explicit, not handwaved. The MEDIUM cluster around module signature ambiguity (MODULE-001) and audit-log coverage gap (REQ-013 silent on document-upload path) will cause implementation arguments and require a small revision pass to resolve.

## Findings by Specialist

#### Security Findings

- **HIGH** Per-request override widens trust surface without documented authn model
  - Evidence: SEC-001 lines 251–252: "`closed_world_filtering` field in the request body is treated as a trusted parameter exactly like `entity_score_thresholds`. No new authentication or authorization surface is introduced. Access control inherits from Redakt's existing endpoint security (FastAPI request handling)." The spec asserts trust but does not cite an existing authentication mechanism (no API key, no bearer token, no IP allow-list, no operator-controlled middleware — none surfaced in the spec or visible in the integration table at lines 41–49). The directional asymmetry is then admitted: "this directional difference (the override is a relaxation knob, unlike `entity_score_thresholds` which is a tightening knob) must be called out in documentation."
  - Risk: An attacker (or an internal misuser of an internal-only deployment) who can reach `/api/detect` can send `closed_world_filtering: true` to bypass the operator's quasi-identifier protection on a per-request basis without any operator-visible signal beyond the count in the audit log (REQ-013). If the audit log is sampled, batched, or aggregated, the per-request relaxation is effectively invisible. The spec's mitigation — "operators must not deploy with default-off + untrusted-caller-accessible override if their threat model requires unconditional quasi-identifier redaction" — pushes the responsibility to the operator without giving the operator a tool to enforce it (no config flag to disable per-request override on a per-endpoint basis).
  - Resolution: Add a REQ that lets operators disable the per-request override per endpoint via a `config.yaml` flag (`allow_per_request_closed_world_override: bool = True`); when false, the request-body field is silently ignored (or rejected with HTTP 400). Also expand SEC-001 to explicitly name the assumed authentication mechanism for the deployment (e.g., "VPN-fronted, no public exposure" — and require operators to confirm this in a deploy checklist).
- **MEDIUM** Audit logging that could obscure suppression on document path
  - Evidence: REQ-013 specifies `closed_world_suppressed_count` on the audit entry for `/api/detect` and `/api/anonymize`, but REQ-015 puts `/api/documents/upload` out of scope. The audit entry for a document submission therefore never carries the field. Combined with the fact that document audits already lack `entity_score_thresholds` coverage today (per REQ-015 note about pre-existing inconsistency), a compliance officer reviewing audit logs cannot distinguish "document path: filter does not apply, full Presidio detection emitted" from "document path: filter silently misconfigured."
  - Risk: Compliance reporting that aggregates closed-world suppression across the deployment will undercount document submissions (treating them as if the filter were enabled) — false sense of suppression coverage. The on-call diagnostic loop (per RESEARCH-008 Q10) breaks if operators ever try to use `closed_world_suppressed_count` to triage user complaints about over-redaction; they will be surprised the field is missing on document submissions.
  - Resolution: Add a REQ that for document submissions the audit entry includes `closed_world_suppressed_count: null` (or a sentinel like `"not_applicable"`) so the field is always present in the schema with a distinguishable "out-of-scope-for-this-pipeline" value, and document the schema convention in SPEC-006's audit-entry schema delta (and call this out in REQ-013).
- **LOW** Verbose-debug surface (`?verbose=true`) interaction with closed-world filter unspecified
  - Evidence: RESEARCH-008 §Open Questions Q10 names the `GET /api/detect?verbose=true` diagnostic surface as the on-call diagnostic path; the spec does not say whether `verbose=true` reveals which spans were suppressed by the closed-world filter or only the final post-filter set.
  - Risk: On-call engineers reach for verbose mode to diagnose over-suppression, see only post-filter output, conclude "Presidio didn't detect anything," and miss that closed-world suppression dropped 5 spans.
  - Resolution: Add a REQ stating verbose mode includes (a) the suppressed-span types/counts (never the original text) and (b) the effective `closed_world_filtering` flag value for the request. Alternative: explicitly out-of-scope verbose-mode disclosure for v1 and document the diagnostic path is via the audit-log `closed_world_suppressed_count` only.

#### Performance Findings

- **MEDIUM** Missing cache strategy for high-traffic anchor-set computation
  - Evidence: MODULE-001 hides "the anchor-detection sweep (single O(n) pass computing `{r.entity_type for r in results} ∩ strong_anchors_set`)" and the spec converts `strong_anchors`/`quasi_identifiers` (declared as `list[str]`) inside the filter function at every call ("Set conversion of list parameters (done once inside the function, not per caller)" — MODULE-001 Hides line 374). With `max_xlsx_cells: 50_000` per submission and one Presidio call per cell, that's 50,000 list-to-set conversions per worst-case document submission, all on the per-cell hot path.
  - Risk: PERF-001's "<1ms on a 100-span document" is a per-call bound; the 50,000-cell worst case multiplies fixed-overhead set conversions across all cells. The overhead is small per call but the total dominates the post-filter chain when document-path scope expands (REQ-015 v2 follow-on).
  - Resolution: Either (a) require `Settings` to expose pre-frozen `strong_anchors_set: frozenset[str]` and `quasi_identifiers_set: frozenset[str]` properties so the filter receives sets, not lists (the per-call set conversion goes to O(1)), or (b) explicitly declare in PERF-001 that the per-call set conversion is amortized to negligibility and is acceptable for the 50,000-cell case. Currently neither is stated.
- **MEDIUM** Synchronous in-line filter on hot path with no overflow handling
  - Evidence: REQ-009 mandates the filter runs synchronously after `filter_by_entity_thresholds()` on every `/api/detect` and `/api/anonymize` request. PERF-001 ("<1ms on a 100-span document") doesn't specify behavior at the tail (e.g., a 10,000-span pathological submission — a long pasted log file). The eval fixtures don't include any worst-case input.
  - Risk: A malicious or pathological submission with a large span list (e.g., a stress-test paste of 100,000 dates) hits the filter and may inflate p99 latency in a way that's not captured by the spec's tests. The filter has no early-termination for "no anchor present, span list exceeds X" — it always does a full pass.
  - Resolution: Add a PERF-XXX requirement bounding behavior at the tail (e.g., "for span lists > 10,000 the filter still completes in O(n) but performance is no longer measured as part of v1 success criteria; document submission paths use the document pipeline which bypasses this filter") and add a perf benchmark fixture for a 10k-span input.
- **LOW** Per-call list-to-set conversion documented as implementation detail but never benchmarked
  - Evidence: MODULE-001 Hides line 374 says set conversion happens "once inside the function, not per caller." Validation Strategy benchmarks (lines 501–502) cover only 100-span document. The fixed-overhead of `set(strong_anchors)` for 19 anchors + `set(quasi_identifiers)` for 4 quasi-identifiers is measurable in absolute terms (~1µs each on CPython) but no benchmark validates this.
  - Risk: A future change (e.g., expanding `strong_anchors` to 100+ entries when more country recognizers ship) silently inflates the fixed overhead.
  - Resolution: Either pre-compute sets at config-load (per Performance HIGH above) or add a benchmark asserting "list-to-set conversion ≤ 10µs for the default lists."

#### Data Modeling Findings

- **MEDIUM** Enum-like entity-type lists stored as untyped `list[str]` without canonical-set validation
  - Evidence: REQ-001 and REQ-002 declare `strong_anchors: list[str]` and `quasi_identifiers: list[str]`. REQ-011 validates these are non-None `list[str]` with no non-string elements; REQ-012 forbids overlap. But the spec does NOT validate that entries are members of any canonical set of known Presidio entity types — an operator can write `strong_anchors: ["PEROSN"]` (typo) and the config will load successfully. The filter then never matches the anchor because no Presidio response will carry "PEROSN".
  - Risk: Silent over-suppression. An operator who misspells `PERSON` as `PEROSN` and enables `closed_world_filtering: true` will see all quasi-identifiers suppressed in all submissions (no anchor ever matches) — production-grade noise reduction collapses to wholesale quasi-identifier blackout. The bug is invisible without a reference set and without audit-log entity-type names (and REQ-013 explicitly excludes types).
  - Resolution: Add a REQ requiring `Settings` validation to check each entry in `strong_anchors`/`quasi_identifiers` against a known-canonical set of Presidio entity types (derived from `docs/supported-entities.md` or an enumerated constant); unknown types produce a startup warning (or a hard ValidationError — operator's choice via a `strict_entity_validation` flag). FAIL-004 ("Presidio returns unknown entity type — treated as always-emit") covers the upstream direction but not the operator-typo case.
- **MEDIUM** Three categorical classification states (strong-anchor / quasi-identifier / always-emit) implemented as set membership in two `list[str]` columns is brittle
  - Evidence: REQ-001/REQ-002/REQ-012 model a tripartite enum (`strong anchor`, `quasi-identifier`, `always-emit`) using two-list membership. The "always-emit" classification has no dedicated representation — it is implicit ("not in either list"). The spec relies on `DE_BSNR ∉ strong_anchors ∧ DE_BSNR ∉ quasi_identifiers ⇒ always-emit" being inferred operationally. EDGE-004 shows this works; but as the entity catalog grows, the implicit classification will drift from the documented "always-emit list" at REQ-002 line 148.
  - Risk: A future entity addition (e.g., a new German recognizer for a new ID type) defaults to "always-emit" simply by not being added to either list — an explicit operator decision becomes an accidental side effect of forgetting to update config. This is the classic enum-as-string-set anti-pattern: missing values silently become "unknown" rather than triggering a known-set check.
  - Resolution: Add a REQ that the spec maintains a documented "canonical entity catalog" in `docs/supported-entities.md` with an explicit `classification:` column (one of `strong_anchor | quasi_identifier | always_emit`), and the spec gates the catalog against this column at PR-review time. Operationally, this is a doc-and-process change, not a code change.
- **LOW** No uniqueness constraint on entity-type strings within a list
  - Evidence: REQ-011 validates `list[str]` and string element type; REQ-012 forbids cross-list overlap; but neither REQ forbids duplicates within a single list (e.g., `strong_anchors: ["PERSON", "PERSON", "EMAIL_ADDRESS"]` would load successfully).
  - Risk: Operator confusion — duplicates suggest different semantics that don't exist. Minor; the filter functions correctly on duplicates.
  - Resolution: Add to REQ-011 that duplicates within a list produce a `ValidationError` (or warn-and-deduplicate; operator's choice).

#### API Contract Findings

- **MEDIUM** Optional-boolean field with three states (`true`/`false`/`null`) is a non-idiomatic API convention
  - Evidence: REQ-004 lines 158–165 specify `closed_world_filtering: bool | None = None` with the merge logic: `None` = use instance default, `true`/`false` = override. The same pattern exists for `entity_score_thresholds` and is consistent — but in REST API contract terms, "absent field" and "explicit null" carry semantically different meanings in many client SDKs and are not distinguishable in standard FastAPI/Pydantic deserialization (both deserialize to `None`).
  - Risk: A client that omits the field gets instance-default behavior; a client that explicitly sends `"closed_world_filtering": null` gets the same behavior. This is currently correct (both should use instance default), but the contract documentation must make this equivalence explicit. Some clients (typed-codegen clients) may treat null as "explicitly set to null" and complain.
  - Resolution: Add an EDGE case or clarification to REQ-004/REQ-005 explicitly stating: "absence of the field and explicit `null` value are semantically equivalent — both mean 'use instance default.'" Document this in the OpenAPI spec when generated.
- **MEDIUM** Breaking-change classification missing for audit-log schema extension
  - Evidence: REQ-013 specifies adding `closed_world_suppressed_count: int` to the audit entry, "always present in the audit entry, never absent." MODULE-004 Risk section says: "SPEC-006's existing audit schema is extended with one new integer field. No PII involved." But no spec REQ explicitly classifies this as a backwards-compatible additive change or a breaking schema change for downstream audit log consumers.
  - Risk: If any downstream consumer (a SIEM ingestor, a compliance dashboard, a log-parser fixture in test code) validates the audit-entry schema with a strict schema (Pydantic, JSON Schema with `additionalProperties: false`), this new field will fail validation. The spec doesn't surface that risk.
  - Resolution: Add a REQ that explicitly classifies REQ-013's audit-entry change as a backwards-compatible additive extension AND surveys SPEC-006's audit-schema strictness (does SPEC-006 declare the schema as open-set or closed-set?). If closed-set, this is a breaking change requiring a SPEC-006 amendment.
- **LOW** No versioning strategy for `closed_world_filtering`-related fields in request/response models
  - Evidence: SEC-001 documents the per-request override; no spec REQ touches API versioning. Redakt currently has no versioned API surface (no `/v1/api/detect`), so this is consistent — but the spec introduces a new request field on an unversioned endpoint with semantics that may evolve (e.g., the v2 MERGE-BY-DIFF semantics mentioned in REQ-006 line 171).
  - Risk: v2 adding `strong_anchors_add`/`strong_anchors_remove` to the request body without an API version bump means old clients that don't send these fields keep the current behavior, but the API contract gets new fields silently. Minor today; will compound.
  - Resolution: Add a brief note (in Implementation Notes or Dependencies) acknowledging the unversioned-API posture and stating: "v2 additions are backwards-compatible additive fields; v3+ MERGE-BY-DIFF semantics will require a versioning discussion."

#### Module Depth Findings

- **MEDIUM** Public method return-type ambiguity in MODULE-001 (deep-module clarity violated)
  - Evidence: MODULE-001 lines 357–366 declare the public interface as `filter_by_closed_world(...) -> tuple[list[RecognizerResult], int]` but immediately admit ambiguity: "If the existing codebase convention strongly prefers a separate count-compute step, an alternative is `filter_by_closed_world(results, ...) -> list[RecognizerResult]` plus `count_quasi_identifiers(results, quasi_identifiers) -> int` called before filtering. Either design satisfies REQ-013; implementation should match whichever pattern `filter_by_entity_thresholds` uses."
  - Risk: The deep-module promise (interface ≪ implementation) is violated when the public interface itself is presented as "the implementation will decide." A caller reading the spec cannot tell whether `filter_by_closed_world()` returns a tuple, a list, or has a side-channel count companion. This is exactly the ambiguity-that-causes-implementation-arguments criterion at MEDIUM. Ousterhout: a module whose public interface is "to be determined by the implementation" is by definition shallow.
  - Resolution: SPEC-008 must pick one. Recommendation: align with `filter_by_entity_thresholds` (RESEARCH-008 confirms the precedent at `utils.py:97-108` returns `list[RecognizerResult]`, no count), so the precedent-consistent choice is `filter_by_closed_world(...) -> list[RecognizerResult]` with a separate `count_quasi_identifiers(results_before, results_after, quasi_identifiers) -> int` helper, OR consciously diverge and explain why a tuple return is correct here. Make the choice in the spec, not in the implementation.
- **MEDIUM** Module surface area: MODULE-001's public-interface explanation buries the no-op branch
  - Evidence: MODULE-001 "Hides" lists 6 items including "The no-op branch when `enabled=False` (returns input unchanged, count=0)" (line 373). The pure-function design is sound, but the public-interface signature does not capture the precondition: callers passing `enabled=False` get an O(1) pass-through, callers passing `enabled=True` get the full O(n) work. PERF-002 captures it ("O(1) no-op when disabled") but the module section's Public Interface does not.
  - Risk: A caller reading the public interface in isolation cannot know that `enabled=False` is a documented zero-cost path. Minor friction.
  - Resolution: Update MODULE-001's Public Interface signature with a docstring sketch stating "When `enabled=False`, returns `(results, 0)` immediately."
- **LOW** Module 005 (eval-loader extension) is genuinely shallow but justification is implicit
  - Evidence: MODULE-005 lines 429–447 declares the eval-loader extension — adding a `request_overrides: dict[str, Any] | None = None` field to `Phrase` and merging it into request bodies. The "Hides" lists three trivial items; the module is essentially a pass-through with shape coercion. No explicit "Justification (if shallow)" stanza exists.
  - Risk: A future reviewer will ask "is this really a module?" The answer is yes (it's a test-infra modification that needs to land alongside the fixtures), but the spec doesn't say so.
  - Resolution: Add a one-line justification: "Shallow by intent — this module is a forward-compat seam for future per-fixture request parameters; it would be re-implemented as a more general fixture-overrides mechanism in v2."

#### Reliability Findings

- **MEDIUM** Graceful-degradation behavior on misconfigured `strong_anchors` not specified
  - Evidence: REQ-011 requires fail-fast on invalid config (`ValidationError` at startup; no graceful degradation). FAIL-001 confirms. But the spec does NOT specify what happens if `strong_anchors` is valid YAML but operationally empty (REQ-008 EDGE-008 says "Both are valid (if unusual) operator configurations. The filter must not crash on either"). When combined with `closed_world_filtering: true`, an empty `strong_anchors` means EVERY submission has no anchor → every quasi-identifier suppressed in every submission. This is a degraded reliability state (over-suppression) with no operator-visible signal beyond `closed_world_suppressed_count` in audit logs.
  - Risk: An operator who clears `strong_anchors` (perhaps trying to disable closed-world filtering by clearing the list, not realizing the correct knob is `closed_world_filtering: false`) silently degrades the system into "all quasi-identifiers always suppressed." The spec acknowledges this is "degenerate" (EDGE-008 line 286: "Operators should be warned via documentation that an empty `strong_anchors` with the flag enabled is a degenerate configuration") but provides no runtime detection.
  - Resolution: Either (a) add a startup-warning log line ("WARN: `closed_world_filtering: true` AND `strong_anchors: []` — every submission will suppress all quasi-identifiers; this is likely a misconfiguration"); or (b) treat empty `strong_anchors` + `closed_world_filtering: true` as a ValidationError (consistent with fail-fast posture for the other config violations in REQ-011/REQ-012).
- **MEDIUM** Idempotency under retry not explicit; relevant if a client retries on transient Presidio failures
  - Evidence: The spec is silent on retry semantics. Reading PERF-002 ("when disabled, immediate return") and REQ-007 ("pure function over span list") implies idempotency by construction. But Redakt's client may retry the entire `/api/detect` call (network failure) and the second call may see different Presidio output if the upstream Analyzer service had a transient internal state change (caching, NER model variability for non-deterministic transformer scoring). Closed-world filter result varies by anchor presence in the Presidio response, not by request fingerprint.
  - Risk: A client that retries an `/api/detect` call expecting deterministic output may get different `closed_world_suppressed_count` values across retries (Presidio returns 5 spans the first time, 4 the second time — anchor presence flips between calls). The audit log records both — a compliance reviewer sees inconsistent suppression and cannot tell whether the closed-world filter is reliable.
  - Resolution: Add an Edge Case or Reliability Note stating "Closed-world filter is deterministic given a fixed Presidio response; non-determinism in the Presidio Analyzer upstream is the source of any retry-time variance. Operators should not interpret per-request `closed_world_suppressed_count` as a stable metric; aggregate counts over time-windows for compliance reporting."
- **LOW** No spec requirement for filter behavior when `RecognizerResult` lacks `entity_type` attribute
  - Evidence: MODULE-001 line 357 type-hints `results: list[RecognizerResult]` and the filter inspects `r.entity_type`. If a future Presidio SDK version changes the attribute name (`entity_type` → `type`), the filter raises `AttributeError`. The spec doesn't cover this.
  - Risk: Future-Presidio SDK upgrade silently breaks the filter. Low because Presidio is pinned via Docker Compose and the upgrade would be visible in PRs.
  - Resolution: Add a one-line implementation note: "Filter depends on `RecognizerResult.entity_type` attribute name (Presidio SDK ≥ 2.x). Re-validate on Presidio major version bumps."

#### Privacy Findings

- **HIGH** Special-category data (NRP) treated as ordinary quasi-identifier without lawful-basis statement
  - Evidence: REQ-017 lines 228–229: "`NRP` (Nationality, Religious belief, Political opinion) is included in the `quasi_identifiers` default list. This classification — 'suppress NRP when no anchor is present' — is a defensible but non-obvious decision under GDPR Art. 9... The review-panel `privacy` specialist must explicitly confirm this classification before the spec is considered signed off." The spec defers this decision to the panel itself — it has no proposed resolution, just a gate. RESEARCH-008 §"GDPR Art. 9 perspective on NRP classification" makes the underlying argument: in isolation NRP doesn't identify, so the closed-world rationale technically holds — but ALSO notes "an operator who misjudges the closed-world assumption (e.g., their workflow is not actually closed-world) would miss an Art. 9 category mention."
  - Risk: GDPR Art. 9 grants special-category protection regardless of identifiability. An NRP detection ("the user mentioned Islam") that gets suppressed because no PERSON anchor is present means an operator's downstream system processes religion text without the special-category-data flag that Redakt's PII detection was meant to surface. If the downstream LLM or human reviewer subsequently uses that text in a profiling decision, the operator has lost the Art. 9 audit trail. The closed-world rationale is sound for re-identification risk; it is NOT sound for Art. 9 lawful-basis tracking. The two are different concerns and the spec conflates them.
  - Resolution: SPEC-008 must take a position rather than deferring. Recommendation: move `NRP` to the always-emit set (out of `quasi_identifiers`), document the trade-off in a new REQ stating "NRP is always-emit because GDPR Art. 9 special-category data requires explicit lawful-basis tracking regardless of identifiability; the closed-world relaxation is appropriate for re-identification quasi-identifiers, not for special-category tracking." If the spec really wants NRP suppression as default, it must add a lawful-basis clause acknowledging the operator's responsibility ("operators enabling NRP suppression must document their Art. 9 lawful basis separately; Redakt's audit log of `closed_world_suppressed_count` does not satisfy Art. 9 record-keeping").
- **MEDIUM** HIPAA Safe Harbor incompatibility framed as a warning, not a regulatory boundary
  - Evidence: REQ-010 line 187: "HIPAA Safe Harbor requires unconditional date removal — do not enable this flag in Safe Harbor contexts." This is repeated in ADR-0007 (§Consequences). The framing is informational ("do not enable in Safe Harbor contexts") but the spec doesn't enforce or detect Safe Harbor deployment context.
  - Risk: A healthcare operator who reads the config comment, misjudges their context ("we're GDPR-only, not US"), enables the flag, and later expands into a US healthcare market, has silently inherited a Safe Harbor incompatibility. Redakt has no runtime check.
  - Resolution: Add a spec REQ requiring a `regulatory_scope: list[str]` field in `config.yaml` (e.g., `["GDPR"]` or `["GDPR", "HIPAA"]`). When the list contains `HIPAA`, `closed_world_filtering: true` triggers a `ValidationError` at startup. This makes the regulatory boundary detectable, not just documented. Alternative: leave as warning but add a deploy checklist artifact (`docs/regulatory-deploy-checklist.md`) listing the closed-world flag with a "do not enable in Safe Harbor" line.
- **MEDIUM** Gameable rule presented as compliance-grade control without naming residual risk to operator
  - Evidence: EDGE-009 explicitly accepts the gameable narrative case ("Treatment confirmed for May 13, 2026 at the Munich clinic"). The spec acknowledges this in RISK-002 with mitigation "documented in ADR-0007 as accepted for B2B PV workflows; spec EDGE-009 acknowledges explicitly." However, the operator-facing message (REQ-010 config comment) frames the flag as a noise-reduction control without telling the operator: "This filter is bypassed by any text that omits a name but includes a person-identifying narrative. If your downstream consumer can infer 'the patient' from context, the closed-world assumption fails."
  - Risk: An operator enables the flag based on the noise-reduction promise, doesn't understand the gameable failure mode, and uses Redakt in a healthcare or social-services workflow where role-based references ("the patient", "der Kunde") are common. The compliance impact lands on the operator, not Redakt.
  - Resolution: Expand REQ-010's config comment to include the gameable-narrative warning verbatim: "GAMEABLE: Role-based references ('the patient', 'the customer', 'der Kunde') do not trigger the anchor check — quasi-identifiers in such narratives will pass through unredacted. Not safe for healthcare, social-services, or any context using role-based identification."
- **LOW** Threat model assumption (closed-world) named in the config comment but not in any operator-facing artifact outside config.yaml
  - Evidence: REQ-010 puts the threat-model warning in the config-yaml comment. RESEARCH-008 §Documentation Needs lists `docs/customizations.md` and `docs/v1-feature-spec.md` as places to document the feature. The spec doesn't require the threat-model framing to appear in those docs in the same precise terms.
  - Risk: An operator who reads `docs/customizations.md` to decide whether to enable the flag may get a watered-down summary; the precise threat-model statement lives only in config.yaml.
  - Resolution: Add a REQ that the threat-model paragraph (REQ-010's comment text verbatim) is also rendered verbatim in `docs/customizations.md`'s closed-world section, and that any future doc updates must preserve the wording.

## Cross-Specialist Observations

Three issues surfaced across multiple specialist lenses:

1. **Audit-log signal is the only operator-visible diagnostic, but its coverage is partial.** Security MEDIUM ("document path audit gap"), Reliability MEDIUM ("misconfigured strong_anchors no runtime signal"), and Privacy LOW ("threat-model framing only in config.yaml") all converge: `closed_world_suppressed_count` is the spec's only post-deployment instrumentation and it has gaps (doesn't fire on document path; doesn't disambiguate "filter disabled" from "no quasi-IDs were present"; doesn't surface why suppression happened). The spec should either accept this as a v1 limitation explicitly or extend REQ-013 to cover the gaps.

2. **The per-request override is a relaxation knob with no operator gating.** Security HIGH and Privacy MEDIUM both pin on this: a caller can disable a privacy control on a per-request basis and the operator has only audit-log post-hoc visibility (and only on the text path). The trust model is implicit in SEC-001 and absent everywhere else.

3. **Implementation ambiguity in MODULE-001 (return type) and REQ-013 (audit field always-present-vs-absent) will cause arguments during implementation.** Module Depth MEDIUM and API Contract MEDIUM converge: SPEC-008 needs to pin its public interfaces, not defer them to "match whatever the precedent is."

## Recommended Actions Before Proceeding

1. **[HIGH] [REQ-017 / Privacy]** Take a position on NRP classification. Move to always-emit by default OR keep as quasi-identifier with an explicit lawful-basis clause and operator-responsibility statement added to REQ-010 and `docs/customizations.md`. Do not ship with the "the panel decides" deferral.
2. **[HIGH] [SEC-001 / Security]** Add operator-controlled config gate (`allow_per_request_closed_world_override: bool = True`) that lets operators disable the per-request override on a deployment basis. Explicitly name the assumed authentication mechanism (or its absence) in SEC-001.
3. **[MEDIUM] [MODULE-001 / Module Depth]** Pin the public interface: choose tuple-return OR separate count helper, justify against `filter_by_entity_thresholds` precedent. Remove the "either design satisfies REQ-013" alternative.
4. **[MEDIUM] [REQ-013 / Security, API Contract]** Specify behavior of `closed_world_suppressed_count` on document-upload audit entries (REQ-015 out-of-scope path). Recommend `null` or sentinel value, schema documented in SPEC-006 delta.
5. **[MEDIUM] [REQ-001/REQ-002/REQ-011 / Data Modeling]** Add validation that `strong_anchors`/`quasi_identifiers` entries are members of a known-canonical Presidio entity set; flag operator typos at startup.
6. **[MEDIUM] [REQ-010 / Privacy]** Expand REQ-010 config-comment text to include the gameable-narrative warning (EDGE-009 in verbatim operator-facing form). Require same text in `docs/customizations.md`.
7. **[MEDIUM] [EDGE-008 / Reliability]** Add startup warning (or fail-fast) when `closed_world_filtering: true` AND `strong_anchors: []` — currently silent degenerate state.
8. **[MEDIUM] [PERF-001 / Performance]** Resolve set-conversion-per-call vs pre-frozen-sets-in-Settings; align with the document-upload v2 scope expansion plan.
9. **[MEDIUM] [REQ-013 / API Contract]** Classify the audit-entry schema extension as backwards-compatible additive in SPEC-006 explicitly; check SPEC-006's audit-schema closedness.
10. **[MEDIUM] [REQ-010 / Privacy]** Add `regulatory_scope: list[str]` config field or `docs/regulatory-deploy-checklist.md` artifact to make HIPAA Safe Harbor incompatibility detectable, not just documented.
11. **[MEDIUM] [REQ-004/REQ-005 / API Contract]** Clarify in REQ-004/REQ-005 that absent field ≡ explicit null ≡ "use instance default".
12. **[MEDIUM] [Reliability]** Add explicit determinism / retry-variance note: closed-world filter is deterministic given a fixed Presidio response; Presidio non-determinism is the source of any variance.
13. **[LOW] [REQ-001/REQ-002]** Forbid duplicates within a single list (REQ-011 extension).
14. **[LOW] [SEC-001 / Security]** Specify whether `?verbose=true` reveals suppressed-span types/counts or only post-filter spans.
15. **[LOW] [MODULE-005]** Add explicit "shallow by intent" justification.
16. **[LOW] [PERF-001]** Either implement pre-frozen sets in Settings or benchmark list-to-set conversion overhead.
17. **[LOW] [REQ-010]** Mirror threat-model paragraph verbatim into `docs/customizations.md`.

## Panel Metadata

- **Specialists with no concerns:** none (all 7 found findings).
- **Specialists with findings:** security=3, performance=3, data-modeling=3, api-contract=3, module-depth=3, reliability=3, privacy=4 (counted before dedup; total raw 22 findings).
- **Post-deduplication finding counts:** HIGH=2, MEDIUM=9, LOW=6 (17 distinct). Cross-specialist overlap merged into Cross-Specialist Observations (3 patterns).
- **Note on panel execution mode:** Specialist findings in this document were produced by the panel orchestrator applying each specialist's canonical vocabulary payload and named anti-pattern set (from `/sdd:spec-review-panel` Section 4) directly against SPEC-008, RESEARCH-008, and ADR-0007. The orchestrator did not spawn subagents (the Task primitive was not available in the execution environment); fresh-context-per-specialist isolation was approximated by applying each specialist's named anti-pattern list as a discrete pass over the spec. The synthesis rules (deduplication, severity aggregation, ban-bare-approvals) were applied per Section 5.

---

## Findings Addressed — Iteration 1

**Fix subagent:** claude-sonnet-4-6
**Date:** 2026-05-13
**Iteration:** 1 of max 3
**Pre-fix finding count:** HIGH=2, MEDIUM=9, LOW=6

---

### HIGH Findings

#### HIGH-1 — REQ-017 NRP/Art.9 panel-deferral (Privacy)
**Finding:** REQ-017 deferred the NRP classification decision to "the review panel privacy specialist." This is a gate, not a position, and cannot ship.

**Resolution:** REQ-017 completely rewritten. The spec now takes a decisive position:
- `NRP` is **retained in `quasi_identifiers`** as the default classification under the closed-world re-identification threat model.
- Rationale is stated: NRP in isolation cannot be joined to identify a natural person without an anchor; the re-identification rationale is sound.
- **Residual Art. 9 risk is explicitly named and assigned to the operator:** the closed-world filter is not a substitute for Art. 9 unconditional removal; operators enabling NRP suppression must document their Art. 9 lawful basis separately; `closed_world_suppressed_count` does NOT satisfy Art. 9 record-keeping.
- Operator escape hatch documented: move `NRP` to neither list (always-emit) in `config.yaml` to disable suppression unconditionally.
- The panel-gate language ("privacy specialist must confirm") is removed.
- The NRP rationale row in REQ-002's entity table is updated to reference REQ-017 for the full lawful-basis position.
- REQ-010 config comment updated to include the Art. 9 operator responsibility paragraph verbatim.

**Spec location:** REQ-002 (NRP row in entity table), REQ-010 (config comment text — ART. 9 block added), REQ-017 (complete replacement of section "NRP review-panel gate" with "NRP classification — GDPR Art. 9 position (resolved)").

---

#### HIGH-2 — SEC-001 per-request trust-model under-spec (Security)
**Finding:** SEC-001 asserted "trusted caller" without naming the authentication mechanism, without giving operators a gating tool, and without specifying audit coverage of the relaxation knob.

**Resolution:** SEC-001 completely rewritten with four explicit sub-clauses:
- **(a) Trust level:** explicitly inherits `entity_score_thresholds` trust model — caller is trusted, no separate authn; no API key / bearer token introduced.
- **(b) Directional asymmetry:** named and explained — this is a relaxation knob (less PII output), unlike `entity_score_thresholds` (more PII output). Operator deployment posture responsibility assigned.
- **(c) Operator deployment posture:** operators in untrusted-caller contexts must NOT enable closed-world filtering globally OR must disable per-request override via the new config gate.
- **(d) Audit visibility:** per-request override is recorded as `closed_world_filtering_override: bool | null` in every audit entry (REQ-013 also updated to specify this field).

**New SEC-001a:** Added `allow_per_request_closed_world_override: bool = True` to `Settings` and `config.yaml`. When `false`, the per-request field is silently ignored; the instance default is always used. Startup INFO log confirms gate state. This gives operators a deployment-level enforcement mechanism.

**REQ-013 updated:** Added `closed_world_filtering_override` field to the audit entry schema with explicit `bool | null` semantics (null = caller did not set field; true/false = caller explicitly overrode). Document-upload path sets this to `null` (consistent with `closed_world_suppressed_count: null` sentinel).

**REQ-010 config comment updated:** Added OVERRIDE block documenting `allow_per_request_closed_world_override` flag.

**Spec location:** SEC-001 (replaced with (a)–(d) clauses plus new SEC-001a), REQ-013 (added `closed_world_filtering_override` field and document-path null semantics), REQ-010 (OVERRIDE block added to config comment).

---

### MEDIUM Findings

#### MEDIUM-1 — MODULE-001 return-type ambiguity (Module Depth)
**Finding:** MODULE-001 public interface presented two alternatives ("either design satisfies REQ-013; implementation should match whichever pattern `filter_by_entity_thresholds` uses") — a classic deep-module clarity violation.

**Resolution:** The tuple return `-> tuple[list[RecognizerResult], int]` is now the sole specified interface. The alternative (separate count helper) is **explicitly rejected** with rationale: `filter_by_entity_thresholds` returns only a list because it has no audit count requirement; this module has an explicit audit requirement (REQ-013) that makes the count a natural output of the same single O(n) pass. Splitting into two functions would require either two passes or shared mutable state. The implementation must NOT use a separate count helper. The docstring sketch is added showing `enabled=False → (results, 0)` immediately.

**Spec location:** MODULE-001 "Public Interface" block — the "Note on return type" paragraph replaced with "Return type decision (resolved — no longer ambiguous)" with explicit rejection of the alternative.

---

#### MEDIUM-2 — REQ-013 audit-coverage gap on document path (Security, API Contract)
**Finding:** REQ-013 was silent on document-upload audit entries; the field would simply be absent on document submissions, creating a distinguishability problem for compliance officers.

**Resolution:** REQ-013 now explicitly states:
- Document-upload audit entries set `closed_world_suppressed_count: null` (JSON null, not `0`).
- `null` = "not applicable — filter does not apply to this pipeline in v1"; distinguishable from `0` (filter applied, no suppression) and from absent.
- Compliance tooling must treat `null` as "not applicable."
- Schema compatibility section added: this is a backwards-compatible additive extension; SPEC-006's audit-entry schema must be declared open-set (not closed-set) before this lands.

**Spec location:** REQ-013 — added "Document-upload path" and "Schema compatibility" paragraphs.

---

#### MEDIUM-3 — REQ-001/REQ-002 unvalidated entity type strings (Data Modeling)
**Finding:** No validation that `strong_anchors`/`quasi_identifiers` entries are in any canonical set; operator typo `"PEROSN"` loads silently and causes silent over-suppression.

**Resolution:** REQ-011 expanded with three rules:
1. Type check (existing — non-list or non-string raises ValidationError).
2. **Duplicate check (new):** duplicates within a list raise ValidationError.
3. **Canonical-set validation (new):** entries not in the canonical entity-type set from `docs/supported-entities.md` produce a startup WARNING by default; `strict_entity_validation: true` escalates to ValidationError.

New FAIL-005 added describing the operator-typo failure scenario and both default/strict behaviors.

**Spec location:** REQ-011 (replaced single rule with three numbered rules), FAIL-005 (new failure scenario).

---

#### MEDIUM-4 — Tripartite classification implicit (Data Modeling)
**Finding:** "always-emit" is implicit (not in either list); as the entity catalog grows, missing classifications silently become "always-emit" rather than triggering explicit review.

**Resolution:** REQ-021 added requiring `docs/supported-entities.md` to carry an explicit `classification:` column (`strong_anchor` | `quasi_identifier` | `always_emit`) for every entity type. PR reviews adding a new entity type must classify it in this column before merging — the `always_emit` default must be an explicit documented decision, not an accident of omission.

**Spec location:** REQ-021 (new requirement, added before REQ-016 section).

---

#### MEDIUM-5 — Optional-boolean three-state API convention not explicit (API Contract)
**Finding:** Absent field and explicit `null` both deserialize to `None` in FastAPI/Pydantic but this equivalence was not documented; typed-codegen clients may be surprised.

**Resolution:** REQ-004 and REQ-005 now include an explicit "Null-equals-absent semantics" paragraph stating: omitting the field and sending `"closed_world_filtering": null` are semantically equivalent — both map to "use instance default." This equivalence must be documented in the generated OpenAPI spec as a note on the field.

**Spec location:** REQ-004 (added "Null-equals-absent semantics" paragraph), REQ-005 (reference to same semantics).

---

#### MEDIUM-6 — Audit-schema breaking-change classification missing (API Contract)
**Finding:** REQ-013 adds a new field to the audit schema without classifying the change as backwards-compatible additive or breaking.

**Resolution:** REQ-013 now explicitly classifies the addition as a **backwards-compatible additive extension** and names the breaking-change risk: downstream consumers with closed-set schema validation (Pydantic `extra='forbid'`, JSON Schema `additionalProperties: false`) will fail. SPEC-006's audit-entry schema must be declared open-set before this lands; if it is currently closed-set, that is a SPEC-006 amendment required as a dependency.

**Spec location:** REQ-013 — "Schema compatibility" paragraph added.

---

#### MEDIUM-7 — EDGE-008 degenerate config no runtime signal (Reliability)
**Finding:** Empty `strong_anchors` + `closed_world_filtering: true` silently causes all quasi-identifiers to always suppress; no runtime detection.

**Resolution:** EDGE-008 updated to require a startup `WARNING` log line when `closed_world_filtering: true` AND `strong_anchors: []`. Warning text is specified verbatim. The choice of WARNING (not ValidationError) is documented: intentional always-suppress is valid, if unusual; the warning enables diagnosis without blocking deliberate use.

**Spec location:** EDGE-008 — replaced single paragraph with "Degenerate-configuration detection (resolved)" block with specified WARNING text.

---

#### MEDIUM-8 — PERF-001 set-conversion and tail behavior unspecified (Performance)
**Finding:** Per-call list-to-set conversion was documented as an implementation detail but not resolved; 50k-cell document path would repeat it per call. Tail behavior at >100 spans not bounded.

**Resolution:** PERF-001 updated with two new sub-sections:
- **Set pre-computation requirement (resolved):** `Settings` exposes `strong_anchors_set: frozenset[str]` and `quasi_identifiers_set: frozenset[str]` computed once at config-load. `filter_by_closed_world()` receives `frozenset` values (not lists), eliminating per-call conversion.
- **Tail behavior (resolved):** `<1ms` guarantee applies to 100-span case only. 10k+ span inputs complete in O(n) but are outside the v1 success criterion. Performance validation suite adds 10k-span and frozenset-verification benchmarks.

**Spec location:** PERF-001 (two new sub-sections added), Validation Strategy — Performance Validation (two new benchmark items added), Critical Implementation Considerations item 7 updated to reference frozenset.

---

#### MEDIUM-9 — HIPAA Safe Harbor framing informational not detectable (Privacy)
**Finding:** REQ-010 config comment said "do not enable in Safe Harbor contexts" — a documentation-only warning with no runtime enforcement.

**Resolution:** REQ-020 added: new `regulatory_scope: list[str] = ["GDPR"]` Settings field. When `"HIPAA"` is in the list and `closed_world_filtering: true`, startup raises `ValidationError` with the specific incompatibility message. Default `["GDPR"]` is backwards-compatible. Config comment in REQ-010 updated to reference `regulatory_scope` and `allow_per_request_closed_world_override`. Threat-model paragraph (gameable-narrative, HIPAA, Art. 9) must also appear verbatim in `docs/customizations.md` — this second publication point is part of REQ-020.

**Spec location:** REQ-020 (new requirement), REQ-010 (config comment text — HIPAA and OVERRIDE blocks added).

---

### LOW Findings (addressed)

#### LOW-1 — Verbose mode interaction unspecified (Security)
**Resolution:** SEC-003 added (new): v1 verbose mode does NOT reveal suppressed spans; it reveals only post-filter span set plus the effective `closed_world_filtering` flag value. Pre-filter span disclosure is deferred to v2. The diagnostic path (audit log `closed_world_suppressed_count`) is named. This is a documented v1 limitation.
**Spec location:** SEC-003 (new non-functional requirement under SEC-002).

#### LOW-2 — MODULE-005 shallow-by-intent justification missing (Module Depth)
**Resolution:** Added one-line justification: "MODULE-005 is a forward-compat seam for future per-fixture request parameters; it would be re-implemented as a more general fixture-overrides mechanism in v2."
**Spec location:** MODULE-005 — "Justification (shallow by intent)" paragraph added after Risk.

#### LOW-3 — Per-call set conversion not benchmarked (Performance)
**Resolution:** Addressed together with MEDIUM-8. Set pre-computation requirement eliminates the per-call conversion entirely. Benchmark verifying frozenset at call site added to Validation Strategy.
**Spec location:** PERF-001 set pre-computation sub-section, Validation Strategy — Performance Validation.

#### LOW-4 — No uniqueness constraint within a list (Data Modeling)
**Resolution:** REQ-011 rule 2 (duplicate check) raises `ValidationError` on duplicates within a list.
**Spec location:** REQ-011 — rule 2 added.

#### LOW-5 — No API versioning strategy documented (API Contract)
**Resolution:** "API Versioning Posture" section added to Implementation Notes. Acknowledges unversioned-API posture; states v2 additions are backwards-compatible additive; v3+ breaking semantics will require a versioning discussion.
**Spec location:** Implementation Notes — "API Versioning Posture" section added.

#### LOW-6 — `RecognizerResult.entity_type` dependency undocumented (Reliability)
**Resolution:** Critical Implementation Consideration item 8 added: filter depends on `RecognizerResult.entity_type` attribute name (Presidio SDK ≥ 2.x); re-validate on Presidio major version bumps.
**Spec location:** Critical Implementation Considerations — item 8 added.

---

### Summary

| Severity | Pre-fix | Post-fix | Delta |
|----------|---------|----------|-------|
| HIGH     | 2       | 0        | −2    |
| MEDIUM   | 9       | 0        | −9    |
| LOW      | 6       | 0        | −6    |

All 17 findings resolved. No findings deferred without disposition. The HIGH finding count decreases by 2 (mandatory for the flow to continue). The MEDIUM count decreases by 9. All 6 LOW findings are addressed (not deferred).

**New requirements added:** REQ-020 (`regulatory_scope` config field), REQ-021 (entity catalog classification column), SEC-001a (operator config gate for per-request override), SEC-003 (verbose mode v1 scope), REL-001 (determinism/retry-variance clarification), FAIL-005 (unrecognized entity type warning), PERF-001 sub-sections (set pre-computation, tail behavior).

**RISK-004 disposition:** RISK-004 ("NRP classification under GDPR Art. 9 — review panel rejects quasi-identifier") is now resolved. The spec takes the quasi-identifier position with a documented lawful-basis position and operator escape hatch. RISK-004 can be closed.

---

## Iteration 2 — 2026-05-13

**Trigger:** Iteration 1 verdict was STOP AND RECONSIDER; fix subagent ran and claimed 17/17 findings resolved (2 HIGH, 9 MEDIUM, 6 LOW → 0/0/0); this is the iteration-2 verification pass by the 7-specialist panel against the updated SPEC-008.

### Executive Summary (Iteration 2)

The fix subagent made substantial, real edits — REQ-017 rewrites the NRP/Art. 9 position decisively, SEC-001 expands into four explicit (a)–(d) sub-clauses, SEC-001a adds the operator config gate, REQ-013 specifies document-path `null` sentinel and the new `closed_world_filtering_override` audit field, REQ-020 introduces runtime `regulatory_scope` enforcement, REQ-021 establishes the canonical classification column, PERF-001 mandates `frozenset` pre-computation. The two HIGH findings (REQ-017 deferral; SEC-001 trust-model under-spec) are genuinely resolved — these are not placating edits, they take positions. However, the panel finds **0 HIGH, 5 MEDIUM, 4 LOW** new or persisting findings. The MEDIUM cluster is concentrated in **internal inconsistencies introduced by the fix itself**: MODULE-001's public signature still declares `list[str]` parameters and Hides "set conversion of list parameters" while PERF-001 and Critical Consideration #7 now mandate `frozenset[str]` parameters — these contradict each other within the same spec. MODULE-002's "Hides" still says frozen-set pre-computation is optional ("if desired"). MODULE-003 and MODULE-004 do not mention the new `closed_world_filtering_override` audit field that REQ-013 requires them to thread. RISK-004's Mitigation paragraph still references the deleted "REQ-017 gates the spec sign-off on privacy-specialist confirmation" gate language. Stakeholder Sign-off line 647 still says the privacy specialist must "confirm NRP default classification" — exactly the gate REQ-017's rewrite removed. These are stale-text regressions: the new normative sections were added, but the older normative sections referencing the old positions were not updated to match. This is a forgivable but real iteration cost — the fix subagent edited section-by-section without doing a cross-reference sweep. Two new MEDIUM concerns also surface: REQ-020's HIPAA gate only fires against the instance default, not the per-request override (so a caller can still relax in a HIPAA-Safe-Harbor-claiming deployment); REQ-011 rule 3's "canonical entity-type set derived from docs/supported-entities.md" is forward-referenced without specifying where the constant lives (Python module? generated from doc? maintained manually?).

### Verdict (Iteration 2)

**REVISE BEFORE PROCEEDING**

No HIGH findings. The two HIGH findings from iteration 1 are genuinely resolved with substantive, position-taking edits — not placation. However, 5 MEDIUM findings (mostly internal inconsistencies introduced by the fix and two new gaps not previously surfaced) reach the panel-rule threshold for REVISE BEFORE PROCEEDING (3+ MEDIUM). One of the MEDIUMs is cross-domain (MODULE-001 signature ↔ PERF-001 type contract flagged by module-depth, performance, and api-contract specialists), which independently triggers REVISE under the cross-domain MEDIUM rule. The pattern across these findings is the same: the fix subagent added new normative sections without sweeping the older sections that referenced the now-changed positions. A single revision pass over RISK-004, MODULE-001 (public interface and Hides), MODULE-002 (Hides), MODULE-003 (Public Interface), MODULE-004 (Public Interface and Spec refs), and Stakeholder Sign-off should close all 5 MEDIUMs. The flow proceeds to iteration 3 (final fix iteration of max 3) per the progress-stall protocol, which passes: HIGH strictly decreased (2 → 0), MEDIUM strictly decreased (9 → 5).

### Iteration 1 → Iteration 2 Finding Count Comparison

| Severity | Iteration 1 | Iteration 2 | Change |
|----------|-------------|-------------|--------|
| HIGH | 2 | 0 | decreased (−2) |
| MEDIUM | 9 | 5 | decreased (−4) |
| LOW | 6 | 4 | decreased (−2) |

**Progress-stall check (per SDD flow Step 3c):** **PASS**
- HIGH was non-zero in iteration 1 (2) and HIGH strictly decreased in iteration 2 (0 < 2) → PASS the HIGH-must-decrease rule.
- MEDIUM strictly decreased (5 < 9) even though verdict is REVISE → PASS the MEDIUM-must-decrease rule.
- LOW strictly decreased (4 < 6) — not gating but consistent with overall progress.
- Result: flow continues to iteration 3 of the fix loop (the final permitted iteration of max 3).

### Placation Audit — Iteration 1 Findings Verification

For each iteration-1 finding the fix subagent claimed resolved, the panel verified the actual spec edit:

| Iter-1 Finding | Fix claim | Spec evidence | Placation verdict |
|----------------|-----------|---------------|---------------------|
| HIGH-1 (REQ-017 NRP/Art.9 gate) | "Decisively retained as quasi-identifier with operator Art. 9 responsibility clause" | Lines 264–284: full rewrite with rationale, residual-risk clause, operator-escape-hatch instruction, HIPAA cross-reference, removal of panel-gate language | NOT PLACATING — substantive position-taking edit |
| HIGH-2 (SEC-001 trust model) | "Expanded into (a)–(d) clauses + SEC-001a config gate + REQ-013 audit field" | Lines 324–343: SEC-001 (a)–(d) all present; SEC-001a present with INFO log spec; REQ-013 carries `closed_world_filtering_override` field | NOT PLACATING — substantive edits across SEC-001, SEC-001a, and REQ-013 |
| MED-1 (MODULE-001 return type) | "Tuple return is sole interface; alternative rejected" | Lines 477–496: tuple is sole signature; "Return type decision (resolved)" paragraph rejects the alternative explicitly | NOT PLACATING for the return-type decision specifically — BUT introduced a NEW inconsistency on the parameter types (`list[str]` vs `frozenset[str]`); see Iteration-2 MED finding below |
| MED-2 (audit doc-path gap) | "Document-path sets `null` sentinel; schema declared open-set" | Line 236: explicit null sentinel for `/api/documents/upload` and `/documents/submit`; schema-compatibility paragraph names the open-set requirement | NOT PLACATING |
| MED-3 (unvalidated entity strings) | "REQ-011 expanded to type/duplicate/canonical-set rules + FAIL-005" | Lines 218–224 and FAIL-005 at 434–439 — three numbered rules; FAIL-005 distinguishes strict vs non-strict modes | NOT PLACATING — but the "canonical set" source-of-truth is under-specified; see Iteration-2 MED finding below |
| MED-4 (tripartite implicit) | "REQ-021 documents classification column requirement" | REQ-021 at lines 252–255 | PARTIAL — adds a doc/process requirement but no runtime enforcement; see Iteration-2 LOW |
| MED-5 (null-equals-absent semantics) | "REQ-004 + REQ-005 explicit paragraph" | Line 167: "Null-equals-absent semantics (explicit):" paragraph in REQ-004; line 170 references same in REQ-005 | NOT PLACATING |
| MED-6 (audit schema breaking change) | "Classified as backwards-compatible additive; SPEC-006 must be open-set" | Line 238: explicit paragraph | NOT PLACATING |
| MED-7 (EDGE-008 degenerate config) | "Startup WARNING with verbatim text" | Lines 393–399: WARN text specified verbatim; rationale for WARN-not-error documented | NOT PLACATING |
| MED-8 (PERF-001 set conversion + tail) | "Set pre-computation mandatory; tail behavior bounded" | Lines 317–319: both sub-sections present and substantive | NOT PLACATING — BUT introduced inconsistency with MODULE-001 signature; see Iteration-2 MED finding |
| MED-9 (HIPAA Safe Harbor) | "REQ-020 regulatory_scope with runtime ValidationError" | REQ-020 at lines 288–296 with verbatim error message | NOT PLACATING — BUT the gate only catches instance-default config, not per-request overrides; see Iteration-2 MED finding |
| LOW-1 through LOW-6 | All claimed resolved | SEC-003 at 348–353, MODULE-005 justification at 578, REQ-011 rule 2 at 222, API Versioning Posture at 692–694, Critical Consideration #8 at 711 | NOT PLACATING (all six addressed) |

**Placation audit verdict:** No iteration-1 finding was placated. All claimed resolutions are backed by substantive normative text. The iteration-2 findings below are **new issues introduced by the fix** (stale references to removed gates, internal type-signature contradictions, gap in the new HIPAA gate's coverage) or **previously-unsurfaced gaps** (canonical-set source-of-truth, MODULE-003/MODULE-004 not threading the new audit field) — not the same findings re-raised.

### Findings by Specialist (Iteration 2)

#### Security Findings (Iteration 2)

- **MEDIUM** REQ-020's HIPAA gate only covers instance default, not per-request override
  - Evidence: REQ-020 lines 289–294 specify that startup `ValidationError` fires when `"HIPAA"` is in `regulatory_scope` AND `closed_world_filtering: true` is set. The check is against the instance default (`Settings.closed_world_filtering`). It does NOT check whether a per-request body can supply `closed_world_filtering: true` and bypass the deployment-time guard. Specifically: an operator deploys with `regulatory_scope: ["HIPAA"]` AND `closed_world_filtering: false` (passes startup validation) AND `allow_per_request_closed_world_override: true` (default). A caller now sends `{"closed_world_filtering": true}` in the request body and the relaxation knob fires — HIPAA Safe Harbor incompatibility realized at runtime, not detected.
  - Risk: REQ-020's value proposition is "detectable runtime error rather than documentation-only warning." Per-request override defeats this entirely. A HIPAA-deploying operator who relies on REQ-020 to catch misconfigurations has a false sense of safety.
  - Resolution: Extend REQ-020 to also gate the per-request override path. When `"HIPAA"` is in `regulatory_scope`, the per-request `closed_world_filtering: true` override is silently rejected (or returns HTTP 400) and the audit log records the rejection. Alternative: when `"HIPAA"` is in `regulatory_scope`, force `allow_per_request_closed_world_override = false` automatically with a startup INFO log line.
  - Specialist: security
  - Anti-pattern: defense-in-depth gap; security control surface mismatch between startup validation and runtime request handling.

#### Performance Findings (Iteration 2)

- **MEDIUM** MODULE-001 public signature contradicts PERF-001 set pre-computation contract
  - Evidence: MODULE-001 Public Interface lines 478–483 declares the function signature as `strong_anchors: list[str], quasi_identifiers: list[str]`. The "Hides" list at line 504 says "Set conversion of list parameters (done once inside the function, not per caller)." Both are stale post-fix. PERF-001 line 317 (newly added in iter-1 fix): "`filter_by_closed_world()` function receives these `frozenset` values (not the raw `list[str]`), eliminating per-call list-to-set conversion." Critical Implementation Consideration #7 line 710 (also newly added) reinforces: "`filter_by_closed_world()` receives `frozenset[str]` values for `strong_anchors` and `quasi_identifiers`... not raw `list[str]`." The Performance Validation benchmark at line 636 even asserts: "`strong_anchors_set` and `quasi_identifiers_set` are `frozenset` (not `list`) at the point `filter_by_closed_world()` is called."
  - Risk: An implementer reading MODULE-001 will type the parameters as `list[str]` and add a `set(strong_anchors)` conversion inside the function (consistent with the "Hides" entry). The benchmark at line 636 then fails. The PR cycle resolves it but the spec has already created argument fuel — exactly the deep-module-clarity violation that iter-1 MED-1 flagged about return type, now recurring on the parameter type. The contradiction crosses three specialist domains: module-depth (signature ambiguity), performance (the set-pre-computation guarantee depends on the signature), api-contract (the function's parameter type is its public contract).
  - Resolution: Update MODULE-001's Public Interface signature to `strong_anchors: frozenset[str], quasi_identifiers: frozenset[str]`. Remove "Set conversion of list parameters (done once inside the function, not per caller)" from the "Hides" list. Add a one-line note: "Parameters are pre-computed `frozenset` values supplied by `Settings.strong_anchors_set` / `quasi_identifiers_set` properties; the filter never receives raw lists." This is the single most consequential stale-text issue introduced by the fix.
  - Specialist: performance (primary) + module-depth + api-contract (cross-domain)

#### Data Modeling Findings (Iteration 2)

- **MEDIUM** REQ-011 rule 3's "canonical entity-type set" has no source-of-truth specification
  - Evidence: REQ-011 rule 3 lines 224 (newly added in iter-1 fix): "Each entry in `strong_anchors` and `quasi_identifiers` is checked against the canonical entity-type set derived from `docs/supported-entities.md` (the enumerated constant maintained alongside the spec)." The parenthetical raises more questions than it answers: (a) does the constant live in a Python module (e.g., `src/redakt/entity_catalog.py`)? (b) Is it generated from `docs/supported-entities.md` at build time or maintained by hand and drift-tested? (c) If the doc and the constant drift, which wins (validation passes silently against stale catalog vs. validation hard-fails)? (d) Where is the constant's update lifecycle defined — REQ-021 mentions PR-review for adding entity types but is silent on the runtime constant. REQ-021 also says "the default sets in REQ-001 and REQ-002 must be consistent with this column" but provides no enforcement mechanism (no CI lint, no schema test).
  - Risk: The validation rule that catches operator typos like `"PEROSN"` depends on a constant whose location and update process is not specified. Implementation will pick one of (a)/(b)/(c)/(d); a future entity type addition will break the validation invisibly (operator adds a new entity to `docs/supported-entities.md` but forgets the Python constant — the new entity flags as "unrecognized typo" with `strict_entity_validation: true`, raising a spurious startup error).
  - Resolution: Add a new REQ or extend REQ-011 to specify: (a) the constant's location (e.g., `src/redakt/entity_catalog.py` with a single `CANONICAL_ENTITY_TYPES: frozenset[str]` constant); (b) the update mechanism (manual? generated? checked against the doc by a CI test?); (c) the precedence rule when doc and constant disagree (recommend: constant wins for validation; CI lints for drift). Specify whether REQ-021's classification column is a separate constant or derived from the same source.
  - Specialist: data-modeling
  - Anti-pattern: forward-referenced shared constant without source-of-truth specification.

#### API Contract Findings (Iteration 2)

- **MEDIUM** MODULE-003 and MODULE-004 do not thread the new `closed_world_filtering_override` audit field
  - Evidence: REQ-013 lines 234 (newly added in iter-1 fix): "The audit entry also includes `closed_world_filtering_override: bool | null` indicating whether the per-request override was used." This requires the per-request override value to flow through `run_detection()` / `run_anonymization()` to the audit logger. MODULE-003 (Per-request override threading) lines 528–546 describes the threading but does NOT mention the audit-log forwarding of the override flag. Its "Hides" list says "the wiring from request model field → function parameter → `filter_by_closed_world()` call → audit log field" — but only references `closed_world_suppressed_count` as the audit field, not `closed_world_filtering_override`. MODULE-004 (Audit logging extension) lines 548–556 describes only `closed_world_suppressed_count: int = 0` as the new audit parameter; it does NOT mention the new override field. Critical Implementation Consideration #4 line 707 says "Audit logging must receive the suppressed count and override flag value" — the only place the override field is named in the threading context, but MODULE-003 and MODULE-004 (the modules responsible for the threading) are silent.
  - Risk: Implementer reads MODULE-003 and MODULE-004 and implements only the suppressed-count threading. The `closed_world_filtering_override` audit field that SEC-001 (d) and REQ-013 require is missing — and SEC-001 (d) is the audit-visibility clause that closes the HIGH-2 finding from iter-1. The HIGH-2 resolution is contingent on this threading being implemented; the modules that implement the threading don't specify it.
  - Resolution: Update MODULE-003 Public Interface to thread the override boolean (or null) to the audit logger. Update MODULE-004 Public Interface to accept `closed_world_filtering_override: bool | None = None` parameter alongside `closed_world_suppressed_count: int = 0`. Add to MODULE-004 Spec refs: REQ-013 (override), SEC-001 (d).
  - Specialist: api-contract (primary) + module-depth + security (cross-domain — this gap weakens the HIGH-2 resolution)

#### Module Depth Findings (Iteration 2)

- **MEDIUM** Stale-text regression cluster: RISK-004, Stakeholder Sign-off, MODULE-002 "Hides" reference deleted/changed positions
  - Evidence: Three places in the spec still reference removed or changed positions:
    1. **RISK-004 lines 674–676:** "Manifestation: the review-panel privacy specialist rejects NRP as a quasi-identifier; NRP must move to always-emit. Mitigation: REQ-017 gates the spec sign-off on privacy-specialist confirmation; the implementation can treat NRP classification as a single-line config change." This describes the old REQ-017 panel-gate behavior that the fix explicitly removed. REQ-017 line 284 says "The panel-gate language ('the privacy specialist must confirm') is removed — the spec takes the position." RISK-004's Mitigation paragraph is now obsolete.
    2. **Stakeholder Sign-off line 647:** "**Privacy specialist (review panel):** Confirm NRP default classification as quasi-identifier (or move to always-emit). See REQ-017." This requires the privacy specialist to confirm — exactly the gate REQ-017's rewrite removed.
    3. **MODULE-002 "Hides" line 522:** "set-precomputation of `strong_anchors` and `quasi_identifiers` as frozen sets for O(1) lookup if desired (implementation detail)." The phrase "if desired" is now wrong — PERF-001's set-pre-computation requirement (lines 317–318) makes it mandatory, not optional.
    4. **MODULE-001 "Hides" line 504:** "Set conversion of list parameters (done once inside the function, not per caller)." Stale — captured in the Performance MEDIUM above; mentioned here to underscore that this is a stale-text regression pattern, not an isolated incident.
    5. **Note on `review_panel` line 19:** "The closed-world assumption's applicability to Art. 9 categories was reviewed by the privacy specialist during the panel (2026-05-13); the resolution is captured in REQ-017." This is past-tense framing of a review that was still in progress when the iter-1 fix was written (the iter-2 review you're reading is the actual conclusion). The framing pre-dates the verdict.
  - Risk: A reader who lands on RISK-004 or Stakeholder Sign-off as their entry point gets the iter-1-vintage position and acts on it. The implementer skips REQ-017's lawful-basis clauses ("the privacy specialist will resolve") because RISK-004 says the mitigation is a config change. The compliance reviewer reads "Confirm NRP default classification" in Stakeholder Sign-off, expects a privacy specialist gate, and is confused when REQ-017 says the gate is removed. Internal inconsistency erodes the spec's authority — a reader cannot tell which paragraph is current.
  - Resolution: Cross-reference sweep. Update RISK-004 Manifestation/Mitigation to reflect the resolved position (NRP retained as quasi-identifier; operator Art. 9 responsibility; escape hatch is moving NRP to always-emit). Replace Stakeholder Sign-off line 647 with "Operator (Pablo / Memodo): Acknowledge the Art. 9 operator responsibility for NRP suppression per REQ-017." Update MODULE-002 "Hides" to remove "if desired" — set-precomputation is mandatory. Update Note on `review_panel` to past tense only after iter-2 verdict completes (today). Update MODULE-001 "Hides" per the Performance MEDIUM resolution.
  - Specialist: module-depth (primary) + privacy + api-contract (the stale text crosses domains)
  - Anti-pattern: section-by-section editing without cross-reference sweep — fix iter-1 added new normative sections without updating older sections that referenced the now-changed positions.

#### Reliability Findings (Iteration 2)

(Checked: REL-001 added cleanly; EDGE-008 startup WARN added; FAIL-005 strict/non-strict semantics covered; degenerate-config detection covered; document-path null sentinel addresses the document-audit gap. No new reliability findings rise to MEDIUM.)

- **LOW** REQ-011 rule 3 strict-mode escalation has no migration path
  - Evidence: REQ-011 rule 3 introduces `strict_entity_validation: bool = False`. Operators who flip to `True` after months of running with non-strict will discover any historic typos at the next startup — but the spec doesn't say what happens for an operator currently running with strict=True who upgrades to a Redakt version that adds a new entity type to the canonical set. Their config (with the new type not in either list) now passes (it's always-emit), but if they had previously added the new type to their config in advance of the recognizer landing (e.g., to test forward-compat), it would have failed validation.
  - Risk: Minor; operators rarely use `strict_entity_validation: true`. Adds friction at startup but no production impact.
  - Resolution: Add a one-line note to REQ-011 rule 3 stating "Operators using `strict_entity_validation: true` should consult `docs/supported-entities.md` after Redakt upgrades to confirm their `strong_anchors`/`quasi_identifiers` lists are consistent with the current canonical set."

#### Privacy Findings (Iteration 2)

- **LOW** EDGE-009 healthcare guidance not symmetric with REQ-020 HIPAA enforcement
  - Evidence: EDGE-009 line 403: "Healthcare or social-services contexts should not enable `closed_world_filtering`." REQ-020 only enforces HIPAA; healthcare contexts outside US HIPAA (e.g., German Krankenhaus under GDPR Art. 9, UK NHS, social services) have no runtime gate. The asymmetry: HIPAA gets a `ValidationError`; non-HIPAA healthcare gets a config comment.
  - Risk: A German healthcare operator who is GDPR-only, not HIPAA-scoped, reads EDGE-009 ("healthcare or social-services contexts should not enable"), enables the flag anyway because there's no runtime gate, and processes Art. 9 patient data through the closed-world filter. REQ-017 covers NRP specifically; it does not cover the broader healthcare gameable-narrative case from EDGE-009.
  - Resolution: Extend REQ-020 to accept additional regulatory scope values (`"HIPAA"`, `"GDPR-HEALTHCARE"`, `"UK-NHS"`, `"SOCIAL-SERVICES"`) or document explicitly that REQ-020's enforcement is HIPAA-only and non-HIPAA healthcare operators must rely on the config comment and EDGE-009. The asymmetry should be acknowledged, not hidden.

- **LOW** REQ-017 escape hatch is binary — no composition with re-id-risk suppression
  - Evidence: REQ-017 lines 280: "Operators who cannot accept the residual Art. 9 risk... MUST move `NRP` from `quasi_identifiers` to neither list (always-emit)." This forces the operator to choose: closed-world re-id suppression for NRP (lose Art. 9 trail) OR always-emit NRP (lose re-id suppression). There is no path to "suppress NRP under closed-world filter AND maintain Art. 9 audit trail separately."
  - Risk: An operator who wants both protections has no spec-supported path. They are forced to choose. The spec's framing presents this as the operator's responsibility but does not acknowledge that the composition gap exists at the design level.
  - Resolution: Either (a) acknowledge in REQ-017 that the composition is genuinely unsupported in v1 (which it is) and document a v2 path (e.g., per-entity-class audit fields like `nrp_suppressed_count` distinct from `closed_world_suppressed_count`), or (b) extend REQ-013 with a `suppressed_by_category: dict[str, int]` audit field that gives operators category-level visibility while preserving the re-id suppression. Option (a) is the lighter touch; option (b) is the principled fix.

- **LOW** Note on `review_panel` past-tense framing pre-dates iter-2 verdict
  - Evidence: Line 19: "The closed-world assumption's applicability to Art. 9 categories was reviewed by the privacy specialist during the panel (2026-05-13); the resolution is captured in REQ-017." Past tense framing for a review still in progress (iter-2 is the actual finalization).
  - Risk: A reader who returns to this spec in iter-3 (if reached) or post-merge will see the past-tense framing and assume the panel concluded — they may not realize the spec went through multiple iterations.
  - Resolution: Either move this note to the appendix as a panel-history artifact or rephrase to "The closed-world assumption's applicability to Art. 9 categories was reviewed by the privacy specialist panel across iterations 1–N (2026-05-13)." Minor.

### Cross-Specialist Observations (Iteration 2)

Two patterns surfaced across multiple specialist lenses:

1. **Stale-text regression after position changes.** Performance MED (MODULE-001 signature ↔ PERF-001 frozenset contract), Module Depth MED (RISK-004, Stakeholder Sign-off, MODULE-002 "Hides", review_panel note), and API Contract MED (MODULE-003/MODULE-004 missing the new audit field) all converge: the fix subagent added new normative sections in iter-1 without sweeping older sections to remove stale references. This is the dominant iteration-2 pattern. A single cross-reference sweep closes all three findings.

2. **Defense-in-depth gaps in the new runtime-enforcement layer.** Security MED (REQ-020 doesn't gate per-request override path) and Privacy LOW (EDGE-009 healthcare gate is HIPAA-only) both pin on REQ-020's enforcement scope being narrower than its motivating threat model. The fix introduced runtime enforcement; the runtime enforcement has gaps.

### Recommended Actions Before Proceeding (Iteration 2)

In priority order for iteration 3 fix:

1. **[MEDIUM] [MODULE-001 / Performance + Module Depth + API Contract]** Update MODULE-001 Public Interface signature to `strong_anchors: frozenset[str], quasi_identifiers: frozenset[str]`. Remove the "Set conversion of list parameters" entry from "Hides." Add a one-line note that parameters are pre-computed frozensets from `Settings`. This is the single highest-impact fix.

2. **[MEDIUM] [MODULE-003 + MODULE-004 / API Contract + Security]** Update MODULE-003 to thread the per-request override boolean to the audit logger. Update MODULE-004 Public Interface to accept `closed_world_filtering_override: bool | None = None`. Update MODULE-004 Spec refs to include REQ-013 (override) and SEC-001 (d).

3. **[MEDIUM] [REQ-020 / Security]** Extend REQ-020 to also gate the per-request override path under HIPAA scope. Specify either (a) silent rejection / HTTP 400, or (b) auto-forcing `allow_per_request_closed_world_override = false` when HIPAA is in `regulatory_scope`. Document the choice.

4. **[MEDIUM] [RISK-004, Stakeholder Sign-off line 647, MODULE-002 "Hides", line 19 / Module Depth + Privacy]** Cross-reference sweep:
   - Update RISK-004 Manifestation and Mitigation to reflect the resolved REQ-017 position.
   - Replace Stakeholder Sign-off line 647 with operator-acknowledgment language (no panel gate).
   - Remove "if desired" from MODULE-002 "Hides" — set-precomputation is mandatory.
   - Move line 19's past-tense framing to a panel-history appendix or update it.

5. **[MEDIUM] [REQ-011 + REQ-021 / Data Modeling]** Specify the canonical entity-type set source-of-truth: (a) where the constant lives, (b) how it's maintained, (c) precedence when doc and constant drift. Specify whether REQ-021's classification column is derived from or independent of the constant.

6. **[LOW] [REQ-011 rule 3 / Reliability]** One-line note about post-upgrade strict-mode migration.

7. **[LOW] [REQ-020 + EDGE-009 / Privacy]** Acknowledge the HIPAA-only enforcement scope; document that non-HIPAA healthcare gets only the config comment.

8. **[LOW] [REQ-017 / Privacy]** Acknowledge the closed-world-suppression vs Art. 9-audit-trail composition gap; document v2 path (e.g., per-category audit fields) or accept the binary operator choice.

9. **[LOW] [line 19 / Privacy]** Past-tense framing for in-progress review. Rephrase or move to appendix.

### Iteration 2 Panel Metadata

- **Specialists with no concerns:** reliability (one LOW finding only, no MEDIUM).
- **Specialists with findings:** security=1 MED, performance=1 MED (shared with module-depth and api-contract), data-modeling=1 MED, api-contract=1 MED (shared with security on MODULE-003/004), module-depth=1 MED (shared with privacy on stale-text), reliability=1 LOW, privacy=3 LOW.
- **Total findings (post-dedup):** HIGH=0, MEDIUM=5 (one cross-domain across 3 specialists, one cross-domain across 2 specialists, three single-specialist), LOW=4.
- **Comparison to iteration 1:** strict decrease across all severities. HIGH: 2 → 0 (−2). MEDIUM: 9 → 5 (−4). LOW: 6 → 4 (−2). Progress-stall check PASSES; flow continues to iter-3.
- **Panel execution mode:** Same as iter-1 — the panel orchestrator applied each specialist's canonical vocabulary payload and named anti-pattern set directly against the updated SPEC-008, the iter-1 review document (including the "Findings Addressed — Iteration 1" appendix), and ADR-0007. The Task primitive was not used (consistent with iter-1); fresh-context-per-specialist isolation was approximated by applying each specialist's named anti-pattern list as a discrete pass over the updated spec.
- **Placation audit:** All 17 iteration-1 findings verified against the actual spec edits. No placating edits detected. New findings represent (a) internal inconsistencies introduced by section-by-section editing without cross-reference sweep, (b) gaps in the new runtime enforcement layer (REQ-020), and (c) previously-unsurfaced issues (canonical-set source-of-truth, MODULE-003/004 audit-field threading).

---

## Findings Addressed — Iteration 2

**Fix subagent:** claude-sonnet-4-6
**Date:** 2026-05-13
**Iteration:** 2 of max 3 (final)
**Pre-fix finding count:** HIGH=0, MEDIUM=5, LOW=4

---

### MEDIUM Findings

#### MEDIUM-A1 — REQ-020 HIPAA gate doesn't cover per-request override (Security)
**Finding:** REQ-020's startup `ValidationError` fires against the instance default (`closed_world_filtering: true` in config). A HIPAA deployment with `closed_world_filtering: false` + `allow_per_request_closed_world_override: true` could still receive per-request `closed_world_filtering: true` and realize Safe Harbor incompatibility at runtime.

**Resolution:** REQ-020 extended with an explicit "Per-request override gating under HIPAA scope" clause. When `"HIPAA"` is in `regulatory_scope`, the implementation auto-forces `allow_per_request_closed_world_override = false` at config-load (via Pydantic `@model_validator`). A startup INFO log line is specified verbatim. If the operator explicitly set `allow_per_request_closed_world_override: true` alongside HIPAA scope, the `true` is silently overridden to `false` (not a fatal error — it's automatic safety enforcement). An explicit "Scope limitation" paragraph acknowledges that non-HIPAA healthcare contexts are not covered by runtime enforcement — this asymmetry is now documented, not hidden.

**Spec location:** REQ-020 — "Per-request override gating under HIPAA scope (extended)" sub-section added; "Scope limitation (explicit)" sub-section added.

---

#### MEDIUM-A2 — MODULE-001 public signature contradicts PERF-001 frozenset contract (Performance + Module Depth + API Contract)
**Finding:** MODULE-001 Public Interface declared `strong_anchors: list[str], quasi_identifiers: list[str]`. Its "Hides" listed "Set conversion of list parameters (done once inside the function, not per caller)." Both were stale post-iter-1 fix: PERF-001, Critical Consideration #7, and the Performance Validation benchmark all mandated `frozenset[str]` parameters pre-computed by `Settings`.

**Resolution:** MODULE-001 Public Interface signature updated to `strong_anchors: frozenset[str], quasi_identifiers: frozenset[str]`. Docstring extended with explicit note: "Parameters are pre-computed frozenset values supplied by `Settings.strong_anchors_set` / `Settings.quasi_identifiers_set`; the filter never receives raw lists." "Set conversion of list parameters" entry removed from "Hides" and replaced with a note explaining that conversion is handled once at config-load by MODULE-002 (Settings), not inside the filter. MODULE-002 "Hides" updated: "if desired (implementation detail)" → "mandatory per PERF-001, not optional."

**Spec location:** MODULE-001 "Public Interface" signature, MODULE-001 "Hides", MODULE-002 "Hides."

---

#### MEDIUM-A3 — MODULE-003/MODULE-004 don't thread `closed_world_filtering_override` audit field (API Contract + Security)
**Finding:** REQ-013 specifies `closed_world_filtering_override: bool | null` in every audit entry (added in iter-1 fix). MODULE-003 "Hides" referenced only `closed_world_suppressed_count` as the audit field. MODULE-004 "Public Interface" declared only `closed_world_suppressed_count: int = 0` as the new parameter — the override field was absent. Critical Consideration #4 named both fields but the modules responsible for threading them were silent on the override field.

**Resolution:** MODULE-003 "Hides" rewritten to explicitly name both audit fields. The threading logic for `closed_world_filtering_override` is specified: the raw per-request field value (before REPLACE merge, before SEC-001a gate) must be captured and forwarded separately from the resolved effective boolean. Semantics for the `allow_per_request_closed_world_override: false` case (override is silently ignored; field records `null`) are documented. MODULE-003 Spec refs updated to add REQ-013, SEC-001a. MODULE-004 "Public Interface" updated with an explicit two-parameter signature for both `log_detection()` and `log_anonymization()`, including `closed_world_filtering_override: bool | None = None`. Document-upload path sentinel (`null`) specified for both fields. MODULE-004 Spec refs updated to add SEC-001 (d) and SEC-001a.

**Spec location:** MODULE-003 "Hides" (complete replacement), MODULE-003 "Spec refs" (added REQ-013, SEC-001a), MODULE-004 "Public Interface" (two-parameter function signatures added), MODULE-004 "Spec refs" (added SEC-001 (d), SEC-001a).

---

#### MEDIUM-A4 — Stale-text regression cluster: RISK-004, Stakeholder Sign-off, MODULE-002 "Hides", line 19 (Module Depth + Privacy)
**Finding:** Four places referenced removed or changed positions from iter-1: (1) RISK-004 described the old panel-gate behavior ("REQ-017 gates the spec sign-off on privacy-specialist confirmation"); (2) Stakeholder Sign-off asked privacy specialist to "Confirm NRP default classification"; (3) MODULE-002 "Hides" said frozenset precomputation was "if desired"; (4) line 19 used past-tense framing for an in-progress review.

**Resolution (cross-reference sweep):**
- **RISK-004:** Manifestation and Mitigation completely rewritten to reflect the resolved position — NRP retained as quasi-identifier; operator Art. 9 responsibility is the mitigation; single-line config escape hatch documented; panel-gate language removed.
- **Stakeholder Sign-off:** Privacy specialist gate replaced with operator acknowledgment: "Operator (Pablo / Memodo): Acknowledge the Art. 9 operator responsibility for NRP suppression per REQ-017."
- **MODULE-002 "Hides":** "if desired (implementation detail)" replaced with "mandatory per PERF-001, not optional" — aligned with PERF-001 set-precomputation requirement.
- **Line 19 (`review_panel` note):** Updated to past-tense framing that accurately reflects the panel history: "reviewed across panel iterations 1–2 (2026-05-13); the resolution is captured in REQ-017. The panel concluded with REVISE BEFORE PROCEEDING (iter-2) → final iteration (iter-3). The privacy specialist gate is removed; the spec takes the position."

**Spec location:** RISK-004, Stakeholder Sign-off (first bullet), MODULE-002 "Hides", Executive Summary `review_panel` note (line 18).

---

#### MEDIUM-A5 — REQ-011 rule 3 canonical-set source-of-truth unspecified (Data Modeling)
**Finding:** REQ-011 rule 3 referenced "the canonical entity-type set derived from `docs/supported-entities.md` (the enumerated constant maintained alongside the spec)" without specifying: (a) where the constant lives, (b) how it's maintained, (c) what happens when doc and constant drift, (d) how REQ-021's classification column relates to the constant.

**Resolution:** REQ-011 rule 3 extended with an explicit "Canonical-set source-of-truth (explicit)" sub-block specifying:
- **Location:** `src/redakt/entity_catalog.py` with a single `CANONICAL_ENTITY_TYPES: frozenset[str]` constant.
- **Maintenance:** Manual, alongside `docs/supported-entities.md`. A CI lint test (`tests/unit/test_entity_catalog.py`) asserts the doc and constant are in sync — no silent drift.
- **Precedence:** Constant wins for validation; CI blocks PRs where doc and constant drift. Operators adding entity types must update both.
- **REQ-021 relationship:** The CI lint test validates entity names AND `classification:` column values. The constant is a flat frozenset; classification is doc-level.
- **Post-upgrade strict-mode note:** Added inline (previously a LOW finding recommendation).

**Spec location:** REQ-011 rule 3 — "Canonical-set source-of-truth (explicit)" sub-block added.

---

### LOW Findings

#### LOW-A1 — REQ-011 rule 3 strict-mode migration note missing (Reliability)
**Resolution:** Folded into the MEDIUM-A5 resolution. The "Post-upgrade migration note for `strict_entity_validation: true` operators" is included in the REQ-011 rule 3 canonical-set source-of-truth block.
**Spec location:** REQ-011 rule 3 — included in the "Canonical-set source-of-truth" sub-block.

#### LOW-A2 — EDGE-009 healthcare/HIPAA enforcement asymmetry not acknowledged (Privacy)
**Resolution:** EDGE-009 extended with an explicit "Enforcement asymmetry (acknowledged)" paragraph. States that HIPAA gets a `ValidationError` via REQ-020; non-HIPAA healthcare contexts get only config comment, EDGE-009 guidance, and REQ-017 NRP clause. The asymmetry is stated to be intentional (HIPAA is enumerable; other healthcare regulation is jurisdiction-specific). Operator responsibility for non-HIPAA healthcare contexts is assigned explicitly.
**Spec location:** EDGE-009 — "Enforcement asymmetry (acknowledged)" paragraph added.

#### LOW-A3 — REQ-017 composition gap (closed-world suppression vs Art. 9 audit trail) not acknowledged (Privacy)
**Resolution:** REQ-017 extended with a "V1 composition gap (acknowledged)" paragraph. States the binary v1 design (either suppress OR always-emit NRP — no "suppress AND audit separately" path). Explains that `closed_world_suppressed_count` is a total count, not per-category. Documents the v2 path: `suppressed_by_category: dict[str, int]` audit field. Operators who need both protections must implement Art. 9 record-keeping outside Redakt in v1.
**Spec location:** REQ-017 — "V1 composition gap (acknowledged)" paragraph added before the resolution closure sentence.

#### LOW-A4 — Line 19 past-tense framing pre-dates iter-2 verdict (Privacy)
**Resolution:** Folded into the MEDIUM-A4 cross-reference sweep. The `review_panel` note on line 18 now accurately reflects the multi-iteration review history and confirms the panel gate is removed.
**Spec location:** Executive Summary `review_panel` note (line 18).

---

### Summary

| Severity | Pre-fix | Post-fix | Delta |
|----------|---------|----------|-------|
| HIGH     | 0       | 0        | 0     |
| MEDIUM   | 5       | 0        | −5    |
| LOW      | 4       | 0        | −4    |

All 9 findings resolved (5 MEDIUM, 4 LOW). No findings deferred without disposition. The MEDIUM count strictly decreases by 5 (from 5 to 0). This is the final iteration (iteration 3 of max 3).

**Primary fix shape:** cross-reference sweep (MEDIUM-A4 + MEDIUM-A2 stale-text) plus three targeted gap closures (MEDIUM-A1 HIPAA per-request gate, MEDIUM-A3 MODULE-003/MODULE-004 audit threading, MEDIUM-A5 canonical-set source-of-truth). All LOW findings either folded into MEDIUM resolutions or addressed with targeted one-paragraph extensions.

**New normative content added:** REQ-020 "Per-request override gating under HIPAA scope" + "Scope limitation (explicit)" clauses; MODULE-003 override threading semantics; MODULE-004 two-parameter function signatures; REQ-011 rule 3 "Canonical-set source-of-truth" sub-block with `src/redakt/entity_catalog.py` and CI lint test; EDGE-009 "Enforcement asymmetry" paragraph; RISK-004 rewrite; REQ-017 "V1 composition gap" paragraph.

---

## Iteration 3 — 2026-05-13

**Trigger:** Iteration 2 verdict was REVISE BEFORE PROCEEDING (0 HIGH, 5 MEDIUM, 4 LOW); the iteration-3 fix subagent ran the cross-reference sweep (MODULE-001/002/003/004 signatures and "Hides", RISK-004, Stakeholder Sign-off, line 19), three targeted gap closures (REQ-020 HIPAA per-request gate, REQ-011 rule 3 canonical-set source-of-truth, REQ-017 composition gap), and EDGE-009 enforcement-asymmetry acknowledgment. This is the final permitted verification pass under the SDD-flow iteration cap.

### Executive Summary (Iteration 3)

The iteration-3 fix subagent's edits land cleanly. Every iter-2 finding maps to a substantive, position-taking change in the spec — no placation, no hand-waving. Specifically: (1) MODULE-001's public signature is now `frozenset[str]` and the "Hides" no longer references list-to-set conversion; the docstring contains an explicit "never receives raw lists" sentence at line 518. (2) MODULE-002's "Hides" reads "mandatory per PERF-001, not optional" (line 550), closing the optional/mandatory contradiction. (3) MODULE-003 "Hides" now specifies the `closed_world_filtering_override` threading semantics in five concrete sub-bullets (lines 572–576) including the pre-merge raw value capture and the SEC-001a-gate interaction. (4) MODULE-004 has explicit two-parameter signatures for both `log_detection()` and `log_anonymization()` (lines 586–597), and the routers' field-pass contract is enumerated below. (5) REQ-020 now contains a "Per-request override gating under HIPAA scope (extended)" sub-section (lines 307–315) auto-forcing `allow_per_request_closed_world_override = false` when `"HIPAA"` is in `regulatory_scope`, with a specified INFO log line; and a "Scope limitation (explicit)" paragraph acknowledges that non-HIPAA healthcare contexts intentionally lack runtime enforcement. (6) REQ-011 rule 3 has a "Canonical-set source-of-truth (explicit)" sub-block (lines 226–231) specifying the location (`src/redakt/entity_catalog.py`), maintenance mechanism (manual + CI lint test at `tests/unit/test_entity_catalog.py`), precedence (constant wins for validation), and REQ-021 relationship (classification column is doc-level; CI validates both). (7) RISK-004 Manifestation and Mitigation (lines 728–730) reflect the resolved position. (8) Stakeholder Sign-off line 701 swaps the privacy-specialist gate for operator Art. 9 acknowledgment. (9) EDGE-009 carries the "Enforcement asymmetry (acknowledged)" paragraph (line 426). (10) REQ-017 carries the "V1 composition gap (acknowledged)" paragraph (line 291) documenting the binary v1 design and the v2 `suppressed_by_category` path. (11) Line 19 review_panel note correctly reflects the multi-iteration panel history and removed gate.

Verifying for **new** issues introduced by the iter-3 fix: none of MEDIUM severity. Two minor coverage gaps in the Validation Strategy section are noted as LOW, plus one stylistic issue in MODULE-004 spec refs formatting. No stale-text regressions persist; the cross-reference sweep landed.

### Verdict (Iteration 3)

**PROCEED**

All 5 iter-2 MEDIUM findings are resolved with substantive normative edits — verified line-by-line below. All 4 iter-2 LOW findings are resolved or folded into the MEDIUM sweep. No HIGH or MEDIUM findings remain. Three LOW findings remain: (a) two Validation Strategy coverage gaps (no enumerated test for the REQ-020 HIPAA per-request auto-force; no enumerated test for the new `closed_world_filtering_override` audit field on either text or document path); (b) one cosmetic issue (MODULE-004 spec refs parenthetical formatting). These are genuine best-practice deviations — they do not change the spec's design, do not block implementation, and are recoverable at Step 4b code review and Step 4d evaluation without spec rework. The progress-stall check passes: MEDIUM strictly decreased (5 → 0), HIGH was already zero. The flow exits the panel-review loop with success.

### Iteration 2 → Iteration 3 Finding Count Comparison

| Severity | Iteration 2 | Iteration 3 | Change |
|----------|-------------|-------------|--------|
| HIGH | 0 | 0 | unchanged (zero) |
| MEDIUM | 5 | 0 | decreased (−5) |
| LOW | 4 | 3 | decreased (−1) |

**Progress-stall check (per SDD flow Step 3c):**
- HIGH was zero in iteration 2 → HIGH-must-decrease rule does not apply.
- MEDIUM strictly decreased (0 < 5) → PASS (and now zero, which independently satisfies the PROCEED severity-gate rule).
- Verdict is PROCEED → progress-stall check is moot; the loop exits with success.

### Placation Audit — Iteration 2 Findings Verification

For each iter-2 finding the iter-3 fix subagent claimed resolved, the panel verified the actual spec edit:

| Iter-2 Finding | Fix claim | Spec evidence | Placation verdict |
|----------------|-----------|---------------|---------------------|
| MED-A1 (REQ-020 HIPAA per-request gate) | "Auto-force `allow_per_request_closed_world_override = false` when HIPAA in scope + scope-limitation paragraph" | Lines 307–315: "Per-request override gating under HIPAA scope (extended)" sub-section present with `@model_validator`-enforced auto-force semantics and verbatim INFO log line. Lines 317–319: "Scope limitation (explicit)" paragraph names the HIPAA-only enforcement explicitly. | NOT PLACATING — substantive runtime-enforcement extension that closes the defense-in-depth gap |
| MED-A2 (MODULE-001 signature ↔ PERF-001) | "Signature → `frozenset[str]`; Hides no longer mentions list conversion; MODULE-002 Hides mandatory" | Lines 501–506: signature is `frozenset[str]` for both params. Line 516–518: docstring sentence: "The filter never receives raw lists — callers must not pass list[str]." Lines 525–532: "Hides" list no longer contains "set conversion of list parameters." Line 532 carries an explicit note that conversion is handled once at config-load by MODULE-002. Line 550 (MODULE-002 Hides): "mandatory per PERF-001, not optional." | NOT PLACATING — the cross-domain inconsistency (performance + module-depth + api-contract) is fully resolved with a single signature change plus aligned narrative |
| MED-A3 (MODULE-003/004 audit field threading) | "MODULE-003 Hides rewritten; MODULE-004 two-param signatures" | Lines 570–576: MODULE-003 "Hides" enumerates both audit fields and specifies override threading in four sub-bullets (raw pre-merge value, SEC-001a gate interaction, omitted-vs-null semantics, document-path null). Lines 586–597: MODULE-004 explicit signatures for both `log_detection()` and `log_anonymization()`. Lines 600–604: routers' field-pass contract enumerated. MODULE-003 Spec refs line 580 includes SEC-001a; MODULE-004 Spec refs line 610 includes SEC-001 (d) and SEC-001a. | NOT PLACATING — closes the HIGH-2 audit-visibility threading gap definitively |
| MED-A4 (stale-text regression sweep) | "RISK-004 / Stakeholder Sign-off / MODULE-002 Hides / line 19 all updated" | Lines 728–730: RISK-004 Manifestation and Mitigation rewritten — "REQ-017 takes a decisive position (NRP is retained in `quasi_identifiers`) with a mandatory operator responsibility clause"; "The panel-gate ('privacy specialist must confirm') is removed from the spec." Line 701: Stakeholder Sign-off first bullet replaced with operator Art. 9 acknowledgment language; "The privacy specialist gate is resolved by spec position (REQ-017); no further panel confirmation required." Line 550: MODULE-002 Hides "mandatory" language. Line 19: review_panel note correctly reflects multi-iteration panel history. | NOT PLACATING — all four stale-text sites swept with no regressions; the cross-reference discipline is now consistent |
| MED-A5 (canonical-set source-of-truth) | "Explicit Location/Maintenance/Precedence/REQ-021 relationship sub-block in REQ-011 rule 3" | Lines 226–231: "Canonical-set source-of-truth (explicit)" sub-block with four explicit sub-bullets (Location: `src/redakt/entity_catalog.py`; Maintenance: manual + CI lint at `tests/unit/test_entity_catalog.py`; Precedence: constant wins for validation; REQ-021 relationship: classification column is doc-level, CI validates both). Post-upgrade migration note at line 231 folds LOW-A1. | NOT PLACATING — fully specifies the constant lifecycle, drift-prevention mechanism, and doc/constant precedence |
| LOW-A1 (strict-mode migration note) | "Folded into MED-A5 source-of-truth block" | Line 231: post-upgrade note included in the canonical-set sub-block | NOT PLACATING |
| LOW-A2 (EDGE-009 enforcement asymmetry) | "Enforcement asymmetry (acknowledged) paragraph added" | Line 426: paragraph present, names the three reliance points (EDGE-009, REQ-010 GAMEABLE, REQ-017) and states the asymmetry is intentional | NOT PLACATING |
| LOW-A3 (REQ-017 composition gap) | "V1 composition gap (acknowledged) paragraph added; v2 path documented" | Line 291: paragraph present; documents binary v1 design, names `suppressed_by_category: dict[str, int]` as the v2 path, assigns operator responsibility for Art. 9 record-keeping outside Redakt in v1 | NOT PLACATING |
| LOW-A4 (line 19 past-tense framing) | "Folded into MED-A4 sweep" | Line 19: updated to reflect iter-1–2 panel history and confirm gate removal | NOT PLACATING |

**Placation audit verdict:** No iter-2 finding was placated. All claimed resolutions are backed by substantive, verifiable normative text at the specified line ranges. The iter-3 fix is the cleanest of the three rounds — section-by-section edits land without introducing new stale-text regressions (the dominant iter-2 pattern). The cross-reference discipline that was missing in iter-1 was successfully applied in iter-3.

### Findings by Specialist (Iteration 3)

#### Security Findings (Iteration 3)

(Checked: SEC-001 (a)–(d) all present and substantive. SEC-001a operator config gate present with explicit silent-ignore semantics. REQ-020 HIPAA enforcement now covers both instance default AND per-request override path. Audit visibility per SEC-001 (d) is threaded through MODULE-003 → MODULE-004. The Stakeholder Sign-off line 704 still requests security-specialist confirmation of SEC-001 — this is a normal SDD-flow code-review checkpoint, not a position-deferral analogous to the removed REQ-017 privacy-panel gate; acceptable.)

No new findings.

#### Performance Findings (Iteration 3)

(Checked: MODULE-001 signature is `frozenset[str]`; PERF-001 set-pre-computation requirement aligns with MODULE-002's mandatory pre-computation in `Settings`; tail-behavior bound at 10k spans documented; the Performance Validation benchmark enumerates a frozenset-verification test. No type-contract mismatch persists.)

No new findings.

#### Data Modeling Findings (Iteration 3)

(Checked: REQ-011 rules 1/2/3 explicit; canonical-set source-of-truth specified at `src/redakt/entity_catalog.py` with `CANONICAL_ENTITY_TYPES: frozenset[str]`; CI lint test named at `tests/unit/test_entity_catalog.py`; precedence rule "constant wins for validation; CI blocks drift" stated; REQ-021's `classification:` column relationship clarified as doc-level superset of the flat constant. The implicit-classification anti-pattern (tripartite enum encoded as two-list membership) is now covered by REQ-021's PR-review gate.)

No new findings.

#### API Contract Findings (Iteration 3)

- **LOW** MODULE-004 spec-refs parenthetical formatting is ambiguous
  - Evidence: Line 610: `**Spec refs:** REQ-013, SEC-001 (d), SEC-001a (SPEC-006)`. The trailing `(SPEC-006)` is positioned as a parenthetical of `SEC-001a`, but SPEC-006 is the upstream audit-logging spec that MODULE-004 extends — it is a cross-spec dependency, not a sub-reference of SEC-001a. A reader cannot determine whether SPEC-006 is being grouped with SEC-001a or listed as a separate dependency.
  - Risk: Implementation-time confusion when an engineer traces spec references. Minor; the surrounding text (MODULE-004 Public Interface, Risk paragraph, REQ-013 Schema compatibility section) all make SPEC-006's role clear.
  - Resolution: Rewrite as `**Spec refs:** REQ-013, SEC-001 (d), SEC-001a; upstream dependency: SPEC-006 (audit-logging schema).` Or split into a separate "Dependencies" line. Cosmetic.

#### Module Depth Findings (Iteration 3)

(Checked: MODULE-001 Public Interface is now unambiguous — tuple return, frozenset params, explicit "never receives raw lists" docstring; MODULE-002 set-precomputation mandatory; MODULE-003 override threading specified in five sub-bullets; MODULE-004 two-parameter signatures explicit; MODULE-005 shallow-by-intent justification present. No deep-module clarity violations.)

No new findings.

#### Reliability Findings (Iteration 3)

(Checked: REL-001 determinism/retry-variance paragraph present; EDGE-008 degenerate-config startup WARNING with verbatim text; FAIL-005 strict/non-strict semantics specified; REQ-011 rule 3 post-upgrade strict-mode migration note included. Document-path null sentinel makes audit aggregation distinguishable.)

No new findings.

#### Privacy Findings (Iteration 3)

(Checked: REQ-017 takes a decisive position with rationale, residual Art. 9 risk clause, operator responsibility statement, escape hatch, HIPAA cross-reference, and V1 composition gap acknowledgment; REQ-010 config comment carries the threat-model paragraph verbatim including HIPAA, ART. 9, and GAMEABLE blocks; REQ-020 enforces HIPAA Safe Harbor at both startup and per-request paths; EDGE-009 carries the enforcement-asymmetry acknowledgment; `docs/customizations.md` is named as the second publication point for the threat-model paragraph. The NRP/Art. 9 position is defensible and the operator obligation is named.)

No new findings.

#### Cross-Cutting (Validation Strategy)

- **LOW** Validation Strategy does not enumerate a test for REQ-020 HIPAA per-request auto-force
  - Evidence: Lines 644–697 (Unit Tests, Integration Tests, Eval Fixtures, Performance Validation, Manual Verification). No test asserts: (a) `regulatory_scope: ["HIPAA"]` + `closed_world_filtering: true` raises `ValidationError` at startup; (b) `regulatory_scope: ["HIPAA"]` + `allow_per_request_closed_world_override: true` auto-forces the latter to `false` with the specified INFO log line; (c) a per-request `closed_world_filtering: true` is silently ignored when `allow_per_request_closed_world_override` is forced false. REQ-020 is the runtime regulatory-enforcement boundary; it deserves enumerated test coverage.
  - Risk: Implementer omits these tests; a future REQ-020 regression (e.g., the `@model_validator` is moved or the auto-force is broken) ships undetected. Mitigated because Step 4b code review will likely catch the omission, but the spec's Validation Strategy is the contract for "what tests must exist."
  - Resolution: Add three unit/integration test bullets explicitly naming REQ-020 (instance-default ValidationError, auto-force INFO log, per-request silent-ignore under HIPAA). Cosmetic; recoverable at implementation.

- **LOW** Validation Strategy does not enumerate a test for `closed_world_filtering_override` audit field
  - Evidence: Lines 671–672 (Integration Tests, audit-entry coverage): only `closed_world_suppressed_count: 2` and `closed_world_suppressed_count: 0` are enumerated. No test asserts the `closed_world_filtering_override` field is `true` / `false` / `null` according to caller intent and SEC-001a state. No test asserts the document-upload path null sentinel for either field.
  - Risk: The HIGH-2 resolution depends on the override field being threaded and logged correctly; if the integration test list does not exercise it, the resolution is contingent on implementer initiative. Step 4b code review can catch this, but the spec's Validation Strategy should make the new audit field a first-class test target.
  - Resolution: Add 3–4 integration test bullets: caller sets `closed_world_filtering: true` → audit field is `true`; caller omits → audit field is `null`; caller sets when `allow_per_request_closed_world_override: false` → audit field is `null`; document-upload audit entry → both fields are `null`. Cosmetic; recoverable at implementation.

### Cross-Specialist Observations (Iteration 3)

One pattern surfaced across specialist lenses but is below MEDIUM severity:

1. **Validation Strategy coverage lags the spec's new normative surface.** Two LOW findings (REQ-020 enforcement coverage; `closed_world_filtering_override` audit-field coverage) and a related observation in API Contract (MODULE-004 spec refs formatting) all stem from the iter-1/iter-2/iter-3 spec expansions outpacing the Validation Strategy section. The Validation Strategy in iter-3 is functionally the same as iter-1, while the normative surface has grown by ~5 new REQ-numbered behaviors (REQ-020, REQ-021, SEC-001a, SEC-003, REQ-011 rule 3 expansion, REQ-013 override-field addition). This is a known artifact of section-by-section editing — the test enumeration was not swept with the same discipline as the normative sections. None of these gaps rise to MEDIUM because Step 4b code review and Step 4d evaluation provide downstream coverage; the spec's design is sound.

### Recommended Actions Before Proceeding (Iteration 3)

**Not required (verdict is PROCEED).** The three LOW findings are optional polish items that may be picked up at Step 3e (artifact distillation) or Step 4b (code review), but none block the flow. If the orchestrator chooses to surface them to the implementation subagent as nice-to-haves:

1. **[LOW] [MODULE-004 spec refs]** Rewrite the trailing `(SPEC-006)` to be a separate line ("Upstream dependency: SPEC-006") rather than an ambiguous parenthetical.
2. **[LOW] [Validation Strategy — REQ-020]** Add three test bullets (instance-default ValidationError, auto-force INFO log, per-request silent-ignore under HIPAA).
3. **[LOW] [Validation Strategy — audit override field]** Add three to four test bullets covering the `closed_world_filtering_override` audit field across caller-set, omitted, SEC-001a-gated, and document-upload-path scenarios.

### Iteration 3 Panel Metadata

- **Specialists with no concerns:** security, performance, data-modeling, module-depth, reliability, privacy (six of seven).
- **Specialists with findings:** api-contract (1 LOW). Cross-cutting (Validation Strategy): 2 LOW. Total raw findings: 3 LOW.
- **Total findings (post-dedup):** HIGH=0, MEDIUM=0, LOW=3.
- **Comparison to iteration 2:** strict decrease across MEDIUM (5 → 0) and LOW (4 → 3). HIGH unchanged at 0.
- **Progress-stall check:** PASS (MEDIUM strictly decreased; verdict is PROCEED → stall check is moot anyway).
- **Panel execution mode:** Same as iterations 1 and 2 — the panel orchestrator applied each specialist's canonical vocabulary payload and named anti-pattern set directly against the iter-3-updated SPEC-008, the iter-2 panel review and "Findings Addressed — Iteration 2" appendix, and ADR-0007. The Task primitive was not used; fresh-context-per-specialist isolation was approximated by applying each specialist's named anti-pattern list as a discrete pass over the updated spec. Synthesis rules (deduplication, severity aggregation, ban-bare-approvals) applied per `/sdd:spec-review-panel` Section 5; "Checked: …" annotations included for the six specialists with no findings, satisfying the no-bare-approval requirement.
- **Placation audit:** All 9 iter-2 findings verified line-by-line against actual spec edits. No placating edits detected. The iter-3 fix is the cleanest of the three iterations — no stale-text regressions introduced, no internal contradictions, no gate-language vestiges.
- **Cap exhaustion:** This is the final permitted iteration of the Step 3c fix loop. Verdict is PROCEED; the loop exits with success. No further fix iteration is needed or permitted.

---

## Findings Addressed — Step 3e (LOW from iter 3)

**Date:** 2026-05-13
**Subagent:** Step 3e address-findings subagent

All 3 remaining LOW findings from iter-3 are resolved:

**Panel LOW (a) — MODULE-004 Spec refs parenthetical formatting ambiguous**
Finding: `SEC-001 (d), SEC-001a (SPEC-006)` — the trailing `(SPEC-006)` qualifier was ambiguous about whether it applied to just `SEC-001a` or both identifiers.
Resolution: MODULE-004 Spec refs rewritten as: `REQ-013, SEC-001 (sub-clause d), SEC-001a, SPEC-006 §SEC-001 (PII-never-logged constraint — external ref)`. Each reference is now unambiguous: `SEC-001 (sub-clause d)` is the within-spec trust-model clause; `SPEC-006 §SEC-001` is the external SPEC-006 PII-never-logged constraint with explicit external-ref annotation.

**Panel LOW (b) — Validation Strategy missing enumerated test for REQ-020 HIPAA enforcement**
Resolution: Two new unit test bullets added covering REQ-020:
- `regulatory_scope: ["HIPAA"]` + `closed_world_filtering: true` → `ValidationError` at startup.
- `regulatory_scope: ["HIPAA"]` + `closed_world_filtering: false` + `allow_per_request_closed_world_override: true` → `allow_per_request_closed_world_override` auto-forced to `false`; INFO log line present.

**Panel LOW (c) — Validation Strategy missing enumerated test for `closed_world_filtering_override` audit field**
Resolution: Three new integration test bullets added covering `closed_world_filtering_override`:
- Per-request override sent as `true` → audit field = `true`.
- Per-request field omitted → audit field = `null`.
- SEC-001a silently ignored per-request value → audit field = `null`.
These directly test the threading from MODULE-003 through MODULE-004 to the audit entry.
