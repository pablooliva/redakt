"""REQ-011 — Recognizer registry floor preservation.

Asserts that every currently-enabled `country recognizer` from the Presidio-
fork commits 71206f6 and d76d884 stays enabled, in current relative order,
with current pattern scoring. New recognizers MAY be added; removals,
disables, reorderings, and rescorings of the floor set fail this gate.

The baseline is captured once from a live `presidio-analyzer` container's
`AnalyzerEngineProvider().create_engine().registry.get_recognizers(...)` and
committed alongside this test as `recognizers-baseline.json`. The test
re-introspects the live registry and compares.

What's checked per language (en, de):
  1. Every baseline recognizer name is still present.
  2. Each recognizer's `supported_entities` set is preserved.
  3. Each recognizer's pattern set (name + score) is preserved (a missing
     pattern or a rescored pattern fails).
  4. Relative order of every pair of baseline recognizers is preserved
     (additions are tolerated; reorderings within the floor set are not).

Failure mode: precise per-recognizer / per-pattern message identifying the
offending change.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest


BASELINE_PATH = Path(__file__).parent / "recognizers-baseline.json"

# The analyzer container exposes its API only on its internal docker network
# (port 5001 inside the container). The /recognizers endpoint returns a list
# of recognizer names but NOT pattern scores — so we introspect the engine
# directly via `docker exec`. This is the same recipe used to capture the
# baseline.
ANALYZER_CONTAINER = os.environ.get(
    "REDAKT_ANALYZER_CONTAINER", "redakt-presidio-analyzer-1"
)

# Exec'd inside the container — uses the analyzer's already-loaded Python env.
INTROSPECT_SCRIPT = """
import json
from presidio_analyzer import AnalyzerEngineProvider
provider = AnalyzerEngineProvider()
engine = provider.create_engine()
def serialize(lang):
    recs = engine.registry.get_recognizers(language=lang, all_fields=True)
    out = []
    for r in recs:
        patterns = []
        for p in getattr(r, 'patterns', []) or []:
            patterns.append({'name': p.name, 'score': p.score})
        patterns.sort(key=lambda x: (x['name'], x['score']))
        out.append({
            'name': r.name,
            'supported_language': r.supported_language,
            'supported_entities': sorted(list(r.supported_entities)),
            'patterns': patterns,
        })
    return out
print(json.dumps({'en': serialize('en'), 'de': serialize('de')}, default=str))
"""


def _live_registry() -> dict[str, list[dict[str, Any]]]:
    """Introspect the live analyzer's recognizer registry via docker exec."""
    try:
        result = subprocess.run(
            ["docker", "exec", ANALYZER_CONTAINER, "python3", "-c", INTROSPECT_SCRIPT],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip(
            "docker CLI not available; cannot introspect analyzer container "
            "for REQ-011 floor check."
        )
    if result.returncode != 0:
        pytest.fail(
            f"Failed to introspect analyzer container {ANALYZER_CONTAINER!r}.\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}"
        )
    # The container's import path emits a UserWarning on stderr (NLP recognizer
    # auto-add notice); stdout is the clean JSON payload.
    return json.loads(result.stdout)


def _by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in rows}


@pytest.fixture(scope="module")
def baseline() -> dict[str, list[dict[str, Any]]]:
    assert BASELINE_PATH.exists(), (
        f"Recognizer baseline missing at {BASELINE_PATH}. "
        "Re-capture by exec'ing the analyzer's Python env (see INTROSPECT_SCRIPT)."
    )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live() -> dict[str, list[dict[str, Any]]]:
    return _live_registry()


@pytest.mark.parametrize("language", ["en", "de"])
def test_baseline_recognizers_still_enabled(
    baseline: dict, live: dict, language: str
) -> None:
    """Every baseline recognizer name is still present in the live registry."""
    baseline_names = {r["name"] for r in baseline[language]}
    live_names = {r["name"] for r in live[language]}
    missing = sorted(baseline_names - live_names)
    assert not missing, (
        f"[{language}] Baseline recognizers no longer enabled: {missing}. "
        "REQ-011 forbids removals/disables of the floor set."
    )


@pytest.mark.parametrize("language", ["en", "de"])
def test_supported_entities_preserved(
    baseline: dict, live: dict, language: str
) -> None:
    """Each baseline recognizer's supported_entities set is preserved.

    Additions to a recognizer's `supported_entities` are tolerated;
    removals fail.
    """
    live_idx = _by_name(live[language])
    failures: list[str] = []
    for b in baseline[language]:
        name = b["name"]
        if name not in live_idx:
            continue  # caught by the previous test
        baseline_entities = set(b["supported_entities"])
        live_entities = set(live_idx[name]["supported_entities"])
        missing = baseline_entities - live_entities
        if missing:
            failures.append(
                f"  {name}: lost entities {sorted(missing)} "
                f"(was {sorted(baseline_entities)}, is {sorted(live_entities)})"
            )
    assert not failures, (
        f"[{language}] Recognizer supported_entities regressed:\n"
        + "\n".join(failures)
    )


@pytest.mark.parametrize("language", ["en", "de"])
def test_pattern_scoring_preserved(
    baseline: dict, live: dict, language: str
) -> None:
    """Each baseline recognizer's pattern (name, score) tuples are preserved.

    Missing patterns fail. Score drift on a baseline pattern fails.
    Adding new patterns to a recognizer is tolerated (new detections are not a
    floor regression).
    """
    live_idx = _by_name(live[language])
    failures: list[str] = []
    for b in baseline[language]:
        name = b["name"]
        if name not in live_idx:
            continue
        baseline_patterns = {(p["name"], p["score"]) for p in b["patterns"]}
        live_patterns = {(p["name"], p["score"]) for p in live_idx[name]["patterns"]}
        # Patterns missing entirely or rescored both surface here.
        for pname, pscore in baseline_patterns:
            live_scores_for_name = {
                ls for (ln, ls) in live_patterns if ln == pname
            }
            if not live_scores_for_name:
                failures.append(
                    f"  {name}: pattern {pname!r} (score {pscore}) is missing"
                )
            elif pscore not in live_scores_for_name:
                failures.append(
                    f"  {name}: pattern {pname!r} rescored "
                    f"(was {pscore}, is {sorted(live_scores_for_name)})"
                )
    assert not failures, (
        f"[{language}] Recognizer pattern scoring regressed:\n"
        + "\n".join(failures)
    )


@pytest.mark.parametrize("language", ["en", "de"])
def test_relative_order_preserved(
    baseline: dict, live: dict, language: str
) -> None:
    """Relative order of every pair of baseline recognizers is preserved.

    REQ-011 allows additions (which by definition shift indices) but forbids
    reorderings within the floor set. So we check pairwise relative order:
    for every (a, b) in the baseline where a comes before b, assert
    `live.index(a) < live.index(b)`.
    """
    live_order = [r["name"] for r in live[language]]
    baseline_names = [r["name"] for r in baseline[language] if r["name"] in live_order]
    live_indices = {name: live_order.index(name) for name in baseline_names}

    failures: list[str] = []
    for i, a in enumerate(baseline_names):
        for b in baseline_names[i + 1 :]:
            if live_indices[a] >= live_indices[b]:
                failures.append(
                    f"  expected {a!r} before {b!r}, "
                    f"got indices {live_indices[a]} >= {live_indices[b]}"
                )
    assert not failures, (
        f"[{language}] Recognizer floor relative-order regressed:\n"
        + "\n".join(failures)
    )
