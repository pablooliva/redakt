"""Calibration report — non-asserting view of how Redakt handles the eval fixtures.

Walks every phrase under tests/eval/fixtures/, sends each one to Redakt's
/api/detect?verbose=true, and prints a human-readable record of:

  - what Redakt returned (entity types + scores, post-filter)
  - the phrase's expected outcome
  - PASS/FAIL verdict against that expectation

Pass `--raw` to also hit Presidio Analyzer directly with score_threshold=0.0
for the same phrase and language. That shows pre-filter candidates including
those Redakt's per-entity score floors would drop — useful for tuning.

Pass `--out` to also write the report to a Markdown file. With no path,
writes to reports/calibration-YYYYMMDD-HHMMSS.md (the reports/ directory is
gitignored). Pass an explicit path to override.

Run:
  uv run python tools/calibration_report.py
  uv run python tools/calibration_report.py --only benign,us
  uv run python tools/calibration_report.py --raw
  uv run python tools/calibration_report.py --out
  uv run python tools/calibration_report.py --raw --out reports/before-tuning.md
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.eval._loader import Phrase, load_all_phrases  # noqa: E402

DEFAULT_REDAKT_URL = os.environ.get("REDAKT_URL", "http://localhost:8000")
DEFAULT_PRESIDIO_URL = os.environ.get(
    "PRESIDIO_ANALYZER_URL", "http://localhost:5002"
)
DEFAULT_REPORTS_DIR = ROOT / "reports"


def _format_scores(items: list[tuple[str, float]]) -> str:
    if not items:
        return "—"
    return ", ".join(f"{name}({score:.2f})" for name, score in items)


def _verdict(phrase: Phrase, found: list[str]) -> str:
    if phrase.expect_clean:
        return "PASS" if not found else "FAIL"
    expected = set(phrase.expect)
    if expected.issubset(set(found)):
        return "PASS"
    return "FAIL"


def _detect_via_redakt(
    http: httpx.Client, url: str, phrase: Phrase
) -> tuple[list[tuple[str, float]], list[str]]:
    response = http.post(
        f"{url}/api/detect?verbose=true",
        json=phrase.build_request_body(),
    )
    response.raise_for_status()
    body = response.json()
    details = body.get("details", [])
    pairs = [(d["entity_type"], d["score"]) for d in details]
    found = sorted({d["entity_type"] for d in details})
    return pairs, found


def _detect_via_presidio(
    http: httpx.Client, url: str, phrase: Phrase
) -> list[tuple[str, float]]:
    """Raw scores, score_threshold=0 — shows everything before Redakt filters."""
    response = http.post(
        f"{url}/analyze",
        json={
            "text": phrase.text,
            "language": phrase.language,
            "score_threshold": 0.0,
        },
    )
    response.raise_for_status()
    return [(r["entity_type"], r["score"]) for r in response.json()]


class Report:
    """Captures lines for both stdout and an optional Markdown file."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, line: str = "") -> None:
        print(line)
        self.lines.append(line)

    def write_markdown(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def run(
    redakt_url: str,
    presidio_url: str | None,
    only: list[str] | None,
    out_path: Path | None,
) -> int:
    phrases = load_all_phrases(only=only)
    if not phrases:
        print("No phrases loaded — check fixture filter.", file=sys.stderr)
        return 2

    report = Report()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report.add("# Redakt calibration report")
    report.add("")
    report.add(f"- Generated: {timestamp}")
    report.add(f"- Redakt: {redakt_url}")
    if presidio_url:
        report.add(f"- Presidio (raw): {presidio_url}")
    if only:
        report.add(f"- Fixtures: {', '.join(only)}")
    report.add(f"- Phrases: {len(phrases)}")
    report.add("")
    report.add("---")
    report.add("")

    fails = 0
    # trust_env=False bypasses any HTTP(S)_PROXY env vars (e.g. the Socket
    # Firewall sandbox intercepts Python network calls but not curl/system
    # traffic to localhost). Same fix pattern as commit a2ddeda for the
    # eval-suite client and tools/memodo_pilot.py.
    with httpx.Client(timeout=10.0, trust_env=False) as http:
        for phrase in phrases:
            try:
                kept_pairs, found = _detect_via_redakt(http, redakt_url, phrase)
            except httpx.HTTPError as exc:
                report.add(f"## [ERROR] {phrase.fixture} — {phrase.text}")
                report.add("")
                report.add(f"- redakt: {exc}")
                report.add("")
                fails += 1
                continue

            verdict = _verdict(phrase, found)
            if verdict == "FAIL":
                fails += 1

            expected = (
                "(clean)" if phrase.expect_clean else ", ".join(phrase.expect) or "—"
            )
            report.add(f"## [{verdict}] {phrase.fixture} — {phrase.text}")
            report.add("")
            report.add(f"- lang: `{phrase.language}`")
            report.add(f"- expected: {expected}")
            report.add(f"- redakt: {_format_scores(kept_pairs)}")

            if presidio_url:
                try:
                    raw_pairs = _detect_via_presidio(http, presidio_url, phrase)
                    report.add(f"- raw: {_format_scores(raw_pairs)}")
                    dropped = [
                        p for p in raw_pairs if (p[0], p[1]) not in set(kept_pairs)
                    ]
                    if dropped:
                        report.add(f"- dropped: {_format_scores(dropped)}")
                except httpx.HTTPError as exc:
                    report.add(f"- raw: (presidio error: {exc})")

            if phrase.notes:
                report.add(f"- notes: {phrase.notes}")
            report.add("")

    report.add("---")
    report.add("")
    report.add(f"**Summary:** {len(phrases) - fails} passing, {fails} failing")

    if out_path is not None:
        report.write_markdown(out_path)
        print(f"\nReport written to {out_path}", file=sys.stderr)

    return 0 if fails == 0 else 1


def _resolve_out_path(value: str | None) -> Path | None:
    """Translate the --out arg into a real path.

    None  → no file written.
    ""    → default location reports/calibration-YYYYMMDD-HHMMSS.md.
    other → use the given path verbatim.
    """
    if value is None:
        return None
    if value == "":
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return DEFAULT_REPORTS_DIR / f"calibration-{stamp}.md"
    return Path(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--redakt-url", default=DEFAULT_REDAKT_URL,
        help=f"Redakt API URL (default: {DEFAULT_REDAKT_URL})",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Also call Presidio directly with score_threshold=0 to show pre-filter scores",
    )
    parser.add_argument(
        "--presidio-url", default=DEFAULT_PRESIDIO_URL,
        help=f"Presidio analyzer URL for --raw (default: {DEFAULT_PRESIDIO_URL})",
    )
    parser.add_argument(
        "--only", default=None,
        help="Comma-separated fixture stems to include (e.g. 'benign,us')",
    )
    parser.add_argument(
        "--out", nargs="?", const="", default=None, metavar="PATH",
        help=(
            "Also write a Markdown report to PATH. "
            "Use bare --out for default reports/calibration-YYYYMMDD-HHMMSS.md."
        ),
    )
    args = parser.parse_args()
    only = (
        [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    )
    presidio_url = args.presidio_url if args.raw else None
    out_path = _resolve_out_path(args.out)
    return run(args.redakt_url, presidio_url, only, out_path)


if __name__ == "__main__":
    raise SystemExit(main())
