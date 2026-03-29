"""Pydantic models for document upload endpoints."""

from pydantic import BaseModel


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
    source_format: str
    metadata: DocumentMetadata
