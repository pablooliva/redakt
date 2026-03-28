"""Unit tests for src/redakt/services/anonymizer.py"""

from redakt.services.anonymizer import (
    anonymize_entities,
    generate_placeholders,
    replace_entities,
    resolve_overlaps,
)


class TestResolveOverlaps:
    def test_no_overlaps(self):
        entities = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.9},
            {"entity_type": "EMAIL_ADDRESS", "start": 20, "end": 35, "score": 1.0},
        ]
        result = resolve_overlaps(entities)
        assert len(result) == 2

    def test_higher_score_wins(self):
        entities = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.6},
            {"entity_type": "ORGANIZATION", "start": 5, "end": 15, "score": 0.9},
        ]
        result = resolve_overlaps(entities)
        assert len(result) == 1
        assert result[0]["entity_type"] == "ORGANIZATION"

    def test_equal_score_longer_span_wins(self):
        entities = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.85},
            {"entity_type": "ORGANIZATION", "start": 2, "end": 15, "score": 0.85},
        ]
        result = resolve_overlaps(entities)
        assert len(result) == 1
        assert result[0]["entity_type"] == "ORGANIZATION"  # span=13 > span=10

    def test_adjacent_entities_not_overlapping(self):
        """end_a == start_b means adjacent, NOT overlapping."""
        entities = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.9},
            {"entity_type": "ORGANIZATION", "start": 10, "end": 20, "score": 0.9},
        ]
        result = resolve_overlaps(entities)
        assert len(result) == 2

    def test_multiple_overlaps_resolved(self):
        entities = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.9},
            {"entity_type": "ORGANIZATION", "start": 5, "end": 15, "score": 0.7},
            {"entity_type": "LOCATION", "start": 8, "end": 18, "score": 0.5},
        ]
        result = resolve_overlaps(entities)
        # PERSON (0.9) wins over ORG (0.7, overlaps). LOCATION overlaps both PERSON and ORG.
        # PERSON accepted first. ORG overlaps PERSON -> discarded. LOCATION overlaps PERSON -> discarded.
        assert len(result) == 1
        assert result[0]["entity_type"] == "PERSON"

    def test_non_overlapping_after_discard(self):
        entities = [
            {"entity_type": "PERSON", "start": 0, "end": 5, "score": 0.9},
            {"entity_type": "ORGANIZATION", "start": 3, "end": 8, "score": 0.7},
            {"entity_type": "EMAIL_ADDRESS", "start": 20, "end": 35, "score": 1.0},
        ]
        result = resolve_overlaps(entities)
        # EMAIL doesn't overlap with anything, PERSON wins over ORG
        assert len(result) == 2
        types = {e["entity_type"] for e in result}
        assert types == {"PERSON", "EMAIL_ADDRESS"}

    def test_empty_entities(self):
        assert resolve_overlaps([]) == []

    def test_single_entity(self):
        entities = [{"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.9}]
        result = resolve_overlaps(entities)
        assert len(result) == 1


class TestGeneratePlaceholders:
    def _make_entity(self, entity_type, original_text, start=0, end=0, score=0.9):
        return {
            "entity_type": entity_type,
            "start": start,
            "end": end,
            "score": score,
            "original_text": original_text,
        }

    def test_single_entity(self):
        entities = [self._make_entity("PERSON", "John Smith")]
        mappings, emap = generate_placeholders(entities)
        assert mappings == {"<PERSON_1>": "John Smith"}
        assert emap[0] == "<PERSON_1>"

    def test_same_value_same_type_same_placeholder(self):
        """REQ-002: Duplicate PII value + same type -> single placeholder."""
        entities = [
            self._make_entity("PERSON", "John Smith"),
            self._make_entity("PERSON", "John Smith"),
            self._make_entity("PERSON", "John Smith"),
        ]
        mappings, emap = generate_placeholders(entities)
        assert mappings == {"<PERSON_1>": "John Smith"}
        assert emap[0] == "<PERSON_1>"
        assert emap[1] == "<PERSON_1>"
        assert emap[2] == "<PERSON_1>"

    def test_different_values_different_placeholders(self):
        entities = [
            self._make_entity("PERSON", "John Smith"),
            self._make_entity("PERSON", "Jane Doe"),
        ]
        mappings, emap = generate_placeholders(entities)
        assert mappings == {"<PERSON_1>": "John Smith", "<PERSON_2>": "Jane Doe"}

    def test_same_value_different_type_different_placeholder(self):
        """REQ-003: Same value + different type -> different placeholders."""
        entities = [
            self._make_entity("ORGANIZATION", "Amazon"),
            self._make_entity("LOCATION", "Amazon"),
        ]
        mappings, emap = generate_placeholders(entities)
        assert "<ORGANIZATION_1>" in mappings
        assert "<LOCATION_1>" in mappings
        assert mappings["<ORGANIZATION_1>"] == "Amazon"
        assert mappings["<LOCATION_1>"] == "Amazon"

    def test_counter_per_type_starts_at_1(self):
        """REQ-004: Counter is per entity type, starting at 1."""
        entities = [
            self._make_entity("PERSON", "John Smith"),
            self._make_entity("EMAIL_ADDRESS", "john@example.com"),
            self._make_entity("PERSON", "Jane Doe"),
        ]
        mappings, emap = generate_placeholders(entities)
        assert emap[0] == "<PERSON_1>"
        assert emap[1] == "<EMAIL_ADDRESS_1>"
        assert emap[2] == "<PERSON_2>"

    def test_empty_entities(self):
        mappings, emap = generate_placeholders([])
        assert mappings == {}
        assert emap == {}

    def test_many_entities_same_type(self):
        entities = [self._make_entity("PERSON", f"Person {i}") for i in range(5)]
        mappings, emap = generate_placeholders(entities)
        assert len(mappings) == 5
        for i in range(5):
            assert emap[i] == f"<PERSON_{i + 1}>"


class TestReplaceEntities:
    def test_single_replacement(self):
        text = "My name is John Smith and I live here."
        entities = [
            {"entity_type": "PERSON", "start": 11, "end": 21, "score": 0.9, "original_text": "John Smith"},
        ]
        result = replace_entities(text, entities, {0: "<PERSON_1>"})
        assert result == "My name is <PERSON_1> and I live here."

    def test_multiple_replacements_preserve_indices(self):
        text = "Contact John Smith at john@example.com please."
        entities = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.9, "original_text": "John Smith"},
            {"entity_type": "EMAIL_ADDRESS", "start": 22, "end": 38, "score": 1.0, "original_text": "john@example.com"},
        ]
        result = replace_entities(text, entities, {0: "<PERSON_1>", 1: "<EMAIL_ADDRESS_1>"})
        assert result == "Contact <PERSON_1> at <EMAIL_ADDRESS_1> please."

    def test_replacement_order_does_not_corrupt(self):
        """Reverse position order prevents index corruption."""
        text = "AB CD EF"
        entities = [
            {"entity_type": "X", "start": 0, "end": 2, "score": 0.9, "original_text": "AB"},
            {"entity_type": "Y", "start": 3, "end": 5, "score": 0.9, "original_text": "CD"},
            {"entity_type": "Z", "start": 6, "end": 8, "score": 0.9, "original_text": "EF"},
        ]
        result = replace_entities(text, entities, {0: "<X_1>", 1: "<Y_1>", 2: "<Z_1>"})
        assert result == "<X_1> <Y_1> <Z_1>"

    def test_empty_entities(self):
        assert replace_entities("hello", [], {}) == "hello"


class TestAnonymizeEntities:
    def test_full_pipeline(self):
        text = "Please review John Smith's contract. His email is john@example.com."
        analyzer_results = [
            {"entity_type": "PERSON", "start": 14, "end": 24, "score": 0.85},
            {"entity_type": "EMAIL_ADDRESS", "start": 50, "end": 66, "score": 1.0},
        ]
        anonymized, mappings, entity_types = anonymize_entities(text, analyzer_results)
        assert anonymized == "Please review <PERSON_1>'s contract. His email is <EMAIL_ADDRESS_1>."
        assert mappings == {
            "<PERSON_1>": "John Smith",
            "<EMAIL_ADDRESS_1>": "john@example.com",
        }

    def test_empty_results(self):
        """REQ-006: No PII -> original text + empty mapping."""
        text = "The weather is nice today."
        anonymized, mappings, entity_types = anonymize_entities(text, [])
        assert anonymized == text
        assert mappings == {}
        assert entity_types == []

    def test_duplicate_values_single_placeholder(self):
        """EDGE-001: Same value appears multiple times -> same placeholder."""
        text = "John Smith met John Smith at the John Smith memorial."
        analyzer_results = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.9},
            {"entity_type": "PERSON", "start": 15, "end": 25, "score": 0.9},
            {"entity_type": "PERSON", "start": 33, "end": 43, "score": 0.9},
        ]
        anonymized, mappings, entity_types = anonymize_entities(text, analyzer_results)
        assert anonymized == "<PERSON_1> met <PERSON_1> at the <PERSON_1> memorial."
        assert mappings == {"<PERSON_1>": "John Smith"}

    def test_overlap_resolution_in_pipeline(self):
        """EDGE-002: Overlapping entities resolved before replacement."""
        text = "Visit Amazon headquarters."
        analyzer_results = [
            {"entity_type": "ORGANIZATION", "start": 6, "end": 12, "score": 0.9},
            {"entity_type": "LOCATION", "start": 6, "end": 12, "score": 0.7},
        ]
        anonymized, mappings, entity_types = anonymize_entities(text, analyzer_results)
        # ORGANIZATION wins (higher score)
        assert "<ORGANIZATION_1>" in anonymized
        assert "<LOCATION_1>" not in anonymized
        assert len(mappings) == 1

    def test_mixed_types_and_duplicates(self):
        text = "Email john@acme.com about John. Then email john@acme.com again."
        analyzer_results = [
            {"entity_type": "EMAIL_ADDRESS", "start": 6, "end": 19, "score": 1.0},
            {"entity_type": "PERSON", "start": 26, "end": 30, "score": 0.85},
            {"entity_type": "EMAIL_ADDRESS", "start": 43, "end": 56, "score": 1.0},
        ]
        anonymized, mappings, entity_types = anonymize_entities(text, analyzer_results)
        assert anonymized == "Email <EMAIL_ADDRESS_1> about <PERSON_1>. Then email <EMAIL_ADDRESS_1> again."
        assert mappings == {
            "<EMAIL_ADDRESS_1>": "john@acme.com",
            "<PERSON_1>": "John",
        }

    def test_placeholder_numbering_by_position_not_score(self):
        """Finding #1: Placeholders should be numbered left-to-right by text position,
        not by Presidio confidence score."""
        text = "Contact Jane Doe at jane@acme.com about John Smith today."
        analyzer_results = [
            {"entity_type": "PERSON", "start": 8, "end": 16, "score": 0.7},
            {"entity_type": "EMAIL_ADDRESS", "start": 20, "end": 33, "score": 1.0},
            {"entity_type": "PERSON", "start": 40, "end": 50, "score": 0.9},
        ]
        anonymized, mappings, entity_types = anonymize_entities(text, analyzer_results)
        # Jane Doe appears first in text -> PERSON_1, John Smith second -> PERSON_2
        assert anonymized == "Contact <PERSON_1> at <EMAIL_ADDRESS_1> about <PERSON_2> today."
        assert mappings["<PERSON_1>"] == "Jane Doe"
        assert mappings["<PERSON_2>"] == "John Smith"
        assert entity_types == ["EMAIL_ADDRESS", "PERSON"]
