from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from redakt.main import app


@pytest.fixture
def mock_presidio_analyze():
    """Mock the Presidio analyze endpoint responses."""
    with patch("redakt.services.presidio.PresidioClient.analyze", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_presidio_health():
    """Mock the Presidio health check."""
    with patch(
        "redakt.services.presidio.PresidioClient.check_health", new_callable=AsyncMock
    ) as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mock_detect_language():
    """Mock the language detection service."""
    with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock) as mock:
        mock.return_value = "en"
        yield mock


@pytest.fixture
def client():
    """Test client with mocked httpx client on app state."""
    with TestClient(app) as c:
        yield c


SAMPLE_PRESIDIO_RESULTS = [
    {
        "entity_type": "PERSON",
        "start": 11,
        "end": 21,
        "score": 0.85,
        "analysis_explanation": None,
        "recognition_metadata": None,
    },
    {
        "entity_type": "EMAIL_ADDRESS",
        "start": 38,
        "end": 58,
        "score": 1.0,
        "analysis_explanation": None,
        "recognition_metadata": None,
    },
]
