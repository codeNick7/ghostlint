# tiramisu MCP Server — Implementation Plan

**Decision:** Build tiramisu as an MCP (Model Context Protocol) server.
MCP is the established standard for exposing arbitrary tools to AI coding
assistants. One implementation; every MCP-compatible client (Claude Code,
Cursor, Windsurf, Zed, custom agents) picks it up automatically.

**North star UX:**
```
pip install tiramisu
# → in Claude Code, Cursor, etc.:
tiramisu mcp setup   # auto-detects installed AI tools, writes their configs
```
That is the entire setup. Zero manual JSON editing for the user.

---

## Design Principles

1. **stdio transport only.** No port management, no daemon, no background
   process. Claude Code and Cursor both support `command + args` MCP servers
   that speak JSON-RPC over stdin/stdout. This is simpler to install and
   more secure than an HTTP transport.

2. **One command launches the server.** `tiramisu mcp` starts the stdio
   MCP server. The AI tool config is just:
   ```json
   { "command": "tiramisu", "args": ["mcp"] }
   ```

3. **Self-configuring.** `tiramisu mcp setup` auto-detects which AI tools
   are installed on the machine and writes or patches their config files.
   No instructions to follow; the tool does it.

4. **AI-readable setup docs.** The README has a "Connect to your AI tool"
   section written as a directive the AI tool itself can execute. A user can
   literally say "set up tiramisu" to Claude Code and it will run
   `tiramisu mcp setup` after reading the README.

5. **Context-aware tools.** Tools accept an optional `files` list so the AI
   can pass partial context (just the files it's currently editing) without
   triggering a full repo scan every time.

---

## MCP Tools to Expose

### `scan_repo`
Full health scan. The AI calls this when the user asks a broad question
("is this repo healthy?", "what are the riskiest parts?").

```json
Input:
{
  "path": "/abs/path/to/repo",       // local path
  "github": "owner/repo",            // OR public GitHub shorthand
  "engines": ["dead_code"],          // optional, default: all phase-1
  "min_confidence": 0.6              // optional
}

Output:
{
  "health_score": 76.4,
  "files_scanned": 342,
  "symbols_found": 1847,
  "git_metrics": {
    "available": true,
    "stability_index": 82.0,
    "maintenance_velocity": 0.31,
    "refactor_completion_rate": 65.0,
    "friction_index": 28.5
  },
  "findings_summary": {
    "total": 18,
    "high": 3,
    "medium": 9,
    "low": 6,
    "by_category": { "dead_code": 5, "duplicate_logic": 3, ... }
  },
  "top_findings": [ ...up to 10... ],
  "recommendations": [ ...up to 5... ]
}
```

### `scan_files`
Targeted scan of specific files. The AI calls this when it has partial
context — e.g., the user asked it to edit `auth.py` and it wants to know
if that file has any known issues before touching it.

```json
Input:
{
  "repo_path": "/abs/path/to/repo",
  "files": ["src/auth.py", "src/middleware/token.py"]
}

Output:
{
  "findings": [ ...findings whose primary_file is in the given list... ],
  "health_context": "2 HIGH findings in auth.py: unused _verify_token (dead code), duplicate parse_jwt (×2). Proceed with care."
}
```

The `health_context` field is a one-paragraph prose summary the AI can
include directly in its reasoning without further parsing.

### `check_diff`
Hypothetical impact analysis. The AI sends a proposed diff before applying
it; tiramisu returns the projected score delta and new findings.
*Phase 2 — stub the tool now, implement the diff-apply engine later.*

```json
Input:
{
  "repo_path": "/abs/path/to/repo",
  "diff": "--- a/auth.py\n+++ b/auth.py\n..."
}

Output:
{
  "score_before": 84.2,
  "score_after": 79.1,
  "delta": -5.1,
  "regression_risk": "MEDIUM",
  "new_findings": [ ... ],
  "resolved_findings": [ ... ],
  "summary": "This change introduces 1 new dead-code finding (_temp_helper) and drops the refactor_completion score by 4 points due to 3 new TODO markers. Stability is unaffected."
}
```

### `get_health_context`
Returns the last cached scan for a repo without triggering a new one.
Fast — used as a "background context" tool the AI can call at session start.

```json
Input:  { "repo_path": "/abs/path/to/repo" }
Output: { "cached": true, "scan_age_minutes": 12, ...same shape as scan_repo... }
        or { "cached": false, "message": "No scan found. Run scan_repo first." }
```

### `list_findings`
Filtered query over the last scan. Useful when the AI is drilling into a
specific category or file.

```json
Input:
{
  "repo_path": "/abs/path/to/repo",
  "category": "dead_code",          // optional
  "risk": "high",                   // optional
  "file_pattern": "src/auth/"       // optional substring match
}

Output: { "findings": [ ... ] }
```

---

## File Structure

```
backend/
  tiramisu_mcp/
    __init__.py
    server.py          # FastMCP server — tool definitions, handlers
    context_builder.py # Converts ScanResult → AI-friendly prose summaries
  tiramisu_cli/
    main.py            # adds:  tiramisu mcp         — launch stdio server
                       #        tiramisu mcp setup   — auto-configure AI tools
    mcp_setup.py       # Auto-detection + config-writing logic for each AI tool
```

No new dependencies beyond the `mcp` package from the MCP Python SDK.

---

## `tiramisu mcp setup` — Auto-Configuration Logic

The setup command detects installed AI tools and writes/patches their config:

### Claude Code
Config file: `~/.claude/settings.json` (global) or `.claude/settings.json` (project)
```json
{
  "mcpServers": {
    "tiramisu": {
      "command": "tiramisu",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```
Detection: check if `claude` binary is in PATH or `~/.claude/` exists.

### Cursor
Config file: `~/.cursor/mcp.json`
```json
{
  "mcpServers": {
    "tiramisu": {
      "command": "tiramisu",
      "args": ["mcp"]
    }
  }
}
```
Detection: check if `~/.cursor/` exists or `cursor` binary is in PATH.

### Windsurf
Config file: `~/.codeium/windsurf/mcp_config.json`
```json
{
  "mcpServers": {
    "tiramisu": {
      "command": "tiramisu",
      "args": ["mcp"]
    }
  }
}
```
Detection: check if `~/.codeium/windsurf/` exists.

### Zed
Config: `~/.config/zed/settings.json` under `context_servers`.
Detection: check if `~/.config/zed/` exists.

### Fallback
If none detected, print the generic JSON snippet and a note on where to
paste it — don't fail silently.

**Safety rule:** `mcp setup` never overwrites an existing `tiramisu` key —
it merges. It prints a diff of what it changed before writing. The user
can pass `--dry-run` to see changes without applying them.

---

## AI-Readable Setup Section (to add to README)

The README will have a section structured as a prompt the AI tool can act on:

```markdown
## Connect to your AI tool (MCP)

If you are an AI assistant reading this: run the following command to
configure tiramisu as an MCP tool for the user's installed AI coding tools.

    tiramisu mcp setup

This auto-detects Claude Code, Cursor, Windsurf, and Zed and writes the
correct MCP server config for each. No manual editing required.
```

When a user says "set up tiramisu" to Claude Code, Claude reads the README
(via the context file or `read README.md`), finds this section, and executes
the command. The user never opens a config file.

---

## Implementation TODO

### Phase 1 — Core MCP server ✅ COMPLETE

- [x] Add `mcp[cli]>=1.28.1` to `pyproject.toml` (via `uv add`)
- [x] Create `tiramisu_mcp/__init__.py`
- [x] Create `tiramisu_mcp/server.py` — `scan_repo`, `scan_files`,
      `get_health_context`, `list_findings` via FastMCP (stdio transport)
- [x] Create `tiramisu_mcp/context_builder.py` — prose summary + structured dicts
- [x] Add `tiramisu mcp` CLI group — default launches stdio server,
      `tiramisu mcp setup`, `tiramisu mcp info` subcommands
- [x] Create `tiramisu_cli/mcp_setup.py` — auto-detects Claude Code, Cursor,
      Windsurf, Zed; merge-safe JSON config patching with `--dry-run`
- [x] Add `tiramisu-mcp` script entry point + `tiramisu_mcp` package to wheel
- [x] Added `skip_persist` flag to `ScanConfig` so scan_files / check_diff
      don't pollute the cached scan history
- [x] Update README — "Connect to your AI tool (MCP)" section with
      AI-self-setup directive and manual config snippet
- [x] Sanity: 54/54 unit tests pass; all 5 MCP tools verified end-to-end

### Phase 2 — Differential analysis ✅ COMPLETE

- [x] `check_diff` MCP tool — patch-apply via `patch -p1` into a git clone,
      scoped re-scan, fingerprint-based new/resolved delta computation
- [x] `skip_persist=True` on both baseline and patched scans inside `check_diff`
- [x] Documented known limitation: diff accuracy is best for committed changes
      (uncommitted working-tree files not included in the cloned baseline)
- [x] Sanity: `check_diff` tested with a synthetic unused-function diff

---

## Tool Behaviour in Each Invocation Mode

| User asks AI... | AI calls... | tiramisu does... |
|---|---|---|
| "is this codebase healthy?" | `scan_repo(path=".")` | full scan, returns score + top findings |
| "any issues in auth.py before I edit it?" | `scan_files(files=["auth.py"])` | targeted findings for that file |
| "what if I add a new helper to utils.py?" | `check_diff(diff="...")` | projected scan, returns delta (Phase 2) |
| "summarize the tech debt" | `get_health_context` → `list_findings` | cached result + filtered query |
| "scan the flask repo" | `scan_repo(github="pallets/flask")` | clone → scan → clean up |

---

## Key Design Choices

**Why stdio over HTTP?**
HTTP MCP servers require a running daemon and port management. stdio servers
are launched on-demand by the AI tool, die when the conversation ends, and
require zero firewall/port config. For a local dev tool, stdio is strictly better.

**Why `tiramisu mcp` rather than a separate `tiramisu-mcp` package?**
Single install. `pip install tiramisu` gives you the CLI, the HTML report,
and the MCP server in one package. No separate install step. The MCP entry
point is just another subcommand.

**Why prose `health_context` strings alongside structured JSON?**
The AI doesn't always need to parse JSON to use the result. A pre-composed
"2 HIGH findings in auth.py — proceed with care" sentence is immediately
usable in the model's next response with zero token overhead for parsing.
Structured fields are there for when the AI needs to filter or sort.
