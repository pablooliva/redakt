"""Shared fixture loader for the eval suite and the calibration CLI.

Each YAML file under tests/eval/fixtures/ is a list of phrase records:

    - text: "..."
      language: en
      expect: [PERSON, EMAIL_ADDRESS]   # OR  expect_clean: true
      notes: "..."                      # optional
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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

    @property
    def label(self) -> str:
        snippet = self.text if len(self.text) <= 60 else self.text[:57] + "..."
        return f"[{self.fixture}] {snippet}"


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
        out.append(
            Phrase(
                text=record["text"],
                language=record.get("language", "en"),
                expect=expect,
                expect_clean=expect_clean,
                notes=record.get("notes", ""),
                fixture=path.stem,
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
