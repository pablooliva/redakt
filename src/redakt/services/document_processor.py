"""Document processing pipeline: extract, analyze, build unified map, replace."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging

from redakt.config import settings
from redakt.services.anonymizer import replace_entities, resolve_overlaps
from redakt.services.extractors import (
    EXTRACTORS,
    ExtractionError,
    ExtractionResult,
    TextChunk,
    _col_num_to_letter,
)
from redakt.services.language import detect_language
from redakt.services.presidio import PresidioClient

logger = logging.getLogger("redakt")


class DocumentProcessingError(Exception):
    """Raised when document processing fails."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

# Magic bytes for binary formats
MAGIC_BYTES = {
    ".pdf": b"%PDF-",
    ".xlsx": b"PK\x03\x04",
    ".docx": b"PK\x03\x04",
}

# Text-based formats that don't need magic byte checks
TEXT_FORMATS = {".txt", ".md", ".csv", ".json", ".xml", ".html", ".rtf"}

# Formats returning anonymized_content (string)
CONTENT_FORMATS = {".txt", ".md", ".rtf", ".pdf", ".docx", ".xml", ".html", ".csv"}

# Formats returning anonymized_structured (object)
STRUCTURED_FORMATS = {".json", ".xlsx"}


def validate_file(
    raw: bytes,
    extension: str,
    file_size: int,
) -> None:
    """Validate file before processing: size, extension, magic bytes."""
    # Size check
    if file_size > settings.max_file_size:
        raise DocumentProcessingError(
            f"File exceeds the maximum size of {settings.max_file_size // (1024 * 1024)}MB. "
            "Please upload a smaller file.",
            status_code=413,
        )

    # Extension check
    if extension not in settings.supported_file_types:
        if not extension:
            raise DocumentProcessingError(
                "Unsupported file format. Supported formats: "
                + ", ".join(settings.supported_file_types),
                status_code=400,
            )
        raise DocumentProcessingError(
            f"Unsupported file format '{extension}'. Supported formats: "
            + ", ".join(settings.supported_file_types),
            status_code=400,
        )

    # Magic bytes check for binary formats
    if extension in MAGIC_BYTES:
        expected = MAGIC_BYTES[extension]
        if not raw[:len(expected)] == expected:
            raise DocumentProcessingError(
                f"The file content does not match the expected format for '{extension}'. "
                "The file may be corrupted or mislabeled.",
                status_code=400,
            )


# ---------------------------------------------------------------------------
# Unified placeholder mapping
# ---------------------------------------------------------------------------

def build_unified_placeholder_map(
    all_chunk_entities: list[list[dict]],
) -> tuple[dict[str, str], list[dict[int, str]]]:
    """Build a single placeholder map across all chunks.

    Returns:
        global_mappings: {"<PERSON_1>": "John Smith", ...}
        per_chunk_placeholder_maps: list of {entity_index: placeholder} dicts per chunk
    """
    counters: dict[str, int] = {}  # entity_type -> next number
    seen: dict[tuple[str, str], str] = {}  # (entity_type, text) -> placeholder
    global_mappings: dict[str, str] = {}
    per_chunk_maps: list[dict[int, str]] = []

    for chunk_entities in all_chunk_entities:
        chunk_map: dict[int, str] = {}
        for i, entity in enumerate(chunk_entities):
            key = (entity["entity_type"], entity["original_text"])
            if key not in seen:
                entity_type = entity["entity_type"]
                counters[entity_type] = counters.get(entity_type, 0) + 1
                placeholder = f"<{entity_type}_{counters[entity_type]}>"
                seen[key] = placeholder
                global_mappings[placeholder] = entity["original_text"]
            chunk_map[i] = seen[key]
        per_chunk_maps.append(chunk_map)

    return global_mappings, per_chunk_maps


# ---------------------------------------------------------------------------
# Language detection for documents
# ---------------------------------------------------------------------------

async def detect_document_language(
    chunks: list[TextChunk], language: str
) -> tuple[str, float | None]:
    """Detect language once for the entire document.

    If language is "auto", concatenate first chunks up to 5KB and detect.
    Returns (language, confidence) tuple.
    """
    if language != "auto":
        if language not in settings.supported_languages:
            raise DocumentProcessingError(
                f"Language '{language}' is not supported. "
                f"Supported languages: {', '.join(settings.supported_languages)}",
                status_code=400,
            )
        return language, None  # Manual override, no confidence

    # Accumulate text sample from chunks (up to 5KB)
    sample_parts: list[str] = []
    accumulated = 0
    for chunk in chunks:
        if chunk.text.strip():
            sample_parts.append(chunk.text)
            accumulated += len(chunk.text)
            if accumulated >= 5000:
                break

    if not sample_parts:
        fallback = settings.language_detection_fallback
        return fallback, None  # Fallback for empty documents

    sample = " ".join(sample_parts)[:5000]
    detection = await detect_language(sample)

    if detection.language not in settings.supported_languages:
        raise DocumentProcessingError(
            f"Language '{detection.language}' is not supported. "
            f"Supported languages: {', '.join(settings.supported_languages)}",
            status_code=400,
        )

    return detection.language, detection.confidence


# ---------------------------------------------------------------------------
# Core processing pipeline
# ---------------------------------------------------------------------------

async def process_document(
    raw: bytes,
    extension: str,
    file_size: int,
    presidio: PresidioClient,
    language: str = "auto",
    score_threshold: float | None = None,
    entities: list[str] | None = None,
    allow_list: list[str] | None = None,
) -> dict:
    """Full document processing pipeline.

    Returns a dict suitable for DocumentUploadResponse construction.
    """
    threshold = score_threshold if score_threshold is not None else settings.default_score_threshold

    # Step 1: Validate file
    validate_file(raw, extension, file_size)

    # Step 2: Extract text
    extractor = EXTRACTORS[extension]
    try:
        extraction = extractor(raw)
    except ExtractionError:
        raise  # Re-raise — these have proper status codes
    except Exception:
        raise DocumentProcessingError(
            "The file could not be parsed. It may be corrupted or in an unsupported variant.",
            status_code=422,
        )

    warnings = list(extraction.warnings)

    # Step 3: Filter empty chunks
    non_empty_chunks = [c for c in extraction.chunks if c.text.strip()]

    if not non_empty_chunks:
        return _build_empty_response(extension, file_size, extraction, warnings)

    # Step 3b: Handle oversized chunks (EDGE-013)
    valid_chunks: list[TextChunk] = []
    skipped_indices: set[int] = set()
    for i, chunk in enumerate(non_empty_chunks):
        if len(chunk.text) > settings.max_text_length:
            skipped_indices.add(i)
            warnings.append(
                "One or more chunks exceeded the maximum text size (512KB) and were skipped."
            )
        else:
            valid_chunks.append(chunk)

    # Deduplicate warnings
    warnings = list(dict.fromkeys(warnings))

    # Step 4: Detect language
    resolved_language, language_confidence = await detect_document_language(valid_chunks, language)

    # Step 5: Merge allow lists
    merged_allow_list = list(settings.allow_list)
    if allow_list:
        merged_allow_list.extend(allow_list)

    # Step 6: Analyze all chunks concurrently via Presidio
    semaphore = asyncio.Semaphore(10)

    async def analyze_chunk(chunk: TextChunk) -> list[dict]:
        async with semaphore:
            results = await presidio.analyze(
                text=chunk.text,
                language=resolved_language,
                score_threshold=threshold,
                entities=entities,
                allow_list=merged_allow_list or None,
            )
            resolved = resolve_overlaps(results)
            # Enrich with original_text
            for r in resolved:
                r["original_text"] = chunk.text[r["start"]:r["end"]]
            # Sort by position for consistent numbering
            resolved.sort(key=lambda e: e["start"])
            return resolved

    all_chunk_entities = await asyncio.gather(
        *[analyze_chunk(c) for c in valid_chunks]
    )

    # Step 7: Build unified placeholder map
    global_mappings, per_chunk_maps = build_unified_placeholder_map(
        list(all_chunk_entities)
    )

    # Step 8: Apply replacements per chunk
    anonymized_chunks: list[str] = []
    for i, (chunk, chunk_entities, chunk_map) in enumerate(
        zip(valid_chunks, all_chunk_entities, per_chunk_maps)
    ):
        anonymized_text = replace_entities(chunk.text, chunk_entities, chunk_map)
        anonymized_chunks.append(anonymized_text)

    # Step 9: Reassemble output
    entity_types = sorted(set(
        e["entity_type"]
        for chunk_ents in all_chunk_entities
        for e in chunk_ents
    ))

    result = _reassemble_output(
        extension=extension,
        valid_chunks=valid_chunks,
        non_empty_chunks=non_empty_chunks,
        skipped_indices=skipped_indices,
        anonymized_chunks=anonymized_chunks,
        extraction=extraction,
        global_mappings=global_mappings,
        resolved_language=resolved_language,
        language_confidence=language_confidence,
        file_size=file_size,
        warnings=warnings,
        entity_types=entity_types,
    )

    return result


def _build_empty_response(
    extension: str,
    file_size: int,
    extraction: ExtractionResult,
    warnings: list[str],
) -> dict:
    """Build response for documents with no extractable text."""
    fallback = settings.language_detection_fallback
    if extension == ".xlsx":
        return {
            "anonymized_content": None,
            "anonymized_structured": {},
            "mappings": {},
            "language_detected": fallback,
            "language_confidence": None,
            "source_format": extension.lstrip("."),
            "metadata": {
                "pages_processed": None,
                "cells_processed": 0,
                "sheets_processed": extraction.metadata.get("sheets_processed", 0),
                "chunks_analyzed": 0,
                "file_size_bytes": file_size,
                "warnings": warnings,
            },
            "entity_types": [],
        }
    elif extension == ".json":
        return {
            "anonymized_content": None,
            "anonymized_structured": extraction.metadata.get("original_structure"),
            "mappings": {},
            "language_detected": fallback,
            "language_confidence": None,
            "source_format": extension.lstrip("."),
            "metadata": {
                "pages_processed": None,
                "cells_processed": None,
                "sheets_processed": None,
                "chunks_analyzed": 0,
                "file_size_bytes": file_size,
                "warnings": warnings,
            },
            "entity_types": [],
        }
    else:
        return {
            "anonymized_content": "",
            "anonymized_structured": None,
            "mappings": {},
            "language_detected": fallback,
            "language_confidence": None,
            "source_format": extension.lstrip("."),
            "metadata": {
                "pages_processed": extraction.metadata.get("pages_processed"),
                "cells_processed": extraction.metadata.get("cells_processed"),
                "sheets_processed": None,
                "chunks_analyzed": 0,
                "file_size_bytes": file_size,
                "warnings": warnings,
            },
            "entity_types": [],
        }


def _reassemble_output(
    extension: str,
    valid_chunks: list[TextChunk],
    non_empty_chunks: list[TextChunk],
    skipped_indices: set[int],
    anonymized_chunks: list[str],
    extraction: ExtractionResult,
    global_mappings: dict[str, str],
    resolved_language: str,
    language_confidence: float | None,
    file_size: int,
    warnings: list[str],
    entity_types: list[str],
) -> dict:
    """Reassemble anonymized chunks into the format-specific output."""
    source_format = extension.lstrip(".")
    chunks_analyzed = len(valid_chunks)

    if extension == ".csv":
        return _reassemble_csv(
            valid_chunks, anonymized_chunks, extraction, global_mappings,
            resolved_language, language_confidence, source_format, file_size,
            warnings, chunks_analyzed, entity_types,
        )
    elif extension == ".json":
        return _reassemble_json(
            valid_chunks, anonymized_chunks, extraction, global_mappings,
            resolved_language, language_confidence, source_format, file_size,
            warnings, chunks_analyzed, entity_types,
        )
    elif extension == ".xlsx":
        return _reassemble_xlsx(
            valid_chunks, non_empty_chunks, skipped_indices, anonymized_chunks,
            extraction, global_mappings, resolved_language, language_confidence,
            source_format, file_size, warnings, chunks_analyzed, entity_types,
        )
    else:
        # Plain text output: txt, md, rtf, pdf, docx, xml, html
        return _reassemble_text(
            valid_chunks, non_empty_chunks, skipped_indices, anonymized_chunks,
            extraction, global_mappings, resolved_language, language_confidence,
            source_format, file_size, warnings, chunks_analyzed, entity_types,
        )


def _reassemble_text(
    valid_chunks, non_empty_chunks, skipped_indices, anonymized_chunks,
    extraction, global_mappings, resolved_language, language_confidence,
    source_format, file_size, warnings, chunks_analyzed, entity_types,
) -> dict:
    """Reassemble plain text output."""
    # Rebuild text preserving skipped chunks
    parts: list[str] = []
    valid_idx = 0
    for i, chunk in enumerate(non_empty_chunks):
        if i in skipped_indices:
            parts.append("[CONTENT TOO LARGE - SKIPPED]")
        else:
            parts.append(anonymized_chunks[valid_idx])
            valid_idx += 1

    anonymized_content = "\n\n".join(parts) if len(parts) > 1 else (parts[0] if parts else "")

    return {
        "anonymized_content": anonymized_content,
        "anonymized_structured": None,
        "mappings": global_mappings,
        "language_detected": resolved_language,
        "language_confidence": language_confidence,
        "source_format": source_format,
        "metadata": {
            "pages_processed": extraction.metadata.get("pages_processed"),
            "cells_processed": extraction.metadata.get("cells_processed"),
            "sheets_processed": None,
            "chunks_analyzed": chunks_analyzed,
            "file_size_bytes": file_size,
            "warnings": warnings,
        },
        "entity_types": entity_types,
    }


def _reassemble_csv(
    valid_chunks, anonymized_chunks, extraction, global_mappings,
    resolved_language, language_confidence, source_format, file_size,
    warnings, chunks_analyzed, entity_types,
) -> dict:
    """Reassemble anonymized CSV text."""
    delimiter = extraction.metadata.get("delimiter", ",")

    # Build chunk_id -> anonymized text mapping
    chunk_map: dict[str, str] = {}
    for chunk, anon_text in zip(valid_chunks, anonymized_chunks):
        chunk_map[chunk.chunk_id] = anon_text

    # Rebuild CSV rows
    output = io.StringIO()
    writer = csv.writer(output, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")

    # Reconstruct from all original chunks (including empty ones)
    rows: dict[int, dict[int, str]] = {}
    for chunk in extraction.chunks:
        # Parse R{row}C{col} format
        parts = chunk.chunk_id.split("C")
        row_num = int(parts[0][1:])
        col_num = int(parts[1])
        if row_num not in rows:
            rows[row_num] = {}
        anon_text = chunk_map.get(chunk.chunk_id, chunk.text)
        rows[row_num][col_num] = anon_text

    for row_num in sorted(rows.keys()):
        row = rows[row_num]
        max_col = max(row.keys())
        csv_row = [row.get(c, "") for c in range(1, max_col + 1)]
        writer.writerow(csv_row)

    anonymized_content = output.getvalue()

    return {
        "anonymized_content": anonymized_content,
        "anonymized_structured": None,
        "mappings": global_mappings,
        "language_detected": resolved_language,
        "language_confidence": language_confidence,
        "source_format": source_format,
        "metadata": {
            "pages_processed": None,
            "cells_processed": extraction.metadata.get("cells_processed"),
            "sheets_processed": None,
            "chunks_analyzed": chunks_analyzed,
            "file_size_bytes": file_size,
            "warnings": warnings,
        },
        "entity_types": entity_types,
    }


def _reassemble_json(
    valid_chunks, anonymized_chunks, extraction, global_mappings,
    resolved_language, language_confidence, source_format, file_size,
    warnings, chunks_analyzed, entity_types,
) -> dict:
    """Reassemble anonymized JSON structure."""
    original_structure = extraction.metadata.get("original_structure")

    # Build path -> anonymized text mapping
    path_map: dict[str, str] = {}
    for chunk, anon_text in zip(valid_chunks, anonymized_chunks):
        path_map[chunk.chunk_id] = anon_text

    # Replace strings in structure
    anonymized_structure = _replace_json_strings(original_structure, "", path_map)

    return {
        "anonymized_content": None,
        "anonymized_structured": anonymized_structure,
        "mappings": global_mappings,
        "language_detected": resolved_language,
        "language_confidence": language_confidence,
        "source_format": source_format,
        "metadata": {
            "pages_processed": None,
            "cells_processed": None,
            "sheets_processed": None,
            "chunks_analyzed": chunks_analyzed,
            "file_size_bytes": file_size,
            "warnings": warnings,
        },
        "entity_types": entity_types,
    }


_MAX_JSON_DEPTH = 100


def _replace_json_strings(obj, path: str, path_map: dict[str, str], depth: int = 0):
    """Recursively replace string values in a JSON structure using the path map."""
    if depth > _MAX_JSON_DEPTH:
        return obj  # Bail out at max depth -- structure was already validated during extraction
    full_path = path or "$"
    if isinstance(obj, str):
        return path_map.get(full_path, obj)
    elif isinstance(obj, dict):
        return {
            key: _replace_json_strings(
                value,
                f"{path}.{key}" if path else f"$.{key}",
                path_map,
                depth + 1,
            )
            for key, value in obj.items()
        }
    elif isinstance(obj, list):
        return [
            _replace_json_strings(item, f"{path}[{i}]", path_map, depth + 1)
            for i, item in enumerate(obj)
        ]
    else:
        return obj  # numbers, booleans, None — preserve


def _reassemble_xlsx(
    valid_chunks, non_empty_chunks, skipped_indices, anonymized_chunks,
    extraction, global_mappings, resolved_language, language_confidence,
    source_format, file_size, warnings, chunks_analyzed, entity_types,
) -> dict:
    """Reassemble anonymized XLSX structure."""
    sheets_data = extraction.metadata.get("sheets_data", {})

    # Build chunk_id -> anonymized text mapping
    chunk_map: dict[str, str] = {}
    for chunk, anon_text in zip(valid_chunks, anonymized_chunks):
        chunk_map[chunk.chunk_id] = anon_text

    # Also handle skipped chunks
    valid_idx = 0
    for i, chunk in enumerate(non_empty_chunks):
        if i in skipped_indices:
            chunk_map[chunk.chunk_id] = "[CONTENT TOO LARGE - SKIPPED]"

    # Replace in sheets_data structure
    anonymized_sheets: dict[str, list] = {}
    for sheet_name, rows in sheets_data.items():
        anon_rows: list[list] = []
        for row_idx, row in enumerate(rows, start=1):
            anon_row: list = []
            for col_idx, cell_value in enumerate(row, start=1):
                if isinstance(cell_value, str) and cell_value.strip():
                    col_letter = _col_num_to_letter(col_idx)
                    chunk_id = f"{sheet_name}!{col_letter}{row_idx}"
                    anon_row.append(chunk_map.get(chunk_id, cell_value))
                else:
                    anon_row.append(cell_value)
            anon_rows.append(anon_row)
        anonymized_sheets[sheet_name] = anon_rows

    return {
        "anonymized_content": None,
        "anonymized_structured": anonymized_sheets,
        "mappings": global_mappings,
        "language_detected": resolved_language,
        "language_confidence": language_confidence,
        "source_format": source_format,
        "metadata": {
            "pages_processed": None,
            "cells_processed": extraction.metadata.get("cells_processed"),
            "sheets_processed": extraction.metadata.get("sheets_processed"),
            "chunks_analyzed": chunks_analyzed,
            "file_size_bytes": file_size,
            "warnings": warnings,
        },
        "entity_types": entity_types,
    }

