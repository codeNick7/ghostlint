"""Naming Consistency detector — near-duplicate model/DTO/schema names."""
from __future__ import annotations
import re
from ghostlint_engine.detectors.base import BaseDetector
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.ast_engine.base import SymbolDef
from ghostlint_engine.models.findings import (
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

# Complementary suffix pairs that intentionally share a stem (e.g. a
# ChatRequest / ChatResponse pair, or a CreateX / UpdateX CRUD pair). These are
# NOT naming problems, so near-duplicate pairs whose ONLY difference is a
# complementary-suffix pair should be skipped.
_COMPLEMENTARY_SUFFIX_PAIRS = frozenset({
    frozenset({"Request", "Response"}),
    frozenset({"Input", "Output"}),
    frozenset({"Req", "Resp"}),
    frozenset({"Create", "Update"}),
    frozenset({"Create", "Delete"}),
    frozenset({"Update", "Delete"}),
})

_SUFFIX_OF_RE = re.compile(r"([A-Z][a-z]+)$")


def _is_complementary_pair(a: str, b: str) -> bool:
    """Return True if two class names differ ONLY in a complementary suffix.

    E.g. ChatRequest/ChatResponse (stems equal, suffixes are a complementary
    pair), or CreateObservationRequest/CreateSubscriptionRequest are NOT
    complementary (stems differ). This lets us keep genuine near-duplicates
    while suppressing the Request/Response & Create/Update convention.
    """
    sa = _SUFFIX_RE.search(a)
    sb = _SUFFIX_RE.search(b)
    if not sa or not sb:
        return False
    suffix_a, suffix_b = sa.group(1), sb.group(1)
    if suffix_a == suffix_b:
        return False  # same suffix — handled by the real near-dup logic
    if frozenset({suffix_a, suffix_b}) not in _COMPLEMENTARY_SUFFIX_PAIRS:
        return False
    # Confirm the stems (everything before the suffix) are equal, so we only
    # skip true pairs like ChatRequest/ChatResponse, not CreateX/CreateY.
    stem_a = a[: -len(suffix_a)]
    stem_b = b[: -len(suffix_b)]
    return _strip_suffix(stem_a) == _strip_suffix(stem_b)


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
                # Skip complementary suffix pairs (Request/Response, Create/Update,
                # Input/Output) — they intentionally share a stem and are not a
                # naming problem. Only skip when the two names differ ONLY in the
                # complementary suffix (stems are otherwise equal).
                if _is_complementary_pair(sym_a.name, sym_b.name):
                    continue
                # Skip pairs sharing the same DTO suffix (e.g. two *Request
                # classes, two *Response classes) — same-suffix naming is a
                # convention, not a naming collision. Only flag when the stems
                # are near-identical (a likely typo like UserAccout/UserAccount).
                sa = _SUFFIX_RE.search(sym_a.name)
                sb = _SUFFIX_RE.search(sym_b.name)
                if sa and sb and sa.group(1) == sb.group(1):
                    continue
                pair_key = frozenset([
                    f"{sym_a.file_path}:{sym_a.name}",
                    f"{sym_b.file_path}:{sym_b.name}",
                ])
                if pair_key in reported:
                    continue
                sim = _similarity(sym_a.name, sym_b.name)
                # High threshold: only flag near-identical names (likely typos),
                # not merely similar ones. 0.92 ≈ a 1-character difference in a
                # 12-char name.
                if sim >= 0.92:
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
