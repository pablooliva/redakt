import os
from pathlib import Path
from typing import Any

import yaml
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

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

    model_config = {
        "env_prefix": "REDAKT_",
        "env_nested_delimiter": "__",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

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
