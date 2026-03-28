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
