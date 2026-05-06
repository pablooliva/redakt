"""REQ-010 — OpenAPI schema diff gate.

Asserts that the live Redakt API's `/openapi.json` matches the committed
baseline byte-for-byte (after deterministic pretty-printing). Catches
inadvertent schema changes — added/removed routes, changed request/response
shapes, type drift in components.

Allowed changes are made by updating the baseline in the same PR; any change
without a baseline update fails this gate.

Counterpart of REQ-010a (`test_api_shape.py`), which gates response envelopes
and headers — they cover orthogonal contract surfaces and BOTH must pass to
merge.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


BASELINE_PATH = Path(__file__).parent / "openapi-baseline.json"


def _normalize(spec: dict) -> str:
    """Render a spec deterministically — sort keys, indent=2, no trailing
    whitespace. Same recipe used to capture the baseline so the diff is
    byte-stable."""
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def test_baseline_exists() -> None:
    assert BASELINE_PATH.exists(), (
        f"OpenAPI baseline missing at {BASELINE_PATH}. "
        "Re-capture with: "
        "`curl -s http://localhost:8000/openapi.json | python3 -c "
        "\"import json,sys; print(json.dumps(json.load(sys.stdin), indent=2, sort_keys=True))\" "
        f"> {BASELINE_PATH}`"
    )


def test_openapi_matches_baseline(client: httpx.Client) -> None:
    """Live `/openapi.json` matches the committed baseline.

    On failure: the assertion message includes a unified diff identifying the
    offending paths/components — review and either revert the schema change or
    update the baseline deliberately in the same PR.
    """
    response = client.get("/openapi.json")
    assert response.status_code == 200

    live_spec = response.json()
    baseline_spec = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    if live_spec == baseline_spec:
        return

    # Build a precise diff to guide the reviewer.
    import difflib

    live_text = _normalize(live_spec).splitlines(keepends=True)
    baseline_text = _normalize(baseline_spec).splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            baseline_text,
            live_text,
            fromfile="openapi-baseline.json",
            tofile="/openapi.json (live)",
            n=3,
        )
    )
    pytest.fail(
        "OpenAPI schema drifted from baseline.\n"
        "If this change is intentional, regenerate the baseline:\n"
        f"  curl -s http://localhost:8000/openapi.json | "
        f"python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin), indent=2, sort_keys=True))' "
        f"> {BASELINE_PATH}\n\n"
        f"Diff:\n{diff}"
    )
