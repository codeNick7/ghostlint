"""Duplicate Logic detector — structurally similar functions via AST fingerprinting."""
from __future__ import annotations
import hashlib
from collections import defaultdict
from tiramasu_engine.detectors.base import BaseDetector
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.ast_engine.base import SymbolDef
from tiramasu_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)


def _python_fingerprint(content: str, sym: SymbolDef) -> str | None:
    """Extract a structural fingerprint from a Python function body."""
    try:
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        PY_LANGUAGE = Language(tspython.language())
        parser = Parser(PY_LANGUAGE)
        source = content.encode("utf-8")
        tree = parser.parse(source)

        # Find the function node at the right line
        def find_func(node, target_line):
            if node.type in ("function_definition", "decorated_definition"):
                if abs(node.start_point[0] + 1 - target_line) <= 2:
                    return node
            for child in node.children:
                result = find_func(child, target_line)
                if result:
                    return result
            return None

        func_node = find_func(tree.root_node, sym.line_start)
        if func_node is None:
            return None

        # Find the actual function_definition inside decorated_definition
        if func_node.type == "decorated_definition":
            for child in func_node.children:
                if child.type == "function_definition":
                    func_node = child
                    break

        # Get the body
        body = func_node.child_by_field_name("body")
        if body is None:
            return None

        # Walk body collecting node types (structural fingerprint)
        tokens = []
        def walk(node):
            # Skip identifiers and literals (variable names, string values)
            if node.type not in ("identifier", "string", "integer", "float",
                                  "comment", "string_content"):
                tokens.append(node.type)
            for child in node.children:
                walk(child)

        walk(body)
        if len(tokens) < 5:  # too short to be meaningful
            return None
        fp = hashlib.md5(" ".join(tokens).encode()).hexdigest()
        return fp
    except Exception:
        return None


def _js_fingerprint(content: str, sym: SymbolDef) -> str | None:
    """Extract a structural fingerprint from a JS/TS function body."""
    try:
        import tree_sitter_javascript as tsjs
        from tree_sitter import Language, Parser

        JS_LANGUAGE = Language(tsjs.language())
        parser = Parser(JS_LANGUAGE)
        source = content.encode("utf-8")
        tree = parser.parse(source)

        def find_func(node, target_line):
            if node.type in ("function_declaration", "arrow_function", "function",
                             "method_definition", "lexical_declaration"):
                if abs(node.start_point[0] + 1 - target_line) <= 2:
                    return node
            for child in node.children:
                result = find_func(child, target_line)
                if result:
                    return result
            return None

        func_node = find_func(tree.root_node, sym.line_start)
        if func_node is None:
            return None

        body = func_node.child_by_field_name("body")
        if body is None:
            return None

        tokens = []
        def walk(node):
            if node.type not in ("identifier", "string", "number",
                                  "comment", "string_fragment"):
                tokens.append(node.type)
            for child in node.children:
                walk(child)

        walk(body)
        if len(tokens) < 5:
            return None
        return hashlib.md5(" ".join(tokens).encode()).hexdigest()
    except Exception:
        return None


def _name_similarity(a: str, b: str) -> float:
    """Simple Levenshtein-based similarity on lowercased names."""
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    # Build DP matrix
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            if ca == cb:
                curr.append(prev[j - 1])
            else:
                curr.append(1 + min(prev[j], curr[j - 1], prev[j - 1]))
        prev = curr
    dist = prev[lb]
    return 1.0 - dist / max(la, lb)


class DuplicateLogicDetector(BaseDetector):
    category = DetectionCategory.DUPLICATE_LOGIC

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # Build file content lookup
        file_content: dict[str, str] = {f.relative_path: f.content for f in context.files}

        # Fingerprint every function/method
        fingerprints: dict[str, list[SymbolDef]] = defaultdict(list)

        for name, defs in context.symbol_graph.definitions.items():
            for sym in defs:
                if sym.kind not in ("function", "method", "arrow_function"):
                    continue
                # Skip very short names (getters, etc.)
                if len(name) <= 3:
                    continue
                content = file_content.get(sym.file_path)
                if content is None:
                    continue

                language = None
                for f in context.files:
                    if f.relative_path == sym.file_path:
                        language = f.language
                        break

                if language == "python":
                    fp = _python_fingerprint(content, sym)
                elif language in ("javascript", "typescript"):
                    fp = _js_fingerprint(content, sym)
                else:
                    fp = None

                if fp:
                    fingerprints[fp].append(sym)

        # Report groups with 2+ symbols from different files
        reported: set[frozenset] = set()
        for fp, group in fingerprints.items():
            if len(group) < 2:
                continue
            # Only flag cross-file duplicates
            files_in_group = {sym.file_path for sym in group}
            if len(files_in_group) < 2:
                continue

            # Build finding for each pair from different files
            for i, sym_a in enumerate(group):
                for sym_b in group[i + 1:]:
                    if sym_a.file_path == sym_b.file_path:
                        continue
                    pair_key = frozenset([
                        f"{sym_a.file_path}:{sym_a.line_start}",
                        f"{sym_b.file_path}:{sym_b.line_start}",
                    ])
                    if pair_key in reported:
                        continue
                    reported.add(pair_key)

                    name_sim = _name_similarity(sym_a.name, sym_b.name)
                    confidence = 0.85 if name_sim > 0.7 else 0.75

                    findings.append(Finding(
                        category=DetectionCategory.DUPLICATE_LOGIC,
                        title=f"Duplicate logic: `{sym_a.name}` and `{sym_b.name}`",
                        description=(
                            f"`{sym_a.name}` in `{sym_a.file_path}` and `{sym_b.name}` in "
                            f"`{sym_b.file_path}` have identical structural AST fingerprints. "
                            f"Consider extracting to a shared utility."
                        ),
                        evidence=[
                            Evidence(
                                file_path=sym_a.file_path,
                                line_start=sym_a.line_start,
                                line_end=sym_a.line_end,
                                snippet=f"def {sym_a.name}(...)",
                            ),
                            Evidence(
                                file_path=sym_b.file_path,
                                line_start=sym_b.line_start,
                                line_end=sym_b.line_end,
                                snippet=f"def {sym_b.name}(...)",
                            ),
                        ],
                        confidence=confidence,
                        risk=RiskLevel.LOW,
                        effort=EffortLevel.HOURS,
                        benefit="Reduces maintenance burden and chance of diverging bug fixes.",
                    ))

        return findings
