from __future__ import annotations
import re
from pathlib import Path
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

# File path patterns whose functions are called by external frameworks at runtime.
# Key: path segment that must appear in the file path.
# Value: set of function names that are framework-managed entry points in that context.
_PATH_ENTRY_POINTS: dict[str, set[str]] = {
    "alembic/versions": {"upgrade", "downgrade"},
    "migrations/versions": {"upgrade", "downgrade"},
    "migrations": {"upgrade", "downgrade"},
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
    # Framework-managed functions called by external tools at runtime (e.g. Alembic)
    normalized = sym.file_path.replace("\\", "/")
    for path_segment, names in _PATH_ENTRY_POINTS.items():
        if path_segment in normalized and sym.name in names:
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


# Python: "from X import ..." or "import X"
_PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(\.+[\w.]*|[\w][\w.]*)\s+import|import\s+([\w][\w.]*))",
    re.MULTILINE,
)

# JS/TS: import ... from 'path' / import('path') / require('path')
# Captures the quoted module path string (group 1).
_JS_IMPORT_RE = re.compile(
    r"""(?:from\s+|import\s*\(|require\s*\()['"](\.{1,2}/[^'"]+|@?[\w][\w/.-]*)['"]\)?""",
    re.MULTILINE,
)

# File stems that are always entry points — never flag these as unused modules.
_MODULE_ENTRY_POINT_STEMS = {
    # Python
    "__init__", "main", "manage", "settings", "config", "wsgi", "asgi",
    "conftest", "setup", "app", "server", "celery", "worker", "tasks",
    "urls", "admin", "signals", "middleware",  # Django
    "entrypoint", "entry_point", "run", "start",
    # JS/TS
    "index",         # index.ts/js is always the package entry point
    "next.config",   # Next.js config files
    "tailwind.config", "postcss.config", "jest.config", "vitest.config",
    "vite.config", "webpack.config", "babel.config", "eslint.config",
    "tsconfig",
    "globals",       # globals.css / globals.ts
    "layout",        # Next.js layout.tsx
    "page",          # Next.js page.tsx
    "route",         # Next.js API route.ts
    "error",         # Next.js error.tsx
    "loading",       # Next.js loading.tsx
    "not-found",     # Next.js not-found.tsx
}

# Path segments that indicate a file is loaded dynamically by a framework.
_DYNAMIC_PATH_SEGMENTS = {
    "alembic/versions", "migrations/versions", "migrations",
    "scripts", "fixtures", "seeds",
}


def _build_referenced_module_keys(context: AnalysisContext) -> set[str]:
    """
    Scan all files for import statements and return a set of all module
    name segments that are referenced.

    We collect every suffix of every dotted/slashed path so that an import
    like 'from myapp.utils.helpers import x' or
    'import { x } from "../utils/helpers"'
    registers 'myapp.utils.helpers', 'utils.helpers', and 'helpers' — this
    lets us match against any file whose repo-relative path ends in any of
    those segments.
    """
    referenced: set[str] = set()

    for file_info in context.files:
        content = file_info.content

        if file_info.language == "python":
            for m in _PY_IMPORT_RE.finditer(content):
                raw = m.group(1) or m.group(2) or ""
                # Strip leading dots (relative markers: ".utils", "..db.session")
                module = raw.lstrip(".")
                if not module:
                    continue
                parts = module.split(".")
                for i in range(len(parts)):
                    referenced.add(".".join(parts[i:]))

        elif file_info.language in ("javascript", "typescript"):
            for m in _JS_IMPORT_RE.finditer(content):
                raw = m.group(1) or ""
                # Normalize path separators and strip extensions
                norm = raw.replace("\\", "/")
                for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
                    norm = norm.removesuffix(ext)
                # Strip trailing /index
                if norm.endswith("/index"):
                    norm = norm[: -len("/index")]
                # Strip leading ./ or ../
                norm = norm.lstrip("./").lstrip("../").lstrip("./")
                # Register all path-segment suffixes
                parts = [p for p in norm.replace("/", ".").split(".") if p]
                for i in range(len(parts)):
                    referenced.add(".".join(parts[i:]))
                # Also register the raw slash form for path matching
                slash_parts = [p for p in norm.split("/") if p]
                for i in range(len(slash_parts)):
                    referenced.add("/".join(slash_parts[i:]))

    return referenced


def _is_module_entry_point(relative_path: str) -> bool:
    """Return True if this file should never be flagged as an unused module."""
    norm = relative_path.replace("\\", "/")
    stem = Path(norm).stem

    if stem in _MODULE_ENTRY_POINT_STEMS:
        return True
    # Python test files
    if stem.startswith("test_") or stem.endswith("_test"):
        return True
    # JS/TS test files
    if ".test." in norm or ".spec." in norm:
        return True
    # __init__.py — always imported implicitly by package machinery
    if "__init__" in norm:
        return True
    # Dynamically loaded by frameworks
    for seg in _DYNAMIC_PATH_SEGMENTS:
        if seg in norm:
            return True
    return False


def _file_match_keys(relative_path: str) -> list[str]:
    """
    Return all dotted-path suffixes by which this file could be imported.
    E.g. 'backend/myapp/utils/helpers.py' →
         ['backend.myapp.utils.helpers', 'myapp.utils.helpers', 'utils.helpers', 'helpers']
    """
    norm = relative_path.replace("\\", "/").removesuffix(".py")
    # Also handle JS/TS index files and extensions
    for ext in (".ts", ".tsx", ".js", ".jsx"):
        norm = norm.removesuffix(ext)
    # Strip trailing /index so 'components/Button/index' → 'Button'
    if norm.endswith("/index"):
        norm = norm[: -len("/index")]
    parts = norm.split("/")
    return [".".join(parts[i:]) for i in range(len(parts))]


class DeadCodeDetector(BaseDetector):
    category = DetectionCategory.DEAD_CODE
    CONFIDENCE_THRESHOLD = 0.6

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # --- Pass 1: symbol-level dead code ---
        unreferenced = context.symbol_graph.get_unreferenced()
        for sym in unreferenced:
            if _is_entry_point(sym):
                continue
            confidence = _confidence(sym)
            if confidence < self.CONFIDENCE_THRESHOLD:
                continue
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

        # --- Pass 2: module-level dead code (entire files never imported) ---
        findings.extend(self._detect_unused_modules(context))

        findings.sort(key=lambda f: f.confidence, reverse=True)
        return findings

    def _detect_unused_modules(self, context: AnalysisContext) -> list[Finding]:
        referenced = _build_referenced_module_keys(context)
        findings: list[Finding] = []

        for file_info in context.files:
            if _is_module_entry_point(file_info.relative_path):
                continue

            match_keys = _file_match_keys(file_info.relative_path)
            if any(k in referenced for k in match_keys):
                continue

            # File has no import anywhere in the repo pointing to it.
            # Confidence: 0.72 — reasonably high but not max, since dynamic
            # loading (importlib, plugin systems) can't be statically detected.
            findings.append(Finding(
                category=DetectionCategory.DEAD_CODE,
                title=f"Unused module: `{Path(file_info.relative_path).name}`",
                description=(
                    f"`{file_info.relative_path}` is never imported by any other file in this "
                    f"repository. The entire module may be dead code."
                ),
                evidence=[Evidence(
                    file_path=file_info.relative_path,
                    line_start=1,
                    line_end=1,
                    snippet=file_info.content.splitlines()[0] if file_info.content else "",
                )],
                confidence=0.72,
                risk=RiskLevel.MEDIUM,
                effort=EffortLevel.MINUTES,
                benefit="Removing an unimported module eliminates its entire maintenance surface.",
            ))

        return findings

    def _get_snippet(self, sym: SymbolDef, context: AnalysisContext) -> str:
        for file_info in context.files:
            if file_info.relative_path == sym.file_path:
                lines = file_info.content.splitlines()
                start = max(0, sym.line_start - 1)
                end = min(len(lines), sym.line_start + 2)  # show definition line + 2
                return "\n".join(lines[start:end])
        return ""
