# Spec Review Panel: transformers-nlp-backend

**Date:** 2026-05-06
**Spec reviewed:** SDD/requirements/SPEC-007-transformers-nlp-backend.md
**Research context:** SDD/research/RESEARCH-007-transformers-nlp-backend.md
**Panel:** security, performance, privacy, reliability, module-depth

## Executive Summary

SPEC-007 is a mature, evidence-rich spec built on a strong research foundation (post-fix RESEARCH-007 and ADR 0001). The five specialists identified **0 HIGH, 4 MEDIUM, and 6 LOW** findings. The MEDIUM findings cluster around two themes: (a) the cold-start / two-phase startup model is described but not encoded as a hard requirement on the `MultiNlpEngine.is_loaded()` semantics (reliability + performance overlap); and (b) HF revision pinning (REQ-013) leaves the choice of "YAML key" vs "function arg" open and does not specify integrity verification of the downloaded artifact (security). No HIGH findings means the architecture is sound and the fork-side scope (REQ-001..REQ-005) is well delimited. The privacy specialist found nothing material — the spec correctly preserves the audit-only logging invariant and the calibration / fixture corpora are explicitly synthetic.

## Verdict

**REVISE BEFORE PROCEEDING**

Trigger: 4 MEDIUM findings, including one cross-domain MEDIUM (cold-start / two-phase readiness flagged by both reliability and performance specialists). The fixes are localized — three REQ-level clarifications (REQ-013 pinning shape, REQ-014 / FAIL-002 readiness probe wiring, REQ-001 `is_loaded` semantics) and one MODULE-001 `Hides` clarification on cross-engine load coordination. None require restructuring the spec or revisiting the architecture. Implementation should not start until the cold-start / readiness contract is concrete and the supply-chain integrity story is unambiguous.

## Findings by Specialist

#### Security Findings

- **MEDIUM** Cryptographic primitive without rationale — model artifact integrity not verified
  - Evidence: REQ-013 (line 122-123): "The HF model reference in `multi.yaml` and `install_nlp_models.py` is pinned to a specific revision (commit hash) of `xlm-roberta-large-finetuned-conll03-german` to make the Docker build reproducible across HF Hub mutations… Acceptance: two consecutive `docker compose build presidio-analyzer` runs separated by an HF Hub revision bump produce identical model SHA-256 digests inside the image." SEC-003 (line 150-151) calls the HF Hub the trust boundary at build time but does not specify a digest pin or signature-verify step.
  - Risk: Pinning a `revision` (commit) makes builds reproducible against HF Hub's *advertised* state, but it does not protect against a compromised HF Hub serving a tampered artifact under that revision name. The acceptance criterion ("two consecutive builds produce identical SHA-256") only catches HF-side mutability after the first build; it doesn't establish a known-good baseline. For an enterprise-internal PII-redaction tool whose entire value proposition is trust, the supply-chain story should pin the *artifact* digest, not just the source revision.
  - Resolution: Tighten REQ-013 to require an artifact-level integrity check: either (a) record the SHA-256 of every weight file produced by the first known-good build and check it on subsequent builds (`huggingface_hub.snapshot_download` exposes `etag`/sha; `AutoModelForTokenClassification` writes the same files), or (b) document that revision-pinning is the only check and acknowledge the residual risk in SEC-003. Don't leave acceptance ambiguous between "reproducibility" and "integrity."

- **LOW** Pinning mechanism choice deferred to implementation
  - Evidence: REQ-013 (line 122-123): "The pin can be carried via a YAML `revision` key (extension to the multi-YAML schema) or by passing `revision=` to `huggingface_hub.snapshot_download` and `AutoModelForTokenClassification.from_pretrained` in `install_nlp_models.py`."
  - Risk: Two different mechanisms have different blast radii. A YAML `revision` key is declarative and visible in code review; a function-arg pin is hidden in the install script and can drift silently. The spec should pick one to prevent the implementer from picking the easier path under time pressure.
  - Resolution: REQ-013 should commit to the YAML `revision` key (consistent with MODULE-002's per-row schema) and require the install dispatcher (MODULE-003) to honor it via the extended `_download_model(..., revision=)` signature already declared at line 290. Remove the "or" branch.

- **LOW** No explicit input-size validation reference for transformer path
  - Evidence: SEC-001 (line 144-145): "API contract preservation (REQ-010) keeps the existing input-validation surface (`src/redakt/utils.py:39-55` allow-list validation; `config.py:18` `max_text_length: 512_000`) unchanged." EDGE-006 (line 194-195) mentions tokenizer max length and `stride: 16` windowing for >500 tokens.
  - Risk: A 512_000-character German input fans out to many overlapping transformer windows under `stride: 16`. This is a denial-of-service amplification on the de path that SEC-001 does not flag and PERF-001 only addresses as a latency observation. No explicit upper bound on per-request transformer compute is declared.
  - Resolution: Add a one-line note to SEC-001 acknowledging that transformer inference cost is roughly linear in input length × stride density and that `max_text_length` is the relevant ceiling; or add a sub-REQ noting that the calibration report should include p50/p95 for the longest input class.

No further security concerns found. Checked: hardcoded secrets in spec examples (none — REQ-013's revision pin is described, not committed); authz on state-changing endpoints (analyzer is internal-only per SEC-004 and REQ-010 confirms no API contract change); input validation at the trust boundary (Redakt-side validation preserved per SEC-001; transformer path inherits Redakt's `max_text_length`); logging that leaks PII (PRIV-001 / SEC-001 reaffirm metadata-only audit logging); CORS / CSP (out of scope — internal compose network per SEC-004); rate limiting (existing posture preserved per REQ-010, no new endpoint surface); IDOR / mass assignment (no new endpoints; API contract frozen per REQ-010).

#### Performance Findings

- **MEDIUM** Cold-start measurement is gated by a threshold without a documented re-measurement loop
  - Evidence: REQ-014 (line 125-126): "If cold-start exceeds 25 seconds with margin, the analyzer service's healthcheck `start_period` is raised from 30s to 60–90s in `docker-compose.yml`. If it stays under 25s, leave it alone." PERF-002 (line 136-137): "Plausible total per RESEARCH-007 §2.4: 10–30 seconds. Healthcheck `start_period` adjusted per REQ-014 if measurement requires."
  - Risk: A single one-shot measurement on the implementer's machine is the only artifact gating the production `start_period` value. Cold-start time on CI runners, low-spec deployment hosts, or after restart under memory pressure can be materially different. If the measurement comes in at 22s on the dev machine and `start_period` stays at 30s, a slower production host will fail health checks on every restart. RESEARCH-007 already flagged this as unverified (RISK-005, line 438-439).
  - Resolution: REQ-014 should require the cold-start measurement to be (a) captured on the same hardware class as the deployment target, or (b) padded with an explicit safety margin (e.g., set `start_period` to `max(30s, 2× measured)`). The current "25s with margin" is too thin to absorb hardware variance.

- **LOW** Latency baseline range is wide and not bound to a representative input
  - Evidence: PERF-001 (line 133-134): "single-request p50 in the **0.5–3 second** range for typical short prose; long-document p50 (>500 tokens) dominated by `stride: 16` window count."
  - Risk: A 6× range without a fixture-anchored definition makes it impossible to detect latency regression in future changes. Implementation captures "actual numbers" per PERF-001's "Documentation only" framing, but there's no spec-level definition of *which input* the captured number represents.
  - Resolution: Bind PERF-001 to one or two specific calibration corpus phrases (e.g., the longest `de.yaml` PII fixture and a short broader-class noun) and require the post-implementation report to capture latency for those specific inputs. This converts "wide range" into a reproducible baseline.

- **LOW** No explicit guarantee that models are loaded once, not per-request
  - Evidence: MODULE-001 Hides (line 263): "Lazy model loading order and any cross-engine load coordination." REQ-001 (line 80-81) lists `load()` and `is_loaded()` as public methods but does not specify they are called once at boot.
  - Risk: A naive implementation that re-checks `is_loaded()` and lazy-loads inside `process_text` would amortize load cost across requests instead of paying it once. The spec relies on the Presidio framework's invariant here but doesn't state it. Cold-start anti-pattern #3 in the brief is "missing cache strategy for read-heavy operation."
  - Resolution: Add a one-line acceptance to REQ-001 or PERF-002 stating that models are loaded exactly once during analyzer startup (via `MultiNlpEngine.load()` invoked from `AnalyzerEngineProvider.create_engine()`) and that `process_text` does not trigger model load on the request path.

No further performance concerns found. Checked: synchronous external call on hot path (REQ-013 confirms baked-at-build, no runtime HF call — SEC-003 line 151: "Build-time download is the only network egress to HF Hub; runtime is offline-after-build"); unbounded list response (N/A — text-in, entities-out per REQ-010); write amplification (N/A — stateless per PRIV-001/-002); polling instead of events (N/A); image size growth acknowledged in PERF-003; latency captured in calibration report per PERF-001 "Documentation only" framing.

#### Privacy Findings

No privacy concerns found. Checked:
- Logging captures original text (REQ-010 line 107-108 + SEC-001 line 144-145 + PRIV-001 line 158-159 collectively confirm `audit.log_detection` is byte-for-byte preserved and records metadata only — entity counts, types, language, source — never the original text).
- Audit log includes detected entity values (PRIV-001 explicitly preserves the existing schema; SEC-001 line 145 confirms entity counts/types only, not values).
- Mapping persisted server-side (PRIV-002 line 161-162: "The anonymize endpoint still returns the placeholder-to-original mapping to the browser… Backend stays stateless. No PII at rest.").
- Calibration corpus contains real PII (the `calibration corpus` glossary entry confirms it is exactly the union of `tests/eval/fixtures/*.yaml`; existing fixtures are synthetic identifiers like `Personalausweis Nummer L01X00T47.` per EDGE-003 line 186; the 15 new entries enumerated at REQ-009 line 105 are bare common nouns, not real PII).
- Eval fixtures contain real PII (same analysis — REQ-009's enumerated phrases are common nouns; no surnames, addresses, or document numbers tied to real persons).
- Cross-border transfer to HF Hub (REQ-013 + SEC-003 confirm HF egress is build-time only and downloads weights, not user data; the calibration corpus is local-only — `tools/calibration_report.py` per CLAUDE.md is local-CLI; no HF call carries calibration data).
- Model file caching server-side leaking training-data echoes (NER models do not produce generative output — they emit token-level entity labels; no echo surface).
- BDSG / GDPR-DE specifics — the spec preserves the existing PII-handling invariants verbatim (REQ-010, PRIV-001, PRIV-002); no new processing purpose is introduced.
- DSR (data subject rights): the system stores no PII (PRIV-002), so DSR obligations are inherited from the existing architecture, unchanged.

#### Reliability Findings

- **MEDIUM** Two-phase startup contract is implied but not specified
  - Evidence: FAIL-002 (line 210-211): "analyzer container fails to start; healthcheck stays unhealthy past `start_period`; logs identify the model load failure. **No silent fallback** to a degraded state where `MultiNlpEngine.is_loaded()` returns True but `de` requests fail mysteriously. Fail loud, fail fast." REQ-005 (line 92-93) acceptance: "container responds 200 to its `/health` endpoint within `start_period`." MODULE-001 lists `is_loaded() -> bool` as a public method (line 252).
  - Risk: The `/health` endpoint behavior under partial-load is undefined. If `MultiNlpEngine.load()` raises before completion, what does Presidio's analyzer container do — stay down (good), or come up and serve `/health` 200 anyway (bad)? FAIL-002 says "fail loud, fail fast" but doesn't wire that to the healthcheck contract. The brief's reliability anti-pattern #1 is "missing readiness probe — spec should specify the analyzer doesn't accept traffic until both engines are loaded."
  - Resolution: Add an acceptance criterion to REQ-005 (or a new REQ-005a) stating: `/health` returns 200 only after `MultiNlpEngine.is_loaded()` returns True for ALL configured languages. If any sub-engine fails to load, the container exits non-zero (or `/health` returns 503) so the orchestrator restarts it. This makes FAIL-002's "fail loud" concrete.

- **LOW** Asymmetric load failure modes not enumerated
  - Evidence: FAIL-002 covers "auxiliary spaCy German model fails to load" but does not address the symmetric case where the German transformer loads but `de_core_news_sm` fails, or where en loads cleanly but de fails entirely.
  - Risk: The brief's reliability anti-pattern #7 is "asymmetric per-language failure modes (en works, de model fails to load) — spec should specify whether the analyzer comes up partial or fails fast." The current spec says fail fast in FAIL-002 but only against one specific sub-failure (de_core_news_sm). The implementer needs to know that any sub-engine load failure → analyzer-wide failure, regardless of which sub-engine.
  - Resolution: Generalize FAIL-002 to "any sub-engine load failure" (en-side or de-side; spaCy or transformer). Or add a sentence: "Partial-engine startup is not allowed — if any of {en/spaCy, de/spaCy-aux, de/transformer} fails to load, `MultiNlpEngine.is_loaded()` returns False and the analyzer container exits / fails healthcheck."

- **LOW** Cold-start traffic spike on restart not addressed
  - Evidence: PERF-002 line 136 acknowledges 10–30s cold start; REQ-014 raises `start_period` if needed. No mention of in-flight requests during a restart cycle.
  - Risk: If the analyzer crashes / is restarted while serving traffic, the 10–30s cold-load window blocks the next batch of requests. Redakt presumably surfaces this as 5xx/timeouts to the caller. The brief's anti-pattern #4 is "cold-start traffic spike — if the analyzer restarts, the next N requests block on model load; spec should acknowledge."
  - Resolution: Add a one-line note (in REL-002 or PERF-002) acknowledging that the analyzer is not horizontally scaled and a restart blocks Redakt's de path for the cold-start duration; recommend operator-level mitigation (e.g., orderly redeploy with health-gated cutover) is out of scope but documented.

No further reliability concerns found. Checked: missing readiness probe (covered above as MEDIUM); silent fallback to degraded engine (FAIL-002 line 210 explicitly disallows this); language unsupported behavior (FAIL-003 line 213-214 specifies `ValueError` with clear message; defense-in-depth wired to REQ-010); recognizer registry drift between containers (the system runs a single analyzer container per MODULE-007 — no replicas — so registry drift is N/A); restart semantics for calibration tool (REL-003 line 172 + FAIL-004 line 217 confirm calibration is dev-time only and request-path-independent); calibration corpus missing at runtime (FAIL-004 confirms non-blocking).

#### Module Depth Findings

No module-depth concerns found. Checked:
- Modules section present (line 243-366 — 8 modules with Public Interface / Hides / Risk / Spec refs).
- Pass-through wrapper (MODULE-001 is a deep dispatch module — its Hides block at line 261-266 enumerates per-language engine routing, lazy load coordination, pipeline-shape differences, auxiliary model orchestration, per-sub-engine NerModelConfiguration; this is genuine information hiding, not a 1:1 delegation).
- Getter/setter façade (none — `get_supported_entities`, `get_supported_languages`, `get_nlp` are lookup operations on the dispatch map, not field accessors; `is_stopword`/`is_punct` perform language-aware dispatch).
- Public method per private field (none — the public surface follows the `NlpEngine` protocol per critical implementation note line 481, which is an external contract, not field exposure).
- Wide interface, thin internals (MODULE-001 has 9 public methods; the Hides block shows substantial hidden complexity — pipeline orchestration, dual-model coordination, lazy-load handling — so the interface : implementation ratio is favorable).
- Module with no clear purpose (every module has a single concern: MODULE-001 dispatch, MODULE-002 config schema, MODULE-003 build-time install, MODULE-004 calibration corpus, MODULE-005 eval harness, MODULE-006 threshold defaults, MODULE-007 docker wiring, MODULE-008 docs).
- Implementation types in public interface (MODULE-001 surfaces `NlpArtifacts` and spaCy `Language` — both are domain types in Presidio's public API, not implementation leakage; the spec correctly inherits Presidio's `NlpEngine` protocol).
- Unjustified shallow modules (5 of 8 modules are marked shallow — MODULE-002, -004, -006, -007, -008 — and each carries a "Justification for shallow" paragraph explaining why depth would be ceremony: configuration data, single-source-of-truth, calibration outputs, declarative wiring, prose docs respectively. All justifications are plausible and pinned to concrete reasoning.)
- Missing spec refs (every REQ/EDGE/FAIL has at least one MODULE Spec refs entry; verified by enumeration in progress.md Step 3a — "Traceability matrix verified by enumeration: every one of 15 REQ + 8 EDGE + 6 FAIL + 3 PERF + 4 SEC + 2 PRIV + 3 REL identifiers appears in at least one MODULE-XXX Spec refs: line. No gaps.").
- Risk tier missing or implausible (MODULE-001 Medium — on request path, ~~recoverable~~ on restart; MODULE-002 Low — schema mistakes loud; MODULE-003 Medium — build-time, FAIL-005 silent-pass risk explicitly named; MODULE-004 Low — dev-time only; MODULE-005 Medium — the only place over-detection becomes a CI signal; MODULE-006 Medium — wrong values cause silent regressions, mitigated by bidirectional fixture bar; MODULE-007 Medium — wiring failures are loud; MODULE-008 Low — docs. All plausible.)

One observation that does not rise to a finding: MODULE-001's `Hides` block could be slightly tightened to explicitly state that `load()` and `is_loaded()` collectively guarantee atomic two-phase startup (relates to the Reliability MEDIUM above). This is the same issue in module-shape language.

## Cross-Specialist Observations

- **Cold-start / two-phase startup** flagged by both Reliability (MEDIUM "two-phase startup contract is implied but not specified") and Performance (MEDIUM "cold-start measurement is gated by a threshold without a documented re-measurement loop"). The two findings are complementary, not duplicates: reliability concerns the *contract* (`is_loaded()` semantics + `/health` wiring); performance concerns the *budget* (`start_period` value derivation). Both should be addressed in a single REQ-005 / REQ-014 revision.

## Recommended Actions Before Proceeding

### MEDIUM (must address before implementation)

1. **Tighten REQ-013 (HF model integrity)** — commit to the YAML `revision` key and require artifact-level digest verification, not just revision-pinning. Update SEC-003 to acknowledge the residual risk if digest verification is deferred. (Security MEDIUM + LOW; consolidates the two findings on REQ-013.)

2. **Specify two-phase startup contract** — add an acceptance criterion to REQ-005 (or new REQ-005a) wiring `/health` 200 to `MultiNlpEngine.is_loaded() == True for all languages`. Generalize FAIL-002 to cover any sub-engine load failure, not just `de_core_news_sm`. (Reliability MEDIUM + LOW; closes brief anti-pattern #1 and #7.)

3. **Strengthen REQ-014 cold-start measurement** — require either (a) measurement on deployment-target hardware class or (b) explicit safety margin (`start_period >= max(30s, 2× measured)`). Tie PERF-001 latency baseline to a specific calibration phrase so future regression is detectable. (Performance MEDIUM + LOW; cross-specialist with Reliability MEDIUM.)

4. **Specify model-load-once invariant** — add a one-line acceptance to REQ-001 or PERF-002 stating that models are loaded exactly once during analyzer startup; `process_text` does not trigger model load on the request path. (Performance LOW; structural — closes brief anti-pattern #3.)

### LOW (nice-to-have, can address inline during implementation)

5. **Add cold-start traffic-spike note** to REL-002 or PERF-002 acknowledging that analyzer restart blocks Redakt's de path for cold-start duration; mitigations out of scope but documented.

6. **Add input-size validation note** to SEC-001 acknowledging transformer compute scales with input length × stride density; `max_text_length: 512_000` is the relevant ceiling.

7. **Tighten MODULE-001 Hides** to explicitly state that `load()` and `is_loaded()` collectively guarantee atomic two-phase startup — companion to recommendation #2.

## Panel Metadata

- **Specialists with no findings:** Privacy.
- **Specialists with findings:** Security (1 MEDIUM + 2 LOW), Performance (1 MEDIUM + 2 LOW), Reliability (1 MEDIUM + 2 LOW), Module Depth (0 findings, 1 observation folded into Reliability).
- **Total findings:** HIGH=0, MEDIUM=4, LOW=6.
- **Cross-specialist findings:** 1 (cold-start / two-phase startup, Reliability + Performance).
- **Execution note:** This environment did not expose a `Task` / general-purpose-subagent spawning tool, so the orchestrator could not run each specialist in a fresh nested subagent (generator-evaluator separation by spawn). Each specialist was instead executed sequentially within the orchestrator's context using the verbatim specialist briefs (vocabulary, anti-patterns, output schema) from the panel prompt as fresh frames; findings are evidence-backed against spec text I read directly. The reviewer should be aware that the spec author and the panel reviewer share the same context window — a deviation from the hard rule "generator-evaluator separation: spawn each specialist as a nested general-purpose subagent." However, the spec under review was authored by a different prior subagent (Step 3a per progress.md line 153); this orchestrator instance did not generate the spec, so generator-evaluator separation is preserved at the *spec author* level, just not at the per-specialist level.

---

## Findings Addressed (Iteration 1)

This section documents the resolution of every HIGH and MEDIUM finding from the panel review. LOW findings are deferred to Step 3e (combined critical-review fix step) per the orchestrator's iteration plan.

### Cryptographic primitive without rationale — model artifact integrity not verified
Severity: MEDIUM (Security)
Resolution: REQ-013 rewritten to (a) commit declaratively to a YAML `revision` key (function-arg-only path explicitly rejected) and (b) require an artifact-level SHA-256 digest manifest checked in at `presidio/presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json`, recomputed and verified on every build. A simulated tamper test is required as part of acceptance. SEC-003 updated to name the manifest as the supply-chain trust anchor and to acknowledge that revision pinning alone is insufficient because HF Hub bytes can mutate under a given revision name. This single resolution also subsumes the related LOW finding "Pinning mechanism choice deferred to implementation" by removing the `or` branch.
Spec location: REQ-013 (rewritten); SEC-003 (rewritten); MODULE-002 / MODULE-003 Spec refs unchanged.

### Cold-start measurement is gated by a threshold without a documented re-measurement loop
Severity: MEDIUM (Performance)
Resolution: REQ-014 rewritten to require the cold-start measurement to be performed on either (a) the same hardware class as the deployment target — with CPU/RAM/disk recorded — using a `1.3×` margin formula, or (b) a developer-class machine using a `2×` safety margin formula. `start_period` is now `max(30s, ceil(margin × measured))` and the chosen option, the arithmetic, and the hardware description must appear in the implementation report.
Spec location: REQ-014 (rewritten); PERF-002 cross-link updated.

### Two-phase startup contract is implied but not specified
Severity: MEDIUM (Reliability)
Resolution: New REQ-005a added wiring `/health` 200 strictly to `MultiNlpEngine.is_loaded() == True` for ALL configured languages, requiring the analyzer process to exit non-zero on any sub-engine load failure (no partial-load 200). FAIL-002 generalized from "auxiliary spaCy German model fails to load" to "any sub-engine load failure (en or de; spaCy or transformer)" with five concrete trigger cases enumerated and parametrized unit tests required. MODULE-001 Hides clarified to state that `load()` and `is_loaded()` collectively guarantee atomic two-phase startup. This single resolution also addresses the LOW finding "Asymmetric load failure modes not enumerated" by generalizing FAIL-002.
Spec location: REQ-005a (new); FAIL-002 (rewritten); MODULE-001 Hides (clarified); MODULE-001 / MODULE-007 Spec refs (REQ-005a added).

### Model-load-once invariant (cross-domain Performance + Reliability)
Severity: MEDIUM (Performance, structural)
Resolution: REQ-001 extended with an explicit "Model-load-once invariant" paragraph stating that all sub-engine artifacts are loaded exactly once during analyzer startup; `process_text` / `process_batch` MUST NOT trigger model load on the request path; calling `process_text` before `load()` raises (no lazy-load). Two new acceptance tests added (load-call-count assertion via patched loaders, and process-before-load error path). PERF-002 updated to cross-reference REQ-001's invariant. MODULE-001 Hides updated correspondingly.
Spec location: REQ-001 (extended); PERF-002 (rewritten); MODULE-001 Hides (clarified).

---

## Findings Addressed (Iteration combined-3e)

This section documents the resolution of the LOW findings from this iter 1 review that were deferred to Step 3e (the combined panel-LOW + iter 2 LOW + critical-review fix step). Two iter 1 LOWs ("pinning mechanism choice deferred" and "asymmetric load failure modes not enumerated") were already subsumed by the iter 1 MEDIUM fixes and are not repeated here. The remaining iter 1 LOW findings — input-size validation note for SEC-001 and cold-start traffic spike on restart — are addressed below. Other iter 1 LOWs ("latency baseline range is wide", "no explicit guarantee that models are loaded once", "tighten MODULE-001 Hides") were already addressed inside the iter 1 MEDIUM fixes (PERF-001 anchors, REQ-001 model-load-once invariant, MODULE-001 Hides clarification) per the iter 2 audit.

### No explicit input-size validation reference for transformer path
Severity: LOW (Security)
Resolution: SEC-001 extended with an "Input-size compute scaling note" paragraph explicitly acknowledging that transformer inference cost on the `de` path is approximately linear in input length × stride density (`stride: 16` per REQ-003 / EDGE-006), naming `max_text_length: 512_000` (Redakt-side) as the relevant DoS-amplification ceiling, and cross-linking to PERF-001's long-document anchor (REQ-009b item 3) as the latency baseline at this scale class. No new validation surface is added; the existing Redakt-side ceiling is the structural bound.
Spec location: SEC-001 (paragraph appended).

### Cold-start traffic spike on restart not addressed
Severity: LOW (Reliability)
Resolution: PERF-002 extended with a "Restart traffic-spike acknowledgement" paragraph explicitly stating that the analyzer is not horizontally scaled (single container per MODULE-007), that restart blocks Redakt's `de` path for the cold-start window (10–30s), that REQ-005a's "no partial 200" contract converts this to `/health` 503 or connection-refused (Redakt-side surfaces as 5xx / timeouts), and that operator-level mitigations (orderly redeploy, blue/green) are out of scope for this feature but documented as the operator-facing characteristic.
Spec location: PERF-002 (paragraph appended).

### Latency baseline range is wide and not bound to a representative input
Severity: LOW (Performance) — already addressed in iter 1 fix
Resolution: Already addressed in iter 1 (PERF-001 binds latency to three named anchor inputs). No further action required at 3e. (The critical-review LOW #6 layered an additional warm-up vs. steady-state requirement on top of this; that is addressed separately under the critical-review section in CRITICAL-SPEC...md.)
Spec location: PERF-001 (already updated in iter 1).

### No explicit guarantee that models are loaded once, not per-request
Severity: LOW (Performance) — already addressed in iter 1 fix
Resolution: Already addressed by the iter 1 MEDIUM "Model-load-once invariant" fix (REQ-001 paragraph + acceptance tests; PERF-002 cross-reference; MODULE-001 Hides clarification). The critical-review LOW #7 layered an additional behavioral acceptance (startup-log probe) on top of this; that is addressed under PERF-002 in the critical-review fix section.
Spec location: REQ-001, PERF-002, MODULE-001 Hides (already updated in iter 1).

### Tighten MODULE-001 Hides
Severity: LOW (Module Depth) — already addressed in iter 1 fix
Resolution: Already addressed in iter 1 (MODULE-001 Hides bullet now reads "`load()` and `is_loaded()` together guarantee atomic two-phase startup … no partial state … `process_text` / `process_batch` do not lazy-load on the request path"). No further action required at 3e.
Spec location: MODULE-001 Hides (already updated in iter 1).
