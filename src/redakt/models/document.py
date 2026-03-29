"""Pydantic models for document upload endpoints."""

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    pages_processed: int | None = None
    cells_processed: int | None = None
    sheets_processed: int | None = None
    chunks_analyzed: int
    file_size_bytes: int
    warnings: list[str] = []


class DocumentUploadResponse(BaseModel):
    anonymized_content: str | None = None
    anonymized_structured: dict | list | None = None
    mappings: dict[str, str]
    language_detected: str
    language_confidence: float | None = Field(
        default=None,
        description=(
            "Confidence score for the detected language. For documents, this "
            "reflects the sampled portion (first ~5KB), not the full document."
        ),
    )
    source_format: str
    metadata: DocumentMetadata
