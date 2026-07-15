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


def _extract_local_imports(content: str, rel_path: str, language: str) -> list[str]:
    """
    Extract relative/local import paths from a file.
    Returns list of relative file paths (best-effort, not resolved).
    """
    imports = []
    base_dir = str(PurePosixPath(rel_path).parent)

    if language == "python":
        # from .services import X → relative import
        for match in re.finditer(r"from\s+(\.[\w.]*)\s+import", content):
            rel_import = match.group(1)
            # Convert dotted relative import to path guess
            # e.g., ".services" → "services" under same package
            parts = rel_import.lstrip(".")
            dots = len(rel_import) - len(parts)
            # Navigate up 'dots' levels
            base = base_dir
            for _ in range(max(0, dots - 1)):
                base = str(PurePosixPath(base).parent)
            if parts:
                guessed = str(PurePosixPath(base) / parts.replace(".", "/"))
                imports.append(guessed)

    elif language in ("javascript", "typescript"):
        # import from './services/userService'
        for match in re.finditer(r"from\s+['\"](\./[^'\"]+|\.\.\/[^'\"]+)['\"]", content):
            path = match.group(1)
            imports.append(path)

    return imports


class ArchDriftDetector(BaseDetector):
    category = DetectionCategory.ARCHITECTURAL_DRIFT

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # Build import graph: file → set of imported files (by relative path guess)
        import_graph: dict[str, list[str]] = {}

        for file_info in context.files:
            imports = _extract_local_imports(
                file_info.content, file_info.relative_path, file_info.language
            )
            import_graph[file_info.relative_path] = imports

        # Layer violation detection
        reported_violations: set[tuple] = set()
        for file_path, imported_paths in import_graph.items():
            if _is_arch_exempt(file_path):
                continue
            src_layer = _classify_file(file_path)
            if src_layer is None:
                continue
            for imp_path in imported_paths:
                # Find matching file in context
                dst_layer = None
                for f in context.files:
                    # Fuzzy match: does the imported path roughly correspond to this file?
                    if (f.relative_path.replace("\\", "/").startswith(imp_path.replace("\\", "/")) or
                            imp_path.replace("\\", "/") in f.relative_path.replace("\\", "/")):
                        dst_layer = _classify_file(f.relative_path)
                        if dst_layer is not None:
                            break

                if dst_layer is None:
                    continue

                # Violation: lower layer (higher number) imported by higher layer is OK
                # Violation: higher layer (lower number) imported by lower layer
                # e.g., Data layer (3) importing from API layer (1) is BAD
                if dst_layer < src_layer:
                    violation_key = (file_path, imp_path, src_layer, dst_layer)
                    if violation_key in reported_violations:
                        continue
                    reported_violations.add(violation_key)
                    findings.append(Finding(
                        category=DetectionCategory.ARCHITECTURAL_DRIFT,
                        title=(
                            f"Layer violation: {_LAYER_NAMES[src_layer]} imports from "
                            f"{_LAYER_NAMES[dst_layer]}"
                        ),
                        description=(
                            f"`{file_path}` (classified as {_LAYER_NAMES[src_layer]}) "
                            f"imports from `{imp_path}` (classified as {_LAYER_NAMES[dst_layer]}). "
                            f"Lower layers should not depend on higher layers."
                        ),
                        evidence=[Evidence(
                            file_path=file_path,
                            line_start=1,
                            line_end=1,
                            snippet=f"import from {imp_path}",
                        )],
                        confidence=0.7,
                        risk=RiskLevel.HIGH,
                        effort=EffortLevel.HOURS,
                        benefit="Enforcing layer boundaries improves testability and maintainability.",
                    ))

        # Circular import detection using NetworkX
        try:
            import networkx as nx
            G = nx.DiGraph()
            for src, dsts in import_graph.items():
                for dst in dsts:
                    # Resolve dst to an actual file path
                    for f in context.files:
                        if dst in f.relative_path or f.relative_path.startswith(dst):
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
