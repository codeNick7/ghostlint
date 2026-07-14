"""Refactor detector — coexisting old/new implementations and abandoned migrations."""
from __future__ import annotations
import re
from tiramisu_engine.detectors.base import BaseDetector
from tiramisu_engine.graph.context import AnalysisContext
from tiramisu_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# File name patterns indicating legacy/old versions
_FILE_LEGACY_RE = re.compile(
    r"(_old|_v\d+|_new|_legacy|_deprecated|_backup|_copy|old_|legacy_|_bak|_orig|_temp)\.",
    re.IGNORECASE,
)

# Symbol-level version/legacy suffix patterns
_SYM_LEGACY_RE = re.compile(
    r"(V\d+|_v\d+|New$|Old$|Legacy$|Deprecated$|Backup$|_new$|_old$|_legacy$)",
    re.IGNORECASE,
)

# Verb synonyms that suggest duplicate implementations
_VERB_SYNONYMS: list[set[str]] = [
    {"get", "fetch", "retrieve", "load", "read"},
    {"create", "make", "build", "construct", "new"},
    {"delete", "remove", "drop", "erase", "destroy"},
    {"update", "modify", "edit", "patch", "change"},
    {"process", "handle", "execute", "run", "perform"},
    {"send", "dispatch", "emit", "publish", "push"},
    {"validate", "verify", "check", "ensure"},
]


def _extract_verb(name: str) -> str | None:
    """Extract the leading verb from a camelCase or snake_case function name."""
    # snake_case: get_user → "get"
    if "_" in name:
        return name.split("_")[0].lower()
    # camelCase: getUser → "get"
    match = re.match(r"^([a-z]+)[A-Z]", name)
    if match:
        return match.group(1).lower()
    return None


def _extract_noun(name: str) -> str:
    """Extract the 'noun' part of a function name (everything after the verb)."""
    if "_" in name:
        parts = name.split("_", 1)
        return parts[1].lower() if len(parts) > 1 else ""
    match = re.match(r"^[a-z]+([A-Z].*)", name)
    if match:
        return match.group(1).lower()
    return ""


# Extension → language family. Synonym-verb duplicate detection is only
# meaningful within the same language family: a Python route handler
# (get_profile) and a TypeScript client fetch (fetchProfile) share a noun stem
# but are not duplicate implementations — they live in different runtimes.
_PY_EXTS = {".py"}
_JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


def _language_family(file_path: str) -> str:
    """Return 'py', 'js', or '' (unknown) for a file path."""
    # Use the final extension (handles multi-dot stems like "foo.config.ts").
    dot = file_path.rfind(".")
    ext = file_path[dot:].lower() if dot != -1 else ""
    if ext in _PY_EXTS:
        return "py"
    if ext in _JS_EXTS:
        return "js"
    return ""


class RefactorDetector(BaseDetector):
    category = DetectionCategory.REFACTOR_COMPLETION

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # 1. File-level: find files whose names suggest old/legacy versions
        for file_info in context.files:
            if _FILE_LEGACY_RE.search(file_info.relative_path):
                findings.append(Finding(
                    category=DetectionCategory.REFACTOR_COMPLETION,
                    title=f"Legacy file: `{file_info.relative_path}`",
                    description=(
                        f"`{file_info.relative_path}` appears to be a legacy or backup copy "
                        f"(the name contains patterns like _old, _v1, _legacy, _backup). "
                        f"Verify if this file is still needed or should be removed."
                    ),
                    evidence=[Evidence(
                        file_path=file_info.relative_path,
                        line_start=1,
                        line_end=1,
                        snippet=f"File: {file_info.relative_path}",
                    )],
                    confidence=0.8,
                    risk=RiskLevel.LOW,
                    effort=EffortLevel.MINUTES,
                    benefit="Removing stale backup files reduces confusion and repository bloat.",
                ))

        # 2. Symbol-level: find SymbolDef pairs where one is a version/legacy variant of another
        all_defs = []
        for name, defs in context.symbol_graph.definitions.items():
            for d in defs:
                all_defs.append(d)

        # Group by "base name" (strip version/legacy SUFFIX only).
        # NOTE: do NOT strip leading underscores — they are privacy markers
        # (e.g. `_get_db`), not version indicators. Previously `.strip("_")`
        # turned `_get_db` → `get_db`, falsely pairing it with the real
        # `get_db` as a "coexisting old/new" pair.
        base_to_defs: dict[str, list] = {}
        for sym in all_defs:
            base = _SYM_LEGACY_RE.sub("", sym.name)
            if base and base != sym.name:
                base_to_defs.setdefault(base, []).append(sym)

        reported: set[frozenset] = set()
        for base, variants in base_to_defs.items():
            # Find the "original" definition with this base name
            originals = [
                d for d in context.symbol_graph.definitions.get(base, [])
            ]
            if not originals:
                continue
            for orig in originals:
                for variant in variants:
                    pair_key = frozenset([
                        f"{orig.file_path}:{orig.line_start}:{orig.name}",
                        f"{variant.file_path}:{variant.line_start}:{variant.name}",
                    ])
                    if pair_key in reported:
                        continue
                    reported.add(pair_key)
                    findings.append(Finding(
                        category=DetectionCategory.REFACTOR_COMPLETION,
                        title=f"Coexisting old/new: `{orig.name}` and `{variant.name}`",
                        description=(
                            f"`{orig.name}` and `{variant.name}` appear to be coexisting "
                            f"versions of the same symbol. One may be a leftover from an "
                            f"incomplete refactor. Consider consolidating or removing the old version."
                        ),
                        evidence=[
                            Evidence(
                                file_path=orig.file_path,
                                line_start=orig.line_start,
                                line_end=orig.line_end,
                                snippet=f"{orig.kind}: {orig.name}",
                            ),
                            Evidence(
                                file_path=variant.file_path,
                                line_start=variant.line_start,
                                line_end=variant.line_end,
                                snippet=f"{variant.kind}: {variant.name}",
                            ),
                        ],
                        confidence=0.65,
                        risk=RiskLevel.MEDIUM,
                        effort=EffortLevel.HOURS,
                        benefit="Completing the refactor reduces maintenance complexity.",
                    ))

        # 3. Synonym-verb detection: get_user + fetch_user in related files
        # Group by noun part
        noun_to_defs: dict[str, list] = {}
        for sym in all_defs:
            if sym.kind not in ("function", "method"):
                continue
            verb = _extract_verb(sym.name)
            noun = _extract_noun(sym.name)
            if not verb or not noun or len(noun) < 3:
                continue
            noun_to_defs.setdefault(noun, []).append((verb, sym))

        for noun, verb_defs in noun_to_defs.items():
            if len(verb_defs) < 2:
                continue
            # Check if any two verbs are synonyms
            for i, (verb_a, sym_a) in enumerate(verb_defs):
                for verb_b, sym_b in verb_defs[i + 1:]:
                    if verb_a == verb_b:
                        continue
                    # Check synonym relationship
                    are_synonyms = any(
                        verb_a in group and verb_b in group
                        for group in _VERB_SYNONYMS
                    )
                    if not are_synonyms:
                        continue
                    # Skip same-file pairs: two differently-named helpers in
                    # the same file are normal (e.g. get_config + fetch_config
                    # for local vs remote), not an incomplete refactor.
                    if sym_a.file_path == sym_b.file_path:
                        continue
                    # Skip cross-language pairs (e.g. a Python route handler
                    # `get_profile` vs a TypeScript client fetch `fetchProfile`).
                    # They share a noun stem but live in different runtimes and
                    # are not duplicate implementations.
                    lang_a = _language_family(sym_a.file_path)
                    lang_b = _language_family(sym_b.file_path)
                    if lang_a and lang_b and lang_a != lang_b:
                        continue
                    pair_key = frozenset([
                        f"{sym_a.file_path}:{sym_a.line_start}:{sym_a.name}",
                        f"{sym_b.file_path}:{sym_b.line_start}:{sym_b.name}",
                    ])
                    if pair_key in reported:
                        continue
                    reported.add(pair_key)
                    findings.append(Finding(
                        category=DetectionCategory.REFACTOR_COMPLETION,
                        title=f"Possible duplicates: `{sym_a.name}` and `{sym_b.name}`",
                        description=(
                            f"`{sym_a.name}` and `{sym_b.name}` use synonym verbs "
                            f"({verb_a!r} / {verb_b!r}) on the same noun `{noun}`. "
                            f"They may be duplicate implementations from an incomplete refactor."
                        ),
                        evidence=[
                            Evidence(
                                file_path=sym_a.file_path,
                                line_start=sym_a.line_start,
                                line_end=sym_a.line_end,
                                snippet=f"{sym_a.kind}: {sym_a.name}",
                            ),
                            Evidence(
                                file_path=sym_b.file_path,
                                line_start=sym_b.line_start,
                                line_end=sym_b.line_end,
                                snippet=f"{sym_b.kind}: {sym_b.name}",
                            ),
                        ],
                        confidence=0.65,
                        risk=RiskLevel.LOW,
                        effort=EffortLevel.HOURS,
                        benefit="Consolidating to one canonical implementation reduces confusion.",
                    ))

        return findings
