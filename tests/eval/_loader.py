"""Shared fixture loader for the eval suite and the calibration CLI.

Each YAML file under tests/eval/fixtures/ is a list of phrase records:

    - text: "..."
      language: en
      expect: [PERSON, EMAIL_ADDRESS]   # OR  expect_clean: true
      notes: "..."                      # optional
      request_params:                   # optional — extra fields merged into
        closed_world_filtering: true    # the /api/detect POST body

Baseline invariant: `closed_world_filtering` defaults to `False` in every
request body emitted by `Phrase.build_request_body()` unless a fixture sets
it explicitly via `request_params`. This pins the eval suite to Redakt's
COMPAT-001 baseline (flag-off behavior identical to today) regardless of
the running instance's config.yaml default. The 4 closed-world acceptance
fixtures opt in via `request_params: {closed_world_filtering: true}`; the
116 baseline fixtures get the explicit `false` and stay deterministic
across operator config experiments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class Phrase:
    text: str
    language: str
    expect: tuple[str, ...]
    expect_clean: bool
    notes: str
    fixture: str
    # Per-fixture overrides merged into the /api/detect request body (REQ-014).
    # Keys here replace or extend the default body keys.  The loader validates
    # that only recognised body fields are used (fail-closed).
    request_params: tuple[tuple[str, Any], ...]

    @property
    def label(self) -> str:
        snippet = self.text if len(self.text) <= 60 else self.text[:57] + "..."
        return f"[{self.fixture}] {snippet}"

    def build_request_body(self) -> dict[str, Any]:
        """Return the /api/detect JSON body for this phrase.

        Base keys are `text` and `language`.  Any `request_params` entries
        are merged on top, with per-fixture values taking precedence.

        Baseline pin: `closed_world_filtering` is set to `False` by default
        so the suite asserts COMPAT-001 (today's behavior) regardless of
        the running instance's config.yaml default. Fixtures opting into
        closed-world set it explicitly via `request_params`.
        """
        body: dict[str, Any] = {
            "text": self.text,
            "language": self.language,
            "closed_world_filtering": False,
        }
        body.update(dict(self.request_params))
        return body


# Fields that the /api/detect endpoint accepts in the request body.
# Any request_params key not in this set is rejected at load time so
# typos in fixture files fail early rather than silently being ignored.
_ALLOWED_REQUEST_PARAM_KEYS: frozenset[str] = frozenset(
    {
        "language",
        "allow_list",
        "entity_score_thresholds",
        "entities",
        "closed_world_filtering",
    }
)


def _load_one(path: Path) -> list[Phrase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out: list[Phrase] = []
    for record in raw:
        expect = tuple(record.get("expect") or ())
        expect_clean = bool(record.get("expect_clean", False))
        if expect_clean and expect:
            raise ValueError(
                f"{path.name}: a phrase cannot set both expect_clean and expect"
            )
        raw_params_value = record.get("request_params")
        # MEDIUM-004 fix: defensively validate the type of request_params before
        # treating it as a dict. A list, string, or integer silently passed through
        # the previous `or {}` fallback; now we raise a clear error.
        if raw_params_value is None or raw_params_value == []:
            raw_params: dict[str, Any] = {}
        elif not isinstance(raw_params_value, dict):
            raise ValueError(
                f"{path.name}: request_params must be a mapping (dict), "
                f"got {type(raw_params_value).__name__!r}: {raw_params_value!r}. "
                "Expected form: request_params: {{closed_world_filtering: true}}"
            )
        else:
            raw_params = raw_params_value
        unknown = set(raw_params) - _ALLOWED_REQUEST_PARAM_KEYS
        if unknown:
            raise ValueError(
                f"{path.name}: unknown request_params key(s): {sorted(unknown)}. "
                f"Allowed: {sorted(_ALLOWED_REQUEST_PARAM_KEYS)}"
            )
        out.append(
            Phrase(
                text=record["text"],
                language=record.get("language", "en"),
                expect=expect,
                expect_clean=expect_clean,
                notes=record.get("notes", ""),
                fixture=path.stem,
                request_params=tuple(raw_params.items()),
            )
        )
    return out


def load_all_phrases(only: list[str] | None = None) -> list[Phrase]:
    """Load every phrase across all fixture files.

    `only` is an optional list of fixture stems (e.g. ["benign", "us"]) to filter to.
    """
    phrases: list[Phrase] = []
    for path in sorted(FIXTURES_DIR.glob("*.yaml")):
        if only and path.stem not in only:
            continue
        phrases.extend(_load_one(path))
    return phrases
