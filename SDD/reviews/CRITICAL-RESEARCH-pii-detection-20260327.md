# Critical Review: RESEARCH-001-pii-detection

**Date:** 2026-03-27
**Reviewing:** `SDD/research/RESEARCH-001-pii-detection.md` + `docs/v1-feature-spec.md`
**Overall Severity:** HIGH

## Executive Summary

The research correctly identifies the tech stack, project structure, and data flow. However, adversarial verification against Presidio's source code uncovered two critical blind spots (German language support with the transformers model, and an overly aggressive default score threshold) and several medium-severity issues around error handling and case sensitivity. These must be resolved before specification, as they affect core architecture decisions — not just implementation details.

## Critical Gaps Found

### 1. Transformers model does not support German — CRITICAL

**The research recommends** the transformers Docker variant (`StanfordAIMI/stanford-deidentifier-base`) for better accuracy.

**The problem:** This model is **English-only**. The `transformers.yaml` config only defines `lang_code: en`. There is no German language entry. For a German enterprise tool, this means:
- NER-based detection (person names, locations, organizations) will not work for German text
- The 13 German-specific regex recognizers (tax ID, passport, etc.) still work — but only if language `"de"` is passed, and the NLP engine supports it

**Evidence:** `presidio/presidio-analyzer/presidio_analyzer/conf/transformers.yaml` — only `lang_code: en` defined.

**Risk:** The entire premise of "transformers variant is the better fit" is wrong for a German enterprise. Users will submit German text, auto-detection will resolve to `"de"`, and Presidio will either error out or miss NER-based entities entirely.

**Recommendation:** Either:
- (a) Use the **spaCy variant** with `de_core_news_lg` for German + `en_core_web_lg` for English (multi-model config)
- (b) Configure the transformers variant with a multilingual NER model (e.g., `xlm-roberta` fine-tuned for NER)
- (c) Run **two analyzer instances** — one per language

This is an architecture-level decision that must be resolved before proceeding.

### 2. Default score threshold of 0.7 will silently drop legitimate PII — CRITICAL

**The research proposes** `score_threshold: 0.7` as the default.

**The problem:** Presidio's own default is `0.0` (return everything). Many legitimate detections score between 0.3 and 0.6:
- Pattern-based recognizers (phone numbers, credit cards) often produce raw scores of 0.4–0.6
- Context enhancement adds up to 0.35 bonus — but only if context words are present
- A phone number without the word "phone" nearby might score 0.4 and be silently dropped at 0.7

**Evidence:** `presidio/presidio-analyzer/presidio_analyzer/analyzer_engine.py:56` — `default_score_threshold: float = 0`

**Risk:** Users will paste text with phone numbers or IDs, Redakt will say "no PII found," and the user will trust that and paste it into ChatGPT. This is worse than a false positive — it's a false negative in a GDPR compliance tool.

**Recommendation:** Default to `0.35` or `0.4` — low enough to catch pattern-based detections, high enough to filter noise. Make it clearly configurable. Document the tradeoff in the UI (e.g., "sensitivity: high/medium/low" mapped to thresholds).

### 3. Allow list matching is case-sensitive — MEDIUM

**The research assumes** allow lists work intuitively.

**The problem:** Presidio's exact-match mode is case-sensitive. If you add "Acme Corp" to the allow list, "acme corp" or "ACME CORP" in text will still be flagged.

**Evidence:** `presidio/presidio-analyzer/presidio_analyzer/analyzer_engine.py:388-394` — uses Python `in` operator (case-sensitive).

**Risk:** Enterprise users will add their company name and wonder why it's still being flagged in different capitalizations. Frustrating UX that undermines trust in the tool.

**Recommendation:** Redakt should normalize both the allow list and extracted entity text to the same case before comparison, or default to regex mode with case-insensitive flag. Document this behavior clearly.

### 4. Unsupported language returns 500, not 400 — MEDIUM

**The research documents** that Presidio requires an explicit language parameter.

**The problem:** If Redakt's language auto-detection resolves to a language Presidio doesn't support (e.g., `"ja"` for Japanese), Presidio returns HTTP 500 with `"No matching recognizers were found"`. This is indistinguishable from an actual server error.

**Evidence:** `presidio/presidio-analyzer/app.py:125-130` — `ValueError` from language validation is caught as generic `Exception` and returns 500.

**Risk:** Redakt can't distinguish "bad language" from "Presidio is down" without parsing the error message string. Fragile error handling.

**Recommendation:** Redakt should validate the language against Presidio's `/supportedentities` endpoint (cached at startup) before forwarding. Return a clear 400 to the user: "Language 'ja' is not supported. Supported: en, de, ..."

### 5. No research on Presidio startup time and health checks — LOW

**Missing from research:** How long does Presidio take to start, especially the transformers variant? The `Dockerfile.transformers` downloads a BERT model at build time, but the model still needs to load into memory at container start.

**Risk:** `docker compose up` may show all containers as "started" but Presidio may not be ready to accept requests for 30–60 seconds. If Redakt starts faster and immediately calls Presidio, it gets connection errors.

**Recommendation:** Redakt's health check (`GET /api/health`) should probe Presidio's `/health` endpoints and report overall readiness. On startup, Redakt should retry Presidio connections with backoff. Add `depends_on` with health check conditions in docker-compose.yml.

### 6. No research on request size limits — LOW

**Missing from research:** What happens when someone pastes a 10MB document into the text field? Presidio's Flask server has no explicit request size limit documented.

**Risk:** Large payloads could cause timeouts or OOM in Presidio (especially the transformers variant which loads text into GPU/CPU memory for NER).

**Recommendation:** Enforce a max text size in Redakt (e.g., 500KB for the detect endpoint). Document the limit. This is especially important for the document upload feature later.

## Questionable Assumptions

### "langdetect is sufficient for language detection"

`langdetect` is known to be unreliable on short text (fewer than ~20 words). Enterprise users may paste short snippets like "Contact Hans Mueller at hans@example.com" — `langdetect` might misidentify this as English due to the email and common words.

**Alternative:** `lingua-py` is significantly more accurate on short text, at the cost of being heavier (~30MB model). Given that language detection is critical to the entire pipeline (wrong language = wrong recognizers = missed PII), accuracy may be worth the tradeoff.

### "Client-side deanonymization is ~20 lines of JS"

This underestimates the complexity. Considerations not addressed:
- What if the LLM restructures the text and placeholders appear in a different order?
- What if the LLM modifies a placeholder (e.g., `<PERSON_1>` becomes `PERSON_1` or `<Person_1>`)?
- What if the mapping expires (browser timeout) before the user finishes their LLM session?
- sessionStorage vs in-memory: sessionStorage survives page refresh but is per-tab

This isn't a blocker for Feature 1 research, but it's flagged as a risk for Feature 2 SDD.

## Missing Perspectives

- **End user (colleague):** How does a non-technical user know if the detection is working correctly? What feedback does the UI give? Is there a way to report missed PII?
- **Compliance officer:** Is the audit log sufficient for actual GDPR audit? What format do auditors expect? Is stdout logging enough or do they need a dashboard?
- **IT/Ops team:** Who maintains the Docker deployment? How are updates to Presidio or the NER model handled? How is the allow list managed at scale?

## Recommended Actions Before Proceeding to Specification

| Priority | Action |
|---|---|
| **P0** | Resolve the German language support question — spaCy multi-language, multilingual transformer, or dual analyzers. This is a blocker. |
| **P0** | Lower the default score threshold to 0.35–0.4 and validate against real-world German + English PII text samples. |
| **P1** | Decide on `langdetect` vs `lingua-py` — test both against short German/English text snippets. |
| **P1** | Add language validation logic to the Redakt design — check supported languages before calling Presidio. |
| **P2** | Document allow list case sensitivity and decide on Redakt's normalization approach. |
| **P2** | Add Presidio startup/readiness handling to the architecture. |
| **P2** | Define request size limits. |

## Proceed/Hold Decision

**HOLD on specification until P0 items are resolved.** The German language support gap is fundamental — it determines which Docker variant to use, which NER models to configure, and potentially the entire analyzer architecture. The score threshold issue could result in a tool that gives users false confidence in their anonymization.

Both can be resolved with targeted research — this is not a full restart, just two focused investigations before moving forward.
