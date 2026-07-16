"""Architectural Drift detector — layer boundary violations and circular imports."""
from __future__ import annotations
import re
from pathlib import PurePosixPath
from ghostlint_engine.detectors.base import BaseDetector
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# Layer classification by directory name patterns.
# Lower number = higher layer (closer to user); violations are detected when a
# lower-numbered layer imports from a lower-numbered destination (dst_layer < src_layer).
# Layer 5 (Foundation) is special: it sits BELOW everything, so any other layer
# importing from it is always legal. Only layer 5 code importing from layers 1-4
# would be flagged (e.g. core/settings importing from services is wrong).
_LAYER_MAP: dict[str, int] = {
    "routes": 1, "routers": 1, "api": 1, "views": 1, "controllers": 1,
    "handlers": 1, "endpoints": 1,
    "services": 2, "business": 2, "domain": 2, "use_cases": 2,
    "models": 3, "schemas": 3, "entities": 3, "db": 3, "repositories": 3,
    "dao": 3, "database": 3,
    "utils": 4, "helpers": 4, "lib": 4, "common": 4, "shared": 4,
    "tools": 4, "support": 4,
    # Foundation/Infrastructure — cross-cutting concerns (config, auth, logging)
    # that every other layer is legitimately allowed to import from.
    "core": 5, "config": 5, "settings": 5, "infrastructure": 5, "foundation": 5,
}

_LAYER_NAMES: dict[int, str] = {
    1: "API/Routes",
    2: "Services/Business",
    3: "Data/Models",
    4: "Utils/Helpers",
    5: "Foundation/Infrastructure",
}

# Path segments or filename prefixes that mark standalone scripts not part of
# the app's import graph. Seed scripts, one-off init scripts, and migration
# runners legitimately import from any layer (they bootstrap data using models,
# settings, and services together) and must not trigger layer violations.
_ARCH_EXEMPT_PATH_SEGMENTS: frozenset[str] = frozenset({
    "scripts", "seeds", "fixtures", "seed_data",
})
_ARCH_EXEMPT_STEM_PREFIXES: tuple[str, ...] = (
    "seed_", "migrate_", "run_", "init_db", "populate_", "bootstrap_",
)


def _is_arch_exempt(rel_path: str) -> bool:
    """Return True for standalone scripts that intentionally cross layer boundaries."""
    norm = rel_path.replace("\\", "/")
    parts = PurePosixPath(norm).parts
    if any(p in _ARCH_EXEMPT_PATH_SEGMENTS for p in parts):
        return True
    stem = PurePosixPath(norm).stem.lower()
    return any(stem.startswith(pfx) for pfx in _ARCH_EXEMPT_STEM_PREFIXES)


def _classify_file(rel_path: str) -> int | None:
    """Return the layer number for a file, or None if unknown."""
    parts = PurePosixPath(rel_path).parts
    for part in parts[:-1]:  # skip filename
        layer = _LAYER_MAP.get(part.lower())
        if layer is not None:
            return layer
    return None


def _extract_local_imports(content: str, rel_path: str, language: str) -> list[tuple[str, int]]:
    """Extract import paths from a file along with their line numbers.

    Returns list of (guessed_path, line_number) tuples.
    Only surfaces paths that resolve to a known project layer segment so that
    the caller can do a precise prefix match rather than loose containment.
    """
    imports: list[tuple[str, int]] = []
    base_dir = str(PurePosixPath(rel_path).parent)
    lines = content.splitlines()

    if language == "python":
        for lineno, line in enumerate(lines, 1):
            # Relative imports: from .services import X
            m = re.match(r"\s*from\s+(\.[\w.]*)\s+import", line)
            if m:
                rel_import = m.group(1)
                parts = rel_import.lstrip(".")
                dots = len(rel_import) - len(parts)
                base = base_dir
                for _ in range(max(0, dots - 1)):
                    base = str(PurePosixPath(base).parent)
                if parts:
                    guessed = str(PurePosixPath(base) / parts.replace(".", "/"))
                    imports.append((guessed, lineno))
                continue

            # Absolute imports rooted at a known layer segment:
            # from services.auth_service import X  OR  from app.services.auth import X
            m = re.match(r"\s*from\s+([\w][\w.]*)\s+import", line)
            if m:
                mod = m.group(1)
                parts = mod.split(".")
                # Walk from the leftmost segment to find a layer keyword
                for i, part in enumerate(parts):
                    if part.lower() in _LAYER_MAP:
                        # Reconstruct path from this layer segment onward
                        guessed = "/".join(parts[i:]).replace(".", "/")
                        imports.append((guessed, lineno))
                        break

    elif language in ("javascript", "typescript"):
        for lineno, line in enumerate(lines, 1):
            m = re.search(r"""from\s+['"](\./[^'"]+|\.\./[^'"]+)['"]""", line)
            if m:
                imports.append((m.group(1), lineno))

    return imports


class ArchDriftDetector(BaseDetector):
    category = DetectionCategory.ARCHITECTURAL_DRIFT

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # Build import graph: file → list of (guessed_path, line_number) pairs
        import_graph: dict[str, list[tuple[str, int]]] = {}

        for file_info in context.files:
            import_graph[file_info.relative_path] = _extract_local_imports(
                file_info.content, file_info.relative_path, file_info.language
            )

        # Pre-index relative paths for O(1) prefix lookup
        all_rel_paths = [f.relative_path.replace("\\", "/") for f in context.files]

        # Layer violation detection
        reported_violations: set[tuple] = set()
        for file_path, imported_pairs in import_graph.items():
            if _is_arch_exempt(file_path):
                continue
            src_layer = _classify_file(file_path)
            if src_layer is None:
                continue
            for imp_path, lineno in imported_pairs:
                norm_imp = imp_path.replace("\\", "/")
                # Precise match: the guessed path must be a prefix of an actual file's
                # relative path (forward direction only — never containment in reverse).
                dst_layer = None
                matched_file = None
                for rel in all_rel_paths:
                    if rel.startswith(norm_imp):
                        candidate_layer = _classify_file(rel)
                        if candidate_layer is not None:
                            dst_layer = candidate_layer
                            matched_file = rel
                            break

                if dst_layer is None:
                    continue

                if dst_layer < src_layer:
                    violation_key = (file_path, norm_imp, src_layer, dst_layer)
                    if violation_key in reported_violations:
                        continue
                    reported_violations.add(violation_key)

                    # Get the actual import line for the snippet
                    src_content = next(
                        (fi.content for fi in context.files if fi.relative_path == file_path), ""
                    )
                    src_lines = src_content.splitlines()
                    snippet = src_lines[lineno - 1].strip() if lineno <= len(src_lines) else f"import from {imp_path}"

                    findings.append(Finding(
                        category=DetectionCategory.ARCHITECTURAL_DRIFT,
                        title=(
                            f"Layer violation: {_LAYER_NAMES[src_layer]} → "
                            f"{_LAYER_NAMES[dst_layer]}"
                        ),
                        description=(
                            f"`{file_path}` ({_LAYER_NAMES[src_layer]}) imports from "
                            f"`{matched_file or imp_path}` ({_LAYER_NAMES[dst_layer]}). "
                            f"Lower layers must not depend on higher layers."
                        ),
                        evidence=[Evidence(
                            file_path=file_path,
                            line_start=lineno,
                            line_end=lineno,
                            snippet=snippet,
                        )],
                        confidence=0.75,
                        risk=RiskLevel.HIGH,
                        effort=EffortLevel.HOURS,
                        benefit="Enforcing layer boundaries improves testability and maintainability.",
                    ))

        # Circular import detection using NetworkX
        try:
            import networkx as nx
            G = nx.DiGraph()
            for src, pairs in import_graph.items():
                for dst, _ln in pairs:
                    norm_dst = dst.replace("\\", "/")
                    for f in context.files:
                        if f.relative_path.replace("\\", "/").startswith(norm_dst):
                            G.add_edge(src, f.relative_path)
                            break

            cycles = list(nx.simple_cycles(G))
            reported_cycles: set[frozenset] = set()
            for cycle in cycles:
                if len(cycle) < 2:
                    continue
                cycle_key = frozenset(cycle)
                if cycle_key in reported_cycles:
                    continue
                reported_cycles.add(cycle_key)
                cycle_str = " → ".join(cycle[:5])
                if len(cycle) > 5:
                    cycle_str += f" → ... ({len(cycle)} files)"
                findings.append(Finding(
                    category=DetectionCategory.ARCHITECTURAL_DRIFT,
                    title=f"Circular import detected ({len(cycle)} files)",
                    description=(
                        f"A circular import chain was detected: {cycle_str}. "
                        f"Circular imports cause import errors, make testing harder, "
                        f"and indicate architectural coupling."
                    ),
                    evidence=[Evidence(
                        file_path=cycle[0],
                        line_start=1,
                        line_end=1,
                        snippet=cycle_str,
                    )],
                    confidence=0.9,
                    risk=RiskLevel.HIGH,
                    effort=EffortLevel.HOURS,
                    benefit="Eliminating circular imports improves module isolation.",
                ))
        except Exception:
            pass

        return findings
