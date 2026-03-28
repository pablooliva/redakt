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


def log_detection(
    entity_count: int,
    entity_types: list[str],
    language: str,
    source: str,
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
        "action": "detect",
        "entity_count": entity_count,
        "entity_types": entity_types,
        "language": language,
        "source": source,
    }
    audit_logger.handle(record)
