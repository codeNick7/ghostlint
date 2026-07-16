from __future__ import annotations
from ghostlint_engine.models.findings import DetectionCategory, Finding, HealthScore

# Weight of each category in the overall score (must sum to 1.0)
_WEIGHTS = {
    DetectionCategory.DEAD_CODE: 0.20,
    DetectionCategory.DUPLICATE_LOGIC: 0.20,
    DetectionCategory.REFACTOR_COMPLETION: 0.15,
    DetectionCategory.ARCHITECTURAL_DRIFT: 0.15,
    DetectionCategory.DEPENDENCY_HEALTH: 0.10,
    DetectionCategory.DOC_HEALTH: 0.08,
    DetectionCategory.TEST_HEALTH: 0.07,
    DetectionCategory.CONFIG_HEALTH: 0.03,
    DetectionCategory.NAMING_CONSISTENCY: 0.02,
}

# Severity multipliers: how aggressively each affected-ratio penalises the score.
#
# Formula:  score = max(0, 100 - ratio × multiplier × 100)
#
# A multiplier of 7 means:
#   1% affected  → -7 pts  (score 93)
#   5% affected  → -35 pts (score 65)
#   15% affected → floor 0
#
# Symbol-based categories (dead_code, duplicate_logic) divide weighted finding
# count by total_symbols; file-based categories divide unique affected files by
# total_files. Both ratios are in [0, 1] before the multiplier is applied.
_MULTIPLIER = {
    DetectionCategory.DEAD_CODE:           7,   # 5% dead symbols → score 65
    DetectionCategory.DUPLICATE_LOGIC:     10,  # 5% duplicate symbols → score 50
    DetectionCategory.REFACTOR_COMPLETION: 10,  # file-based: 5% stale files → score 50
    DetectionCategory.ARCHITECTURAL_DRIFT: 20,  # file-based: 3% violating files → score 40
    DetectionCategory.DEPENDENCY_HEALTH:   8,   # file-based
    DetectionCategory.DOC_HEALTH:          5,   # file-based: docs decay slowly
    DetectionCategory.TEST_HEALTH:         8,   # file-based
    DetectionCategory.CONFIG_HEALTH:       8,   # file-based
    DetectionCategory.NAMING_CONSISTENCY:  5,   # file-based: style issues, low severity
}

_SYMBOL_BASED = {
    DetectionCategory.DEAD_CODE,
    DetectionCategory.DUPLICATE_LOGIC,
}


def compute_health_score(
    findings: list[Finding],
    total_symbols: int,
    total_files: int = 0,
) -> HealthScore:
    """Compute a size-normalised, severity-scaled health score.

    score = max(0, 100 - ratio × multiplier × 100)

    where ratio = weighted_affected / total (always in [0, 1]) and multiplier
    controls how steeply the score drops. This keeps scores meaningful across
    repos of any size: 5% of symbols dead in a 100-symbol repo and in a
    10 000-symbol repo both score the same (~65 for dead_code).
    """
    from collections import defaultdict
    by_category: dict[DetectionCategory, list[Finding]] = defaultdict(list)
    for f in findings:
        by_category[f.category].append(f)

    def _symbol_score(cat: DetectionCategory) -> float:
        cat_findings = by_category.get(cat, [])
        if not cat_findings or total_symbols == 0:
            return 100.0
        weighted = sum(f.confidence for f in cat_findings)
        ratio = min(weighted / total_symbols, 1.0)
        penalty = ratio * _MULTIPLIER[cat] * 100
        return round(max(0.0, 100.0 - penalty), 1)

    def _file_score(cat: DetectionCategory) -> float:
        cat_findings = by_category.get(cat, [])
        denom = total_files or 1
        if not cat_findings:
            return 100.0
        by_file: dict[str, float] = {}
        for f in cat_findings:
            fp = f.primary_file
            by_file[fp] = max(by_file.get(fp, 0.0), f.confidence)
        weighted = sum(by_file.values())
        ratio = min(weighted / denom, 1.0)
        penalty = ratio * _MULTIPLIER[cat] * 100
        return round(max(0.0, 100.0 - penalty), 1)

    def _score(cat: DetectionCategory) -> float:
        if cat in _SYMBOL_BASED:
            return _symbol_score(cat)
        return _file_score(cat)

    dead    = _score(DetectionCategory.DEAD_CODE)
    dup     = _score(DetectionCategory.DUPLICATE_LOGIC)
    refactor= _score(DetectionCategory.REFACTOR_COMPLETION)
    arch    = _score(DetectionCategory.ARCHITECTURAL_DRIFT)
    dep     = _score(DetectionCategory.DEPENDENCY_HEALTH)
    doc     = _score(DetectionCategory.DOC_HEALTH)
    test    = _score(DetectionCategory.TEST_HEALTH)
    config  = _score(DetectionCategory.CONFIG_HEALTH)
    naming  = _score(DetectionCategory.NAMING_CONSISTENCY)

    overall = round(
        dead     * _WEIGHTS[DetectionCategory.DEAD_CODE]
        + dup    * _WEIGHTS[DetectionCategory.DUPLICATE_LOGIC]
        + refactor * _WEIGHTS[DetectionCategory.REFACTOR_COMPLETION]
        + arch   * _WEIGHTS[DetectionCategory.ARCHITECTURAL_DRIFT]
        + dep    * _WEIGHTS[DetectionCategory.DEPENDENCY_HEALTH]
        + doc    * _WEIGHTS[DetectionCategory.DOC_HEALTH]
        + test   * _WEIGHTS[DetectionCategory.TEST_HEALTH]
        + config * _WEIGHTS[DetectionCategory.CONFIG_HEALTH]
        + naming * _WEIGHTS[DetectionCategory.NAMING_CONSISTENCY],
        1,
    )

    return HealthScore(
        overall=overall,
        dead_code=dead,
        duplicate_logic=dup,
        refactor_completion=refactor,
        architectural_drift=arch,
        dependency_health=dep,
        documentation_freshness=doc,
        test_health=test,
        config_consistency=config,
    )
