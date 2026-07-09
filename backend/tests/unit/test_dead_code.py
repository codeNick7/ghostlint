"""Tests for the DeadCodeDetector."""
from __future__ import annotations
import pytest
from tiramasu_engine.detectors.dead_code.detector import DeadCodeDetector
from tiramasu_engine.graph.symbol_graph import SymbolGraph
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.models.findings import DetectionCategory
from tests.unit.conftest import make_symbol_def, make_symbol_ref, make_file_info


def make_context(defs=None, refs=None, files=None):
    g = SymbolGraph()
    for d in (defs or []):
        g.add_definition(d)
    for r in (refs or []):
        g.add_reference(r)
    return AnalysisContext(
        files=files or [],
        symbol_graph=g,
        repo_path=".",
    )


def test_detects_unreferenced_function() -> None:
    d = make_symbol_def("orphan", kind="function", file_path="utils.py", is_private=True)
    ctx = make_context(defs=[d])
    findings = DeadCodeDetector().detect(ctx)
    assert any(f.category == DetectionCategory.DEAD_CODE for f in findings)


def test_does_not_flag_referenced_function() -> None:
    d = make_symbol_def("used_func", kind="function", file_path="utils.py")
    r = make_symbol_ref("used_func", file_path="main.py")
    ctx = make_context(defs=[d], refs=[r])
    findings = DeadCodeDetector().detect(ctx)
    assert not any("used_func" in f.title for f in findings)


def test_does_not_flag_entry_points() -> None:
    """main(), test_ prefixed functions, and dunder methods are entry points."""
    entry_defs = [
        make_symbol_def("main", kind="function", file_path="app.py"),
        make_symbol_def("test_something", kind="function", file_path="test_app.py"),
        make_symbol_def("__init__", kind="method", file_path="cls.py"),
    ]
    ctx = make_context(defs=entry_defs)
    findings = DeadCodeDetector().detect(ctx)
    flagged = {f.title for f in findings}
    assert not any("main" in t or "test_something" in t or "__init__" in t for t in flagged)


def test_does_not_flag_decorated_routes() -> None:
    d = make_symbol_def(
        "get_health",
        kind="function",
        file_path="routes.py",
        decorators=["@router.get('/health')"],
    )
    ctx = make_context(defs=[d])
    findings = DeadCodeDetector().detect(ctx)
    assert not any("get_health" in f.title for f in findings)


def test_confidence_higher_for_private() -> None:
    d_private = make_symbol_def("_unused_helper", kind="function", file_path="utils.py", is_private=True)
    d_public = make_symbol_def("unused_helper", kind="function", file_path="utils.py", is_private=False)
    ctx = make_context(defs=[d_private, d_public])
    findings = DeadCodeDetector().detect(ctx)
    private_f = next((f for f in findings if "_unused_helper" in f.title), None)
    public_f = next((f for f in findings if "unused_helper" in f.title and "_" not in f.title.split("`")[1][:1]), None)
    if private_f and public_f:
        assert private_f.confidence >= public_f.confidence


def test_does_not_flag_alembic_upgrade_downgrade() -> None:
    """upgrade/downgrade in alembic migration files are called by Alembic at runtime."""
    defs = [
        make_symbol_def("upgrade", kind="function", file_path="backend/alembic/versions/20251108_add_users.py"),
        make_symbol_def("downgrade", kind="function", file_path="backend/alembic/versions/20251108_add_users.py"),
        make_symbol_def("upgrade", kind="function", file_path="migrations/versions/0001_init.py"),
    ]
    ctx = make_context(defs=defs)
    findings = DeadCodeDetector().detect(ctx)
    flagged_titles = {f.title for f in findings}
    assert not any("upgrade" in t or "downgrade" in t for t in flagged_titles), (
        f"Alembic migration entry points should not be flagged: {flagged_titles}"
    )


def test_detects_unused_module_python() -> None:
    """A Python file never imported by any other file is flagged as an unused module."""
    from tiramasu_engine.graph.context import AnalysisContext
    from tiramasu_engine.graph.symbol_graph import SymbolGraph
    from tests.unit.conftest import make_file_info

    files = [
        make_file_info("src/main.py", "from src.utils.helpers import help\n"),
        make_file_info("src/utils/helpers.py", "def help(): pass\n"),
        make_file_info("src/orphan.py", "def noop(): pass\n"),  # never imported
    ]
    ctx = AnalysisContext(files=files, symbol_graph=SymbolGraph(), repo_path=".")
    findings = DeadCodeDetector()._detect_unused_modules(ctx)
    flagged = [f.evidence[0].file_path for f in findings]
    assert "src/orphan.py" in flagged
    assert "src/utils/helpers.py" not in flagged
    assert "src/main.py" not in flagged  # main.py is entry point stem


def test_detects_unused_module_typescript() -> None:
    """A TS component never imported by any other file is flagged."""
    from tiramasu_engine.graph.context import AnalysisContext
    from tiramasu_engine.graph.symbol_graph import SymbolGraph
    from tests.unit.conftest import make_file_info

    files = [
        make_file_info("components/Button.tsx", "export default function Button() {}", "typescript"),
        make_file_info("pages/index.tsx", 'import Button from "../components/Button"\nexport default function Home() {}', "typescript"),
        make_file_info("components/Ghost.tsx", "export default function Ghost() {}", "typescript"),
    ]
    ctx = AnalysisContext(files=files, symbol_graph=SymbolGraph(), repo_path=".")
    findings = DeadCodeDetector()._detect_unused_modules(ctx)
    flagged = [f.evidence[0].file_path for f in findings]
    assert "components/Ghost.tsx" in flagged
    assert "components/Button.tsx" not in flagged
    assert "pages/index.tsx" not in flagged  # index is entry point stem


def test_findings_sorted_by_confidence() -> None:
    defs = [
        make_symbol_def(f"func_{i}", kind="function", file_path="utils.py", is_private=(i % 2 == 0))
        for i in range(5)
    ]
    ctx = make_context(defs=defs)
    findings = DeadCodeDetector().detect(ctx)
    confidences = [f.confidence for f in findings]
    assert confidences == sorted(confidences, reverse=True)
