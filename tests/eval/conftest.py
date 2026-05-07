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


# trust_env=False bypasses any HTTP(S)_PROXY env vars (e.g., a sandbox
# proxy that intercepts Python network calls but not direct localhost
# traffic). Without this, the readiness check 405s and the whole suite
# silently skips.
def _redakt_ready(url: str) -> bool:
    try:
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            return client.get(f"{url}/api/health").status_code == 200
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
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        yield client
