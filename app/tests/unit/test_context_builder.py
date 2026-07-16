"""Tests for MCP context_builder module."""
from __future__ import annotations
from datetime import datetime, timezone
import pytest

from ghostlint_engine.models.findings import (
    ScanResult, HealthScore, GitMetrics, Finding,
    DetectionCategory, RiskLevel, EffortLevel, Evidence, Recommendation,
)
from ghostlint_mcp.context_builder import (
    build_health_context_prose,
    build_file_context_prose,
    build_full_scan_response,
    findings_to_dicts,
    git_metrics_to_dict,
    findings_summary_dict,
)


def _make_result(
    score: float = 80.0,
    findings: list | None = None,
    git_available: bool = False,
) -> ScanResult:
    now = datetime.now(timezone.utc)
    hs = HealthScore(overall=score)
    gm = GitMetrics(available=git_available, stability_index=70.0, friction_index=25.0)
    return ScanResult(
        repo_path="/repo",
        scan_mode="full",
        started_at=now,
        completed_at=now,
        health_score=hs,
        findings=findings or [],
        recommendations=[],
        files_scanned=50,
        symbols_found=200,
        git_metrics=gm,
    )


def _make_finding(risk: RiskLevel = RiskLevel.HIGH, title: str = "Dead func") -> Finding:
    return Finding(
        category=DetectionCategory.DEAD_CODE,
        title=title,
        description="Unused",
        evidence=[Evidence(file_path="auth.py", line_start=10, line_end=15)],
        confidence=0.9,
        risk=risk,
        effort=EffortLevel.MINUTES,
    )


class TestBuildHealthContextProse:
    def test_healthy_score_label(self) -> None:
        result = _make_result(score=95.0)
        prose = build_health_context_prose(result)
        assert "healthy" in prose.lower()

    def test_critical_score_label(self) -> None:
        result = _make_result(score=30.0)
        prose = build_health_context_prose(result)
        assert "critical" in prose.lower()

    def test_includes_file_and_symbol_counts(self) -> None:
        result = _make_result()
        prose = build_health_context_prose(result)
        assert "50 files" in prose
        assert "200 symbols" in prose

    def test_mentions_high_risk_findings(self) -> None:
        findings = [_make_finding(risk=RiskLevel.HIGH, title="BadFunc")]
        result = _make_result(findings=findings)
        prose = build_health_context_prose(result)
        assert "HIGH" in prose
        assert "BadFunc" in prose

    def test_no_findings_no_risk_mention(self) -> None:
        result = _make_result(findings=[])
        prose = build_health_context_prose(result)
        assert "HIGH" not in prose
        assert "MEDIUM" not in prose

    def test_includes_git_friction_warning_when_high(self) -> None:
        now = datetime.now(timezone.utc)
        gm = GitMetrics(available=True, friction_index=75.0)
        result = _make_result()
        result.git_metrics = gm
        prose = build_health_context_prose(result)
        assert "friction" in prose.lower()


class TestBuildFileContextProse:
    def test_safe_when_no_findings(self) -> None:
        prose = build_file_context_prose([], ["auth.py"])
        assert "Safe to edit" in prose

    def test_mentions_finding_count(self) -> None:
        findings = [_make_finding()]
        prose = build_file_context_prose(findings, ["auth.py"])
        assert "1 issue" in prose

    def test_highlights_high_risk(self) -> None:
        findings = [_make_finding(risk=RiskLevel.HIGH)]
        prose = build_file_context_prose(findings, ["auth.py"])
        assert "HIGH" in prose
        assert "care" in prose.lower()


class TestFindingsToDicts:
    def test_returns_list_of_dicts(self) -> None:
        f = _make_finding()
        result = _make_result(findings=[f])
        dicts = findings_to_dicts(result)
        assert isinstance(dicts, list)
        assert len(dicts) == 1

    def test_dict_has_expected_keys(self) -> None:
        f = _make_finding()
        result = _make_result(findings=[f])
        d = findings_to_dicts(result)[0]
        for key in ("id", "category", "title", "file", "line", "confidence", "risk"):
            assert key in d

    def test_respects_max_findings(self) -> None:
        findings = [_make_finding() for _ in range(20)]
        result = _make_result(findings=findings)
        dicts = findings_to_dicts(result, max_findings=5)
        assert len(dicts) == 5


class TestGitMetricsToDict:
    def test_all_keys_present(self) -> None:
        gm = GitMetrics(available=True, stability_index=80.0)
        d = git_metrics_to_dict(gm)
        for key in ("available", "stability_index", "maintenance_velocity",
                    "refactor_completion_rate", "friction_index",
                    "total_commits_analyzed", "repo_age_days", "top_contributors"):
            assert key in d

    def test_unavailable_flag(self) -> None:
        gm = GitMetrics(available=False)
        d = git_metrics_to_dict(gm)
        assert d["available"] is False


class TestBuildFullScanResponse:
    def test_has_all_top_level_keys(self) -> None:
        result = _make_result()
        resp = build_full_scan_response(result)
        for key in ("health_score", "health_label", "files_scanned", "symbols_found",
                    "git_metrics", "findings_summary", "high_and_medium_findings",
                    "low_findings_summary", "report", "health_context"):
            assert key in resp

    def test_health_context_is_string(self) -> None:
        result = _make_result()
        resp = build_full_scan_response(result)
        assert isinstance(resp["health_context"], str)
        assert len(resp["health_context"]) > 10
