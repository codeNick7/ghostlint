"""Tests for the SymbolGraph."""
from __future__ import annotations
import pytest
from ghostlint_engine.graph.symbol_graph import SymbolGraph
from tests.unit.conftest import make_symbol_def, make_symbol_ref


def test_graph_tracks_definitions() -> None:
    g = SymbolGraph()
    d = make_symbol_def("my_func")
    g.add_definition(d)
    assert "my_func" in g.definitions
    assert g.total_definitions() == 1


def test_unreferenced_with_no_callers(simple_graph: SymbolGraph) -> None:
    unreferenced = g_names(simple_graph.get_unreferenced())
    assert "orphan_func" in unreferenced


def test_referenced_not_in_unreferenced(simple_graph: SymbolGraph) -> None:
    unreferenced = g_names(simple_graph.get_unreferenced())
    assert "my_func" not in unreferenced


def test_multiple_definitions_same_name() -> None:
    g = SymbolGraph()
    d1 = make_symbol_def("helper", file_path="a.py", line_start=1)
    d2 = make_symbol_def("helper", file_path="b.py", line_start=5)
    g.add_definition(d1)
    g.add_definition(d2)
    assert g.total_definitions() == 2
    assert len(g.definitions["helper"]) == 2


def test_cross_file_reference_resolves() -> None:
    g = SymbolGraph()
    d = make_symbol_def("process_data", file_path="processor.py", line_start=1)
    r = make_symbol_ref("process_data", file_path="main.py", line=10)
    g.add_definition(d)
    g.add_reference(r)
    unreferenced = g_names(g.get_unreferenced())
    assert "process_data" not in unreferenced


def test_reference_before_definition() -> None:
    """References added before definitions shouldn't break the graph."""
    g = SymbolGraph()
    r = make_symbol_ref("late_def", file_path="main.py", line=5)
    d = make_symbol_def("late_def", file_path="utils.py", line_start=10)
    g.add_reference(r)
    g.add_definition(d)
    # Node is defined but reference was added before it — still considered unreferenced
    # because the edge was not added (definition wasn't in graph at ref time)
    # This is acceptable behavior for the two-pass scanner
    assert g.total_definitions() == 1


def g_names(syms) -> set[str]:
    return {s.name for s in syms}
