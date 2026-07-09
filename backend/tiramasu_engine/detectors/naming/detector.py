"""Naming Consistency detector — near-duplicate model/DTO/schema names."""
from __future__ import annotations
import re
from tiramasu_engine.detectors.base import BaseDetector
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.ast_engine.base import SymbolDef
from tiramasu_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# Suffixes that indicate model/DTO/schema classes
_SUFFIXES = (
    "Model", "DTO", "Dto", "Schema", "Request", "Response", "Type",
    "Data", "Entity", "Payload", "Form", "Input", "Output",
)

_SUFFIX_RE = re.compile(
    r"(Model|DTO|Dto|Schema|Request|Response|Type|Data|Entity|Payload|Form|Input|Output)$"
)


def _strip_suffix(name: str) -> str:
    """Remove known suffix and lowercase for comparison."""
    return _SUFFIX_RE.sub("", name).lower()


def _levenshtein(a: str, b: str) -> int:
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            if ca == cb:
                curr.append(prev[j - 1])
            else:
                curr.append(1 + min(prev[j], curr[j - 1], prev[j - 1]))
        prev = curr
    return prev[lb]


def _similarity(a: str, b: str) -> float:
    a_stripped = _strip_suffix(a)
    b_stripped = _strip_suffix(b)
    if not a_stripped or not b_stripped:
        return 0.0
    dist = _levenshtein(a_stripped, b_stripped)
    max_len = max(len(a_stripped), len(b_stripped))
    return 1.0 - dist / max_len


class NamingConsistencyDetector(BaseDetector):
    category = DetectionCategory.NAMING_CONSISTENCY

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # Collect all class definitions that look like models/DTOs/schemas
        model_classes: list[SymbolDef] = []
        for name, defs in context.symbol_graph.definitions.items():
            if not _SUFFIX_RE.search(name):
                continue
            for d in defs:
                if d.kind == "class":
                    model_classes.append(d)

        # 1. Flag exact same name defined in multiple files
        by_name: dict[str, list[SymbolDef]] = {}
        for sym in model_classes:
            by_name.setdefault(sym.name, []).append(sym)

        for name, defs in by_name.items():
            if len(defs) < 2:
                continue
            # Multiple definitions of the same class name
            files = [d.file_path for d in defs]
            findings.append(Finding(
                category=DetectionCategory.NAMING_CONSISTENCY,
                title=f"Duplicate class name: `{name}` defined in {len(defs)} files",
                description=(
                    f"`{name}` is defined in multiple files: {', '.join(f'`{f}`' for f in files)}. "
                    f"This can cause import confusion and hidden overwrites."
                ),
                evidence=[
                    Evidence(
                        file_path=d.file_path,
                        line_start=d.line_start,
                        line_end=d.line_end,
                        snippet=f"class {name}",
                    )
                    for d in defs
                ],
                confidence=0.9,
                risk=RiskLevel.MEDIUM,
                effort=EffortLevel.HOURS,
                benefit="Eliminates naming confusion and potential import shadowing.",
            ))

        # 2. Near-duplicate names across different files (similarity > 0.7)
        reported: set[frozenset] = set()
        for i, sym_a in enumerate(model_classes):
            for sym_b in model_classes[i + 1:]:
                if sym_a.file_path == sym_b.file_path:
                    continue
                if sym_a.name == sym_b.name:
                    continue  # already reported above
                pair_key = frozenset([
                    f"{sym_a.file_path}:{sym_a.name}",
                    f"{sym_b.file_path}:{sym_b.name}",
                ])
                if pair_key in reported:
                    continue
                sim = _similarity(sym_a.name, sym_b.name)
                if sim >= 0.7:
                    reported.add(pair_key)
                    findings.append(Finding(
                        category=DetectionCategory.NAMING_CONSISTENCY,
                        title=f"Near-duplicate names: `{sym_a.name}` vs `{sym_b.name}`",
                        description=(
                            f"`{sym_a.name}` in `{sym_a.file_path}` and `{sym_b.name}` in "
                            f"`{sym_b.file_path}` are {sim:.0%} similar. They may represent "
                            f"the same concept with redundant definitions."
                        ),
                        evidence=[
                            Evidence(
                                file_path=sym_a.file_path,
                                line_start=sym_a.line_start,
                                line_end=sym_a.line_end,
                                snippet=f"class {sym_a.name}",
                            ),
                            Evidence(
                                file_path=sym_b.file_path,
                                line_start=sym_b.line_start,
                                line_end=sym_b.line_end,
                                snippet=f"class {sym_b.name}",
                            ),
                        ],
                        confidence=0.7,
                        risk=RiskLevel.LOW,
                        effort=EffortLevel.HOURS,
                        benefit="Consolidating duplicate models reduces API surface and confusion.",
                    ))

        return findings
