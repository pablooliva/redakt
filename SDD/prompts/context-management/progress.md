# Research Progress

## RESEARCH-002: Anonymize + Reversible Deanonymization (Feature 2)

**Status:** Research phase COMPLETE. Ready for `/sdd:planning-start`.

### Documents

- Research: `SDD/research/RESEARCH-002-anonymize-deanonymize.md`
- Critical review: `SDD/reviews/CRITICAL-RESEARCH-anonymize-deanonymize-20260328.md`
- Critical review: All 7 findings resolved (2 HIGH, 3 MEDIUM, 2 LOW)

### Key Technical Decisions

1. **Redakt-side text replacement** — not Presidio Anonymizer's `/anonymize` endpoint (API limitation: per-type, not per-entity configs)
2. **In-memory JS variable** for PII mapping (not sessionStorage — XSS/DevTools risk)
3. **Cross-type overlap resolution** — sort by score desc, discard lower-score overlaps, tie-break by longer span
4. **Placeholder key:** (entity_type, text_value) — same value + different type = different placeholders
5. **Counter starts at 1** — more natural for users
6. **Client-side deanonymization:** longest placeholder first to avoid partial match corruption
7. **CSP + SRI** required as browser security headers
8. **HTMX + JS coexistence:** HTMX for server interactions, JS for client-only deanonymization

### Phase Transition

Research phase complete. `RESEARCH-002-anonymize-deanonymize.md` finalized. Ready for `/sdd:planning-start`.

---

## SPEC-002: Planning/Specification Phase

**Status:** APPROVED. Planning phase COMPLETE.

### Documents

- Specification: `SDD/requirements/SPEC-002-anonymize-deanonymize.md`
- Based on: `SDD/research/RESEARCH-002-anonymize-deanonymize.md`
- Research critical review: `SDD/reviews/CRITICAL-RESEARCH-anonymize-deanonymize-20260328.md` (7 findings, all resolved)
- Spec critical review: `SDD/reviews/CRITICAL-SPEC-anonymize-deanonymize-20260328.md` (6 findings, all resolved)

### Specification Summary

- 15 functional requirements (REQ-001 through REQ-015)
- 5 security requirements (SEC-001 through SEC-005)
- 8 edge cases documented with test approaches
- 4 failure scenarios with recovery strategies
- 3 identified risks with mitigations
- Full API contract + Web UI contract defined
- Core algorithms specified (anonymize flow, client-side deanonymize)
- Suggested implementation order (10 steps)
- 9 new files to create, 5 existing files to modify

### Critical Review Resolutions (Spec)

1. CSP inline handler conflict → extract to external `detect.js`, no inline scripts permitted
2. JS testing strategy → manual verification for v1, pure function structure for future testability
3. Web UI routes → full contract added (URLs, form fields, HTMX partial structure, deanonymize UX flow)
4. Overlap boundary → formalized with exclusive `end`, overlap predicate defined
5. Placeholder format → raw Presidio entity type names (`<EMAIL_ADDRESS_1>`, not `<EMAIL_1>`)
6. Score threshold → example fixed to `null`, default documented as config-driven

### Ready For

- `/sdd:implement` to begin coding

---

## Implementation Phase — READY TO START

### Implementation Priorities
1. Backend core: models, anonymizer service, unit tests
2. API endpoint: router, integration tests, audit logging
3. Web UI: templates, HTMX routes, client-side JS
4. Security: CSP middleware, SRI, inline handler migration, cross-feature verification

### Critical Implementation Notes
- Do NOT call Presidio Anonymizer — Redakt does its own text replacement
- Placeholders use raw Presidio entity type names (`<EMAIL_ADDRESS_1>`)
- Overlap resolution before placeholder assignment (predicate: `start_a < end_b AND start_b < end_a`)
- CSP is global — must extract Feature 1's inline handler to `detect.js` first
- Clipboard API needs `document.execCommand('copy')` fallback for HTTP
- Mapping handoff: `data-mappings` attribute on `#anonymize-output`, parsed on `htmx:afterSwap`, then removed from DOM

### Context Management Strategy
- Target: <40% context utilization
- Essential files: 8 existing files (see spec)
- Delegatable: `deanonymize.js`, `detect.js`, test files, security middleware

### Known Risks
- RISK-001: LLM placeholder modification (known v1 limitation)
- RISK-002: Health check semantics (non-blocking, document only)
- RISK-003: Placeholder collision (accepted v1 limitation)

### Next Steps
Planning phase complete. Run `/sdd:implement` to begin implementation.
