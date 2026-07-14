"""Tests for the TestHealthDetector — orphan test call detection."""
from __future__ import annotations
import pytest
from tiramisu_engine.detectors.test_health.detector import TestHealthDetector
from tiramisu_engine.ast_engine import PARSERS
from tiramisu_engine.graph.symbol_graph import SymbolGraph
from tiramisu_engine.graph.context import AnalysisContext
from tiramisu_engine.models.findings import DetectionCategory
from tests.unit.conftest import make_file_info, make_symbol_def, make_symbol_ref


def _parse_into_graph(files, main_defs=None):
    """Parse the given FileInfo objects into a SymbolGraph (defs + refs)."""
    g = SymbolGraph()
    parsed = []
    for f in files:
        parser = PARSERS.get(f.language)
        if parser is None:
            continue
        defs, refs = parser.parse_file(f)
        parsed.append((defs, refs))
    for defs, _ in parsed:
        for d in defs:
            g.add_definition(d)
    for _, refs in parsed:
        for r in refs:
            g.add_reference(r)
    # Add any extra main-code definitions (functions the test calls into).
    for d in (main_defs or []):
        g.add_definition(d)
    return AnalysisContext(files=files, symbol_graph=g, repo_path=".")


def test_for_of_destructure_not_flagged_as_orphan() -> None:
    """`variationIndex` destructured in `for (const {...} of ...)` is a local
    binding, not a call to a missing function. Regression for the regex that
    previously required '=' after the destructuring pattern."""
    test_src = (
        "const allCases = [{ scenario: 'a', query: 'q', variationIndex: 1 }];\n"
        "for (const { scenario, query, variationIndex } of allCases) {\n"
        "  console.log(`${scenario} v${variationIndex}: ${query}`);\n"
        "  String(variationIndex);\n"  # variationIndex used as a call arg
        "}\n"
    )
    files = [make_file_info("tests/stress.spec.ts", test_src, "typescript")]
    ctx = _parse_into_graph(files)
    findings = TestHealthDetector().detect(ctx)
    orphan_names = {f.title for f in findings if "Orphan" in f.title}
    assert not any("variationIndex" in t for t in orphan_names), (
        f"for-of destructured local should not be flagged: {orphan_names}"
    )


def test_multiline_typed_const_not_flagged_as_orphan() -> None:
    """`const byScenario: Record<...>\\n = {}` spans lines; the per-line regex
    misses the `=`, so the whole-file safety net must still treat it as local."""
    test_src = (
        "function summarize() {\n"
        "  const byScenario: Record<\n"
        "    string,\n"
        "    { passed: number; failed: number }\n"
        "  > = {};\n"
        "  Object.entries(byScenario);\n"  # byScenario used as a call arg
        "  return byScenario;\n"
        "}\n"
    )
    files = [make_file_info("tests/summary.spec.ts", test_src, "typescript")]
    ctx = _parse_into_graph(files)
    findings = TestHealthDetector().detect(ctx)
    orphan_names = {f.title for f in findings if "Orphan" in f.title}
    assert not any("byScenario" in t for t in orphan_names), (
        f"multiline typed const should not be flagged: {orphan_names}"
    )


def test_genuine_orphan_call_is_flagged() -> None:
    """A bare call to a name that is neither defined, imported, nor a local
    variable should still be reported as an orphan test call."""
    test_src = (
        "removedHelper();\n"  # not defined anywhere, not a local var
    )
    files = [make_file_info("tests/real.spec.ts", test_src, "typescript")]
    ctx = _parse_into_graph(files)
    findings = TestHealthDetector().detect(ctx)
    assert any("removedHelper" in f.title for f in findings), (
        "a genuine orphan call should be flagged"
    )


def test_for_in_destructure_not_flagged() -> None:
    """`for (const [key, value] of Object.entries(x))` — array destructure in a
    for-of loop must register key/value as locals."""
    test_src = (
        "for (const [key, value] of Object.entries({ a: 1 })) {\n"
        "  console.log(key, value);\n"
        "}\n"
    )
    files = [make_file_info("tests/loop.spec.ts", test_src, "typescript")]
    ctx = _parse_into_graph(files)
    findings = TestHealthDetector().detect(ctx)
    orphan_names = {f.title for f in findings if "Orphan" in f.title}
    assert not any("key" in t or "value" in t for t in orphan_names), (
        f"for-of array destructure bindings should not be flagged: {orphan_names}"
    )
