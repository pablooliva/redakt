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
