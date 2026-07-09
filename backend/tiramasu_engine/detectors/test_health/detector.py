"""Test Health detector — orphan tests calling functions that no longer exist."""
from __future__ import annotations
import re
from tiramasu_engine.detectors.base import BaseDetector
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# Names that are test framework APIs, JS/Python builtins, or Playwright/Jest/Mocha/pytest
# internals — should never be flagged as "orphan calls"
_SKIP_CALLS: frozenset[str] = frozenset({
    # Python builtins
    "assert", "print", "len", "range", "list", "dict", "set", "str", "int", "float",
    "isinstance", "type", "hasattr", "getattr", "setattr", "iter", "next", "open",
    "enumerate", "zip", "map", "filter", "sorted", "reversed", "any", "all", "sum",
    "min", "max", "abs", "round", "repr", "format", "hash", "id", "callable",
    "super", "property", "staticmethod", "classmethod", "vars", "dir", "help",
    # pytest
    "assertEqual", "assertTrue", "assertFalse", "assertRaises", "assertIn",
    "assertNotIn", "assertIsNone", "assertIsNotNone", "assertAlmostEqual",
    "assertGreater", "assertLess", "mock", "patch", "fixture", "parametrize",
    "raises", "pytest", "setup", "teardown", "setup_method", "teardown_method",
    "setup_class", "teardown_class", "setUp", "tearDown",
    # Mocha / Jest
    "describe", "it", "test", "beforeEach", "afterEach", "beforeAll", "afterAll",
    "expect", "toBe", "toEqual", "toBeNull", "toBeTruthy", "toBeFalsy",
    "toContain", "toContainText", "toHaveLength", "toHaveCount", "toHaveBeenCalled",
    "toHaveBeenCalledWith", "toThrow", "toBeVisible", "toBeHidden", "toBeEnabled",
    "toBeDisabled", "toBeGreaterThan", "toBeLessThan", "toBeCloseTo",
    # Playwright
    "goto", "page", "locator", "click", "fill", "type", "press", "check", "uncheck",
    "select", "hover", "focus", "blur", "waitFor", "waitForTimeout", "waitForSelector",
    "waitForNavigation", "waitForResponse", "waitForRequest", "waitForLoadState",
    "screenshot", "getByText", "getByRole", "getByLabel", "getByPlaceholder",
    "getByTestId", "getByAltText", "getByTitle", "first", "last", "nth", "all",
    "boundingBox", "textContent", "innerHTML", "inputValue", "getAttribute",
    "isVisible", "isHidden", "isEnabled", "isDisabled", "isChecked",
    "dragTo", "tap", "dblclick", "dispatchEvent", "evaluate", "evaluateHandle",
    "addScriptTag", "addStyleTag", "route", "context", "browser",
    "mouse", "keyboard", "move", "down", "up",
    "toBeOK", "toHaveURL", "toHaveTitle", "toHaveScreenshot",
    # JS builtins / common patterns
    "require", "console", "log", "error", "warn", "info",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval", "Promise",
    "resolve", "reject", "then", "catch", "finally",
    "JSON", "parse", "stringify", "Array", "Object", "Number", "String",
    "Boolean", "Date", "Math", "Error", "Symbol",
    "join", "split", "slice", "splice", "push", "pop", "shift", "unshift",
    "indexOf", "findIndex", "find", "includes", "from", "of", "entries",
    "keys", "values", "assign", "freeze", "create", "keys",
    "reduce", "forEach", "map", "every", "some", "flat", "flatMap",
    "trim", "toLowerCase", "toUpperCase", "replace", "match", "search",
    "url", "method", "body", "headers", "status", "json", "text", "blob",
    "label", "value", "modal", "request", "response",
    "repeat", "charAt", "charCodeAt", "substring", "startsWith", "endsWith",
    # Common test variables (local vars treated as refs)
    "result", "response", "data", "error", "err", "res", "req", "ctx",
    "it", "its", "btn", "node", "el", "elem", "container", "wrapper",
})

_TEST_FILE_PATTERNS = re.compile(
    r"(test_.*\.(py|js|jsx|ts|tsx)|.*_test\.(py|js|jsx|ts|tsx)|.*\.(test|spec)\.(js|jsx|ts|tsx))$"
)


def _is_test_file(rel_path: str) -> bool:
    return bool(_TEST_FILE_PATTERNS.search(rel_path))


class TestHealthDetector(BaseDetector):
    category = DetectionCategory.TEST_HEALTH

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # Identify test files from indexed file list
        test_file_paths: set[str] = {
            f.relative_path for f in context.files if _is_test_file(f.relative_path)
        }
        if not test_file_paths:
            return findings

        # Collect all non-test symbol definitions by name
        all_main_defs: set[str] = set()
        for name, defs in context.symbol_graph.definitions.items():
            for d in defs:
                if not _is_test_file(d.file_path):
                    all_main_defs.add(name)

        # Build a set of local variable names declared in each test file
        # (const/let/var/Python assignments) — these should not be flagged as orphan calls
        local_vars_by_file: dict[str, set[str]] = {}
        for f in context.files:
            if f.relative_path not in test_file_paths:
                continue
            local_names: set[str] = set()
            for line in f.content.splitlines():
                # JS: const/let/var declarations
                m = re.match(r"\s*(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=", line)
                if m:
                    local_names.add(m.group(1))
                # Python: simple assignment at function body level
                m2 = re.match(r"\s+([a-z_][a-zA-Z0-9_]*)\s*=\s*[^=]", line)
                if m2:
                    local_names.add(m2.group(1))
            local_vars_by_file[f.relative_path] = local_names

        # For each test file, collect test functions and what they call
        # from the symbol graph references
        test_refs: dict[str, list] = {}  # file -> list of refs from that file
        for name, refs in context.symbol_graph.references.items():
            for ref in refs:
                if ref.file_path in test_file_paths and ref.kind == "call":
                    test_refs.setdefault(ref.file_path, []).append(ref)

        # Find test functions in test files
        test_funcs: dict[str, list] = {}
        for name, defs in context.symbol_graph.definitions.items():
            if not (name.startswith("test_") or name.startswith("Test")):
                continue
            for d in defs:
                if d.file_path in test_file_paths:
                    test_funcs.setdefault(d.file_path, []).append(d)

        # Check: test files that reference functions not present in main code
        # These are "orphan tests" — testing something that no longer exists
        reported: set[str] = set()
        for file_path, refs in test_refs.items():
            for ref in refs:
                called_name = ref.name
                # Skip common test helpers, assertions, fixtures
                if called_name in _SKIP_CALLS:
                    continue
                # Skip very short names (likely variables or single-letter tokens)
                if len(called_name) <= 3:
                    continue
                # Skip camelCase method chains (e.g. srcHandle, deleteBtn, tgtHandle)
                # These are local test variable names, not orphan function calls
                if any(called_name.endswith(suffix) for suffix in (
                    "Btn", "Handle", "El", "Elem", "Ref", "Node", "Box",
                    "X", "Y", "W", "H", "Id", "Idx",
                )):
                    continue
                # Skip if it's defined in main code or the test file itself
                if called_name in all_main_defs:
                    continue
                # Check if the name appears in any definition at all
                if called_name in context.symbol_graph.definitions:
                    continue
                # Skip if it's a local variable declared in the same test file
                local_vars = local_vars_by_file.get(file_path, set())
                if called_name in local_vars:
                    continue
                # This is a call to something not in the symbol graph at all
                key = f"{file_path}:{called_name}"
                if key in reported:
                    continue
                reported.add(key)
                findings.append(Finding(
                    category=DetectionCategory.TEST_HEALTH,
                    title=f"Orphan test call: `{called_name}` not found in codebase",
                    description=(
                        f"`{called_name}` is called in test file `{file_path}` but is not "
                        f"defined anywhere in the scanned source. This test may be testing "
                        f"a function that has been removed or renamed."
                    ),
                    evidence=[Evidence(
                        file_path=file_path,
                        line_start=ref.line,
                        line_end=ref.line,
                        snippet=f"{called_name}(...)",
                    )],
                    confidence=0.8,
                    risk=RiskLevel.MEDIUM,
                    effort=EffortLevel.MINUTES,
                    benefit="Removes tests that give false coverage signals.",
                ))

        return findings
