"""Tests for per-entity score thresholds (post-filter on Presidio results)."""

from unittest.mock import patch

from redakt.utils import filter_by_entity_thresholds, merge_entity_thresholds


class TestMergeEntityThresholds:
    def test_empty_inputs(self):
        assert merge_entity_thresholds({}, None) == {}
        assert merge_entity_thresholds({}, {}) == {}

    def test_instance_only(self):
        assert merge_entity_thresholds({"LOCATION": 0.85}, None) == {"LOCATION": 0.85}

    def test_request_only(self):
        assert merge_entity_thresholds({}, {"PERSON": 0.5}) == {"PERSON": 0.5}

    def test_request_overrides_instance_per_key(self):
        merged = merge_entity_thresholds(
            {"LOCATION": 0.85, "DATE_TIME": 0.95},
            {"LOCATION": 0.5},
        )
        assert merged == {"LOCATION": 0.5, "DATE_TIME": 0.95}

    def test_request_adds_new_key(self):
        merged = merge_entity_thresholds(
            {"LOCATION": 0.85},
            {"PERSON": 0.7},
        )
        assert merged == {"LOCATION": 0.85, "PERSON": 0.7}


class TestFilterByEntityThresholds:
    def _result(self, entity_type: str, score: float) -> dict:
        return {
            "entity_type": entity_type,
            "start": 0,
            "end": 5,
            "score": score,
            "analysis_explanation": None,
            "recognition_metadata": None,
        }

    def test_empty_thresholds_passes_through(self):
        results = [self._result("LOCATION", 0.5)]
        assert filter_by_entity_thresholds(results, {}) == results

    def test_drops_below_floor(self):
        results = [self._result("LOCATION", 0.5)]
        assert filter_by_entity_thresholds(results, {"LOCATION": 0.85}) == []

    def test_keeps_at_or_above_floor(self):
        results = [self._result("LOCATION", 0.85), self._result("LOCATION", 0.95)]
        out = filter_by_entity_thresholds(results, {"LOCATION": 0.85})
        assert len(out) == 2

    def test_unlisted_entity_unaffected(self):
        results = [self._result("PERSON", 0.4)]
        assert filter_by_entity_thresholds(results, {"LOCATION": 0.85}) == results

    def test_mixed_entities(self):
        results = [
            self._result("LOCATION", 0.5),  # filtered
            self._result("LOCATION", 0.9),  # kept
            self._result("PERSON", 0.4),    # kept (no floor)
            self._result("DATE_TIME", 0.8), # filtered
        ]
        out = filter_by_entity_thresholds(
            results, {"LOCATION": 0.85, "DATE_TIME": 0.95}
        )
        assert len(out) == 2
        types = {r["entity_type"] for r in out}
        assert types == {"LOCATION", "PERSON"}


# Sample analyzer results that mix a borderline LOCATION/DATE_TIME with a clear PERSON
MUNICH_RESULTS = [
    {"entity_type": "LOCATION", "start": 14, "end": 20, "score": 0.6,
     "analysis_explanation": None, "recognition_metadata": None},
    {"entity_type": "DATE_TIME", "start": 21, "end": 26, "score": 0.85,
     "analysis_explanation": None, "recognition_metadata": None},
    {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.85,
     "analysis_explanation": None, "recognition_metadata": None},
]


class TestDetectEntityThresholds:
    """Integration tests via /api/detect."""

    def test_default_filters_munich_today(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """Out-of-the-box defaults drop borderline LOCATION/DATE_TIME but keep PERSON."""
        mock_presidio_analyze.return_value = MUNICH_RESULTS
        resp = client.post(
            "/api/detect?verbose=true",
            json={"text": "John Smith Munich today"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_count"] == 1
        assert data["entities_found"] == ["PERSON"]
        assert len(data["details"]) == 1
        assert data["details"][0]["entity_type"] == "PERSON"

    def test_request_override_lowers_floor(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """Per-request override below the global default lets borderline LOCATION through."""
        mock_presidio_analyze.return_value = MUNICH_RESULTS
        resp = client.post(
            "/api/detect?verbose=true",
            json={
                "text": "John Smith Munich today",
                "entity_score_thresholds": {"LOCATION": 0.5},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        types = {d["entity_type"] for d in data["details"]}
        # LOCATION (0.6) now passes the lowered 0.5 floor; DATE_TIME (0.85) still filtered (default 0.95)
        assert types == {"PERSON", "LOCATION"}

    def test_request_override_raises_floor(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """Per-request override can also raise a floor for an entity not in the global map."""
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.6,
             "analysis_explanation": None, "recognition_metadata": None},
        ]
        resp = client.post(
            "/api/detect",
            json={
                "text": "John Smith",
                "entity_score_thresholds": {"PERSON": 0.9},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["entity_count"] == 0

    def test_empty_global_map_matches_legacy_behavior(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """With the global map cleared and no per-request override, all results pass through."""
        mock_presidio_analyze.return_value = MUNICH_RESULTS
        with patch("redakt.routers.detect.settings") as mock_settings:
            mock_settings.allow_list = []
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.default_score_threshold = 0.35
            mock_settings.entity_score_thresholds = {}
            resp = client.post(
                "/api/detect?verbose=true",
                json={"text": "John Smith Munich today"},
            )
        assert resp.status_code == 200
        assert resp.json()["entity_count"] == 3


class TestAnonymizeEntityThresholds:
    """Integration tests via /api/anonymize."""

    def test_default_filters_munich_today(
        self, client, mock_presidio_analyze, mock_anon_detect_language
    ):
        text = "John Smith Munich today"
        mock_presidio_analyze.return_value = MUNICH_RESULTS
        resp = client.post("/api/anonymize", json={"text": text})
        assert resp.status_code == 200
        data = resp.json()
        # Only PERSON is anonymized; "Munich" and "today" remain in the text
        assert "Munich" in data["anonymized_text"]
        assert "today" in data["anonymized_text"]
        assert "<PERSON_1>" in data["anonymized_text"]
        assert set(data["mappings"].keys()) == {"<PERSON_1>"}

    def test_request_override(
        self, client, mock_presidio_analyze, mock_anon_detect_language
    ):
        text = "John Smith Munich today"
        mock_presidio_analyze.return_value = MUNICH_RESULTS
        resp = client.post(
            "/api/anonymize",
            json={
                "text": text,
                "entity_score_thresholds": {"LOCATION": 0.5, "DATE_TIME": 0.5},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # All three entities now anonymized
        assert "Munich" not in data["anonymized_text"]
        assert "today" not in data["anonymized_text"]
        assert len(data["mappings"]) == 3
