"""Canonical entity type catalog for Redakt.

This module is the authoritative source of truth for all entity type strings
recognized by the Redakt/Presidio stack. It is used at config-load time to
validate `strong_anchors` and `quasi_identifiers` entries.

Maintenance: update this constant alongside `docs/supported-entities.md`.
A CI lint test (`tests/test_entity_catalog.py`) asserts the two stay in sync.
"""

# All entity types recognized by the Redakt/Presidio stack.
# Classification (strong_anchor / quasi_identifier / always_emit) lives in
# docs/supported-entities.md — this constant carries only the names.
CANONICAL_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        # --- Universal Presidio entity types ---
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "LOCATION",
        "DATE_TIME",
        "NRP",
        "IP_ADDRESS",
        "URL",
        "IBAN_CODE",
        "MEDICAL_LICENSE",
        "US_SSN",
        "US_PASSPORT",
        "US_ITIN",
        "US_DRIVER_LICENSE",
        "US_BANK_NUMBER",
        "ORGANIZATION",
        "CREDIT_CARD",
        "CRYPTO",
        "EU_VAT_ID",
        "BIC_CODE",
        "SEPA_CREDITOR_ID",
        # --- German-specific entity types ---
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
        "DE_PLZ",
        "DE_BSNR",
        "DE_HANDELSREGISTER",
        "DE_MALO",
        "DE_MELO",
        "DE_EEG_ANLAGE",
        "DE_ZAEHLERNUMMER",
    }
)
