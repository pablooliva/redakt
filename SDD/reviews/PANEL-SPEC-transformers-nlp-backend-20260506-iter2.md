# Spec Review Panel: transformers-nlp-backend (Iteration 2)

**Date:** 2026-05-06
**Iteration:** 2 (re-review after iter 1 fix)
**Spec reviewed:** SDD/requirements/SPEC-007-transformers-nlp-backend.md
**Research context:** SDD/research/RESEARCH-007-transformers-nlp-backend.md
**Iter 1 review:** SDD/reviews/PANEL-SPEC-transformers-nlp-backend-20260506.md
**Panel:** security, performance, privacy, reliability, module-depth

## Executive Summary

The iter 1 fix subagent's edits substantively address all four iter 1 MEDIUM findings with concrete, testable acceptance criteria — not placating wording. The artifact-digest manifest (REQ-013), two-phase startup contract (REQ-005a + generalized FAIL-002), measurement-driven `start_period` formula (REQ-014), and model-load-once invariant (REQ-001 extension + PERF-002 cross-link) are all wired to specific tests or build-time checks. The fixes did not introduce new MEDIUM-level concerns. Two minor LOW-tier observations surfaced on re-read: (a) PERF-001's long-document anchor is referenced but not explicitly named as a fixture, requiring the implementer to backfill EDGE-006's phrase; and (b) the digest manifest's module ownership is split implicitly between MODULE-002 (config) and MODULE-003 (dispatcher) without an explicit owner statement. Neither rises above LOW. No HIGH findings, no new MEDIUM findings, no regression on iter 1 fixes.

## Verdict

**PROCEED**

Trigger: 0 HIGH, 0 MEDIUM, 2 LOW. Iter 1 → iter 2 MEDIUM count delta is 4 → 0. Both LOW findings are minor wording / fixture-naming issues that can be addressed inline during implementation or rolled into the Step 3e combined critical-review fix step alongside the deferred iter 1 LOWs.

## Iteration 1 Fix Acceptance Audit

### Iter 1 Finding 1: REQ-013 HF model integrity (Security MEDIUM + LOW pin mechanism)
**Status:** ACCEPTED.
**Evidence:**
- REQ-013 (lines 144–159) commits declaratively to a YAML `revision` key in `multi.yaml`'s per-row `models[]`; the function-arg-only path is explicitly rejected ("pinning must be visible in the YAML, not buried in the install script").
- Artifact-level integrity is enforced via `multi.model_digests.json` (per-file SHA-256, keyed by `(model_name, revision)`), recomputed on every build with mismatch → build fail.
- Acceptance criteria include four concrete checks: revision present in YAML and read by `install_nlp_models.py`; manifest exists post-first-build with all weight digests; second build passes digest match; **tamper test** required (flip a byte → build fails with clear error).
- SEC-003 (lines 208–209) names the manifest as the "supply-chain trust anchor" and explicitly acknowledges that revision pinning alone is insufficient.

Verifiability check (iter 2 specialist brief question): YES — `huggingface_hub.snapshot_download` writes files to a known cache path; `install_nlp_models.py` walks them and computes SHA-256 against the checked-in JSON. This is mechanically verifiable at build time. The TOFU baseline (first build's manifest) is checked in as a "deliberate, reviewable commit" — explicitly named, not hidden.

Subsumes the iter 1 LOW "pinning mechanism choice deferred to implementation" by removing the `or` branch.

### Iter 1 Finding 2: Two-phase startup contract (Reliability MEDIUM + LOW asymmetric failure modes)
**Status:** ACCEPTED.
**Evidence:**
- New REQ-005a (lines 104–115) explicitly wires `/health` 200 to `MultiNlpEngine.is_loaded() == True` for **every** configured language. Partial-load → `/health` 503 OR HTTP server unbound (both acceptable). Process exits non-zero on `load()` raise. "No silent fallback" is the structural anchor.
- FAIL-002 (lines 268–278) generalized from `de_core_news_sm`-only to "any sub-engine load failure (en or de; spaCy or transformer)" with **five concrete trigger cases enumerated**: en_core_web_lg corrupt; de_core_news_sm corrupt; xlm-roberta-large corrupt or digest-mismatch; transformers/torch import failure; HF tokenizer instantiation failure (e.g., `sentencepiece` missing).
- Validation requires parametrized unit tests across the three sub-engine slots and an integration test exercising the analyzer process exit path or `/health` 503 for at least one case.
- MODULE-001 Hides (line 330) updated: "`load()` and `is_loaded()` together guarantee atomic two-phase startup … no partial state … `process_text` / `process_batch` do not lazy-load on the request path."

Iter 2 specialist brief question (`/health` endpoint owner): the spec consistently refers to "the analyzer's `/health` endpoint" (analyzer-side, Presidio's). The startup model (engine creation before HTTP bind) is plausible because Presidio's `app.py` constructs the engine eagerly during Flask app initialization; if `load()` raises, the import fails and the server never binds. The integration test in REQ-005a's acceptance verifies the observable behavior, which is the right specification level.

FAIL-002's five trigger cases satisfy the iter 2 brief's question about concrete enumeration.

Subsumes the iter 1 LOW "asymmetric load failure modes not enumerated."

### Iter 1 Finding 3: REQ-014 cold-start measurement (Performance MEDIUM + LOW latency baseline)
**Status:** ACCEPTED.
**Evidence:**
- REQ-014 (lines 161–174) requires the cold-start measurement on either (a) deployment-target hardware (recorded CPU model, core count, RAM, disk type) with `1.3×` margin, or (b) developer-class machine with `2×` safety margin. `start_period = max(30s, ceil(margin × measured))`. The chosen option, hardware description, and arithmetic must appear in the implementation report.
- PERF-001 (lines 181–192) binds latency to three named anchor inputs: short bare-noun (`Personalausweis` from REQ-009), sentence-context PII (`Personalausweis Nummer L01X00T47.` from existing `de.yaml`), and long-document (>500 tokens, exercising `stride: 16` windowing). Median over N≥5 runs with N recorded.
- Anchors are re-measured on every future change touching the `de` NLP path — converts "wide range" into stable comparison baseline.

Iter 2 specialist brief questions (anchor representativeness, load-once concrete test):
- Anchors span the three dimensions that drive transformer latency on CPU: minimal input (bare noun), representative short PII (the headline use case), and long-document stride traversal. Reasonable distribution — not arbitrary.
- The model-load-once invariant cites a concrete test (REQ-001 acceptance, line 88): "two consecutive `process_text` calls do not re-invoke the underlying spaCy / transformers loaders (verified by patching the loaders and asserting call count == 1 from the `load()` step only)." This is mockable, deterministic, and runs in the unit-test layer — strictly better than a startup-completion log line.

### Iter 1 Finding 4: Model-load-once invariant (Performance MEDIUM, structural)
**Status:** ACCEPTED.
**Evidence:**
- REQ-001 (lines 82–88) has an explicit "Model-load-once invariant" paragraph: all sub-engine artifacts loaded **exactly once** during analyzer startup via a single `MultiNlpEngine.load()` call from `AnalyzerEngineProvider.create_engine()`; `process_text` and `process_batch` MUST NOT trigger model load on the request path; calling `process_text` before `load()` MUST raise (no lazy-load).
- Acceptance: two new unit tests — (1) pre-load `process_text` raises a clear error; (2) two consecutive `process_text` calls produce loader call count == 1.
- PERF-002 (lines 194–195) cross-references REQ-001's invariant explicitly. MODULE-001 Hides (line 330) clarifies the cross-engine load coordination.

## Findings by Specialist (Iteration 2 — fresh)

### Security Findings

- **LOW** Long-document anchor for digest verification timing not bounded
  - Evidence: REQ-013 acceptance (lines 153–157) requires the second build to "report digest match for every file" but does not put a bound on the verification step's runtime cost. For ~2.2 GB of weights split across multiple safetensors / pytorch_model.bin shards, recomputing SHA-256 on every build adds tens of seconds per build.
  - Risk: cosmetic; does not threaten security; just a latent CI cost. The check is correct as specified.
  - Resolution: optional — add a one-line note to REQ-013 acknowledging that digest verification adds CPU cost proportional to weight file size (linear scan); acceptable for a build-time check. Not a blocker.

No further security concerns found. Checked: hardcoded secrets in spec examples (none — REQ-013 and SEC-003 describe but don't commit); authz on state-changing endpoints (analyzer internal-only per SEC-004); input validation at the trust boundary (REQ-010 preserves Redakt's `max_text_length`); logging that leaks PII (PRIV-001 / SEC-001 affirm metadata-only audit logging); CORS / CSP (out of scope — internal compose network); rate limiting (existing posture preserved); IDOR / mass assignment (no new endpoints); cryptographic primitive without rationale (SHA-256 for build-time integrity is appropriate — collision-resistance is the property needed and SHA-256 satisfies it; no rationale gap); supply-chain TOFU baseline (acknowledged: "deliberate, reviewable commit" — operator-reviewed first manifest is the trust anchor).

### Performance Findings

- **LOW** PERF-001 long-document anchor is referenced but not explicitly named as a fixture
  - Evidence: PERF-001 (line 188): "**Long-document anchor (`de` >500 tokens):** the long-text calibration phrase added per EDGE-006." EDGE-006 (lines 252–253): "at least one fixture with German text >500 tokens is exercised during calibration" — but EDGE-006 does not concretely add a phrase, and REQ-009 (which adds the 15 new fixtures) lists only short bare-noun fixtures.
  - Risk: the implementer must backfill the long-document fixture without an explicit REQ pointer to a specific phrase. If the implementer skips this, PERF-001's third anchor silently degrades to a no-op (no measurement captured).
  - Resolution: add a sub-REQ to REQ-009 (or a new REQ-009b) explicitly creating a >500-token German phrase fixture for long-document calibration; cross-reference from EDGE-006 and PERF-001. Or, accept that the implementer will add this fixture during step 6 (calibration) and document that EDGE-006's "at least one" requirement implicitly anchors it. Either is acceptable; the spec should pick one.

No further performance concerns found. Checked: synchronous external call on hot path (REQ-013 confirms baked-at-build, no runtime HF call — SEC-003); unbounded list response (N/A — text-in, entities-out per REQ-010); write amplification (N/A — stateless per PRIV-001/-002); polling instead of events (N/A); cold-start re-measurement loop (REQ-014 1.3×/2× margin formula closes this); model-load-once invariant (REQ-001 paragraph + acceptance tests are concrete, structural — closes brief anti-pattern #3); image size growth acknowledged in PERF-003.

### Privacy Findings

No privacy concerns found. Checked:
- The iter 1 fix introduced `multi.model_digests.json` — verified this contains only file paths and SHA-256 hashes of weight files (REQ-013 line 149: "per-file: `{path: sha256}`"). No PII surface.
- REQ-005a wires `/health` to engine load state — `/health` body is a status check, no PII surface; logs identify which sub-engine failed (FAIL-002 line 276), not user input.
- PERF-001 latency capture timing is non-PII; capture into `reports/` is operator-controlled.
- Logging captures original text (REQ-010 + SEC-001 + PRIV-001 collectively confirm `audit.log_detection` is byte-for-byte preserved, metadata-only; iter 1 fixes do not touch the audit path).
- Audit log includes detected entity values (PRIV-001 explicitly preserves the existing schema; iter 1 changes do not modify audit).
- Mapping persisted server-side (PRIV-002 unchanged).
- Calibration corpus contains real PII (verified earlier — synthetic identifiers; the 15 new bare-noun fixtures from REQ-009 are common nouns, no PII).
- Eval fixtures contain real PII (same — synthetic).
- Cross-border transfer to HF Hub (REQ-013 + SEC-003 confirm HF egress is build-time only and downloads weights, not user data).
- Model file caching server-side leaking training-data echoes (NER models emit token-level labels, no echo surface).
- BDSG / GDPR-DE specifics (preserved verbatim by REQ-010 / PRIV-001 / PRIV-002).
- DSR (no PII at rest, inherited unchanged from existing architecture).

### Reliability Findings

No reliability concerns found. Checked:
- Two-phase startup contract (REQ-005a) is concrete: `/health` ↔ `is_loaded()` for ALL languages; partial-load → 503 or unbound; non-zero exit on `load()` raise. Closes brief anti-pattern #1.
- FAIL-002 enumerates 5 trigger cases (en model corrupt; de_core_news_sm corrupt; xlm-roberta corrupt or digest fail; transformers/torch import; HF tokenizer instantiate). Closes brief anti-pattern #7.
- Silent fallback to degraded engine explicitly disallowed (REQ-005a, FAIL-002).
- Language unsupported behavior (FAIL-003 specifies `ValueError`; defense-in-depth wired to REQ-010).
- Recognizer registry drift between containers (single analyzer container per MODULE-007 — N/A).
- Restart semantics for calibration tool (REL-003 + FAIL-004 confirm dev-time only).
- Calibration corpus missing at runtime (FAIL-004 confirms non-blocking).
- Cold-start traffic spike on restart (still a LOW from iter 1, deferred to 3e — not re-flagged).
- Asymmetric per-language failure modes (closed by FAIL-002 generalization).
- Readiness probe contract (closed by REQ-005a explicit `/health` 200 ↔ all-engines-loaded wiring).

### Module Depth Findings

- **LOW** Digest manifest ownership is split implicitly between MODULE-002 and MODULE-003
  - Evidence: REQ-013 introduces `presidio/presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json`. MODULE-002 (config schema, lines 341–351) lists `multi.yaml` in its Public Interface and includes REQ-013 in Spec refs (line 351), but does not name the digest manifest. MODULE-003 (install dispatcher, lines 355–363) Hides "Revision-pinning logic" (line 359) and includes REQ-013 in Spec refs (line 363), but does not explicitly name the digest manifest as an owned artifact.
  - Risk: the manifest sits in `conf/` (suggesting MODULE-002 ownership) but is read+written by `install_nlp_models.py` (suggesting MODULE-003 ownership). An implementer could plausibly skip checking the manifest in (treating it as a build artifact rather than source-controlled config) without violating either MODULE statement.
  - Resolution: add the manifest to MODULE-002's Public Interface as a peer of `multi.yaml` ("declarative config — `multi.yaml` and `multi.model_digests.json`"); MODULE-003's Hides explicitly states it reads+writes the manifest. This makes the source-controlled invariant explicit. Trivial wording fix; not a blocker.

No further module-depth concerns found. Checked:
- Modules section present (8 modules with Public Interface / Hides / Risk / Spec refs).
- Pass-through wrapper (MODULE-001 dispatch genuinely hides cross-engine coordination — Hides block extended in iter 1 to name two-phase startup explicitly).
- Getter/setter façade (none — `get_supported_*` are lookups, `is_stopword`/`is_punct` are language-aware dispatch).
- Public method per private field (none — protocol-driven public surface).
- Wide interface, thin internals (MODULE-001's 9 public methods balance against substantial hidden complexity — pipeline orchestration, dual-model coordination, lazy-load coordination, two-phase startup).
- Module with no clear purpose (every module has a single concern).
- Implementation types in public interface (MODULE-001 surfaces `NlpArtifacts` and spaCy `Language` — both Presidio public-API domain types; not leakage).
- Unjustified shallow modules (5 of 8 marked shallow with explicit per-module justification — all plausible).
- Missing spec refs (REQ-005a maps to MODULE-001 + MODULE-007 + FAIL-002 — confirmed in Spec refs lines for both modules; REQ-013 maps to MODULE-002 + MODULE-003 — both confirmed; REQ-014 maps to MODULE-007 — confirmed; PERF-002 maps to MODULE-001 + MODULE-007 — confirmed via REQ-001 and REQ-005a refs; every iter 1 new identifier has at least one MODULE Spec refs entry).
- Risk tier missing or implausible (MODULE-001 Medium; MODULE-002 Low; MODULE-003 Medium; MODULE-004 Low; MODULE-005 Medium; MODULE-006 Medium; MODULE-007 Medium; MODULE-008 Low — all unchanged and plausible).

## Cross-Specialist Observations

None. Iter 1's cross-specialist MEDIUM (cold-start / two-phase startup, Reliability + Performance) is fully closed by the combination of REQ-005a (contract), REQ-014 (budget), and REQ-001 model-load-once invariant. The iter 2 LOWs are independent and single-specialist.

## Recommended Actions Before Proceeding

None required. Verdict is PROCEED.

The two LOW findings are nice-to-haves, addressable inline during implementation or in Step 3e:

1. **PERF-001 long-document anchor naming** (Performance LOW) — add a sub-REQ (REQ-009b or extend REQ-009) explicitly creating the >500-token German fixture, or accept implicit backfill during step 6 calibration.
2. **Digest manifest module ownership** (Module Depth LOW) — name `multi.model_digests.json` in MODULE-002's Public Interface and MODULE-003's Hides. Wording fix.

The 6 iter 1 LOW findings (deferred to 3e) are unchanged and stand for the combined critical-review fix step.

## Panel Metadata

- Iteration 1 → Iteration 2 finding count delta: HIGH 0 → 0, MEDIUM 4 → 0, LOW 6 → 2. (Iter 1 LOWs were deferred to 3e per orchestrator plan, not re-evaluated here; iter 2 LOWs are net-new from re-read.)
- **Iter 1 fix acceptance:** all 4 MEDIUM findings ACCEPTED. Two related LOWs ("pinning mechanism choice deferred" and "asymmetric load failure modes not enumerated") subsumed by the iter 1 fix.
- **Specialists with no findings (iter 2):** Privacy, Reliability.
- **Specialists with findings (iter 2):** Security (1 LOW), Performance (1 LOW), Module Depth (1 LOW). Note: the digest-manifest-runtime-cost LOW from Security is cosmetic/acknowledgement-only.
- **Total iter 2 findings:** HIGH=0, MEDIUM=0, LOW=2 (treating Security's cosmetic note and Module-Depth's wording fix as the binding LOWs; Performance's missing-anchor LOW is the most actionable).
- **Cross-specialist findings (iter 2):** 0.
- **Verdict:** PROCEED.
- **Execution note:** This environment did not expose a `Task` / general-purpose-subagent spawning tool, so each specialist was applied sequentially within the orchestrator's context using verbatim specialist briefs (vocabulary, anti-patterns, output schema) from the iter 1 review document and the iter 2 panel prompt. Generator-evaluator separation is preserved at the spec-author level (the spec was authored in Step 3a by a different subagent instance; the iter 1 fix subagent produced the post-fix edits in a separate context); the iter 2 panel reviewer (this orchestrator) did not author either the spec or the fix. Findings are evidence-backed against spec text I read directly. Counter usage: Reads 4/10, Nested subagents 0/6 — well within budget.

---

## Findings Addressed (Iteration combined-3e)

All net-new iter 2 LOW findings (3 total) are addressed in this combined fix step alongside the iter 1 deferred LOWs and the critical-review findings.

### PERF-001 long-document anchor is referenced but not explicitly named as a fixture
Severity: LOW (Performance)
Resolution: New REQ-009b added with three concrete fixtures: a held-out positive DE LOCATION fixture (e.g., `Sie wohnt in Berlin und arbeitet in München.`), a held-out positive DE DATE_TIME fixture (e.g., `Der Termin ist morgen um 14 Uhr.`), and a long-document anchor (>500 transformer tokens). The long-document fixture is the explicit named asset that PERF-001's "Long-document anchor" line refers to (PERF-001 was updated to point at REQ-009b item 3). EDGE-006 was also updated to reference REQ-009b. The iter 2 ambiguity ("backfilled implicitly during step 6") is closed by promoting the fixture to a REQ.
Spec location: REQ-009b (new); PERF-001 (long-document anchor bullet updated); EDGE-006 (validation line updated); Implementation Notes step 7 (updated to add the 3 new fixtures).

### Digest manifest ownership is split implicitly between MODULE-002 and MODULE-003
Severity: LOW (Module Depth)
Resolution: MODULE-002's Public Interface now explicitly names `multi.model_digests.json` as a peer of `multi.yaml` ("checked-in supply-chain trust anchor … Updated by deliberate, reviewable commit only"); MODULE-002's Hides clarifies the split ("MODULE-003 is responsible for *reading and writing* the digest manifest at build time; MODULE-002 *owns* it as source-controlled config"). MODULE-003's Hides extended with a "Digest-manifest read/write logic" bullet documenting that the dispatcher reads the manifest, recomputes per-file SHA-256, fails the build on mismatch, and writes a fresh manifest on the first known-good build. The split is now explicit and source-controlled-vs-build-time-logic.
Spec location: MODULE-002 Public Interface + Hides (extended); MODULE-003 Hides (extended).

### Long-document anchor for digest verification timing not bounded (cosmetic)
Severity: LOW (Security, cosmetic)
Resolution: REQ-013 acceptance section gained a "Note (build-time cost)" paragraph explicitly acknowledging that recomputing SHA-256 on every build is linear in total weight-file size (~2.2 GB), adding tens of seconds per build — acceptable for a build-time integrity check, called out so future CI optimization work has the right framing. No test required (cosmetic).
Spec location: REQ-013 (note appended after acceptance).
