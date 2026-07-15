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

_PENALTY_PER_FINDING = {
    DetectionCategory.DEAD_CODE: 3.0,
    DetectionCategory.DUPLICATE_LOGIC: 5.0,
    DetectionCategory.REFACTOR_COMPLETION: 6.0,
    DetectionCategory.ARCHITECTURAL_DRIFT: 8.0,
    DetectionCategory.DEPENDENCY_HEALTH: 4.0,
    DetectionCategory.DOC_HEALTH: 2.0,
    DetectionCategory.TEST_HEALTH: 3.0,
    DetectionCategory.CONFIG_HEALTH: 4.0,
    DetectionCategory.NAMING_CONSISTENCY: 1.0,
}


def compute_health_score(findings: list[Finding], total_symbols: int) -> HealthScore:
    from collections import defaultdict
    by_category: dict[DetectionCategory, list[Finding]] = defaultdict(list)
    for f in findings:
        by_category[f.category].append(f)

    def _category_score(cat: DetectionCategory) -> float:
        cat_findings = by_category.get(cat, [])
        if not cat_findings:
            return 100.0
        penalty = sum(f.confidence * _PENALTY_PER_FINDING[cat] for f in cat_findings)
        return round(max(0.0, 100.0 - penalty), 1)

    dead = _category_score(DetectionCategory.DEAD_CODE)
    dup = _category_score(DetectionCategory.DUPLICATE_LOGIC)
    refactor = _category_score(DetectionCategory.REFACTOR_COMPLETION)
    arch = _category_score(DetectionCategory.ARCHITECTURAL_DRIFT)
    dep = _category_score(DetectionCategory.DEPENDENCY_HEALTH)
    doc = _category_score(DetectionCategory.DOC_HEALTH)
    test = _category_score(DetectionCategory.TEST_HEALTH)
    config = _category_score(DetectionCategory.CONFIG_HEALTH)
    naming = _category_score(DetectionCategory.NAMING_CONSISTENCY)

    overall = round(
        dead * _WEIGHTS[DetectionCategory.DEAD_CODE]
        + dup * _WEIGHTS[DetectionCategory.DUPLICATE_LOGIC]
        + refactor * _WEIGHTS[DetectionCategory.REFACTOR_COMPLETION]
        + arch * _WEIGHTS[DetectionCategory.ARCHITECTURAL_DRIFT]
        + dep * _WEIGHTS[DetectionCategory.DEPENDENCY_HEALTH]
        + doc * _WEIGHTS[DetectionCategory.DOC_HEALTH]
        + test * _WEIGHTS[DetectionCategory.TEST_HEALTH]
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
