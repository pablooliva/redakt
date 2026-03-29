"""Integration tests for allow list web UI handlers and API validation."""

import json
import logging
from unittest.mock import AsyncMock, patch

import httpx

from redakt.services.language import LanguageDetection
from tests.conftest import SAMPLE_PRESIDIO_RESULTS


class TestDetectAllowListWeb:
    """Tests for detect page allow_list functionality."""

    def test_detect_page_shows_allow_list_input(self, client):
        resp = client.get("/detect")
        assert resp.status_code == 200
        assert 'name="allow_list"' in resp.text
        assert "allow_list_help" in resp.text
        assert "case-sensitive" in resp.text

    def test_detect_page_shows_instance_terms(self, client):
        with patch("redakt.routers.pages.settings") as mock_settings:
            mock_settings.allow_list = ["CompanyName", "ProductX"]
            mock_settings.base_dir = __import__("redakt.config", fromlist=["settings"]).settings.base_dir
            resp = client.get("/detect")
        assert resp.status_code == 200
        assert "CompanyName" in resp.text
        assert "ProductX" in resp.text
        assert "Instance-wide terms" in resp.text

    def test_detect_submit_with_allow_list(self, client, mock_presidio_analyze):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("en", 0.95)):
            resp = client.post(
                "/detect/submit",
                data={"text": "Acme Corp is great", "language": "en", "allow_list": "Acme Corp, ProductX"},
            )
        assert resp.status_code == 200
        # Verify allow_list was passed to presidio
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert "Acme Corp" in call_kwargs["allow_list"]
        assert "ProductX" in call_kwargs["allow_list"]

    def test_detect_submit_empty_allow_list(self, client, mock_presidio_analyze):
        """Empty allow_list field should work (no per-request terms)."""
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("en", 0.95)):
            resp = client.post(
                "/detect/submit",
                data={"text": "Hello world", "language": "en", "allow_list": ""},
            )
        assert resp.status_code == 200

    def test_detect_submit_validation_too_many_terms(self, client):
        terms = ", ".join(f"term{i}" for i in range(101))
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("en", 0.95)):
            resp = client.post(
                "/detect/submit",
                data={"text": "Hello world", "language": "en", "allow_list": terms},
            )
        assert resp.status_code == 200
        assert "exceeds maximum of 100 terms" in resp.text

    def test_detect_submit_validation_term_too_long(self, client):
        long_term = "a" * 201
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("en", 0.95)):
            resp = client.post(
                "/detect/submit",
                data={"text": "Hello world", "language": "en", "allow_list": long_term},
            )
        assert resp.status_code == 200
        assert "exceeds maximum length" in resp.text


class TestAnonymizeAllowListWeb:
    """Tests for anonymize page allow_list functionality."""

    def test_anonymize_page_shows_allow_list_input(self, client):
        resp = client.get("/anonymize")
        assert resp.status_code == 200
        assert 'name="allow_list"' in resp.text
        assert "case-sensitive" in resp.text

    def test_anonymize_submit_with_allow_list(self, client, mock_presidio_analyze, mock_anon_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post(
            "/anonymize/submit",
            data={"text": "Acme Corp is great", "language": "en", "allow_list": "Acme Corp"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert "Acme Corp" in call_kwargs["allow_list"]

    def test_anonymize_submit_validation_too_many_terms(self, client, mock_anon_detect_language):
        terms = ", ".join(f"term{i}" for i in range(101))
        resp = client.post(
            "/anonymize/submit",
            data={"text": "Hello world", "language": "en", "allow_list": terms},
        )
        assert resp.status_code == 200
        assert "exceeds maximum of 100 terms" in resp.text


class TestDocumentsAllowListWeb:
    """Tests for documents page allow_list functionality."""

    def test_documents_page_shows_allow_list_input(self, client):
        resp = client.get("/documents")
        assert resp.status_code == 200
        assert 'name="allow_list"' in resp.text
        assert "case-sensitive" in resp.text

    def test_documents_submit_with_allow_list(self, client, mock_presidio_analyze, mock_doc_detect_language):
        """Verify that submitting a document with allow list passes terms to process_document."""
        mock_presidio_analyze.return_value = []
        resp = client.post(
            "/documents/submit",
            files={"file": ("test.txt", b"John Smith works at Acme Corp", "text/plain")},
            data={"language": "en", "allow_list": "Acme Corp, ProductX"},
        )
        assert resp.status_code == 200
        # Verify allow_list was passed to presidio analyze
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert "Acme Corp" in call_kwargs["allow_list"]
        assert "ProductX" in call_kwargs["allow_list"]

    def test_documents_submit_empty_doc_with_allow_list(self, client):
        """Empty document with allow list terms should still report allow_list_count in audit."""
        with patch("redakt.routers.pages.log_document_upload") as mock_log:
            resp = client.post(
                "/documents/submit",
                files={"file": ("empty.txt", b"", "text/plain")},
                data={"language": "en", "allow_list": "Acme Corp, ProductX"},
            )
        assert resp.status_code == 200
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        # allow_list_count should reflect the 2 terms, not None
        assert call_kwargs["allow_list_count"] == 2

    def test_documents_submit_empty_doc_with_instance_and_request_allow_list(self, client):
        """Empty document with both instance and per-request terms should report merged count."""
        with patch("redakt.services.document_processor.settings") as mock_dp_settings, \
             patch("redakt.routers.pages.log_document_upload") as mock_log:
            mock_dp_settings.allow_list = ["InstanceTerm"]
            mock_dp_settings.max_file_size = 10 * 1024 * 1024
            mock_dp_settings.supported_file_types = [".txt", ".md", ".csv", ".json", ".xml", ".html", ".rtf", ".pdf", ".docx", ".xlsx"]
            mock_dp_settings.language_detection_fallback = "en"
            mock_dp_settings.default_score_threshold = 0.35
            mock_dp_settings.max_text_length = 512 * 1024
            resp = client.post(
                "/documents/submit",
                files={"file": ("empty.txt", b"   ", "text/plain")},
                data={"language": "en", "allow_list": "Acme Corp"},
            )
        assert resp.status_code == 200
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        # Merged: InstanceTerm + Acme Corp = 2
        assert call_kwargs["allow_list_count"] == 2


class TestAllowListEdgeCaseIntegration:
    """Integration tests for edge cases EDGE-002 and EDGE-010."""

    def test_partial_match_does_not_suppress(self, client, mock_presidio_analyze, mock_detect_language):
        """EDGE-002: 'John' in allow_list should NOT suppress 'John Smith' detection."""
        # Simulate Presidio returning PERSON for "John Smith" even with "John" in allow_list
        mock_presidio_analyze.return_value = [
            {
                "entity_type": "PERSON",
                "start": 0,
                "end": 10,
                "score": 0.85,
                "analysis_explanation": None,
                "recognition_metadata": None,
            }
        ]
        resp = client.post(
            "/api/detect",
            json={"text": "John Smith is here", "allow_list": ["John"]},
        )
        assert resp.status_code == 200
        # Presidio's exact match means "John" does not suppress "John Smith"
        # Verify the allow_list was passed (Presidio handles the matching)
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert "John" in call_kwargs["allow_list"]
        # Entity should still be returned since Presidio does exact match
        data = resp.json()
        assert data["entity_count"] == 1
        assert "PERSON" in data["entities_found"]

    def test_cross_language_allow_list(self, client, mock_presidio_analyze):
        """EDGE-010: Same allow_list term with different languages."""
        mock_presidio_analyze.return_value = []
        # English text with allow list
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("en", 0.95)):
            resp_en = client.post(
                "/api/detect",
                json={"text": "Meeting with John Smith in Berlin", "allow_list": ["Berlin"]},
            )
        assert resp_en.status_code == 200
        call_en = mock_presidio_analyze.call_args.kwargs
        assert call_en["language"] == "en"
        assert "Berlin" in call_en["allow_list"]

        # German text with same allow list
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("de", 0.90)):
            resp_de = client.post(
                "/api/detect",
                json={"text": "Treffen mit Johann Schmidt in Berlin", "language": "auto", "allow_list": ["Berlin"]},
            )
        assert resp_de.status_code == 200
        call_de = mock_presidio_analyze.call_args.kwargs
        assert call_de["language"] == "de"
        assert "Berlin" in call_de["allow_list"]


class TestDetectAllowListAPI:
    """API-level allow_list validation tests."""

    def test_detect_api_validation_too_many_terms(self, client, mock_detect_language):
        terms = [f"term{i}" for i in range(101)]
        resp = client.post("/api/detect", json={"text": "Hello world", "allow_list": terms})
        assert resp.status_code == 422
        assert "exceeds maximum of 100 terms" in resp.json()["detail"]

    def test_detect_api_validation_term_too_long(self, client, mock_detect_language):
        terms = ["a" * 201]
        resp = client.post("/api/detect", json={"text": "Hello world", "allow_list": terms})
        assert resp.status_code == 422
        assert "exceeds maximum length" in resp.json()["detail"]

    def test_detect_api_valid_allow_list(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post(
            "/api/detect",
            json={"text": "Hello world", "allow_list": ["Acme Corp", "ProductX"]},
        )
        assert resp.status_code == 200

    def test_detect_api_max_valid_terms(self, client, mock_presidio_analyze, mock_detect_language):
        """100 terms, each 200 chars -- at the limit, should pass."""
        mock_presidio_analyze.return_value = []
        terms = ["a" * 200 for _ in range(100)]
        resp = client.post(
            "/api/detect",
            json={"text": "Hello world", "allow_list": terms},
        )
        assert resp.status_code == 200


class TestAnonymizeAllowListAPI:
    def test_anonymize_api_validation_too_many_terms(self, client, mock_anon_detect_language):
        terms = [f"term{i}" for i in range(101)]
        resp = client.post("/api/anonymize", json={"text": "Hello world", "allow_list": terms})
        assert resp.status_code == 422
        assert "exceeds maximum of 100 terms" in resp.json()["detail"]

    def test_anonymize_api_validation_term_too_long(self, client, mock_anon_detect_language):
        terms = ["a" * 201]
        resp = client.post("/api/anonymize", json={"text": "Hello world", "allow_list": terms})
        assert resp.status_code == 422
        assert "exceeds maximum length" in resp.json()["detail"]


class TestDocumentsAllowListAPI:
    def test_documents_api_validation_too_many_terms(self, client, mock_doc_detect_language, mock_presidio_analyze):
        terms = ", ".join(f"term{i}" for i in range(101))
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.txt", b"Hello world", "text/plain")},
            data={"allow_list": terms},
        )
        assert resp.status_code == 422
        assert "exceeds maximum of 100 terms" in resp.json()["detail"]


class TestAllowListAuditLogging:
    """Tests for allow_list_count in audit logs."""

    def test_detect_audit_includes_allow_list_count(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.log_detection") as mock_log:
            resp = client.post(
                "/api/detect",
                json={"text": "Hello world", "allow_list": ["Acme Corp", "ProductX"]},
            )
        assert resp.status_code == 200
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["allow_list_count"] == 2

    def test_detect_audit_excludes_allow_list_terms(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.log_detection") as mock_log:
            resp = client.post(
                "/api/detect",
                json={"text": "Hello world", "allow_list": ["SecretCompany"]},
            )
        assert resp.status_code == 200
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        # Never log actual terms
        assert "SecretCompany" not in str(call_kwargs)
        # Only count is logged
        assert call_kwargs["allow_list_count"] == 1

    def test_detect_audit_no_allow_list_count_when_none(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.log_detection") as mock_log:
            resp = client.post("/api/detect", json={"text": "Hello world"})
        assert resp.status_code == 200
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["allow_list_count"] is None

    def test_anonymize_audit_includes_allow_list_count(self, client, mock_presidio_analyze, mock_anon_detect_language):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.anonymize.log_anonymization") as mock_log:
            resp = client.post(
                "/api/anonymize",
                json={"text": "Hello world", "allow_list": ["Acme Corp"]},
            )
        assert resp.status_code == 200
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["allow_list_count"] == 1


class TestAllowListInstanceMerge:
    """Tests for instance + per-request allow list merge behavior."""

    def test_instance_allow_list_applied_without_per_request(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.settings") as mock_settings:
            mock_settings.allow_list = ["CompanyName"]
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.default_score_threshold = 0.35
            mock_settings.language_detection_fallback = "en"
            resp = client.post("/api/detect", json={"text": "CompanyName is great"})
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        assert call_kwargs["allow_list"] == ["CompanyName"]

    def test_merge_deduplicates(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.settings") as mock_settings:
            mock_settings.allow_list = ["CompanyName"]
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.default_score_threshold = 0.35
            mock_settings.language_detection_fallback = "en"
            resp = client.post(
                "/api/detect",
                json={"text": "CompanyName is great", "allow_list": ["CompanyName", "Other"]},
            )
        assert resp.status_code == 200
        call_kwargs = mock_presidio_analyze.call_args.kwargs
        # Should be deduplicated
        assert call_kwargs["allow_list"] == ["CompanyName", "Other"]


class TestAllowListEdgeCases:
    """Edge case tests for allow list behavior."""

    def test_unicode_terms_in_api(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post(
            "/api/detect",
            json={"text": "Meeting in München", "allow_list": ["München", "Straße", "北京市"]},
        )
        assert resp.status_code == 200

    def test_regex_special_chars_in_exact_mode(self, client, mock_presidio_analyze, mock_detect_language):
        mock_presidio_analyze.return_value = []
        resp = client.post(
            "/api/detect",
            json={"text": "Email test@example.com", "allow_list": ["test@example.com"]},
        )
        assert resp.status_code == 200

    def test_only_whitespace_allow_list_entries(self, client, mock_presidio_analyze):
        """Web UI: submitting only whitespace entries should be treated as empty."""
        mock_presidio_analyze.return_value = []
        with patch("redakt.routers.detect.detect_language", new_callable=AsyncMock, return_value=LanguageDetection("en", 0.95)):
            resp = client.post(
                "/detect/submit",
                data={"text": "Hello world", "language": "en", "allow_list": "  ,  ,  "},
            )
        assert resp.status_code == 200
