# Research Critical Review: Anonymize + Reversible Deanonymization

**Document reviewed:** `SDD/research/RESEARCH-002-anonymize-deanonymize.md`
**Date:** 2026-03-28
**Reviewer role:** Adversarial critical review

## Executive Summary

The research correctly identifies the core technical constraint (Presidio REST API can't assign per-entity placeholders) and proposes a sound solution (Redakt-side replacement). However, the document contains an internal contradiction in its data flow, underestimates overlapping entity complexity, proposes an insecure client-side storage mechanism (sessionStorage), and leaves several edge cases unresolved that will cause ambiguity during specification. Seven findings total: 2 HIGH, 3 MEDIUM, 2 LOW.

**Resolution status: ALL 7 FINDINGS RESOLVED (2026-03-28)**

---

## Critical Findings

### 1. **Internal Contradiction in Data Flow** — HIGH

The proposed data flow diagram (lines 31-48) includes step [7]: "Call presidio.anonymize() with per-entity replace operators." But the "Implementation approach" section (lines 136-141) explicitly states: "Redakt performs the text replacement itself instead of relying on Presidio's anonymizer endpoint."

These contradict each other. The data flow says we call Presidio Anonymizer; the solution says we don't.

- **Evidence:** Lines 47 vs. lines 136-141
- **Risk:** Implementer follows the flow diagram and builds the wrong architecture, or wastes time reconciling the two sections
- **Recommendation:** Correct the data flow diagram to remove step [7] and reflect the actual Redakt-side replacement approach. The corrected flow should be: Analyze (Presidio) → Generate placeholders (Redakt) → Replace text (Redakt) → Return response.

---

### 2. **sessionStorage Is Insecure for PII** — HIGH

The research recommends sessionStorage for browser-side mapping (line 248). This is a significant security concern for an enterprise GDPR tool:

- **XSS exposure:** Any XSS vulnerability (or malicious browser extension) can read all PII mappings from sessionStorage with one line of JavaScript: `sessionStorage.getItem('pii_mappings')`
- **DevTools visibility:** Anyone with access to the browser's developer tools can inspect sessionStorage and extract all original PII values
- **No CSP headers:** The current codebase has no Content-Security-Policy headers configured. HTMX is loaded from an external CDN (`unpkg.com`) without Subresource Integrity (SRI) hashes — a MITM could inject malicious code.
- **Shared/kiosk environments:** Enterprise deployments may use shared workstations where a subsequent user could inspect storage

**Recommendation:** Use an in-memory JavaScript variable instead of sessionStorage. The mapping only needs to survive for a single anonymize→copy→paste→deanonymize workflow within one page load. In-memory variables are not inspectable via the Storage tab in DevTools, are not accessible to other scripts on the origin, and are automatically cleared on any navigation. Additionally, CSP headers and SRI for the HTMX CDN should be specified as security requirements.

---

### 3. **Overlapping Entity Handling Is Under-Researched** — MEDIUM

The research acknowledges overlapping entities (lines 181-184) but hand-waves the resolution: "Presidio's analyzer results may already handle this."

**Verified behavior from Presidio source code:**
- Presidio's `remove_duplicates()` only removes entities **fully contained** within another entity **of the same type**
- Entities of **different types** that overlap the same span are **both returned** (confirmed by test comment: "we only remove duplicates when the two have the same entity type")
- **Partial overlaps** of the same type are NOT deduplicated

**Concrete scenario not addressed:**
- Input: `"Contact John Smith at john.smith@acme.com"`
- Presidio may return: PERSON "John Smith" at [8,18] AND EMAIL "john.smith@acme.com" at [22,42]
- But also: PERSON "John" at [8,12] could appear if a different recognizer fires (this one WOULD be deduplicated as it's contained in same-type "John Smith")
- More problematic: `"Berlin office"` → LOCATION "Berlin" at [0,6] AND ORGANIZATION "Berlin office" at [0,13] — overlapping spans, different types, BOTH returned

**Risk:** The replacement algorithm will corrupt text if it tries to replace overlapping spans — replacing "Berlin" first shifts indices, then replacing "Berlin office" at the original indices produces garbage.

**Recommendation:** The spec must define an explicit overlap resolution strategy. Recommended: for overlapping entities of different types, keep the one with the higher confidence score. If scores are equal, keep the longer span. This must be implemented in Redakt before the replacement step.

---

### 4. **Same Value, Different Entity Types — Ambiguous** — MEDIUM

The research states "same value = same placeholder" but doesn't address what happens when the same text is detected as different entity types.

**Example:** "Amazon" could be detected as both ORGANIZATION and PERSON (the river). Should both get `<ORGANIZATION_1>` or should one get `<ORGANIZATION_1>` and the other `<PERSON_1>`?

The deduplication rule says group by `(entity_type, original_text)` — this means the same text detected as two different types gets two different placeholders. But this interacts with the overlap resolution above.

- **Risk:** Ambiguity during implementation; inconsistent behavior
- **Recommendation:** Clarify that placeholder assignment is keyed by `(entity_type, text_value)`. After overlap resolution (finding 3), each surviving entity gets a placeholder based on its type. Document this explicitly.

---

### 5. **Client-Side Deanonymization Edge Cases Incomplete** — MEDIUM

The research identifies that deanonymization is "simple string replacement" but doesn't explore failure modes:

**a) LLM modifies placeholders:**
- LLM might output `PERSON_1` (without angle brackets), `<person_1>` (lowercase), or `<PERSON 1>` (space instead of underscore)
- The research mentions "Must handle the case where LLM adds/modifies text around placeholders" (line 170) but offers no solution

**b) Placeholder appears in LLM-generated text:**
- If LLM generates text containing `<PERSON_1>` that doesn't correspond to the original mapping (e.g., the LLM discusses the anonymization scheme), deanonymization would incorrectly substitute

**c) Replacement order matters:**
- If `<PERSON_1>` = "Al" and `<PERSON_12>` = "Bob", naive `replaceAll` on `<PERSON_1>` first would corrupt `<PERSON_12>` → `"2">` is left behind
- Must replace longer placeholders first, or use word-boundary-aware matching

- **Risk:** Users get corrupted deanonymized text and lose trust in the tool
- **Recommendation:** Spec should define: (1) exact-match only (case-sensitive, with angle brackets), (2) replacement order (longest placeholder first, or regex-based whole-token match), (3) document as known limitation that LLM-modified placeholders won't be reversed

---

### 6. **HTMX + Client-Side JS Architecture Tension** — LOW

The existing frontend is purely HTMX-driven with server-rendered HTML fragments and zero custom JavaScript. Feature 2 requires significant client-side JavaScript for:
- Storing the mapping in memory
- Performing deanonymization (string replacement)
- Copy-to-clipboard functionality
- Possibly a "deanonymize" button that works entirely client-side

This is an architectural shift from the current pattern. The research lists `deanonymize.js` as a new file but doesn't discuss how HTMX and custom JS will coexist, or whether the deanonymize field/button should be an HTMX interaction or pure JS.

- **Risk:** Inconsistent frontend architecture; implementer has to make design decisions not covered by the spec
- **Recommendation:** Research should clarify the frontend interaction model: HTMX for the anonymize request (server-side), JS for deanonymization (client-side). Specify whether the mapping is passed from the HTMX response into a JS variable.

---

### 7. **Presidio Anonymizer Service Becomes Unused Infrastructure** — LOW

The research notes that Presidio Anonymizer "is still deployed (used for health checks, and will be needed for Feature 3 document support)." But for Feature 2, it's running as a Docker container consuming memory and CPU while serving zero functional requests.

The health check currently probes both services. If the anonymizer is down but analyzer is up, the health endpoint reports "degraded" — which would be misleading since anonymize functionality actually works fine (Redakt does its own replacement).

- **Risk:** Confusing health status; wasted resources in resource-constrained deployments
- **Recommendation:** Not blocking, but the spec should note that health check semantics may need adjustment. The anonymizer health is only relevant once Feature 3 uses it.

---

## Questionable Assumptions

1. **"Low probability" of placeholder collision** (line 188) — In technical documentation, `<PERSON_1>` patterns are not uncommon. Enterprise users anonymizing documentation about anonymization systems (meta-usage) would hit this. The assumption should be validated, not dismissed.

2. **"JSON mapping is tiny"** (line 203) — True for text, but the research doesn't consider Feature 3 (documents). A large Excel spreadsheet could have hundreds of PII entities, producing a mapping that's non-trivial to hold in browser memory. Not a real problem, but the assumption is stated without bounds.

3. **Counter starting at 1** (line 128) — The InstanceCounterAnonymizer sample code starts at 0. The research says 1. This should be an explicit decision, not accidental. Starting at 1 is more natural for users reading the output.

---

## Missing Perspectives

- **Security/Compliance team:** Would they accept in-memory JS over sessionStorage? Do they require the mapping to be encrypted client-side? Is there a requirement for mapping to be clearable on demand (a "forget" button)?
- **AI agent developers:** How exactly do agents use the mapping? The research mentions agents "hold the mapping in memory for the duration of their task" but doesn't specify the API contract for this (is mapping in the response body sufficient, or do agents need a session concept?).

---

## Recommended Actions Before Proceeding to Specification

| Priority | Action |
|----------|--------|
| **HIGH** | Fix the internal contradiction — update the data flow to remove the Presidio Anonymizer call |
| **HIGH** | Change recommendation from sessionStorage to in-memory JS variable; add CSP/SRI as security requirements |
| **MEDIUM** | Define explicit overlap resolution strategy with concrete algorithm |
| **MEDIUM** | Clarify same-value-different-type placeholder assignment |
| **MEDIUM** | Specify client-side replacement order and known limitations for LLM-modified placeholders |
| **LOW** | Clarify HTMX + JS coexistence pattern for the frontend |
| **LOW** | Note health check semantic change for Presidio Anonymizer |

## Proceed/Hold Decision

**PROCEED WITH REVISIONS** — The core technical approach (Redakt-side replacement, client-side deanonymization) is sound and well-researched. The 2 HIGH findings are straightforward to fix (contradiction is editorial; sessionStorage → in-memory is a one-line change in the recommendation). The MEDIUM findings need resolution during specification but don't require additional research — they're design decisions that can be made in the spec.

---

## Resolution Log (2026-03-28)

All 7 findings have been resolved in the research document:

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Internal contradiction in data flow | HIGH | Flow diagram corrected: removed Presidio Anonymizer call (step 7), replaced with Redakt-side replacement (step 8). Added overlap resolution as step 6. |
| 2 | sessionStorage insecure for PII | HIGH | Changed to in-memory JS variable throughout. Added CSP, SRI, and X-Content-Type-Options as security requirements in new "Browser Security Headers" subsection. |
| 3 | Overlapping entity handling | MEDIUM | Documented actual Presidio behavior (same-type dedup only). Added explicit overlap resolution algorithm: sort by score desc → discard lower-score overlaps → tie-break by longer span. |
| 4 | Same value, different entity types | MEDIUM | Clarified placeholder key is `(entity_type, text_value)`. Added "Amazon" example showing same value gets different placeholders when detected as different types. |
| 5 | Client-side deanonymization edge cases | MEDIUM | Added dedicated subsection covering: replacement order (longest first), LLM-modified placeholders (known v1 limitation), phantom placeholders, and missing placeholders. |
| 6 | HTMX + JS coexistence pattern | LOW | Clarified in Engineering perspective: HTMX handles server interactions (anonymize POST), JS handles client-only logic (deanonymization). Mapping passed via data attribute or script tag in HTMX response. |
| 7 | Health check semantics | LOW | Added note in Key Technical Decision section about health endpoint reporting "degraded" when Anonymizer is down even though Feature 2 works. Flagged for spec consideration. |

**Updated decision: PROCEED TO SPECIFICATION**
