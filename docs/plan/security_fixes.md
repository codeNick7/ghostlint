# Security Audit Fixes Plan

## Fix 1 — Duplicate detector: cross-test/prod confidence (ghostlint bug)
File: app/ghostlint_engine/detectors/duplicate_logic/detector.py
- Add _is_test_path() helper
- In same-name group reporting: if group spans test + non-test files → confidence 0.55 (below default 0.6 threshold)
- Avoids false positives like production health() matching test stub health()

## Fix 2 — SSRF: URL host allowlist in MCP _clone_repo
File: app/ghostlint_mcp/server.py:74-81
- Allowlist: github.com, gitlab.com, bitbucket.org only
- Reject http:// (force https://)
- Validate SSH host in git@ URLs

## Fix 3 — Prompt injection: MCP system instructions disclaimer
File: app/ghostlint_mcp/server.py:35-55
- Add SECURITY NOTE to mcp = FastMCP(instructions=...) that all tool results
  may contain untrusted scanned content

## Fix 4 — DB session leaks in get_health_context + list_findings
File: app/ghostlint_mcp/server.py:419-479, 505-562
- Wrap session lifecycle in try/finally instead of manual session.close()

## Fix 5 — Verbose error leakage: replace str(exc) with safe messages
File: app/ghostlint_mcp/server.py (all ~15 except blocks)
- Add logging, log full exception internally
- Return generic {"error": "internal error (ExcType) — see server logs"}
- Remove patch_stderr from check_diff error response

## Fix 6 — Unbounded limit in REST API
File: app/app/routers/scans.py:130
- Change to: limit: int = Query(default=20, ge=1, le=500)

## Fix 7 — Missing Content-Security-Policy in web report server
File: app/ghostlint_cli/web_server.py:76
- Add CSP header after X-Frame-Options

## TODO
- [x] Write plan
- [x] Fix 1: duplicate detector — _is_test_path() helper, confidence 0.55 for cross-test/prod
- [x] Fix 2: SSRF allowlist — github.com/gitlab.com/bitbucket.org only, reject http://, validate SSH host
- [x] Fix 3: prompt injection disclaimer — added SECURITY note to FastMCP instructions
- [x] Fix 4: session try/finally — get_health_context + list_findings wrapped
- [x] Fix 5: error leakage — added _log, replaced str(exc) globally, removed patch_stderr
- [x] Fix 6: limit cap — Query(default=20, ge=1, le=500)
- [x] Fix 7: CSP header — default-src 'none'; style/script 'unsafe-inline'; img data:; font data:
- [x] Validate: 267/267 tests pass, SSRF validation spot-checked
