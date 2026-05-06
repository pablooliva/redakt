"""REQ-016 — End-to-end ``language: auto`` routing test (positive coverage).

Asserts that when the request specifies ``language: auto`` the
`language auto-detect path` (lingua-py) correctly resolves the request
language AND the analyzer's ``MultiNlpEngine`` correctly dispatches that
resolved language to the right sub-engine.

This is the structural mitigation for MODULE-001's HIGH risk tier (silent
wrong-engine routing — see SPEC-007 §MODULE-001 Risk paragraph). A
hypothetical engine-swap bug (e.g. a one-character flip in
``MultiNlpEngine._sub_engines`` keys) would cause a deterministic failure
here with a meaningful diff, because the EN and DE sub-engines produce
distinctive entity-score fingerprints:

  - **EN engine** (spaCy ``en_core_web_lg``): PERSON returns at exactly
    0.85 (the spaCy ``ner_strength`` constant), and English text never
    yields the >0.99 transformer-style scores.
  - **DE engine** (xlm-roberta-large-finetuned-conll03-german): PERSON /
    LOCATION return at >0.99 (raw transformer probability). The engine
    additionally produces LOCATION on `Berlin` / `München` — the EN
    spaCy path either does not flag those at all or scores them below
    Redakt's `LOCATION` floor (0.90 default).

The test relies on the ``language_detected`` field in the verbose response
(populated by ``src/redakt/services/detect.py``'s `language auto-detect
path`) as the lingua-py routing signal, and on score-fingerprint
assertions to confirm the analyzer-side dispatch is correct.

Counterpart documentation: `SDD/requirements/SPEC-007-transformers-nlp-backend.md` REQ-016.

Live-stack gating: this test is excluded from the default
`uv run pytest tests/` run (see pyproject.toml `addopts`); invoke via
`uv run pytest tests/integration/`.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest


# Score fingerprint thresholds — derived from chunk-1B/chunk-2 calibration.
# spaCy `en_core_web_lg`'s SpacyRecognizer emits PERSON at exactly 0.85
# (`ner_strength` constant); xlm-roberta-large-finetuned-conll03-german emits
# PERSON / LOCATION at raw probability >0.99 for high-confidence hits.
SPACY_PERSON_SCORE = 0.85
TRANSFORMER_FLOOR = 0.95  # well above 0.85, well below the typical >0.99 actual


def _detect(client: httpx.Client, text: str, language: str = "auto") -> dict[str, Any]:
    response = client.post(
        "/api/detect",
        params={"verbose": "true"},
        json={"text": text, "language": language},
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    return response.json()


def _scores_by_entity(body: dict) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for d in body["details"]:
        out.setdefault(d["entity_type"], []).append(d["score"])
    return out


def test_auto_routes_german_text_to_de_engine(client: httpx.Client) -> None:
    """Unambiguously German text + ``language: auto`` → DE sub-engine.

    Uses the same DE LOCATION held-out-positive sentence the calibration
    suite exercises (REQ-009b). lingua-py picks `de`; ``MultiNlpEngine``
    must dispatch to the German transformer.

    Routing signals checked:
      1. ``language_detected == "de"`` — lingua-py resolved to German.
      2. LOCATION present in entities found.
      3. LOCATION score > 0.95 — transformer fingerprint (EN spaCy never
         scores LOCATION at this confidence on `Berlin`).

    Failure under an engine-swap bug: if the request silently routes to
    the EN spaCy engine, LOCATION either won't appear or will score
    around / below 0.85 (and Redakt's per-entity LOCATION floor of 0.90
    drops it entirely) — assertion 2 or 3 fails with a clear diff.
    """
    text = "Sie wohnt in Berlin und arbeitet in München."
    body = _detect(client, text, language="auto")

    assert body["language_detected"] == "de", (
        f"lingua-py routing signal: expected 'de' for unambiguously German "
        f"text, got {body['language_detected']!r}. Either lingua-py "
        f"mis-detected the language or the language auto-detect path is "
        f"misreporting the routing decision."
    )

    scores = _scores_by_entity(body)
    assert "LOCATION" in scores, (
        f"DE-routed transformer engine should emit LOCATION on 'Berlin' / "
        f"'München'. None present. entities_found={body['entities_found']!r}. "
        f"This is consistent with the EN spaCy engine being dispatched by "
        f"mistake (it does not produce LOCATION at the floor of 0.90 for "
        f"these tokens). Investigate MultiNlpEngine._sub_engines dispatch."
    )

    max_loc_score = max(scores["LOCATION"])
    assert max_loc_score >= TRANSFORMER_FLOOR, (
        f"DE LOCATION score {max_loc_score:.4f} is below the transformer "
        f"fingerprint floor {TRANSFORMER_FLOOR}. xlm-roberta-large emits "
        f"LOCATION at >0.99 on 'Berlin'/'München'; spaCy `en_core_web_lg` "
        f"would emit at ~0.85 (or not at all). This score profile suggests "
        f"the request was routed to the EN sub-engine."
    )


def test_auto_routes_english_text_to_en_engine(client: httpx.Client) -> None:
    """Unambiguously English text + ``language: auto`` → EN sub-engine.

    Uses the REQ-016 spec's example sentence. lingua-py picks `en`;
    ``MultiNlpEngine`` must dispatch to the English spaCy engine.

    Routing signals checked:
      1. ``language_detected == "en"`` — lingua-py resolved to English.
      2. PERSON present in entities found.
      3. PERSON score == 0.85 — spaCy fingerprint. The transformer
         engine never produces this exact score on a clear PERSON span.

    Failure under an engine-swap bug: if the request routes to the DE
    transformer engine, PERSON score on `Anna Schmidt` would be ~0.9999
    (raw transformer probability) — assertion 3 fails with a clear diff.
    """
    text = "Anna Schmidt works at Acme Corp in New York."
    body = _detect(client, text, language="auto")

    assert body["language_detected"] == "en", (
        f"lingua-py routing signal: expected 'en' for unambiguously English "
        f"text, got {body['language_detected']!r}. Either lingua-py "
        f"mis-detected the language or the language auto-detect path is "
        f"misreporting the routing decision."
    )

    scores = _scores_by_entity(body)
    assert "PERSON" in scores, (
        f"EN-routed spaCy engine should emit PERSON on 'Anna Schmidt'. "
        f"None present. entities_found={body['entities_found']!r}."
    )

    person_score = max(scores["PERSON"])
    # spaCy emits at exactly 0.85; transformer always emits >0.95.
    # A score > 0.9 is the engine-swap canary.
    assert person_score < 0.9, (
        f"EN PERSON score {person_score:.4f} is above the spaCy "
        f"fingerprint ceiling of 0.9 (spaCy `en_core_web_lg` emits at "
        f"exactly 0.85). xlm-roberta-large-finetuned-conll03-german emits "
        f"PERSON at >0.99. This score profile indicates the request was "
        f"routed to the DE transformer engine."
    )
    assert abs(person_score - SPACY_PERSON_SCORE) < 0.01, (
        f"EN PERSON score {person_score:.4f} differs from the expected "
        f"spaCy `ner_strength` constant {SPACY_PERSON_SCORE}. Either the "
        f"upstream spaCy recognizer changed its scoring constant (review)"
        f" or the request was mis-routed."
    )


def test_auto_routing_signals_invert_under_explicit_language_swap(
    client: httpx.Client,
) -> None:
    """Sanity check: explicit `language: en` on DE text and `language: de`
    on EN text produce the inverted score fingerprints.

    This locks the score-fingerprint assumption used by the two tests
    above: the score profile on a fixed input genuinely differs based
    on the routed engine, so the swap-detection assertions in those
    tests have signal. If this test ever passes with mis-inverted
    scores, the engine fingerprints have collapsed and the auto-routing
    tests above lose their swap-detection power — review them.
    """
    # DE text forced through EN engine: PERSON score collapses to ~0.85,
    # LOCATION on Berlin doesn't survive Redakt's 0.90 LOCATION floor.
    body_de_via_en = _detect(
        client, "Sie wohnt in Berlin und arbeitet in München.", language="en"
    )
    de_scores_via_en = _scores_by_entity(body_de_via_en)
    if "PERSON" in de_scores_via_en:
        # If the EN spaCy somehow flags `Berlin` as PERSON it'd be at 0.85;
        # never at the >0.95 transformer mark.
        assert max(de_scores_via_en["PERSON"]) < 0.9, (
            "Engine fingerprint collapse: EN engine produced a >0.9 "
            "PERSON score, which means the score-fingerprint test in "
            "test_auto_routes_german_text_to_de_engine no longer has "
            "swap-detection signal. Review."
        )

    # EN text forced through DE engine: PERSON score jumps to >0.99.
    body_en_via_de = _detect(
        client, "Anna Schmidt works at Acme Corp in New York.", language="de"
    )
    en_scores_via_de = _scores_by_entity(body_en_via_de)
    assert "PERSON" in en_scores_via_de, (
        "EN text routed through DE transformer should still flag PERSON "
        "(transformer is multilingual on PER). None found. This breaks "
        "the swap-detection precondition."
    )
    person_via_de = max(en_scores_via_de["PERSON"])
    assert person_via_de >= TRANSFORMER_FLOOR, (
        f"Engine fingerprint collapse: DE transformer produced a PERSON "
        f"score of {person_via_de:.4f} on EN text, below the {TRANSFORMER_FLOOR} "
        f"floor that distinguishes it from spaCy's 0.85. The score "
        f"fingerprints used in test_auto_routes_english_text_to_en_engine "
        f"no longer have swap-detection signal. Review."
    )
