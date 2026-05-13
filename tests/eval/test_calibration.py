"""End-to-end calibration tests.

Each phrase in tests/eval/fixtures/*.yaml is parametrized into a separate test.
The test calls Redakt's /api/detect?verbose=true and asserts the entities the
API returns match the phrase's `expect` (or are empty for `expect_clean: true`).

Because the request goes through the real API path, this exercises the
configured `entity_score_thresholds`, the global `score_threshold`, the
instance allow list, and any other post-filter logic — exactly what an
operator or AI agent would observe.

Run with: uv run pytest tests/eval/

A failure here means either (a) the deployed thresholds need adjusting in
config.py / via REDAKT_ENTITY_SCORE_THRESHOLDS, or (b) the fixture phrase is
unrealistic and should be revised.
"""

from __future__ import annotations

import httpx
import pytest

from tests.eval._loader import Phrase, load_all_phrases

PHRASES: list[Phrase] = load_all_phrases()


def _detect(http: httpx.Client, url: str, phrase: Phrase) -> dict:
    response = http.post(
        f"{url}/api/detect?verbose=true",
        json=phrase.build_request_body(),
    )
    response.raise_for_status()
    return response.json()


@pytest.mark.parametrize("phrase", PHRASES, ids=[p.label for p in PHRASES])
def test_phrase(phrase: Phrase, http: httpx.Client, redakt_url: str) -> None:
    body = _detect(http, redakt_url, phrase)
    details = body.get("details", [])
    found = sorted({d["entity_type"] for d in details})

    if phrase.expect_clean:
        assert found == [], (
            f"Expected no PII but got {found}.\n"
            f"Details: {[(d['entity_type'], d['score']) for d in details]}\n"
            f"Notes: {phrase.notes or '—'}"
        )
        return

    expected = sorted(set(phrase.expect))
    missing = [e for e in expected if e not in found]
    assert not missing, (
        f"Missing expected entities {missing} (got {found}).\n"
        f"Details: {[(d['entity_type'], d['score']) for d in details]}\n"
        f"Notes: {phrase.notes or '—'}"
    )
