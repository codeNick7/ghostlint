"""Tests for the DuplicateLogicDetector — title clarity for same-name pairs."""
from __future__ import annotations
import pytest
from ghostlint_engine.detectors.duplicate_logic.detector import DuplicateLogicDetector
from ghostlint_engine.graph.symbol_graph import SymbolGraph
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.models.findings import DetectionCategory
from tests.unit.conftest import make_symbol_def, make_file_info


def _ctx(defs, files=None):
    g = SymbolGraph()
    for d in defs:
        g.add_definition(d)
    return AnalysisContext(files=files or [], symbol_graph=g, repo_path=".")


def test_same_name_cross_file_gets_clear_title():
    """When two different files define a helper of the same name, the title must
    say 'duplicated across files' rather than the confusing 'X and X'."""
    # Two sizeable Python functions with identical structure and the same name.
    body = (
        "def _get_db():\n"
        "    session = SessionLocal()\n"
        "    try:\n"
        "        yield session\n"
        "    finally:\n"
        "        session.close()\n"
    )
    files = [
        make_file_info("app/api/routes_user.py", body, "python"),
        make_file_info("app/api/routes_planner.py", body, "python"),
    ]
    # Parse real defs so fingerprints are computed from actual ASTs.
    from ghostlint_engine.ast_engine import PARSERS
    g = SymbolGraph()
    for f in files:
        parser = PARSERS.get(f.language)
        defs, _ = parser.parse_file(f)
        for d in defs:
            g.add_definition(d)
    ctx = AnalysisContext(files=files, symbol_graph=g, repo_path=".")
    findings = DuplicateLogicDetector().detect(ctx)
    dup_titles = [f.title for f in findings if "Duplicate logic" in f.title]
    assert dup_titles, "expected at least one duplicate finding"
    # The title should NOT be the confusing "X and X" form.
    assert any("duplicated across files" in t for t in dup_titles), (
        f"same-name cross-file pair should use the clearer title: {dup_titles}"
    )


def test_distinct_name_pair_keeps_standard_title():
    """Two structurally-identical functions with DIFFERENT names keep the
    standard 'X and Y' title."""
    body_a = (
        "def compute_score(a, b):\n"
        "    total = a + b\n"
        "    bonus = total * 2\n"
        "    return bonus\n"
    )
    body_b = (
        "def compute_rating(a, b):\n"
        "    total = a + b\n"
        "    bonus = total * 2\n"
        "    return bonus\n"
    )
    files = [
        make_file_info("app/services/scoring.py", body_a, "python"),
        make_file_info("app/services/rating.py", body_b, "python"),
    ]
    from ghostlint_engine.ast_engine import PARSERS
    g = SymbolGraph()
    for f in files:
        parser = PARSERS.get(f.language)
        defs, _ = parser.parse_file(f)
        for d in defs:
            g.add_definition(d)
    ctx = AnalysisContext(files=files, symbol_graph=g, repo_path=".")
    findings = DuplicateLogicDetector().detect(ctx)
    dup_titles = [f.title for f in findings if "Duplicate logic" in f.title]
    assert any("compute_score" in t and "compute_rating" in t for t in dup_titles), (
        f"distinct-name pair should keep 'X and Y' title: {dup_titles}"
    )
