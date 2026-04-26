"""test_formatters_v11.py — Tests for v3.0.1 new formatters in _process_table_rows.

Covers: list_length, list_count_by_type, join_csv.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    monkeypatch.setenv("VIEWER_ROOTS", str(tmp_path))
    import viewer.app as m
    importlib.reload(m)
    return m


class TestListLengthFormatter:
    def test_empty_list(self, app_module):
        rows = [{"hints": []}]
        cols = [{"field": "hints", "label": "B-roll #", "format": "list_length"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["hints"] == 0

    def test_non_empty_list(self, app_module):
        rows = [{"hints": [{"type": "screenshot"}, {"type": "logo"}]}]
        cols = [{"field": "hints", "label": "B-roll #", "format": "list_length"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["hints"] == 2

    def test_non_list_value_returns_zero(self, app_module):
        rows = [{"hints": None}]
        cols = [{"field": "hints", "label": "B-roll #", "format": "list_length"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["hints"] == 0

    def test_missing_field_returns_zero(self, app_module):
        rows = [{}]
        cols = [{"field": "hints", "label": "B-roll #", "format": "list_length"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["hints"] == 0


class TestListCountByTypeFormatter:
    def test_single_type(self, app_module):
        rows = [{"broll": [{"type": "screenshot"}, {"type": "screenshot"}]}]
        cols = [{"field": "broll", "label": "B-roll", "format": "list_count_by_type"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["broll"] == "screenshot×2"

    def test_multiple_types(self, app_module):
        rows = [{"broll": [{"type": "video"}, {"type": "screenshot"}, {"type": "video"}]}]
        cols = [{"field": "broll", "label": "B-roll", "format": "list_count_by_type"}]
        result = app_module._process_table_rows(rows, cols)
        val = result[0]["broll"]
        assert "video×2" in val
        assert "screenshot×1" in val

    def test_empty_list_returns_empty_string(self, app_module):
        rows = [{"broll": []}]
        cols = [{"field": "broll", "label": "B-roll", "format": "list_count_by_type"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["broll"] == ""

    def test_non_list_returns_empty_string(self, app_module):
        rows = [{"broll": None}]
        cols = [{"field": "broll", "label": "B-roll", "format": "list_count_by_type"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["broll"] == ""


class TestJoinCsvFormatter:
    def test_list_of_strings(self, app_module):
        rows = [{"topics": ["foo_product", "bar_company"]}]
        cols = [{"field": "topics", "label": "Topic focus", "format": "join_csv"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["topics"] == "foo_product, bar_company"

    def test_empty_list(self, app_module):
        rows = [{"topics": []}]
        cols = [{"field": "topics", "label": "Topic focus", "format": "join_csv"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["topics"] == ""

    def test_none_value(self, app_module):
        rows = [{"topics": None}]
        cols = [{"field": "topics", "label": "Topic focus", "format": "join_csv"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["topics"] == ""

    def test_single_item(self, app_module):
        rows = [{"topics": ["only_topic"]}]
        cols = [{"field": "topics", "label": "Topic focus", "format": "join_csv"}]
        result = app_module._process_table_rows(rows, cols)
        assert result[0]["topics"] == "only_topic"
