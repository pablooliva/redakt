from pathlib import Path

from pydantic_settings import BaseSettings

# Default: resolve from this file's location (works both installed and local)
_DEFAULT_BASE_DIR = str(Path(__file__).parent)


class Settings(BaseSettings):
    base_dir: str = _DEFAULT_BASE_DIR
    presidio_analyzer_url: str = "http://localhost:5001"
    presidio_anonymizer_url: str = "http://localhost:5001"
    default_score_threshold: float = 0.35
    default_language: str = "auto"
    supported_languages: list[str] = ["en", "de"]
    allow_list: list[str] = []
    max_text_length: int = 512_000  # ~500KB
    presidio_timeout: float = 30.0
    language_detection_timeout: float = 2.0
    log_level: str = "WARNING"

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

    model_config = {"env_prefix": "REDAKT_", "env_nested_delimiter": "__"}


settings = Settings()
