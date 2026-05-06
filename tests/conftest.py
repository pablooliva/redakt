from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from redakt.main import app
from redakt.services.language import LanguageDetection


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
    """Mock the language detection service in the detect router."""
    with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock) as mock:
        mock.return_value = LanguageDetection("en", 0.95)
        yield mock


@pytest.fixture
def mock_anon_detect_language():
    """Mock the language detection service in the anonymize router."""
    with patch("redakt.routers.anonymize.detect_language", new_callable=AsyncMock) as mock:
        mock.return_value = LanguageDetection("en", 0.95)
        yield mock


@pytest.fixture
def mock_doc_detect_language():
    """Mock the language detection service in the document processor."""
    with patch("redakt.services.document_processor.detect_language", new_callable=AsyncMock) as mock:
        mock.return_value = LanguageDetection("en", 0.95)
        yield mock


@pytest.fixture
def client():
    """Test client with mocked httpx client on app state."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_upload_semaphore():
    """Reset the module-level upload semaphore between tests."""
    import redakt.routers.documents as docs_mod
    docs_mod._upload_semaphore = None
    yield
    docs_mod._upload_semaphore = None


SAMPLE_PRESIDIO_RESULTS = [
    {
        "entity_type": "PERSON",
        "start": 11,
        "end": 21,
        # NOTE (SDD-007 4e F-O): the 0.85 score here is BACKEND-AGNOSTIC.
        # Tests under `tests/` use these mocks to exercise Redakt's
        # downstream behavior (entity-threshold filtering, anonymizer
        # mapping, audit logging) — the score value is illustrative,
        # not a claim about any specific NLP backend's output. The eval
        # suite (`tests/eval/`) hits the real analyzer for behavior
        # under the deployed config (multi.yaml: en→spaCy, de→xlm-roberta).
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
