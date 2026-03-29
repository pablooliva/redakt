"""Unit tests for allow list utility functions (parse, validate, merge)."""

import logging

import pytest

from redakt.utils import (
    merge_allow_lists,
    parse_allow_list,
    parse_comma_separated,
    validate_allow_list,
    validate_instance_allow_list,
)


class TestParseCommaSeparated:
    def test_basic_parsing(self):
        assert parse_comma_separated("term1, term2, term3") == ["term1", "term2", "term3"]

    def test_strips_whitespace(self):
        assert parse_comma_separated("  term1 , term2  ") == ["term1", "term2"]

    def test_removes_empty_entries(self):
        assert parse_comma_separated("term1,,term2, ,term3") == ["term1", "term2", "term3"]

    def test_trailing_comma(self):
        assert parse_comma_separated("term1, term2 , , term3,") == ["term1", "term2", "term3"]

    def test_returns_none_for_none(self):
        assert parse_comma_separated(None) is None

    def test_returns_none_for_empty_string(self):
        assert parse_comma_separated("") is None

    def test_returns_none_for_only_commas(self):
        assert parse_comma_separated(",,,") is None

    def test_returns_none_for_only_whitespace(self):
        assert parse_comma_separated("  ,  ,  ") is None

    def test_unicode_terms(self):
        result = parse_comma_separated("München, Straße, 北京市")
        assert result == ["München", "Straße", "北京市"]

    def test_single_term(self):
        assert parse_comma_separated("single") == ["single"]


class TestParseAllowList:
    def test_returns_empty_list_for_empty_string(self):
        assert parse_allow_list("") == []

    def test_returns_empty_list_for_whitespace(self):
        assert parse_allow_list("   ") == []

    def test_parses_terms(self):
        assert parse_allow_list("Acme Corp, ProductX") == ["Acme Corp", "ProductX"]

    def test_strips_and_removes_empty(self):
        assert parse_allow_list("term1, , term2") == ["term1", "term2"]

    def test_comma_containing_term_splits(self):
        """V1 limitation: comma-separated parsing splits on commas."""
        assert parse_allow_list("Smith, John") == ["Smith", "John"]


class TestValidateAllowList:
    def test_accepts_empty_list(self):
        validate_allow_list([])  # Should not raise

    def test_accepts_valid_terms(self):
        validate_allow_list(["Acme Corp", "ProductX", "Berlin HQ"])

    def test_rejects_too_many_terms(self):
        terms = [f"term{i}" for i in range(101)]
        with pytest.raises(ValueError, match="exceeds maximum of 100 terms"):
            validate_allow_list(terms)

    def test_accepts_exactly_max_terms(self):
        terms = [f"term{i}" for i in range(100)]
        validate_allow_list(terms)  # Should not raise

    def test_rejects_term_too_long(self):
        terms = ["a" * 201]
        with pytest.raises(ValueError, match="exceeds maximum length of 200 characters"):
            validate_allow_list(terms)

    def test_accepts_term_at_max_length(self):
        terms = ["a" * 200]
        validate_allow_list(terms)  # Should not raise

    def test_custom_limits(self):
        with pytest.raises(ValueError, match="exceeds maximum of 5 terms"):
            validate_allow_list(["a", "b", "c", "d", "e", "f"], max_terms=5)

    def test_regex_special_chars_accepted(self):
        """Exact mode: regex special chars are safe."""
        validate_allow_list(["test@example.com", "price: $100", "a+b=c"])


class TestMergeAllowLists:
    def test_instance_only(self):
        result = merge_allow_lists(["A", "B"], None)
        assert result == ["A", "B"]

    def test_per_request_only(self):
        result = merge_allow_lists([], ["X", "Y"])
        assert result == ["X", "Y"]

    def test_both_lists(self):
        result = merge_allow_lists(["A", "B"], ["C", "D"])
        assert result == ["A", "B", "C", "D"]

    def test_neither_returns_none(self):
        result = merge_allow_lists([], None)
        assert result is None

    def test_empty_per_request_returns_instance(self):
        result = merge_allow_lists(["A"], [])
        assert result == ["A"]

    def test_deduplication_preserves_order(self):
        """Instance terms first, per-request appended, duplicates removed."""
        result = merge_allow_lists(["A", "B"], ["B", "C"])
        assert result == ["A", "B", "C"]

    def test_deduplication_all_duplicates(self):
        result = merge_allow_lists(["A", "B"], ["A", "B"])
        assert result == ["A", "B"]

    def test_empty_list_per_request(self):
        """Empty per-request list (not None) should still just return instance."""
        result = merge_allow_lists(["A"], [])
        assert result == ["A"]

    def test_returns_none_for_empty_result(self):
        assert merge_allow_lists([], []) is None
        assert merge_allow_lists([], None) is None


class TestValidateInstanceAllowList:
    def test_empty_list_no_warnings(self, caplog):
        with caplog.at_level(logging.WARNING, logger="redakt"):
            result = validate_instance_allow_list([])
        assert len(caplog.records) == 0
        assert result == []

    def test_warns_about_empty_strings(self, caplog):
        with caplog.at_level(logging.WARNING, logger="redakt"):
            result = validate_instance_allow_list(["valid", "", "  "])
        assert any("empty string" in r.message for r in caplog.records)
        # FAIL-002: empty strings must be stripped from the returned list
        assert result == ["valid"]
        assert "" not in result
        assert "  " not in result

    def test_warns_about_long_terms(self, caplog):
        with caplog.at_level(logging.WARNING, logger="redakt"):
            validate_instance_allow_list(["a" * 201])
        assert any("exceeding" in r.message for r in caplog.records)

    def test_warns_about_large_list(self, caplog):
        terms = [f"term{i}" for i in range(501)]
        with caplog.at_level(logging.WARNING, logger="redakt"):
            validate_instance_allow_list(terms)
        assert any("501 terms" in r.message for r in caplog.records)

    def test_no_warning_for_valid_list(self, caplog):
        with caplog.at_level(logging.WARNING, logger="redakt"):
            result = validate_instance_allow_list(["Acme Corp", "ProductX"])
        assert len(caplog.records) == 0
        assert result == ["Acme Corp", "ProductX"]
