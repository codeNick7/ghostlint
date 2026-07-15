"""Unit tests for ghostlint_mcp.repo_intel — the pure-function intelligence layer.

These exercise the helpers in isolation (no scan, no git) by constructing
Finding/ScanResult objects directly, mirroring the factory pattern used in
test_context_builder.py and test_html_report.py.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ghostlint_engine.models.findings import (
    DetectionCategory,
    EffortLevel,
    Evidence,
    Finding,
    GitMetrics,
    HealthScore,
    RiskLevel,
    ScanResult,
)
from ghostlint_mcp import repo_intel


# ─── factories ──────────────────────────────────────────────────────────────

def _finding(
    category: DetectionCategory = DetectionCategory.DEAD_CODE,
    title: str = "Unused function foo",
    description: str = "foo is never called.",
    confidence: float = 0.8,
    risk: RiskLevel = RiskLevel.LOW,
    effort: EffortLevel = EffortLevel.MINUTES,
    file: str = "src/app.py",
    line: int = 10,
    benefit: str = "Reduces maintenance surface.",
) -> Finding:
    return Finding(
        category=category,
        title=title,
        description=description,
        evidence=[Evidence(file_path=file, line_start=line, line_end=line, snippet="x")],
        confidence=confidence,
        risk=risk,
        effort=effort,
        benefit=benefit,
    )


def _result(findings: list[Finding] | None = None, score: float = 80.0) -> ScanResult:
    return ScanResult(
        repo_path="/repo",
        scan_mode="full",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        health_score=HealthScore(overall=score),
        findings=findings or [],
        recommendations=[],
        files_scanned=10,
        symbols_found=50,
        git_metrics=GitMetrics(available=False),
    )


# ─── health_label ───────────────────────────────────────────────────────────

class TestHealthLabel:
    def test_boundaries(self) -> None:
        assert repo_intel.health_label(95) == "healthy"
        assert repo_intel.health_label(90) == "healthy"
        assert repo_intel.health_label(89.9) == "needs review"
        assert repo_intel.health_label(70) == "needs review"
        assert repo_intel.health_label(50) == "has significant issues"
        assert repo_intel.health_label(49.9) == "critical"
        assert repo_intel.health_label(0) == "critical"


# ─── finding_to_dict ────────────────────────────────────────────────────────

class TestFindingToDict:
    def test_full_shape(self) -> None:
        f = _finding()
        d = repo_intel.finding_to_dict(f)
        for key in ("id", "category", "title", "description", "file", "line",
                    "confidence", "risk", "effort", "benefit"):
            assert key in d
        assert d["category"] == "dead_code"
        assert d["risk"] == "low"
        assert d["effort"] == "minutes"
        assert d["file"] == "src/app.py"
        assert d["line"] == 10


# ─── estimate_effort ────────────────────────────────────────────────────────

class TestEstimateEffort:
    def test_empty(self) -> None:
        out = repo_intel.estimate_effort([])
        assert out["total_findings"] == 0
        assert out["estimated_hours"] == 0.0

    def test_aggregation_math(self) -> None:
        # minutes (0.5h) * 0.8 conf = 0.4 ; days (8h) * 1.0 conf = 8.0
        fs = [
            _finding(confidence=0.8, effort=EffortLevel.MINUTES),
            _finding(confidence=1.0, effort=EffortLevel.DAYS),
        ]
        out = repo_intel.estimate_effort(fs)
        assert out["total_findings"] == 2
        assert out["estimated_hours"] == round(0.4 + 8.0, 1)
        assert out["estimated_days"] == round((0.4 + 8.0) / 8.0, 1)
        assert out["by_effort"] == {"minutes": 1, "days": 1}
        assert out["by_category"] == {"dead_code": 2}

    def test_quick_wins_count(self) -> None:
        # high conf + low risk + minutes/hours → quick win
        quick = _finding(confidence=0.8, risk=RiskLevel.LOW, effort=EffortLevel.MINUTES)
        not_quick = _finding(confidence=0.5, risk=RiskLevel.LOW, effort=EffortLevel.MINUTES)
        high_risk = _finding(confidence=0.9, risk=RiskLevel.HIGH, effort=EffortLevel.MINUTES)
        out = repo_intel.estimate_effort([quick, not_quick, high_risk])
        assert out["quick_wins_count"] == 1


# ─── cleanup_recommendations ───────────────────────────────────────────────

class TestCleanupRecommendations:
    def test_quick_wins_first(self) -> None:
        # low-risk, high-confidence minutes should rank above high-risk days
        quick = _finding(title="quick", confidence=0.9, risk=RiskLevel.LOW,
                         effort=EffortLevel.MINUTES)
        risky = _finding(title="risky", confidence=0.6, risk=RiskLevel.HIGH,
                         effort=EffortLevel.DAYS)
        recs = repo_intel.cleanup_recommendations([risky, quick])
        assert recs[0]["title"] == "quick"
        assert recs[1]["title"] == "risky"
        assert "est_hours" in recs[0]

    def test_limit_respected(self) -> None:
        fs = [_finding(title=f"f{i}", confidence=0.7) for i in range(10)]
        recs = repo_intel.cleanup_recommendations(fs, limit=3)
        assert len(recs) == 3


# ─── build_cleanup_plan ────────────────────────────────────────────────────

class TestBuildCleanupPlan:
    def test_phase_assignment(self) -> None:
        quick = _finding(title="quick", confidence=0.9, risk=RiskLevel.LOW,
                         effort=EffortLevel.MINUTES)
        quickfix = _finding(title="qfix", confidence=0.6, risk=RiskLevel.MEDIUM,
                            effort=EffortLevel.HOURS)
        refactor = _finding(title="ref", confidence=0.8, risk=RiskLevel.MEDIUM,
                            effort=EffortLevel.DAYS)
        strategic = _finding(title="strat", confidence=0.8, risk=RiskLevel.HIGH,
                             effort=EffortLevel.HOURS)
        plan = repo_intel.build_cleanup_plan(
            [quick, quickfix, refactor, strategic], HealthScore(overall=70.0),
        )
        phases = plan["phases"]
        assert phases["1_quick_wins"]["summary"]["count"] == 1
        assert phases["2_quick_fixes"]["summary"]["count"] == 1
        assert phases["3_refactors"]["summary"]["count"] == 1
        assert phases["4_strategic"]["summary"]["count"] == 1
        # High-risk always goes strategic even if also days.
        assert phases["4_strategic"]["items"][0]["title"] == "strat"

    def test_recommended_order_omits_empty_phases(self) -> None:
        quick = _finding(confidence=0.9, risk=RiskLevel.LOW, effort=EffortLevel.MINUTES)
        plan = repo_intel.build_cleanup_plan([quick], HealthScore(overall=90.0))
        assert plan["recommended_order"] == ["1_quick_wins"]
        assert plan["health_label"] == "healthy"

    def test_empty_plan(self) -> None:
        plan = repo_intel.build_cleanup_plan([], HealthScore(overall=100.0))
        assert plan["total_findings"] == 0
        assert plan["recommended_order"] == []
        assert plan["total_estimated_hours"] == 0.0

    def test_summary_string(self) -> None:
        plan = repo_intel.build_cleanup_plan(
            [_finding(confidence=0.9, risk=RiskLevel.LOW, effort=EffortLevel.MINUTES)],
            HealthScore(overall=90.0),
        )
        assert "quick win" in plan["summary"]


# ─── patterns ───────────────────────────────────────────────────────────────

class TestPatterns:
    def test_duplication_grouping(self, tmp_path: Path) -> None:
        dups = [
            _finding(category=DetectionCategory.DUPLICATE_LOGIC, title="dup A",
                     file="a.py"),
            _finding(category=DetectionCategory.DUPLICATE_LOGIC, title="dup A",
                     file="b.py"),
        ]
        out = repo_intel.patterns(dups, tmp_path)
        assert len(out["duplication_patterns"]) == 1
        assert out["duplication_patterns"][0]["occurrences"] == 2
        assert "a.py" in out["duplication_patterns"][0]["files"]

    def test_naming_and_api_proliferation(self, tmp_path: Path) -> None:
        fs = [
            _finding(category=DetectionCategory.NAMING_CONSISTENCY, title="dup model"),
            _finding(category=DetectionCategory.REFACTOR_COMPLETION, title="get vs fetch"),
        ]
        out = repo_intel.patterns(fs, tmp_path)
        assert len(out["naming_patterns"]) == 1
        assert len(out["api_proliferation"]) == 1

    def test_directory_structure_shape(self, tmp_path: Path) -> None:
        out = repo_intel.patterns([], tmp_path)
        assert "top_source_directories" in out["directory_structure"]
        assert isinstance(out["summary"], str)


# ─── search_knowledge ──────────────────────────────────────────────────────

class TestSearchKnowledge:
    def test_empty_query(self, tmp_path: Path) -> None:
        out = repo_intel.search_knowledge([], tmp_path, "   ", limit=5)
        assert out["finding_matches"] == []
        assert "message" in out

    def test_finding_match_ranked_by_overlap(self, tmp_path: Path) -> None:
        strong = _finding(title="login function unused", description="login",
                          confidence=0.9)
        weak = _finding(title="unrelated thing", description="zzz", confidence=0.5)
        out = repo_intel.search_knowledge([weak, strong], tmp_path, "login", limit=5)
        assert out["finding_matches"][0]["title"] == "login function unused"
        assert out["finding_matches"][0]["score"] > 0

    def test_file_match(self, tmp_path: Path) -> None:
        (tmp_path / "auth_service.py").write_text("def login(): pass\n")
        out = repo_intel.search_knowledge([], tmp_path, "auth", limit=5)
        assert any("auth_service.py" in m["file"] for m in out["file_matches"])

    def test_total_matches(self, tmp_path: Path) -> None:
        f = _finding(title="foo unused", description="foo")
        out = repo_intel.search_knowledge([f], tmp_path, "foo", limit=5)
        assert out["total_matches"] == len(out["finding_matches"]) + len(out["file_matches"])


# ─── metrics_dict ──────────────────────────────────────────────────────────

class TestMetricsDict:
    def test_shape_and_weakest(self) -> None:
        result = _result(
            findings=[_finding(file="a.py"), _finding(file="a.py"), _finding(file="b.py")],
            score=60.0,
        )
        gm = GitMetrics(available=True, stability_index=80.0, maintenance_velocity=0.2,
                        repo_age_days=100, total_commits_analyzed=50, top_contributors=3)
        out = repo_intel.metrics_dict(result, gm)
        assert out["health_score"] == 60.0
        assert out["health_label"] == "has significant issues"
        assert "dead_code" in out["category_scores"]
        assert len(out["weakest_categories"]) == 3
        # a.py has 2 findings → top hotspot
        assert out["hotspot_files"][0]["file"] == "a.py"
        assert out["hotspot_files"][0]["finding_count"] == 2
        assert out["git_metrics"]["available"] is True

    def test_no_findings(self) -> None:
        out = repo_intel.metrics_dict(_result(score=100.0), GitMetrics(available=False))
        assert out["findings_total"] == 0
        assert out["hotspot_files"] == []


# ─── scan_timeline ──────────────────────────────────────────────────────────

class _FakeRecord:
    """Minimal duck-typed stand-in for a ScanRecord ORM object."""
    def __init__(self, rid: str, score: float, files: int, findings_count: int) -> None:
        self.id = rid
        self.started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.health_score_overall = score
        self.files_scanned = files
        self.symbols_found = files * 5
        self.findings = list(range(findings_count))  # len() is all we need


# ─── overview ──────────────────────────────────────────────────────────────

class TestOverview:
    def test_returns_required_keys(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("def main(): pass\n")
        out = repo_intel.overview(tmp_path)
        for key in ("repo_path", "total_files", "total_lines", "files_by_language",
                    "top_directories", "entry_points", "detected_frameworks", "config_files"):
            assert key in out

    def test_counts_python_file(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")
        out = repo_intel.overview(tmp_path)
        assert out["total_files"] >= 1
        assert "python" in out["files_by_language"]

    def test_detects_entry_point(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("def main(): pass\n")
        out = repo_intel.overview(tmp_path)
        assert any("main.py" in ep for ep in out["entry_points"])

    def test_detects_fastapi_framework(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\nuvicorn\n")
        (tmp_path / "app.py").write_text("from fastapi import FastAPI\n")
        out = repo_intel.overview(tmp_path)
        assert "fastapi" in out["detected_frameworks"]

    def test_detects_react_from_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}\n')
        (tmp_path / "index.js").write_text("import React from 'react';\n")
        out = repo_intel.overview(tmp_path)
        assert "react" in out["detected_frameworks"]

    def test_config_files_listed(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n")
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
        out = repo_intel.overview(tmp_path)
        assert "pyproject.toml" in out["config_files"]
        assert "Makefile" in out["config_files"]

    def test_empty_dir_has_zero_files(self, tmp_path: Path) -> None:
        out = repo_intel.overview(tmp_path)
        assert out["total_files"] == 0
        assert out["total_lines"] == 0
        assert out["entry_points"] == []

    def test_top_directories_counted(self, tmp_path: Path) -> None:
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "utils.py").write_text("pass\n")
        (sub / "models.py").write_text("pass\n")
        out = repo_intel.overview(tmp_path)
        assert "src" in out["top_directories"]
        assert out["top_directories"]["src"] >= 2


# ─── explain_history & _history_narrative ─────────────────────────────────

class TestExplainHistory:
    def test_not_git_returns_unavailable(self, tmp_path: Path) -> None:
        out = repo_intel.explain_history(tmp_path)
        assert out["available"] is False
        assert "message" in out

    def test_git_repo_returns_available(self, tmp_path: Path) -> None:
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"],
                       capture_output=True, check=True)
        (tmp_path / "f.py").write_text("x=1\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"],
                       capture_output=True, check=True)
        out = repo_intel.explain_history(tmp_path)
        assert out["available"] is True
        assert isinstance(out["recent_commits"], list)
        assert len(out["recent_commits"]) >= 1
        assert isinstance(out["narrative"], str)
        assert len(out["narrative"]) > 0

    def test_has_contributors_key(self, tmp_path: Path) -> None:
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "a@b.com"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "A"],
                       capture_output=True, check=True)
        (tmp_path / "g.py").write_text("y=2\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "feat: add g"],
                       capture_output=True, check=True)
        out = repo_intel.explain_history(tmp_path)
        assert "contributors" in out
        assert isinstance(out["contributors"], list)


class TestHistoryNarrative:
    def test_unavailable_returns_short_message(self) -> None:
        gm = GitMetrics(available=False)
        narrative = repo_intel._history_narrative(gm, 0)
        assert "No git metrics" in narrative

    def test_available_includes_key_metrics(self) -> None:
        gm = GitMetrics(
            available=True,
            stability_index=75.0,
            maintenance_velocity=0.3,
            friction_index=40.0,
            total_commits_analyzed=50,
            repo_age_days=120,
        )
        narrative = repo_intel._history_narrative(gm, 10)
        assert "120" in narrative
        assert "50" in narrative
        assert "75" in narrative

    def test_low_stability_mentioned(self) -> None:
        gm = GitMetrics(
            available=True,
            stability_index=30.0,
            maintenance_velocity=0.05,
            friction_index=70.0,
            total_commits_analyzed=10,
            repo_age_days=30,
        )
        narrative = repo_intel._history_narrative(gm, 5)
        assert "30" in narrative  # stability index in text


class TestScanTimeline:
    def test_empty(self) -> None:
        out = repo_intel.scan_timeline([])
        assert out["available"] is False
        assert out["scan_count"] == 0
        assert out["trend"] == "stable"

    def test_trend_improving(self) -> None:
        records = [
            _FakeRecord("1", 50.0, 10, 8),
            _FakeRecord("2", 70.0, 10, 4),
            _FakeRecord("3", 90.0, 10, 1),
        ]
        out = repo_intel.scan_timeline(records)
        assert out["available"] is True
        assert out["scan_count"] == 3
        assert out["trend"] == "improving"
        assert out["latest"]["health_score"] == 90.0
        assert out["oldest"]["health_score"] == 50.0
        assert "+" in out["summary"] or "→" in out["summary"] or "improv" in out["summary"]

    def test_trend_declining(self) -> None:
        records = [_FakeRecord("1", 90.0, 10, 1), _FakeRecord("2", 50.0, 10, 8)]
        out = repo_intel.scan_timeline(records)
        assert out["trend"] == "declining"

    def test_trend_stable(self) -> None:
        records = [_FakeRecord("1", 80.0, 10, 3), _FakeRecord("2", 80.5, 10, 3)]
        out = repo_intel.scan_timeline(records)
        assert out["trend"] == "stable"
