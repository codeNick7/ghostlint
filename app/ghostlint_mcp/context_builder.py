"""Convert ScanResult / GitMetrics into AI-friendly prose and structured dicts."""
from __future__ import annotations
from ghostlint_engine.models.findings import ScanResult, RiskLevel, GitMetrics


def _finding_to_dict(f) -> dict:
    return {
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
    }


def findings_to_dicts(result: ScanResult, max_findings: int = 10) -> list[dict]:
    return [_finding_to_dict(f) for f in result.findings[:max_findings]]


def findings_to_dicts_list(findings: list, max_findings: int = 200) -> list[dict]:
    """Convert a pre-filtered list of findings (not a ScanResult) to dicts."""
    return [_finding_to_dict(f) for f in findings[:max_findings]]


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
    """Complete report dict for the scan_repo MCP tool.

    Contains everything needed for a standard health report — no follow-up
    tool calls required. Presentation order (tell the AI exactly what to show):

      1. report.executive_summary   — one-paragraph overall verdict
      2. report.priority_actions    — ordered list: what to fix first and why
      3. high_and_medium_findings   — ALL actionable findings (HIGH + MEDIUM)
      4. report.category_scores     — per-category breakdown with health labels
      5. report.hotspot_files       — top files by finding density
      6. report.effort_estimate     — total estimated cleanup hours
      7. low_findings_summary       — count only; drill with list_findings(risk='low')

    Focused tools (find_dead_code, find_duplicate_logic, etc.) are for
    deep-dives into a specific category — not needed for a standard report.
    """
    from collections import Counter
    from ghostlint_mcp import repo_intel

    findings = result.findings
    hs = result.health_score
    high_med = [f for f in findings if f.risk.value in ("high", "medium")]
    low = [f for f in findings if f.risk.value == "low"]

    # Per-category scores with labels
    category_scores = {
        "dead_code":              {"score": round(hs.dead_code, 1),            "label": repo_intel.health_label(hs.dead_code)},
        "duplicate_logic":        {"score": round(hs.duplicate_logic, 1),      "label": repo_intel.health_label(hs.duplicate_logic)},
        "refactor_completion":    {"score": round(hs.refactor_completion, 1),  "label": repo_intel.health_label(hs.refactor_completion)},
        "architectural_drift":    {"score": round(hs.architectural_drift, 1),  "label": repo_intel.health_label(hs.architectural_drift)},
        "dependency_health":      {"score": round(hs.dependency_health, 1),    "label": repo_intel.health_label(hs.dependency_health)},
        "documentation_freshness":{"score": round(hs.documentation_freshness, 1), "label": repo_intel.health_label(hs.documentation_freshness)},
        "test_health":            {"score": round(hs.test_health, 1),          "label": repo_intel.health_label(hs.test_health)},
        "config_consistency":     {"score": round(hs.config_consistency, 1),   "label": repo_intel.health_label(hs.config_consistency)},
    }
    weakest = sorted(category_scores.items(), key=lambda kv: kv[1]["score"])[:3]

    # Hotspot files — top 5 by finding density
    file_counts: Counter = Counter(f.primary_file for f in findings if f.primary_file)
    hotspot_files = [{"file": f, "finding_count": n} for f, n in file_counts.most_common(5)]

    # Quick-win cleanup recommendations (high confidence, low effort, low risk)
    quick_wins = repo_intel.cleanup_recommendations(findings, limit=10)

    # Effort estimate
    effort = repo_intel.estimate_effort(findings)

    # Priority actions: HIGH findings first, then weakest categories
    priority_actions = []
    for f in high_med[:5]:
        priority_actions.append({
            "action": f.title,
            "file": f.primary_file,
            "why": f.description[:120] + ("…" if len(f.description) > 120 else ""),
            "effort": f.effort.value,
            "risk": f.risk.value,
        })
    for cat, info in weakest:
        if not any(pa["action"].lower().startswith(cat.replace("_", " ")) for pa in priority_actions):
            priority_actions.append({
                "action": f"Improve {cat.replace('_', ' ')} (score: {info['score']})",
                "file": None,
                "why": f"Category is {info['label']} — use find_{cat} for details.",
                "effort": "hours",
                "risk": "medium",
            })

    low_by_cat = dict(Counter(f.category.value for f in low))

    return {
        # ── Top-level numbers ────────────────────────────────────────────────
        "health_score": result.health_score.overall,
        "health_label": repo_intel.health_label(result.health_score.overall),
        "files_scanned": result.files_scanned,
        "symbols_found": result.symbols_found,
        "scan_duration_seconds": round(
            (result.completed_at - result.started_at).total_seconds(), 2
        ),

        # ── Presentation-ready report block (use this for the report) ───────
        "report": {
            "executive_summary": build_health_context_prose(result),
            "priority_actions": priority_actions,
            "category_scores": category_scores,
            "weakest_categories": [{"category": c, "score": s["score"], "label": s["label"]} for c, s in weakest],
            "hotspot_files": hotspot_files,
            "effort_estimate": effort,
            "quick_wins": quick_wins,
        },

        # ── Findings ─────────────────────────────────────────────────────────
        "findings_summary": findings_summary_dict(result),
        "high_and_medium_findings": findings_to_dicts_list(high_med),
        "low_findings_summary": {
            "count": len(low),
            "by_category": low_by_cat,
            "note": "Use list_findings(risk='low') to page through individual low-risk items.",
        },

        # ── Git signals ──────────────────────────────────────────────────────
        "git_metrics": git_metrics_to_dict(result.git_metrics),

        # ── Prose context (for injecting into AI system prompts) ─────────────
        "health_context": build_health_context_prose(result),
    }
