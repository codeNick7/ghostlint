"""Duplicate Logic detector — structurally similar functions via AST fingerprinting."""
from __future__ import annotations
import hashlib
from collections import defaultdict
from ghostlint_engine.detectors.base import BaseDetector
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.ast_engine.base import SymbolDef
from ghostlint_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# Framework/lifecycle convention names that legitimately share structure across
# many files. Flagging them as duplicates is noise: they are idiomatic
# implementations of a well-known contract, not copy-pasted logic.
_CONVENTION_NAMES: frozenset[str] = frozenset({
    # Python dunder methods — every class implements these with a near-identical shape
    "__init__", "__repr__", "__str__", "__eq__", "__hash__", "__len__",
    "__enter__", "__exit__", "__iter__", "__next__", "__contains__",
    # React / Next.js data-fetching & metadata convention functions
    "generateStaticParams", "generateMetadata", "metadata", "viewport",
    "GET", "POST", "PUT", "PATCH", "DELETE",  # Next.js route handlers
    "loader", "action", "headers", "cookies",
    # Observable/Redux store subscribe — identical contract across stores
    "subscribe", "unsubscribe", "getState", "dispatch",
    # React component lifecycle (class components / hooks contracts)
    "componentDidMount", "componentWillUnmount", "render",
    # Alembic/SQLAlchemy migration interface — upgrade/downgrade are REQUIRED in every
    # migration file and are called by the Alembic CLI, not imported. Each migration
    # file must define both; they are identical in structure but intentionally isolated.
    "upgrade", "downgrade",
})

# Path segments that identify database migration version files. Functions in these
# files (especially per-migration helpers like _table_exists, _idx_exists) are
# isolation patterns, not copy-paste — each migration must be self-contained.
_MIGRATION_PATH_SEGMENTS: frozenset[str] = frozenset({
    "alembic/versions", "migrations/versions",
})


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
        # Require a minimum body size so trivial 1-2 line boilerplate (e.g.
        # `def _get_db(): return SessionLocal()`) isn't fingerprinted — such
        # tiny bodies match many unrelated functions purely on shape, producing
        # false-positive duplicate pairs. 10 tokens ≈ a real multi-statement body.
        if len(tokens) < 10:
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
        # Same minimum-size threshold as the Python fingerprinter: skip trivial
        # one-liners that match many unrelated functions on shape alone.
        if len(tokens) < 10:
            return None
        return hashlib.md5(" ".join(tokens).encode()).hexdigest()
    except Exception:
        return None


def _is_abstract_or_override(sym: SymbolDef) -> bool:
    """Heuristic: is this symbol an abstract method or a subclass override?

    Abstract methods (on ABCs/protocols) and their overrides have many sibling
    implementations with similar AST shapes but genuinely different logic.
    Fingerprinting them produces false-positive duplicate pairs (e.g. the
    `applies_to()` / `apply()` methods across ~25 rule subclasses).
    """
    # An @abstractmethod / @Override decorator is a strong signal.
    for deco in sym.decorators:
        d = deco.lstrip("@").lower().split(".")[-1]
        if d in ("abstractmethod", "override", "abstractproperty"):
            return True
    # A method on a class that declares an abstract base / protocol also counts.
    for base in sym.base_classes:
        b = base.lower().split(".")[-1]
        if b in ("abc", "abcmeta", "protocol", "abstractmethod", "interface"):
            return True
    return False


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


def _detect_mirror_roots(files) -> list[tuple[str, str]]:
    """Detect pairs of top-level directories that are near-identical mirrors.

    Repositories sometimes keep a renamed copy of a whole app alongside the
    original (e.g. ``web/`` and ``web-new/`` during a migration). Every file in
    one mirror has a structural twin in the other, so the duplicate detector
    would flag every component twice. This returns pairs of mirror root
    prefixes (e.g. ``[("web", "web-new")]``) by detecting top-level dirs that
    share a large fraction of identical relative sub-paths.
    """
    from collections import defaultdict
    # Group files by their first path segment (top-level dir).
    by_root: dict[str, set[str]] = defaultdict(set)
    for f in files:
        parts = f.relative_path.replace("\\", "/").split("/", 1)
        if len(parts) == 2:
            by_root[parts[0]].add(parts[1])
    roots = list(by_root.keys())
    mirrors: list[tuple[str, str]] = []
    for i, a in enumerate(roots):
        for b in roots[i + 1:]:
            sa, sb = by_root[a], by_root[b]
            if not sa or not sb:
                continue
            # Two roots are mirrors if their relative-path sets overlap heavily.
            overlap = len(sa & sb)
            smaller = min(len(sa), len(sb))
            # Require ≥60% path overlap AND at least 20 shared files — this is
            # specific enough to avoid matching unrelated dirs that share a few
            # common filenames (like package.json / index.ts).
            if smaller >= 20 and overlap >= 0.6 * smaller:
                mirrors.append((a, b))
    return mirrors


def _are_mirror_twins(path_a: str, path_b: str, mirror_roots: list[tuple[str, str]]) -> bool:
    """Return True if path_a and path_b are the same relative file under two
    mirror roots (e.g. web/components/Foo.tsx and web-new/components/Foo.tsx)."""
    na, nb = path_a.replace("\\", "/"), path_b.replace("\\", "/")
    for root_a, root_b in mirror_roots:
        for ra, rb in ((root_a, root_b), (root_b, root_a)):
            pa = ra + "/"
            pb = rb + "/"
            if na.startswith(pa) and nb.startswith(pb):
                if na[len(pa):] == nb[len(pb):]:
                    return True
    return False


class DuplicateLogicDetector(BaseDetector):
    category = DetectionCategory.DUPLICATE_LOGIC

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # Build file content lookup
        file_content: dict[str, str] = {f.relative_path: f.content for f in context.files}

        # Detect "mirror" top-level directories — sibling roots whose file trees
        # are near-identical copies of the same app (e.g. web/ and web-new/).
        # Cross-mirror file pairs are structural twins, not actionable duplicates:
        # every component appears once per mirror, so flagging each pair floods the
        # report. We suppress cross-mirror duplicate pairs below.
        mirror_roots = _detect_mirror_roots(context.files)

        # Precompute the set of method names declared @abstractmethod anywhere
        # in the codebase. Any method sharing such a name is an override of an
        # abstract interface — its siblings have similar shapes but genuinely
        # different logic, so they must not be fingerprinted as duplicates.
        abstract_method_names: set[str] = set()
        for name, defs in context.symbol_graph.definitions.items():
            for d in defs:
                for deco in d.decorators:
                    # Decorators are stored with the leading '@' (e.g.
                    # '@abstractmethod', '@abc.abstractmethod'). Strip it and
                    # take the final segment to normalize the name.
                    norm = deco.lstrip("@").lower().split(".")[-1]
                    if norm in ("abstractmethod", "abstractproperty"):
                        abstract_method_names.add(name)
                        break

        # Fingerprint every function/method
        fingerprints: dict[str, list[SymbolDef]] = defaultdict(list)

        for name, defs in context.symbol_graph.definitions.items():
            for sym in defs:
                if sym.kind not in ("function", "method", "arrow_function"):
                    continue
                # Skip very short names (getters, etc.)
                if len(name) <= 3:
                    continue
                # Skip abstract methods and their overrides (interface/protocol
                # implementations) — see abstract_method_names above.
                if name in abstract_method_names:
                    continue
                if _is_abstract_or_override(sym):
                    continue
                # Skip common framework/lifecycle conventions that legitimately
                # share structure across files (React/Next.js data-fetching
                # functions, Python dunder methods, observable subscribe calls).
                # Flagging these produces noise, not signal.
                if name in _CONVENTION_NAMES:
                    continue
                # Skip symbols in migration version files — per-migration helper
                # functions (e.g. _table_exists, _idx_exists) are isolation
                # patterns, not copy-paste logic. Each migration file must be
                # self-contained and forward/backward compatible independently.
                norm_path = sym.file_path.replace("\\", "/")
                if any(seg in norm_path for seg in _MIGRATION_PATH_SEGMENTS):
                    continue
                # Skip shadcn/ui component library files. shadcn installs Radix-UI
                # primitive wrappers as local source files under components/ui/. These
                # deliberately share the same forwardRef+cn() wrapper pattern — it is
                # the design system contract, not copy-pasted logic.
                if "components/ui/" in norm_path:
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

        # Report groups with 2+ symbols from different files.
        # Strategy:
        #   Same-name group (e.g. _get_db in 10 route files) → ONE grouped finding
        #     listing all N files. Pairwise reporting generates N*(N-1)/2 findings
        #     for a single actionable issue, flooding the report.
        #   Different-name pair (structural match across different function names) →
        #     one finding per pair, with name-similarity filtering to avoid
        #     unrelated-function cross-matches.
        reported_groups: set[str] = set()   # grouped: "<name>:<fp>"
        reported_pairs: set[frozenset] = set()  # pairs: frozenset of "path:line"

        # Build a language lookup once to avoid repeated linear scans.
        file_language: dict[str, str] = {f.relative_path: f.language for f in context.files}

        for fp, group in fingerprints.items():
            if len(group) < 2:
                continue
            files_in_group = {sym.file_path for sym in group}
            if len(files_in_group) < 2:
                continue

            # --- Split group into same-name buckets and cross-name pairs ---
            # Normalize names by stripping leading underscores before bucketing.
            # This merges private and public variants of the same function
            # (e.g. `_get_db` and `get_db`) into one group, avoiding N×M
            # cross-pair findings for what is a single "extract this function"
            # recommendation. The original names are preserved on the SymbolDef.
            by_name: dict[str, list[SymbolDef]] = defaultdict(list)
            for sym in group:
                by_name[sym.name.lstrip("_")].append(sym)

            # 1. Same-name groups → single grouped finding
            for name, syms in by_name.items():
                group_key = f"{name}:{fp}"
                if group_key in reported_groups:
                    continue

                # Collect one representative sym per file (avoid intra-file dups)
                seen_files: dict[str, SymbolDef] = {}
                for sym in syms:
                    if sym.file_path not in seen_files:
                        seen_files[sym.file_path] = sym

                if len(seen_files) < 2:
                    continue

                # Check that at least one non-mirror pair exists
                sym_list = list(seen_files.values())
                has_non_mirror = any(
                    not _are_mirror_twins(sym_list[i].file_path, sym_list[j].file_path, mirror_roots)
                    for i in range(len(sym_list))
                    for j in range(i + 1, len(sym_list))
                )
                if not has_non_mirror:
                    continue

                # Name similarity filter for JS/TS and Python applies per-pair;
                # for same-name groups name_sim is always 1.0, so always passes.
                reported_groups.add(group_key)

                n = len(seen_files)
                # Cap evidence to 5 entries to avoid overwhelming the output
                evidence_syms = sym_list[:5]
                lang = file_language.get(sym_list[0].file_path)
                snippet_prefix = "def" if lang == "python" else "function"
                # Collect the distinct original names (e.g. _get_db + get_db)
                actual_names = sorted({s.name for s in sym_list})
                display_name = (
                    " / ".join(f"`{n_}`" for n_ in actual_names[:3])
                    + (" ..." if len(actual_names) > 3 else "")
                )
                title = (
                    f"Duplicate logic: {display_name} defined identically in {n} files"
                    if n > 2
                    else f"Duplicate logic: {display_name} duplicated across files"
                )
                description = (
                    f"{display_name} {'have' if len(actual_names) > 1 else 'has'} "
                    f"an identical structural AST fingerprint in {n} files. "
                    f"Consider extracting to a shared module to avoid diverging bug fixes. "
                    f"Files: {', '.join(f'`{s.file_path}`' for s in sym_list[:5])}"
                    + (" ..." if n > 5 else "")
                )
                findings.append(Finding(
                    category=DetectionCategory.DUPLICATE_LOGIC,
                    title=title,
                    description=description,
                    evidence=[
                        Evidence(
                            file_path=s.file_path,
                            line_start=s.line_start,
                            line_end=s.line_end,
                            snippet=f"{snippet_prefix} {name}(...)",
                        )
                        for s in evidence_syms
                    ],
                    confidence=0.85,
                    risk=RiskLevel.LOW,
                    effort=EffortLevel.HOURS,
                    benefit="Reduces maintenance burden and chance of diverging bug fixes.",
                ))

            # 2. Cross-name pairs (different function names, same structure)
            names = list(by_name.keys())
            for i, name_a in enumerate(names):
                for name_b in names[i + 1:]:
                    for sym_a in by_name[name_a]:
                        for sym_b in by_name[name_b]:
                            if sym_a.file_path == sym_b.file_path:
                                continue
                            if _are_mirror_twins(sym_a.file_path, sym_b.file_path, mirror_roots):
                                continue
                            pair_key = frozenset([
                                f"{sym_a.file_path}:{sym_a.line_start}",
                                f"{sym_b.file_path}:{sym_b.line_start}",
                            ])
                            if pair_key in reported_pairs:
                                continue

                            name_sim = _name_similarity(sym_a.name, sym_b.name)
                            lang_a = file_language.get(sym_a.file_path)
                            # JS/TS: require name similarity >= 0.6 to filter out
                            # unrelated components that share a wrapper shape.
                            if lang_a in ("javascript", "typescript") and name_sim < 0.6:
                                continue
                            # Python: require name similarity >= 0.5 to prevent
                            # semantically unrelated functions (e.g. setup_logger vs
                            # get_thread_record_by_session) from being reported.
                            if lang_a == "python" and name_sim < 0.5:
                                continue

                            reported_pairs.add(pair_key)
                            confidence = 0.85 if name_sim > 0.7 else 0.75
                            lang_snippet = "def" if lang_a == "python" else "function"
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
                                        snippet=f"{lang_snippet} {sym_a.name}(...)",
                                    ),
                                    Evidence(
                                        file_path=sym_b.file_path,
                                        line_start=sym_b.line_start,
                                        line_end=sym_b.line_end,
                                        snippet=f"{lang_snippet} {sym_b.name}(...)",
                                    ),
                                ],
                                confidence=confidence,
                                risk=RiskLevel.LOW,
                                effort=EffortLevel.HOURS,
                                benefit="Reduces maintenance burden and chance of diverging bug fixes.",
                            ))

        return findings
