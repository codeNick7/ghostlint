"""Integration tests for the tiramisu CLI scan command."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
import pytest
from typer.testing import CliRunner

from tiramisu_cli.main import app


runner = CliRunner()


class TestScanCommand:
    def test_scan_exits_zero_on_valid_repo(self, committed_repo: Path) -> None:
        result = runner.invoke(app, ["scan", str(committed_repo), "--headless"])
        assert result.exit_code in (0, 1), result.output  # 1 is allowed for low score

    def test_scan_json_to_file_is_valid(self, committed_repo: Path, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        result = runner.invoke(
            app,
            ["scan", str(committed_repo), "--format", "json", "--output", str(out), "--headless"],
        )
        assert result.exit_code in (0, 1), result.output
        payload = json.loads(out.read_text())
        assert "health_score" in payload

    def test_scan_json_has_findings_key(self, committed_repo: Path, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        runner.invoke(
            app,
            ["scan", str(committed_repo), "--format", "json", "--output", str(out), "--headless"],
        )
        payload = json.loads(out.read_text())
        assert "findings" in payload

    def test_scan_json_health_score_in_range(self, committed_repo: Path, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        runner.invoke(
            app,
            ["scan", str(committed_repo), "--format", "json", "--output", str(out), "--headless"],
        )
        payload = json.loads(out.read_text())
        score = payload["health_score"]
        assert isinstance(score, (int, float))
        assert 0.0 <= score <= 100.0

    def test_scan_json_git_metrics_present(self, committed_repo: Path, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        runner.invoke(
            app,
            ["scan", str(committed_repo), "--format", "json", "--output", str(out), "--headless"],
        )
        payload = json.loads(out.read_text())
        assert "git_metrics" in payload
        assert "stability_index" in payload["git_metrics"]

    def test_scan_nonexistent_path_fails(self) -> None:
        result = runner.invoke(app, ["scan", "/no/such/path", "--headless"])
        assert result.exit_code not in (0,)

    def test_scan_headless_does_not_open_browser(self, committed_repo: Path, monkeypatch) -> None:
        opened = []
        monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
        runner.invoke(app, ["scan", str(committed_repo), "--headless"])
        assert opened == []

    def test_scan_with_engine_filter(self, committed_repo: Path, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        result = runner.invoke(
            app,
            [
                "scan", str(committed_repo),
                "--engine", "dead_code",
                "--format", "json",
                "--output", str(out),
                "--headless",
            ],
        )
        assert result.exit_code in (0, 1), result.output
        payload = json.loads(out.read_text())
        assert "health_score" in payload


class TestMcpInfoCommand:
    def test_mcp_info_exits_zero(self) -> None:
        result = runner.invoke(app, ["mcp", "info"])
        assert result.exit_code == 0

    def test_mcp_info_lists_tools(self) -> None:
        result = runner.invoke(app, ["mcp", "info"])
        assert "scan_repo" in result.output

    def test_mcp_setup_dry_run_exits_zero(self) -> None:
        result = runner.invoke(app, ["mcp", "setup", "--dry-run"])
        assert result.exit_code == 0
