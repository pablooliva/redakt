"""Unit tests for audit logging service."""

import io
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from redakt.services.audit import (
    JSONFormatter,
    _emit_audit,
    log_anonymization,
    log_detection,
    log_document_upload,
    setup_logging,
)


@pytest.fixture(autouse=True)
def clean_audit_logger():
    """Ensure the audit logger is clean before and after each test."""
    audit_logger = logging.getLogger("redakt.audit")
    for handler in audit_logger.handlers[:]:
        handler.close()
    audit_logger.handlers.clear()
    yield
    for handler in audit_logger.handlers[:]:
        handler.close()
    audit_logger.handlers.clear()


def _capture_audit_output() -> tuple[logging.Logger, io.StringIO]:
    """Set up a StringIO buffer to capture formatted audit JSON output."""
    audit_logger = logging.getLogger("redakt.audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JSONFormatter())
    audit_logger.addHandler(handler)
    return audit_logger, buffer


class TestJSONFormatter:
    def test_output_structure(self):
        """JSON output contains timestamp, level, logger, plus audit data fields."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=2,
            entities_found=["EMAIL_ADDRESS", "PERSON"],
            language_detected="en",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        assert "timestamp" in data
        assert data["level"] == "INFO"
        assert data["logger"] == "redakt.audit"
        assert data["action"] == "detect"
        assert data["entity_count"] == 2
        assert data["entities_found"] == ["EMAIL_ADDRESS", "PERSON"]
        assert data["language_detected"] == "en"
        assert data["source"] == "api"
        # No extra fields like "message"
        assert "message" not in data

    def test_timestamp_format(self):
        """Timestamp is UTC ISO 8601 format."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=0,
            entities_found=[],
            language_detected="en",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        ts = data["timestamp"]
        # Should parse as a valid datetime and be UTC
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    def test_timestamp_uses_record_created(self):
        """Timestamp derives from record.created, not datetime.now().

        This ensures correct timestamps when using QueueHandler (post-v1).
        """
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="redakt.audit",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="",
            args=(),
            exc_info=None,
        )
        # Set record.created to a known past time (2020-01-01T00:00:00 UTC)
        record.created = 1577836800.0
        record.audit_data = {
            "action": "detect",
            "entity_count": 0,
            "entities_found": [],
            "language_detected": "en",
            "source": "api",
        }
        output = formatter.format(record)
        data = json.loads(output)
        parsed = datetime.fromisoformat(data["timestamp"])
        assert parsed.year == 2020
        assert parsed.month == 1
        assert parsed.day == 1

    def test_non_audit_record(self):
        """Non-audit records (no audit_data) produce message field."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="redakt.audit",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "test message"
        assert "audit_data" not in data


class TestSetupLogging:
    def test_handler_guard_stdout_only(self):
        """Calling setup_logging() 3 times results in exactly 1 handler."""
        setup_logging()
        setup_logging()
        setup_logging()
        audit_logger = logging.getLogger("redakt.audit")
        assert len(audit_logger.handlers) == 1

    def test_handler_guard_with_file(self):
        """Calling setup_logging() 3 times with file config results in exactly 2 handlers."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            setup_logging(audit_log_file=path)
            setup_logging(audit_log_file=path)
            setup_logging(audit_log_file=path)
            audit_logger = logging.getLogger("redakt.audit")
            assert len(audit_logger.handlers) == 2
        finally:
            os.unlink(path)

    def test_audit_level_always_info(self):
        """Audit logger level is INFO regardless of log_level parameter."""
        setup_logging(log_level="DEBUG")
        assert logging.getLogger("redakt.audit").level == logging.INFO
        setup_logging(log_level="ERROR")
        assert logging.getLogger("redakt.audit").level == logging.INFO

    def test_propagate_false(self):
        """Audit logger propagate is False."""
        setup_logging()
        assert logging.getLogger("redakt.audit").propagate is False

    def test_file_handler_invalid_path(self):
        """Invalid file path logs warning and falls back to stdout only."""
        with patch.object(logging.getLogger("redakt"), "warning") as mock_warn:
            setup_logging(audit_log_file="/nonexistent/path/audit.log")
        audit_logger = logging.getLogger("redakt.audit")
        assert len(audit_logger.handlers) == 1  # stdout only
        mock_warn.assert_called_once()
        assert "/nonexistent/path/audit.log" in str(mock_warn.call_args)

    def test_file_handler_rotation_config(self):
        """RotatingFileHandler is configured with correct maxBytes and backupCount."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            setup_logging(
                audit_log_file=path,
                audit_log_max_bytes=5_000_000,
                audit_log_backup_count=3,
            )
            audit_logger = logging.getLogger("redakt.audit")
            file_handlers = [
                h for h in audit_logger.handlers
                if hasattr(h, "maxBytes")
            ]
            assert len(file_handlers) == 1
            assert file_handlers[0].maxBytes == 5_000_000
            assert file_handlers[0].backupCount == 3
        finally:
            os.unlink(path)

    def test_file_then_no_file_closes_handler(self):
        """Calling setup_logging with file, then without, properly closes file handler."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            setup_logging(audit_log_file=path)
            audit_logger = logging.getLogger("redakt.audit")
            assert len(audit_logger.handlers) == 2

            # Call again without file config
            setup_logging()
            assert len(audit_logger.handlers) == 1
            # The remaining handler should be a StreamHandler (stdout)
            assert isinstance(audit_logger.handlers[0], logging.StreamHandler)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestEmitAudit:
    def test_defensive_error_handling(self):
        """Audit emission failure is caught and logged to app logger."""
        _logger, _buffer = _capture_audit_output()
        with patch.object(
            logging.getLogger("redakt.audit"),
            "handle",
            side_effect=OSError("Broken pipe"),
        ):
            with patch.object(
                logging.getLogger("redakt"), "warning"
            ) as mock_warn:
                # Should not raise
                _emit_audit(
                    action="detect",
                    entity_count=1,
                    entities_found=["PERSON"],
                    language_detected="en",
                    source="api",
                )
                mock_warn.assert_called_once()
                assert "Broken pipe" in str(mock_warn.call_args)

    def test_entities_found_field_name(self):
        """Audit data uses 'entities_found' key (not 'entity_types')."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=2,
            entities_found=["EMAIL_ADDRESS", "PERSON"],
            language_detected="en",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        assert "entities_found" in data
        assert "entity_types" not in data

    def test_language_detected_field_name(self):
        """Audit data uses 'language_detected' key (not 'language')."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=0,
            entities_found=[],
            language_detected="de",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        assert "language_detected" in data
        assert data["language_detected"] == "de"
        # Ensure old key not present
        keys = [k for k in data.keys() if k == "language"]
        assert len(keys) == 0

    def test_operator_included_when_set(self):
        """Operator field is present when explicitly passed."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="anonymize",
            entity_count=1,
            entities_found=["PERSON"],
            language_detected="en",
            source="api",
            operator="replace",
        )
        data = json.loads(buffer.getvalue())
        assert data["operator"] == "replace"

    def test_operator_absent_when_none(self):
        """Operator field is absent when not passed."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=1,
            entities_found=["PERSON"],
            language_detected="en",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        assert "operator" not in data

    def test_file_type_empty_defaults_to_unknown(self):
        """Empty file_type is defaulted to 'unknown'."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="document_upload",
            entity_count=0,
            entities_found=[],
            language_detected="en",
            source="api",
            file_type="",
            file_size_bytes=100,
        )
        data = json.loads(buffer.getvalue())
        assert data["file_type"] == "unknown"

    def test_file_type_none_excluded(self):
        """file_type=None is not included in audit data."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=0,
            entities_found=[],
            language_detected="en",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        assert "file_type" not in data

    def test_file_size_bytes_none_excluded(self):
        """file_size_bytes=None is not included in audit data."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=0,
            entities_found=[],
            language_detected="en",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        assert "file_size_bytes" not in data

    def test_large_entity_types_list(self):
        """All entity types are logged without truncation."""
        types = [f"ENTITY_TYPE_{i}" for i in range(25)]
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=25,
            entities_found=types,
            language_detected="en",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        assert data["entities_found"] == types
        assert len(data["entities_found"]) == 25


class TestLogDetection:
    def test_no_operator_field(self):
        """Detect action does not include operator field."""
        _logger, buffer = _capture_audit_output()
        log_detection(
            entity_count=1,
            entities_found=["PERSON"],
            language_detected="en",
            source="api",
        )
        data = json.loads(buffer.getvalue())
        assert data["action"] == "detect"
        assert "operator" not in data


class TestLogAnonymization:
    def test_includes_operator(self):
        """Anonymize action includes operator field."""
        _logger, buffer = _capture_audit_output()
        log_anonymization(
            entity_count=1,
            entities_found=["PERSON"],
            language_detected="en",
            source="api",
            operator="replace",
        )
        data = json.loads(buffer.getvalue())
        assert data["action"] == "anonymize"
        assert data["operator"] == "replace"


class TestLogDocumentUpload:
    def test_file_type_empty_defaults_unknown(self):
        """Empty file_type defaults to 'unknown'."""
        _logger, buffer = _capture_audit_output()
        log_document_upload(
            file_type="",
            file_size_bytes=1024,
            entity_count=0,
            entities_found=[],
            language_detected="en",
            source="api",
            operator="replace",
        )
        data = json.loads(buffer.getvalue())
        assert data["file_type"] == "unknown"

    def test_includes_operator(self):
        """Document upload includes operator field."""
        _logger, buffer = _capture_audit_output()
        log_document_upload(
            file_type="txt",
            file_size_bytes=1024,
            entity_count=1,
            entities_found=["PERSON"],
            language_detected="en",
            source="api",
            operator="replace",
        )
        data = json.loads(buffer.getvalue())
        assert data["operator"] == "replace"

    def test_includes_file_metadata(self):
        """Document upload includes file_type and file_size_bytes."""
        _logger, buffer = _capture_audit_output()
        log_document_upload(
            file_type="xlsx",
            file_size_bytes=102400,
            entity_count=3,
            entities_found=["EMAIL_ADDRESS", "LOCATION", "PERSON"],
            language_detected="de",
            source="api",
            operator="replace",
        )
        data = json.loads(buffer.getvalue())
        assert data["file_type"] == "xlsx"
        assert data["file_size_bytes"] == 102400
        assert data["action"] == "document_upload"


class TestAllowListCount:
    def test_omitted_when_none(self):
        """allow_list_count key absent when None."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=0,
            entities_found=[],
            language_detected="en",
            source="api",
            allow_list_count=None,
        )
        data = json.loads(buffer.getvalue())
        assert "allow_list_count" not in data

    def test_omitted_when_zero(self):
        """allow_list_count key absent when 0."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=0,
            entities_found=[],
            language_detected="en",
            source="api",
            allow_list_count=0,
        )
        data = json.loads(buffer.getvalue())
        assert "allow_list_count" not in data

    def test_present_when_positive(self):
        """allow_list_count is included when > 0."""
        _logger, buffer = _capture_audit_output()
        _emit_audit(
            action="detect",
            entity_count=0,
            entities_found=[],
            language_detected="en",
            source="api",
            allow_list_count=3,
        )
        data = json.loads(buffer.getvalue())
        assert data["allow_list_count"] == 3
