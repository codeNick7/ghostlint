from __future__ import annotations
from tiramasu_engine.ast_engine.base import SymbolDef
from tiramasu_engine.detectors.base import BaseDetector
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# Symbols that are valid entry points and should never be flagged
_SKIP_NAMES = {
    "main", "__init__", "__new__", "__call__", "__del__",
    "__str__", "__repr__", "__len__", "__iter__", "__next__",
    "__enter__", "__exit__", "__getitem__", "__setitem__", "__delitem__",
    "__contains__", "__eq__", "__hash__", "__lt__", "__le__", "__gt__", "__ge__",
    "__add__", "__sub__", "__mul__", "__truediv__", "__floordiv__", "__mod__",
    "__bool__", "__int__", "__float__", "__bytes__", "__format__",
    "setUp", "tearDown", "setUpClass", "tearDownClass",
    "app", "router",  # common FastAPI / Flask entry points
}

# Decorator patterns that indicate the symbol is an entry point
_ENTRY_DECORATORS = {
    "@app.route", "@app.get", "@app.post", "@app.put", "@app.delete",
    "@app.patch", "@router.get", "@router.post", "@router.put",
    "@router.delete", "@router.patch", "@click.command", "@click.group",
    "@pytest.fixture", "@property", "@staticmethod", "@classmethod",
    "@app.command", "@typer.command",
}


def _is_entry_point(sym: SymbolDef) -> bool:
    if sym.name in _SKIP_NAMES:
        return True
    if sym.name.startswith("test_") or sym.name.startswith("Test"):
        return True
    # Dunder methods
    if sym.name.startswith("__") and sym.name.endswith("__"):
        return True
    # Decorated with a known entry-point decorator
    for dec in sym.decorators:
        for pattern in _ENTRY_DECORATORS:
            if pattern in dec:
                return True
    return False


def _confidence(sym: SymbolDef) -> float:
    score = 0.5

    # Private symbols unreferenced anywhere = very likely dead
    if sym.is_private:
        score += 0.3

    # Free functions (not methods) with no decorators = unlikely to be overrides or hooks
    if sym.kind == "function" and not sym.decorators:
        score += 0.15

    # Arrow functions / lambdas assigned to a variable
    if sym.kind == "arrow_function":
        score += 0.1

    # Methods could be overrides or called via polymorphism — lower confidence
    if sym.kind == "method":
        score -= 0.15

    # Classes might be instantiated dynamically (reflection, factories)
    if sym.kind == "class":
        score -= 0.1

    return round(min(max(score, 0.0), 1.0), 2)


def _risk(sym: SymbolDef) -> RiskLevel:
    if sym.is_private:
        return RiskLevel.LOW
    if sym.kind in ("function", "arrow_function"):
        return RiskLevel.LOW
    if sym.kind == "method":
        return RiskLevel.MEDIUM
    return RiskLevel.MEDIUM


class DeadCodeDetector(BaseDetector):
    category = DetectionCategory.DEAD_CODE
    CONFIDENCE_THRESHOLD = 0.6

    def detect(self, context: AnalysisContext) -> list[Finding]:
        unreferenced = context.symbol_graph.get_unreferenced()
        findings: list[Finding] = []

        for sym in unreferenced:
            if _is_entry_point(sym):
                continue

            confidence = _confidence(sym)
            if confidence < self.CONFIDENCE_THRESHOLD:
                continue

            # Try to get a code snippet for the evidence
            snippet = self._get_snippet(sym, context)

            findings.append(Finding(
                category=DetectionCategory.DEAD_CODE,
                title=f"Unused {sym.kind}: `{sym.name}`",
                description=(
                    f"`{sym.name}` is defined at line {sym.line_start} in `{sym.file_path}` "
                    f"but is never called or imported anywhere in this repository."
                ),
                evidence=[Evidence(
                    file_path=sym.file_path,
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    snippet=snippet,
                )],
                confidence=confidence,
                risk=_risk(sym),
                effort=EffortLevel.MINUTES,
                benefit="Reduces codebase size and cognitive load. Safe to delete.",
            ))

        # Sort by confidence descending so highest-confidence findings appear first
        findings.sort(key=lambda f: f.confidence, reverse=True)
        return findings

    def _get_snippet(self, sym: SymbolDef, context: AnalysisContext) -> str:
        for file_info in context.files:
            if file_info.relative_path == sym.file_path:
                lines = file_info.content.splitlines()
                start = max(0, sym.line_start - 1)
                end = min(len(lines), sym.line_start + 2)  # show definition line + 2
                return "\n".join(lines[start:end])
        return ""
