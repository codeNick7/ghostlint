"""Tests for the RefactorDetector — synonym-verb duplicate detection."""
from __future__ import annotations
import pytest
from tiramisu_engine.detectors.refactor.detector import RefactorDetector
from tiramisu_engine.graph.symbol_graph import SymbolGraph
from tiramisu_engine.graph.context import AnalysisContext
from tiramisu_engine.models.findings import DetectionCategory
from tests.unit.conftest import make_symbol_def, make_file_info


def _ctx(defs, files=None):
    g = SymbolGraph()
    for d in defs:
        g.add_definition(d)
    return AnalysisContext(files=files or [], symbol_graph=g, repo_path=".")


def test_cross_language_synonym_pair_not_flagged() -> None:
    """A Python route handler `get_profile` and a TypeScript client fetch
    `fetchProfile` share the noun 'profile' but are not duplicate implementations
    — they live in different runtimes. Regression for cross-language FP."""
    defs = [
        make_symbol_def("get_profile", kind="function",
                        file_path="backend/app/api/routes_user.py", line_start=39),
        make_symbol_def("fetchProfile", kind="function",
                        file_path="web/app/profile/page.tsx", line_start=75),
    ]
    ctx = _ctx(defs)
    findings = RefactorDetector().detect(ctx)
    possible = [f.title for f in findings if "Possible duplicates" in f.title]
    assert not any("get_profile" in t and "fetchProfile" in t for t in possible), (
        f"cross-language synonym pair should not be flagged: {possible}"
    )


def test_same_language_synonym_pair_flagged() -> None:
    """Two genuinely-duplicate same-language functions (get_user / fetch_user)
    in different files SHOULD be flagged as possible duplicates."""
    defs = [
        make_symbol_def("get_user", kind="function",
                        file_path="backend/app/services/user_service.py", line_start=10),
        make_symbol_def("fetch_user", kind="function",
                        file_path="backend/app/repositories/user_repo.py", line_start=20),
    ]
    ctx = _ctx(defs)
    findings = RefactorDetector().detect(ctx)
    possible = [f.title for f in findings if "Possible duplicates" in f.title]
    assert any("get_user" in t and "fetch_user" in t for t in possible), (
        f"same-language synonym pair should be flagged: {possible}"
    )


def test_same_file_synonym_pair_not_flagged() -> None:
    """Two differently-named helpers in the SAME file are normal, not an
    incomplete refactor — they should not be flagged as possible duplicates."""
    defs = [
        make_symbol_def("get_config", kind="function",
                        file_path="backend/app/config.py", line_start=10),
        make_symbol_def("fetch_config", kind="function",
                        file_path="backend/app/config.py", line_start=40),
    ]
    ctx = _ctx(defs)
    findings = RefactorDetector().detect(ctx)
    possible = [f.title for f in findings if "Possible duplicates" in f.title]
    assert not any("get_config" in t and "fetch_config" in t for t in possible), (
        f"same-file synonym pair should not be flagged: {possible}"
    )
