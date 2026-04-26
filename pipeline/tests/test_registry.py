"""Tests for the phase registry."""
from __future__ import annotations

import pytest

from pipeline.registry import PIPELINE_PHASES
from pipeline.orchestrator import _topo_sort


class TestRegistry:
    def test_has_capture_and_polish(self):
        names = [d.name for d in PIPELINE_PHASES]
        assert "capture" in names
        assert "polish" in names

    def test_no_duplicate_names(self):
        names = [d.name for d in PIPELINE_PHASES]
        assert len(names) == len(set(names)), f"Duplicate phase names: {names}"

    def test_topological_sort_valid(self):
        sorted_phases = _topo_sort(PIPELINE_PHASES)
        # capture before polish
        names = [d.name for d in sorted_phases]
        assert names.index("capture") < names.index("polish")

    def test_capture_no_deps(self):
        cap = next(d for d in PIPELINE_PHASES if d.name == "capture")
        assert cap.depends_on == []

    def test_polish_depends_on_capture(self):
        pol = next(d for d in PIPELINE_PHASES if d.name == "polish")
        assert "capture" in pol.depends_on

    def test_all_deps_exist(self):
        names = {d.name for d in PIPELINE_PHASES}
        for d in PIPELINE_PHASES:
            for dep in d.depends_on:
                assert dep in names, f"Phase {d.name!r} depends on unknown {dep!r}"

    def test_orders_are_unique(self):
        orders = [d.order for d in PIPELINE_PHASES]
        assert len(orders) == len(set(orders)), "Duplicate order values"

    def test_capture_has_render_artifacts(self):
        cap = next(d for d in PIPELINE_PHASES if d.name == "capture")
        assert len(cap.render_artifacts) > 0

    def test_polish_has_render_artifacts(self):
        pol = next(d for d in PIPELINE_PHASES if d.name == "polish")
        assert len(pol.render_artifacts) > 0
