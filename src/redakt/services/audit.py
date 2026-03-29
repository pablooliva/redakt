"""Audit logging service for Redakt.

Provides structured JSON audit logging for all PII detection and anonymization
operations. Logs metadata only — never PII, original text, filenames, or
anonymization mappings.

Known v1 Limitations
--------------------
- **Source field spoofability:** The ``source`` field ("web_ui" vs "api") is
  derived from the ``HX-Request`` header set by HTMX. Any API caller can set
  ``HX-Request: true`` to appear as ``web_ui``. For v1 without authentication,
  this is accepted.

- **Log integrity:** v1 has no tamper-detection mechanism. Audit entries are
  plain JSON lines to stdout (and optionally a file). There is no signing, no
  sequence numbers, and no hash chain. A compliance officer relying on these
  logs cannot cryptographically prove they have not been modified. For
  production hardening, ship logs to an immutable log store (e.g., AWS
  CloudWatch, append-only S3, centralized SIEM) and consider adding monotonic
  sequence numbers for gap detection.

- **Synchronous emission:** ``audit_logger.handle(record)`` is synchronous. If
  a log handler is slow (e.g., remote fluentd, full pipe buffer, slow disk),
  the event loop is blocked. For v1 with stdout + optional file, this is
  acceptable. Migration to ``QueueHandler``/``QueueListener`` is the
  recommended post-v1 path.

- **No failed-request auditing:** Requests that fail before processing
  completes (Presidio 503/504/502, validation errors) are not audited. This
  is a compliance gap that should be documented for the DPO.

- **Language detection ambiguity:** The ``language_detected`` field logs the
  resolved language code but does not distinguish between auto-detected and
  manually specified languages. Adding ``language_confidence`` (which is
  ``None`` for manual override) is deferred to post-v1.
"""

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        if hasattr(record, "audit_data"):
            log_data.update(record.audit_data)
        else:
            log_data["message"] = record.getMessage()
        return json.dumps(log_data)


def setup_logging(
    log_level: str = "WARNING",
    audit_log_file: str = "",
    audit_log_max_bytes: int = 10_485_760,
    audit_log_backup_count: int = 5,
) -> None:
    # Audit logger — always INFO, JSON format, stdout
    audit_logger = logging.getLogger("redakt.audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False

    # Close and remove existing handlers to prevent duplicate accumulation
    # on uvicorn reload or repeated calls (Python's handlers.clear() does NOT
    # call handler.close(), so we must iterate explicitly to release file
    # descriptors).
    for handler in audit_logger.handlers[:]:
        handler.close()
    audit_logger.handlers.clear()

    # Always add stdout handler
    audit_handler = logging.StreamHandler()
    audit_handler.setFormatter(JSONFormatter())
    audit_logger.addHandler(audit_handler)

    # Optionally add file handler
    if audit_log_file:
        try:
            file_handler = RotatingFileHandler(
                audit_log_file,
                maxBytes=audit_log_max_bytes,
                backupCount=audit_log_backup_count,
            )
            file_handler.setFormatter(JSONFormatter())
            audit_logger.addHandler(file_handler)
        except (OSError, PermissionError) as exc:
            logging.getLogger("redakt").warning(
                "Audit log file handler could not be created for path '%s': %s. "
                "Falling back to stdout only.",
                audit_log_file,
                exc,
            )

    # Application logger
    app_logger = logging.getLogger("redakt")
    app_logger.setLevel(getattr(logging, log_level.upper(), logging.WARNING))


def _emit_audit(
    action: str,
    entity_count: int,
    entities_found: list[str],
    language_detected: str,
    source: str,
    allow_list_count: int | None = None,
    file_type: str | None = None,
    file_size_bytes: int | None = None,
    operator: str | None = None,
) -> None:
    audit_logger = logging.getLogger("redakt.audit")
    record = audit_logger.makeRecord(
        name="redakt.audit",
        level=logging.INFO,
        fn="",
        lno=0,
        msg="",
        args=(),
        exc_info=None,
    )
    record.audit_data = {
        "action": action,
        "entity_count": entity_count,
        "entities_found": entities_found,
        "language_detected": language_detected,
        "source": source,
    }
    if allow_list_count is not None and allow_list_count > 0:
        record.audit_data["allow_list_count"] = allow_list_count
    if file_type is not None:
        record.audit_data["file_type"] = file_type or "unknown"
    if file_size_bytes is not None:
        record.audit_data["file_size_bytes"] = file_size_bytes
    if operator is not None:
        record.audit_data["operator"] = operator

    try:
        audit_logger.handle(record)
    except Exception as exc:
        # exc_info=True is safe here: the traceback can only reference audit
        # metadata (action, entity counts, language code, source) — never PII.
        # The _emit_audit signature accepts only typed metadata fields, and
        # record.audit_data contains the same safe metadata dict.
        logging.getLogger("redakt").warning(
            "Audit log emission failed: %s: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )


def log_detection(
    entity_count: int,
    entities_found: list[str],
    language_detected: str,
    source: str,
    allow_list_count: int | None = None,
) -> None:
    _emit_audit(
        "detect",
        entity_count,
        entities_found,
        language_detected,
        source,
        allow_list_count=allow_list_count,
    )


def log_anonymization(
    entity_count: int,
    entities_found: list[str],
    language_detected: str,
    source: str,
    allow_list_count: int | None = None,
    operator: str | None = None,
) -> None:
    _emit_audit(
        "anonymize",
        entity_count,
        entities_found,
        language_detected,
        source,
        allow_list_count=allow_list_count,
        operator=operator,
    )


def log_document_upload(
    file_type: str,
    file_size_bytes: int,
    entity_count: int,
    entities_found: list[str],
    language_detected: str,
    source: str,
    allow_list_count: int | None = None,
    operator: str | None = None,
) -> None:
    _emit_audit(
        "document_upload",
        entity_count,
        entities_found,
        language_detected,
        source,
        allow_list_count=allow_list_count,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        operator=operator,
    )
