from unittest.mock import AsyncMock, patch

import httpx
import pytest

from redakt.services.language import LanguageDetection
from tests.conftest import SAMPLE_PRESIDIO_RESULTS


class TestDetectEndpoint:
    def test_detect_has_pii(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        resp = client.post("/api/detect", json={"text": "My name is John Smith"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is True
        assert data["entity_count"] == 2
        assert "PERSON" in data["entities_found"]
        assert "EMAIL_ADDRESS" in data["entities_found"]

    def test_detect_no_pii(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/detect", json={"text": "The weather is nice today"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is False
        assert data["entity_count"] == 0
        assert data["entities_found"] == []

    def test_detect_verbose(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        resp = client.post("/api/detect?verbose=true", json={"text": "My name is John Smith"})
        assert resp.status_code == 200
        data = resp.json()
        assert "details" in data
        assert len(data["details"]) == 2
        assert data["details"][0]["entity_type"] == "PERSON"

    def test_detect_verbose_off(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        resp = client.post("/api/detect", json={"text": "My name is John Smith"})
        assert resp.status_code == 200
        data = resp.json()
        assert "details" not in data

    def test_detect_language_auto(self, client, mock_presidio_analyze, mock_detect_language):
        mock_detect_language.return_value = LanguageDetection("de", 0.92)
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/detect", json={"text": "Mein Name ist Hans"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["language_detected"] == "de"
        assert data["language_confidence"] == 0.92
        mock_detect_language.assert_called_once()

    def test_detect_language_explicit(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/detect", json={"text": "Hello world", "language": "en"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["language_confidence"] is None  # Manual override
        mock_detect_language.assert_not_called()

    def test_detect_language_fallback(self, client, mock_presidio_analyze, mock_detect_language):
        mock_detect_language.return_value = LanguageDetection("en", 0.0)
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/detect", json={"text": "123"})
        assert resp.status_code == 200
        assert resp.json()["language_detected"] == "en"

    def test_detect_language_unsupported(self, client, mock_detect_language):
        resp = client.post("/api/detect", json={"text": "Hello", "language": "ja"})
        assert resp.status_code == 400
        assert "not supported" in resp.json()["detail"]

    def test_detect_allow_list_merge(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.settings") as mock_settings:
            mock_settings.allow_list = ["CompanyName"]
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.default_score_threshold = 0.35
            resp = client.post(
                "/api/detect",
                json={"text": "CompanyName is great", "allow_list": ["ProductName"]},
            )
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert "CompanyName" in call_kwargs["allow_list"]
        assert "ProductName" in call_kwargs["allow_list"]

    def test_detect_text_too_long(self, client):
        long_text = "a" * 512_001
        resp = client.post("/api/detect", json={"text": long_text})
        assert resp.status_code == 422

    def test_detect_empty_text(self, client):
        resp = client.post("/api/detect", json={"text": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is False
        assert data["language_detected"] == "en"  # Fallback language
        assert data["language_confidence"] is None  # No detection attempted

    def test_detect_empty_text_with_unsupported_language(self, client):
        """EDGE-001: Empty text should return has_pii:false even with unsupported language."""
        resp = client.post("/api/detect", json={"text": "", "language": "ja"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is False
        assert data["language_detected"] == "en"  # Fallback language

    def test_detect_whitespace_only(self, client):
        resp = client.post("/api/detect", json={"text": "   \n\t  "})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is False

    def test_detect_score_threshold_zero(self, client, mock_presidio_analyze, mock_detect_language):
        """EDGE-009: score_threshold=0.0 is allowed and passes to Presidio."""
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        resp = client.post(
            "/api/detect",
            json={"text": "John Smith test", "score_threshold": 0.0},
        )
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert call_kwargs["score_threshold"] == 0.0

    def test_detect_score_threshold_default_from_config(self, client, mock_presidio_analyze, mock_detect_language):
        """P3 #12: When score_threshold omitted, uses config default."""
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/detect", json={"text": "Hello world"})
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert call_kwargs["score_threshold"] == 0.35

    def test_detect_presidio_unavailable(self, client, mock_detect_language):
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            resp = client.post("/api/detect", json={"text": "John Smith lives here"})
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"]

    def test_detect_presidio_error(self, client, mock_detect_language):
        mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test/analyze"))
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=mock_response.request, response=mock_response
            ),
        ):
            resp = client.post("/api/detect", json={"text": "John Smith lives here"})
        assert resp.status_code == 502
        assert "returned an error" in resp.json()["detail"]

    def test_detect_presidio_timeout(self, client, mock_detect_language):
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("Timeout"),
        ):
            resp = client.post("/api/detect", json={"text": "John Smith lives here"})
        assert resp.status_code == 504
        assert "timed out" in resp.json()["detail"]

    def test_detect_audit_log(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        with patch("redakt.routers.detect.log_detection") as mock_log:
            client.post("/api/detect", json={"text": "My name is John Smith"})
            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["entity_count"] == 2
            assert "PERSON" in call_kwargs["entity_types"]
            assert call_kwargs["source"] == "api"
            # Verify no PII in the log call
            assert "John" not in str(call_kwargs)
