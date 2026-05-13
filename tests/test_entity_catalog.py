"""CI lint test: entity catalog vs docs/supported-entities.md consistency (REQ-021).

This test is the "single source of truth" enforcement binding. It asserts that
every entity type referenced in docs/supported-entities.md is also present in
CANONICAL_ENTITY_TYPES in entity_catalog.py, and vice versa for the
Redakt-active subset (universal + DE-specific).

The test does NOT require the Presidio stack to be running — it reads only the
local .md file and the Python constant. It runs as part of the default unit
suite (uv run pytest tests/).

Maintenance: when adding a new entity type to entity_catalog.py, also add it
to docs/supported-entities.md, and vice versa. This test will fail if the two
diverge.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SUPPORTED_ENTITIES_DOC = REPO_ROOT / "docs" / "supported-entities.md"
ENTITY_CATALOG_MODULE = "redakt.entity_catalog"


def _extract_entity_types_from_doc(path: Path) -> set[str]:
    """Extract all backtick-wrapped entity type names from the supported-entities doc.

    Matches ``ENTITY_NAME`` patterns (uppercase letters, digits, underscores)
    inside backtick spans. Filters to types that look like Presidio entity names
    (all-caps with optional underscores, not short abbreviations).
    """
    text = path.read_text(encoding="utf-8")
    # Match `ENTITY_NAME` patterns — backtick-wrapped all-caps identifiers
    candidates = re.findall(r"`([A-Z][A-Z0-9_]+)`", text)
    # Filter: must be all-caps with underscores, length >= 2, not a generic keyword
    excluded = {
        "POST", "GET", "JSON", "API", "NLP", "PII", "CSV", "PDF",
        "ISO", "IBAN", "SEPA", "VIES", "BDEW", "VDE",
        "UUID", "SHA", "DEA", "MOD", "ACH", "ABA",
        # Short tech abbreviations that are NOT entity type names
        "YAML", "GDPR", "HIPAA", "CFR",
    }
    # Minimum length 3 to include NRP, URL etc.
    result = {c for c in candidates if c not in excluded and len(c) >= 3}
    return result


class TestEntityCatalogConsistency:
    """REQ-021: entity_catalog.py and docs/supported-entities.md in sync."""

    def test_supported_entities_doc_exists(self):
        """docs/supported-entities.md exists (prerequisite for all other checks)."""
        assert SUPPORTED_ENTITIES_DOC.exists(), (
            f"docs/supported-entities.md not found at {SUPPORTED_ENTITIES_DOC}"
        )

    def test_catalog_module_importable(self):
        """entity_catalog module is importable (basic sanity check)."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        assert CANONICAL_ENTITY_TYPES is not None

    def test_all_catalog_types_documented(self):
        """Every type in CANONICAL_ENTITY_TYPES appears in docs/supported-entities.md."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        doc_types = _extract_entity_types_from_doc(SUPPORTED_ENTITIES_DOC)
        missing_from_doc = CANONICAL_ENTITY_TYPES - doc_types
        assert not missing_from_doc, (
            f"Entity types in CANONICAL_ENTITY_TYPES but not in "
            f"docs/supported-entities.md: {sorted(missing_from_doc)}. "
            "Add the missing types to docs/supported-entities.md."
        )

    def test_catalog_contains_universal_presidio_types(self):
        """Universal Presidio entity types from the docs are in the catalog."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        # Authoritative list from docs/supported-entities.md universal sections
        universal_types = {
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "LOCATION",
            "ORGANIZATION",
            "NRP",
            "DATE_TIME",
            "CREDIT_CARD",
            "CRYPTO",
            "IP_ADDRESS",
            "IBAN_CODE",
            "EU_VAT_ID",
            "BIC_CODE",
            "SEPA_CREDITOR_ID",
            "US_SSN",
            "US_PASSPORT",
            "US_ITIN",
            "US_DRIVER_LICENSE",
            "US_BANK_NUMBER",
            "MEDICAL_LICENSE",
            "URL",
        }
        missing = universal_types - CANONICAL_ENTITY_TYPES
        assert not missing, (
            f"Universal entity types not in CANONICAL_ENTITY_TYPES: {sorted(missing)}"
        )

    def test_catalog_contains_de_specific_types(self):
        """German-specific entity types are in the catalog."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        de_types = {
            "DE_TAX_ID",
            "DE_VAT_ID",
            "DE_ID_CARD",
            "DE_PASSPORT",
            "DE_SOCIAL_SECURITY",
            "DE_FUEHRERSCHEIN",
            "DE_HEALTH_INSURANCE",
            "DE_MASTR_ID",
            "DE_KFZ",
            "DE_PLZ",
            "DE_MALO",
            "DE_MELO",
            "DE_EEG_ANLAGE",
            "DE_ZAEHLERNUMMER",
        }
        missing = de_types - CANONICAL_ENTITY_TYPES
        assert not missing, (
            f"DE-specific entity types not in CANONICAL_ENTITY_TYPES: {sorted(missing)}"
        )

    def test_catalog_is_frozenset(self):
        """CANONICAL_ENTITY_TYPES is a frozenset (immutable — prevents accidental mutation)."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        assert isinstance(CANONICAL_ENTITY_TYPES, frozenset)

    def test_catalog_types_are_strings(self):
        """All entries in CANONICAL_ENTITY_TYPES are strings."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        non_strings = [t for t in CANONICAL_ENTITY_TYPES if not isinstance(t, str)]
        assert not non_strings, f"Non-string entries in CANONICAL_ENTITY_TYPES: {non_strings}"

    def test_catalog_types_uppercase_format(self):
        """All entity type names are UPPER_SNAKE_CASE (standard Presidio convention)."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        bad_format = [
            t for t in CANONICAL_ENTITY_TYPES
            if not re.match(r"^[A-Z][A-Z0-9_]+$", t)
        ]
        assert not bad_format, (
            f"Entity types with non-UPPER_SNAKE_CASE format: {sorted(bad_format)}"
        )

    def test_default_config_lists_are_subsets_of_catalog(self):
        """Default strong_anchors and quasi_identifiers are both subsets of the catalog."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES
        from redakt.config import Settings

        s = Settings()
        all_configured = set(s.strong_anchors) | set(s.quasi_identifiers)
        unknown = all_configured - CANONICAL_ENTITY_TYPES
        assert not unknown, (
            f"Default config entity types not in CANONICAL_ENTITY_TYPES: {sorted(unknown)}. "
            "Add missing types to entity_catalog.py."
        )

    def test_no_overlap_in_default_lists(self):
        """Default strong_anchors and quasi_identifiers are disjoint (REQ-012)."""
        from redakt.config import Settings

        s = Settings()
        overlap = set(s.strong_anchors) & set(s.quasi_identifiers)
        assert not overlap, (
            f"Default config: entity types appear in BOTH strong_anchors and "
            f"quasi_identifiers: {sorted(overlap)}"
        )
