# IMPLEMENTATION-SUMMARY-008: closed-world-filtering

**Completed:** 2026-05-13 15:38:56
**Spec:** SDD/requirements/SPEC-008-closed-world-filtering.md
**Research:** SDD/research/RESEARCH-008-closed-world-filtering.md
**ADR:** SDD/adr/0007-closed-world-filtering-quasi-identifiers.md
**Implementation tracker:** SDD/implementation/IMPLEMENTATION-PLAN-008-closed-world-filtering-2026-05-13.md
**Code review:** SDD/reviews/REVIEW-008-closed-world-filtering-20260513.md (final: APPROVED post-Step-4c)
**Implementation critical review:** SDD/reviews/CRITICAL-IMPL-closed-world-filtering-20260513.md (final: APPROVED post-Step-4e)
**Panel review:** SDD/reviews/PANEL-SPEC-closed-world-filtering-20260513.md (final: PROCEED at iter 3)
**Spec critical review:** SDD/reviews/CRITICAL-SPEC-closed-world-filtering-20260513.md (final: PROCEED WITH CAUTION; all addressed in Step 3e)

## What this feature does

Closed-world filtering is an opt-in post-filter policy layer in Redakt (off by default) that suppresses quasi-identifier spans (DATE_TIME, LOCATION, NRP, DE_PLZ) when no strong-anchor span (PERSON, EMAIL_ADDRESS, PHONE_NUMBER, etc.) is present in the same submission. It is overridable per request via a `closed_world_filtering` boolean field on both `/api/detect` and `/api/anonymize`. The feature is deliberately HIPAA-incompatible by design: when `regulatory_scope` includes `HIPAA`, the gate raises a ValidationError at config-load and auto-forces the per-request override gate to false, preventing any relaxation of PII detection in HIPAA-scoped deployments.

## What changed in the codebase

### Production code (files modified)

- `src/redakt/entity_catalog.py` — NEW: `CANONICAL_ENTITY_TYPES` frozenset (39 types); authoritative source-of-truth for config-load canonical-set validation (REQ-011)
- `src/redakt/config.py` — extended `Settings` with 6 new fields (`closed_world_filtering`, `strong_anchors`, `quasi_identifiers`, `allow_per_request_closed_world_override`, `strict_entity_validation`, `regulatory_scope`) + 2 pre-computed frozensets + `@model_validator` enforcing REQ-012 (overlap), REQ-011 (duplicates, canonical-set, FAIL-005), REQ-020 (HIPAA gate + auto-force); `CANONICAL_REGULATORY_SCOPES` frozenset; case-normalizing `.strip().upper()` at validator entry; `is_hipaa_scoped()` helper; unknown-scope-token validation (HIGH-001 fix from Step 4e)
- `config.yaml` — new `closed_world_filtering` block with verbatim threat-model comment (THREAT MODEL, GAMEABLE, HIPAA, ART. 9, NOTE, OVERRIDE clauses per REQ-010)
- `src/redakt/utils.py` — new `filter_by_closed_world()` pure function; O(n) anchor sweep; tuple return `(list[dict], int)` for suppressed-count audit; O(1) no-op when flag disabled
- `src/redakt/models/detect.py` — `closed_world_filtering: StrictBool | None = None` (strict — no coercion; MEDIUM-001 fix from Step 4e)
- `src/redakt/models/anonymize.py` — same `StrictBool | None` field
- `src/redakt/routers/detect.py` — filter wired in after `filter_by_entity_thresholds`; SEC-002a gate precedence (HIPAA > SEC-001a operator gate > per-request > instance default); audit fields threaded; dead variable `raw_cwf_override` removed (LOW-001 fix from Step 4c)
- `src/redakt/routers/anonymize.py` — same changes as detect.py
- `src/redakt/services/audit.py` — `closed_world_suppressed_count` + `closed_world_filtering_override` unconditionally emitted (null serialized as JSON null, not omitted); explicit null kwargs on `log_document_upload()` (LOW-003/LOW-004 fixes from Steps 4c and 4e)

### Tests (files modified)

- `tests/test_closed_world_filter.py` — comprehensive unit+integration battery (24 Chunk 1 + 47 Chunk 2 + 48 Step 4e = 119 tests total); covers every REQ/EDGE/FAIL including HIPAA gate normalization, StrictBool rejection, eval-loader guard, audit field symmetry, SEC-001a gate, EDGE-005 allow-list-stripped anchor
- `tests/test_entity_catalog.py` — NEW: 10 CI lint tests asserting `CANONICAL_ENTITY_TYPES` ↔ `docs/supported-entities.md` bidirectional consistency (REQ-021)
- `tests/e2e/test_closed_world_e2e.py` — NEW: 8 Playwright E2E tests (requires Docker stack; not run in autonomous-mode CI)
- `tests/eval/_loader.py` — extended with `request_params: tuple[tuple[str, Any], ...]` per-fixture field + `build_request_body()` method + `_ALLOWED_REQUEST_PARAM_KEYS` frozenset + `isinstance(raw_params_value, dict)` guard (MEDIUM-004 fix from Step 4e)
- `tests/eval/test_calibration.py` — updated to use `phrase.build_request_body()`
- `tests/eval/fixtures/closed-world.yaml` — NEW: 4 fixtures (Munich-weather expect_clean, Stefan Berger anchor-present, PV invoice DE_VAT_ID anchor, EDGE-008 gameable healthcare narrative expect_clean)

### Docs (files modified)

- `docs/v1-feature-spec.md` — Feature 7 section added (closed-world filtering)
- `docs/customizations.md` — Item 8 appended with config keys table, per-request override note, HIPAA incompatibility note, EDGE-005 allow-list interaction note, audit fields table; verbatim threat-model config comment block per REQ-010 (LOW-002 fix from Step 4c)
- `docs/supported-entities.md` — Classification column added to Generic (NLP-based), Generic (pattern-based), and Germany (DE_*) sections; classification corrections for MEDICAL_LICENSE (strong_anchor), CREDIT_CARD (always_emit), DE_KFZ (strong_anchor) applied at Step 4c

## Test results

- Unit + integration: **471/471 passing** (`uv run pytest tests/`)
- E2E: written, not run in autonomous mode (operator runs against Docker compose stack)
- Eval fixtures: written, not run (operator runs `uv run pytest tests/eval/` against real Presidio)

## Requirement coverage (21 REQ + 10 EDGE + 5 FAIL)

- REQ-001 through REQ-021: all implemented and tested
- EDGE-001 through EDGE-010: all implemented and tested
- FAIL-001 through FAIL-005: all error handling implemented and tested
- PERF-001 (O(n), frozenset pre-computation at config-load): verified by O(n) code inspection; no production benchmark run
- PERF-002 (O(1) no-op when disabled): verified by code inspection
- SEC-001 (trusted caller), SEC-001a (operator gate), SEC-002a (gate precedence truth table): all implemented; gate-precedence tested end-to-end
- COMPAT-001 (default-off; existing tests pass unchanged): confirmed (374/374 pre-existing tests unaffected)

## Review trail

| Review | Verdict | Findings (HIGH/MED/LOW) | Status |
|--------|---------|-------------------------|--------|
| Critical research review (Step 2c) | REVISE BEFORE PROCEEDING | 3/5/3 | All addressed in Step 2d |
| Panel review iter 1 (Step 3c) | STOP AND RECONSIDER | 2/9/6 | Addressed in iter 1 fix |
| Panel review iter 2 (Step 3c) | REVISE BEFORE PROCEEDING | 0/5/4 | Addressed in iter 2 fix |
| Panel review iter 3 (Step 3c) | PROCEED | 0/0/3 | PROCEED |
| Critical spec review (Step 3d) | PROCEED WITH CAUTION | 0/4/6 | All addressed in Step 3e |
| Code review (Step 4b) | REVISIONS REQUIRED | 0/4/4 + risk-tier | All addressed in Step 4c |
| Implementation critical review (Step 4d) | REVISIONS REQUIRED | 1/4/4 | All addressed in Step 4e |

## Key implementation decisions documented

- ADR-0007 (already in place) governs the threat-model decision and DE_PLZ classification. Spec inherits.
- DE_KFZ classified as `strong_anchor` (not quasi) — conservative default; documented in REQ-001 and corrected in docs at Step 4c (MEDIUM-003).
- MODULE-002 risk-tier upgraded from Low to High in Step 4c due to HIPAA gate regulatory exposure.
- Document-upload path (v2-out-of-scope): closed-world filter not invoked; audit fields emit explicit null sentinel on the `log_document_upload()` path.
- Pydantic `StrictBool` chosen over plain `bool` for per-request override field (no coercion; FAIL-002/MEDIUM-001 hardened in Step 4e).
- `regulatory_scope` tokens normalized via `.strip().upper()` at validator entry; unknown tokens validated against `CANONICAL_REGULATORY_SCOPES`; prevents HIPAA gate bypass via case typo (HIGH-001 from Step 4d/4e).

## Cross-cutting decisions made

- No new ADRs written (ADR-0007 already covered all cross-cutting decisions; spec frontmatter `cross_cutting_decisions: []`).

## Glossary additions

- 6 new terms added to `SDD/UBIQUITOUS_LANGUAGE.md` at Step 2a-2: `strong anchor`, `quasi-identifier`, `closed-world assumption`, `closed-world filtering`, `post-filter`, `per-request override`.
- 1 new term added at Step 3a-2: `always-emit entity`.
- `strong anchor` entry updated at Step 3e to enumerate all 19 default strong-anchor entity types matching REQ-001.
- No new terms introduced during implementation: `is_hipaa_scoped()` is a method name internal to `config.py` (single call site; not drift-prone); `CANONICAL_REGULATORY_SCOPES` is a module-level constant (not a domain term); neither rises to glossary threshold.

## Operator follow-up actions

1. Run E2E tests against Docker compose stack: `uv run pytest tests/e2e/test_closed_world_e2e.py` (add `--headed` for visible browser).
2. Run eval suite against real Presidio: `uv run pytest tests/eval/`.
3. Optionally run the calibration report against the new closed-world fixtures: `uv run python tools/calibration_report.py`.
4. Toggle `closed_world_filtering: true` in production `config.yaml` when ready (default off).

## Known residual risks

- RISK-001: over-suppression UX bug — mitigated by default-off + per-request override.
- RISK-002: gameable rule — accepted per ADR-0007; healthcare gameable fixture covers it.
- RISK-003: allow-list interaction — documented in EDGE-004/EDGE-005 + customizations.md.
