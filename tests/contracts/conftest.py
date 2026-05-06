"""Shared fixtures for contract gate tests (REQ-010 / REQ-010a / REQ-011).

These tests require a live Redakt + Presidio stack. They are excluded from the
default `uv run pytest tests/` run via pyproject.toml's `addopts`. Invoke
explicitly with `uv run pytest tests/contracts/`.
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
    with httpx.Client(base_url=REDAKT_URL, timeout=30.0) as c:
        yield c
