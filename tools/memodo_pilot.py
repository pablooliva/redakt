"""Memodo PV-wholesale 10-phrase calibration pilot.

Probes Redakt's /api/detect against realistic German B2B PV traffic to
surface gaps before promoting any of these into the canonical eval
fixtures under tests/eval/fixtures/. Each phrase is a multi-PII
positive built from typical Memodo contexts: installer onboarding,
quote requests, RMA tickets, order confirmations, internal escalations,
site reports, manufacturer correspondence, customer complaints,
end-customer referrals, and address-block-heavy order paperwork.

Policy decisions baked into `expected`:
  - Brand / product names (Sungrow, Huawei, Tesla, Fronius, JA Solar,
    LG Chem, Trina, SMA, Tigo, BYD, DHL) are NOT PII — must NOT appear.
  - Memodo employee names ARE PII (treated as customer PII per GDPR).
  - EEG / MaStR plant IDs ARE PII (no recognizer exists yet — will
    show up as recall miss; that's the point of including them).

Run from repo root with the dev compose stack up:
    uv run python tools/memodo_pilot.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

REDAKT_URL = "http://localhost:8000"


@dataclass
class Phrase:
    label: str
    text: str
    language: str
    expected: set[str]
    notes: str = ""


PHRASES: list[Phrase] = [
    Phrase(
        label="01-installer-onboarding",
        text=(
            "Sehr geehrte Damen und Herren, hiermit möchte sich die Solarprofi "
            "Müller GmbH (USt-IdNr. DE123456789) für ein Kundenkonto bei Memodo "
            "bewerben. Geschäftsführer Hans Müller, erreichbar unter "
            "+49 89 12345678 oder hans.mueller@solarprofi-mueller.de. "
            "Lieferadresse: Solarweg 12, 80331 München."
        ),
        language="de",
        expected={
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
            "DE_VAT_ID", "LOCATION", "DE_PLZ",
        },
        notes="Memodo is the operator of Redakt — the brand 'Memodo' itself should not redact (own-brand reference, not customer PII).",
    ),
    Phrase(
        label="02-quote-request-with-products",
        text=(
            "Hallo Memodo-Team, für unser Bauvorhaben in 73230 Kirchheim/Teck "
            "benötigen wir 24x Sungrow SH10RT Hybridwechselrichter sowie "
            "48x BYD Battery-Box Premium HVS 10.2. Bitte um Angebot bis Ende der "
            "Woche an info@energiehaus-koch.de oder telefonisch unter 07021 88512. "
            "Vielen Dank, Markus Koch."
        ),
        language="de",
        expected={"DE_PLZ", "EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "LOCATION"},
        notes="Sungrow SH10RT and BYD Battery-Box must NOT fire (brands).",
    ),
    Phrase(
        label="03-rma-ticket",
        text=(
            "Reklamation Auftrag #A-2024-87432. Ein Fronius Symo 10.0-3-M "
            "Wechselrichter (Seriennummer F1234567) zeigt seit gestern den "
            "Fehlercode 'State 1015'. Endkunde Familie Schneider, "
            "Anlagenstandort Hauptstraße 47, 86150 Augsburg. Anlagenbetreiber "
            "meldet sich unter 0821 4567890 bei Techniker Tobias Weber."
        ),
        language="de",
        expected={"PERSON", "LOCATION", "DE_PLZ", "PHONE_NUMBER"},
        notes="Fronius Symo 10.0-3-M and serial F1234567 must NOT fire.",
    ),
    Phrase(
        label="04-order-confirmation-employee-customer",
        text=(
            "Liebe Frau Bauer, Ihre Bestellung BE-91823 (12x Tigo TS4-A-O "
            "Optimierer) wird voraussichtlich am 15.05.2026 an die von Ihnen "
            "angegebene Baustelle in Linz, Österreich (PLZ 4020) geliefert. "
            "Bei Rückfragen wenden Sie sich bitte an Ihren Memodo-"
            "Vertriebsmitarbeiter Stefan Hofer unter +43 732 7654321."
        ),
        language="de",
        expected={"PERSON", "LOCATION", "PHONE_NUMBER", "DATE_TIME"},
        notes="AT phone (+43); AT 4-digit PLZ (4020) won't match DE_PLZ regex (5-digit) — clean miss expected.",
    ),
    Phrase(
        label="05-internal-escalation-bank",
        text=(
            "Kollegen, der Kunde Photovoltaik Express Bayern UG (Inhaber "
            "Lars Fischer, lars.fischer@pv-express.bayern) hat seine Rechnung "
            "R-2024-4456 über 14.892,33 EUR noch nicht beglichen. Letzte "
            "Zahlung kam von IBAN DE89 3704 0044 0532 0130 00. Bitte Mahnung "
            "versenden. Grüße, Anna Berger"
        ),
        language="de",
        expected={"PERSON", "EMAIL_ADDRESS", "IBAN_CODE"},
        notes="Anna Berger is Memodo employee — must redact per policy.",
    ),
    Phrase(
        label="06-site-visit-with-mastr",
        text=(
            "Aufmaß bei Bauernhof Hubert Maier, Dorfstraße 8, 94032 Passau am "
            "12.05.2026. Geplant: 18 kWp PV-Anlage mit 36x JA Solar JAM72S20-450 "
            "Modulen auf der Süd-Dachfläche, gekoppelt mit einem Huawei "
            "SUN2000-15KTL-M2 Wechselrichter. Anlagenbetreiber-Kontakt: "
            "0851 666999. MaStR-Nummer SEE901234567890."
        ),
        language="de",
        expected={"PERSON", "LOCATION", "DE_PLZ", "PHONE_NUMBER", "DATE_TIME", "MASTR_ID"},
        notes="MASTR_ID is a custom-recognizer placeholder — will be MISSED (no recognizer exists). Brands JA Solar / Huawei must NOT fire.",
    ),
    Phrase(
        label="07-english-mfg-correspondence",
        text=(
            "Hi Sarah, regarding our purchase order PO-44231 for 200 units of "
            "LG Chem RESU10H batteries: do you have an updated ETA? The shipment "
            "was originally promised by March 28, 2026. Our customer in Hamburg "
            "(installation site PLZ 20095) is asking for an exact date. Best "
            "regards, Dr. Lukas Brandt, Memodo GmbH (lukas.brandt@memodo.de, "
            "+49 89 9876543)."
        ),
        language="en",
        expected={"PERSON", "LOCATION", "EMAIL_ADDRESS", "PHONE_NUMBER", "DATE_TIME"},
        notes="English fixture; LG Chem must NOT fire. UK_POSTCODE could spuriously match 20095.",
    ),
    Phrase(
        label="08-customer-complaint-callback",
        text=(
            "Beschwerde von Familie Wagner, Mozartstraße 23, 70197 Stuttgart. "
            "Ihre installierte Anlage (System-ID PV-2024-09812) liefert seit "
            "der Inbetriebnahme nur 60% der prognostizierten Leistung. "
            "Rückrufwunsch heute zwischen 16 und 18 Uhr unter 0711 33445566. "
            "Bearbeitung durch Service-Team, zugewiesen an Julia Krause (Memodo)."
        ),
        language="de",
        expected={"PERSON", "LOCATION", "DE_PLZ", "PHONE_NUMBER", "DATE_TIME"},
        notes="System-ID PV-2024-09812 must NOT fire (internal ref). Julia Krause is Memodo employee.",
    ),
    Phrase(
        label="09-end-customer-referral",
        text=(
            "Hallo, mein Endkunde Friedrich Hartmann, geboren am 03.07.1962, "
            "wohnhaft Lindenallee 17, 04317 Leipzig, möchte ein Angebot für eine "
            "9,8 kWp Anlage. Ausweisnummer L01X00T47 für die KfW-Förderung "
            "benötigt. Telefon: 0341 2233445. Sein bisheriger Stromverbrauch "
            "laut Jahresabrechnung 4.800 kWh. Mit freundlichen Grüßen, Klaus "
            "Wagner, Solar Wagner GbR."
        ),
        language="de",
        expected={"PERSON", "LOCATION", "DE_PLZ", "DE_ID_CARD", "PHONE_NUMBER", "DATE_TIME"},
        notes="9,8 kWp and 4.800 kWh are units — must NOT fire as numerics.",
    ),
    Phrase(
        label="10-multi-address-order",
        text=(
            "Auftragsbestätigung Bestellung 88123-A. Rechnungsadresse: "
            "Sonnenkraft Anlagenbau GmbH & Co. KG, Industriering 4, 27412 "
            "Tarmstedt, USt-IdNr. DE987654321. Lieferadresse: Baustelle Familie "
            "Petersen, Am Deich 9, 27619 Schiffdorf. Material: 30x Trina Solar "
            "Vertex S+ 440W Glasmodule, 1x SMA Sunny Tripower 25000TL-30 "
            "Wechselrichter. Versand voraussichtlich 14.05.2026 mit DHL. Bei "
            "Rückfragen: Memodo Vertrieb DACH, Christina Lehmann, "
            "+49 89 4242000, christina.lehmann@memodo.de."
        ),
        language="de",
        expected={
            "PERSON", "LOCATION", "DE_PLZ", "DE_VAT_ID",
            "PHONE_NUMBER", "EMAIL_ADDRESS", "DATE_TIME",
        },
        notes="Trina / SMA brands must NOT fire. DHL is a carrier — likely ORG, but not customer PII.",
    ),
]


# Thresholds are configured globally via REDAKT_ENTITY_SCORE_THRESHOLDS
# in the .env file (or via per-request override on /api/detect when a
# specific consumer needs to deviate). The pilot intentionally uses no
# per-request override so it exercises the same policy any consumer
# would see.
def detect(client: httpx.Client, phrase: Phrase) -> dict:
    response = client.post(
        f"{REDAKT_URL}/api/detect?verbose=true",
        json={"text": phrase.text, "language": phrase.language},
    )
    response.raise_for_status()
    return response.json()


def run() -> None:
    print(f"Hitting {REDAKT_URL} with {len(PHRASES)} Memodo pilot phrases\n")
    print("=" * 78)

    totals = {"expected": 0, "found": 0, "tp": 0, "fn": 0, "fp": 0}
    spurious_tally: dict[str, int] = {}

    # trust_env=False bypasses any HTTP(S)_PROXY env vars (e.g., the
    # Socket Firewall sandbox that intercepts Python network calls but
    # not curl/system traffic to localhost).
    with httpx.Client(timeout=30.0, trust_env=False) as client:
        for ph in PHRASES:
            body = detect(client, ph)
            details = body.get("details", [])
            found_entities = {d["entity_type"] for d in details}

            tp = ph.expected & found_entities
            fn = ph.expected - found_entities
            fp = found_entities - ph.expected

            totals["expected"] += len(ph.expected)
            totals["found"] += len(found_entities)
            totals["tp"] += len(tp)
            totals["fn"] += len(fn)
            totals["fp"] += len(fp)
            for e in fp:
                spurious_tally[e] = spurious_tally.get(e, 0) + 1

            print(f"\n[{ph.label}]  language={ph.language}")
            print(f"  expected:  {sorted(ph.expected)}")
            print(f"  found:     {sorted(found_entities)}")
            if fn:
                print(f"  MISSED:    {sorted(fn)}")
            if fp:
                fp_with_text = sorted(
                    f"{d['entity_type']}('{ph.text[d['start']:d['end']]}', {d['score']:.2f})"
                    for d in details if d["entity_type"] in fp
                )
                print(f"  SPURIOUS:  {fp_with_text}")
            if not fn and not fp:
                print(f"  CLEAN MATCH ✓")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    tp, fn, fp = totals["tp"], totals["fn"], totals["fp"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    print(f"  expected entities (positives across all phrases): {totals['expected']}")
    print(f"  found entities (any detection):                   {totals['found']}")
    print(f"  true positives:    {tp}")
    print(f"  false negatives:   {fn}  (missed: real PII not detected)")
    print(f"  false positives:   {fp}  (spurious: detected something not in expected)")
    print(f"  precision (entity-type level): {precision:.2%}")
    print(f"  recall    (entity-type level): {recall:.2%}")
    print(f"  F1:                            {f1:.2%}")
    if spurious_tally:
        print(f"\n  spurious entity types by frequency:")
        for ent, count in sorted(spurious_tally.items(), key=lambda kv: -kv[1]):
            print(f"    {ent}: {count}x")


if __name__ == "__main__":
    run()
