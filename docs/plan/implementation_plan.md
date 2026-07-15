# Repository Health Intelligence Platform — Full Implementation Plan

**Version**: 1.1  
**Date**: 2026-07-09  
**Status**: Phase 1 Active

### Resolved Decisions (2026-07-09)
| # | Decision | Resolution |
|---|----------|-----------|
| 1 | CLI / product name | `ghostlint` |
| 2 | Monorepo tooling | uv (Python) + pnpm (Node) — no Nx |
| 3 | Embedding model | Local `all-MiniLM-L6-v2` as default; OpenAI optional for higher accuracy |
| 4 | V1 web auth | No auth in V1 — local-only dashboard; GitHub OAuth deferred to V2 |
| 5 | Default LLM | **GPT-4o-mini** (OpenAI) for V1; migrate to Claude Haiku 4.5 in V2 |

---

## 1. Product Summary

Repository Health Intelligence (working name: **ghostlint**) is an AI-assisted engineering platform that continuously scans software repositories to surface dead code, duplicate logic, incomplete refactors, architectural drift, configuration inconsistencies, and other maintainability degradation.

It is positioned **above** linters, security scanners, and SAST tools — not a replacement for any of them. Its output is actionable cleanup tasks, not raw warnings.

Target users: Staff/Principal Engineers, Architects, Platform Teams, CTOs.

---

## 2. Tech Stack Decision

### 2.1 Core Analysis Engine (Python)

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.12+ | Ecosystem dominance for AST, NLP, AI libs |
| AST Parsing | **tree-sitter** + **tree-sitter-languages** | `tree-sitter-languages` bundles pre-compiled grammars for 29+ languages (Python, TS, JS, Go, Java, C#, Rust) — no grammar compilation needed; each grammar teaches tree-sitter the language constructs (function defs, class defs, imports, scope) for accurate symbol extraction |
| Graph Engine | **NetworkX** | Industry standard for call/dependency graphs; pure Python, easy to extend |
| Git History | **GitPython** | Full git object access, blame, rename detection, commit walks |
| Semantic Embeddings | **sentence-transformers** `all-MiniLM-L6-v2` (local default) | Runs on-device; no code leaves machine; OpenAI `text-embedding-3-small` available as optional upgrade |
| LLM Reasoning | **LiteLLM** + **GPT-4o-mini** (V1) | LiteLLM abstracts provider; default model GPT-4o-mini (user has OpenAI key); migrate to Claude Haiku 4.5 in V2 |
| Async Task Queue | **Celery + Redis** | Standard Python async job processing; needed for long-running full scans |
| CLI | **Typer** + **Rich** | Typer = Click + type hints; Rich for beautiful terminal output |

### 2.2 Backend API

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | **FastAPI** | Already in PRD; async-native, automatic OpenAPI docs, Pydantic validation |
| ORM | **SQLAlchemy 2.0** (async) + **Alembic** | Async-compatible, migrations via Alembic |
| Task Queue | **Celery** with **Redis** broker | Offload scan jobs off the API request cycle |
| Auth (V1) | **API key** auth | Simple, CI/CD-friendly; JWT/OAuth in V2 |

### 2.3 Storage

Two-tier strategy: CLI runs with zero external dependencies; the server-mode API uses a proper DB for multi-user access.

**CLI / Local mode (no server required)**

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Relational | **SQLite** via SQLAlchemy | Zero setup; single file at `~/.ghostlint/ghostlint.db`; stores scan results, findings, health history |
| Vector Index | **ChromaDB** (local persistent) | Pure Python; persists to `~/.ghostlint/vectors/`; no server process; used for duplicate logic / semantic similarity in Phase 2 |

**API / Server mode (Phase 3 — web dashboard)**

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Primary DB | **PostgreSQL 16** + pgvector | Multi-user, concurrent; pgvector replaces ChromaDB for server deployments |
| Cache / Queue | **Redis 7** | Celery broker + result backend for async scan jobs |

SQLAlchemy is used in both tiers — only the connection string changes (`sqlite:///...` vs `postgresql://...`), so analysis engine code is identical.

### 2.4 Frontend

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | **Next.js 14** (App Router) | In PRD; React Server Components for fast dashboard load |
| Styling | **Tailwind CSS** + **shadcn/ui** | Consistent, accessible components; rapid iteration |
| Charts | **Recharts** | Lightweight, React-native charting for health trends |
| State | **TanStack Query (React Query)** | Server state management with caching and polling |
| Auth (V1) | **NextAuth.js** | GitHub OAuth for initial users |

### 2.5 Deployment

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Containers | **Docker** + **Docker Compose** (local) | Reproducible environments; dev parity |
| Frontend Hosting | **Vercel** | In PRD; zero-config Next.js |
| Backend Hosting | **Railway / Fly.io** | Simple Dockerized FastAPI + Celery deployment |
| CI/CD | **GitHub Actions** | Native integration; also ships the GitHub Action product itself |
| GitHub Action | **Docker-based Action** | Reproducible, versioned, no runner dependency |

### 2.6 Language Support Roadmap

| Priority | Languages |
|----------|-----------|
| V1 | Python, TypeScript/JavaScript |
| V2 | Go, Java |
| V3 | C#, Rust |

---

## 3. System Architecture

```
Repository (local path or git remote)
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│                   ANALYSIS ENGINE (Python package)       │
│                                                         │
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ File Indexer  │  │  AST Engine  │  │ Git Analyzer│  │
│  │ (walk + hash) │  │ (tree-sitter)│  │ (GitPython) │  │
│  └───────┬───────┘  └──────┬───────┘  └──────┬──────┘  │
│          │                 │                  │         │
│          └─────────────────▼──────────────────┘         │
│                            │                            │
│               ┌────────────▼───────────┐                │
│               │    Symbol Graph         │                │
│               │    + Dependency Graph   │                │
│               │    (NetworkX)           │                │
│               └────────────┬───────────┘                │
│                            │                            │
│               ┌────────────▼───────────┐                │
│               │  Semantic Indexer       │                │
│               │  (embeddings → pgvector)│                │
│               └────────────┬───────────┘                │
│                            │                            │
│          ┌─────────────────▼──────────────────┐         │
│          │         DETECTION ENGINES           │         │
│          │  dead_code | duplicates | refactor  │         │
│          │  arch_drift | config | docs | deps  │         │
│          │  tests | naming                     │         │
│          └─────────────────┬──────────────────┘         │
│                            │                            │
│               ┌────────────▼───────────┐                │
│               │   LLM Reasoning Layer   │                │
│               │   (LiteLLM)             │                │
│               └────────────┬───────────┘                │
│                            │                            │
│               ┌────────────▼───────────┐                │
│               │  Recommendation Engine  │                │
│               │  (scoring + priority)   │                │
│               └────────────┬───────────┘                │
└────────────────────────────┼────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         ┌────▼────┐   ┌─────▼──────┐  ┌───▼────────────┐
         │   CLI   │   │ FastAPI    │  │ GitHub Action  │
         │(Typer)  │   │ Backend    │  │ (Docker)       │
         └─────────┘   └─────┬──────┘  └────────────────┘
                             │
                    ┌────────▼────────┐
                    │ PostgreSQL       │
                    │ + pgvector       │
                    │ + Redis          │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Next.js Frontend │
                    │ (Vercel)         │
                    └─────────────────┘
```

---

## 4. Repository Structure

```
ghostlint/
├── packages/
│   └── analysis-engine/          # Core Python package (pip-installable)
│       ├── ghostlint/
│       │   ├── __init__.py
│       │   ├── indexer/          # File indexer
│       │   ├── ast_engine/       # Tree-sitter wrappers per language
│       │   ├── graph/            # Symbol graph + dependency graph (NetworkX)
│       │   ├── git_analyzer/     # Git history + blame + renames
│       │   ├── semantic/         # Embeddings generation
│       │   ├── detectors/        # All detection engines
│       │   │   ├── dead_code.py
│       │   │   ├── duplicates.py
│       │   │   ├── refactor.py
│       │   │   ├── arch_drift.py
│       │   │   ├── config.py
│       │   │   ├── docs.py
│       │   │   ├── dependencies.py
│       │   │   ├── tests.py
│       │   │   └── naming.py
│       │   ├── llm/              # LiteLLM wrapper + prompt templates
│       │   ├── recommendations/  # Scoring + recommendation generation
│       │   └── models/           # Pydantic models (Finding, Recommendation, etc.)
│       ├── pyproject.toml
│       └── tests/
│
├── apps/
│   ├── api/                      # FastAPI backend
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── routers/
│   │   │   │   ├── scans.py
│   │   │   │   ├── reports.py
│   │   │   │   ├── findings.py
│   │   │   │   └── health.py
│   │   │   ├── tasks/            # Celery tasks
│   │   │   ├── db/               # SQLAlchemy models + Alembic migrations
│   │   │   └── config.py
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   ├── cli/                      # CLI package
│   │   ├── ghostlint_cli/
│   │   │   ├── main.py           # Typer app (health scan, report, fix)
│   │   │   ├── output.py         # Rich formatters
│   │   │   └── config.py         # health.yml loader
│   │   └── pyproject.toml
│   │
│   └── web/                      # Next.js frontend
│       ├── app/
│       │   ├── dashboard/
│       │   ├── reports/
│       │   ├── findings/
│       │   └── api/              # Next.js API routes (thin proxy)
│       ├── components/
│       ├── package.json
│       └── Dockerfile
│
├── github-action/                # GitHub Action definition
│   ├── action.yml
│   └── Dockerfile
│
├── docs/
│   ├── plan/                     # This folder
│   └── *.md
│
├── docker-compose.yml
├── docker-compose.dev.yml
└── .github/
    └── workflows/
```

---

## 5. Data Models (Core)

### Finding
```python
class Finding:
    id: UUID
    scan_id: UUID
    category: DetectionCategory   # dead_code | duplicate | refactor | ...
    title: str
    description: str
    evidence: list[Evidence]      # file + line references
    files: list[str]
    confidence: float             # 0.0 - 1.0
    risk: RiskLevel               # low | medium | high
    effort: EffortLevel           # minutes | hours | days
    benefit: str
    autofix_available: bool
    llm_explanation: str | None
```

### ScanResult
```python
class ScanResult:
    id: UUID
    repo_path: str
    scan_mode: ScanMode           # full | incremental | pr | commit
    started_at: datetime
    completed_at: datetime
    health_score: HealthScore
    findings: list[Finding]
    recommendations: list[Recommendation]
```

### HealthScore
```python
class HealthScore:
    overall: float                # 0-100
    dead_code: float
    duplicate_logic: float
    refactor_completion: float
    architectural_drift: float
    config_consistency: float
    documentation_freshness: float
    dependency_health: float
    test_health: float
```

---

## 6. Detection Engine Design

Each detector follows the same interface:

```python
class BaseDetector:
    def detect(self, context: AnalysisContext) -> list[Finding]:
        ...
```

`AnalysisContext` contains: symbol graph, dependency graph, git history, file index, embeddings.

### Detection Logic per Engine

| Engine | Primary Signal | LLM Assist |
|--------|---------------|------------|
| Dead Code | Symbol graph — zero callers | Optional: "is this intentionally exported?" |
| Duplicate Logic | AST hash + vector similarity | Required: "are these semantically equivalent?" |
| Refactor Completion | Git history + coexisting old/new APIs | Required: "is the old API still needed?" |
| Architectural Drift | Dependency graph — layer violations | Optional |
| Config Health | File parsing + key comparison | No |
| Doc Health | Embedding distance: comment vs code | Required: "does this comment still describe the code?" |
| Dependency Health | package.json / pyproject.toml + import scan | No |
| Test Health | Symbol graph — test → source coverage | Optional |
| Naming Consistency | Embedding similarity across models/DTOs | Optional |

---

## 7. API Endpoints

```
POST   /api/v1/scans                  # Start a scan (returns scan_id)
GET    /api/v1/scans/{id}             # Scan status + result
GET    /api/v1/scans/{id}/findings    # Paginated findings
GET    /api/v1/scans/{id}/report      # Full health report
GET    /api/v1/scans/{id}/score       # Health score only
POST   /api/v1/scans/{id}/fix         # Apply autofix for a finding (V2)

GET    /api/v1/repos/{repo}/history   # Historical scan scores
GET    /api/v1/repos/{repo}/trend     # Trend data for dashboard
```

---

## 8. CLI Commands

```bash
ghostlint scan                     # Full scan of current directory
ghostlint scan --changed           # Only git-changed files + dependency impact
ghostlint scan --pr <branch>       # PR scan (changed files vs base)
ghostlint scan --full              # Explicit full scan
ghostlint scan --config ghostlint.yml # Custom config

ghostlint report                   # View latest scan report (Rich terminal)
ghostlint report --format json     # JSON output for CI
ghostlint report --format html     # HTML report

ghostlint fix                      # Interactive autofix (V2)
```

---

## 9. `ghostlint.yml` Configuration Schema

```yaml
version: 1

scan:
  scope: full                   # full | src | changed
  exclude:
    - "**/generated/**"
    - "**/vendor/**"
    - "**/migrations/**"
    - "**/__snapshots__/**"
    - "**/dist/**"
    - "**/build/**"

rules:
  dead_code:
    enabled: true
    confidence_threshold: 0.7
  duplicate_logic:
    enabled: true
    similarity_threshold: 0.85
  architectural_drift:
    enabled: true
    severity: warning            # advisory | warning | blocking
  dependency_health:
    enabled: true

thresholds:
  overall_health_min: 70        # Block CI if below this
  blocking_findings_max: 0      # Block on any high-risk finding

llm:
  provider: openai               # openai | anthropic | ollama | none
  model: gpt-4o-mini
  offline: false                 # true = structural analysis only, no LLM
```

---

## 10. Implementation Phases

### Phase 1: Foundation (Weeks 1–5)
**Goal**: Working CLI that produces a health report for Python and TypeScript repos.

**Tasks**:
- [ ] Monorepo scaffold (uv workspaces + pnpm workspaces)
- [ ] `packages/analysis-engine` package setup
- [ ] File Indexer: walk repo, collect files, hashes, language detection
- [ ] AST Engine: tree-sitter for Python + TypeScript
- [ ] Symbol Graph: functions, classes, exports, imports (NetworkX)
- [ ] Dependency Graph: inter-module import resolution
- [ ] Git History Analyzer: commit log, blame, rename detection
- [ ] Dead Code Detector: zero-caller symbols from symbol graph
- [ ] Basic Recommendation Engine: findings → ranked list
- [ ] Health Score Calculator: weighted score per category
- [ ] CLI (`apps/cli`): `health scan` + `health report` with Rich output
- [ ] PostgreSQL schema + Alembic migrations
- [ ] FastAPI backend: `POST /scans`, `GET /scans/{id}`
- [ ] Docker Compose dev setup
- [ ] Unit tests for each analyzer module

**Deliverable**: `health scan` on a local Python or TypeScript repo produces a terminal report with dead code findings and a health score.

---

### Phase 2: Detection Engines + AI Layer (Weeks 6–10)
**Goal**: Full detection suite + LLM reasoning layer.

**Tasks**:
- [ ] Semantic Indexer: generate embeddings (sentence-transformers), store in pgvector
- [ ] Duplicate Logic Detector: AST hash + vector similarity
- [ ] LiteLLM integration: reasoning prompts for duplicate explanation
- [ ] Refactor Completion Detector: git history + coexisting API detection
- [ ] Dependency Health Detector: unused/overlapping packages
- [ ] Configuration Health Detector: .env / docker / k8s comparison
- [ ] Documentation Health Detector: comment vs code drift (embeddings)
- [ ] Test Health Detector: orphan tests + missing coverage after refactor
- [ ] Naming Consistency Detector: duplicate DTOs/models via embeddings
- [ ] Architectural Drift Detector: layer violation rules on dependency graph
- [ ] Feature Flag Detector: stale/unused flags
- [ ] Recommendation Engine v2: confidence + effort + risk scoring
- [ ] Celery + Redis: async scan jobs for large repos
- [ ] `health.yml` config loader
- [ ] `health scan --changed` (incremental mode)
- [ ] Integration tests: end-to-end scan of test repos

**Deliverable**: Full detection suite running locally with LLM reasoning producing actionable explanations.

---

### Phase 3: Frontend + GitHub Integration (Weeks 11–15)
**Goal**: Web dashboard + GitHub Action + PR bot comments.

**Tasks**:
- [ ] Next.js app scaffold (App Router, Tailwind, shadcn/ui)
- [ ] Dashboard: Health Score overview + trend charts (Recharts)
- [ ] Findings browser: filter by category, severity, confidence
- [ ] Report page: full scan report with evidence
- [ ] NextAuth.js: GitHub OAuth
- [ ] GitHub Action: Docker-based action definition
- [ ] GitHub Action: `health scan --pr` mode
- [ ] GitHub bot: PR comment with findings + explanations
- [ ] CI exit codes: advisory / warning / blocking modes
- [ ] Vercel deployment for frontend
- [ ] Backend deployment (Railway or Fly.io)
- [ ] E2E tests (Playwright)

**Deliverable**: V1 complete — CLI + GitHub Action + web dashboard all functional.

---

### Phase 4: V2 Enhancements (Post-V1)
- Autofix PR generation (safe, well-explained cleanup PRs)
- Multi-repository analytics + organization dashboard
- Slack / Teams notifications
- Jira ticket creation from findings
- Architectural trend prediction (ML on health score history)
- Plugin SDK: language plugins + custom rules
- Go, Java language support

---

## 11. Testing Strategy

| Layer | Tool | Coverage Target |
|-------|------|----------------|
| Analysis engine unit tests | pytest | 80%+ per detector |
| API integration tests | pytest + httpx | All endpoints |
| CLI tests | pytest + subprocess | All commands |
| Frontend unit tests | Vitest | Critical components |
| E2E tests | Playwright | Dashboard + scan flow |
| Test repos | Synthetic repos with known issues | Detector validation |

Synthetic test repos (committed under `tests/fixtures/`) will contain intentionally injected dead code, duplicates, and drift for deterministic detector validation.

---

## 12. Security Considerations

- **Local-first**: Analysis engine runs entirely local; no source code leaves the machine by default.
- **LLM privacy**: Only code snippets (not full files) sent to LLM; configurable. `offline: true` mode skips LLM entirely.
- **API keys**: Stored in environment; never logged.
- **GitHub Action**: Runs in the user's own GitHub Actions runner; no source upload to third parties.
- **Enterprise mode**: All components deployable on-premises via Docker.

---

## 13. Decisions Log

All decisions resolved on 2026-07-09. See header table.

---

## 14. TODO Tracking

### Phase 1 (active)
- [x] Monorepo scaffold under `app/` with uv + pyproject.toml + requirements.txt
- [x] File indexer (Python + JS language detection)
- [x] AST engine: tree-sitter for Python + JavaScript (with correct grammars)
- [x] Symbol graph (NetworkX) — two-pass definition/reference resolution
- [x] Dead code detector with confidence scoring and entry-point exclusions
- [x] Engine registry — all 9 engines registered; Phase 2 stubs in place
- [x] Engine selection via CLI flag (`-e`), `--quick` mode, sentinel constants
- [x] Health score calculator (weighted per category)
- [x] Recommendation engine
- [x] SQLite storage (`~/.ghostlint/ghostlint.db`)
- [x] CLI: `ghostlint scan`, `ghostlint report`, `ghostlint engines`
- [x] FastAPI backend skeleton with `/api/v1/scans` endpoints
- [x] Live scan validated against VectorShift-Assignment (100/100 clean repo)
- [ ] Git history analyzer (GitPython)
- [ ] `ghostlint scan --changed` incremental mode
- [ ] Pytest unit tests for each module

### Phase 2
- [ ] Duplicate logic detector (AST hash + embeddings)
- [ ] ChromaDB local vector store
- [ ] LiteLLM / GPT-4o-mini reasoning layer
- [ ] Refactor completion, arch drift, config, doc, dependency, test, naming detectors
- [ ] `ghostlint scan --pr` PR mode

### Phase 3
- [ ] Next.js dashboard
- [ ] GitHub Action
- [ ] PR bot comments

### Documentation (end of project)
- [ ] Root `README.md` — product overview, install, quickstart
- [ ] `docs/engines/` — one `.md` per engine: what it detects, how it works, example output, config options
- [ ] User guide: CLI reference, `ghostlint.yml` config schema, CI/CD integration, AI tool integration

---

*Plan written: 2026-07-09 | Last updated: 2026-07-09*
