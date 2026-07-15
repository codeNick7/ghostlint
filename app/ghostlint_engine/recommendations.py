from __future__ import annotations
from ghostlint_engine.models.findings import Finding, Recommendation, RiskLevel


def generate_recommendations(findings: list[Finding]) -> list[Recommendation]:
    recs: list[Recommendation] = []

    for f in findings:
        title = _recommendation_title(f)
        recs.append(Recommendation(
            title=title,
            description=f.description,
            finding_id=f.id,
            files=list({e.file_path for e in f.evidence}),
            confidence=f.confidence,
            risk=f.risk,
            effort=f.effort,
            benefit=f.benefit,
        ))

    # Sort: high confidence + low risk first
    recs.sort(key=lambda r: (-r.confidence, r.risk.value))
    return recs


def _recommendation_title(f: Finding) -> str:
    from ghostlint_engine.models.findings import DetectionCategory
    if f.category == DetectionCategory.DEAD_CODE:
        return f"Remove {f.title.replace('Unused ', '').strip()}"
    return f.title
