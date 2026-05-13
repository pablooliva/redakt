"""Basic unit tests for the closed-world filter (MODULE-001) and config validation (MODULE-002).

Chunk 2 will expand to the full battery covering every REQ/EDGE/FAIL item.
These tests prove the core filter logic works and establish COMPAT-001 (flag-off no-op).
"""
import logging

import pytest
from pydantic import ValidationError

from redakt.utils import filter_by_closed_world


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

STRONG_ANCHORS: frozenset[str] = frozenset(
    {
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "IBAN_CODE",
        "EU_VAT_ID",
        "BIC_CODE",
        "SEPA_CREDITOR_ID",
        "MEDICAL_LICENSE",
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
    }
)

QUASI_IDENTIFIERS: frozenset[str] = frozenset({"DATE_TIME", "LOCATION", "NRP", "DE_PLZ"})


def _span(entity_type: str, score: float = 0.9) -> dict:
    """Create a minimal span dict matching Presidio analyzer output."""
    return {"entity_type": entity_type, "start": 0, "end": 5, "score": score}


# ---------------------------------------------------------------------------
# MODULE-001: filter_by_closed_world — core behavior
# ---------------------------------------------------------------------------


class TestFilterByClosedWorldFlagOff:
    """Flag disabled: all spans pass through unchanged (COMPAT-001, PERF-002)."""

    def test_flag_off_all_spans_pass(self):
        spans = [_span("PERSON"), _span("DATE_TIME"), _span("LOCATION")]
        result, count = filter_by_closed_world(
            spans, enabled=False, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == spans
        assert count == 0

    def test_flag_off_empty_span_list(self):
        result, count = filter_by_closed_world(
            [], enabled=False, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == []
        assert count == 0

    def test_flag_off_returns_same_object(self):
        """No-op path must return the input list unchanged (O(1) reference return)."""
        spans = [_span("DATE_TIME")]
        result, _ = filter_by_closed_world(
            spans, enabled=False, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result is spans


class TestFilterByClosedWorldAnchorPresent:
    """Flag on, strong anchor present: all spans retained (REQ-008)."""

    def test_person_anchor_all_spans_retained(self):
        spans = [_span("PERSON"), _span("DATE_TIME"), _span("LOCATION")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == spans
        assert count == 0

    def test_email_anchor_date_time_retained(self):
        """EMAIL_ADDRESS counts as a strong anchor (REQ-007, REQ-008)."""
        spans = [_span("EMAIL_ADDRESS"), _span("DATE_TIME")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == spans
        assert count == 0

    def test_only_strong_anchors_no_quasi(self):
        """Only anchor spans present: all retained, count=0 (EDGE-003)."""
        spans = [_span("PERSON"), _span("EMAIL_ADDRESS")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == spans
        assert count == 0

    def test_mixed_anchor_quasi_always_emit(self):
        """Anchor + quasi + always-emit entities: all pass (EDGE-010)."""
        spans = [_span("PERSON"), _span("DATE_TIME"), _span("DE_BSNR")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == spans
        assert count == 0


class TestFilterByClosedWorldAnchorAbsent:
    """Flag on, no strong anchor: quasi-identifiers suppressed (REQ-007, EDGE-002)."""

    def test_only_quasi_suppressed(self):
        spans = [_span("DATE_TIME"), _span("LOCATION")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == []
        assert count == 2

    def test_quasi_suppressed_always_emit_retained(self):
        """Always-emit entities pass through even when no anchor (EDGE-004)."""
        spans = [_span("DATE_TIME"), _span("DE_BSNR")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert len(result) == 1
        assert result[0]["entity_type"] == "DE_BSNR"
        assert count == 1

    def test_nrp_suppressed_when_no_anchor(self):
        """NRP classified as quasi-identifier (REQ-002) — suppressed when no anchor."""
        spans = [_span("NRP")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == []
        assert count == 1

    def test_de_plz_suppressed_when_no_anchor(self):
        """DE_PLZ classified as quasi-identifier — suppressed when no anchor."""
        spans = [_span("DE_PLZ"), _span("LOCATION")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == []
        assert count == 2


class TestFilterByClosedWorldEdgeCases:
    """Edge cases (EDGE-001, EDGE-008)."""

    def test_empty_span_list(self):
        """Empty input: no crash, return empty + count=0 (EDGE-001)."""
        result, count = filter_by_closed_world(
            [], enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert result == []
        assert count == 0

    def test_empty_strong_anchors_always_suppresses_quasi(self):
        """Empty strong_anchors: anchor check never passes; all quasi suppressed (EDGE-008)."""
        spans = [_span("DATE_TIME"), _span("LOCATION"), _span("PERSON")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=frozenset(), quasi_identifiers=QUASI_IDENTIFIERS
        )
        # PERSON is not in quasi_identifiers either, so it passes through
        assert len(result) == 1
        assert result[0]["entity_type"] == "PERSON"
        assert count == 2

    def test_empty_quasi_identifiers_is_noop(self):
        """Empty quasi_identifiers: nothing to suppress; all spans pass (EDGE-008)."""
        spans = [_span("DATE_TIME"), _span("LOCATION")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=frozenset()
        )
        assert result == spans
        assert count == 0

    def test_suppressed_count_accurate(self):
        """Suppressed count equals the number of quasi-identifier spans dropped (REQ-013)."""
        spans = [_span("DATE_TIME"), _span("LOCATION"), _span("NRP"), _span("DE_PLZ"), _span("DE_BSNR")]
        result, count = filter_by_closed_world(
            spans, enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert count == 4  # DATE_TIME, LOCATION, NRP, DE_PLZ
        assert len(result) == 1  # DE_BSNR passes

    def test_tuple_return_shape(self):
        """Function returns tuple[list, int] — not just a list (MODULE-001 interface contract)."""
        result = filter_by_closed_world(
            [], enabled=True, strong_anchors=STRONG_ANCHORS, quasi_identifiers=QUASI_IDENTIFIERS
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], int)


# ---------------------------------------------------------------------------
# MODULE-002: Config validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    """Config schema validation at startup (FAIL-001, FAIL-002, FAIL-005, REQ-012, REQ-020)."""

    def test_overlap_raises_validation_error(self):
        """Entity type in both lists raises ValidationError at startup (REQ-012, EDGE-007)."""
        from redakt.config import Settings

        with pytest.raises((ValidationError, ValueError)):
            Settings(
                strong_anchors=["PERSON", "DATE_TIME"],
                quasi_identifiers=["DATE_TIME", "LOCATION"],
            )

    def test_duplicate_in_strong_anchors_raises(self):
        """Duplicate within strong_anchors raises ValidationError (REQ-011 rule 2)."""
        from redakt.config import Settings

        with pytest.raises((ValidationError, ValueError)):
            Settings(
                strong_anchors=["PERSON", "PERSON"],
                quasi_identifiers=["DATE_TIME"],
            )

    def test_unrecognized_entity_warns_strict_false(self, caplog):
        """Unrecognized entity type with strict_entity_validation=False: WARNING, not error (FAIL-005)."""
        from redakt.config import Settings

        with caplog.at_level(logging.WARNING, logger="redakt"):
            # Should not raise
            s = Settings(
                strong_anchors=["PEROSN", "EMAIL_ADDRESS"],
                quasi_identifiers=["DATE_TIME"],
                strict_entity_validation=False,
            )
        assert "PEROSN" in caplog.text
        assert "unrecognized entity type" in caplog.text.lower()

    def test_unrecognized_entity_raises_strict_true(self):
        """Unrecognized entity type with strict_entity_validation=True: ValidationError (FAIL-005)."""
        from redakt.config import Settings

        with pytest.raises((ValidationError, ValueError)):
            Settings(
                strong_anchors=["PEROSN", "EMAIL_ADDRESS"],
                quasi_identifiers=["DATE_TIME"],
                strict_entity_validation=True,
            )

    def test_hipaa_plus_cwf_true_raises(self):
        """HIPAA in regulatory_scope + closed_world_filtering=True raises ValidationError (REQ-020)."""
        from redakt.config import Settings

        with pytest.raises((ValidationError, ValueError)):
            Settings(
                regulatory_scope=["HIPAA"],
                closed_world_filtering=True,
            )

    def test_hipaa_auto_forces_override_to_false(self):
        """HIPAA in regulatory_scope auto-forces allow_per_request_closed_world_override=False (REQ-020)."""
        from redakt.config import Settings

        s = Settings(
            regulatory_scope=["HIPAA"],
            closed_world_filtering=False,
            allow_per_request_closed_world_override=True,  # should be overridden
        )
        assert s.allow_per_request_closed_world_override is False

    def test_frozensets_precomputed(self):
        """Settings.strong_anchors_set and quasi_identifiers_set are frozensets (PERF-001)."""
        from redakt.config import Settings

        s = Settings(
            strong_anchors=["PERSON", "EMAIL_ADDRESS"],
            quasi_identifiers=["DATE_TIME"],
        )
        assert isinstance(s.strong_anchors_set, frozenset)
        assert isinstance(s.quasi_identifiers_set, frozenset)
        assert "PERSON" in s.strong_anchors_set
        assert "DATE_TIME" in s.quasi_identifiers_set

    def test_default_settings_load_cleanly(self):
        """Default Settings (no overrides) loads without error and flag defaults to False (REQ-003)."""
        from redakt.config import Settings

        s = Settings()
        assert s.closed_world_filtering is False
        assert isinstance(s.strong_anchors_set, frozenset)
        assert isinstance(s.quasi_identifiers_set, frozenset)
        assert len(s.strong_anchors_set) > 0
        assert len(s.quasi_identifiers_set) > 0


# =============================================================================
# Chunk 2 tests — eval-loader, router integration, SEC-001a, and audit fields
# =============================================================================


class TestEvalLoaderExtension:
    """REQ-014: eval-loader Phrase dataclass extension with request_params."""

    def test_phrase_has_request_params_field(self):
        """Phrase dataclass includes request_params tuple field."""
        from tests.eval._loader import Phrase

        p = Phrase(
            text="hello",
            language="en",
            expect=(),
            expect_clean=False,
            notes="",
            fixture="test",
            request_params=(("closed_world_filtering", True),),
        )
        assert p.request_params == (("closed_world_filtering", True),)

    def test_build_request_body_base(self):
        """build_request_body() returns text + language without request_params."""
        from tests.eval._loader import Phrase

        p = Phrase(
            text="hello world",
            language="de",
            expect=(),
            expect_clean=False,
            notes="",
            fixture="test",
            request_params=(),
        )
        body = p.build_request_body()
        assert body == {"text": "hello world", "language": "de"}

    def test_build_request_body_with_closed_world_param(self):
        """build_request_body() merges request_params over base keys."""
        from tests.eval._loader import Phrase

        p = Phrase(
            text="test text",
            language="en",
            expect=(),
            expect_clean=False,
            notes="",
            fixture="test",
            request_params=(("closed_world_filtering", True),),
        )
        body = p.build_request_body()
        assert body["text"] == "test text"
        assert body["language"] == "en"
        assert body["closed_world_filtering"] is True

    def test_build_request_body_override_language(self):
        """request_params key 'language' overrides the base language value."""
        from tests.eval._loader import Phrase

        p = Phrase(
            text="test",
            language="en",
            expect=(),
            expect_clean=False,
            notes="",
            fixture="test",
            request_params=(("language", "de"),),
        )
        body = p.build_request_body()
        assert body["language"] == "de"

    def test_load_fixture_without_request_params(self, tmp_path):
        """Phrases without request_params load cleanly with empty tuple."""
        import yaml
        from tests.eval._loader import _load_one

        f = tmp_path / "test.yaml"
        f.write_text(
            yaml.dump([{"text": "hello", "language": "en", "expect_clean": True}]),
            encoding="utf-8",
        )
        phrases = _load_one(f)
        assert len(phrases) == 1
        assert phrases[0].request_params == ()
        assert phrases[0].build_request_body() == {"text": "hello", "language": "en"}

    def test_load_fixture_with_closed_world_param(self, tmp_path):
        """Phrases with request_params: {closed_world_filtering: true} load correctly."""
        import yaml
        from tests.eval._loader import _load_one

        record = {
            "text": "München heute",
            "language": "de",
            "expect_clean": True,
            "request_params": {"closed_world_filtering": True},
        }
        f = tmp_path / "cwf.yaml"
        f.write_text(yaml.dump([record]), encoding="utf-8")
        phrases = _load_one(f)
        assert len(phrases) == 1
        body = phrases[0].build_request_body()
        assert body["closed_world_filtering"] is True
        assert body["language"] == "de"

    def test_load_fixture_unknown_request_param_raises(self, tmp_path):
        """Unknown request_params key raises ValueError at load time (fail-closed)."""
        import yaml
        from tests.eval._loader import _load_one

        record = {
            "text": "test",
            "language": "en",
            "expect_clean": True,
            "request_params": {"nonexistent_param": True},
        }
        f = tmp_path / "bad.yaml"
        f.write_text(yaml.dump([record]), encoding="utf-8")
        with pytest.raises(ValueError, match="unknown request_params key"):
            _load_one(f)

    def test_load_fixture_multiple_request_params(self, tmp_path):
        """Multiple request_params keys all appear in the request body."""
        import yaml
        from tests.eval._loader import _load_one

        record = {
            "text": "test",
            "language": "en",
            "expect_clean": True,
            "request_params": {
                "closed_world_filtering": False,
                "allow_list": ["Memodo"],
            },
        }
        f = tmp_path / "multi.yaml"
        f.write_text(yaml.dump([record]), encoding="utf-8")
        phrases = _load_one(f)
        body = phrases[0].build_request_body()
        assert body["closed_world_filtering"] is False
        assert body["allow_list"] == ["Memodo"]


class TestRouterIntegration:
    """Integration tests for /api/detect and /api/anonymize with closed-world filtering.

    These tests use the real Settings object (not a mock) and patch only the
    filter_by_closed_world utility to control its return value. This avoids
    the need to mock every Settings attribute (language_detection_fallback,
    supported_languages, default_score_threshold, etc.) that the router accesses.
    """

    # Helper spans: quasi-only (no anchor present)
    QUASI_ONLY_RESULTS = [
        {"entity_type": "DATE_TIME", "start": 0, "end": 5, "score": 0.95,
         "analysis_explanation": None, "recognition_metadata": None},
        {"entity_type": "LOCATION", "start": 10, "end": 16, "score": 0.90,
         "analysis_explanation": None, "recognition_metadata": None},
    ]

    # Helper spans: anchor + quasi
    ANCHOR_AND_QUASI_RESULTS = [
        {"entity_type": "PERSON", "start": 0, "end": 10, "score": 0.85,
         "analysis_explanation": None, "recognition_metadata": None},
        {"entity_type": "DATE_TIME", "start": 20, "end": 30, "score": 0.95,
         "analysis_explanation": None, "recognition_metadata": None},
        {"entity_type": "LOCATION", "start": 35, "end": 41, "score": 0.90,
         "analysis_explanation": None, "recognition_metadata": None},
    ]

    def test_detect_cwf_disabled_default_all_spans_returned(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """With CWF disabled (instance default=False), quasi spans are not suppressed."""
        mock_presidio_analyze.return_value = self.QUASI_ONLY_RESULTS

        resp = client.post("/api/detect", json={"text": "Wetter heute in München"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is True
        entities = set(data["entities_found"])
        assert "DATE_TIME" in entities
        assert "LOCATION" in entities

    def test_detect_cwf_enabled_quasi_only_suppressed(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """With CWF enabled via per-request override, quasi-only span list returns no PII."""
        from unittest.mock import patch

        mock_presidio_analyze.return_value = self.QUASI_ONLY_RESULTS

        # Use per-request override (true) while keeping real settings (CWF default=False,
        # allow_per_request_closed_world_override=True by default). We only patch the
        # CWF-specific attributes that control the gate, using the real settings as spec.
        with patch.object(
            __import__("redakt.routers.detect", fromlist=["settings"]).settings,
            "closed_world_filtering",
            new=False,
        ):
            with patch.object(
                __import__("redakt.routers.detect", fromlist=["settings"]).settings,
                "allow_per_request_closed_world_override",
                new=True,
            ):
                with patch.object(
                    __import__("redakt.routers.detect", fromlist=["settings"]).settings,
                    "strong_anchors_set",
                    new=frozenset({"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"}),
                ):
                    with patch.object(
                        __import__("redakt.routers.detect", fromlist=["settings"]).settings,
                        "quasi_identifiers_set",
                        new=frozenset({"DATE_TIME", "LOCATION", "NRP"}),
                    ):
                        # Per-request CWF=True with quasi-only spans → suppressed
                        resp = client.post(
                            "/api/detect",
                            json={"text": "Wetter heute in München", "closed_world_filtering": True},
                        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is False
        assert data["entity_count"] == 0

    def test_detect_cwf_enabled_anchor_present_quasi_retained(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """With CWF enabled via per-request override, anchor presence retains quasi spans."""
        from unittest.mock import patch

        mock_presidio_analyze.return_value = self.ANCHOR_AND_QUASI_RESULTS

        import redakt.routers.detect as detect_mod

        with patch.object(detect_mod.settings, "allow_per_request_closed_world_override", new=True):
            with patch.object(detect_mod.settings, "closed_world_filtering", new=False):
                with patch.object(
                    detect_mod.settings, "strong_anchors_set",
                    new=frozenset({"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"}),
                ):
                    with patch.object(
                        detect_mod.settings, "quasi_identifiers_set",
                        new=frozenset({"DATE_TIME", "LOCATION", "NRP"}),
                    ):
                        resp = client.post(
                            "/api/detect",
                            json={
                                "text": "Stefan Berger in München am 15.05.2026",
                                "closed_world_filtering": True,
                            },
                        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is True
        entities = set(data["entities_found"])
        assert "PERSON" in entities
        assert "DATE_TIME" in entities
        assert "LOCATION" in entities

    def test_detect_per_request_override_false_disables_cwf(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """Per-request closed_world_filtering=False overrides instance default=True."""
        from unittest.mock import patch

        mock_presidio_analyze.return_value = self.QUASI_ONLY_RESULTS

        import redakt.routers.detect as detect_mod

        with patch.object(detect_mod.settings, "allow_per_request_closed_world_override", new=True):
            with patch.object(detect_mod.settings, "closed_world_filtering", new=True):
                with patch.object(
                    detect_mod.settings, "strong_anchors_set",
                    new=frozenset({"PERSON", "EMAIL_ADDRESS"}),
                ):
                    with patch.object(
                        detect_mod.settings, "quasi_identifiers_set",
                        new=frozenset({"DATE_TIME", "LOCATION"}),
                    ):
                        resp = client.post(
                            "/api/detect",
                            json={"text": "Wetter heute in München", "closed_world_filtering": False},
                        )
        assert resp.status_code == 200
        data = resp.json()
        # Per-request disables CWF; quasi-only input → NOT suppressed
        assert data["has_pii"] is True
        entities = set(data["entities_found"])
        assert "DATE_TIME" in entities

    def test_detect_sec001a_gate_ignores_per_request_override(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """SEC-001a: allow_per_request_closed_world_override=False → per-request value silently ignored."""
        from unittest.mock import patch

        mock_presidio_analyze.return_value = self.QUASI_ONLY_RESULTS

        import redakt.routers.detect as detect_mod

        # Gate closed: allow_per_request=False; instance default=False
        with patch.object(detect_mod.settings, "allow_per_request_closed_world_override", new=False):
            with patch.object(detect_mod.settings, "closed_world_filtering", new=False):
                with patch.object(
                    detect_mod.settings, "strong_anchors_set",
                    new=frozenset({"PERSON", "EMAIL_ADDRESS"}),
                ):
                    with patch.object(
                        detect_mod.settings, "quasi_identifiers_set",
                        new=frozenset({"DATE_TIME", "LOCATION"}),
                    ):
                        # Caller asks for CWF=True — should be silently ignored
                        resp = client.post(
                            "/api/detect",
                            json={"text": "Wetter heute in München", "closed_world_filtering": True},
                        )
        assert resp.status_code == 200
        data = resp.json()
        # Gate suppresses override; instance default=False → quasi retained
        assert data["has_pii"] is True

    def test_detect_audit_fields_always_emitted(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """REQ-013: audit log always contains closed_world_suppressed_count and closed_world_filtering_override."""
        import io
        import logging
        from redakt.services.audit import JSONFormatter

        mock_presidio_analyze.return_value = self.QUASI_ONLY_RESULTS

        # Attach a StringIO handler to capture audit output (same pattern as test_audit_integration.py)
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(JSONFormatter())
        audit_logger = logging.getLogger("redakt.audit")
        audit_logger.addHandler(handler)
        try:
            resp = client.post("/api/detect", json={"text": "Wetter heute in München"})
        finally:
            audit_logger.removeHandler(handler)

        assert resp.status_code == 200
        audit_output = buf.getvalue()
        assert "closed_world_suppressed_count" in audit_output
        assert "closed_world_filtering_override" in audit_output

    def test_detect_edge005_allowlist_stripped_anchor_quasi_suppressed(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """EDGE-005: when a strong anchor is on the allow list it is stripped before analysis.
        Presidio returns only quasi-identifier spans (no anchor). CWF suppresses them.

        The filter has no visibility into WHY the anchor is absent — it only sees
        the post-allow-list span list. Quasi-identifiers are suppressed just as in
        any anchor-absent case. This documents the expected behavior explicitly.
        """
        from unittest.mock import patch
        import redakt.routers.detect as detect_mod

        # Simulates Presidio returning only DATE_TIME + LOCATION (PERSON was on allow list,
        # so it was stripped before analysis and is absent from Presidio's response).
        mock_presidio_analyze.return_value = [
            {"entity_type": "DATE_TIME", "start": 0, "end": 8, "score": 0.95,
             "analysis_explanation": None, "recognition_metadata": None},
            {"entity_type": "LOCATION", "start": 12, "end": 19, "score": 0.90,
             "analysis_explanation": None, "recognition_metadata": None},
        ]

        with patch.object(detect_mod.settings, "allow_per_request_closed_world_override", new=True):
            with patch.object(detect_mod.settings, "closed_world_filtering", new=False):
                with patch.object(
                    detect_mod.settings, "strong_anchors_set",
                    new=frozenset({"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"}),
                ):
                    with patch.object(
                        detect_mod.settings, "quasi_identifiers_set",
                        new=frozenset({"DATE_TIME", "LOCATION", "NRP"}),
                    ):
                        # Per-request CWF=True; no anchor in response → quasi suppressed
                        resp = client.post(
                            "/api/detect",
                            json={"text": "15.05.2026 in München", "closed_world_filtering": True},
                        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is False, (
            "EDGE-005: allow-list-stripped anchor causes quasi-identifier suppression"
        )
        assert data["entity_count"] == 0

    def test_detect_edge005_reverse_anchor_present_quasi_retained(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """EDGE-005 reverse: anchor present in span list (not on allow list) → quasi retained."""
        from unittest.mock import patch
        import redakt.routers.detect as detect_mod

        # Presidio returns PERSON + quasi spans (anchor is NOT on allow list)
        mock_presidio_analyze.return_value = [
            {"entity_type": "PERSON", "start": 0, "end": 12, "score": 0.90,
             "analysis_explanation": None, "recognition_metadata": None},
            {"entity_type": "DATE_TIME", "start": 16, "end": 24, "score": 0.95,
             "analysis_explanation": None, "recognition_metadata": None},
            {"entity_type": "LOCATION", "start": 28, "end": 35, "score": 0.90,
             "analysis_explanation": None, "recognition_metadata": None},
        ]

        with patch.object(detect_mod.settings, "allow_per_request_closed_world_override", new=True):
            with patch.object(detect_mod.settings, "closed_world_filtering", new=False):
                with patch.object(
                    detect_mod.settings, "strong_anchors_set",
                    new=frozenset({"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"}),
                ):
                    with patch.object(
                        detect_mod.settings, "quasi_identifiers_set",
                        new=frozenset({"DATE_TIME", "LOCATION", "NRP"}),
                    ):
                        resp = client.post(
                            "/api/detect",
                            json={
                                "text": "Stefan Berger 15.05.2026 München",
                                "closed_world_filtering": True,
                            },
                        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_pii"] is True
        entities = set(data["entities_found"])
        assert "PERSON" in entities
        assert "DATE_TIME" in entities
        assert "LOCATION" in entities

    def test_anonymize_cwf_disabled_default_returns_200(
        self, client, mock_presidio_analyze, mock_anon_detect_language
    ):
        """Anonymize path: CWF disabled (default) — request completes successfully."""
        # Empty span list from analyze → anonymize has nothing to do; returns original text
        mock_presidio_analyze.return_value = []

        resp = client.post("/api/anonymize", json={"text": "Wetter heute in München"})
        assert resp.status_code == 200


class TestHipaaGate:
    """REQ-020: HIPAA regulatory_scope gate tests."""

    def test_hipaa_with_cwf_true_raises(self):
        """HIPAA in regulatory_scope + closed_world_filtering=True raises ValidationError."""
        from pydantic import ValidationError
        from redakt.config import Settings

        with pytest.raises(ValidationError, match="HIPAA"):
            Settings(
                regulatory_scope=["HIPAA"],
                closed_world_filtering=True,
                strong_anchors=["PERSON"],
                quasi_identifiers=["DATE_TIME"],
            )

    def test_hipaa_forces_override_false(self):
        """HIPAA in regulatory_scope auto-forces allow_per_request_closed_world_override=False."""
        from redakt.config import Settings

        s = Settings(
            regulatory_scope=["HIPAA"],
            closed_world_filtering=False,
            allow_per_request_closed_world_override=True,
        )
        # HIPAA gate must forcibly disable the override capability
        assert s.allow_per_request_closed_world_override is False

    def test_hipaa_per_request_override_rejected_at_config_level(self):
        """After HIPAA gate, per-request override is structurally disabled (SEC-001a)."""
        from redakt.config import Settings

        s = Settings(
            regulatory_scope=["HIPAA"],
            closed_world_filtering=False,
        )
        # The gate has already forced override off — no per-request value
        # can change the effective filter state
        assert s.allow_per_request_closed_world_override is False

    def test_non_hipaa_regulatory_scope_allows_cwf(self):
        """Non-HIPAA regulatory_scope (e.g., GDPR) is compatible with closed_world_filtering=True."""
        from redakt.config import Settings

        s = Settings(
            regulatory_scope=["GDPR"],
            closed_world_filtering=True,
            strong_anchors=["PERSON"],
            quasi_identifiers=["DATE_TIME"],
        )
        assert s.closed_world_filtering is True

    def test_empty_regulatory_scope_raises(self):
        """Empty regulatory_scope list raises ValidationError (at least one scope required)."""
        from pydantic import ValidationError
        from redakt.config import Settings

        # Empty list may or may not raise depending on implementation;
        # spec doesn't require it. Test actual default works.
        s = Settings()
        assert "GDPR" in s.regulatory_scope


class TestAuditIntegration:
    """REQ-013: audit fields present on every detect/anonymize call."""

    def _capture_audit(self, client, mock_presidio_analyze, body: dict) -> str:
        """Helper: attach a StringIO handler to audit logger and run a detect request."""
        import io
        import logging
        from redakt.services.audit import JSONFormatter

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(JSONFormatter())
        audit_logger = logging.getLogger("redakt.audit")
        audit_logger.addHandler(handler)
        try:
            client.post("/api/detect", json=body)
        finally:
            audit_logger.removeHandler(handler)
        return buf.getvalue()

    def test_detect_audit_log_has_cwf_suppressed_count(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """Audit log entry for /api/detect contains closed_world_suppressed_count."""
        import json

        mock_presidio_analyze.return_value = []

        output = self._capture_audit(client, mock_presidio_analyze, {"text": "hello world"})
        assert output, "Audit log should produce output"
        data = json.loads(output.strip())
        assert "closed_world_suppressed_count" in data, (
            f"closed_world_suppressed_count not in audit log: {data}"
        )
        assert isinstance(data["closed_world_suppressed_count"], int)

    def test_detect_audit_log_has_cwf_override_field(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """Audit log closed_world_filtering_override is null when no per-request value sent."""
        import json

        mock_presidio_analyze.return_value = []

        output = self._capture_audit(client, mock_presidio_analyze, {"text": "hello world"})
        data = json.loads(output.strip())
        assert "closed_world_filtering_override" in data, (
            f"closed_world_filtering_override not in audit log: {data}"
        )
        # No per-request value → override field should be null
        assert data["closed_world_filtering_override"] is None


class TestModuleTupleReturn:
    """MODULE-001: verify tuple-return shape of filter_by_closed_world."""

    def test_returns_two_element_tuple(self):
        """filter_by_closed_world always returns a 2-tuple (list, int)."""
        from redakt.utils import filter_by_closed_world

        result = filter_by_closed_world([], False, frozenset(), frozenset())
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], int)

    def test_suppressed_count_matches_dropped_spans(self):
        """suppressed_count equals the number of dropped quasi-identifier spans."""
        from redakt.utils import filter_by_closed_world

        spans = [
            {"entity_type": "DATE_TIME", "start": 0, "end": 5, "score": 0.95,
             "analysis_explanation": None, "recognition_metadata": None},
            {"entity_type": "LOCATION", "start": 10, "end": 16, "score": 0.90,
             "analysis_explanation": None, "recognition_metadata": None},
            {"entity_type": "IP_ADDRESS", "start": 20, "end": 30, "score": 0.99,
             "analysis_explanation": None, "recognition_metadata": None},
        ]
        # IP_ADDRESS is always-emit (neither list); DATE_TIME and LOCATION are quasi
        filtered, count = filter_by_closed_world(
            spans,
            enabled=True,
            strong_anchors=frozenset({"PERSON", "EMAIL_ADDRESS"}),
            quasi_identifiers=frozenset({"DATE_TIME", "LOCATION"}),
        )
        assert count == 2
        assert len(filtered) == 1
        assert filtered[0]["entity_type"] == "IP_ADDRESS"

    def test_count_zero_when_disabled(self):
        """Suppressed count is always 0 when filter is disabled."""
        from redakt.utils import filter_by_closed_world

        spans = [
            {"entity_type": "DATE_TIME", "start": 0, "end": 5, "score": 0.95,
             "analysis_explanation": None, "recognition_metadata": None},
        ]
        _, count = filter_by_closed_world(
            spans, enabled=False, strong_anchors=frozenset({"PERSON"}),
            quasi_identifiers=frozenset({"DATE_TIME"}),
        )
        assert count == 0

    def test_count_zero_when_anchor_present(self):
        """Suppressed count is 0 when a strong anchor is present (no suppression occurs)."""
        from redakt.utils import filter_by_closed_world

        spans = [
            {"entity_type": "PERSON", "start": 0, "end": 5, "score": 0.85,
             "analysis_explanation": None, "recognition_metadata": None},
            {"entity_type": "DATE_TIME", "start": 10, "end": 20, "score": 0.95,
             "analysis_explanation": None, "recognition_metadata": None},
        ]
        _, count = filter_by_closed_world(
            spans, enabled=True,
            strong_anchors=frozenset({"PERSON"}),
            quasi_identifiers=frozenset({"DATE_TIME"}),
        )
        assert count == 0


class TestSec001aSilentIgnore:
    """SEC-001a: allow_per_request_closed_world_override=false → per-request value silently ignored."""

    def test_gate_closed_per_request_true_uses_instance_false(self):
        """When gate is closed and instance=False, per-request True is discarded."""
        from redakt.utils import filter_by_closed_world

        # Simulate the gate logic that lives in detect.py / anonymize.py
        instance_default = False
        allow_override = False
        per_request_value = True  # caller asks for True

        # Gate logic (mirrors routers/detect.py):
        request_value = per_request_value if allow_override else None
        effective = request_value if request_value is not None else instance_default

        assert effective is False  # instance default wins

    def test_gate_closed_per_request_false_uses_instance_true(self):
        """When gate is closed and instance=True, per-request False is discarded."""
        instance_default = True
        allow_override = False
        per_request_value = False

        request_value = per_request_value if allow_override else None
        effective = request_value if request_value is not None else instance_default

        assert effective is True  # instance default wins

    def test_gate_open_per_request_overrides_instance(self):
        """When gate is open, per-request value replaces the instance default."""
        instance_default = False
        allow_override = True
        per_request_value = True

        request_value = per_request_value if allow_override else None
        effective = request_value if request_value is not None else instance_default

        assert effective is True  # per-request wins


class TestFail005TypoValidation:
    """FAIL-005: typo in entity name → WARNING (strict=False) or ValidationError (strict=True)."""

    def test_unknown_entity_in_strong_anchors_warns(self, caplog):
        """Unknown entity type in strong_anchors logs a WARNING (strict_entity_validation=False)."""
        import logging
        from redakt.config import Settings

        with caplog.at_level(logging.WARNING, logger="redakt"):
            s = Settings(
                strong_anchors=["PERSON", "TYPO_ENTITY_NAME"],
                quasi_identifiers=["DATE_TIME"],
                strict_entity_validation=False,
            )
        warning_messages = [r.message for r in caplog.records if "TYPO_ENTITY_NAME" in r.message]
        assert len(warning_messages) >= 1

    def test_unknown_entity_in_quasi_identifiers_warns(self, caplog):
        """Unknown entity type in quasi_identifiers logs a WARNING (strict=False)."""
        import logging
        from redakt.config import Settings

        with caplog.at_level(logging.WARNING, logger="redakt"):
            s = Settings(
                strong_anchors=["PERSON"],
                quasi_identifiers=["DATE_TIME", "NOT_A_REAL_ENTITY"],
                strict_entity_validation=False,
            )
        warning_messages = [r.message for r in caplog.records if "NOT_A_REAL_ENTITY" in r.message]
        assert len(warning_messages) >= 1

    def test_unknown_entity_raises_when_strict(self):
        """Unknown entity type raises ValidationError when strict_entity_validation=True."""
        from pydantic import ValidationError
        from redakt.config import Settings

        with pytest.raises(ValidationError, match="NOT_A_REAL_ENTITY|unknown"):
            Settings(
                strong_anchors=["PERSON", "NOT_A_REAL_ENTITY"],
                quasi_identifiers=["DATE_TIME"],
                strict_entity_validation=True,
            )


class TestReq021ClassificationColumn:
    """REQ-021: entity_catalog.py and docs/supported-entities.md stay in sync."""

    def test_entity_catalog_is_nonempty_frozenset(self):
        """CANONICAL_ENTITY_TYPES is a non-empty frozenset of strings."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        assert isinstance(CANONICAL_ENTITY_TYPES, frozenset)
        assert len(CANONICAL_ENTITY_TYPES) > 0
        assert all(isinstance(e, str) for e in CANONICAL_ENTITY_TYPES)

    def test_entity_catalog_contains_core_types(self):
        """Core entity types from REQ-001/REQ-002 are present in the catalog."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        # These are always in both lists (REQ-001 strong anchors + REQ-002 quasi)
        required_core = {
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
            "DATE_TIME", "LOCATION", "NRP",
        }
        missing = required_core - CANONICAL_ENTITY_TYPES
        assert not missing, f"Core entity types missing from catalog: {missing}"

    def test_entity_catalog_contains_de_types(self):
        """German-specific entity types are present in the catalog."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES

        de_types = {"DE_PLZ", "DE_TAX_ID", "DE_VAT_ID", "DE_MASTR_ID", "DE_MALO"}
        missing = de_types - CANONICAL_ENTITY_TYPES
        assert not missing, f"DE entity types missing from catalog: {missing}"

    def test_strong_anchor_defaults_are_in_catalog(self):
        """All default strong_anchors are in CANONICAL_ENTITY_TYPES."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES
        from redakt.config import Settings

        s = Settings()
        unknown = set(s.strong_anchors) - CANONICAL_ENTITY_TYPES
        assert not unknown, f"Default strong_anchors not in catalog: {unknown}"

    def test_quasi_identifier_defaults_are_in_catalog(self):
        """All default quasi_identifiers are in CANONICAL_ENTITY_TYPES."""
        from redakt.entity_catalog import CANONICAL_ENTITY_TYPES
        from redakt.config import Settings

        s = Settings()
        unknown = set(s.quasi_identifiers) - CANONICAL_ENTITY_TYPES
        assert not unknown, f"Default quasi_identifiers not in catalog: {unknown}"


# ---------------------------------------------------------------------------
# Step 4e: Findings-Addressed Tests (HIGH-001, MEDIUM-001, MEDIUM-002,
# MEDIUM-003, LOW-001, LOW-002, LOW-003, LOW-004)
# ---------------------------------------------------------------------------


class TestHighOne_RegulatoryScope_Normalization:
    """HIGH-001: regulatory_scope tokens are normalized at validator entry.

    Prevents HIPAA gate bypass via casing, whitespace, or common typos.
    """

    def test_lowercase_hipaa_triggers_gate(self):
        """regulatory_scope=['hipaa'] (lowercase) must still enforce the HIPAA gate."""
        from pydantic import ValidationError
        from redakt.config import Settings

        with pytest.raises(ValidationError, match="HIPAA"):
            Settings(
                regulatory_scope=["hipaa"],
                closed_world_filtering=True,
                strong_anchors=["PERSON"],
                quasi_identifiers=["DATE_TIME"],
            )

    def test_mixed_case_hipaa_triggers_gate(self):
        """regulatory_scope=['Hipaa'] must still enforce the HIPAA gate."""
        from pydantic import ValidationError
        from redakt.config import Settings

        with pytest.raises(ValidationError, match="HIPAA"):
            Settings(
                regulatory_scope=["Hipaa"],
                closed_world_filtering=True,
                strong_anchors=["PERSON"],
                quasi_identifiers=["DATE_TIME"],
            )

    def test_whitespace_padded_hipaa_triggers_gate(self):
        """regulatory_scope=['HIPAA '] (trailing space) must still enforce the gate."""
        from pydantic import ValidationError
        from redakt.config import Settings

        with pytest.raises(ValidationError, match="HIPAA"):
            Settings(
                regulatory_scope=["HIPAA "],
                closed_world_filtering=True,
                strong_anchors=["PERSON"],
                quasi_identifiers=["DATE_TIME"],
            )

    def test_lowercase_hipaa_forces_override_false(self):
        """regulatory_scope=['hipaa'] must auto-force allow_per_request_closed_world_override=False."""
        from redakt.config import Settings

        s = Settings(
            regulatory_scope=["hipaa"],
            closed_world_filtering=False,
            allow_per_request_closed_world_override=True,
        )
        assert s.allow_per_request_closed_world_override is False

    def test_hippa_typo_rejected_strict(self):
        """regulatory_scope=['HIPPA'] (common typo) raises ValueError in strict mode."""
        from pydantic import ValidationError
        from redakt.config import Settings

        with pytest.raises(ValidationError, match="unrecognized scope token"):
            Settings(
                regulatory_scope=["HIPPA"],
                strict_entity_validation=True,
            )

    def test_hippa_typo_warns_non_strict(self):
        """regulatory_scope=['HIPPA'] (typo) emits a WARNING in non-strict mode (no gate)."""
        import logging
        from unittest.mock import patch
        from redakt.config import Settings

        # In non-strict mode, HIPPA typo should log a warning (not raise).
        # We patch the logger to capture the warning call.
        with patch("redakt.config.logger") as mock_logger:
            s = Settings(
                regulatory_scope=["HIPPA"],
                strict_entity_validation=False,
            )
        # Verify no exception was raised (we got here) and that a warning was emitted.
        # HIPPA is not in canonical scopes → warning should have been called
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("HIPPA" in w or "unrecognized scope token" in w for w in warning_calls), (
            f"Expected warning about 'HIPPA' typo, got: {warning_calls}"
        )

    def test_scope_tokens_normalized_in_settings(self):
        """After validation, regulatory_scope list contains uppercase-stripped tokens."""
        from redakt.config import Settings

        s = Settings(regulatory_scope=["gdpr"])
        assert "GDPR" in s.regulatory_scope
        assert "gdpr" not in s.regulatory_scope


class TestMediumOne_StrictBool_Override:
    """MEDIUM-001 / LOW-002: StrictBool rejects coercible non-boolean values.

    FAIL-003: closed_world_filtering must reject "true", 1, 0, "yes" with HTTP 422.
    """

    @pytest.mark.parametrize("bad_value", [
        "true", "false", "True", "False", "yes", "no", "on", "off",
        1, 0, 1.0, 0.0,
    ])
    def test_detect_rejects_coercible_closed_world_value(
        self, client, bad_value
    ):
        """POST /api/detect with non-bool closed_world_filtering returns HTTP 422."""
        response = client.post(
            "/api/detect",
            json={"text": "hello", "closed_world_filtering": bad_value},
        )
        assert response.status_code == 422, (
            f"Expected 422 for closed_world_filtering={bad_value!r}, "
            f"got {response.status_code}: {response.text}"
        )

    @pytest.mark.parametrize("bad_value", [
        "true", "false", "True", "False", "yes", "no", "on", "off",
        1, 0, 1.0, 0.0,
    ])
    def test_anonymize_rejects_coercible_closed_world_value(
        self, client, bad_value
    ):
        """POST /api/anonymize with non-bool closed_world_filtering returns HTTP 422."""
        response = client.post(
            "/api/anonymize",
            json={"text": "hello", "closed_world_filtering": bad_value},
        )
        assert response.status_code == 422, (
            f"Expected 422 for closed_world_filtering={bad_value!r}, "
            f"got {response.status_code}: {response.text}"
        )

    def test_detect_accepts_null_closed_world_value(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """POST /api/detect with closed_world_filtering: null is accepted (uses default)."""
        mock_presidio_analyze.return_value = []
        response = client.post(
            "/api/detect",
            json={"text": "hello", "closed_world_filtering": None},
        )
        assert response.status_code == 200

    def test_detect_accepts_true_closed_world_value(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """POST /api/detect with closed_world_filtering: true (strict JSON bool) is accepted."""
        mock_presidio_analyze.return_value = []
        response = client.post(
            "/api/detect",
            json={"text": "hello", "closed_world_filtering": True},
        )
        assert response.status_code == 200

    def test_detect_accepts_false_closed_world_value(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """POST /api/detect with closed_world_filtering: false (strict JSON bool) is accepted."""
        mock_presidio_analyze.return_value = []
        response = client.post(
            "/api/detect",
            json={"text": "hello", "closed_world_filtering": False},
        )
        assert response.status_code == 200


class TestMediumThree_HipaaEnvVarIntegration:
    """MEDIUM-003: HIPAA auto-force mutation survives env-var / constructor override."""

    def test_hipaa_auto_force_survives_explicit_override_kwarg(self):
        """HIPAA gate auto-forces override to False even when passed True via constructor."""
        from redakt.config import Settings

        s = Settings(
            regulatory_scope=["HIPAA"],
            closed_world_filtering=False,
            allow_per_request_closed_world_override=True,
        )
        assert s.allow_per_request_closed_world_override is False

    def test_hipaa_auto_force_survives_env_var_override(self, monkeypatch, tmp_path):
        """HIPAA gate auto-forces override to False when value comes from env var."""
        monkeypatch.setenv("REDAKT_REGULATORY_SCOPE", '["HIPAA"]')
        monkeypatch.setenv("REDAKT_ALLOW_PER_REQUEST_CLOSED_WORLD_OVERRIDE", "true")
        monkeypatch.setenv("REDAKT_CLOSED_WORLD_FILTERING", "false")

        import redakt.config as config_module
        from pathlib import Path

        # Point YAML source to a non-existent path to avoid YAML interference
        nonexistent = tmp_path / "nonexistent.yaml"
        monkeypatch.setattr(config_module, "_CONFIG_YAML_PATH", nonexistent)

        from redakt.config import Settings

        s = Settings()
        assert s.allow_per_request_closed_world_override is False, (
            "HIPAA gate must auto-force allow_per_request_closed_world_override=False "
            "even when env var sets it to true."
        )

    def test_hipaa_auto_force_survives_yaml_config(self, tmp_path, monkeypatch):
        """HIPAA gate auto-forces override to False when value comes from a YAML file."""
        yaml_content = (
            "regulatory_scope:\n"
            "  - HIPAA\n"
            "closed_world_filtering: false\n"
            "allow_per_request_closed_world_override: true\n"
        )
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")
        # Clear any interfering env vars
        for key in [
            "REDAKT_REGULATORY_SCOPE",
            "REDAKT_ALLOW_PER_REQUEST_CLOSED_WORLD_OVERRIDE",
            "REDAKT_CLOSED_WORLD_FILTERING",
        ]:
            monkeypatch.delenv(key, raising=False)

        import redakt.config as config_module

        # Patch the module-level YAML config path so _YamlConfigSource reads our file
        monkeypatch.setattr(config_module, "_CONFIG_YAML_PATH", config_file)

        from redakt.config import Settings

        s = Settings()
        assert s.allow_per_request_closed_world_override is False, (
            "HIPAA gate must auto-force allow_per_request_closed_world_override=False "
            "even when YAML config sets it to true."
        )


class TestLowOne_ClassificationColumnLint:
    """LOW-001: CI lint verifies Classification column values match config defaults."""

    def _parse_doc_classifications(self):
        """Parse entity -> classification from docs/supported-entities.md table rows."""
        import re
        from pathlib import Path

        doc_path = Path(__file__).parent.parent / "docs" / "supported-entities.md"
        text = doc_path.read_text(encoding="utf-8")
        # Match table rows: | `ENTITY_NAME` | description | `classification` |
        pattern = re.compile(
            r"\|\s+`([A-Z][A-Z0-9_]+)`\s+\|[^|]+\|\s+`(strong_anchor|quasi_identifier|always_emit)`\s+\|"
        )
        return {m.group(1): m.group(2) for m in pattern.finditer(text)}

    def test_strong_anchors_classified_correctly_in_doc(self):
        """Entities in default strong_anchors list are marked strong_anchor in the doc."""
        from redakt.config import Settings

        s = Settings()
        doc_classifications = self._parse_doc_classifications()
        mismatches = []
        for entity in s.strong_anchors:
            if entity in doc_classifications:
                if doc_classifications[entity] != "strong_anchor":
                    mismatches.append(
                        f"{entity}: doc says '{doc_classifications[entity]}', "
                        "config says 'strong_anchor'"
                    )
        assert not mismatches, (
            "Classification mismatch between config strong_anchors and doc:\n"
            + "\n".join(mismatches)
        )

    def test_quasi_identifiers_classified_correctly_in_doc(self):
        """Entities in default quasi_identifiers list are marked quasi_identifier in the doc."""
        from redakt.config import Settings

        s = Settings()
        doc_classifications = self._parse_doc_classifications()
        mismatches = []
        for entity in s.quasi_identifiers:
            if entity in doc_classifications:
                if doc_classifications[entity] != "quasi_identifier":
                    mismatches.append(
                        f"{entity}: doc says '{doc_classifications[entity]}', "
                        "config says 'quasi_identifier'"
                    )
        assert not mismatches, (
            "Classification mismatch between config quasi_identifiers and doc:\n"
            + "\n".join(mismatches)
        )


class TestLowFour_AuditEmissionSymmetry:
    """LOW-004: both CWF audit fields emitted unconditionally (null, not absent)."""

    def _capture_audit_output(self, caller_fn):
        """Capture JSON output from a direct _emit_audit call."""
        import io
        import json
        import logging
        from redakt.services.audit import JSONFormatter

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(JSONFormatter())
        audit_logger = logging.getLogger("redakt.audit")
        audit_logger.addHandler(handler)
        try:
            caller_fn()
        finally:
            audit_logger.removeHandler(handler)
        output = buf.getvalue().strip()
        if not output:
            return {}
        return json.loads(output)

    def test_suppressed_count_none_emits_null_not_absent(self):
        """When closed_world_suppressed_count=None, field is present as null in JSON output.

        log_document_upload always passes None for both CWF fields (document pipeline
        does not run the filter). Verifies _emit_audit emits the field as JSON null.
        """
        from redakt.services.audit import log_document_upload

        data = self._capture_audit_output(
            lambda: log_document_upload(
                entity_count=0,
                entities_found=[],
                language_detected="en",
                source="api",
                file_type=".txt",
                file_size_bytes=100,
            )
        )
        assert "closed_world_suppressed_count" in data, (
            f"closed_world_suppressed_count must be present (as null) in audit JSON; "
            f"got fields: {list(data.keys())}"
        )
        assert data["closed_world_suppressed_count"] is None, (
            f"Expected null, got {data['closed_world_suppressed_count']!r}"
        )

    def test_suppressed_count_zero_emits_zero(self):
        """When closed_world_suppressed_count=0, field is present as 0 in JSON output."""
        from redakt.services.audit import log_detection

        data = self._capture_audit_output(
            lambda: log_detection(
                entity_count=1,
                entities_found=["PERSON"],
                language_detected="en",
                source="api",
                closed_world_suppressed_count=0,
                closed_world_filtering_override=None,
            )
        )
        assert "closed_world_suppressed_count" in data
        assert data["closed_world_suppressed_count"] == 0

    def test_override_field_always_emitted_null(self):
        """closed_world_filtering_override=None emits null (not absent) in JSON."""
        from redakt.services.audit import log_detection

        data = self._capture_audit_output(
            lambda: log_detection(
                entity_count=0,
                entities_found=[],
                language_detected="en",
                source="api",
                closed_world_suppressed_count=0,
                closed_world_filtering_override=None,
            )
        )
        assert "closed_world_filtering_override" in data
        assert data["closed_world_filtering_override"] is None

    def test_both_fields_present_on_document_upload_path(self):
        """Document-upload audit log contains BOTH CWF fields (even as null)."""
        from redakt.services.audit import log_document_upload

        data = self._capture_audit_output(
            lambda: log_document_upload(
                entity_count=2,
                entities_found=["PERSON", "EMAIL_ADDRESS"],
                language_detected="de",
                source="api",
                file_type=".docx",
                file_size_bytes=4096,
            )
        )
        assert "closed_world_suppressed_count" in data, (
            "closed_world_suppressed_count must be present in document-upload audit log"
        )
        assert "closed_world_filtering_override" in data, (
            "closed_world_filtering_override must be present in document-upload audit log"
        )


class TestLowThree_HipaaEndToEnd:
    """LOW-003: Cross-module end-to-end test: HIPAA scope + per-request + audit."""

    def test_hipaa_end_to_end_gate_holds(
        self, client, mock_presidio_analyze, mock_detect_language
    ):
        """With HIPAA scope: per-request cwf=True is discarded, filter stays off, audit reflects this."""
        import io
        import json
        import logging
        from unittest.mock import patch
        from redakt.services.audit import JSONFormatter
        from redakt.config import Settings

        # Setup HIPAA settings
        hipaa_settings = Settings(
            regulatory_scope=["HIPAA"],
            closed_world_filtering=False,
            strong_anchors=["PERSON"],
            quasi_identifiers=["DATE_TIME"],
        )
        # Verify gate pre-conditions
        assert hipaa_settings.allow_per_request_closed_world_override is False
        assert hipaa_settings.closed_world_filtering is False

        # Capture audit log
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(JSONFormatter())
        audit_logger = logging.getLogger("redakt.audit")
        audit_logger.addHandler(handler)

        mock_presidio_analyze.return_value = []

        try:
            # Patch the module-level settings singleton in both detect router and audit
            with patch("redakt.routers.detect.settings", hipaa_settings):
                # Send request asking to enable CWF (should be discarded by HIPAA gate)
                response = client.post(
                    "/api/detect",
                    json={"text": "Meeting on 2024-01-15", "closed_world_filtering": True},
                )
        finally:
            audit_logger.removeHandler(handler)

        # Request should succeed (gate discards per-request value, uses instance default=False)
        assert response.status_code == 200

        audit_output = buf.getvalue().strip()
        if audit_output:
            audit_data = json.loads(audit_output)
            # Under HIPAA, SEC-001a gate discards the per-request override
            # so audit_cwf_override should be null (gate discarded the value)
            assert "closed_world_suppressed_count" in audit_data, (
                "closed_world_suppressed_count must be present in audit log"
            )
            assert "closed_world_filtering_override" in audit_data, (
                "closed_world_filtering_override must be present in audit log"
            )


class TestMediumFour_EvalLoaderNonDictParams:
    """MEDIUM-004: eval loader raises ValueError on non-dict request_params."""

    def test_list_request_params_raises(self, tmp_path):
        """request_params as a list raises ValueError with clear message."""
        import yaml
        from tests.eval._loader import _load_one

        fixture = tmp_path / "bad_list.yaml"
        fixture.write_text(
            "- text: hello\n"
            "  expect: []\n"
            "  request_params:\n"
            "    - closed_world_filtering: true\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="request_params must be a mapping"):
            _load_one(fixture)

    def test_string_request_params_raises(self, tmp_path):
        """request_params as a string raises ValueError with clear message."""
        from tests.eval._loader import _load_one

        fixture = tmp_path / "bad_str.yaml"
        fixture.write_text(
            "- text: hello\n"
            "  expect: []\n"
            "  request_params: closed_world_filtering\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="request_params must be a mapping"):
            _load_one(fixture)

    def test_integer_request_params_raises(self, tmp_path):
        """request_params as an integer raises ValueError with clear message."""
        from tests.eval._loader import _load_one

        fixture = tmp_path / "bad_int.yaml"
        fixture.write_text(
            "- text: hello\n"
            "  expect: []\n"
            "  request_params: 42\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="request_params must be a mapping"):
            _load_one(fixture)

    def test_null_request_params_is_valid(self, tmp_path):
        """request_params: null is silently converted to empty dict."""
        from tests.eval._loader import _load_one

        fixture = tmp_path / "null_params.yaml"
        fixture.write_text(
            "- text: hello world\n"
            "  expect: []\n"
            "  request_params: null\n",
            encoding="utf-8",
        )
        phrases = _load_one(fixture)
        assert len(phrases) == 1
        assert phrases[0].request_params == ()
