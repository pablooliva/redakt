"""Integration tests for audit logging — full request through TestClient to JSON output.

Note on EDGE-008 (concurrent request isolation): Python's ``logging`` module
guarantees thread-safe handler emission via internal locks (``Handler.acquire()``
/ ``Handler.release()``).  Each ``Logger.handle()`` call acquires the handler lock
before ``emit()``, so concurrent requests produce non-interleaved JSON lines by
stdlib contract.  A dedicated concurrency test would be testing Python's stdlib,
not Redakt's code, and is therefore omitted.
"""

import io
import json
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from redakt.services.audit import JSONFormatter
from redakt.services.language import LanguageDetection
from tests.conftest import SAMPLE_PRESIDIO_RESULTS


@pytest.fixture
def audit_capture(client):
    """Attach a StringIO handler to the audit logger AFTER the client (and lifespan) has started.

    The client fixture triggers setup_logging() which clears handlers. We must
    add our capture handler after that.
    """
    audit_logger = logging.getLogger("redakt.audit")
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JSONFormatter())
    audit_logger.addHandler(handler)
    yield buffer
    audit_logger.removeHandler(handler)
    handler.close()


class TestDetectAuditIntegration:
    def test_detect_audit_json_structure(
        self, client, mock_presidio_analyze, mock_detect_language, audit_capture
    ):
        """Full detect request produces audit JSON with all REQ-012 fields."""
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        resp = client.post("/api/detect", json={"text": "My name is John Smith"})
        assert resp.status_code == 200

        output = audit_capture.getvalue()
        data = json.loads(output)
        assert data["action"] == "detect"
        assert data["entity_count"] == 2
        assert data["entities_found"] == ["EMAIL_ADDRESS", "PERSON"]
        assert data["language_detected"] == "en"
        assert data["source"] == "api"
        assert "timestamp" in data
        assert data["level"] == "INFO"
        assert data["logger"] == "redakt.audit"
        # detect action should NOT have operator
        assert "operator" not in data

    def test_source_detection_api_route(
        self, client, mock_presidio_analyze, mock_detect_language, audit_capture
    ):
        """Request without HX-Request header gets source='api'."""
        mock_presidio_analyze.return_value = []
        client.post("/api/detect", json={"text": "Hello"})
        data = json.loads(audit_capture.getvalue())
        assert data["source"] == "api"

    def test_source_detection_htmx_header(
        self, client, mock_presidio_analyze, mock_detect_language, audit_capture
    ):
        """Request with HX-Request: true gets source='web_ui'."""
        mock_presidio_analyze.return_value = []
        client.post(
            "/api/detect",
            json={"text": "Hello"},
            headers={"HX-Request": "true"},
        )
        data = json.loads(audit_capture.getvalue())
        assert data["source"] == "web_ui"

    def test_entities_found_is_deduplicated(
        self, client, mock_presidio_analyze, mock_detect_language, audit_capture
    ):
        """entities_found is deduplicated and sorted."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 0, "end": 5, "score": 0.85},
            {"entity_type": "PERSON", "start": 10, "end": 15, "score": 0.85},
            {"entity_type": "EMAIL_ADDRESS", "start": 20, "end": 35, "score": 1.0},
        ]
        client.post("/api/detect", json={"text": "John and Jane at test@example.com"})
        data = json.loads(audit_capture.getvalue())
        assert data["entities_found"] == ["EMAIL_ADDRESS", "PERSON"]
        assert data["entity_count"] == 3

    def test_no_pii_in_audit_output(
        self, client, mock_presidio_analyze, mock_detect_language, audit_capture
    ):
        """No PII values appear in the formatted JSON output."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 11, "end": 21, "score": 0.85},
        ]
        client.post("/api/detect", json={"text": "My name is John Smith and my email is john@example.com"})
        output = audit_capture.getvalue()
        assert "John" not in output
        assert "Smith" not in output
        assert "john@example.com" not in output
        assert "example.com" not in output


class TestAnonymizeAuditIntegration:
    def test_anonymize_audit_json_structure(
        self, client, mock_presidio_analyze, mock_anon_detect_language, audit_capture
    ):
        """Full anonymize request produces audit JSON with operator field."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85},
        ]
        resp = client.post("/api/anonymize", json={"text": "Contact John Smith please"})
        assert resp.status_code == 200

        data = json.loads(audit_capture.getvalue())
        assert data["action"] == "anonymize"
        assert data["operator"] == "replace"
        assert data["entities_found"] == ["PERSON"]
        assert data["language_detected"] == "en"
        assert data["entity_count"] == 1
        assert data["source"] == "api"


class TestDocumentUploadAuditIntegration:
    def test_document_upload_audit_json_structure(
        self, client, mock_presidio_analyze, mock_doc_detect_language, audit_capture
    ):
        """Full document upload produces audit JSON with file metadata and operator."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.85},
        ]
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.txt", io.BytesIO(b"John Smith"), "text/plain")},
        )
        assert resp.status_code == 200

        data = json.loads(audit_capture.getvalue())
        assert data["action"] == "document_upload"
        assert data["file_type"] == "txt"
        assert data["file_size_bytes"] == 10
        assert data["operator"] == "replace"
        assert data["entity_count"] == 1
        assert data["entities_found"] == ["PERSON"]
        assert data["language_detected"] == "en"
        assert data["source"] == "api"


class TestAuditNotEmittedOnError:
    def test_audit_not_emitted_on_presidio_error(
        self, client, mock_detect_language, audit_capture
    ):
        """When Presidio returns 503, no audit log entry is emitted."""
        with patch(
            "redakt.services.presidio.PresidioClient.analyze",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            resp = client.post("/api/detect", json={"text": "John Smith"})
        assert resp.status_code == 503
        assert audit_capture.getvalue() == ""


class TestEmptyTextAudit:
    """EDGE-003: Empty text requests produce audit entries with zero entities."""

    def test_detect_empty_text_audit(
        self, client, audit_capture
    ):
        """Empty text detect produces audit with entity_count=0, entities_found=[]."""
        resp = client.post("/api/detect", json={"text": ""})
        assert resp.status_code == 200

        data = json.loads(audit_capture.getvalue())
        assert data["action"] == "detect"
        assert data["entity_count"] == 0
        assert data["entities_found"] == []
        assert data["language_detected"] == "en"

    def test_anonymize_empty_text_audit(
        self, client, audit_capture
    ):
        """Empty text anonymize produces audit with entity_count=0, entities_found=[]."""
        resp = client.post("/api/anonymize", json={"text": ""})
        assert resp.status_code == 200

        data = json.loads(audit_capture.getvalue())
        assert data["action"] == "anonymize"
        assert data["entity_count"] == 0
        assert data["entities_found"] == []
        assert data["operator"] == "replace"


class TestEmptyDocumentAudit:
    """EDGE-013: Document with zero text chunks produces valid audit entry."""

    def test_empty_document_audit(
        self, client, mock_presidio_analyze, mock_doc_detect_language, audit_capture
    ):
        """Empty document produces audit with entity_count=0, operator='replace'."""
        mock_presidio_analyze.return_value = []
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )
        assert resp.status_code == 200

        data = json.loads(audit_capture.getvalue())
        assert data["action"] == "document_upload"
        assert data["entity_count"] == 0
        assert data["entities_found"] == []
        assert data["operator"] == "replace"
        assert data["file_type"] == "txt"
        assert data["language_detected"] == "en"


class TestNoPiiInAuditAnonymize:
    """SEC-001: No PII values appear in anonymize audit output."""

    def test_no_pii_in_anonymize_audit_output(
        self, client, mock_presidio_analyze, mock_anon_detect_language, audit_capture
    ):
        """PII values from anonymize request must not appear in audit JSON."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85},
            {"entity_type": "EMAIL_ADDRESS", "start": 22, "end": 38, "score": 1.0},
        ]
        client.post(
            "/api/anonymize",
            json={"text": "Contact John Smith at john@example.com please"},
        )
        output = audit_capture.getvalue()
        assert "John" not in output
        assert "Smith" not in output
        assert "john@example.com" not in output

    def test_no_pii_in_document_upload_audit_output(
        self, client, mock_presidio_analyze, mock_doc_detect_language, audit_capture
    ):
        """PII values from document upload must not appear in audit JSON."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.85},
        ]
        client.post(
            "/api/documents/upload",
            files={"file": ("test.txt", io.BytesIO(b"John Smith"), "text/plain")},
        )
        output = audit_capture.getvalue()
        assert "John" not in output
        assert "Smith" not in output


class TestWebUiRouteAudit:
    """Integration tests for audit logging from web UI routes (pages.py call sites)."""

    def test_detect_submit_audit(
        self, client, mock_presidio_analyze, mock_detect_language, audit_capture
    ):
        """Web UI detect submit produces audit entry with source='web_ui'."""
        mock_presidio_analyze.return_value = SAMPLE_PRESIDIO_RESULTS
        resp = client.post(
            "/detect/submit",
            data={"text": "My name is John Smith", "language": "auto"},
        )
        assert resp.status_code == 200

        data = json.loads(audit_capture.getvalue())
        assert data["action"] == "detect"
        assert data["source"] == "web_ui"
        assert data["entities_found"] == ["EMAIL_ADDRESS", "PERSON"]
        assert data["entity_count"] == 2
        assert data["language_detected"] == "en"
        assert "operator" not in data

    def test_anonymize_submit_audit(
        self, client, mock_presidio_analyze, mock_anon_detect_language, audit_capture
    ):
        """Web UI anonymize submit produces audit entry with operator and source='web_ui'."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85},
        ]
        resp = client.post(
            "/anonymize/submit",
            data={"text": "Contact John Smith please", "language": "auto"},
        )
        assert resp.status_code == 200

        data = json.loads(audit_capture.getvalue())
        assert data["action"] == "anonymize"
        assert data["source"] == "web_ui"
        assert data["operator"] == "replace"
        assert data["entities_found"] == ["PERSON"]
        assert data["entity_count"] == 1
        assert data["language_detected"] == "en"

    def test_documents_submit_audit(
        self, client, mock_presidio_analyze, mock_doc_detect_language, audit_capture
    ):
        """Web UI document submit produces audit entry with file metadata and source='web_ui'."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.85},
        ]
        resp = client.post(
            "/documents/submit",
            files={"file": ("test.txt", io.BytesIO(b"John Smith"), "text/plain")},
            data={"language": "auto"},
        )
        assert resp.status_code == 200

        data = json.loads(audit_capture.getvalue())
        assert data["action"] == "document_upload"
        assert data["source"] == "web_ui"
        assert data["operator"] == "replace"
        assert data["file_type"] == "txt"
        assert data["file_size_bytes"] == 10
        assert data["entities_found"] == ["PERSON"]
        assert data["entity_count"] == 1
        assert data["language_detected"] == "en"
