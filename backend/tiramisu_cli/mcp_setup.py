"""Auto-detect installed AI coding tools and write tiramisu MCP server configs."""
from __future__ import annotations
import json
import shutil
import sys
from pathlib import Path
from typing import Optional


_SERVER_ENTRY = {
    "command": "tiramisu",
    "args": ["mcp"],
    "env": {},
}

# Fallback when tiramisu isn't on PATH (e.g. installed in a venv)
_SERVER_ENTRY_PYTHON = {
    "command": sys.executable,
    "args": ["-m", "tiramisu_cli.main", "mcp"],
    "env": {},
}


def _tiramisu_on_path() -> bool:
    return shutil.which("tiramisu") is not None


def _server_entry() -> dict:
    if _tiramisu_on_path():
        return _SERVER_ENTRY.copy()
    # Use the current Python interpreter as fallback
    return _SERVER_ENTRY_PYTHON.copy()


# ── Per-tool config writers ────────────────────────────────────────────────────

def _detect_claude_code() -> Optional[Path]:
    """Return the settings file to patch, or None if Claude Code not found."""
    claude_dir = Path.home() / ".claude"
    if claude_dir.exists() or shutil.which("claude"):
        return claude_dir / "settings.json"
    return None


def _detect_cursor() -> Optional[Path]:
    cursor_dir = Path.home() / ".cursor"
    if cursor_dir.exists() or shutil.which("cursor"):
        cursor_dir.mkdir(parents=True, exist_ok=True)
        return cursor_dir / "mcp.json"
    return None


def _detect_windsurf() -> Optional[Path]:
    ws_dir = Path.home() / ".codeium" / "windsurf"
    if ws_dir.exists():
        return ws_dir / "mcp_config.json"
    return None


def _detect_zed() -> Optional[Path]:
    zed_dir = Path.home() / ".config" / "zed"
    if zed_dir.exists():
        return zed_dir / "settings.json"
    return None


_TOOLS: list[tuple[str, callable]] = [
    ("Claude Code", _detect_claude_code),
    ("Cursor", _detect_cursor),
    ("Windsurf", _detect_windsurf),
    ("Zed", _detect_zed),
]


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _patch_config(tool_name: str, config_path: Path, entry: dict, dry_run: bool) -> str:
    """Merge the tiramisu MCP entry into *config_path*. Returns a status string."""
    data = _read_json(config_path)

    # Normalise: Claude Code uses top-level mcpServers; Cursor uses mcpServers;
    # Zed uses context_servers; Windsurf uses mcpServers.
    if tool_name == "Zed":
        key = "context_servers"
        # Zed's schema differs: { "context_servers": { "tiramisu": { ... } } }
        servers = data.setdefault(key, {})
        existing = servers.get("tiramisu")
        if existing == entry:
            return "already configured — no changes needed"
        servers["tiramisu"] = entry
    else:
        key = "mcpServers"
        servers = data.setdefault(key, {})
        existing = servers.get("tiramisu")
        if existing == entry:
            return "already configured — no changes needed"
        servers["tiramisu"] = entry

    if dry_run:
        preview = json.dumps({key: {"tiramisu": entry}}, indent=2)
        return f"would write to {config_path}:\n{preview}"

    _write_json(config_path, data)
    return f"written to {config_path}"


def run_setup(dry_run: bool = False, tool_filter: Optional[str] = None) -> list[tuple[str, str]]:
    """Auto-configure tiramisu MCP for all detected AI tools.

    Returns a list of (tool_name, status_message) tuples.
    """
    entry = _server_entry()
    results: list[tuple[str, str]] = []

    for tool_name, detector in _TOOLS:
        if tool_filter and tool_filter.lower() not in tool_name.lower():
            continue
        config_path = detector()
        if config_path is None:
            results.append((tool_name, "not detected on this machine — skipped"))
            continue
        status = _patch_config(tool_name, config_path, entry, dry_run)
        results.append((tool_name, status))

    return results


def print_manual_snippet() -> str:
    """Return a copy-paste snippet for tools not auto-detected."""
    entry = _server_entry()
    snippet = {
        "mcpServers": {
            "tiramisu": entry,
        }
    }
    return json.dumps(snippet, indent=2)
