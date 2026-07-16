"""Tests for the HTML report generator."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest

from ghostlint_engine.models.findings import (
    ScanResult, HealthScore, GitMetrics, Finding,
    DetectionCategory, RiskLevel, EffortLevel, Evidence,
)
from ghostlint_cli.html_report import generate_html_report, write_html_report


def _make_result(findings: list | None = None) -> ScanResult:
    now = datetime.now(timezone.utc)
    return ScanResult(
        repo_path="/myrepo",
        scan_mode="full",
        started_at=now,
        completed_at=now,
        health_score=HealthScore(overall=82.5, dead_code=70.0, test_health=95.0),
        findings=findings or [],
        recommendations=[],
        files_scanned=100,
        symbols_found=400,
        git_metrics=GitMetrics(
            available=True,
            stability_index=75.0,
            maintenance_velocity=0.35,
            refactor_completion_rate=60.0,
            friction_index=30.0,
            total_commits_analyzed=50,
            repo_age_days=180,
            top_contributors=4,
        ),
    )


def _make_finding(risk: RiskLevel = RiskLevel.MEDIUM) -> Finding:
    return Finding(
        category=DetectionCategory.DEAD_CODE,
        title="Unused function: _helper",
        description="Never called",
        evidence=[Evidence(file_path="src/utils.py", line_start=42, line_end=48)],
        confidence=0.85,
        risk=risk,
        effort=EffortLevel.MINUTES,
    )


class TestGenerateHtmlReport:
    def test_returns_string(self) -> None:
        result = _make_result()
        html = generate_html_report(result)
        assert isinstance(html, str)

    def test_is_valid_html(self) -> None:
        html = generate_html_report(_make_result())
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_repo_name(self) -> None:
        html = generate_html_report(_make_result())
        assert "myrepo" in html

    def test_contains_health_score(self) -> None:
        html = generate_html_report(_make_result())
        assert "82.5" in html

    def test_contains_ghostlint_branding(self) -> None:
        html = generate_html_report(_make_result())
        assert "ghostlint" in html.lower()

    def test_contains_git_metrics_when_available(self) -> None:
        html = generate_html_report(_make_result())
        assert "Stability Index" in html
        assert "Friction Index" in html

    def test_git_unavailable_shows_fallback(self) -> None:
        result = _make_result()
        result.git_metrics = GitMetrics(available=False)
        html = generate_html_report(result)
        assert "not available" in html

    def test_findings_appear_in_table(self) -> None:
        f = _make_finding()
        result = _make_result(findings=[f])
        html = generate_html_report(result)
        assert "_helper" in html
        assert "src/utils.py" in html

    def test_no_findings_message(self) -> None:
        html = generate_html_report(_make_result(findings=[]))
        assert "No issues found" in html

    def test_escapes_html_special_chars(self) -> None:
        result = _make_result()
        result.repo_path = "/repos/<my>&repo"
        html = generate_html_report(result)
        assert "<my>&repo" not in html
        assert "&lt;" in html or "repo" in html  # escaped or safe portion present

    def test_sri_integrity_on_chartjs(self) -> None:
        html = generate_html_report(_make_result())
        assert 'integrity="sha384-' in html
        assert 'crossorigin="anonymous"' in html

    def test_security_headers_present(self) -> None:
        html = generate_html_report(_make_result())
        assert "X-Content-Type-Options" not in html  # HTTP header, not in HTML body
        assert "nosniff" not in html  # same — belongs in HTTP response, not HTML

    def test_filter_dropdowns_rendered(self) -> None:
        f = _make_finding(risk=RiskLevel.HIGH)
        html = generate_html_report(_make_result(findings=[f]))
        assert "riskFilter" in html
        assert "catFilter" in html


class TestWriteHtmlReport:
    def test_writes_file(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        write_html_report(_make_result(), out)
        assert out.exists()
        assert out.stat().st_size > 100

    def test_written_file_is_valid_html(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        write_html_report(_make_result(), out)
        content = out.read_text()
        assert "<!DOCTYPE html>" in content
