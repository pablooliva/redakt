import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        if hasattr(record, "audit_data"):
            log_data.update(record.audit_data)
        else:
            log_data["message"] = record.getMessage()
        return json.dumps(log_data)


def setup_logging(log_level: str = "WARNING") -> None:
    # Audit logger — always INFO, JSON format, stdout
    audit_logger = logging.getLogger("redakt.audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False

    audit_handler = logging.StreamHandler()
    audit_handler.setFormatter(JSONFormatter())
    audit_logger.addHandler(audit_handler)

    # Application logger
    app_logger = logging.getLogger("redakt")
    app_logger.setLevel(getattr(logging, log_level.upper(), logging.WARNING))


def _emit_audit(
    action: str,
    entity_count: int,
    entity_types: list[str],
    language: str,
    source: str,
    allow_list_count: int | None = None,
    **extra: object,
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
        "entity_types": entity_types,
        "language": language,
        "source": source,
    }
    if allow_list_count is not None and allow_list_count > 0:
        record.audit_data["allow_list_count"] = allow_list_count
    record.audit_data.update(extra)
    audit_logger.handle(record)


def log_detection(
    entity_count: int,
    entity_types: list[str],
    language: str,
    source: str,
    allow_list_count: int | None = None,
) -> None:
    _emit_audit("detect", entity_count, entity_types, language, source, allow_list_count=allow_list_count)


def log_anonymization(
    entity_count: int,
    entity_types: list[str],
    language: str,
    source: str,
    allow_list_count: int | None = None,
) -> None:
    _emit_audit("anonymize", entity_count, entity_types, language, source, allow_list_count=allow_list_count)


def log_document_upload(
    file_type: str,
    file_size_bytes: int,
    entity_count: int,
    entity_types: list[str],
    language: str,
    source: str,
    allow_list_count: int | None = None,
) -> None:
    _emit_audit(
        "document_upload",
        entity_count,
        entity_types,
        language,
        source,
        allow_list_count=allow_list_count,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
    )
