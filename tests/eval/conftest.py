"""Eval-suite fixtures.

These tests run end-to-end against the Redakt API (default
http://localhost:8000), exercising the real /api/detect path including the
per-entity score post-filter, allow lists, and language handling.

The full Docker Compose stack (Redakt + Presidio Analyzer + Anonymizer) must
be running. If Redakt's health endpoint isn't reachable, the suite is skipped.
"""

from __future__ import annotations

import os

import httpx
import pytest

REDAKT_URL = os.environ.get("REDAKT_URL", "http://localhost:8000")


def _redakt_ready(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/health", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def redakt_url() -> str:
    if not _redakt_ready(REDAKT_URL):
        pytest.skip(
            f"Redakt API not reachable at {REDAKT_URL} — "
            "start the full Docker Compose stack first."
        )
    return REDAKT_URL


@pytest.fixture(scope="session")
def http(redakt_url: str):
    with httpx.Client(timeout=10.0) as client:
        yield client
