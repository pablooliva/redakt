"""Shared fixtures for integration tests (REQ-016 etc.).

These tests require a live Redakt + Presidio stack (Redakt on
`localhost:8000`, Presidio analyzer wrapped behind it). They are excluded
from the default `uv run pytest tests/` run via pyproject.toml's `addopts`.
Invoke explicitly with `uv run pytest tests/integration/`.
"""
from __future__ import annotations

import os

import httpx
import pytest


REDAKT_URL = os.environ.get("REDAKT_URL", "http://localhost:8000")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    """Plain httpx client against the live Redakt API.

    Module scope so we open a single TCP connection per test module.
    """
    with httpx.Client(base_url=REDAKT_URL, timeout=60.0) as c:
        yield c
