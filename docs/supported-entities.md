# Supported Entities

This is the canonical list of PII entity types that Microsoft Presidio (and therefore Redakt) can detect. Use these names when configuring `entity_score_thresholds`, `entities` filters, or allow lists.

The list is grouped by category. Generic entities work in any language with an NLP model loaded; country-specific entities are scoped to that country's language code.

## Generic — multilingual (NLP-based)

Detected by the configured NLP engine (spaCy or Hugging Face transformers). Confidence varies by model and context — these are the entities most likely to need per-entity score tuning.

| Entity | Description |
|---|---|
| `PERSON` | A full name |
| `LOCATION` | Cities, countries, addresses, geographic features |
| `ORGANIZATION` | Companies, agencies, institutions |
| `NRP` | Nationality, religious or political group |
| `DATE_TIME` | Absolute or relative dates and times |

## Generic — pattern / checksum-based

Regex- or checksum-validated. These typically come back at near-1.0 confidence and rarely need tuning.

| Entity | Description |
|---|---|
| `BIC_CODE` | ISO 9362 Business Identifier Code (SWIFT) — 8 or 11 chars, ISO 3166-1 alpha-2 country slot |
| `CREDIT_CARD` | Major credit card numbers (Luhn-validated) |
| `CRYPTO` | Cryptocurrency wallet addresses |
| `EMAIL_ADDRESS` | Email addresses |
| `EU_VAT_ID` | EU VAT identification number (any of the 27 EU country prefixes) |
| `IBAN_CODE` | International bank account numbers |
| `IP_ADDRESS` | IPv4 / IPv6 addresses |
| `MAC_ADDRESS` | Hardware MAC addresses |
| `MEDICAL_LICENSE` | Generic medical license numbers (DEA) |
| `PHONE_NUMBER` | International / regional phone numbers |
| `SEPA_CREDITOR_ID` | SEPA Creditor Identifier (EPC scheme) — 8-35 chars, ISO 3166-1 alpha-2 country slot |
| `URL` | Web URLs |

## Country-specific

These recognizers are registered per language code in Presidio. To detect them, the request must use that country's language and the corresponding NLP model must be loaded.

### 🇺🇸 United States (`en`)

| Entity | Description |
|---|---|
| `US_SSN` | Social Security Number |
| `US_PASSPORT` | US passport number |
| `US_DRIVER_LICENSE` | State-issued driver's license number |
| `US_ITIN` | Individual Taxpayer Identification Number |
| `US_BANK_NUMBER` | US bank account number |
| `US_NPI` | National Provider Identifier (healthcare) |
| `US_MBI` | Medicare Beneficiary Identifier |
| `ABA_ROUTING_NUMBER` | ABA bank routing number |

### 🇬🇧 United Kingdom (`en`)

| Entity | Description |
|---|---|
| `UK_NHS` | National Health Service number |
| `UK_NINO` | National Insurance Number |
| `UK_PASSPORT` | UK passport number |
| `UK_POSTCODE` | UK postal code |
| `UK_VEHICLE_REGISTRATION` | UK vehicle registration plate |

### 🇩🇪 Germany (`de`, also `en`)

German recognizers are registered under both `de` and `en` so cross-border correspondence from English-speaking subsidiaries surfaces the same identifiers as native-German text. Low-base context-gated recognizers (`DE_PLZ`, `DE_KFZ`, `DE_HEALTH_INSURANCE`, `DE_FUEHRERSCHEIN`, `DE_ZAEHLERNUMMER`) only fire when a German CONTEXT keyword sits in the surrounding window; high-base structural recognizers (`DE_VAT_ID`, `DE_TAX_ID`, `DE_MASTR_ID`, `DE_ID_CARD`, `DE_PASSPORT`, `DE_MELO`) fire on shape alone.

| Entity | Description |
|---|---|
| `DE_TAX_ID` | Steuerliche Identifikationsnummer |
| `DE_TAX_NUMBER` | Steuernummer |
| `DE_VAT_ID` | Umsatzsteuer-Identifikationsnummer |
| `DE_ID_CARD` | Personalausweis number |
| `DE_PASSPORT` | German passport number |
| `DE_FUEHRERSCHEIN` | German driver's license |
| `DE_PLZ` | Postleitzahl (postal code) |
| `DE_KFZ` | Kfz-Kennzeichen (vehicle plate) |
| `DE_HEALTH_INSURANCE` | Krankenversicherungsnummer |
| `DE_SOCIAL_SECURITY` | Sozialversicherungsnummer |
| `DE_LANR` | Lebenslange Arztnummer (physician ID) |
| `DE_BSNR` | Betriebsstättennummer (medical practice ID) |
| `DE_HANDELSREGISTER` | Commercial register number |
| `DE_MASTR_ID` | Marktstammdatenregister-Nummer (BNetzA energy-market identifier) |
| `DE_EEG_ANLAGE` | Anlagenschlüssel — 33-char EEG plant identifier (BDEW BK6-13-200) |
| `DE_MALO` | Marktlokations-ID — 11-digit market-location ID, BDEW Mod-10 checksum-validated to score 1.0 |
| `DE_MELO` | Messlokations-ID — 33-char DE-prefixed metering-location ID (VDE-AR-N 4400) |
| `DE_ZAEHLERNUMMER` | Zählernummer — 8-15 alphanumeric meter number, context-required |

### 🇮🇹 Italy (`it`)

| Entity | Description |
|---|---|
| `IT_FISCAL_CODE` | Codice fiscale |
| `IT_VAT_CODE` | Partita IVA |
| `IT_IDENTITY_CARD` | Italian identity card |
| `IT_DRIVER_LICENSE` | Italian driver's license |
| `IT_PASSPORT` | Italian passport |

### 🇪🇸 Spain (`es`)

| Entity | Description |
|---|---|
| `ES_NIF` | Número de Identificación Fiscal |
| `ES_NIE` | Número de Identidad de Extranjero |

### 🇦🇺 Australia (`en`)

| Entity | Description |
|---|---|
| `AU_ABN` | Australian Business Number |
| `AU_ACN` | Australian Company Number |
| `AU_TFN` | Tax File Number |
| `AU_MEDICARE` | Medicare card number |

### 🇮🇳 India (`en`)

| Entity | Description |
|---|---|
| `IN_AADHAAR` | Aadhaar card number |
| `IN_PAN` | Permanent Account Number |
| `IN_PASSPORT` | Indian passport |
| `IN_VOTER` | Voter ID |
| `IN_VEHICLE_REGISTRATION` | Vehicle registration |
| `IN_GSTIN` | Goods and Services Tax Identification Number |

### 🇰🇷 South Korea (`ko`)

| Entity | Description |
|---|---|
| `KR_RRN` | Resident Registration Number |
| `KR_BRN` | Business Registration Number |
| `KR_FRN` | Foreign Registration Number |
| `KR_PASSPORT` | Korean passport |
| `KR_DRIVER_LICENSE` | Korean driver's license |

### 🇸🇬 Singapore (`en`)

| Entity | Description |
|---|---|
| `SG_NRIC_FIN` | National Registration Identity Card / Foreign ID |
| `SG_UEN` | Unique Entity Number |

### 🇳🇬 Nigeria (`en`)

| Entity | Description |
|---|---|
| `NG_NIN` | National Identification Number |
| `NG_VEHICLE_REGISTRATION` | Vehicle registration |

### 🇵🇱 Poland (`pl`)

| Entity | Description |
|---|---|
| `PL_PESEL` | PESEL personal number |

### 🇫🇮 Finland (`fi`)

| Entity | Description |
|---|---|
| `FI_PERSONAL_IDENTITY_CODE` | Henkilötunnus |

### 🇹🇭 Thailand (`th`)

| Entity | Description |
|---|---|
| `TH_TNIN` | Thai National ID |

## Notes

- **Language scoping.** A country-specific recognizer fires only when the request's `language` matches the language the recognizer was registered under, and an NLP model for that language is loaded. Redakt's default `supported_languages` is `["en", "de"]`, so US, UK, and DE recognizers are reachable out of the box; IT, PL, ES and others require loading additional NLP models in the Presidio container. German recognizers are dual-registered under `en` to cover cross-border traffic from English-speaking EU subsidiaries.
- **Overlap is expected.** Several recognizer pairs intentionally fire on the same span: `EU_VAT_ID` + `DE_VAT_ID` on `DE` VAT prefixes; `SEPA_CREDITOR_ID` + `IBAN_CODE` on IBAN-shaped spans ≥ 15 chars (IBAN's checksum validation promotes it to score 1.0 so it wins by score); `DE_MELO` + `DE_EEG_ANLAGE` on DE-prefixed 33-char spans. The anonymization template picks one winner per span; subset-matching in the eval suite tolerates the extras.
- **spaCy NLP entities have flat ~0.85 confidence.** When Redakt is deployed with the spaCy backend (`presidio/docker-compose-text.yml`), the NLP recognizer assigns a constant ~0.85 score to every `PERSON`, `LOCATION`, `ORGANIZATION`, `NRP`, and `DATE_TIME` it detects. Per-entity score thresholds for these entities are therefore effectively binary: a floor at or below 0.85 keeps every detection; a floor above 0.85 drops them all. The transformers backend (`presidio/docker-compose-transformers.yml`) returns varied confidence and tunes more gradually.
- **NLP entities are noisier.** `PERSON`, `LOCATION`, `ORGANIZATION`, `NRP`, `DATE_TIME` are model-driven, so they overfire on generic terms (cities, common temporal words). The defaults — `LOCATION: 0.90`, `DATE_TIME: 0.95` — are tuned to disable both on spaCy out of the box, since the original motivating bug ("Munich today" being flagged) was an artifact of that overfiring.
- **Pattern entities are sharper.** `CREDIT_CARD`, `IBAN_CODE`, the country ID numbers, etc. are regex + checksum, so they typically score very high or don't fire at all.
- **Custom entities.** Presidio supports user-defined recognizers, which can introduce arbitrary additional entity names. Anything you register is detectable.
- **Optional third-party recognizers** (Azure AI Language, Hugging Face NER, GLiNER) live under `presidio/presidio-analyzer/presidio_analyzer/predefined_recognizers/third_party/` and are not enabled by default in Redakt's compose stack.
