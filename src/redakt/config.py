import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

logger = logging.getLogger("redakt")

# Default: resolve from this file's location (works both installed and local)
_DEFAULT_BASE_DIR = str(Path(__file__).parent)

# Path to the YAML config file. Defaults to ./config.yaml relative to the
# working directory; override with REDAKT_CONFIG_FILE for non-standard
# layouts. Missing file is fine — the YAML source returns {} and the
# class defaults below take effect.
_CONFIG_YAML_PATH = Path(os.environ.get("REDAKT_CONFIG_FILE", "config.yaml"))


class _YamlConfigSource(PydanticBaseSettingsSource):
    """Load Settings fields from a YAML file at the project root.

    Sits between env vars and class defaults in the precedence chain
    so committed policy values (in config.yaml) act as the operative
    defaults, while .env / shell env still override per instance.
    """

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)
        if _CONFIG_YAML_PATH.is_file():
            with _CONFIG_YAML_PATH.open(encoding="utf-8") as fh:
                self._data: dict[str, Any] = yaml.safe_load(fh) or {}
        else:
            self._data = {}

    def get_field_value(
        self, _field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        # Required by the PydanticBaseSettingsSource interface but the
        # FieldInfo isn't needed — the YAML key matches the field name
        # directly, and YAML's typed scalars match pydantic's coercion.
        value = self._data.get(field_name)
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return {
            name: self._data[name]
            for name in self._data
            if name in self.settings_cls.model_fields
        }


class Settings(BaseSettings):
    base_dir: str = _DEFAULT_BASE_DIR
    presidio_analyzer_url: str = "http://localhost:5001"
    presidio_anonymizer_url: str = "http://localhost:5001"
    default_score_threshold: float = 0.35
    entity_score_thresholds: dict[str, float] = {"LOCATION": 0.90, "DATE_TIME": 0.95}
    default_language: str = "auto"
    supported_languages: list[str] = ["en", "de"]
    allow_list: list[str] = []
    max_text_length: int = 512_000  # ~500KB
    presidio_timeout: float = 30.0
    language_detection_timeout: float = 2.0
    language_detection_fallback: str = "en"
    log_level: str = "WARNING"

    # Audit logging settings
    audit_log_file: str = ""
    audit_log_max_bytes: int = 10_485_760  # 10MB
    audit_log_backup_count: int = 5

    # Document upload settings
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    supported_file_types: list[str] = [
        ".txt", ".md", ".csv", ".json", ".xml", ".html",
        ".xlsx", ".docx", ".rtf", ".pdf",
    ]
    document_processing_timeout: float = 120.0
    max_zip_uncompressed_size: int = 100 * 1024 * 1024  # 100MB
    max_concurrent_uploads: int = 3
    max_xlsx_cells: int = 50_000

    # --- Closed-world filtering (REQ-001, REQ-002, REQ-003, SEC-001a, REQ-020) ---
    # Default strong anchors: entity types that confirm a natural person is
    # identifiable in the submission. When any one of these is present,
    # quasi-identifier spans are retained (not suppressed).
    strong_anchors: list[str] = [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "IBAN_CODE",
        "EU_VAT_ID",
        "BIC_CODE",
        "SEPA_CREDITOR_ID",
        "MEDICAL_LICENSE",
        "DE_TAX_ID",
        "DE_VAT_ID",
        "DE_ID_CARD",
        "DE_PASSPORT",
        "DE_SOCIAL_SECURITY",
        "DE_FUEHRERSCHEIN",
        "DE_LANR",
        "DE_TAX_NUMBER",
        "DE_HEALTH_INSURANCE",
        "DE_MASTR_ID",
        "DE_KFZ",
    ]
    # Default quasi-identifiers: entity types that are only re-identifying
    # when joined with a strong anchor. Suppressed when no anchor is present.
    quasi_identifiers: list[str] = [
        "DATE_TIME",
        "LOCATION",
        "NRP",
        "DE_PLZ",
    ]
    closed_world_filtering: bool = False
    # Operator gate: set to false to prevent per-request closed_world_filtering
    # overrides. The effective value is always the instance default.
    allow_per_request_closed_world_override: bool = True
    # When true, unrecognized entity types in strong_anchors or quasi_identifiers
    # raise a ValidationError at startup instead of emitting a WARNING.
    strict_entity_validation: bool = False
    # Regulatory scope: include "HIPAA" to enforce HIPAA Safe Harbor
    # incompatibility gate (prevents enabling closed_world_filtering).
    regulatory_scope: list[str] = ["GDPR"]

    # Pre-computed frozensets for O(1) per-call membership checks (PERF-001).
    # Populated once by the model_validator below; never recomputed at request time.
    strong_anchors_set: frozenset[str] = frozenset()
    quasi_identifiers_set: frozenset[str] = frozenset()

    model_config = {
        "env_prefix": "REDAKT_",
        "env_nested_delimiter": "__",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # Canonical set of recognized regulatory scopes (HIGH-001 / MEDIUM-002 fix).
    # All tokens in regulatory_scope are normalized (uppercase + strip) at validator
    # entry and validated against this set. Unknown tokens raise a ValueError if
    # strict_entity_validation is True, or emit a WARNING otherwise (same pattern
    # as entity-type validation). This prevents HIPAA-gate bypass via casing typos.
    CANONICAL_REGULATORY_SCOPES: frozenset[str] = frozenset({"GDPR", "HIPAA", "CCPA"})

    @model_validator(mode="after")
    def validate_closed_world_config(self) -> "Settings":
        """Validate closed-world filtering configuration at startup (fail-fast)."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        # HIGH-001 / MEDIUM-002 fix: Normalize regulatory_scope tokens at
        # validator entry (uppercase + strip whitespace) so that env-var or YAML
        # spellings like ["hipaa"], ["Hipaa"], ["HIPAA "] all resolve to "HIPAA".
        # Validate each token against the canonical set; reject unknown tokens.
        self.regulatory_scope = [s.strip().upper() for s in self.regulatory_scope]
        unknown_scopes = [
            s for s in self.regulatory_scope
            if s not in self.CANONICAL_REGULATORY_SCOPES
        ]
        for unknown in unknown_scopes:
            msg = (
                f"regulatory_scope contains unrecognized scope token '{unknown}'. "
                f"Recognized tokens: {sorted(self.CANONICAL_REGULATORY_SCOPES)}. "
                "This token will have no effect — verify it is not a typo."
            )
            if self.strict_entity_validation:
                raise ValueError(msg)
            logger.warning("WARN: %s", msg)

        # REQ-012: No entity type may appear in both lists.
        overlap = set(self.strong_anchors) & set(self.quasi_identifiers)
        if overlap:
            raise ValueError(
                f"Entity type(s) appear in both strong_anchors and quasi_identifiers: "
                f"{sorted(overlap)}. Remove from one list and restart."
            )

        # REQ-011 rule 2: Duplicate check within each list.
        for field_name, entity_list in [
            ("strong_anchors", self.strong_anchors),
            ("quasi_identifiers", self.quasi_identifiers),
        ]:
            seen: set[str] = set()
            duplicates: list[str] = []
            for entity in entity_list:
                if entity in seen:
                    duplicates.append(entity)
                seen.add(entity)
            if duplicates:
                raise ValueError(
                    f"{field_name} contains duplicate entity type(s): {sorted(set(duplicates))}. "
                    "Remove the duplicate(s) and restart."
                )

        # REQ-011 rule 3: Canonical-set check (FAIL-005).
        for field_name, entity_list in [
            ("strong_anchors", self.strong_anchors),
            ("quasi_identifiers", self.quasi_identifiers),
        ]:
            for entity in entity_list:
                if entity not in CANONICAL_ENTITY_TYPES:
                    msg = (
                        f"{field_name} contains unrecognized entity type '{entity}' — "
                        f"it will never match a Presidio result; likely a typo"
                    )
                    if self.strict_entity_validation:
                        raise ValueError(msg)
                    logger.warning("WARN: %s", msg)

        # REQ-020: HIPAA incompatibility gate.
        if "HIPAA" in self.regulatory_scope:
            if self.closed_world_filtering:
                raise ValueError(
                    "closed_world_filtering: true is incompatible with regulatory_scope: "
                    f"{self.regulatory_scope!r}. HIPAA Safe Harbor requires unconditional "
                    "date removal; the closed-world filter suppresses DATE_TIME only when no "
                    "anchor is present, which does not satisfy Safe Harbor requirements. "
                    "Set closed_world_filtering: false or remove \"HIPAA\" from regulatory_scope."
                )
            # Auto-force allow_per_request_closed_world_override to false under HIPAA.
            if self.allow_per_request_closed_world_override:
                logger.info(
                    "INFO: regulatory_scope includes HIPAA — per-request closed_world_filtering "
                    "overrides are forcibly disabled (allow_per_request_closed_world_override set "
                    "to false). HIPAA Safe Harbor compliance requires that per-request relaxation "
                    "of PII controls is not possible."
                )
                self.allow_per_request_closed_world_override = False

        # SEC-001a: Log when override gate is disabled explicitly.
        elif not self.allow_per_request_closed_world_override:
            logger.info(
                "INFO: allow_per_request_closed_world_override: false — per-request "
                "closed_world_filtering overrides are disabled; instance default will always be used."
            )

        # EDGE-008 degenerate-configuration warning.
        if self.closed_world_filtering and not self.strong_anchors:
            logger.warning(
                "WARN: closed_world_filtering is true but strong_anchors is empty — every "
                "submission will suppress all quasi-identifiers regardless of content. This is "
                "likely a misconfiguration. To disable closed-world filtering, set "
                "closed_world_filtering: false instead of clearing strong_anchors."
            )

        # PERF-001: Pre-compute frozensets once at config-load.
        self.strong_anchors_set = frozenset(self.strong_anchors)
        self.quasi_identifiers_set = frozenset(self.quasi_identifiers)

        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence (highest first):
        #   init args > env vars > .env > config.yaml > class defaults
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlConfigSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()
