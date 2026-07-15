"""Tests for MCP auto-setup (config detection and writing)."""
from __future__ import annotations
import json
from pathlib import Path
import pytest

from tiramisu_cli.mcp_setup import (
    _patch_config,
    _read_json,
    _write_json,
    print_manual_snippet,
    run_setup,
)

_ENTRY = {
    "command": "tiramisu",
    "args": ["mcp"],
    "env": {},
}


class TestReadWriteJson:
    def test_read_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        assert _read_json(tmp_path / "nope.json") == {}

    def test_read_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "cfg.json"
        f.write_text('{"a": 1}')
        assert _read_json(f) == {"a": 1}

    def test_write_creates_file(self, tmp_path: Path) -> None:
        f = tmp_path / "out.json"
        _write_json(f, {"x": 42})
        assert json.loads(f.read_text()) == {"x": 42}

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        f = tmp_path / "a" / "b" / "cfg.json"
        _write_json(f, {"ok": True})
        assert f.exists()


class TestPatchConfig:
    def test_creates_new_mcp_servers_key(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        _patch_config("Claude Code", cfg, _ENTRY, dry_run=False)
        data = json.loads(cfg.read_text())
        assert data["mcpServers"]["tiramisu"] == _ENTRY

    def test_merges_without_overwriting_other_keys(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        cfg.write_text(json.dumps({"mcpServers": {"other_tool": {"command": "other"}}}))
        _patch_config("Claude Code", cfg, _ENTRY, dry_run=False)
        data = json.loads(cfg.read_text())
        assert "other_tool" in data["mcpServers"]
        assert "tiramisu" in data["mcpServers"]

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        status = _patch_config("Claude Code", cfg, _ENTRY, dry_run=True)
        assert not cfg.exists()
        assert "would write" in status

    def test_already_configured_returns_no_changes_needed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        _write_json(cfg, {"mcpServers": {"tiramisu": _ENTRY}})
        status = _patch_config("Claude Code", cfg, _ENTRY, dry_run=False)
        assert "no changes needed" in status

    def test_zed_uses_context_servers_key(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        _patch_config("Zed", cfg, _ENTRY, dry_run=False)
        data = json.loads(cfg.read_text())
        assert "context_servers" in data
        assert data["context_servers"]["tiramisu"] == _ENTRY

    def test_written_status_contains_path(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        status = _patch_config("Claude Code", cfg, _ENTRY, dry_run=False)
        assert str(cfg) in status


class TestPrintManualSnippet:
    def test_returns_valid_json(self) -> None:
        snippet = print_manual_snippet()
        parsed = json.loads(snippet)
        assert "mcpServers" in parsed
        assert "tiramisu" in parsed["mcpServers"]

    def test_snippet_has_command(self) -> None:
        snippet = print_manual_snippet()
        parsed = json.loads(snippet)
        entry = parsed["mcpServers"]["tiramisu"]
        assert "command" in entry
        assert "args" in entry


class TestRunSetup:
    def test_returns_list_of_tuples(self, tmp_path: Path, monkeypatch) -> None:
        # Monkeypatch detectors so we control what's found
        import tiramisu_cli.mcp_setup as m
        monkeypatch.setattr(m, "_TOOLS", [
            ("FakeTool", lambda: tmp_path / "fake_cfg.json"),
        ])
        results = run_setup(dry_run=True)
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0][0] == "FakeTool"

    def test_skips_not_detected_tools(self, monkeypatch) -> None:
        import tiramisu_cli.mcp_setup as m
        monkeypatch.setattr(m, "_TOOLS", [
            ("GhostTool", lambda: None),
        ])
        results = run_setup()
        assert "not detected" in results[0][1]

    def test_tool_filter_limits_results(self, tmp_path: Path, monkeypatch) -> None:
        import tiramisu_cli.mcp_setup as m
        monkeypatch.setattr(m, "_TOOLS", [
            ("ToolA", lambda: tmp_path / "a.json"),
            ("ToolB", lambda: tmp_path / "b.json"),
        ])
        results = run_setup(dry_run=True, tool_filter="ToolA")
        assert len(results) == 1
        assert results[0][0] == "ToolA"
