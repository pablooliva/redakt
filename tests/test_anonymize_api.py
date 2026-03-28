"""Integration tests for POST /api/anonymize endpoint."""

from unittest.mock import AsyncMock, patch

import httpx


class TestAnonymizeEndpoint:
    def test_anonymize_basic(self, client, mock_presidio_analyze, mock_anon_detect_language):
        text = "Contact John Smith at john@example.com please."
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85,
             "analysis_explanation": None, "recognition_metadata": None},
            {"entity_type": "EMAIL_ADDRESS", "start": 22, "end": 38, "score": 1.0,
             "analysis_explanation": None, "recognition_metadata": None},
        ]
        resp = client.post("/api/anonymize", json={"text": text})
        assert resp.status_code == 200
        data = resp.json()
        assert data["anonymized_text"] == "Contact <PERSON_1> at <EMAIL_ADDRESS_1> please."
        assert data["mappings"]["<PERSON_1>"] == "John Smith"
        assert data["mappings"]["<EMAIL_ADDRESS_1>"] == "john@example.com"
        assert data["language_detected"] == "en"

    def test_anonymize_no_pii(self, client, mock_presidio_analyze, mock_anon_detect_language):
        """REQ-006: No PII detected -> original text + empty mapping."""
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/anonymize", json={"text": "The weather is nice."})
        assert resp.status_code == 200
        data = resp.json()
        assert data["anonymized_text"] == "The weather is nice."
        assert data["mappings"] == {}

    def test_anonymize_empty_text(self, client):
        resp = client.post("/api/anonymize", json={"text": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["anonymized_text"] == ""
        assert data["mappings"] == {}
        assert data["language_detected"] == "unknown"

    def test_anonymize_language_auto(self, client, mock_presidio_analyze, mock_anon_detect_language):
        mock_anon_detect_language.return_value = "de"
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/anonymize", json={"text": "Mein Name ist Hans"})
        assert resp.status_code == 200
        assert resp.json()["language_detected"] == "de"
        mock_anon_detect_language.assert_called_once()

    def test_anonymize_language_explicit(self, client, mock_presidio_analyze, mock_anon_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/anonymize", json={"text": "Hello world", "language": "en"})
        assert resp.status_code == 200
        mock_anon_detect_language.assert_not_called()

    def test_anonymize_language_unsupported(self, client, mock_anon_detect_language):
        resp = client.post("/api/anonymize", json={"text": "Hello", "language": "ja"})
        assert resp.status_code == 400
        assert "not supported" in resp.json()["detail"]

    def test_anonymize_allow_list_merge(self, client, mock_presidio_analyze, mock_anon_detect_language):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.anonymize.settings") as mock_settings:
            mock_settings.allow_list = ["CompanyName"]
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.default_score_threshold = 0.35
            resp = client.post(
                "/api/anonymize",
                json={"text": "CompanyName is great", "allow_list": ["ProductName"]},
            )
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert "CompanyName" in call_kwargs["allow_list"]
        assert "ProductName" in call_kwargs["allow_list"]

    def test_anonymize_text_too_long(self, client):
        long_text = "a" * 512_001
        resp = client.post("/api/anonymize", json={"text": long_text})
        assert resp.status_code == 422

    def test_anonymize_presidio_unavailable(self, client, mock_anon_detect_language):
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            resp = client.post("/api/anonymize", json={"text": "John Smith lives here"})
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"]

    def test_anonymize_presidio_timeout(self, client, mock_anon_detect_language):
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("Timeout"),
        ):
            resp = client.post("/api/anonymize", json={"text": "John Smith lives here"})
        assert resp.status_code == 504
        assert "timed out" in resp.json()["detail"]

    def test_anonymize_presidio_error(self, client, mock_anon_detect_language):
        mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test/analyze"))
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=mock_response.request, response=mock_response
            ),
        ):
            resp = client.post("/api/anonymize", json={"text": "John Smith lives here"})
        assert resp.status_code == 502

    def test_anonymize_score_threshold_default(self, client, mock_presidio_analyze, mock_anon_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/anonymize", json={"text": "Hello world"})
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert call_kwargs["score_threshold"] == 0.35

    def test_anonymize_score_threshold_custom(self, client, mock_presidio_analyze, mock_anon_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/anonymize", json={"text": "Hello world", "score_threshold": 0.8})
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert call_kwargs["score_threshold"] == 0.8

    def test_anonymize_audit_log(self, client, mock_presidio_analyze, mock_anon_detect_language):
        text = "Contact John Smith at john@example.com please."
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85},
            {"entity_type": "EMAIL_ADDRESS", "start": 22, "end": 38, "score": 1.0},
        ]
        with patch("redakt.routers.anonymize.log_anonymization") as mock_log:
            client.post("/api/anonymize", json={"text": text})
            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["entity_count"] == 2
            assert "PERSON" in call_kwargs["entity_types"]
            assert "EMAIL_ADDRESS" in call_kwargs["entity_types"]
            assert call_kwargs["source"] == "api"
            # Verify no PII in log call
            assert "John" not in str(call_kwargs)
            assert "example.com" not in str(call_kwargs)

    def test_anonymize_response_structure(self, client, mock_presidio_analyze, mock_anon_detect_language):
        """Verify response matches API contract exactly."""
        mock_presidio_analyze.return_value = []
        resp = client.post("/api/anonymize", json={"text": "Hello world"})
        data = resp.json()
        assert set(data.keys()) == {"anonymized_text", "mappings", "language_detected"}
        assert isinstance(data["anonymized_text"], str)
        assert isinstance(data["mappings"], dict)
        assert isinstance(data["language_detected"], str)
