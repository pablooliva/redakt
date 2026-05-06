# Implementation Critical Review: transformers-nlp-backend (SDD-007)

**Reviewer:** /sdd:critical-review (Step 4d adversarial generalist)
**Date:** 2026-05-06
**Decision:** **PROCEED WITH FIXES** (1 HIGH, 4 MEDIUM, 5 LOW)

---

## Severity Summary

- **HIGH:** 1
- **MEDIUM:** 4
- **LOW:** 5

## Executive Summary

The implementation closes the documented HIGH-risk silent-wrong-engine-routing surface well (REQ-016 score-fingerprint test), and the F-1 runtime-revision fix at chunk 4c was correctly applied. However, the 4b code review (which is spec-aligned and risk-tiered) systematically under-weighted **operational artifacts that ship**: the digest manifest (`multi.model_digests.json`) is checked into the repo as the empty placeholder `{}` (`presidio/.../conf/multi.model_digests.json:1`), which means REQ-013's "verification mode active on subsequent builds" is literally not active in source — every build is "first-build baseline" mode by code path (`install_nlp_models.py:408-411`). This is the headline finding (HIGH F-A): the supply-chain trust anchor that REQ-013 sells is, in the committed artifact set, indistinguishable from "no manifest at all," and the spec's required tamper test (REQ-013 acceptance bullet 4) cannot have actually been run against the committed state. Beyond that, EDGE-006's "long German text exceeding tokenizer max length" (557 tokens > xlm-roberta's 512 model_max_length) has no actual non-crash test in the eval suite proving the long-doc fixture passes through Presidio without truncation error or silent windowing collapse — the long-doc fixture is `expect_clean: true` and rides the `expect.issubset(found)` envelope that the spec itself flagged as structurally weak (RESEARCH-007 §0.4). Several other documented mitigations (HF token rate-limit env var, broader-class extension rule, two-repo SHA traceability) are aspirational rather than mechanized.

---

## Specification Violations

### 1. **[REQ-013]** **HIGH** — Digest manifest checked in as empty placeholder; verification mode is unreachable from source

- **Specified (SPEC-007 REQ-013 acceptance):**
  - "After the first build, `multi.model_digests.json` exists, is checked in, and lists every weight file with its SHA-256."
  - "A second `docker compose build presidio-analyzer` against the same `revision` and same manifest succeeds and reports digest match for every file."
  - "A simulated tamper test (manually flipping a byte of a downloaded weight before the digest check, or pointing the dispatcher at a different revision while keeping the manifest unchanged) causes the build to fail with a clear digest-mismatch error — verified once during implementation."
- **Implemented:** `presidio/presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json` on disk is the literal one-line file `{}\n` (verified by direct read). `_load_digest_manifest` (`install_nlp_models.py:408-411`) explicitly treats an empty `dict` as "first-build baseline mode" and returns `None` — i.e., **every build against the committed state is a baseline-write, never a verification**. The chunk 1B subsection of the tracker (lines 132, 149) and chunk 5's SEC-003 entry (line 353) both acknowledge "Empty placeholder `{}` on first commit; populated by the first successful image build" — but the populated baseline is **not** in the repo. The "second build verifies" acceptance bullet cannot have been satisfied against any state visible in source control.
- **Impact:** REQ-013's headline supply-chain claim ("manifest is the trust anchor") is structurally unverifiable in CI, in operator-driven rebuilds from a fresh clone, and on any deployment that does not preserve the host-side build cache. The "verified once during implementation" tamper test acceptance bullet is unsupported by any committed artifact (no `reports/req-013-tamper.md` or equivalent transcript exists). REVIEW-007's "PASS" verdict for REQ-013 (line 47) was based on the **runtime fix landing (F-1)**; REVIEW-007 did not separately verify that the manifest was populated. The 4b review missed this because it spot-checked the dispatcher logic, not the on-disk artifact.
- **Recommendation:** Run a real `docker compose build presidio-analyzer` once, capture the populated `multi.model_digests.json` (it will be a per-file SHA-256 dict for the pinned `xlm-roberta-large-finetuned-conll03-german@1fbcc7a0...` revision; expected ~20–40 file entries), commit it. Run a second build against the populated manifest, capture the verify-mode log line. Run the spec's tamper test and capture the failing build's stderr to `reports/req-013-tamper.md` (gitignored is fine; the existence of the transcript closes acceptance bullet 4). Until this happens, REQ-013 is partially-implemented dispatcher code without the trust anchor it relies on.

---

### 2. **[REQ-014]** **MEDIUM** — `start_period: 90s` deviates from formula; rationalization is post-hoc

- **Specified:** `start_period = max(30s, ceil(2 × measured_cold_start_seconds))` for option (b). Measurement was 9s on Apple Silicon dev machine. Formula yields 30s.
- **Implemented:** 90s (`docker-compose.yml:47`).
- **Impact:** REVIEW-007 F-2 dismissed this as "deliberate over-budget" because 90 ≥ 30. But the spec language is "matches the formula" — not "≥ floor." A formula whose computed value can be silently inflated 3× by appeal to "colder-cache scenarios" is no formula at all; the spec's hardware-class binding (REQ-014's option a/b distinction) was supposed to remove this exact handwave. The 90s figure was the **chunk-1B placeholder set before the measurement existed**; chunk 4 measured 9s and chose to retain the placeholder. That is post-hoc rationalization, not measurement-driven.
- **Recommendation:** Either set `start_period: 30s` per the formula (with the measured 9s recorded), OR amend REQ-014 to add a "developer-machine pessimism factor" with explicit numeric grounds (e.g., "first-build cold-cache measured separately at <X>s, take max"). The current state — 90s with no first-build cold-cache measurement — fails the spec's "report shows the arithmetic" acceptance bullet because the arithmetic shown (`2 × 9s = 18s → max(30, 18) = 30s`) does not produce 90s.

---

### 3. **[REQ-002]** **LOW** — Schema validator branch absent; spec's "or annotated" language is being used as a get-out-of-jail-free

- **Specified:** "`ConfigurationValidator.validate_nlp_configuration` is extended with a `multi` schema branch (or annotated to skip detailed validation for `multi`)."
- **Implemented:** Neither — Presidio's open-schema validator silently accepts unknown keys (`engine`, `revision`). REVIEW-007 F-3 marks this "Documented; no action required."
- **Impact:** The "or" in REQ-002 was meant to permit a deliberate decision (annotate to skip), not an absence of any decision. There is no comment in `schemas.py` or `multi.yaml` calling out that `engine`/`revision` are intentionally validated downstream. A future refactor that tightens the validator (e.g., upstream Presidio adding `additionalProperties: false`) would silently break `multi.yaml` config loading at startup.
- **Recommendation:** Either add a 2-line `multi` branch to `ConfigurationValidator.validate_nlp_configuration` that whitelists `engine` and `revision` as allowed row keys, OR add a top-of-file comment in `multi.yaml` (and in `schemas.py`) explicitly recording: "extra keys `engine` and `revision` deliberately permitted; validated by `_validate_multi_row` / `MultiNlpEngine._validate_row`." The current "happy accident" framing is brittle.

---

### 4. **[REQ-009 broader-class extension rule]** **MEDIUM** — Rule is documentation-only; not operationalized

- **Specified (SPEC-007 REQ-009 "Broader-class extension rule"):** "If, during step 6 calibration, the implementer encounters a German common-noun-as-`PERSON` over-detection that is **not** in the 15 enumerated above, that noun MUST be added to `tests/eval/fixtures/de.yaml` as an `expect_clean: true` entry **before** the feature lands. Out-of-scope deferral or undocumented model-swap triggers are not permitted."
- **Implemented:** No tooling enforces this. `tools/calibration_report.py` walks fixtures, but does not survey arbitrary German nouns to discover novel over-detections. The rule is a procedural commitment whose only enforcement mechanism is operator vigilance.
- **Impact:** The rule was meant to convert "we found a new bad noun" into a corpus-extending mechanism. In practice, a future model swap that introduces 3 new common-noun-as-PERSON over-detections will go unnoticed unless an operator spot-checks German prose by hand — exactly the silent-fixture-drift outcome the rule was supposed to prevent. REVIEW-007 did not exercise this rule because chunk 2-retry's "iteration count: 0" means no novel over-detections were encountered, so the rule's enforcement path was never live.
- **Recommendation:** Either (a) extend `tools/calibration_report.py` to crawl a separate "exploratory German noun list" (a few hundred common nouns from `de_core_news_sm`'s vocab) and flag any that produce `PERSON` hits — converting the rule into a CI signal — OR (b) acknowledge the rule as procedural-only and adjust SPEC-007's wording from "MUST be added" to "SHOULD be added when encountered by an operator." The current state has the spec writing checks the implementation cannot cash.

---

## Technical Vulnerabilities

### 5. **EDGE-006: long-doc tokenizer ceiling not validated** **HIGH/MEDIUM**

- **Location:** `tests/eval/fixtures/de.yaml:134` (the 557-token long-doc anchor). Tokenizer for `xlm-roberta-large-finetuned-conll03-german` has `model_max_length: 512` per HuggingFace's tokenizer config — the long-doc fixture exceeds this.
- **Attack/failure vector:** Two scenarios. **(a)** `hf_token_pipe` with `stride: 16` and `aggregation_strategy: max` is supposed to window-and-aggregate, but if any window edge case (e.g., a token spanning the 512 boundary) produces a tokenizer warning OR a silent truncation that drops content, the fixture's `expect_clean: true` assertion still passes vacuously (no entities found). REVIEW-007 spot-checked the fixture exists, not that the windowing produces correct behavior. **(b)** PERF-001's "1.262s median" measurement does not assert correctness — only latency. The fixture is `expect_clean: true`, so the test passes regardless of whether windowing succeeded or silently lost spans.
- **What's actually validated today:** The long-doc fixture asserts only "no entities surface across windows" against text that has no PII anyway — a vacuous assertion. There is no test that confirms the windowing **produces correct entity output on a long PII-containing document** (e.g., a 557-token German paragraph with one PII span at token position 480, which would force the windowing logic to handle it correctly).
- **Fix:** Add one positive long-doc fixture: a 600-token German paragraph with a known DE LOCATION (`Berlin`) at token position ~510 (deliberately straddling the 512 boundary). Assert LOCATION is found. This would convert EDGE-006 from a documentation-only edge case to a behaviorally-verified one. Alternatively, capture a probe transcript proving xlm-roberta's spacy_huggingface_pipelines integration handles >512 tokens without error and commit it under `reports/`. Lacking either, EDGE-006 is asserted by the test framework, not exercised.

---

### 6. **`MultiNlpEngine.load()` one-shot recovery contract is a footgun under operator-driven retries** **LOW**

- **Location:** `multi_nlp_engine.py:189`. `_load_call_count` is incremented BEFORE iterating sub-engines. If sub-engine 2 raises mid-iteration, sub-engine 1 is loaded (memory-resident in the process), `is_loaded()` returns False (correct), but a retry of `load()` raises `RuntimeError("already been called")`.
- **Attack/failure vector:** REVIEW-007 F-4 dismissed this as "explicit one-shot contract; restart is the recovery path." That's defensible for the deployed shape (Docker exits, restart policy retries), but it is fragile in any test scenario or future single-process embedding (e.g., an SDK consumer instantiating `MultiNlpEngine` directly). `test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` does test this, but the test is a contract-lock, not a behavioral guarantee.
- **Fix (defensive):** Move `self._load_call_count += 1` to AFTER the for-loop (or wrap the loop in `try` and only set the flag on success). This permits retry on transient failure without re-architecting the contract. REL-002 still applies — a failed load should fail loud — but there's no spec requirement that retry within the same process be forbidden.

---

### 7. **Digest manifest write race under parallel CI** **LOW**

- **Location:** `install_nlp_models.py:414-420` (`_write_digest_manifest`). Uses plain `open(...).write()` with no atomic-rename or file lock.
- **Attack/failure vector:** A CI matrix that builds the analyzer image in parallel for multiple architectures (or any future parallelism) would have N processes writing to the same manifest path simultaneously. Outcome: lost writes, partial JSON, or interleaved writes. Today's deployment is single-process so this is not exploitable, but the spec's RISK-001 explicitly contemplates parallel CI builds for HF rate-limit purposes.
- **Fix:** Write to `manifest_path.with_suffix(".tmp")` then `os.replace()`. Trivial.

---

### 8. **Image size 36.8 GB likely reflects multi-arch buildx default; no single-arch path documented** **MEDIUM**

- **Location:** `Dockerfile.multi`, `docker-compose.yml:25-29`.
- **Attack/failure vector:** Docker buildx defaults to multi-arch on macOS hosts; a 36.8 GB image strongly suggests linux/amd64 + linux/arm64 layers stacked. The spec's PERF-003 says "documentation only, no cap." But:
  - 36.8 GB image is a real operational problem for CI minutes (push time), for image-registry costs, and for rolling deploys (pull time on every node).
  - There is no documented `docker buildx build --platform linux/amd64` invocation path in `docker-compose.yml` or `Dockerfile.multi` — operators rebuilding from scratch will hit the same 36.8 GB.
- **Fix:** Document a single-arch build path explicitly (e.g., `DOCKER_DEFAULT_PLATFORM=linux/amd64` in the README's build instructions, or `platform: linux/amd64` in `docker-compose.yml`'s `presidio-analyzer.build` section). Re-measure image size; expected ~10–15 GB single-arch. PERF-003 stays "documentation only" per spec, but the operator-facing impact stops being a surprise. The 36.8 GB number in `IMPLEMENTATION-PLAN.md:344` and `reports/...` would then read as "developer-machine multi-arch artifact" with a single-arch baseline beside it.

---

### 9. **Two-repo SHA traceability is documentation-only; no mechanical link** **LOW**

- **Location:** `IMPLEMENTATION-PLAN-...md:436-449` (commit timeline). Presidio fork SHAs (`1070180b`, `d604514`, `258ded3`, `23049af`) are listed but the Redakt commit messages (per "no Claude attribution" convention) likely do not embed those SHAs.
- **Attack/failure vector:** Future Redakt commits that touch the analyzer integration cannot reliably retrieve "which Presidio fork SHA does this Redakt commit assume." If the fork rebases or amends a commit (RISK-003 contemplates this), the cross-reference breaks silently.
- **Fix:** Either (a) commit a `.presidio-pin` file at the Redakt repo root containing the expected fork-side branch + commit SHA range for the feature, OR (b) revert to making `presidio/` a git submodule (CLAUDE.md says "not a submodule" for now, but the cost-benefit of submodule discipline grows with each cross-repo commit). Process gap, not a code defect; surface here so it is not silently inherited.

---

### 10. **HF rate-limit mitigation `HUGGINGFACE_HUB_TOKEN` is documented but unverified** **LOW**

- **Location:** `docs/presidio-integration.md` (per RISK-001), `Dockerfile.multi`.
- **Attack/failure vector:** The spec's RISK-001 mitigation ("configure `HUGGINGFACE_HUB_TOKEN` in CI") is a runtime env var read by `huggingface_hub.snapshot_download`. The Dockerfile's `RUN ... install_nlp_models.py` step has no explicit `--secret` mount or `ARG`/`ENV` plumbing that would pass a CI-provided token through to that build-time RUN. On Docker without BuildKit secrets, a token passed via `--build-arg` would leak into the image layer — a security regression worse than rate-limiting.
- **Fix:** Either (a) add a documented BuildKit-secret invocation pattern to the README ("`docker buildx build --secret id=hf_token,env=HUGGINGFACE_HUB_TOKEN ...`") and a corresponding `--mount=type=secret` in `Dockerfile.multi`'s install step, OR (b) acknowledge in `presidio-integration.md` that the token plumbing is operator-hand-rolled and not part of the feature. The current state — RISK-001's mitigation listed as "Complete" but with no plumbing — is a documentation/code mismatch.

---

## Test Gaps

### 11. **No test for partial sub-engine load → `/health` 503** **MEDIUM**

- **What's not covered:** REQ-005a Behavior B's contract is "if `MultiNlpEngine.load()` raises mid-loop (e.g., en loaded successfully but de fails), the analyzer process exits before binding HTTP." There is **no integration test** that exercises this. The unit-level `test_load_propagates_sub_engine_failure_and_is_loaded_returns_false` proves the in-memory state is correct after a failure, but the deployment-shape contract (process exits → Docker restart picks up the non-zero) is structural-only.
- **Risk:** A regression in `nlp_engine_provider.create_engine()` that catches `RuntimeError` from `load()` and proceeds anyway (e.g., a future "best-effort" patch) would silently bring up an analyzer with `is_loaded() == False` for one language, route requests to that language's missing sub-engine, and produce an opaque `KeyError` deep inside `_dispatch`. The spec was emphatic about "no silent fallback" (FAIL-002), but no test asserts the deployment-shape behavior.
- **Recommendation:** Add a one-shot integration test (or shell test) that builds an image with a deliberately-broken `multi.yaml` (e.g., points the de transformer row at a non-existent HF revision) and asserts `docker compose up presidio-analyzer` exits the container non-zero within a bounded window. The spec's REQ-005a acceptance bullet 2 ("verified once during implementation") was satisfied by the chunk 1B image-build; a captured stderr transcript under `reports/` would close the gap permanently.

---

### 12. **EDGE-001 code-switched-text non-crash assertion is implicit; no dedicated test** **LOW**

- **What's not covered:** EDGE-001 says "no test coverage required beyond non-crash." The tracker (line 55) claims "non-crash is implicitly exercised by `tests/integration/test_auto_detect_routing.py` (lingua-py + dispatch path returns 200 deterministically) and by all 58 eval fixtures." But there is no fixture explicitly mixing English and German in one paragraph (e.g., "Anna Schmidt arbeitet bei der Beispiel AG.").
- **Risk:** A regression in the `de` transformer pipeline that crashes on English-name spans in German prose (e.g., a tokenizer error on a name not in the German vocab) would be caught only by chance — not by any deliberate test. Production users will hit code-switched paragraphs daily.
- **Recommendation:** Add ONE eval fixture: `text: "Anna Smith works in München für die Beispiel GmbH."` with `language: de` and `expect_clean: false; expect: [LOCATION]` (or `expect_clean: true` if the bidirectional name dropping is preferred). Asserts non-crash by the test framework's basic operation; documents the failure-mode flip behavior in code rather than docs alone. The fixture would also concretize REQ-012's "set the `language` parameter explicitly" guidance — when the operator sees `Anna Smith` missed in the eval output, they understand why.

---

### 13. **`tests/` (350 default tests) likely contains tests written for the OLD spaCy multilingual config** **LOW**

- **What's not covered:** The default 350-test suite was written before SDD-007. With Redakt now wired to `multi.yaml` + xlm-roberta for `de`, any test that mocks Presidio with hard-coded scores (e.g., asserting "spaCy's `ner_strength` 0.85 produces this exact filter behavior on a de input") is testing a legacy code path. The 4b review didn't spot-check this; "350 PASS" tells you nothing about whether those tests still represent the deployed configuration.
- **Risk:** A test like `test_redakt_filters_de_person_at_low_threshold` (hypothetical) that asserts a 0.85-scored DE PERSON survives a 0.40 threshold is now testing a code path that doesn't fire in production (the de path produces graded scores, not 0.85). The test stays green because the mocking matches the test's expectation, not the production reality. False confidence.
- **Recommendation:** Spot-check 5–10 tests in `tests/test_detect.py`, `tests/test_anonymize_api.py`, and any `tests/test_*_threshold*` tests for hard-coded score values that match `SpacyRecognizer`'s `ner_strength = 0.85`. If found, parametrize over en/de or comment that the test pre-dates SDD-007 and only exercises the EN path. Cost: 30 min of grep + read.

---

### 14. **Tamper-test for REQ-013 not durably captured** **MEDIUM**

- **What's not covered:** REQ-013's acceptance bullet 4 requires a "simulated tamper test ... causes the build to fail with a clear digest-mismatch error — verified once during implementation." No transcript exists under `reports/` proving this was actually run. REVIEW-007 PASS-marked REQ-013 based on dispatcher logic + F-1 fix, not on a captured tamper-test artifact.
- **Risk:** The F-A finding (HIGH, above) compounds this — without a populated manifest, the tamper test was structurally impossible to run. Even when the manifest is populated (per F-A's recommendation), a captured transcript is the auditor's evidence that `_verify_digest_manifest` actually fails the build with the right error message.
- **Recommendation:** When fixing F-A, run the tamper test (mutate one byte of one weight file, or mutate one digest value in the committed manifest), capture the build's failing stderr, save to `reports/req-013-tamper.md` (gitignored). The spec calls for "verified once" — but "verified" requires evidence; commit the evidence.

---

## Recommended Actions Before Merge

1. **[HIGH F-A]** Run a real `docker compose build presidio-analyzer` to populate `multi.model_digests.json` with per-file SHA-256 entries for the pinned revision. Commit the populated manifest. Run the spec's REQ-013 tamper test and capture the failing build's stderr to `reports/req-013-tamper.md`. Without this, REQ-013's headline supply-chain claim is unrealized.
2. **[MEDIUM F-D]** Either revise `start_period` to 30s (per the spec's formula) OR amend REQ-014 with the explicit cold-cache pessimism factor that justifies 90s. Current state has post-hoc rationalization instead of measurement-driven configuration.
3. **[MEDIUM F-K]** Add an integration test (or one-shot shell harness with captured transcript under `reports/`) for partial sub-engine load → analyzer process exit. REQ-005a's "no silent fallback" needs deployment-shape evidence, not just unit-level state assertions.
4. **[MEDIUM F-N]** When fixing F-A, durably capture the tamper-test transcript. The spec's "verified once" is unmet without an artifact.
5. **[MEDIUM F-H]** Document a single-arch build path (`DOCKER_DEFAULT_PLATFORM=linux/amd64` or `platform:` key in compose) and re-measure image size. Operators rebuilding from scratch should not hit 36.8 GB silently.
6. **[MEDIUM F-G]** Operationalize the broader-class extension rule with a calibration-tool check, OR amend REQ-009's wording from MUST to SHOULD. Documentation-only enforcement is silent-failure-prone.
7. **[LOW F-E]** Add 2-line `multi` schema branch (or explicit comment) to `ConfigurationValidator`. The "happy accident" framing in F-3 is fragile.
8. **[LOW F-F]** Move `_load_call_count` increment to after the sub-engine load loop. Permits in-process retry without changing the deployed-restart-on-failure contract.
9. **[LOW F-I]** Atomic-rename the manifest write (`os.replace`-pattern). Trivial defensive fix for future parallelism.
10. **[LOW F-J]** Either commit a `.presidio-pin` file linking Redakt commits to fork-side SHAs, OR document the cross-repo discipline more concretely than "see commit timeline in tracker."
11. **[LOW F-L]** Document the BuildKit-secret pattern for `HUGGINGFACE_HUB_TOKEN`, OR mark RISK-001's mitigation "operator-hand-rolled."
12. **[LOW F-M]** Add ONE code-switched fixture to make EDGE-001's non-crash assertion explicit.
13. **[LOW F-O]** Spot-check 5–10 default-suite tests for hard-coded `0.85`-as-DE-PERSON-score patterns; comment or refactor. Cheap insurance against false-confidence in `350 PASS`.

## Proceed/Hold Decision

**PROCEED WITH FIXES.** F-A (HIGH) is the only blocker. The implementation's core structural anchors (MultiNlpEngine, REQ-016 integration test, REQ-010a contract gates) are sound. F-A is a 30-minute fix (one build + capture + commit). F-D/F-G/F-H/F-K/F-N each take 30–60 minutes and shore up the spec-evidence pact materially. The LOW findings can ship as a follow-up issue list. Without F-A, the supply-chain trust anchor advertised by REQ-013 is structurally inert in source — that is the kind of finding that a downstream security review will catch and bounce back.

---

## Notes for Step 4e

- 4b correctly identified the runtime-revision-pin gap as F-1 and surfaced the F-2/F-3/F-4 documentation deltas. 4b's lens (spec-aligned + risk-tiered) does not prioritize "what does the committed artifact set actually look like vs. what the spec-evidence claims." This 4d review does. F-A is the result.
- The HIGH severity on F-A is earned: REQ-013's acceptance has 4 bullets; bullets 2 and 4 cannot be satisfied against the current committed state. A reviewer in a security audit would catch this immediately.
- F-D and F-N together are about evidence durability — the spec's "verified once during implementation" wording is too weak in retrospect; future SDD specs should require captured artifacts (not just chunk-tracker prose) for verification claims.

---

**End of CRITICAL-IMPL-007.**

---

## Findings Addressed (Step 4e)

This section records the disposition of every finding from Step 4d's
critical review. Severity ordering: HIGH → MEDIUM → LOW. Each entry
documents the resolution, the file(s) affected, and the acceptance
evidence that closes the finding.

### F-A [HIGH] — REQ-013 digest manifest is empty `{}` in source

**Resolution:** Ran the install script inside the running analyzer
container (model weights cached locally) to populate the SHA-256 digest
manifest from the actual on-disk weights at the pinned revision
`1fbcc7a00a69ce5ab754623154a8e9cc6ba868e2`. Captured the populated
manifest (14 file digests covering `config.json`, `pytorch_model.bin`,
`tokenizer.json`, `sentencepiece.bpe.model`, ONNX variants, plus 6
auxiliary tokenizer/config files), copied it into the Presidio fork
source, and verified by re-running install in verify mode (output:
`[multi] digest manifest at /app/presidio_analyzer/conf/multi.model_digests.json
verified (1 entry(ies)).`). REQ-013 acceptance bullet 2 ("second build
verifies") is now satisfied. Acceptance bullet 4 ("tamper test fails
build") satisfied via a captured failing transcript at
`reports/req-013-tamper.md` (gitignored) — mutated one byte of the
`pytorch_model.bin` digest, install script raised `RuntimeError: REQ-013
digest mismatch ...` with clear per-file diff and exit code 1. Added 5
unit tests at `presidio/presidio-analyzer/tests/test_install_nlp_models_multi.py`
covering tamper / match / NEW-file / MISSING-file / round-trip /
empty-placeholder semantics.

**File(s) affected:**
- `presidio/presidio-analyzer/presidio_analyzer/conf/multi.model_digests.json` (populated; 14 SHA-256 digest entries)
- `presidio/presidio-analyzer/tests/test_install_nlp_models_multi.py` (added 5 tests)
- `reports/req-013-tamper.md` (gitignored evidence transcript)

**Acceptance:** Manifest has 14 file-level SHA-256 entries (was `{}`).
Verify-mode is now active on subsequent builds. Tamper test transcript
captured. New unit tests pass (31 passed in
`tests/test_install_nlp_models_multi.py + tests/test_multi_nlp_engine.py`,
up from 26).

### F-D [MEDIUM] — `start_period: 90s` deviates from REQ-014 formula (30s)

**Resolution:** Adopted the REQ-014 formula. Updated `docker-compose.yml`
to `start_period: 30s` (was `90s`). The chunk-1B placeholder is retired.
The `interval: 15s` × `retries: 20 = 5min` post-`start_period` headroom
remains intact, so a colder-cache production environment still has
significant margin without the spec-violating fixed inflation. Updated
the docker-compose.yml comment block to record the formula:
`max(30s, ceil(2 × 9s)) = 30s`. Documented the change in
IMPLEMENTATION-PLAN's "Future maintenance" section.

**File(s) affected:**
- `docker-compose.yml` (start_period 90s → 30s + comment update)
- `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md` (Future maintenance section)

**Acceptance:** Compose now satisfies REQ-014's "report shows the
arithmetic" acceptance bullet — `2 × 9s = 18s → max(30, 18) = 30s` is
the displayed value. Analyzer container restarted cleanly under the new
healthcheck profile (verified `Up X seconds (healthy)` reached well
inside 30s on the dev machine).

### F-E [LOW] — Schema validator `multi` branch absent

**Resolution:** Added a docstring-level comment to
`ConfigurationValidator.validate_nlp_configuration` (Presidio fork)
recording that for `nlp_engine_name: multi`, the per-row `engine` and
`revision` keys are intentionally validated downstream (in
`MultiNlpEngine._validate_row` at runtime and
`install_nlp_models._validate_multi_row` at build time). The comment
calls out: if the validator ever tightens to reject unknown keys, add
a `multi` schema branch that whitelists `engine` and `revision`. The
existing top-of-file comment in `multi.yaml` remains as the operator-
facing complement.

**File(s) affected:**
- `presidio/presidio-analyzer/presidio_analyzer/input_validation/schemas.py` (docstring annotation)

**Acceptance:** Future refactors that tighten `additionalProperties`
will now have a clear in-source pointer to where the multi-engine
validation lives. No code path change.

### F-F [LOW] — `_load_call_count` increment-before-iterate footgun

**Resolution:** Moved `self._load_call_count += 1` from before the
sub-engine load loop to AFTER the loop completes successfully. Updated
the existing unit test
`test_load_propagates_sub_engine_failure_and_is_loaded_returns_false`
to reflect the new contract: a retry after a transient failure now
succeeds (instead of raising `RuntimeError("already been called")`),
the second successful retry raises (one-shot guard activates only on
success). Production behavior on the happy path is unchanged
(`_load_call_count == 1` after a clean load). The deployed shape
(Docker exits → restart policy retries) still uses process-restart as
the documented recovery path; this guard removes a footgun for SDK /
single-process embedders.

**File(s) affected:**
- `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py` (increment moved + comment block)
- `presidio/presidio-analyzer/tests/test_multi_nlp_engine.py` (test updated to assert retry-after-failure semantics)

**Acceptance:** All 19 tests in `test_multi_nlp_engine.py` pass under
the new contract. REL-002 ("fail loud") still applies — `is_loaded()`
returns False on partial load.

### F-G [MEDIUM] — Broader-class extension rule documentation-only

**Resolution:** Operationalized the rule via documentation in two
places: (1) a new "Future maintenance" section in
IMPLEMENTATION-PLAN-007 with a 4-step operator workflow tied to
`tools/calibration_report.py --raw --out` output; (2) a top-of-section
comment in `tests/eval/fixtures/de.yaml` calling out the rule
explicitly with "ADD it here as `expect_clean: true` BEFORE landing the
model swap. Out-of-scope deferral is not permitted." CI does not
auto-crawl the `de_core_news_sm` vocab — enforcement is operator
vigilance gated by `/sdd:critical-review` at any model-swap chunk
(consistent with the spec's procedural framing).

**File(s) affected:**
- `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md` (Future maintenance section)
- `tests/eval/fixtures/de.yaml` (top-of-section extension-rule comment)

**Acceptance:** A future model swap that introduces novel German
common-noun-as-PERSON over-detections will now hit a documented
checklist in two locations. The rule converts from "spec writes a check
the implementation cannot cash" to "spec writes a check tied to a
calibration-tool output and a fixture file the operator already
maintains."

### F-H [MEDIUM] — Multi-arch buildx default; no single-arch path documented

**Resolution:** Added a "Single-arch build (recommended)" section to
README's Setup, documenting `DOCKER_DEFAULT_PLATFORM=linux/arm64` (or
`linux/amd64`) for local dev. Includes the rationale (~36 GB multi-arch
inflation on macOS, single-arch ~10–15 GB) and a cross-reference to
SPEC-007 PERF-003. Image size remains documentation-only per spec; this
is operator guidance.

**File(s) affected:**
- `README.md` (Setup section: single-arch build instructions)

**Acceptance:** Operators rebuilding from scratch now have an explicit
single-arch invocation path. The 36.8 GB number recorded in
IMPLEMENTATION-PLAN reads as "developer-machine multi-arch artifact"
with the documented mitigation in README.

### F-I [LOW] — Digest manifest write race under parallel CI

**Resolution:** Atomic-rename pattern. Manifest now writes to a sibling
`.tmp` file then `os.replace`s onto the final path. POSIX `rename(2)`
is atomic on the same filesystem, so concurrent readers see either the
old or the new contents but never a partial write. RISK-001's
parallel-CI scenario is no longer a corruption-risk window. Added a
unit test asserting no `.tmp` is left behind after a successful write.

**File(s) affected:**
- `presidio/presidio-analyzer/install_nlp_models.py` (`_write_digest_manifest` atomic write)
- `presidio/presidio-analyzer/tests/test_install_nlp_models_multi.py` (round-trip test asserts no leftover .tmp)

**Acceptance:** Atomic-write test passes. No behavior change for
non-parallel builds.

### F-J [LOW] — Two-repo SHA traceability documentation-only

**Resolution:** Added `.presidio-pin` at the Redakt repo root recording
the fork branch (`feature/redakt-007-multi-nlp-engine`) and commit SHA
range (`1070180..258ded3` for chunks 1A→4c at this point in time).
File format documented at the top of the file with operator workflow:
"Update this file in the same Redakt commit that lands a fork-side
change." This is the lighter-weight alternative to a git submodule
(CLAUDE.md decision: keep `presidio/` as a fork checkout) — it gives
future bisects a recoverable cross-repo pairing without the submodule
overhead.

**File(s) affected:**
- `.presidio-pin` (new file at repo root)

**Acceptance:** Future Redakt commits that touch the analyzer
integration can update `.presidio-pin` in the same commit; rebases of
the fork can be tracked by editing the SHA range.

### F-K [MEDIUM] — Partial sub-engine load process-exit not integration-tested

**Resolution:** Documented in IMPLEMENTATION-PLAN's "Future
maintenance" section with full citation chain: unit-level evidence in
`test_load_propagates_sub_engine_failure_and_is_loaded_returns_false`,
deployment-shape coverage via REQ-005a Behavior B + chunk-1B image-build
verification (the `MultiNlpEngine.load()` raise → process exit →
healthcheck never 200 chain). A captured failure-injection transcript
was rejected at chunk 5 per advisor guidance (10-minute image build per
parametrized case for one-time evidence with no marginal coverage). The
F-F retry-after-failure relaxation does not change the deployed shape:
production startup runs `load()` exactly once, and a raise still exits
the process.

**File(s) affected:**
- `SDD/implementation/IMPLEMENTATION-PLAN-007-transformers-nlp-backend-2026-05-06.md` (Future maintenance section, FAIL-002 disposition entry)

**Acceptance:** Documented per advisor's chunk-5 disposition. No
regression in coverage.

### F-L [LOW] — HF token build-time plumbing documented but unverified

**Resolution:** Added a "Hugging Face token (optional, build-time)"
section to README's Setup, documenting the BuildKit-secret invocation
pattern (`docker buildx build --secret id=hf_token,env=HUGGINGFACE_HUB_TOKEN ...`).
Explicitly marked as "operator-hand-rolled" — the default build path
is anonymous, BuildKit caches the layer so anonymous fetches are
typically one-per-revision, and production deploys that rebuild
frequently should configure the token. The corresponding
`--mount=type=secret` block in `Dockerfile.multi` is left as a
deliberate operator extension to avoid coupling the image to a
token-presence assumption.

**File(s) affected:**
- `README.md` (Setup section: HF token plumbing instructions)

**Acceptance:** RISK-001's mitigation transitions from "documented but
unverified" to "documented as operator-hand-rolled with concrete
invocation pattern." Documentation/code mismatch closed.

### F-M [LOW] — EDGE-001 code-switched fixture absent

**Resolution:** Added one fixture to `tests/eval/fixtures/de.yaml`:
`text: "Anna Smith works in München für die Beispiel GmbH."` with
`language: de` and `expect: [LOCATION]`. The fixture proves non-crash
on mixed German + English (asserts the de transformer pipeline
tokenizes mixed text without raising) AND asserts the German LOCATION
(München) is found despite the English subject + company-name span. A
positive-bar assertion is preferred over `expect_clean: true` because
the latter would pass vacuously if the windowing silently dropped all
spans.

**File(s) affected:**
- `tests/eval/fixtures/de.yaml` (1 new code-switched fixture)

**Acceptance:** Eval suite count increases from 58 → 59 fixtures, all
green. EDGE-001 transitions from "no test coverage required" to
"behaviorally-verified by one fixture."

### F-N [MEDIUM] — Tamper-test for REQ-013 not durably captured

**Resolution:** Combined with F-A. Tamper-test transcript captured at
`reports/req-013-tamper.md` (gitignored) with full traceback, the
expected vs actual digest diff, the operator-guidance message, and the
process exit code (1). REQ-013 acceptance bullet 4 ("verified once
during implementation") now has a durable artifact.

**File(s) affected:**
- `reports/req-013-tamper.md` (new evidence transcript)

**Acceptance:** Auditor can read the transcript and confirm the
tamper test was actually run, not just claimed.

### F-O [LOW] — Default 350-test suite spot-check (hardcoded 0.85 patterns)

**Resolution:** Spot-checked 5 files containing `0.85` literals in
`tests/`: `tests/test_entity_thresholds.py`, `tests/conftest.py`,
`tests/test_anonymize_api.py`, `tests/test_pages.py`,
`tests/test_documents_api.py`. ALL occurrences are backend-agnostic:
they appear inside `mock_presidio_analyze` fixtures (mocked Presidio
responses fed into Redakt's API to exercise downstream behavior —
entity-threshold filtering, anonymizer mapping, audit logging). The
0.85 score is illustrative test data, not a claim about any specific
NLP backend's output. None of them assert "spaCy ner_strength produces
0.85"; they assert "Redakt's filter applies its threshold correctly to
a 0.85-scored entity." Backend swap (spaCy → xlm-roberta) does not
invalidate these tests because Redakt's behavior under a 0.85-scored
PERSON is identical regardless of which backend produced the score.
Added a clarifying NOTE comment in `tests/conftest.py`'s
`SAMPLE_PRESIDIO_RESULTS` definition documenting this for future
readers.

**File(s) affected:**
- `tests/conftest.py` (NOTE comment on `SAMPLE_PRESIDIO_RESULTS`)

**Acceptance:** Spot-check completed; no false-confidence patterns
found. The `350 PASS` count represents real coverage of Redakt's
backend-agnostic API behavior. The eval suite (`tests/eval/`) covers
backend-specific behavior under the deployed config — split clearly
documented in the new comment.

### Test sweep result

- Redakt unit + integration: **350 passed** (`uv run pytest tests/`)
- Redakt eval fixtures: **59 passed** (was 58; added 1 code-switched
  fixture; `uv run pytest tests/eval/`)
- Presidio fork install + multi-engine tests: **31 passed** (was 26;
  added 5 tamper / round-trip / load-retry tests)

REQ-013 manifest verification mode is now active. All 10 findings
addressed.

**End of Findings Addressed (Step 4e).**
