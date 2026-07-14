"""Convert ScanResult / GitMetrics into AI-friendly prose and structured dicts."""
from __future__ import annotations
from tiramisu_engine.models.findings import ScanResult, RiskLevel, GitMetrics


def findings_to_dicts(result: ScanResult, max_findings: int = 10) -> list[dict]:
    out = []
    for f in result.findings[:max_findings]:
        out.append({
            "id": f.id,
            "category": f.category.value,
            "title": f.title,
            "description": f.description,
            "file": f.primary_file,
            "line": f.primary_line,
            "confidence": round(f.confidence, 2),
            "risk": f.risk.value,
            "effort": f.effort.value,
            "benefit": f.benefit,
        })
    return out


def recommendations_to_dicts(result: ScanResult, max_recs: int = 5) -> list[dict]:
    out = []
    for r in result.recommendations[:max_recs]:
        out.append({
            "title": r.title,
            "description": r.description,
            "files": r.files,
            "confidence": round(r.confidence, 2),
            "risk": r.risk.value,
            "effort": r.effort.value,
            "benefit": r.benefit,
        })
    return out


def git_metrics_to_dict(gm: GitMetrics) -> dict:
    return {
        "available": gm.available,
        "stability_index": gm.stability_index,
        "maintenance_velocity": round(gm.maintenance_velocity, 3),
        "refactor_completion_rate": gm.refactor_completion_rate,
        "friction_index": gm.friction_index,
        "total_commits_analyzed": gm.total_commits_analyzed,
        "repo_age_days": gm.repo_age_days,
        "top_contributors": gm.top_contributors,
    }


def findings_summary_dict(result: ScanResult) -> dict:
    from collections import Counter
    by_cat: Counter = Counter(f.category.value for f in result.findings)
    by_risk: Counter = Counter(f.risk.value for f in result.findings)
    return {
        "total": len(result.findings),
        "high": by_risk.get("high", 0),
        "medium": by_risk.get("medium", 0),
        "low": by_risk.get("low", 0),
        "by_category": dict(by_cat),
    }


def build_health_context_prose(result: ScanResult) -> str:
    """One-paragraph prose summary ready to be dropped into an AI system prompt."""
    hs = result.health_score
    score_label = (
        "healthy" if hs.overall >= 90
        else "needs review" if hs.overall >= 70
        else "has significant issues" if hs.overall >= 50
        else "is in critical condition"
    )

    findings = result.findings
    highs = [f for f in findings if f.risk == RiskLevel.HIGH]
    meds = [f for f in findings if f.risk == RiskLevel.MEDIUM]

    lines = [
        f"Repository health score: {hs.overall:.1f}/100 — {score_label}. "
        f"Scanned {result.files_scanned} files, {result.symbols_found} symbols, "
        f"found {len(findings)} issue(s)."
    ]

    if highs:
        titles = "; ".join(f.title for f in highs[:3])
        lines.append(f"HIGH risk findings ({len(highs)}): {titles}{'…' if len(highs) > 3 else ''}.")
    if meds:
        titles = "; ".join(f.title for f in meds[:3])
        lines.append(f"MEDIUM risk findings ({len(meds)}): {titles}{'…' if len(meds) > 3 else ''}.")

    weak = [name for name, score in [
        ("dead_code", hs.dead_code), ("duplicate_logic", hs.duplicate_logic),
        ("refactor", hs.refactor_completion), ("arch_drift", hs.architectural_drift),
        ("deps", hs.dependency_health), ("tests", hs.test_health),
    ] if score < 70]
    if weak:
        lines.append(f"Weakest categories: {', '.join(weak)}.")

    gm = result.git_metrics
    if gm.available:
        git_parts = []
        if gm.stability_index < 50:
            git_parts.append(f"low stability index ({gm.stability_index:.0f}/100 — core files churning)")
        if gm.friction_index > 60:
            git_parts.append(f"high friction ({gm.friction_index:.0f}/100)")
        if gm.maintenance_velocity < 0.1:
            git_parts.append("very low maintenance velocity")
        if git_parts:
            lines.append("Git signals: " + "; ".join(git_parts) + ".")

    if result.recommendations:
        top = result.recommendations[0]
        lines.append(f"Top recommendation: {top.title} ({top.effort.value} effort).")

    return " ".join(lines)


def build_file_context_prose(findings: list, files: list[str]) -> str:
    """Prose summary scoped to specific files."""
    if not findings:
        return f"No issues found in {', '.join(files)}. Safe to edit."

    highs = [f for f in findings if f.risk == RiskLevel.HIGH]
    intro = f"{len(findings)} issue(s) found across {', '.join(files)}."
    risk_note = ""
    if highs:
        titles = "; ".join(f.title for f in highs[:3])
        risk_note = f" HIGH risk: {titles}."
    caution = " Proceed with care." if highs else ""
    return intro + risk_note + caution


def build_full_scan_response(result: ScanResult) -> dict:
    """Structured response dict for the scan_repo and scan_files MCP tools."""
    return {
        "health_score": result.health_score.overall,
        "files_scanned": result.files_scanned,
        "symbols_found": result.symbols_found,
        "scan_duration_seconds": round(
            (result.completed_at - result.started_at).total_seconds(), 2
        ),
        "git_metrics": git_metrics_to_dict(result.git_metrics),
        "findings_summary": findings_summary_dict(result),
        "top_findings": findings_to_dicts(result, max_findings=10),
        "recommendations": recommendations_to_dicts(result, max_recs=5),
        "health_context": build_health_context_prose(result),
    }
