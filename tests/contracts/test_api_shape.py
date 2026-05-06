"""REQ-010a — API-shape regression test (byte-identical envelope + headers).

This test asserts byte-identical envelopes for representative `200`-status
requests on each of the three Redakt API endpoints
(`/api/detect`, `/api/anonymize`, `/api/deanonymize`), distinct from the
`tests/eval/` fixtures and distinct from the OpenAPI schema diff
(`test_openapi_diff.py`).

What's checked:
  - Status code is 200.
  - `Content-Type` response header equals `application/json`.
  - No new `X-Redakt-*` headers exist (none today; should stay none).
  - The set of response headers (excluding volatile `date`, `server`,
    `content-length`) matches the baseline exactly.
  - The set of top-level JSON keys matches the baseline exactly.
  - Each per-entity object in `details` has exactly the baseline keys.
  - Each placeholder mapping is a `dict[str, str]` (content may differ — only
    shape is checked, per REQ-010a item 2).

What's intentionally NOT checked:
  - Numeric `score` values (transformer runs may drift slightly).
  - Names inside `mappings` (PII content may differ across model upgrades).

Failure mode: a precise field-level diff identifies the offending key/header
(per REQ-010a item 4). Tamper test verified once during chunk-3
implementation: a stray `X-Test-Stray` header added to
`SecurityHeadersMiddleware` causes the header-set assertion to fail with the
extra header named in the diff.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


SNAPSHOT_DIR = Path(__file__).parent

# Volatile headers we don't gate on — they change per-request by design.
VOLATILE_HEADERS = frozenset({"date", "server", "content-length"})


# Fixed inputs, captured alongside snapshot baselines. Keep these short and
# unambiguous so any drift is signal, not noise.
DETECT_INPUTS = {
    "en": {
        "body": {"text": "John Smith works at Acme Corp.", "language": "en"},
        "snapshot": "snapshot_detect_en.json",
    },
    "de": {
        "body": {"text": "Anna Schmidt arbeitet bei der Beispiel AG.", "language": "de"},
        "snapshot": "snapshot_detect_de.json",
    },
}

ANONYMIZE_INPUTS = {
    "en": {
        "body": {"text": "John Smith works at Acme Corp.", "language": "en"},
        "snapshot": "snapshot_anonymize_en.json",
    },
    "de": {
        "body": {"text": "Anna Schmidt arbeitet bei der Beispiel AG.", "language": "de"},
        "snapshot": "snapshot_anonymize_de.json",
    },
}

DEANONYMIZE_INPUT = {
    "body": {
        "text": "<PERSON_1> works at <ORG_1>.",
        "mappings": {"<PERSON_1>": "John Smith", "<ORG_1>": "Acme Corp"},
    },
    "snapshot": "snapshot_deanonymize.json",
}


def _load_snapshot(name: str) -> dict:
    path = SNAPSHOT_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_headers(response: httpx.Response) -> dict[str, str]:
    """Return response headers with volatile keys stripped, lowercased."""
    return {
        k.lower(): v for k, v in response.headers.items() if k.lower() not in VOLATILE_HEADERS
    }


def _assert_no_xredakt_headers(headers: dict[str, str]) -> None:
    """REQ-010a item 3: no `X-Redakt-*` headers expected to be added."""
    extra = sorted(k for k in headers if k.startswith("x-redakt-"))
    assert not extra, (
        f"Unexpected X-Redakt-* response header(s) detected: {extra}. "
        "Per REQ-010a item 3, no X-Redakt-* headers exist today and adding "
        "any breaks the API contract."
    )


def _assert_header_set_matches(
    response: httpx.Response, baseline_keys: set[str], endpoint: str
) -> None:
    live = set(_stable_headers(response).keys())
    missing = baseline_keys - live
    extra = live - baseline_keys
    assert not missing and not extra, (
        f"[{endpoint}] response header set drifted from contract.\n"
        f"  missing (present in baseline, absent live): {sorted(missing)}\n"
        f"  extra   (absent in baseline, present live): {sorted(extra)}"
    )


def _assert_top_level_keys_match(
    body: dict, baseline_keys: set[str], endpoint: str
) -> None:
    live = set(body.keys())
    missing = baseline_keys - live
    extra = live - baseline_keys
    assert not missing and not extra, (
        f"[{endpoint}] top-level JSON keys drifted from contract.\n"
        f"  missing (present in baseline, absent live): {sorted(missing)}\n"
        f"  extra   (absent in baseline, present live): {sorted(extra)}"
    )


# Baseline header set — captured once for all three JSON endpoints. They share
# the same FastAPI app + SecurityHeadersMiddleware, so the header set is
# uniform.
BASELINE_HEADER_KEYS = {
    "content-type",
    "content-security-policy",
    "x-content-type-options",
}


@pytest.mark.parametrize("lang", ["en", "de"])
def test_detect_envelope_shape(client: httpx.Client, lang: str) -> None:
    spec = DETECT_INPUTS[lang]
    snapshot = _load_snapshot(spec["snapshot"])

    response = client.post("/api/detect", params={"verbose": "true"}, json=spec["body"])

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.headers.get("content-type") == "application/json", (
        f"Content-Type drift: got {response.headers.get('content-type')!r}"
    )
    _assert_no_xredakt_headers(_stable_headers(response))
    _assert_header_set_matches(response, BASELINE_HEADER_KEYS, f"detect[{lang}]")

    body = response.json()
    _assert_top_level_keys_match(body, set(snapshot.keys()), f"detect[{lang}]")

    # Per-entity detail object shape (verbose mode emits `details`).
    assert isinstance(body["details"], list), "details must be a list"
    if snapshot["details"]:
        baseline_detail_keys = set(snapshot["details"][0].keys())
        for i, item in enumerate(body["details"]):
            assert isinstance(item, dict), f"details[{i}] not a dict"
            actual = set(item.keys())
            assert actual == baseline_detail_keys, (
                f"[detect[{lang}]] details[{i}] keys drifted.\n"
                f"  expected: {sorted(baseline_detail_keys)}\n"
                f"  got:      {sorted(actual)}"
            )
            assert isinstance(item["entity_type"], str)
            assert isinstance(item["start"], int)
            assert isinstance(item["end"], int)
            assert isinstance(item["score"], (int, float))

    assert isinstance(body["entities_found"], list)
    assert isinstance(body["entity_count"], int)
    assert isinstance(body["has_pii"], bool)
    assert isinstance(body["language_detected"], str)
    assert body["language_confidence"] is None or isinstance(
        body["language_confidence"], (int, float)
    )


@pytest.mark.parametrize("lang", ["en", "de"])
def test_anonymize_envelope_shape(client: httpx.Client, lang: str) -> None:
    spec = ANONYMIZE_INPUTS[lang]
    snapshot = _load_snapshot(spec["snapshot"])

    response = client.post("/api/anonymize", json=spec["body"])

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.headers.get("content-type") == "application/json", (
        f"Content-Type drift: got {response.headers.get('content-type')!r}"
    )
    _assert_no_xredakt_headers(_stable_headers(response))
    _assert_header_set_matches(response, BASELINE_HEADER_KEYS, f"anonymize[{lang}]")

    body = response.json()
    _assert_top_level_keys_match(body, set(snapshot.keys()), f"anonymize[{lang}]")

    assert isinstance(body["anonymized_text"], str)
    # REQ-010a item 2: mappings CONTENT may differ; SHAPE (dict[str, str]) must
    # be identical.
    assert isinstance(body["mappings"], dict), "mappings must be a dict"
    for k, v in body["mappings"].items():
        assert isinstance(k, str), f"mappings key not str: {k!r}"
        assert isinstance(v, str), f"mappings value not str for {k!r}: {v!r}"
    assert isinstance(body["language_detected"], str)
    assert body["language_confidence"] is None or isinstance(
        body["language_confidence"], (int, float)
    )


def test_deanonymize_envelope_shape(client: httpx.Client) -> None:
    spec = DEANONYMIZE_INPUT
    snapshot = _load_snapshot(spec["snapshot"])

    response = client.post("/api/deanonymize", json=spec["body"])

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.headers.get("content-type") == "application/json", (
        f"Content-Type drift: got {response.headers.get('content-type')!r}"
    )
    _assert_no_xredakt_headers(_stable_headers(response))
    _assert_header_set_matches(response, BASELINE_HEADER_KEYS, "deanonymize")

    body = response.json()
    _assert_top_level_keys_match(body, set(snapshot.keys()), "deanonymize")

    # Deanonymize is deterministic for fixed inputs, so we CAN assert
    # byte-identical content here (no model in the loop).
    assert body == snapshot, (
        "Deanonymize response drifted from baseline. "
        "This endpoint is purely string-substitution, so any divergence is a "
        "real contract change.\n"
        f"  expected: {snapshot}\n"
        f"  got:      {body}"
    )
