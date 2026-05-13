# Architecture Decision Records

Cross-cutting architectural decisions for this system. Each ADR captures a choice that binds future work.

## Conventions

- ADRs are numbered sequentially (0001, 0002, ...).
- Status lifecycle: **Accepted** → **Deprecated** (no longer followed but not replaced) or **Superseded** (replaced by a newer ADR).
- Superseded ADRs remain in this directory with updated status and a reference to the superseding ADR. They are never deleted.

## Index

| # | Title | Status | Date | Topic |
|---|-------|--------|------|-------|
| [0001](0001-presidio-per-language-nlp-engine.md) | Use a per-language Presidio NLP engine — spaCy en_core_web_lg for English, xlm-roberta-large-finetuned-conll03-german for German | Accepted | 2026-05-06 | NLP / PII detection |
| [0002](0002-eu-vat-id-multi-country-recognizer.md) | Use a single multi-country EU_VAT_ID recognizer over per-country EU VAT recognizers | Accepted | 2026-05-11 | Recognizer-authorship / cross-border |
| [0003](0003-de-recognizers-dual-registered-under-en.md) | Dual-register country-specific recognizers under en for cross-border subsidiary traffic | Accepted | 2026-05-12 | Language-registration policy |
| [0004](0004-industry-vertical-recognizers-in-fork.md) | Accept industry-vertical recognizers in the Presidio fork's DE baseline (PV/energy) | Accepted | 2026-05-12 | Fork scope |
| [0005](0005-dual-tier-scoring-date-patterns.md) | Use dual-tier scoring (0.95 canonical / 0.85 ambiguous) for DateRecognizer pattern additions | Accepted | 2026-05-12 | Score-arithmetic convention |
| [0006](0006-inline-case-flag-scoping-and-iso-country-anchoring.md) | Wrap case-sensitive recognizer patterns in inline `(?-i:...)` and anchor structurally loose patterns on ISO 3166-1 alpha-2 | Accepted | 2026-05-12 | Recognizer-authorship conventions |
| [0007](0007-closed-world-filtering-quasi-identifiers.md) | Closed-world filtering — anchor-conditional emission for quasi-identifier entities | Proposed | 2026-05-13 | Redakt policy / threat-model |
