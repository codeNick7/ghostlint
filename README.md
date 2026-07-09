# tiramasu

**Repository Health Intelligence** — detect dead code, duplicate logic, architectural drift, and more. Tiramasu sits above linters and SAST tools; it understands _intent_ and _structure_, not just syntax.

```
tiramasu scan ~/myrepo
```

```
 ╭─ tiramasu scan results ──────────────────────────────────────────────────────╮
 │  Health Score  94 / 100      Files  342    Symbols  1 847    Findings  12    │
 ╰──────────────────────────────────────────────────────────────────────────────╯

  DEAD CODE          _internal_helper     src/utils/auth.py:214       conf 82%
  DUPLICATE LOGIC    parse_date (×3)      src/api/orders.py:58        conf 75%
  INCOMPLETE REFACTOR  get_ vs fetch_     src/services/user.py:103    conf 80%
```

---

## Installation

**Requires Python 3.12+.**

```bash
pip install tiramasu
```

Or with `uv`:

```bash
uv tool install tiramasu
```

---

## Quickstart

```bash
# Scan the current directory (all engines)
tiramasu scan

# Scan a specific repo
tiramasu scan ~/workspace/myproject

# Run only fast engines — ideal as a pre-commit hook
tiramasu scan --quick

# Run a single engine
tiramasu scan -e dead_code

# Run two engines
tiramasu scan -e dead_code -e duplicate_logic

# Scan only files changed since last commit (great for CI diff mode)
tiramasu scan --changed

# JSON output for CI pipelines
tiramasu scan --format json

# Adjust confidence threshold (default 0.6)
tiramasu scan --min-confidence 0.75
```

---

## Detection Engines

| Engine | Speed | What it finds |
|---|---|---|
| `dead_code` | fast | Unused functions, methods, and classes with zero callers |
| `duplicate_logic` | slow | Structurally identical functions (AST fingerprint match) |
| `refactor` | medium | Coexisting old/new APIs and abandoned migration leftovers |
| `arch_drift` | medium | Boundary violations, cyclic dependencies, layer leakage |
| `config_health` | fast | Conflicts and drift across `.env` files |
| `doc_health` | medium | Stale TODO/FIXME comments and empty docstrings |
| `dependency_health` | fast | Unused, duplicate, and undeclared packages |
| `test_health` | medium | Orphan tests calling functions that no longer exist |
| `naming` | slow | Near-duplicate class names, inconsistent DTOs/models |

List engines:

```bash
tiramasu engines
```

See detailed guides for each engine under [`docs/engines/`](docs/engines/).

---

## Pre-Commit Hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: tiramasu
        name: tiramasu health check
        entry: tiramasu scan --quick --format json
        language: system
        pass_filenames: false
```

Or with the `--changed` flag to only check modified files:

```yaml
      - id: tiramasu-changed
        name: tiramasu (changed files)
        entry: tiramasu scan --changed --format json
        language: system
        pass_filenames: false
```

---

## GitHub Action

```yaml
- name: Repository Health Check
  uses: ./github-action
  with:
    engines: "dead_code,duplicate_logic,dependency_health"
    min_confidence: "0.7"
    fail_on_score_below: "80"
    format: "json"
```

**Outputs:** `health_score`, `findings_count`, `report_path`

The action writes a summary to the GitHub Actions step summary page.

---

## Dashboard (Next.js)

The `frontend/` directory contains a Next.js 14 dashboard that connects to the tiramasu FastAPI server.

```bash
# Start the API server
cd backend && uvicorn app.main:app --reload

# Start the dashboard
cd frontend && npm install && npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## API Server

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

The API key is auto-generated on first run and stored at `~/.tiramasu/api_key`. Pass it as the `X-API-Key` header.

```bash
API_KEY=$(cat ~/.tiramasu/api_key)

# Trigger a scan
curl -X POST http://localhost:8000/scans \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/repo", "scan_mode": "full"}'

# List recent scans
curl http://localhost:8000/scans -H "X-API-Key: $API_KEY"
```

Override the key with the `TIRAMASU_API_KEY` environment variable.  
Restrict which paths can be scanned with `TIRAMASU_ALLOWED_ROOTS` (colon-separated paths, default: `$HOME`).

---

## Data Storage

Scan history is stored in SQLite at `~/.tiramasu/tiramasu.db` (created automatically).  
View the last scan:

```bash
tiramasu report
```

Override the database path:

```bash
TIRAMASU_DB_PATH=/tmp/tiramasu.db tiramasu scan .
```

---

## `tiramasu.yml` Configuration

Place a `tiramasu.yml` at the repo root to commit scan configuration:

```yaml
engines:
  - dead_code
  - duplicate_logic
  - dependency_health

min_confidence: 0.7
exclude_dirs:
  - vendor
  - generated
```

---

## Development

```bash
git clone https://github.com/yourorg/tiramasu
cd tiramasu/backend
uv sync
.venv/bin/python -m pytest tests/unit/ -v
```

---

## Architecture

```
backend/
  tiramasu_engine/          # Core analysis library
    ast_engine/             # Tree-sitter AST parsers (Python + JS/TS)
    graph/                  # NetworkX symbol graph + analysis context
    detectors/              # 9 detection engines + registry
    db/                     # SQLite persistence (SQLAlchemy)
    indexer.py              # File discovery + language detection
    scanner.py              # Orchestration + two-pass symbol resolution
    health_score.py         # Scoring algorithm
  tiramasu_cli/             # Typer CLI (scan, report, engines commands)
  app/                      # FastAPI server + /scans endpoints

frontend/                   # Next.js 14 dashboard
github-action/              # Docker-based GitHub Action
```

---

## License

MIT
