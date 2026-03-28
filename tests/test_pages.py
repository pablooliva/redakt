from unittest.mock import AsyncMock, patch

import httpx

from tests.conftest import SAMPLE_PRESIDIO_RESULTS


class TestDetectPage:
    def test_detect_page_renders(self, client):
        resp = client.get("/detect")
        assert resp.status_code == 200
        assert "PII Detection" in resp.text
        assert "htmx" in resp.text

    def test_detect_submit_with_pii(self, client, mock_presidio_analyze):
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value="en"):
            resp = client.post(
                "/detect/submit",
                data={"text": "My name is John Smith", "language": "auto"},
            )
        assert resp.status_code == 200
        assert "PII Detected" in resp.text
        assert "PERSON" in resp.text

    def test_detect_submit_no_pii(self, client, mock_presidio_analyze):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value="en"):
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
