import json
from unittest.mock import AsyncMock, patch

import httpx

from redakt.services.language import LanguageDetection
from tests.conftest import SAMPLE_PRESIDIO_RESULTS


class TestDetectPage:
    def test_detect_page_renders(self, client):
        resp = client.get("/detect")
        assert resp.status_code == 200
        assert "PII Detection" in resp.text
        assert "htmx" in resp.text

    def test_detect_submit_with_pii(self, client, mock_presidio_analyze):
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("en", 0.95)):
            resp = client.post(
                "/detect/submit",
                data={"text": "My name is John Smith", "language": "auto"},
            )
        assert resp.status_code == 200
        assert "PII Detected" in resp.text
        assert "PERSON" in resp.text

    def test_detect_submit_no_pii(self, client, mock_presidio_analyze):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("en", 0.95)):
            resp = client.post(
                "/detect/submit",
                data={"text": "Weather is nice", "language": "en"},
            )
        assert resp.status_code == 200
        assert "No PII Detected" in resp.text

    def test_detect_submit_empty_text(self, client):
        resp = client.post("/detect/submit", data={"text": "", "language": "auto"})
        assert resp.status_code == 200
        assert "No PII Detected" in resp.text

    def test_detect_submit_text_too_long(self, client):
        long_text = "a" * 512_001
        resp = client.post("/detect/submit", data={"text": long_text, "language": "en"})
        assert resp.status_code == 200
        assert "exceeds maximum length" in resp.text

    def test_detect_submit_presidio_unavailable(self, client):
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ), patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value="en"):
            resp = client.post(
                "/detect/submit",
                data={"text": "John Smith", "language": "en"},
            )
        assert resp.status_code == 200
        assert "starting up" in resp.text

    def test_detect_submit_presidio_timeout(self, client):
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("Timeout"),
        ), patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value="en"):
            resp = client.post(
                "/detect/submit",
                data={"text": "John Smith", "language": "en"},
            )
        assert resp.status_code == 200
        assert "timed out" in resp.text


class TestAnonymizePage:
    def test_anonymize_page_renders(self, client):
        resp = client.get("/anonymize")
        assert resp.status_code == 200
        assert "PII Anonymization" in resp.text
        assert "deanonymize.js" in resp.text
        assert "deanonymize-section" in resp.text

    def test_anonymize_submit_with_pii(self, client, mock_presidio_analyze, mock_anon_detect_language):
        text = "Contact John Smith at john@example.com please."
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85},
            {"entity_type": "EMAIL_ADDRESS", "start": 22, "end": 38, "score": 1.0},
        ]
        resp = client.post(
            "/anonymize/submit",
            data={"text": text, "language": "en"},
        )
        assert resp.status_code == 200
        assert "Anonymized Text" in resp.text
        assert "&lt;PERSON_1&gt;" in resp.text
        assert "&lt;EMAIL_ADDRESS_1&gt;" in resp.text
        assert "data-mappings" in resp.text
        assert "Copy to clipboard" in resp.text
        # Verify mapping table
        assert "Mapping (2 entries)" in resp.text

    def test_anonymize_submit_no_pii(self, client, mock_presidio_analyze, mock_anon_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post(
            "/anonymize/submit",
            data={"text": "Weather is nice", "language": "en"},
        )
        assert resp.status_code == 200
        assert "Anonymized Text" in resp.text
        assert "Mapping (0 entries)" in resp.text

    def test_anonymize_submit_empty_text(self, client):
        resp = client.post("/anonymize/submit", data={"text": "", "language": "auto"})
        assert resp.status_code == 200
        # Empty text returns unchanged with empty mapping
        assert "Mapping (0 entries)" in resp.text

    def test_anonymize_submit_text_too_long(self, client):
        long_text = "a" * 512_001
        resp = client.post("/anonymize/submit", data={"text": long_text, "language": "en"})
        assert resp.status_code == 200
        assert "exceeds maximum length" in resp.text

    def test_anonymize_submit_presidio_unavailable(self, client, mock_anon_detect_language):
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            resp = client.post(
                "/anonymize/submit",
                data={"text": "John Smith", "language": "en"},
            )
        assert resp.status_code == 200
        assert "starting up" in resp.text

    def test_anonymize_submit_presidio_timeout(self, client, mock_anon_detect_language):
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("Timeout"),
        ):
            resp = client.post(
                "/anonymize/submit",
                data={"text": "John Smith", "language": "en"},
            )
        assert resp.status_code == 200
        assert "timed out" in resp.text

    def test_anonymize_submit_mappings_json_roundtrip(self, client, mock_presidio_analyze, mock_anon_detect_language):
        """Verify data-mappings attribute contains valid JSON after HTML entity decoding."""
        text = "Contact John Smith please."
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85},
        ]
        resp = client.post(
            "/anonymize/submit",
            data={"text": text, "language": "en"},
        )
        assert resp.status_code == 200
        # The data-mappings value is JSON-serialized by Jinja2's |tojson filter
        # which escapes single quotes to \u0027 (safe for single-quoted HTML attribute)
        import html
        import re
        match = re.search(r"data-mappings='([^']*)'", resp.text)
        assert match is not None, "data-mappings attribute not found"
        decoded = html.unescape(match.group(1))
        mappings = json.loads(decoded)
        assert mappings["<PERSON_1>"] == "John Smith"
