"""Test Health detector — orphan tests calling functions that no longer exist."""
from __future__ import annotations
import re
from ghostlint_engine.detectors.base import BaseDetector
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.models.findings import (
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
    "input", "exit", "bytes", "bytearray", "memoryview", "complex", "bool", "frozenset",
    "tuple", "object", "Exception", "ValueError", "TypeError", "KeyError",
    "AttributeError", "RuntimeError", "StopIteration", "NotImplementedError",
    "ImportError", "FileNotFoundError", "ConnectionError", "TimeoutError",
    "SystemExit", "KeyboardInterrupt", "GeneratorExit", "OSError", "IOError",
    "ZeroDivisionError", "OverflowError", "PermissionError", "AssertionError",
    # Python module-level dunder attributes (referenced as bare names in tests)
    "__file__", "__name__", "__doc__", "__path__", "__package__", "__spec__",
    # pytest
    "assertEqual", "assertTrue", "assertFalse", "assertRaises", "assertIn",
    "assertNotIn", "assertIsNone", "assertIsNotNone", "assertAlmostEqual",
    "assertGreater", "assertLess", "mock", "patch", "fixture", "parametrize",
    "raises", "pytest", "setup", "teardown", "setup_method", "teardown_method",
    "setup_class", "teardown_class", "setUp", "tearDown", "monkeypatch",
    "capsys", "caplog", "tmp_path", "tmpdir", "capture", "mark",
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
    # Node.js globals and browser builtins referenced as bare calls
    "__dirname", "__filename", "encodeURIComponent", "decodeURIComponent",
    "encodeURI", "decodeURI", "process", "global", "globalThis", "Buffer",
    "exports", "module",
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

# Python standard-library module names commonly imported and called as bare
# functions in tests (e.g. `time.sleep`, `datetime(...)`, `Path(...)`). A bare
# call to one of these is almost certainly a stdlib constructor/function, not a
# missing project function. These are only used to suppress false-positive orphan
# calls; they never cause a real miss to be hidden (a genuine project function
# named `time`/`json`/etc. would be in the symbol graph and pass the checks above).
_STDLIB_MODULES: frozenset[str] = frozenset({
    "datetime", "date", "time", "timedelta", "timezone",
    "Path", "PurePath", "PosixPath", "WindowsPath",
    "json", "os", "sys", "re", "math", "random", "uuid",
    "collections", "defaultdict", "Counter", "OrderedDict", "deque",
    "itertools", "functools", "operator", "copy", "deepcopy",
    "logging", "getLogger", "basicConfig", "warning", "warn",
    "argparse", "ArgumentParser",
    "subprocess", "threading", "multiprocessing", "asyncio", "queue",
    "tempfile", "shutil", "glob", "fnmatch", "pathlib",
    "hashlib", "hmac", "secrets", "base64", "binascii",
    "io", "BytesIO", "StringIO", "TextIOWrapper",
    "traceback", "print_exc", "format_exc",
    "types", "SimpleNamespace", "Mapping", "Sequence",
    "decimal", "fractions", "statistics",
    "csv", "configparser", "xml", "html", "urllib", "http",
    "socket", "ssl", "select",
    "sqlite3", "shelve", "pickle", "json",
    "unittest", "MagicMock", "Mock", "AsyncMock", "patch",
    "warnings", "contextlib", "dataclasses",
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

        # Build a set of local symbol names declared in each test file
        # (imports, const/let/var/Python assignments, UPPER_CASE constants,
        # tuple-unpacking targets, function parameters) — these should not be
        # flagged as orphan calls.
        _PY_ASSIGN_TARGET = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_\s,]*)\s*=\s*[^=]")
        _JS_DECL = re.compile(r"\s*(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*(?::\s*[^=]+)?=")
        _IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
        # Python: def foo(param1, param2=..., *args, **kwargs) → parameter names
        _PY_DEF_PARAMS = re.compile(r"^\s*def\s+\w+\s*\(([^)]*)\)")
        # JS: function foo(a, b) {  /  const foo = (a, b) =>  /  (a, b) =>
        _JS_FUNC_PARAMS = re.compile(r"(?:function\s+\w+|(?:const|let|var)\s+\w+\s*=)\s*\(([^)]*)\)")
        local_vars_by_file: dict[str, set[str]] = {}
        for f in context.files:
            if f.relative_path not in test_file_paths:
                continue
            local_names: set[str] = set()
            for line in f.content.splitlines():
                # JS/TS: const/let/var declarations — both simple (const x = ...),
                # typed (const x: Type = ...), and destructuring
                # (const { a, b } = ... / const [a, b] = ...).
                m = _JS_DECL.match(line)
                if m:
                    local_names.add(m.group(1))
                # Destructuring: const { a, b } = / const [a, b] = / let {a}= /
                # for (const {a, b} of ...) / for (const [a, b] of ...). The
                # binding may be terminated by '=' (assignment) OR by 'of'/'in'
                # (for...of / for...in loops) — previously only '=' was accepted,
                # so for-of destructured bindings were missed and later flagged as
                # orphan calls.
                # Case A: assignment destructuring, optionally with a type
                # annotation (const { a, b }: Type = ...).
                m_destr = re.search(
                    r"(?:const|let|var)\s*([{\[][^\]}]*[\]}])\s*(?::\s*[^=]+)?=",
                    line,
                )
                if m_destr:
                    for ident in _IDENT.findall(m_destr.group(1)):
                        local_names.add(ident)
                # Case B: for...of / for...in destructuring — the binding is
                # followed by 'of' or 'in', not '='.
                #   for (const { scenario, query } of allCases) { ... }
                #   for (const [key, value] of Object.entries(x)) { ... }
                m_for_destr = re.search(
                    r"\bfor\s*\(\s*(?:const|let|var)\s+([{\[][^\]}]*[\]}])\s+(?:of|in)\b",
                    line,
                )
                if m_for_destr:
                    for ident in _IDENT.findall(m_for_destr.group(1)):
                        local_names.add(ident)
                # Python: assignment targets — captures single targets (x = ...),
                # UPPER_CASE module constants (MOCK_ID = ...), AND tuple-unpacking
                # targets (CENTER_LAT, CENTER_LON = ...). Each comma-separated
                # identifier in the target list is added.
                m2 = _PY_ASSIGN_TARGET.match(line)
                if m2:
                    for ident in _IDENT.findall(m2.group(1)):
                        local_names.add(ident)
                # Python: for-loop targets — `for w300 in ...` / `for k, v in ...`
                m_loop = re.match(r"\s*for\s+([A-Za-z_][A-Za-z0-9_\s,]*)\s+in\b", line)
                if m_loop:
                    for ident in _IDENT.findall(m_loop.group(1)):
                        local_names.add(ident)
                # Python: import aliases — `import foo as bar` or
                # `from x import foo as bar`. The alias `bar` is the name used
                # at call sites, so treat it as a local symbol.
                for alias in re.findall(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)", line):
                    local_names.add(alias)
                # Python: function/method parameters
                m3 = _PY_DEF_PARAMS.match(line)
                if m3:
                    for param in m3.group(1).split(","):
                        param = param.strip().lstrip("*")
                        # strip default value and type annotation
                        param = param.split("=")[0].split(":")[0].strip()
                        if param and _IDENT.fullmatch(param):
                            local_names.add(param)
                # JS: function/arrow parameters
                m4 = _JS_FUNC_PARAMS.search(line)
                if m4:
                    for param in m4.group(1).split(","):
                        param = param.strip().lstrip(".").lstrip("*").strip("{}")
                        param = param.split("=")[0].split(":")[0].strip()
                        if param and _IDENT.fullmatch(param):
                            local_names.add(param)
            # Whole-file safety net: multi-line declarations where the type
            # annotation or value spans lines defeat the per-line regexes above
            # (e.g. `const byScenario: Record<\n  string, Stats\n> = {...}`). A
            # bare `const|let|var <name>` anywhere in the file is a local binding
            # regardless of where the `=` lands, so capture the name from the
            # declaration head without requiring `=` on the same line.
            for m in re.finditer(
                r"\b(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\b",
                f.content,
            ):
                local_names.add(m.group(1))
            # Also collect names imported into this test file (from the symbol
            # graph's import refs) — e.g. `from fastapi import HTTPException`,
            # `from sqlalchemy import create_engine`. A bare call to an imported
            # name is not an orphan.
            for ref_list in context.symbol_graph.references.values():
                for ref in ref_list:
                    if ref.file_path == f.relative_path and ref.kind == "import":
                        local_names.add(ref.name)
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
                # Only consider bare function calls (foo()), NOT method/attribute
                # calls (obj.foo()). Attribute refs now have kind="attribute" from
                # the parser, so library methods like datetime.utcnow(),
                # session.commit(), JSON.parse() are excluded automatically.
                if ref.kind != "call":
                    continue
                # Skip common test helpers, assertions, fixtures
                if called_name in _SKIP_CALLS:
                    continue
                # Skip standard-library module/constructor names called bare
                # (e.g. `Path(...)`, `datetime(...)`, `MagicMock()`)
                if called_name in _STDLIB_MODULES:
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
