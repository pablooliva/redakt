"""Shared utility functions for allow list parsing, validation, and merging."""

from __future__ import annotations

import logging

logger = logging.getLogger("redakt")

# Validation constants
MAX_ALLOW_LIST_TERMS = 100
MAX_ALLOW_LIST_TERM_LENGTH = 200
INSTANCE_ALLOW_LIST_WARN_THRESHOLD = 500


def parse_comma_separated(raw: str | None) -> list[str] | None:
    """Parse a comma-separated string into a list of stripped, non-empty strings.

    Returns None if input is None/empty or no valid items remain.
    """
    if not raw:
        return None
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items if items else None


def parse_allow_list(raw: str) -> list[str]:
    """Parse a comma-separated allow list string for web UI input.

    Returns [] (not None) for empty input, since allow-list-specific
    validation and merge handle the empty case.
    """
    result = parse_comma_separated(raw)
    return result if result is not None else []


def validate_allow_list(
    terms: list[str],
    max_terms: int = MAX_ALLOW_LIST_TERMS,
    max_term_length: int = MAX_ALLOW_LIST_TERM_LENGTH,
) -> None:
    """Validate per-request allow list terms. Raises ValueError on violation.

    Validation is fail-closed: the entire request is rejected on any violation.
    No truncation or partial processing.
    """
    if not terms:
        return

    if len(terms) > max_terms:
        raise ValueError(f"Allow list exceeds maximum of {max_terms} terms.")

    for term in terms:
        if len(term) > max_term_length:
            raise ValueError(
                f"Allow list term exceeds maximum length of {max_term_length} characters."
            )


def merge_allow_lists(
    instance_list: list[str],
    per_request_list: list[str] | None,
) -> list[str] | None:
    """Merge instance-wide and per-request allow lists with order-preserving deduplication.

    Order: instance terms first, per-request appended, duplicates removed
    while preserving first-seen order via dict.fromkeys().

    Returns None if the result is empty (Presidio treats None as
    "skip allow list filtering entirely").
    """
    combined: list[str] = list(instance_list)
    if per_request_list:
        combined.extend(per_request_list)

    if not combined:
        return None

    # Order-preserving deduplication
    deduped = list(dict.fromkeys(combined))
    return deduped if deduped else None


def merge_entity_thresholds(
    instance_map: dict[str, float],
    per_request_map: dict[str, float] | None,
) -> dict[str, float]:
    """Merge instance-wide and per-request entity score floors.

    Per-request keys override instance keys.
    """
    merged = dict(instance_map)
    if per_request_map:
        merged.update(per_request_map)
    return merged


def filter_by_entity_thresholds(
    results: list[dict],
    thresholds: dict[str, float],
) -> list[dict]:
    """Drop analyzer results whose entity_type has a per-entity floor and whose score is below it.

    Entity types not present in `thresholds` are unaffected (they're already
    above the global score_threshold that Presidio applied).
    """
    if not thresholds:
        return results
    return [r for r in results if r["score"] >= thresholds.get(r["entity_type"], 0.0)]


def filter_by_closed_world(
    results: list[dict],
    enabled: bool,
    strong_anchors: frozenset[str],
    quasi_identifiers: frozenset[str],
) -> tuple[list[dict], int]:
    """Filter quasi-identifier spans when no strong anchor is present.

    Returns a tuple of (filtered_results, suppressed_count).
    - filtered_results: spans to emit (input unchanged when enabled=False or anchor present)
    - suppressed_count: number of spans dropped by the closed-world rule (0 if disabled)

    When enabled=False, returns (results, 0) immediately — O(1) no-op (PERF-002).

    Parameters `strong_anchors` and `quasi_identifiers` are pre-computed frozenset
    values from Settings.strong_anchors_set / Settings.quasi_identifiers_set (PERF-001).
    The caller must not pass raw list[str].
    """
    if not enabled:
        return results, 0

    # O(n) single pass: check anchor presence and collect quasi-identifier spans.
    has_anchor = any(r["entity_type"] in strong_anchors for r in results)

    if has_anchor:
        # Anchor present: all spans pass through unchanged (REQ-008).
        return results, 0

    # No anchor: suppress quasi-identifier spans (REQ-007).
    filtered: list[dict] = []
    suppressed_count = 0
    for r in results:
        if r["entity_type"] in quasi_identifiers:
            suppressed_count += 1
        else:
            filtered.append(r)

    return filtered, suppressed_count


def validate_instance_allow_list(allow_list: list[str]) -> list[str]:
    """Validate instance-wide allow list at startup. Logs warnings but never blocks startup.

    Returns a cleaned list with empty strings stripped (FAIL-002).
    """
    if not allow_list:
        return allow_list

    # Warn about and strip empty strings (after strip)
    empty_count = sum(1 for term in allow_list if not term.strip())
    if empty_count:
        logger.warning(
            "Instance-wide allow list contains %d empty string(s). "
            "These will be stripped from the list.",
            empty_count,
        )

    # Strip empty strings from the list
    cleaned = [term for term in allow_list if term.strip()]

    # Warn about overly long terms
    for term in cleaned:
        if len(term) > MAX_ALLOW_LIST_TERM_LENGTH:
            logger.warning(
                "Instance-wide allow list contains a term exceeding %d characters. "
                "This may impact performance.",
                MAX_ALLOW_LIST_TERM_LENGTH,
            )
            break  # One warning is enough

    # Performance advisory for large lists
    if len(cleaned) > INSTANCE_ALLOW_LIST_WARN_THRESHOLD:
        logger.warning(
            "Instance-wide allow list contains %d terms (exceeds %d). "
            "Large allow lists may impact Presidio performance.",
            len(cleaned),
            INSTANCE_ALLOW_LIST_WARN_THRESHOLD,
        )

    return cleaned
