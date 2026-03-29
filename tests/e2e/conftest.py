"""E2E test fixtures — runs against the Docker Compose stack.

Expects `docker compose up` to be running (Redakt on port 8000 + Presidio services).
Run tests with: uv run pytest tests/e2e/ -v
With browser visible: uv run pytest tests/e2e/ -v --headed
"""

import httpx
import pytest

REDAKT_URL = "http://localhost:8000"


@pytest.fixture(scope="session")
def base_url():
    """Provide the base URL for Playwright — points to the Docker Compose Redakt instance."""
    try:
        resp = httpx.get(f"{REDAKT_URL}/api/health/live", timeout=3.0)
        if resp.status_code != 200:
            pytest.skip("Redakt server not healthy — is docker compose up running?")
    except httpx.ConnectError:
        pytest.skip("Redakt server not reachable at localhost:8000 — run: docker compose up")

    return REDAKT_URL
