"""Core anonymization logic: overlap resolution, placeholder generation, text replacement."""


def resolve_overlaps(entities: list[dict]) -> list[dict]:
    """Remove cross-type overlapping entities.

    Resolution order: higher score wins, longer span breaks ties,
    then first-encountered (stable sort).

    Two entities overlap when start_a < end_b AND start_b < end_a.
    Adjacent entities (end_a == start_b) do NOT overlap.
    """
    # Sort by score desc, then span length desc (stable sort preserves input order for ties)
    sorted_entities = sorted(
        entities,
        key=lambda e: (e["score"], e["end"] - e["start"]),
        reverse=True,
    )

    accepted: list[dict] = []
    for entity in sorted_entities:
        overlaps = False
        for kept in accepted:
            if entity["start"] < kept["end"] and kept["start"] < entity["end"]:
                overlaps = True
                break
        if not overlaps:
            accepted.append(entity)

    return accepted


def generate_placeholders(
    entities: list[dict],
) -> tuple[dict[str, str], dict[int, str]]:
    """Assign numbered placeholders to entities.

    Key: (entity_type, original_text) -> same placeholder.
    Counter is per entity type, starting at 1.

    Returns:
        mappings: {"<PERSON_1>": "John Smith", ...}
        entity_placeholder_map: {entity_index: "<PERSON_1>", ...} keyed by index in input list
    """
    # Track (entity_type, text) -> placeholder
    seen: dict[tuple[str, str], str] = {}
    # Counter per entity type
    counters: dict[str, int] = {}
    # Mapping: placeholder -> original value
    mappings: dict[str, str] = {}
    # Which placeholder each entity gets (by list index)
    entity_placeholder_map: dict[int, str] = {}

    for i, entity in enumerate(entities):
        entity_type = entity["entity_type"]
        original_text = entity["original_text"]
        key = (entity_type, original_text)

        if key in seen:
            entity_placeholder_map[i] = seen[key]
        else:
            counter = counters.get(entity_type, 0) + 1
            counters[entity_type] = counter
            placeholder = f"<{entity_type}_{counter}>"
            seen[key] = placeholder
            mappings[placeholder] = original_text
            entity_placeholder_map[i] = placeholder

    return mappings, entity_placeholder_map


def replace_entities(
    text: str,
    entities: list[dict],
    entity_placeholder_map: dict[int, str],
) -> str:
    """Replace entity spans with placeholders, processing in reverse position order."""
    # Sort by start position descending to preserve indices during replacement
    indexed = sorted(enumerate(entities), key=lambda ie: ie[1]["start"], reverse=True)

    result = text
    for i, entity in indexed:
        placeholder = entity_placeholder_map[i]
        result = result[: entity["start"]] + placeholder + result[entity["end"] :]

    return result


def anonymize_entities(
    text: str, analyzer_results: list[dict]
) -> tuple[str, dict[str, str], list[str]]:
    """Full anonymization pipeline: resolve overlaps, generate placeholders, replace text.

    Args:
        text: Original text.
        analyzer_results: Presidio Analyzer results (list of dicts with
            entity_type, start, end, score).

    Returns:
        (anonymized_text, mappings, entity_types) where:
        - mappings is {"<TYPE_N>": "original_value", ...}
        - entity_types is sorted list of unique entity type names found
    """
    if not analyzer_results:
        return text, {}, []

    # Enrich entities with their original text from the source
    entities = []
    for r in analyzer_results:
        entity = dict(r)
        entity["original_text"] = text[r["start"] : r["end"]]
        entities.append(entity)

    # Step 1: Resolve cross-type overlaps
    resolved = resolve_overlaps(entities)

    # Step 2: Sort by text position so placeholder numbering is left-to-right
    resolved.sort(key=lambda e: e["start"])

    # Step 3: Generate numbered placeholders
    mappings, entity_placeholder_map = generate_placeholders(resolved)

    # Step 4: Replace text (reverse position order)
    anonymized = replace_entities(text, resolved, entity_placeholder_map)

    # Collect unique entity types from resolved entities
    entity_types = sorted(set(e["entity_type"] for e in resolved))

    return anonymized, mappings, entity_types
