"""Tests for POST /api/deanonymize endpoint."""


class TestDeanonymizeEndpoint:
    def test_basic_deanonymize(self, client):
        resp = client.post("/api/deanonymize", json={
            "text": "Please review <PERSON_1>'s contract. His email is <EMAIL_ADDRESS_1>.",
            "mappings": {
                "<PERSON_1>": "John Smith",
                "<EMAIL_ADDRESS_1>": "john@example.com",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Please review John Smith's contract. His email is john@example.com."
        assert data["replacements_made"] == 2

    def test_no_mappings(self, client):
        resp = client.post("/api/deanonymize", json={
            "text": "No placeholders here.",
            "mappings": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "No placeholders here."
        assert data["replacements_made"] == 0

    def test_empty_text(self, client):
        resp = client.post("/api/deanonymize", json={
            "text": "",
            "mappings": {"<PERSON_1>": "John Smith"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == ""
        assert data["replacements_made"] == 0

    def test_placeholder_not_in_text(self, client):
        resp = client.post("/api/deanonymize", json={
            "text": "Hello world.",
            "mappings": {"<PERSON_1>": "John Smith"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Hello world."
        assert data["replacements_made"] == 0

    def test_multiple_occurrences(self, client):
        resp = client.post("/api/deanonymize", json={
            "text": "<PERSON_1> said hello to <PERSON_2>. <PERSON_1> smiled.",
            "mappings": {
                "<PERSON_1>": "Alice",
                "<PERSON_2>": "Bob",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Alice said hello to Bob. Alice smiled."
        assert data["replacements_made"] == 3

    def test_longest_placeholder_first(self, client):
        """Ensure <PERSON_10> is replaced before <PERSON_1> to avoid partial matches."""
        resp = client.post("/api/deanonymize", json={
            "text": "<PERSON_1> and <PERSON_10> met.",
            "mappings": {
                "<PERSON_1>": "Alice",
                "<PERSON_10>": "Bob",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Alice and Bob met."
        assert data["replacements_made"] == 2

    def test_missing_text_field(self, client):
        resp = client.post("/api/deanonymize", json={"mappings": {}})
        assert resp.status_code == 422

    def test_missing_mappings_field(self, client):
        resp = client.post("/api/deanonymize", json={"text": "hello"})
        assert resp.status_code == 422

    def test_round_trip_with_anonymize(self, client, mock_presidio_analyze, mock_anon_detect_language):
        """Full round-trip: anonymize then deanonymize restores original text."""
        original = "Contact John Smith at john@example.com please."
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85,
             "analysis_explanation": None, "recognition_metadata": None},
            {"entity_type": "EMAIL_ADDRESS", "start": 22, "end": 38, "score": 1.0,
             "analysis_explanation": None, "recognition_metadata": None},
        ]

        # Anonymize
        anon_resp = client.post("/api/anonymize", json={"text": original})
        assert anon_resp.status_code == 200
        anon_data = anon_resp.json()

        # Deanonymize
        deanon_resp = client.post("/api/deanonymize", json={
            "text": anon_data["anonymized_text"],
            "mappings": anon_data["mappings"],
        })
        assert deanon_resp.status_code == 200
        assert deanon_resp.json()["text"] == original
