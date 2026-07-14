# tiramisu × AI Coding Tools — Integration Options

The core problem: an AI coding assistant (Claude Code, Cursor, Copilot, Aider, etc.)
needs to know the health of the codebase it's about to modify — not after the fact,
but before or during the edit. Tiramisu already produces exactly that signal.
The question is: what is the cleanest way to connect them?

Three invocation modes must be handled:

| Mode | What the AI has | What tiramisu should return |
|---|---|---|
| **No context** | Just a question ("is auth risky to touch?") | Full scan summary + risk map |
| **Partial context** | A file, a diff, a changed module | Targeted findings for those paths |
| **Full context** | Entire file tree or a proposed edit/diff | Impact prediction, regression smell |

---

## Option A — MCP Server (Model Context Protocol)

**How it works:** tiramisu runs as an MCP tool server. Any MCP-compatible client
(Claude Code, Cursor with MCP support, custom agents) can call named tools like
`tiramisu_scan`, `tiramisu_query_file`, `tiramisu_impact_check`.

**What the AI sees:**
```json
{
  "tool": "tiramisu_impact_check",
  "input": { "diff": "--- a/auth.py\n+++ b/auth.py\n..." }
}
→ { "risk": "HIGH", "findings": [...], "score_delta": -12 }
```

**Covers which modes:** All three. The AI decides which tool to call based on context.

**Pros:**
- Standardized protocol — zero per-tool glue code once implemented
- Claude Code supports MCP natively today
- Cursor has MCP support in recent releases
- Streaming and structured output are first-class
- Single implementation serves all MCP-compatible clients

**Cons:**
- Requires the MCP server to be running (daemon or on-demand via `uvx`)
- The AI must decide to call tiramisu — it won't happen automatically unless
  system-prompted or hooked

**Implementation effort:** Medium. FastAPI + `mcp` Python library.
The existing FastAPI server is nearly there; MCP adds a tool manifest on top.

---

## Option B — Context Snapshot File (`.tiramisu/context.json`)

**How it works:** Running `tiramisu snapshot` writes a structured JSON file to the
repo root at `.tiramisu/context.json`. AI tools include it in their context window
via `.cursorrules`, `CLAUDE.md`, or similar per-tool config files.

```json
{
  "health_score": 76.4,
  "risk_areas": ["auth/", "payments/", "src/api/legacy.py"],
  "top_findings": [
    { "category": "dead_code", "file": "src/utils/crypto.py", "risk": "HIGH" }
  ],
  "git_metrics": { "stability_index": 42.0, "friction_index": 68.1 },
  "generated_at": "2026-07-14T10:32:00Z"
}
```

The AI coding tool reads this file exactly once per session (or caches it) and
uses it as background context. When the user asks "is it safe to refactor auth?",
the AI already has the risk map.

**Covers which modes:** No-context and partial-context. Not hypothetical.

**Pros:**
- Works with every AI tool today — no protocol, no server, no plugin
- Zero runtime dependency; the snapshot ages gracefully
- Can be committed to the repo so the whole team has the same health picture
- Claude Code picks it up via `CLAUDE.md @.tiramisu/context.json` in one line

**Cons:**
- Static — stale the moment code changes
- Requires discipline to re-run `tiramisu snapshot` regularly (or automate it as a
  pre-commit hook or CI step)
- No "what if" capability

**Implementation effort:** Very low. Add a `snapshot` sub-command that writes
the JSON; the existing `ScanResult` serialization is almost there.

---

## Option C — Pre/Post Edit Hook (Subprocess / Stdio)

**How it works:** The AI tool's hook system (Claude Code hooks, Cursor rules,
Aider `--watch` callbacks) shells out to tiramisu before or after each edit.
tiramisu outputs structured JSON; the hook injects findings back into context.

```
# Claude Code settings.json hook example
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Edit|Write",
      "command": "tiramisu scan --changed --format json --headless"
    }]
  }
}
```

Tiramisu scans the changed files, emits JSON to stdout, and the hook framework
feeds that back to the model as a system observation.

**Covers which modes:** Partial context (changed files). Can approximate hypothetical
if run on a staged patch.

**Pros:**
- Works with Claude Code today without any new tiramisu code
- Automatic — the AI sees health context on every edit, not just when asked
- `--changed` mode is already implemented; output is already JSON

**Cons:**
- Adds latency to every edit cycle (even if fast engines only: ~2–5s)
- The AI tool's hook framework must support stdout → context injection
  (Claude Code does; Cursor's is more limited today)
- Not useful for "what if I implement feature X" questions — only reacts to
  actual edits

**Implementation effort:** Zero for tiramisu. Config-only on the AI tool side.
Add a `tiramisu hook-config` command to generate the config snippet as a nice-to-have.

---

## Option D — Differential / Hypothetical Analysis

**How it works:** A new endpoint `POST /analyze/diff` accepts a unified diff or
a partial file tree. Tiramisu applies the patch to a temporary copy of the repo,
runs its engines on the projected state, and returns the delta.

```
POST /analyze/diff
{
  "repo_path": "/home/user/myrepo",
  "diff": "--- a/auth.py\n+++ b/auth.py\n@@ -14,6 +14,8 @@\n+ def _unsafe_helper():\n+     pass"
}

→ {
  "score_before": 84.2,
  "score_after": 79.1,
  "score_delta": -5.1,
  "new_findings": [{ "category": "dead_code", "title": "_unsafe_helper unused" }],
  "resolved_findings": [],
  "regression_risk": "MEDIUM"
}
```

The AI tool (or a wrapper around it) calls this before committing a proposed change.
It's the only option that fully covers the **hypothetical mode** ("what would happen
if I add feature A?").

**Covers which modes:** All three, but shines for hypothetical.

**Pros:**
- Uniquely powerful — no linter or SAST tool offers projected-state diff analysis
- Works as an API the AI agent can call as a tool (function calling / MCP tool)
- Makes tiramisu a genuine co-pilot rather than a post-hoc reporter

**Cons:**
- Hardest to implement: requires a patch-apply + isolated scan pipeline
- For large repos, running a full scan on every proposed diff is expensive
  (mitigated by running only fast engines + scoping to changed files)
- Needs the tiramisu API server to be running (or a cloud endpoint)

**Implementation effort:** High. New `POST /analyze/diff` route; patch-apply logic;
scoped re-scan; delta computation. ~2–3 days of backend work.

---

## Option E — LSP Diagnostics Server

**How it works:** tiramisu runs as a Language Server Protocol server. Every editor
with LSP support (VS Code, Cursor, Neovim, JetBrains) sees tiramisu findings as
inline diagnostics — yellow/red squiggles — alongside compiler errors and lint warnings.

AI tools that pull diagnostics into their context (Cursor, Copilot with Diagnostics
access) automatically see tiramisu findings when the user asks about a file.

**Covers which modes:** No-context (editor already open) and partial-context
(current file diagnostics). Not hypothetical.

**Pros:**
- Deep editor integration — findings appear inline without any prompting
- AI tools that read diagnostics get tiramisu data for free
- Familiar UX — same as eslint / pyright

**Cons:**
- LSP is a significant protocol to implement correctly
- Background LSP scanning must be incremental and very fast to avoid blocking the editor
- tiramisu's strengths (cross-file analysis, git history) don't map well to single-file
  LSP requests; shallow per-file mode would be needed
- Won't help with "what if" questions unless combined with another option

**Implementation effort:** High. LSP server, `textDocument/publishDiagnostics`,
incremental scan trigger on `didSave`. ~1 week.

---

## Option F — OpenAI-Compatible Tool Definition (Function Calling)

**How it works:** Expose tiramisu's capabilities as a JSON tool schema compatible
with OpenAI function calling / Claude tool use / Gemini tools. Any AI that supports
tool calling can invoke tiramisu without any protocol negotiation.

```json
{
  "name": "tiramisu_check",
  "description": "Scan a file path or diff for health issues, dead code, regressions",
  "parameters": {
    "type": "object",
    "properties": {
      "path": { "type": "string" },
      "diff": { "type": "string" },
      "engines": { "type": "array", "items": { "type": "string" } }
    }
  }
}
```

This is essentially MCP (Option A) but at the JSON schema level, without requiring
the MCP protocol layer. Works in custom agents, LangChain/LlamaIndex workflows,
and any LLM with function calling.

**Covers which modes:** All three.

**Pros:**
- Works across every major LLM provider (Claude, GPT-4, Gemini, etc.)
- No proprietary protocol — just JSON
- Easy to embed in custom RAG/agent pipelines

**Cons:**
- Doesn't auto-integrate into Cursor/Copilot — only useful in agent/API contexts
- Overlaps heavily with MCP (Option A) which is more complete for IDE-native tools

**Implementation effort:** Low. The tool schema is a JSON document; tiramisu
already has the API endpoints. This is mostly documentation + a `/tools` endpoint.

---

## Recommendation

These options aren't mutually exclusive, but they have a natural implementation order
based on impact vs effort:

| Priority | Option | Why |
|---|---|---|
| **1 — Ship now** | **C: Pre/Post Edit Hook** | Zero tiramisu changes. Immediate value in Claude Code and Cursor. Document a 5-line config snippet. |
| **2 — Ship soon** | **B: Context Snapshot File** | One new sub-command. Works with every tool without any integration. Great for team-shared health baseline. |
| **3 — Next sprint** | **A: MCP Server** | Highest long-term value. One implementation serves Claude Code, Cursor, and any future MCP client. Builds on existing FastAPI server. |
| **4 — Phase 2** | **D: Differential Analysis** | Unique capability, strongest "what if" story. Worth building once MCP is in place (it becomes an MCP tool). |
| **Skip for now** | E: LSP | High effort, LSP's single-file model conflicts with tiramisu's cross-file strengths. |
| **Skip for now** | F: Function Calling schema | Fully covered by MCP once that's built. |

### Suggested sequencing

```
Week 1:  C (hook config snippet + docs) — zero code
Week 1:  B (tiramisu snapshot command) — ~1 day
Week 2–3: A (MCP server wrapping existing FastAPI routes) — ~3 days
Month 2:  D (diff analysis endpoint, exposed as MCP tool) — ~3–4 days
```

The north-star experience:

> User in Cursor: "What happens if I split the auth module into two?"
> → Cursor invokes tiramisu MCP tool with the proposed diff
> → tiramisu scans the projected state in 4 seconds
> → Returns: "score drops from 84 → 77, 3 new dead-code findings in auth_helpers.py,
>   refactor completion rate drops — you have 2 incomplete TODOs that reference the
>   old module name"
> → Cursor surfaces this inline before the edit is committed
