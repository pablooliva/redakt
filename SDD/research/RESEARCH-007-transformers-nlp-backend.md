# RESEARCH-007-transformers-nlp-backend

**Status:** Complete
**Date:** 2026-05-06
**Author:** research-investigation subagent (Opus 4.7)
**Branch:** feature/007-transformers-nlp-backend
**Inputs:**
  - Resolved design intent: `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md`
  - Calibration baseline: `reports/post-fix-2.md` (41/41 PASS, 2026-05-06 08:20:12)
  - Project conventions: `CLAUDE.md`, `docs/v1-feature-spec.md`, `docs/presidio-integration.md`

> **Glossary terms** used below (all from CLARIFICATION; consolidated in §14): asymmetric routing, detection-set non-regression, calibration corpus, country recognizer, language auto-detect path, broader class.

---

## 0. Executive findings (read this first)

Five things planning needs front-loaded, derived from the rest of the document:

1. **Presidio's `NlpEngineProvider` cannot mix engine types per language.** `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py:90-108` reads exactly one `nlp_engine_name` and instantiates exactly one engine class for *all* configured languages. The CLARIFICATION's stated implementation — *"Two engines coexist via `NlpEngineProvider`'s per-language engine map"* — is **wrong as written**. The design intent (asymmetric routing per Q3 C) is sound and unchanged; only the wiring needs to be different. Three viable wirings, each with trade-offs, are documented in §3.3. Cleanest fit given the constraints: a small custom `NlpEngine` subclass inside the Presidio fork that holds one `SpacyNlpEngine` (en) + one `TransformersNlpEngine` (de) and dispatches on `language`.
2. **Models are baked into the analyzer image at build time** via `presidio/presidio-analyzer/install_nlp_models.py` (called from `Dockerfile.transformers:30`). For transformers models that runs `huggingface_hub.snapshot_download` (`install_nlp_models.py:91`) + a one-shot `AutoModelForTokenClassification.from_pretrained` (`install_nlp_models.py:94-95`) to materialize weights into the image. **No hot reload.** Per CLARIFICATION Q4 ("no caps") this is acceptable; document the rationale and the alternative (`TRANSFORMERS_CACHE` mount) in case it ever changes. **However, `install_nlp_models.py:54-68` is hard-coded to dispatch only on `spacy | stanza | transformers`** — under Option C's `nlp_engine_name: multi`, the build fails at line 68 (`raise ValueError("Unsupported nlp engine: {engine_name}")`). This is a build-pipeline gap that planning must close in the same fork PR (~10 LoC extension). See §2.6.
3. **Of the candidate German NER models surveyed, `flair/ner-german-large` wins on benchmark accuracy alone (F1 92.31 on CoNLL-03 German revised) but is INCOMPATIBLE with Presidio's `TransformersNlpEngine`** — it ships in flair-native format and requires `flair.models.SequenceTagger.load`, while Presidio's pipeline is wired to `spacy_huggingface_pipelines.hf_token_pipe`, which uses HF's `pipeline()` and `AutoModelForTokenClassification` (`presidio/presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py:99`). Picking flair would force either a recognizer-side adapter or a custom `NlpEngine` subclass that bypasses `hf_token_pipe`. **Recommended primary: `xlm-roberta-large-finetuned-conll03-german`** — confirmed via live HF-pipeline probe (§4.5) to return **zero entities on all 10 broader-class bare nouns** while preserving correct sentence-context behavior (PER on `Anna Schmidt`, LOC on `Berlin`, ORG on `Beispiel AG`; `Personalausweis` not flagged even when followed by a real PERSON). The `mschiesser/ner-bert-german` fallback was probed in the same harness and **failed the bug-class test** (mis-tags `Personalausweis` as PER 0.997, `Aufenthaltstitel` as PER 0.998, etc.) — see §4.5; demoted from "fallback" to "rejected on bug-class evidence". Validated A/B target: `Davlan/bert-base-multilingual-cased-ner-hrl` (also clean on all 10, smaller backbone, ~700 MB).
4. **The current eval suite is structurally weak at catching over-detection.** `tests/eval/test_calibration.py:55` enforces `expected.issubset(found)` — i.e. it asserts only that *every expected entity is found*, not that *unexpected entities are absent*. Concretely: `reports/post-fix-2.md` shows `Personalausweis Nummer L01X00T47.` returns `PERSON(0.85), DE_ID_CARD(0.75), DE_PASSPORT(0.40)` and is marked PASS because `DE_ID_CARD` is in `found`. The PERSON over-detection of `Personalausweis` — the headline bug being fixed — is invisible to the green CI line. Adding new fixtures to `tests/eval/fixtures/de.yaml` with `expect_clean: true` (e.g. `"Personalausweis"` alone) is the only way to convert this class into a CI signal, since `expect_clean` is the only branch that asserts `found == []` (test_calibration.py:46-50).
5. **The post-filter (`filter_by_entity_thresholds`) lives in Redakt, not Presidio.** `src/redakt/utils.py:97-110` is the single chokepoint where per-entity thresholds are enforced, called from `src/redakt/routers/detect.py:117`. The threshold *config shape* (`dict[str, float]` in `src/redakt/config.py:14`) is preserved unchanged. Only the *values* and possibly the *entity coverage* of that map need re-tuning under the new graded scores. No code change to the filter itself is required.

---

## 1. System Data Flow

### 1.1 Key entry points (Redakt + Presidio Analyzer)

| File:line | Role |
|---|---|
| `src/redakt/main.py:33-58` | FastAPI app construction, CSP middleware, lifespan that sets up `httpx.AsyncClient` and validates language config |
| `src/redakt/routers/detect.py:111` | `POST /api/detect` — entry point for the eval suite, calibration tool, and the boolean PII check |
| `src/redakt/routers/detect.py:60-127` | `run_detection()` — shared orchestration: language resolve → Presidio call → per-entity post-filter |
| `src/redakt/services/presidio.py:13-36` | Async HTTP wrapper that POSTs to Presidio Analyzer's `/analyze` |
| `src/redakt/services/language.py:80-102` | `detect_language()` — lingua-py based auto-detect with timeout/fallback |
| `src/redakt/utils.py:83-95` | `merge_entity_thresholds()` — instance + per-request map merge |
| `src/redakt/utils.py:97-110` | `filter_by_entity_thresholds()` — drops results below per-entity floor |
| `presidio/presidio-analyzer/app.py:40-58` | Presidio's Flask `Server.__init__` — reads `NLP_CONF_FILE`, `ANALYZER_CONF_FILE`, `RECOGNIZER_REGISTRY_CONF_FILE` env vars and constructs an `AnalyzerEngine` once at boot |
| `presidio/presidio-analyzer/presidio_analyzer/analyzer_engine_provider.py:81-104` | `AnalyzerEngineProvider.create_engine()` — composes nlp_engine + registry into the analyzer; per-engine and per-registry config files are independent |
| `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py:87-114` | `NlpEngineProvider.create_engine()` — **single `nlp_engine_name`**, single engine class instantiated for all `models[].lang_code` entries |

### 1.2 Per-request data transformation chain

```
HTTP POST /api/detect (text, language, allow_list, entity_score_thresholds)
   |
   v
detect.py:run_detection
   - if language=="auto":  language.py:detect_language  ─── lingua-py
   - validate language ∈ settings.supported_languages (en, de)
   - validate per-request allow_list; merge with instance allow_list
   |
   v
presidio.py:analyze
   - HTTP POST {analyzer_url}/analyze with score_threshold=settings.default_score_threshold (0.35)
   |
   v   (Presidio Analyzer container — single process, one AnalyzerEngine instance)
analyzer_engine.analyze
   - nlp_engine.process_text(text, language)
        - SpacyNlpEngine.process_text  ─── self.nlp[language](text)  (one model per lang)
        - TransformersNlpEngine.process_text  ─── inherits SpacyNlpEngine.process_text;
            spaCy pipeline runs tokenizer+lemmatizer (parser/ner disabled, line 88);
            hf_token_pipe component fills doc.spans["bert-base-ner"] with NER hits
   - Entity-recognizer registry runs (PatternRecognizer, country regexes, NLP-based)
   - LemmaContextAwareEnhancer reads NlpArtifacts.lemmas → boosts scores
   - returns List[RecognizerResult] (entity_type, start, end, score)
   |
   v   (back in Redakt)
detect.py:run_detection
   - merge_entity_thresholds(instance, per_request)
   - filter_by_entity_thresholds(results, merged)  ─── DROPS scores below per-entity floor
   - log_detection (audit-only, no PII content)
   - return DetectResponse / DetectDetailedResponse
```

### 1.3 External dependencies

- **lingua-language-detector** (`pyproject.toml:8`) — language auto-detect; Lingua handles en/de/es and is configured to require ≥ 2 languages.
- **Presidio Analyzer service** (HTTP at `REDAKT_PRESIDIO_ANALYZER_URL`, default `http://localhost:5001` in `config.py:11` but `docker-compose.yml:13` overrides to `http://presidio-analyzer:5001` inside the compose network).
- **Presidio Anonymizer service** (HTTP at port 5001 in compose; not relevant to detection but co-located).
- **Hugging Face Hub** (build-time only, via `huggingface_hub.snapshot_download` in `install_nlp_models.py:91`).

### 1.4 Integration points that this feature touches

| Surface | Status under this feature |
|---|---|
| `POST /api/detect` request/response shape | **Unchanged.** API contract preserved per CLARIFICATION constraint. |
| `POST /api/anonymize` and `POST /api/deanonymize` | **Unchanged.** These don't go through Presidio's NLP engine choice. |
| `entity_score_thresholds` config (instance + per-request) | **Shape unchanged** (`dict[str, float]`). **Values re-tuned** per CLARIFICATION Q5c. |
| `low_score_entity_names` / `low_confidence_score_multiplier` (Presidio NER config) | **Re-tuned** under graded transformer scores. Currently `low_score_entity_names: [ORG, ORGANIZATION]`, multiplier `0.4` (`spacy_multilingual.yaml:27-30`). |
| `default_score_threshold` (`config.py:13`) | Currently `0.35`. May or may not need re-tuning; a calibration-corpus pass under the new model is the only way to know. |
| `spacy_multilingual.yaml` | **Replaced or supplanted** by a new NLP engine config that wires per-language engines (see §3.3). |
| `default_recognizers.yaml` | **Floor preserved.** Currently-enabled recognizers stay enabled in current order with current scoring per CLARIFICATION constraint. New ones may be added. |
| `Dockerfile.transformers` | **Selected** (compose file points to it) and possibly extended with a German spaCy model and the German transformer. |
| `docker-compose.yml` (root) | `presidio-analyzer.build.dockerfile` switched from default to `Dockerfile.transformers`; `args.NLP_CONF_FILE` switched to the new YAML. |
| `tools/calibration_report.py` | **Corpus expanded** per CLARIFICATION Q5b — but the corpus is implicit: the tool walks all of `tests/eval/fixtures/*.yaml` (`calibration_report.py:116`, `tests/eval/_loader.py:65-72`). New phrases land in fixtures, not in the tool. |
| `tests/eval/fixtures/de.yaml` | **5–10 new phrases added** with `expect_clean: true` for the broader class (per Q5a). |

---

## 2. Existing State of the Presidio Fork

### 2.1 Current production NLP config (`presidio/presidio-analyzer/presidio_analyzer/conf/spacy_multilingual.yaml`)

```yaml
nlp_engine_name: spacy
models:
  - lang_code: en
    model_name: en_core_web_lg
  - lang_code: de
    model_name: de_core_news_lg
  - lang_code: es
    model_name: es_core_news_md

ner_model_configuration:
  model_to_presidio_entity_mapping:
    PER: PERSON
    PERSON: PERSON
    NORP: NRP
    FAC: LOCATION
    LOC: LOCATION
    LOCATION: LOCATION
    GPE: LOCATION
    ORG: ORGANIZATION
    ORGANIZATION: ORGANIZATION
    DATE: DATE_TIME
    TIME: DATE_TIME

  low_confidence_score_multiplier: 0.4
  low_score_entity_names:
    - ORG
    - ORGANIZATION
```

Notes:
- **`es` is in the YAML but not in the `default_recognizers.yaml` `supported_languages` list** (which is `[en, de]`, line 1-3 of that file). Spanish-specific recognizers are still listed in the registry; they just don't activate for Redakt's two production languages. Leaving `es` in the model list is harmless — the multilingual engine just doesn't get queried with `language=es`.
- **`low_score_entity_names: [ORG, ORGANIZATION]`** halves spaCy's flat 0.85 score for ORG/ORGANIZATION (multiplier 0.4). This is the only knob the current registry uses against spaCy's flat-score problem.
- **No `default_score`** is set, so `NerModelConfiguration.default_score` defaults to **0.85** (`presidio_analyzer/nlp_engine/ner_model_configuration.py:63-64`, the `Field(default=0.85, ge=0.0, le=1.0, ...)` line). That's the source of the "everything from spaCy German is 0.85" finding the CLARIFICATION cites.

### 2.2 Recognizer-registry floor (`presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml`)

Top-level:
```yaml
supported_languages:
  - en
  - de
global_regex_flags: 26
```

Currently-enabled country recognizers per language (after fork commits 71206f6 and d76d884):

| Language | Enabled recognizers (regex/pattern-based, score-floor for the planning ADR) |
|---|---|
| `en` (US) | `UsBankRecognizer`, `UsLicenseRecognizer`, `UsItinRecognizer`, `UsPassportRecognizer`, `UsSsnRecognizer`, `UsMbiRecognizer`, `UsNpiRecognizer`, `AbaRoutingRecognizer` |
| `en` (UK) | `NhsRecognizer`, `UkNinoRecognizer`, `UkPassportRecognizer`, `UkPostcodeRecognizer`, `UkVehicleRegistrationRecognizer` |
| `de` | `DeTaxIdRecognizer`, `DeVatIdRecognizer`, `DePassportRecognizer`, `DeIdCardRecognizer`, `DeHealthInsuranceRecognizer`, `DeKfzRecognizer`, `DeFuehrerscheinRecognizer`, `DePlzRecognizer` |
| Generic (any language) | `CryptoRecognizer`, `DateRecognizer`, `EmailRecognizer`, `IbanRecognizer`, `IpRecognizer`, `MedicalLicenseRecognizer`, `MacAddressRecognizer`, `PhoneRecognizer`, `UrlRecognizer`, `CreditCardRecognizer` |
| `es` (still listed) | `EsNifRecognizer`, `EsNieRecognizer` |
| `it`, `pl` (still listed) | Italian + Polish recognizers — all `enabled` defaults |

Recognizers explicitly **disabled** in the fork that should remain disabled until separately re-evaluated:
- `DeTaxNumberRecognizer`, `DeSocialSecurityRecognizer`, `DeHandelsregisterRecognizer` — per d76d884 commit message, no eval coverage yet.
- `SgFinRecognizer`, all `Au*Recognizer`, all `Ng*Recognizer`, all `In*Recognizer`, all `Kr*Recognizer`, `ThTninRecognizer`, `HuggingFaceNerRecognizer`, `BasicLangExtractRecognizer`, `InVoterRecognizer`, `InGstinRecognizer`.

**Critical for planning:** the `nlp_engine` is provided to `RecognizerRegistryProvider` (`analyzer_engine_provider.py:108-110`); recognizers like `PhoneRecognizer` use it for context-word checks via the lemma enhancer. Whatever NLP engine the new config produces, it must implement the `NlpEngine` interface and provide `nlp_artifacts.lemmas`.

### 2.3 Existing transformers scaffold (`presidio/presidio-analyzer/presidio_analyzer/conf/transformers.yaml`)

```yaml
nlp_engine_name: transformers
models:
  - lang_code: en
    model_name:
      spacy: en_core_web_sm
      transformers: StanfordAIMI/stanford-deidentifier-base

ner_model_configuration:
  labels_to_ignore: [O]
  aggregation_strategy: max
  stride: 16
  alignment_mode: expand
  model_to_presidio_entity_mapping:
    PER: PERSON
    PERSON: PERSON
    LOC: LOCATION
    LOCATION: LOCATION
    GPE: LOCATION
    ORG: ORGANIZATION
    ORGANIZATION: ORGANIZATION
    NORP: NRP
    AGE: AGE
    ID: ID
    EMAIL: EMAIL
    PATIENT: PERSON
    STAFF: PERSON
    HOSP: ORGANIZATION
    PATORG: ORGANIZATION
    DATE: DATE_TIME
    TIME: DATE_TIME
    PHONE: PHONE_NUMBER
    HCW: PERSON
    HOSPITAL: LOCATION
    FACILITY: LOCATION
    VENDOR: ORGANIZATION
  low_confidence_score_multiplier: 0.4
  low_score_entity_names: [ID]
```

Key facts:
- `model_name` for transformers is a **dict with `spacy` and `transformers` keys** — both required (`transformers_nlp_engine.py:103-115`). The spaCy model is for tokenization/lemma; the transformers model is for NER.
- `aggregation_strategy: max` (alternates: `simple`, `first`, `average`) — passes through to HF `pipeline()`.
- `stride: 16` — overlapping-window length in *transformer tokenizer tokens* (not spaCy tokens) for long-text handling.
- The shipping mapping is StanfordAIMI-specific (PATIENT, HOSP, HCW labels). For `de`, the new mapping needs to fit whichever model is chosen — for CoNLL-03-trained models (xlm-roberta, Davlan, ner-bert-german) the labels are just `PER`/`LOC`/`ORG` (and sometimes `MISC`).

### 2.4 Dockerfile.transformers (`presidio/presidio-analyzer/Dockerfile.transformers`)

Lines 16-32 do the load-bearing work:
- `COPY ${NLP_CONF_FILE} /app/${NLP_CONF_FILE}` — bakes the NLP YAML into the image.
- `poetry install --no-root --only=main -E server -E transformers` — pulls transformers, accelerate, huggingface_hub, spacy_huggingface_pipelines (the `-E transformers` extra in `pyproject.toml`).
- `poetry run python install_nlp_models.py --conf_file ${NLP_CONF_FILE}` — **at build time** downloads:
  - the spaCy model via `spacy.cli.download` (`install_nlp_models.py:56` for the `spacy` engine branch and `:87` inside `_install_transformers_spacy_models`)
  - the HF model via `huggingface_hub.snapshot_download` + a one-shot `AutoModelForTokenClassification.from_pretrained` (`install_nlp_models.py:91, 94-95`)

So model weights live in the image. **No runtime download, no hot reload of model code or weights.** Source code under `/app` *can* be hot-reloaded by mounting volumes (the root `docker-compose.yml:9` already volume-mounts `./src:/app/src` for Redakt itself, and the spaCy/transformers Python code is just a `poetry install` away if needed at dev time), but model artifacts are immutable per image.

Per CLARIFICATION Q4 ("strong preference: hot-reload-friendly when feasible; if model files must be baked into the image, document the reason"), the reason to bake is:

1. `huggingface_hub.snapshot_download` is slow-ish (multi-GB downloads) and produces flaky behavior on first request if deferred to runtime.
2. The healthcheck on the analyzer container (`docker-compose.yml:31-37`) has a `start_period: 30s` — runtime download would extend cold start to many minutes for an xlm-roberta-large. **Whether 30s is sufficient for the new baked-in model load (xlm-roberta-large + de_core_news_sm + en_core_web_lg) is itself a "verify during implementation" item — not a documented trade-off accepted up front.** Cold-load time for a 2.2 GB safetensors model is typically 5–20 seconds on modern CPU; en_core_web_lg loads in 3–5 seconds. The plausible total is 10–30 seconds — the existing 30s `start_period` may suffice without change. If the implementation calibration measures cold start > 25 seconds with margin, raise to 60–90 seconds; otherwise leave alone. Add a one-shot timing measurement to the implementation plan: `time docker compose up presidio-analyzer` after first build, captured for the calibration report.
3. Reproducibility: a baked image is deterministic across deployments; runtime download is at the mercy of HF Hub availability.

The alternative (mount `TRANSFORMERS_CACHE` as a named volume, defer download to first request) is documented but not adopted.

### 2.5 Root compose wiring (`docker-compose.yml`)

```yaml
presidio-analyzer:
  build:
    context: ./presidio/presidio-analyzer
    args:
      - NLP_CONF_FILE=presidio_analyzer/conf/spacy_multilingual.yaml
```

There is **no `dockerfile:` directive**, so it uses the default `Dockerfile` (not `Dockerfile.transformers`). Redakt currently runs the spaCy variant. The transformers variant is built only by `presidio/docker-compose-transformers.yml:9-15` (a Presidio-fork-internal compose used for raw Presidio testing, not Redakt's stack).

For this feature, the root `docker-compose.yml` needs to be updated to:
- Add `dockerfile: Dockerfile.transformers`
- Update `args.NLP_CONF_FILE` to the new German-aware NLP YAML

(See §3.3 Wiring Option B for the alternative two-container approach which would touch this file differently.)

### 2.6 Build-pipeline gap: `install_nlp_models.py` does not know about Option C

**Verified at `presidio/presidio-analyzer/install_nlp_models.py:54-68` (full function body):**

```python
def _download_model(engine_name: str, model_name: Union[str, Dict[str, str]]) -> None:
    if engine_name == "spacy":
        spacy_download(model_name)
    elif engine_name == "stanza":
        if stanza:
            stanza.download(model_name)
        else:
            raise ImportError("stanza is not installed")
    elif engine_name == "transformers":
        if transformers:
            _install_transformers_spacy_models(model_name)
        else:
            raise ImportError("transformers is not installed")
    else:
        raise ValueError(f"Unsupported nlp engine: {engine_name}")
```

The dispatch is hard-coded to three engine names. Under Option C the YAML's `nlp_engine_name: multi` is read at `install_nlp_models.py:47` and passed to `_download_model` for every entry of `nlp_configuration["models"]` (the loop at `:46-49` unconditionally hands the **single global** `nlp_engine_name` to the dispatcher; per-row `engine` keys in the proposed multi YAML schema are ignored). **The image build fails at `Dockerfile.transformers:30` (the `RUN poetry run python install_nlp_models.py` step) on the first build attempt.**

**Implementation impact (must land in the same fork PR as `MultiNlpEngine`):**

1. Add a `multi` branch to `_download_model` (or add it as a parallel arm in the loop at `install_nlp_models.py:46-49`) that ignores the global `nlp_engine_name` and dispatches each `model` entry by its **per-row** `engine` key (`spacy` or `transformers`).
2. The proposed multi-YAML schema (RESEARCH-007 §3.4) has each `models[]` entry carry its own `engine` key — `model["engine"] == "spacy"` for the en row and `"transformers"` for the de row. The simplest extension: when `nlp_engine_name == "multi"`, iterate `nlp_configuration["models"]` and for each row call `_download_model(model["engine"], model["model_name"])`.
3. Diff is small (~10 LoC) but blocking — without it, `docker compose build presidio-analyzer` errors before any runtime testing is possible.

**LoC accounting (relevant to §11.2 / §0):** the `~150 LoC` figure for `MultiNlpEngine` does **not** include this `install_nlp_models.py` extension or test code. A more honest total: ~100 LoC for `MultiNlpEngine` itself, ~10 LoC for the install script extension, and ~80–150 LoC of unit tests across `MultiNlpEngine` + the new install branch — total ~200–260 LoC in the Presidio fork.

---

## 3. Asymmetric Routing — the Load-Bearing Technical Question

### 3.1 The constraint

`presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py:87-114`:

```python
def create_engine(self) -> NlpEngine:
    nlp_engine_name = self.nlp_configuration["nlp_engine_name"]    # ONE name
    if nlp_engine_name not in self.nlp_engines:
        raise ValueError(...)

    nlp_engine_class = self.nlp_engines[nlp_engine_name]            # ONE class
    nlp_models = self.nlp_configuration["models"]                   # MANY models, all under same engine

    ner_model_configuration = ...
    engine = nlp_engine_class(
        models=nlp_models, ner_model_configuration=ner_model_configuration
    )
    engine.load()
    return engine
```

The configuration schema enforces a single engine type (`nlp_engine_name: spacy | transformers | stanza`) for all configured `models[]`. There is no per-language engine map; the `models[].lang_code` keys exist *within* the single chosen engine, not across engines.

### 3.2 What `TransformersNlpEngine` does to spaCy

`TransformersNlpEngine` *extends* `SpacyNlpEngine` (`presidio/presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py:22`). At load time (`load`, lines 73-100):

```python
nlp = spacy.load(spacy_model, disable=["parser", "ner"])
pipe_config = { "model": transformers_model, ... }
nlp.add_pipe("hf_token_pipe", config=pipe_config)
self.nlp[model["lang_code"]] = nlp
```

So:
- spaCy is *still loaded* (provides tokenizer + lemmatizer; that's what `LemmaContextAwareEnhancer` reads via `nlp_artifacts.lemmas`).
- spaCy's NER and parser are *disabled*.
- The HF `pipeline()` runs as a spaCy pipe component, populating `doc.spans["bert-base-ner"]`.
- `_get_entities` returns `doc.spans[self.entity_key]` instead of `doc.ents` (line 117-126).

This means: **if you set `nlp_engine_name: transformers` and list both `en` and `de` models, both languages get spaCy-NER-disabled-plus-transformer-NER.** That is *not* asymmetric routing — that's transformers for everything. spaCy en NER becomes unreachable.

### 3.3 Three viable wirings (planning picks one)

**Option A — Transformers-only, both languages.** Set `nlp_engine_name: transformers` with two model entries. spaCy NER is bypassed for English too; rely on the transformer for English PERSON/EMAIL/etc.

- *Pros:* zero fork code change. Single container. Single config file.
- *Cons:* Violates CLARIFICATION Q3 C explicitly (*"spaCy en stays the primary"*). Risks English non-regression failure since spaCy `en_core_web_lg` and a generic English transformer don't flag the same sets of entities. The current `transformers.yaml` ships StanfordAIMI which is a deidentification-tuned model with a *richer* label set than spaCy — likely a superset, but unverified, and StanfordAIMI's German performance is unknown. To preserve "detection-set non-regression" with confidence, the en transformer would need to be calibrated against the en fixtures in `generic.yaml`, `uk.yaml`, `us.yaml`, and the en half of `benign.yaml`.
- *Net:* possible but requires extra calibration work for English. Not the cheapest path.

**Option B — Two analyzer containers, route in Redakt.** Run two separate `presidio-analyzer` containers (one with `spacy_multilingual.yaml`, one with the new German transformer YAML). Redakt's `PresidioClient` picks which URL to call based on `language`.

- *Pros:* No fork code change — fork stays closer to upstream, lowering future merge cost. Each engine runs in its own process; OOM risk on one doesn't take down the other. Independent restarts. The Redakt-side change is small (per-language URL map in `src/redakt/services/presidio.py:7-12` and `src/redakt/config.py:11` — ~5–10 LoC). Image size is split (each container only carries one model family), so disk usage is not necessarily doubled — could be similar to or smaller than Option C's single-image-with-everything depending on overlap.
- *Cons:* Two containers, two health checks, two cold-start paths to manage in compose. Each container loads its own copy of the recognizer registry (the de container holds the full registry but is queried only for `de`, and vice versa — the registry's `supported_languages` filter handles this; no per-container registry surgery is required). Two `docker compose build` cycles when changing models or recognizers.
- *Net:* viable. Slightly more operational surface than Option C, less invasive to the Presidio fork, **honest balance is closer than this research originally framed it**. Useful as a "phase 0" while the fork-modification path is being prototyped. The strongest argument for **Option C over Option B** is *English bit-for-bit preservation by construction* (RESEARCH-007 §5.3) — under Option B, the en container is unchanged, but the wiring to switch which container handles which language adds a Redakt-side seam that currently doesn't exist. Both Options preserve detection-set non-regression for English; Option C does so without touching Redakt at all.

**Option C (recommended) — Custom `MultiNlpEngine` subclass inside the Presidio fork.** Write a thin `NlpEngine` implementation that holds one `SpacyNlpEngine` (with `en_core_web_lg`) and one `TransformersNlpEngine` (with `de_core_news_sm` + the chosen DE transformer), and dispatches `process_text(text, language)` and `process_batch` by language. Register it in `NlpEngineProvider`'s `nlp_engines` tuple. Drive it via a YAML where `nlp_engine_name: multi` and `models[]` carries a sub-engine type per language.

- *Pros:* Exactly preserves the asymmetric-routing intent. Single container, single image, single config file in the analyzer. No change to Redakt or `services/presidio.py`. Each sub-engine sees its native NLP artifacts (en gets full spaCy tokens+ents+lemmas; de gets spaCy-tokens-only-plus-transformer-NER). The `NerModelConfiguration` can be per-sub-engine, enabling different `low_score_entity_names` per language.
- *Cons:* Adds Presidio-fork code that must be carried indefinitely on the fork — `MultiNlpEngine` is **unlikely to be upstream-mergeable** because upstream's stance is single-engine-per-config-file as intentional simplicity (see also Missing Perspectives, §11). The diff includes one new module + the provider registration + a YAML schema extension + the `install_nlp_models.py` build-pipeline extension (§2.6). Honest size estimate: **~100 LoC for `MultiNlpEngine` itself + ~10 LoC for `install_nlp_models.py` + ~80–150 LoC of unit tests = ~200–260 LoC total in the fork.** `ConfigurationValidator.validate_nlp_configuration` (`presidio_analyzer/input_validation/schemas.py`) will need a new branch for the `multi` engine schema or a `skip` annotation.
- *Net:* recommended. Smallest user-facing complication; cleanest data-flow story; preserves Q3 C verbatim. **Phasing alternative noted:** if planning prefers to validate the model + new fixtures + threshold re-tuning end-to-end before committing to the fork extension, Option B can serve as a 2-week phase-0; Option C then becomes a phase-1 consolidation. This research recommends Option C as a single deliverable on grounds that the bug-class probe (§4.5) has already de-risked the model choice, leaving the engine wiring as the only remaining variable.

### 3.4 Implementation skeleton for Option C (illustrative — for planning, not for copy-paste)

```python
# presidio/presidio-analyzer/presidio_analyzer/nlp_engine/multi_nlp_engine.py
class MultiNlpEngine(NlpEngine):
    engine_name = "multi"
    is_available = True

    def __init__(self, models, ner_model_configuration=None):
        # models = [
        #   {"lang_code": "en", "engine": "spacy",        "model_name": "en_core_web_lg", "ner_model_configuration": {...}},
        #   {"lang_code": "de", "engine": "transformers", "model_name": {"spacy": "de_core_news_sm",
        #                                                                  "transformers": "xlm-roberta-large-finetuned-conll03-german"},
        #                                                  "ner_model_configuration": {...}},
        # ]
        self._sub_engines = {}
        for m in models:
            cls = {"spacy": SpacyNlpEngine, "transformers": TransformersNlpEngine}[m["engine"]]
            cfg = NerModelConfiguration.from_dict(m["ner_model_configuration"]) if m.get("ner_model_configuration") else ner_model_configuration
            self._sub_engines[m["lang_code"]] = cls(models=[{"lang_code": m["lang_code"], "model_name": m["model_name"]}],
                                                   ner_model_configuration=cfg)

    def load(self): [e.load() for e in self._sub_engines.values()]
    def is_loaded(self):  return all(e.is_loaded() for e in self._sub_engines.values())
    def process_text(self, text, language):  return self._sub_engines[language].process_text(text, language)
    def process_batch(self, texts, language, **kw): return self._sub_engines[language].process_batch(texts, language, **kw)
    def is_stopword(self, w, lang):  return self._sub_engines[lang].is_stopword(w, lang)
    def is_punct(self, w, lang):     return self._sub_engines[lang].is_punct(w, lang)
    def get_supported_entities(self): return list({e for sub in self._sub_engines.values() for e in sub.get_supported_entities()})
    def get_supported_languages(self): return list(self._sub_engines.keys())
    def get_nlp(self, language):     return self._sub_engines[language].get_nlp(language)
```

A YAML example:
```yaml
nlp_engine_name: multi
models:
  - lang_code: en
    engine: spacy
    model_name: en_core_web_lg
    ner_model_configuration:
      model_to_presidio_entity_mapping: { PER: PERSON, PERSON: PERSON, NORP: NRP, FAC: LOCATION, LOC: LOCATION, LOCATION: LOCATION, GPE: LOCATION, ORG: ORGANIZATION, ORGANIZATION: ORGANIZATION, DATE: DATE_TIME, TIME: DATE_TIME }
      low_score_entity_names: [ORG, ORGANIZATION]
      low_confidence_score_multiplier: 0.4
  - lang_code: de
    engine: transformers
    model_name:
      spacy: de_core_news_sm
      transformers: xlm-roberta-large-finetuned-conll03-german
    ner_model_configuration:
      labels_to_ignore: [O]
      aggregation_strategy: max
      stride: 16
      alignment_mode: expand
      model_to_presidio_entity_mapping: { PER: PERSON, LOC: LOCATION, ORG: ORGANIZATION, MISC: MISC }
      labels_to_ignore: [O, MISC]   # MISC is not a Presidio entity; drop it
      low_score_entity_names: []     # graded scores; tune empirically
      low_confidence_score_multiplier: 1.0   # neutral
```

Planning will refine. The point is to show that the data-model fit exists.

### 3.5 Open Q2 — spaCy German + transformer interplay for lemma-aware recognizers

Per `transformers_nlp_engine.py:88`, `spacy.load(spacy_model, disable=["parser", "ner"])` keeps **tokenizer + tagger + lemmatizer**. `_doc_to_nlp_artifact` is **inherited from `SpacyNlpEngine`** (defined at `spacy_nlp_engine.py:200-213`, with `lemmas = [token.lemma_ for token in doc]` on line 201) — `TransformersNlpEngine` does not override it. So lemma-aware recognizers (PhoneRecognizer's context handling, the `LemmaContextAwareEnhancer` itself at `presidio_analyzer/context_aware_enhancers/lemma_context_aware_enhancer.py:9-50`) get exactly what they need from the spaCy half of the transformers engine.

**A small spaCy German model is sufficient.** `de_core_news_sm` (~14 MB) provides German lemmatization and is the recommended companion (Presidio's transformers docs explicitly suggest "a simple model, such as en_core_web_sm" — `transformers_nlp_engine.py:43-46`).

This resolves CLARIFICATION open Q2: under the transformers engine for de, load `de_core_news_sm` for spaCy duties. Lemma-aware enhancement keeps working.

**Caveat (flagged for implementation, out of scope for this feature):** PhoneRecognizer's context-word list is English-only by default. Whether the German PII regex hits are context-degraded by the absence of a German trigger list (`Telefon`, `Mobil`) is a pre-existing latent question independent of this feature; verify during implementation calibration. If German PhoneRecognizer hits arrive de-prioritized, that's a follow-up feature, not a blocker for this one.

---

## 4. German Transformer Model Survey

All candidates investigated against five criteria:
1. **HF compatibility** (must work via `transformers.pipeline()` + `AutoModelForTokenClassification`, since that's what `spacy_huggingface_pipelines.hf_token_pipe` uses).
2. **Parameter count / size on disk** (informational — no caps per Q4).
3. **Label space** (must map cleanly to Presidio entities via `model_to_presidio_entity_mapping`).
4. **Reported quality on German** (F1, training corpus).
5. **Common-noun-as-PERSON behavior** (the headline bug).

### 4.1 Comparison table

| Model | HF format | Params / size | Labels | F1 / corpus | Common-noun behavior (live probe — §4.5) | Verdict |
|---|---|---|---|---|---|---|
| `flair/ner-german-large` | **Flair-native, NOT HF pipeline-compatible** | Not in card; estimated ~1.5 GB (xlm-roberta-large + flair head) | PER, LOC, ORG, MISC | **F1 92.31** on CoNLL-03 German revised | Not probed (incompatible loading path) | **Highest accuracy, INCOMPATIBLE** with Presidio's transformers engine. Loading requires `flair.SequenceTagger.load`, which `hf_token_pipe` doesn't call. |
| `xlm-roberta-large-finetuned-conll03-german` | **HF-compatible** (AutoModel + pipeline; needs `sentencepiece` Python dep at install time) | Not in card; xlm-roberta-large is ~2.2 GB | PER, LOC, ORG, MISC (CoNLL-03 standard) | F1 not in card; refers to associated paper (arXiv:1911.02116) | **EMPIRICALLY VERIFIED CLEAN.** Returns zero entities on all 10 broader-class bare nouns (`Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`, `Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`, `Versicherungsnummer`) AND on 9 of 10 broader-extras (only `BIC` flags as ORG 0.998 — defensible). Sentence-context behavior preserved: `Hans Müllers Personalausweis ist abgelaufen.` flags only `Hans Müllers` as PER 1.0; `Personalausweis` is NOT flagged in context either. See §4.5 for the probe transcript. | **Recommended primary, evidence-backed.** Same backbone family as the flair model; HF-loadable; CoNLL-03 corpus identity confirmed; bug-class behavior probed and clean. |
| `Davlan/bert-base-multilingual-cased-ner-hrl` | **HF-compatible** | 0.2B params / ~700 MB | PER, LOC, ORG (no MISC) | German in training corpus (CoNLL 2003); F1 not per-language reported | **EMPIRICALLY VERIFIED CLEAN** on all 10 bare nouns; correct sentence-context behavior (`Anna Schmidt` PER 1.0, `Beispiel AG` ORG 1.0, `Berlin` LOC 1.0). Cleaner tokenization (no `sentencepiece` fallback warning). | **Validated A/B target.** Smaller (~700 MB vs 2.2 GB), multilingual, no `sentencepiece` dep. Worth an A/B run during calibration if image size or latency pressure matters. |
| `Davlan/distilbert-base-multilingual-cased-ner-hrl` | HF-compatible | 0.1B params / ~350 MB | PER, LOC, ORG | German in corpus; F1 not reported | Not probed (research budget; sibling model `Davlan/bert-base-multilingual-cased-ner-hrl` cleared bug-class probe, plausibly extends to distil variant) | Smallest viable candidate. Worth noting in alternates if the larger models prove unworkably slow. |
| `mschiesser/ner-bert-german` | HF-compatible (Transformers 4.25.1, safetensors) | 0.2B params / ~840 MB | PER, LOC, ORG | F1 0.8829 overall, PER F1 0.9152; trained on **wikiann-de** | **EMPIRICALLY DISQUALIFIED.** Mis-tags `Personalausweis` as PER 0.997, `Aufenthaltstitel` as PER 0.998, `Mitarbeiterausweis` as PER 0.994, `Bundespersonalausweis` as PER 0.793, `Reisepassnummer` as PER 0.85; the rest as ORG (`Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`, `Sozialversicherungsnummer`, `Versicherungsnummer`). Wikiann training did not generalize to bare bureaucratic nouns. The bug class would survive this swap. | **Rejected on bug-class evidence.** Earlier hypothesis (wikiann broader than CoNLL → better common-noun calibration) does not hold empirically. |
| `dslim/bert-base-NER` | HF-compatible | 110M params / ~440 MB | PER, LOC, ORG, MISC | **English only** (CoNLL-2003 English) | N/A (English-only) | **Not a German candidate.** Appears only in `TransformersNlpEngine`'s docstring example (`transformers_nlp_engine.py:36`) as illustration of the dict shape. The actual `__init__` default model when no `models` argument is passed is `obi/deid_roberta_i2b2` (`transformers_nlp_engine.py:66`), not this. Listed for completeness; not in scope. |

### 4.2 Recommendation

**Primary: `xlm-roberta-large-finetuned-conll03-german`** — HF-pipeline-compatible, same training corpus and backbone as the highest-scoring flair model, **and verified by live HF-pipeline probe (§4.5) to return zero entities on all 10 broader-class bare nouns** while preserving correct sentence-context behavior. Per CLARIFICATION Q4 there's no cost gate that argues against the larger weights. The CoNLL-03 label space (PER/LOC/ORG/MISC) maps cleanly onto Presidio entities.

**Secondary fallback (calibration A/B target): `Davlan/bert-base-multilingual-cased-ner-hrl`.** Also empirically clean on all 10 broader-class phrases (§4.5). Smaller (~700 MB vs ~2.2 GB), no `sentencepiece` Python-dep requirement, and produces cleaner tokenization (no fallback-heuristic warning). Worth A/B-ing during calibration if image size or CPU-latency proves a pressure point — though per Q4 no cap applies.

**Demoted/rejected (was previously listed as fallback): `mschiesser/ner-bert-german`.** The bug-class probe (§4.5) shows this model **mis-tags 5 of 10 broader-class bare nouns as PER** with confidences 0.793–0.998 (and the remaining 5 as ORG). Adopting it would carry the same headline bug into the new system. Earlier reasoning about wikiann-de coverage was not borne out empirically.

**If Pablo wants flair's 92.31 F1:** that becomes a different feature (write a flair-aware `NlpEngine` subclass that bypasses `hf_token_pipe` and calls `SequenceTagger.predict` directly). It's tractable but doubles the fork-modification scope. Not recommended for this feature.

### 4.3 Alternatives Considered (for the ADR's "Alternatives" section)

- **`flair/ner-german-large`** — would have been the accuracy winner but requires custom adapter.
- **`Davlan/bert-base-multilingual-cased-ner-hrl`** — promoted from "fallback" status: empirically clean on the bug class (§4.5); preferred A/B target.
- **`Davlan/distilbert-base-multilingual-cased-ner-hrl`** — minimal-footprint candidate; defer to a future "smaller image" feature.
- **`mschiesser/ner-bert-german`** — empirically disqualified by §4.5 probe. Documented for traceability so future contributors don't re-propose it without re-running the probe.
- **A bespoke fine-tuned German model** — out of scope for this feature; the brief is "swap in an off-the-shelf transformer," not "train one."

### 4.4 Per-entity mapping for the recommended model

For `xlm-roberta-large-finetuned-conll03-german` and any CoNLL-03-labels model:

```yaml
model_to_presidio_entity_mapping:
  PER: PERSON
  LOC: LOCATION
  ORG: ORGANIZATION
labels_to_ignore: [O, MISC]   # MISC has no clean Presidio mapping; drop
```

(BIO prefixes `B-` and `I-` are stripped by the HF pipeline's `aggregation_strategy: max` before they reach this mapping.)

### 4.5 Bug-class probe results (live HF-pipeline runs, 2026-05-06)

To resolve CRITICAL-RESEARCH Gap 2 — "model selection is benchmark-only; never probed against the bug class" — three HF-loadable candidate models were run live against the 5 named over-detection phrases plus the CLARIFICATION-named extras. Probe harness: `transformers.pipeline(task="ner", model=<id>, aggregation_strategy="max")` invoked from `uv run --no-project --with "transformers,torch,sentencepiece,protobuf,huggingface_hub" python -c ...` (temp script discarded after capturing the transcript; not committed). Inputs and outputs verbatim:

**Set A — 10 broader-class bare nouns** (the success-criterion set per CLARIFICATION Q2a):

| Phrase | `xlm-roberta-large-finetuned-conll03-german` | `Davlan/bert-base-multilingual-cased-ner-hrl` | `mschiesser/ner-bert-german` |
|---|---|---|---|
| `Personalausweis` | `[]` clean | `[]` clean | `PER 0.997` |
| `Reisepassnummer` | `[]` clean | `[]` clean | `PER 0.85` |
| `Krankenversicherungsnummer` | `[]` clean | `[]` clean | `ORG 0.997` |
| `Führerschein` | `[]` clean | `[]` clean | `ORG 1.0` |
| `Steuer-IdNr.` | `[]` clean | `[]` clean | `ORG 0.948 / 0.945 / 0.933` (3 fragments) |
| `Sozialversicherungsnummer` | `[]` clean | `[]` clean | `ORG 0.994` |
| `Bundespersonalausweis` | `[]` clean | `[]` clean | `PER 0.793` |
| `Aufenthaltstitel` | `[]` clean | `[]` clean | `PER 0.998` |
| `Mitarbeiterausweis` | `[]` clean | `[]` clean | `PER 0.994` |
| `Versicherungsnummer` | `[]` clean | `[]` clean | `ORG 0.995` |

**Set B — 10 broader-class extras** (probed only against the primary recommendation; sub-class boundary spec, see §7.4):

| Phrase | `xlm-roberta-large-finetuned-conll03-german` |
|---|---|
| `Geburtsurkunde` | `[]` clean |
| `Heiratsurkunde` | `[]` clean |
| `Meldebescheinigung` | `[]` clean |
| `Steuernummer` | `[]` clean |
| `Kontonummer` | `[]` clean |
| `Mitgliedsnummer` | `[]` clean |
| `Kundennummer` | `[]` clean |
| `Auftragsnummer` | `[]` clean |
| `BIC` | `ORG 0.998` |
| `IBAN` | `[]` clean |

**Set C — sentence-context controls** (must NOT regress under the new model):

| Phrase | `xlm-roberta-large-finetuned-conll03-german` | `Davlan/bert-base-multilingual-cased-ner-hrl` | `mschiesser/ner-bert-german` |
|---|---|---|---|
| `Anna Schmidt arbeitet bei der Beispiel AG in Berlin.` | `PER AnnaSchmidt 1.0`, `ORG BeispielAG 1.0`, `LOC Berlin. 1.0` | `PER Anna Schmidt 1.0`, `ORG Beispiel AG 1.0`, `LOC Berlin 1.0` | `PER Anna Schmidt 0.999`, `ORG Beispiel 0.988`, `ORG AG 0.782`, `LOC Berlin 0.999` |
| `Hans Müllers Personalausweis ist abgelaufen.` | `PER HansMüllers 1.0` (only — `Personalausweis` clean in context) | `PER Hans 1.0` (only) | `PER Hans Müllers 1.0` (only — `Personalausweis` clean in context here too) |

**Conclusions:**

1. **Primary recommendation `xlm-roberta-large-finetuned-conll03-german` is empirically validated.** All 10 named broader-class phrases return zero entities. 9 of 10 broader-extras are clean. Only `BIC` flags as ORG (defensible — BIC is the SWIFT bank-identifier-code term, frequently appears in financial-institution contexts where ORG tagging is reasonable). Sentence-context controls preserve correct PER/ORG/LOC behavior; `Personalausweis` is not flagged even when it follows a real PERSON name.
2. **`Davlan/bert-base-multilingual-cased-ner-hrl` is also empirically clean** on the same bug-class set and is the documented A/B target. Cleaner tokenization (no `sentencepiece` fallback-heuristic warning) is a minor but real ergonomic advantage.
3. **`mschiesser/ner-bert-german` is empirically disqualified.** The hypothesis that wikiann-de training would calibrate it better against bare common nouns did not survive contact with the data. Demoted from "fallback" in the original research to "rejected on bug-class evidence" — see §4.2 / §4.3.

**Tokenization note.** The xlm-roberta probe emits a `Tokenizer does not support real words, using fallback heuristic` warning; the model returns concatenated tokens like `AnnaSchmidt` / `BeispielAG` rather than the space-separated forms Davlan returns. This is purely a span-rendering artifact — entity types and scores are correct. Presidio's `hf_token_pipe` consumes the spans via `aggregation_strategy: max` (`transformers.yaml:11`) which collapses sub-word tokens; per-character offsets land on the original text. Not a blocker; flagged for any planning subagent that reads raw pipeline output.

**Class boundary observation.** The 20 phrases in Sets A+B span 4 sub-classes (identity-document: `Personalausweis`, `Bundespersonalausweis`, `Mitarbeiterausweis`, `Aufenthaltstitel`, `Geburtsurkunde`, `Heiratsurkunde`, `Meldebescheinigung`, `Reisepassnummer`; insurance: `Krankenversicherungsnummer`, `Sozialversicherungsnummer`, `Versicherungsnummer`; financial: `Steuer-IdNr.`, `Steuernummer`, `Kontonummer`, `BIC`, `IBAN`; employment/membership: `Mitgliedsnummer`, `Kundennummer`, `Auftragsnummer`, `Führerschein`). The recommended model handles all but `BIC` cleanly across sub-classes. See §7.4 for the full class boundary specification.

---

## 5. English Baseline Preservation

### 5.1 What spaCy English currently flags

Pulled from `reports/post-fix-2.md` (the 2026-05-06 baseline). English fixtures are in `tests/eval/fixtures/{generic,benign,us,uk}.yaml` (29 of the 41 phrases are en).

| Fixture phrase (en) | Currently flagged | Notes |
|---|---|---|
| `"Please email John Smith at john.smith@example.com..."` | EMAIL_ADDRESS(1.00), PERSON(0.85), URL(0.50) ×2 | URL fires on the email host; cosmetic. |
| `"Contact Maria Rodriguez on +1 415 555 0133."` | PERSON(0.85), PHONE_NUMBER(0.40) | |
| `"Send the wire to IBAN GB82 WEST 1234 5698 7654 32."` | IBAN_CODE(1.00), NRP(0.85) | NRP fires on "WEST" — spaCy quirk. |
| `"My card number is 4111 1111 1111 1111, expiring 12/27."` | CREDIT_CARD(1.00) | |
| `"Server at 192.168.1.42 went down."` | IP_ADDRESS(0.60) | |
| `"Visit https://internal.acme.example/admin..."` | URL(0.60) | |
| `"MAC address 00:1A:2B:3C:4D:5E"` | MAC_ADDRESS(0.95) | |
| `"BTC tip address 1BoatSLRHtKNngkdXEeobR76b53LETtpyT"` | CRYPTO(1.00) | |
| Each US fixture | The expected country recognizer fires, score in 0.40–1.00 range. | |
| Each UK fixture | The expected country recognizer fires, score 0.45–1.00. | |
| All en `benign` fixtures | (clean) — the LOCATION 0.90 / DATE_TIME 0.95 floors successfully drop "Munich today", "Paris this afternoon", etc. | |

**Detection-set non-regression bar (per CLARIFICATION Q1):** the set of entities flagged on en fixtures by the new system must be a *superset of* `{EMAIL_ADDRESS, PERSON, URL, PHONE_NUMBER, IBAN_CODE, NRP, CREDIT_CARD, IP_ADDRESS, MAC_ADDRESS, CRYPTO, US_SSN, US_DRIVER_LICENSE, US_ITIN, ABA_ROUTING_NUMBER, US_BANK_NUMBER, US_PASSPORT, US_NPI, US_MBI, UK_NHS, UK_NINO, UK_POSTCODE, UK_VEHICLE_REGISTRATION, UK_PASSPORT}` (consolidated from the post-fix-2 report).

Score values may freely move inside that envelope. Only entity *presence* matters.

### 5.2 No English-only over-detection bugs visible in the baseline

The baseline shows zero FAIL verdicts on en `benign` fixtures (post-fix-2.md lines 8-44). All 11 benign en/de phrases pass clean. The current LOCATION 0.90 / DATE_TIME 0.95 thresholds in `config.py:14` are doing their job for English; this feature should not regress them.

**The brief is correct that there's no en-side fix to bundle.** Confirmed.

### 5.3 Risk: under Option C, English keeps spaCy verbatim

Because Option C mounts `SpacyNlpEngine` for `en` with `en_core_web_lg` exactly as today, English behavior is bit-for-bit identical to the current production. Detection-set non-regression on English is **automatic** under Option C.

Under Option A (transformers for both) the risk is real and would require fixture-level verification that StanfordAIMI or whatever en transformer is chosen flags the full set above. Worth noting because Option A is operationally simplest.

---

## 6. Per-Entity Threshold Mechanism (current state, no changes required)

### 6.1 Where the floor is enforced

**Redakt-side post-filter, not Presidio.** The flow is:

1. Redakt calls Presidio with `score_threshold=settings.default_score_threshold` (0.35) — `services/presidio.py:24`. This is Presidio's own global cutoff.
2. Presidio returns results above 0.35.
3. Redakt's `filter_by_entity_thresholds` (`utils.py:97-110`) drops results whose `entity_type` has a per-entity floor and whose `score < floor`. Entities not in the map are unaffected.

Per-entity floors only *raise* the bar; to *lower* (e.g., let through borderline LOCATION at 0.5 when the instance default is 0.9) the per-request body must override.

### 6.2 Current values

`src/redakt/config.py:14`:
```python
entity_score_thresholds: dict[str, float] = {"LOCATION": 0.90, "DATE_TIME": 0.95}
```

Tuned for spaCy's flat 0.85 score: nothing PERSON or NRP from spaCy can hit 0.90 LOCATION (different entity), and the only LOCATION/DATE_TIME hits at 0.85 are dropped (since 0.85 < 0.90). Effectively, LOCATION and DATE_TIME from spaCy are *off* under this setup unless context-aware enhancement boosts the score above 0.9 — which it can do via the `LemmaContextAwareEnhancer` (similarity factor 0.35, max boost configured per recognizer).

### 6.3 Other knobs

In Presidio's NER config, two related knobs:
- `low_score_entity_names: [ORG, ORGANIZATION]` (`spacy_multilingual.yaml:29-30`)
- `low_confidence_score_multiplier: 0.4` (`spacy_multilingual.yaml:27`)

These multiply the model's NER score for those entity names *inside Presidio*, *before* Redakt sees the results. spaCy ORG hits at 0.85 become 0.34 — below Presidio's 0.35 cutoff — so ORG/ORGANIZATION are effectively *suppressed* from spaCy. (This is also why the `generic.yaml` German fixture for "Anna Schmidt arbeitet bei der Beispiel AG in Berlin" has `expect: [PERSON]` only, with the note "ORGANIZATION not currently firing on the spaCy German model.")

### 6.4 What changes under transformer scores

Under graded transformer scores:
- Per-entity LOCATION 0.90 floor likely too high — most real LOCATION hits will land 0.7–0.95. **Re-tune empirically via calibration.**
- Per-entity DATE_TIME 0.95 — same story; the spaCy German model didn't even produce DATE_TIME, so this knob never fired on German anyway. The English en_core_web_lg is unchanged so the en-side DATE_TIME threshold need not move (Option C).
- `low_score_entity_names`: under the new mapping (PER/LOC/ORG → PERSON/LOCATION/ORGANIZATION) the ORG suppression *via the 0.4 multiplier* still applies if listed there. Whether to keep ORG suppressed for German depends on whether the new model produces ORG hits the user wants vs not — calibration question.
- `low_confidence_score_multiplier`: lifted to 1.0 (neutral) for the de transformer would let the model's natural gradient flow through; lifted to 0.5–0.7 would shave score off the ORG class as an extra precaution. **Empirical.**

### 6.5 Open Q3 explicitly deferred

The CLARIFICATION's Q3 (research target) reads: *"What `low_score_entity_names` and `low_confidence_score_multiplier` should be set to under graded scores — answered empirically by calibration."* This research document does **not** propose specific values. The current values are documented above; the new values are calibration-driven and belong in implementation, not research.

---

## 7. Calibration Tool Internals

### 7.1 What `tools/calibration_report.py` does

- **Walks all of `tests/eval/fixtures/*.yaml`** via `tests.eval._loader.load_all_phrases()` (line 116).
- **Sends each phrase through Redakt's `/api/detect?verbose=true`** (line 67-77). This means the report includes Redakt's per-entity threshold filter — what an operator sees in production.
- **With `--raw`, also hits Presidio Analyzer directly with `score_threshold=0.0`** (line 79-92). This bypasses both Presidio's global cutoff and Redakt's per-entity post-filter, surfacing pre-filter candidates including the ones Redakt drops. **Useful for tuning the floors.**
- **With `--out [PATH]`, writes a Markdown report** (line 105-107). Default location: `reports/calibration-YYYYMMDD-HHMMSS.md` (the `reports/` directory is gitignored per the repo conventions).
- Verdict per phrase via `_verdict()` (lines 55-61): `expect_clean → PASS iff found is empty`; otherwise `PASS iff expected.issubset(found)`. Same semantic as the test suite.
- Output is grouped by `## [VERDICT] {fixture} — {text}` headings; under each phrase the line `- redakt: {entity_type}({score}), ...` is the post-filter view, and `- raw:` / `- dropped:` are the Presidio-direct views.

### 7.2 Where new German-noun phrases land (for Q5b)

**In `tests/eval/fixtures/de.yaml`.** The calibration tool has no separate corpus; it's the same set as the eval suite. So adding `expect_clean: true` phrases to `de.yaml` simultaneously:
- Adds them to the calibration report (the operator sees them).
- Adds them to CI (the eval suite parametrizes them).

This is by design — single source of truth, no duplication. (Confirmed by reading `_loader.py:50-72` and `calibration_report.py:36-40,116`.)

### 7.3 Recommended new fixture entries (for planning to refine)

Based on CLARIFICATION's enumeration of the broader class — *"Sozialversicherungsnummer, Bundespersonalausweis, Aufenthaltstitel, Mitarbeiterausweis"* and the original five — suggested entries:

```yaml
# Broader class: German identity/document/insurance common nouns
- text: "Personalausweis"
  language: de
  expect_clean: true
  notes: "Bare common noun — must not flag PERSON or any entity"
- text: "Reisepassnummer"
  language: de
  expect_clean: true
- text: "Krankenversicherungsnummer"
  language: de
  expect_clean: true
- text: "Führerschein"
  language: de
  expect_clean: true
- text: "Steuer-IdNr."
  language: de
  expect_clean: true
- text: "Sozialversicherungsnummer"
  language: de
  expect_clean: true
- text: "Bundespersonalausweis"
  language: de
  expect_clean: true
- text: "Aufenthaltstitel"
  language: de
  expect_clean: true
- text: "Mitarbeiterausweis"
  language: de
  expect_clean: true
- text: "Versicherungsnummer"
  language: de
  expect_clean: true
```

(Planning may add 5–10 more from the Wiktionary "Ausweis" / "Nummer" compound classes.)

### 7.4 Class boundary specification (broader-class definition for testing)

CLARIFICATION Q2a says "research must verify the fix generalizes beyond the 5 named phrases" and Q5b reads "expand with ~10–20 German document/insurance/ID nouns for verification." The original 10 phrases in §7.3 hit Q5b's lower bound but did not articulate the **class boundary** — what makes a phrase a member, what doesn't, and what the test sample should span. This section closes that gap.

**Membership criterion** (working definition): a phrase is a member of the broader class iff it is a German nominal-form (no inflection suffix, no numeric tail) common noun designating an identity document, insurance document, financial-account artifact, or employment/membership token, in a context where the bare token alone (no surrounding sentence) would not be a real-world PII reference.

**Sub-classes and target sample** (probed in §4.5 wherever possible):

1. **Identity / document** (8 members covered):
   - Probed clean: `Personalausweis`, `Bundespersonalausweis`, `Mitarbeiterausweis`, `Aufenthaltstitel`, `Reisepassnummer`, `Geburtsurkunde`, `Heiratsurkunde`, `Meldebescheinigung`.
   - Future-set candidates: `Wohnsitzbescheinigung`, `Aufenthaltserlaubnis`, `Personenstandsurkunde`.
2. **Insurance** (3 members covered):
   - Probed clean: `Krankenversicherungsnummer`, `Sozialversicherungsnummer`, `Versicherungsnummer`.
   - Future-set candidates: `Rentenversicherungsnummer`, `Pflegeversicherungsnummer`.
3. **Financial / tax / banking** (5 members covered):
   - Probed clean: `Steuer-IdNr.`, `Steuernummer`, `Kontonummer`, `IBAN`.
   - Probed FLAG (defensible): `BIC` → ORG 0.998 (SWIFT term for bank identifier; the model's training-time corpus likely sees `BIC` overwhelmingly in bank-name contexts).
   - Future-set candidates: `Bankleitzahl`, `Kreditkartennummer`, `SEPA-Mandatsreferenz`.
4. **Employment / membership** (4 members covered):
   - Probed clean: `Führerschein`, `Mitgliedsnummer`, `Kundennummer`, `Auftragsnummer`.
   - Future-set candidates: `Personalnummer`, `Arbeitgebernummer`, `Rechnungsnummer`, `Bestellnummer`.

**Recommended fixture set for `tests/eval/fixtures/de.yaml`** (refining §7.3 to 15 phrases spanning 4 sub-classes):

The 10 in §7.3 cover identity (7), insurance (2), financial (1). To fill the gap planning should add 5 more covering the under-represented sub-classes. The §4.5 probe data already validates the model on these — the fixtures convert the validation into a CI signal:

```yaml
- text: "Geburtsurkunde"           # identity-document, sub-class 1
  language: de
  expect_clean: true
- text: "Steuernummer"             # financial, sub-class 3 (distinct from Steuer-IdNr.)
  language: de
  expect_clean: true
- text: "Kontonummer"              # financial, sub-class 3
  language: de
  expect_clean: true
- text: "Mitgliedsnummer"          # employment/membership, sub-class 4
  language: de
  expect_clean: true
- text: "Kundennummer"             # employment/membership, sub-class 4
  language: de
  expect_clean: true
```

Total: 10 (§7.3) + 5 (§7.4) = 15 fixtures, hitting the upper end of Q5b's "10–20" target and spanning all 4 sub-classes.

**Operator-side spot-check (calibration cadence).** `uv run python tools/calibration_report.py --raw --out` should be the standing check for any new candidate German common noun that surfaces in production. The CI fixtures fix the regression signal at 15 phrases; the calibration report remains the broader observability surface for the long tail.

**Documented future expansion.** The `BIC → ORG` flag is defensible but worth surfacing in the ADR's "Consequences/Neutral observations": the recommended model does flag `BIC`, and any operator-facing documentation should note this. If a customer flags `BIC` as an unwanted detection, the next step is to add an ORG floor entry (`{"ORGANIZATION": 0.99}` or similar) for German, not a model change.

---

## 8. Eval Suite Layout

### 8.1 Pytest harness

- `tests/eval/conftest.py:31-36` — session-scoped fixture skips the suite if Redakt's `/api/health` isn't reachable. The full Docker Compose stack must be up.
- `tests/eval/test_calibration.py:30-34` — module-level `PHRASES = load_all_phrases()`.
- `tests/eval/test_calibration.py:38` — `@pytest.mark.parametrize("phrase", PHRASES, ids=[p.label for p in PHRASES])` — each phrase becomes a separately-IDed test case.
- `pyproject.toml:42-44` — `addopts = "--ignore=tests/e2e --ignore=tests/eval"` excludes both directories from default `pytest`. Run explicitly with `uv run pytest tests/eval/`.

### 8.2 The `expect.issubset(found)` semantic

`tests/eval/test_calibration.py:46-60`:

```python
if phrase.expect_clean:
    assert found == [], (...)
    return

expected = sorted(set(phrase.expect))
missing = [e for e in expected if e not in found]
assert not missing, (...)
```

Two branches:
- **`expect_clean: true`** — strict: `found` must be empty. **This is the only branch that catches over-detection.**
- **`expect: [...]`** — permissive: every entity in `expect` must appear in `found`. Extra entities in `found` are silently allowed.

**This is why the broader-class fix isn't visible in the current 41/41 PASS line.** The current de.yaml fixture *"Personalausweis Nummer L01X00T47."* (expect: `[DE_ID_CARD]`) yields `PERSON(0.85), DE_ID_CARD(0.75), DE_PASSPORT(0.40)` — three entities, of which `DE_ID_CARD` is in `expect`, so the assertion passes. The PERSON over-detection of `Personalausweis` rides through unflagged.

To surface the broader-class bug, planning must add **`expect_clean: true` phrases for the bare common nouns** (the 10 above are a starting set). This is the only way the test signal lights up.

### 8.3 The new German-noun fixtures (for Q5a)

Land them in `tests/eval/fixtures/de.yaml`. Per Q5a's "5–10 new CI fixtures" target. The set in §7.3 satisfies this with 10 phrases.

---

## 9. Docker Image and Hot-Reload Story

### 9.1 What's baked in

Per Dockerfile.transformers (§2.4):
- spaCy model (e.g., `de_core_news_sm` for de, `en_core_web_lg` for en) — downloaded at image build via `spacy.cli.download` (`install_nlp_models.py:56` for the `spacy` engine path; `:87` for the `transformers` engine path inside `_install_transformers_spacy_models`).
- HF model — downloaded at image build via `huggingface_hub.snapshot_download` (`install_nlp_models.py:91`) + `AutoTokenizer.from_pretrained` and `AutoModelForTokenClassification.from_pretrained` (`install_nlp_models.py:94-95`). Note: `_install_transformers_spacy_models` itself spans `install_nlp_models.py:71-95`.
- Presidio source code (the Presidio fork itself).
- Presidio's pyproject + dependencies via `poetry install`.

**Build-pipeline gap noted in §2.6** — the `_download_model` dispatcher only knows three engine names; the multi-engine YAML produced by Option C requires an additional dispatch branch for `nlp_engine_name: multi` (or, equivalently, an iteration that respects the per-row `engine` key). Without this extension, the image build fails at the install step (`Dockerfile.transformers:30`).

### 9.2 Hot-reload story for code

- The **root Redakt service** mounts `./src:/app/src` (`docker-compose.yml:9`), so Redakt API code is hot-reloaded.
- The **Presidio Analyzer service** does **not** volume-mount source. Code changes in the Presidio fork (e.g., adding `MultiNlpEngine`) require an image rebuild.

### 9.3 Hot-reload story for models

**Models are NOT hot-reloaded.** Switching the German model (e.g., from xlm-roberta-large to mschiesser/ner-bert-german during calibration A/B) requires:
1. Edit the NLP YAML.
2. `docker compose build presidio-analyzer`.
3. `docker compose up presidio-analyzer`.

For an iterative calibration workflow this is workable but slow (image rebuild downloads the new model — minutes for ~2 GB models). **Workaround for hot iteration**: a developer can `docker exec -it presidio-analyzer python` and rebind `analyzer.nlp_engine` in-process for ad-hoc testing — but this isn't formal.

### 9.4 Why not runtime download

Per CLARIFICATION Q4 there are no caps, so the operator-friendly behavior (deterministic image content, healthcheck-clean cold start) wins over the dev-friendly behavior (smaller image, faster rebuild). Document it; don't change it.

If the operator preference flips later, the change is straightforward: drop `install_nlp_models.py` invocation from the Dockerfile, mount a `huggingface-cache` named volume on `/home/presidio/.cache/huggingface` (or set `TRANSFORMERS_CACHE` to a mounted path), and accept multi-minute first-request latency.

---

## 10. ADR Neighborhood

### 10.1 No prior NLP-backend ADR

`SDD/adr/` exists as an empty directory (verified via `ls -la SDD/adr/` — only `.` and `..`).

**This is the first ADR** under the SDD process.

### 10.2 Suggested ADR identity

- **Number:** 0001
- **Title:** *NLP engine selection — asymmetric routing (spaCy en, transformer de)*
- **Status:** Proposed → Accepted by /sdd:plan
- **Decision in one sentence:** "Presidio's NLP engine is a custom `MultiNlpEngine` (Option C in §3.3) that runs spaCy `en_core_web_lg` for English and a transformer (`xlm-roberta-large-finetuned-conll03-german` per §4.2) for German, coexisting in a single analyzer container."
- **Alternatives considered:** §3.3 Options A (transformers-only, both langs) and B (two analyzer containers). §4.3 model alternatives.

(The ADR file is the planning subagent's deliverable, not this research document's.)

### 10.3 Cross-cutting touches

This decision binds:
- **Future language additions** (es, fr) — they would extend the `MultiNlpEngine` config, choosing engine type per language.
- **Future NLP-backend swaps** — same module is the swap point.
- **Future calibration runs** — must re-baseline whenever any sub-engine changes.

---

## 11. Stakeholder Mental Models

### 11.1 Pablo (operator, sole stakeholder)

- *Wants:* a usable confidence gradient for German entities so per-entity thresholds actually do work; the German common-noun-as-PERSON class fixed; the calibration report's broader-class section showing zero entity flags.
- *Accepts:* longer per-request latency, larger Docker images, longer cold start, code-switched-text best-effort behavior.
- *Will not accept:* English regression, country-recognizer changes (currently-enabled set must stay enabled in current order with current scoring), API contract changes, threshold-shape changes, removal of spaCy.
- *Confirmation in calibration report:* the bare German common nouns from §7.3 should appear under `## [PASS] de — {noun}` with `redakt: —` (no entity flags).

### 11.2 Engineering (the future maintainer; Pablo wearing a different hat)

- *Wants:* swap the NLP engine without changing the API contract or recognizer registry behavior. Single container, single config file.
- *Concerns:* the diff to the Presidio fork for Option C is small but non-trivial. **Honest LoC accounting** (revised from "~150 LoC" after Gap 5 analysis): ~100 LoC for `MultiNlpEngine` itself + ~10 LoC for the `install_nlp_models.py` extension (§2.6) + ~80–150 LoC of unit tests = **~200–260 LoC total in the fork**. Test-coverage for `MultiNlpEngine` should include `process_text`, `process_batch`, `is_stopword`, `is_punct`, `get_supported_entities`, `get_supported_languages`, `get_nlp`, and `is_loaded` for both `en` and `de` language args. Tests for the install-script branch should cover: `multi` with one spacy + one transformers entry; `multi` with an unknown per-row engine (must error); rejection of a `models[]` entry that lacks `engine`.

### 11.3 Presidio upstream maintainer (cross-cutting concern)

- *Mental model:* upstream Presidio's stance on `nlp_engine_name` (single name per config file) is **intentional simplicity**, not an oversight. `MultiNlpEngine` violates that stance: it's a meta-engine that wraps two real engines. Upstream is unlikely to merge it.
- *Implication for Redakt:* the `MultiNlpEngine` module (and the `install_nlp_models.py` extension and the `nlp_engine_provider.py` registration) are **fork-only diffs that must be carried forward indefinitely**. Each upstream merge into `pablooliva/presidio` (the fork) re-applies these diffs as conflicts. Mitigation: keep all three diffs in clearly-delimited blocks (e.g., `# === redakt: MultiNlpEngine ===` markers) and centralize them in as few files as possible. Document the diff in a per-feature CHANGES log under the fork's docs.
- *Alternative*: contribute a more general "engine federation" abstraction upstream that subsumes `MultiNlpEngine`. Out of scope for this feature; flagged for future cross-cutting work if the maintenance cost grows.

### 11.3 Enterprise users (humans pasting into Redakt)

- *Wants:* German nouns NOT redacted; English to keep working.
- *Don't see:* engine internals; only the redaction quality.
- *Accept:* slower first-request response (model spin-up); slightly slower per-request response (transformer inference vs spaCy).

### 11.4 AI agents (programmatic clients)

- *Wants:* same as humans — German false positives stop, English keeps working.
- *Cares about:* API stability. `POST /api/detect` request/response shape unchanged is the contract.

### 11.5 Support — N/A

Internal tool, sole stakeholder Pablo. No external support channel.

---

## 12. Production Edge Cases

Synthesized from the CLARIFICATION and verified against `reports/post-fix-2.md`:

### 12.1 Known (must be addressed)

- **Five named over-detection cases** — `Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`. Visible in the baseline — `de.yaml` fixtures *"Personalausweis Nummer L01X00T47."* (PERSON(0.85), DE_ID_CARD(0.75), DE_PASSPORT(0.40)), *"Krankenversicherungsnummer A123456787."* (DE_HEALTH_INSURANCE(1.00), PERSON(0.85)), and *"Reisepassnummer C01X00T47."* (PERSON(0.85), DE_PASSPORT(0.75), DE_ID_CARD(0.40)) all show the spurious PERSON hit. Eval passes only because of `issubset` semantics (§8.2).

- **Broader class** — German identity/document/insurance common nouns. CLARIFICATION enumerates `Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis` as further examples. New fixtures (§7.3) test this.

- **Country recognizers on bare nouns** — must NOT fire. Verified by reading the German recognizer regexes: they all require numeric patterns (e.g., DE_TAX_ID's 11-digit checksum, DE_ID_CARD's letter-digit pattern). On bare nouns like `"Personalausweis"`, no country recognizer fires. **Confirmed.**

### 12.2 Accepted limitations (CLARIFICATION-resolved)

- **Code-switched text** (e.g., German paragraph with English names embedded). Whichever language lingua-py picks gets the engine. Users override via `language` parameter. Documented; no test coverage required.

  **Behavior change relative to today's baseline** (flagged for the operator-facing docs): under the current uniform-spaCy multilingual setup, a code-switched paragraph routes through whichever spaCy model lingua-py's pick selects, and *both* languages' entities are likely to be over-flagged because of the flat 0.85 score plus the ORG-suppression-only multiplier. Under asymmetric routing, the same input has two failure modes: (a) lingua picks `de` → the German transformer runs, English-name PERSON detection falls back to whatever the German transformer can recognize on English-language proper nouns (likely degraded since the model is German-CoNLL-trained), or (b) lingua picks `en` → spaCy English runs, German PII content rides through unflagged entirely. **Either failure mode is potentially worse than today's uniform-over-flagging baseline for code-switched content.** CLARIFICATION Q6 explicitly accepted this trade-off; the `docs/v1-feature-spec.md` operator-facing note (§18.1) should explicitly warn: "for mixed-language paragraphs, set `language` explicitly to the language with the dominant PII content; do not rely on auto-detect." Out of scope for code/test changes in this feature; in scope for documentation.

### 12.3 Other live mis-detections in the baseline (cosmetic, not blockers)

A scan of `reports/post-fix-2.md` surfaces a few that are not part of this feature's scope but worth flagging for future iteration:
- `"Server at 192.168.1.42 went down."` — IP_ADDRESS(0.60) only — fine.
- `"Send the wire to IBAN GB82 WEST 1234 5698 7654 32."` — IBAN_CODE(1.00), **NRP(0.85)** — "WEST" is mistakenly an NRP (nationality/religious/political group). spaCy quirk, en_core_web_lg artefact. Not in scope.
- `"Routing number 121000248, account 9876543210."` — ABA_ROUTING_NUMBER(1.00), **UK_NHS(1.00)**, PHONE_NUMBER(0.75), US_BANK_NUMBER(0.40) — UK_NHS regex matches the routing number digits. Cross-recognizer false positive. Not in scope.
- Most of the de fixtures show extra PERSON(0.85) hits riding alongside the country recognizer hits — that's the bug being fixed.

None of these block this feature. The first two would be future-iteration cleanups.

---

## 13. Open Research Questions — Status

Mapping CLARIFICATION's "Open Questions" to this research:

| # | Question | Status | Where addressed |
|---|---|---|---|
| open Q1 | Can `NlpEngineProvider` mix engine types per language? | **Resolved: NO.** Workaround: custom `MultiNlpEngine` (Option C) recommended. | §3 |
| open Q2 | spaCy German interplay with transformer NER for lemma-aware recognizers | **Resolved: lemma-aware enhancers work** under `TransformersNlpEngine` because spaCy's parser/ner are disabled but the **lemmatizer remains** (`transformers_nlp_engine.py:88`), and `_doc_to_nlp_artifact` builds `lemmas` from `token.lemma_`. A small `de_core_news_sm` is sufficient. | §3.5, §4 |
| open Q3 | `low_score_entity_names` / `low_confidence_score_multiplier` defaults | **Deferred to calibration.** Current values documented (`spacy_multilingual.yaml:27-30`). New values empirical, set during implementation. | §6.5 |
| open Q4 | German model selection | **Resolved with empirical evidence (§4.5):** `xlm-roberta-large-finetuned-conll03-german` (primary, all 10 broader-class phrases clean; sentence-context PER/ORG/LOC preserved). `Davlan/bert-base-multilingual-cased-ner-hrl` (validated A/B target, also clean). `mschiesser/ner-bert-german` rejected on bug-class evidence (mis-tags 5 of 10 phrases as PER). flair model rejected on compatibility grounds. | §4, §4.5 |

---

## 14. Glossary Consolidation

Terms to add to `SDD/UBIQUITOUS_LANGUAGE.md` (the glossary doesn't yet exist; planning's `research-complete` step creates/updates it).

From CLARIFICATION:
- **asymmetric routing** — per-language NLP engine selection (spaCy for `en`, transformers for `de`).
- **detection-set non-regression** — non-regression measured by the set of flagged entity types per phrase, not by score levels.
- **calibration corpus** — the set of phrases `tools/calibration_report.py` runs through both Presidio and Redakt for tuning visibility. Source of truth: `tests/eval/fixtures/*.yaml`.
- **country recognizer** — regex-based Presidio recognizer keyed to a specific country's ID/document patterns (e.g., `DE_ID_NUMBER`, `UK_NHS`).
- **language auto-detect path** — existing lingua-py based per-request language detection that selects the active engine. Implementation: `src/redakt/services/language.py:detect_language`.
- **broader class** — the user-defined class of German identity/document/insurance common nouns that should never be flagged as any entity. Examples: `Personalausweis`, `Reisepassnummer`, `Krankenversicherungsnummer`, `Führerschein`, `Steuer-IdNr.`, `Sozialversicherungsnummer`, `Bundespersonalausweis`, `Aufenthaltstitel`, `Mitarbeiterausweis`, `Versicherungsnummer`.

New terms surfaced by this research:
- **NLP engine** — Presidio's abstraction for tokenization + lemma + NER. Three implementations ship: `SpacyNlpEngine`, `StanzaNlpEngine`, `TransformersNlpEngine`. This feature adds a fourth — `MultiNlpEngine` — that dispatches to a sub-engine per language.
- **per-entity score floor** — instance + per-request `dict[str, float]` map enforced by Redakt's `filter_by_entity_thresholds` post-filter. Distinct from Presidio's global `score_threshold`. Current values: `{"LOCATION": 0.90, "DATE_TIME": 0.95}`.
- **graded scores** — transformer NER scores that vary continuously per detection, in contrast to spaCy's flat 0.85 default (`presidio_analyzer/nlp_engine/ner_model_configuration.py:63-64`). Forces re-tuning of per-entity floors that were calibrated against the constant.
- **issubset assertion** — the eval suite's permissive check that flags only *missing* expected entities, not *extra* unexpected ones. Together with `expect_clean: true`, the only mechanism that catches over-detection is the latter. (Reference: `tests/eval/test_calibration.py:55`.)

---

## 15. Files That Matter (Index)

### 15.1 Core implementation files (this feature touches)

| Path | Why it matters |
|---|---|
| `presidio/presidio-analyzer/presidio_analyzer/conf/spacy_multilingual.yaml` | Current production NLP YAML; replaced or supplanted. |
| `presidio/presidio-analyzer/presidio_analyzer/conf/transformers.yaml` | Reference scaffold for transformers schema. |
| `presidio/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml` | Recognizer registry floor — must be preserved. |
| `presidio/presidio-analyzer/presidio_analyzer/conf/default_analyzer.yaml` | Top-level `supported_languages: [en, de]`, `default_score_threshold: 0`. |
| `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/nlp_engine_provider.py` | Single-engine constraint (lines 87-114). |
| `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/transformers_nlp_engine.py` | Reference for the spaCy+HF dual-pipe pattern (lines 73-100). Default model in `__init__` is `obi/deid_roberta_i2b2` at line 66; `dslim/bert-base-NER` appears only in the docstring example at line 36. |
| `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/spacy_nlp_engine.py` | Reference for `process_text`; `_doc_to_nlp_artifact` defined at lines 200-213 (with `lemmas = [token.lemma_ for token in doc]` on line 201). Inherited verbatim by `TransformersNlpEngine`. |
| `presidio/presidio-analyzer/presidio_analyzer/nlp_engine/ner_model_configuration.py` | `default_score: 0.85` source (lines 63-64, the `Field(default=0.85, ge=0.0, le=1.0, ...)` line); `low_score_entity_names`, `low_confidence_score_multiplier` definitions follow at 70-76. |
| `presidio/presidio-analyzer/presidio_analyzer/analyzer_engine_provider.py` | How conf files compose into `AnalyzerEngine` (lines 81-104). |
| `presidio/presidio-analyzer/presidio_analyzer/input_validation/schemas.py` | `validate_nlp_configuration` — needs a new branch for the `multi` engine schema or a `skip` annotation (Option C). |
| `presidio/presidio-analyzer/Dockerfile.transformers` | Image build (lines 16-30; `RUN poetry run python install_nlp_models.py` at line 30). |
| `presidio/presidio-analyzer/install_nlp_models.py` | Model bake-in at build time. Dispatcher `_download_model` at lines 54-68 (must be extended for `multi` per §2.6). spaCy download invoked at line 56 (spacy engine path) and line 87 (transformers engine path). HF model download via `snapshot_download` at line 91 + `AutoModelForTokenClassification.from_pretrained` at line 95. |
| `docker-compose.yml` (root) | Service composition; needs `dockerfile: Dockerfile.transformers` and updated `NLP_CONF_FILE` arg. |
| `src/redakt/config.py` | `entity_score_thresholds` (line 14), `default_score_threshold` (line 13), `supported_languages` (line 16). |
| `src/redakt/utils.py` | `filter_by_entity_thresholds` (lines 97-110), `merge_entity_thresholds` (lines 83-95). |
| `src/redakt/routers/detect.py` | Where the post-filter is invoked (line 117); shared `run_detection` orchestration (lines 60-127). |
| `src/redakt/services/presidio.py` | HTTP client; only relevant to Option B (would become per-language URL map). |
| `src/redakt/services/language.py` | lingua-py auto-detect; unchanged by this feature. |

### 15.2 Test/calibration files (this feature exercises)

| Path | Why it matters |
|---|---|
| `tests/eval/fixtures/de.yaml` | Where new German-noun phrases land. |
| `tests/eval/fixtures/{benign,generic,uk,us}.yaml` | English baseline; must not regress. |
| `tests/eval/_loader.py` | Fixture parser used by both eval and calibration tool. |
| `tests/eval/test_calibration.py:46-60` | Assertion semantic — the `issubset` line. |
| `tests/eval/conftest.py` | Session skip when Redakt not running. |
| `tools/calibration_report.py` | Calibration runner; no code change needed; corpus expanded via fixture additions. |
| `reports/post-fix-2.md` | Pre-feature baseline; the "before" against which the fix is measured. |

### 15.3 Documentation/decision files (this feature creates)

| Path | What it captures |
|---|---|
| `SDD/research/CLARIFICATION-007-transformers-nlp-backend.md` (exists) | Resolved design intent. |
| `SDD/research/RESEARCH-007-transformers-nlp-backend.md` (this file) | Research findings and analysis. |
| `SDD/UBIQUITOUS_LANGUAGE.md` (does not yet exist) | Glossary; to be created by `research-complete` from §14. |
| `SDD/adr/0001-nlp-engine-asymmetric-routing.md` (planning will create) | Architecture decision record. |
| `SDD/requirements/REQUIREMENTS-007-...` (planning will create) | Numbered requirements. |
| `SDD/implementation/...` (planning + implementation will create) | Implementation plan, test plan. |

---

## 16. Security Considerations

### 16.1 Authentication / Authorization

This feature touches the NLP engine, not auth. Redakt has no auth layer in v1; this is unchanged. The Presidio Analyzer container is reachable only on the internal compose network (`docker-compose.yml:21-25`); there's no external port. Per the v1 spec, "Presidio services are internal — only Redakt API talks to them."

### 16.2 Data privacy

PII still flows through:
- `POST /api/detect` request body (text) → Redakt → Presidio Analyzer → back to Redakt → response.
- Audit log records *metadata only* (`src/redakt/services/audit.py:log_detection`) — entity counts, types, language, source. Never the original text. **Preserved.**

The transformer model itself is read-only at inference; HF `pipeline()` doesn't transmit text outside the container. The `huggingface_hub.snapshot_download` in `install_nlp_models.py:79` is **build-time only** — runtime is offline-after-build.

### 16.3 Input validation

Unchanged. Existing input validation in:
- `src/redakt/utils.py:39-55` — allow-list term/length validation.
- `src/redakt/config.py:18` — `max_text_length: 512_000` (≈ 500KB).
- `src/redakt/services/language.py:43-78` — language config validation at startup.

No new input surface introduced. The `entity_score_thresholds` per-request body is already validated by Pydantic on the existing route (`src/redakt/models/detect.py` defines the schema).

### 16.4 Model supply chain

Pinning the HF model by ID (`xlm-roberta-large-finetuned-conll03-german`) means Redakt trusts whatever revision Hugging Face Hub serves at build time. For stronger reproducibility, planning may pin via `revision=` parameter (a specific commit hash) in `install_nlp_models.py` or via a `revision` key in the YAML schema. Out of scope for this research; flag for ADR consideration.

---

## 17. Testing Strategy

### 17.1 Unit tests

**No Redakt-side unit tests need to change.** The post-filter (`filter_by_entity_thresholds`) is unchanged. The Presidio client is unchanged. The language detector is unchanged.

**Presidio fork side:** if Option C is chosen, add unit tests for `MultiNlpEngine`:
- `process_text(text, "en")` dispatches to the spaCy sub-engine.
- `process_text(text, "de")` dispatches to the transformers sub-engine.
- `get_supported_languages` returns `["en", "de"]`.
- `is_stopword`, `is_punct` per language work.
- `is_loaded` is True iff all sub-engines are loaded.

### 17.2 Integration tests

The eval suite (`tests/eval/`) **is** the integration test. It hits the real Docker Compose stack on `localhost:8000`. New fixtures in `de.yaml` (§7.3) extend the suite.

**Add 5–10 `expect_clean: true` fixtures** to surface the broader-class assertion. Without them, no new CI signal exists.

### 17.3 Edge cases for the implementation to test

- **Code-switched text**: `"Hans Müller works at Acme Corp in Berlin."` (de+en mix) — accept whichever language lingua-py picks. No assertion needed beyond non-crash. **Note:** under asymmetric routing, code-switched text fails differently than under today's uniform spaCy multilingual setup (see §12.2). The non-regression bar for code-switched content is *non-crash*, not *non-degraded detection*. Existing `generic.yaml` fixtures that mix de+en (e.g., `"Anna Schmidt arbeitet bei der Beispiel AG in Berlin."`, which is German prose with German names) lingua-py-classifies as `de`; under the new model that fixture's expected entities (`PERSON` per the §4.5 probe + the existing fixture comment) still flag — verified empirically. The §4.5 transcript shows `Anna Schmidt arbeitet bei der Beispiel AG in Berlin.` correctly returns `PER AnnaSchmidt 1.0`, `ORG BeispielAG 1.0`, `LOC Berlin. 1.0` under the recommended model — so this fixture is **detection-set non-regression on de** (PERSON preserved; ORG and LOC are extras within the issubset envelope).
- **Pre-implementation model validation gate.** The §4.5 probe data is captured in research; planning should add a tracking REQ that during implementation calibration re-runs the same 20 phrases via Redakt's `/api/detect?verbose=true` after the model is wired into Presidio. If the in-Redakt probe diverges from §4.5 (e.g., a phrase that probed clean now flags), fall back to `Davlan/bert-base-multilingual-cased-ner-hrl` per §4.2.
- **Empty text** to `MultiNlpEngine.process_text` — should be handled by sub-engines as today. (`src/redakt/routers/detect.py:67-72` already short-circuits empty text before reaching Presidio.)
- **Long German text** (>tokenizer max length, ~512 tokens) — covered by `stride: 16` in the transformers config; verify on a long-document fixture.
- **PERSON name that *is* a German common noun** (e.g., the surname "Schmidt" *is* a common noun for "blacksmith") — the transformer should disambiguate from sentence context. The `generic.yaml` fixture `"Anna Schmidt arbeitet bei der Beispiel AG in Berlin."` exercises this and is empirically clean (§4.5). **Detection-set non-regression bar.**
- **PERSON + country-recognizer co-occurrence** — `"Hans Müller's Steuer-IdNr. ist 12345678903."` should flag both PERSON (on Müller) and DE_TAX_ID, but NOT flag PERSON on `Steuer-IdNr.`. The §4.5 control `"Hans Müllers Personalausweis ist abgelaufen."` confirms the model flags only `Hans Müllers` as PER and not `Personalausweis`; the same pattern is expected for `Steuer-IdNr.` Add as a new fixture.

### 17.4 Calibration runs (manual, operator-driven)

Per CLARIFICATION Q5b/Q5c, the implementation phase will iterate:
1. Build the analyzer image with the new YAML and chosen model.
2. `uv run python tools/calibration_report.py --raw --out` against the full fixture set.
3. Inspect the report: did all 41 existing fixtures stay PASS? Did the 5–10 new `expect_clean` fixtures stay PASS? Where do raw scores cluster?
4. Adjust `entity_score_thresholds`, `low_score_entity_names`, `low_confidence_score_multiplier` based on the gradient observed.
5. Repeat until both invariants hold.

The implementation plan should pencil in 2–3 calibration iterations.

---

## 18. Documentation Needs

### 18.1 User-facing

- **README.md / docs/** — note that the analyzer image now includes a transformer model (~2–3 GB image growth). First-time `docker compose up --build` is slower.
- **Code-switched-text limitation** — document in the user-facing README or `docs/v1-feature-spec.md`: "For mixed-language text, set `language` explicitly to override auto-detection."

### 18.2 Developer-facing

- **`docs/presidio-integration.md`** — update the "NLP Engine Options" section (currently lines 196-212) to reflect that Redakt uses `MultiNlpEngine` (asymmetric routing), not pure `spacy_multilingual`.
- **`SDD/adr/0001-...`** — the architecture decision record. Cross-cutting; binds future feature work.
- **`SDD/UBIQUITOUS_LANGUAGE.md`** — created or extended with §14's terms.

### 18.3 Configuration documentation

- **The new NLP YAML** — comment heavily, since the `multi` engine schema is fork-specific and operators need to understand it.
- **`src/redakt/config.py`** — if `entity_score_thresholds` defaults change, document the new values inline.
- **`.env`** — the new `REDAKT_ENTITY_SCORE_THRESHOLDS` example (if shipped) — document the JSON-string-via-env format.

---

## End of research document

Total citations to source: 70+ file:line references (revised after Step 2d citation pass). Every concrete claim about code behavior is anchored against the current revision of the Presidio fork (verified during Step 2d).

The German model recommendation is empirically grounded: §4.5 shows the §4 primary recommendation passes all 10 broader-class bare-noun probes plus sentence-context controls, while the originally-listed fallback (`mschiesser/ner-bert-german`) was empirically disqualified by the same probe.

Decisions deferred to planning: Option A vs B vs C (recommended C); model pinning revision (recommended yes); calibration value re-tuning (empirical, not a research output); cold-start `start_period` tuning (verify during implementation, may not need changing); model pinning hash for `xlm-roberta-large-finetuned-conll03-german` and `Davlan/bert-base-multilingual-cased-ner-hrl`.
