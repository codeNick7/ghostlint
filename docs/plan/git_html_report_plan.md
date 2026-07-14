# Plan: GitHub Repo Scanning + HTML Report + Git Metrics

## Goal
- Accept a GitHub public repo URL as CLI input, clone it, scan it
- Compute 4 new git-history-based metrics
- Show summary in terminal after scan
- Generate a rich HTML report
- Serve it via a temp HTTP server and open in default browser (unless `--headless`)

---

## New Files to Create

1. `tiramisu_engine/git_metrics.py`
   — Compute 4 new git-history metrics from a local git repo

2. `tiramisu_cli/html_report.py`
   — Generate a self-contained HTML report from ScanResult + GitMetrics

3. `tiramisu_cli/web_server.py`
   — Serve a single HTML file on a random port, open browser

---

## Changes to Existing Files

- `tiramisu_engine/models/findings.py`
  — Add `GitMetrics` dataclass

- `tiramisu_engine/scanner.py`
  — Accept optional `github_url` param; run git metrics when repo is git

- `tiramisu_cli/main.py`
  — Add `--github` option (URL or owner/repo shorthand)
  — Add `--headless` flag
  — After scan: show terminal summary, generate HTML, serve + open browser

---

## New Git Metrics

### 1. Repository Stability Index (0–100)
- Measure: % of "core" files (models, schemas, routes, interfaces) that were
  NOT touched in the last N commits (default 30).
- High stability = good. Low stability = architecture under churn.
- Needs: git log per-file, or `git log --name-only` over last N commits.

### 2. Maintenance Velocity (ratio)
- Measure: commits in last 90d that fix things (fix, close, resolve, patch
  keywords in message) vs total commits.
- > 0.4 → good cadence. < 0.1 → stagnant or purely additive.
- Needs: git log --oneline, parse commit messages.

### 3. Refactor Completion Rate (0–100 %)
- Measure: grep for TODO/FIXME/HACK/deprecated markers now vs. N commits ago.
  If the count is decreasing, rate is high.
- Requires at least 2 reference points in history.
- Needs: git show HEAD~N:file or `git log -p` for marker lines.

### 4. Repository Friction Index (0–100, lower is better)
- Composite of:
  a. Average file churn (commits/file across repo)
  b. % of files with >3 authors (ownership fragmentation)
  c. % of files >500 lines (complexity proxy)
- Normalized to 0–100 where 0 = no friction.

---

## HTML Report Layout

```
┌─────────────────────────────────────┐
│  tiramisu  Repository Health Report  │
│  {repo_name}  ·  {scan_date}        │
├─────────────────────────────────────┤
│  Overall Health Score  [gauge]      │
│  Category Breakdown   [bar chart]   │
├─────────────────────────────────────┤
│  Git Intelligence Metrics            │
│  Stability Index  |  Maint Velocity │
│  Refactor Completion | Friction Idx │
├─────────────────────────────────────┤
│  Findings Table  (filterable)       │
├─────────────────────────────────────┤
│  Recommendations                    │
└─────────────────────────────────────┘
```

Self-contained HTML: Chart.js via CDN, inline CSS, no external assets.

---

## CLI Interface (after changes)

```
# Scan local repo, open HTML report in browser
tiramisu scan /path/to/repo

# Scan GitHub public repo, open HTML report
tiramisu scan --github https://github.com/owner/repo

# Shorthand
tiramisu scan --github owner/repo

# Scan without opening browser (CI mode)
tiramisu scan --github owner/repo --headless

# Headless + JSON output (pure CI)
tiramisu scan --format json --headless
```

---

## TODO

- [x] Write plan
- [x] Create `tiramisu_engine/git_metrics.py`
- [x] Add `GitMetrics` dataclass to `findings.py`
- [x] Create `tiramisu_cli/html_report.py` (SRI hash on Chart.js CDN)
- [x] Create `tiramisu_cli/web_server.py`
- [x] Update `tiramisu_cli/main.py` — add `--github`, `--headless`
- [x] Update `tiramisu_engine/scanner.py` — wire git_metrics into ScanResult
- [x] Validate: all modules import OK, 54/54 unit tests pass
