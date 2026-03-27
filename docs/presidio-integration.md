# Presidio Integration Reference

Redakt is built on [Microsoft Presidio](https://github.com/microsoft/presidio), an open-source framework for PII detection and anonymization. Presidio lives as a Git submodule at `./presidio/` in this repository.

This document captures the architecture, integration options, and API surface that Redakt builds on.

## Architecture Overview

Presidio is split into independent modules. For text-based PII work, two are relevant:

```
Input Text
    |
    v
+------------------+     +------------------+
|  Presidio        |     |  NLP Engine      |
|  Analyzer        |<----|  (spaCy /        |
|                  |     |   Transformers / |
|  Detects PII     |     |   Stanza)       |
|  entities in text|     +------------------+
+--------+---------+
         | List[RecognizerResult]
         | (entity_type, start, end, score)
         v
+------------------+
|  Presidio        |
|  Anonymizer      |
|                  |
|  Applies operators
|  (replace, redact,
|   hash, mask,    |
|   encrypt, custom)
+--------+---------+
         |
         v
    Anonymized Text + Metadata
```

## Analyzer — PII Detection

The `AnalyzerEngine` is the detection layer. When called, it:

1. Processes text through an NLP engine (spaCy by default) to produce tokens, lemmas, and named entities
2. Runs all registered recognizers against the text
3. Enhances scores using context — surrounding words like "phone" or "email" near a match boost confidence
4. Resolves conflicts — overlapping detections are merged or the highest-confidence one wins
5. Returns `RecognizerResult` objects — each with entity type, character positions, and a confidence score (0.0-1.0)

### Built-in Recognizers

Presidio ships with 50+ recognizers:

| Category | Examples |
|---|---|
| **Pattern-based** (regex) | Email, phone, credit card, IP address, IBAN, URL, MAC address, crypto addresses |
| **NLP-based** (NER) | Person names, locations, organizations, nationalities (via spaCy/Transformers) |
| **Country-specific** | DE: tax ID, passport, ID card, KFZ plate, VAT (13 recognizers); US: SSN, driver license; UK: NINO, NHS; AU, IN, IT, KR, and more |
| **LLM-based** (optional) | Ollama / Azure OpenAI for flexible zero-shot entity detection |

### Custom Recognizers

Two approaches:

- **Pattern-based**: subclass `PatternRecognizer`, define regex patterns and context words
- **NLP-based**: subclass `LocalRecognizer`, implement `analyze()` using NLP artifacts

Register with `analyzer.registry.add_recognizer(my_recognizer)`.

## Anonymizer — PII Replacement

The `AnonymizerEngine` takes analyzer results and transforms detected PII using configurable operators.

### Built-in Operators

| Operator | What it does | Reversible? |
|---|---|---|
| **replace** (default) | Substitutes with `<ENTITY_TYPE>` or custom value | No |
| **redact** | Removes the PII entirely | No |
| **mask** | Replaces characters with a masking char (e.g., `****`) | No |
| **hash** | SHA-256/512 hash of the value | No |
| **encrypt** | AES-CBC encryption with a key | Yes (via `decrypt`) |
| **keep** | Leaves PII in place (for tracking without anonymizing) | N/A |
| **custom** | Applies any callable/lambda | Depends |

### Deanonymization

Only `encrypt` is truly reversible. The `DeanonymizeEngine` can decrypt previously encrypted entities given the same key and the operator metadata from the anonymize step.

## Other Presidio Modules

- **presidio-image-redactor** — OCR-based PII detection and redaction in images and DICOM files
- **presidio-structured** — PII detection and anonymization in pandas DataFrames and JSON
- **presidio-cli** — A PII **linter/scanner only** (no anonymization). Scans files, reports PII findings, exits with code 1 if PII found. Designed as a CI gate / pre-commit hook to *block* text containing PII, not to transform it.

## Integration Options

There are two ways to consume Presidio's functionality:

### 1. Direct Python Library

Import the engines directly — no server needed:

```python
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

results = analyzer.analyze(text="John Smith's email is john@example.com", language="en")

anonymized = anonymizer.anonymize(
    text="John Smith's email is john@example.com",
    analyzer_results=results,
    operators={
        "PERSON": OperatorConfig("replace", {"new_value": "<NAME>"}),
        "EMAIL_ADDRESS": OperatorConfig("redact"),
    }
)
```

Best for: embedding in a CLI tool or a Python web backend.

### 2. REST API (Flask)

Presidio ships two Flask servers (`presidio-analyzer/app.py` and `presidio-anonymizer/app.py`) that expose a full HTTP API. Any language or AI agent that can make HTTP requests can use this — no Python SDK required.

#### Analyzer Endpoints (port 5002)

| Method | Path | Description |
|---|---|---|
| `POST` | `/analyze` | Detect PII in text (single or batch) |
| `GET` | `/recognizers?language=en` | List loaded recognizers |
| `GET` | `/supportedentities?language=en` | List detectable entity types |
| `GET` | `/health` | Health check |

#### Anonymizer Endpoints (port 5001)

| Method | Path | Description |
|---|---|---|
| `POST` | `/anonymize` | Anonymize text given analyzer results + operator config |
| `POST` | `/deanonymize` | Reverse encryption-based anonymization |
| `GET` | `/anonymizers` | List available operators |
| `GET` | `/deanonymizers` | List available deanonymizers |
| `GET` | `/health` | Health check |

#### Example: Full Analyze + Anonymize Flow

```bash
# Step 1: Analyze
curl -X POST http://localhost:5002/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "text": "John Smith drivers license is AC432223",
    "language": "en"
  }'

# Response:
# [
#   {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.85},
#   {"entity_type": "US_DRIVER_LICENSE", "start": 30, "end": 38, "score": 0.65}
# ]

# Step 2: Anonymize (pass analyzer results from step 1)
curl -X POST http://localhost:5001/anonymize \
  -H "Content-Type: application/json" \
  -d '{
    "text": "John Smith drivers license is AC432223",
    "anonymizers": {
      "DEFAULT": {"type": "replace", "new_value": "ANONYMIZED"}
    },
    "analyzer_results": [
      {"start": 0, "end": 10, "score": 0.85, "entity_type": "PERSON"},
      {"start": 30, "end": 38, "score": 0.65, "entity_type": "US_DRIVER_LICENSE"}
    ]
  }'

# Response:
# {"text": "ANONYMIZED drivers license is ANONYMIZED", "items": [...]}
```

#### OpenAPI Spec

A full OpenAPI 3.0 specification is available at `presidio/docs/api-docs/api-docs.yml`. This can be loaded into Swagger UI for interactive exploration or used to auto-generate client code.

### Running the REST API via Docker

The simplest way to run the API services locally:

```bash
docker compose -f presidio/docker-compose-transformers.yml up --build
```

## NLP Engine Options

### docker-compose-text.yml (spaCy)

- NLP engine: spaCy (`en_core_web_lg`)
- NER: spaCy's built-in named entity recognition
- Entity coverage: standard (PERSON, LOCATION, ORG, DATE_TIME, NRP)
- Faster to build, smaller image

### docker-compose-transformers.yml (Transformers)

- NLP engine: Transformers + spaCy for tokenization only (`en_core_web_sm`)
- NER model: `StanfordAIMI/stanford-deidentifier-base` (BERT-based)
- Entity coverage: richer — also maps AGE, ID, PATIENT, STAFF, HOSPITAL, FACILITY, VENDOR, HCW
- Trained specifically for deidentification — more accurate at catching names and contextual PII
- Tradeoff: larger Docker image, slower inference without GPU

**Recommendation for Redakt:** The transformers variant is the better fit for GDPR compliance. Catching more names is worth the overhead. Use the text variant for faster iteration during development.

## Implications for Redakt

### What Presidio provides
- PII detection engine with 50+ recognizers (including 13 German-specific)
- Anonymization with multiple operator strategies
- REST API ready for any client (web app, AI agent, CLI)
- OpenAPI spec for client generation and documentation
- Docker deployment out of the box

### What Redakt needs to build
- **Web UI** — frontend for pasting text and seeing redacted results (Presidio has no UI)
- **Agent-friendly interface** — AI agents can call the REST API directly; no wrapper CLI needed
- **Orchestration** — the analyze-then-anonymize two-step flow needs to be handled by Redakt (either in a backend or by the client)
- **Configuration UX** — expose operator choices, confidence thresholds, and entity selection to users
- **Deanonymization workflow** — if using encrypt/decrypt, Redakt needs to manage keys and operator metadata to allow reversal

### Architecture decision: REST API vs. direct Python

The REST API approach (Docker containers) is the simplest path for both the web app and AI agent integration:
- The web frontend can call the API directly
- AI agents make HTTP requests — no Python SDK needed
- Both share the same backend with zero wrapper code
- Stateless and independently scalable

Direct Python embedding makes sense if Redakt eventually ships as a standalone CLI tool (no Docker dependency).
