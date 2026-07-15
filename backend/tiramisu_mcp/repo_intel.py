"""Repository intelligence helpers for the tiramisu MCP server.

Pure functions that turn a :class:`ScanResult` (or a list of findings) plus the
filesystem / git history into AI-friendly structured dicts. These are the
"brains" behind the higher-level MCP tools; the tools themselves are thin
wrappers that resolve a path, obtain a scan, and call into this module.

No I/O except where explicitly stated (``overview`` reads the filesystem,
``explain_history`` reads git). All other functions operate on in-memory data so
they are trivially unit-testable.
"""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from tiramisu_engine.models.findings import (
    EffortLevel,
    Evidence,
    Finding,
    GitMetrics,
    HealthScore,
    RiskLevel,
    ScanResult,
)


# ─── small shared primitives ────────────────────────────────────────────────

# Approximate effort → hours mapping used for aggregate estimates.
_EFFORT_HOURS: dict[str, float] = {
    EffortLevel.MINUTES.value: 0.5,
    EffortLevel.HOURS.value: 2.0,
    EffortLevel.DAYS.value: 8.0,
}

# Sort rank for risk (lower = safer / quick win first).
_RISK_RANK: dict[str, int] = {
    RiskLevel.LOW.value: 0,
    RiskLevel.MEDIUM.value: 1,
    RiskLevel.HIGH.value: 2,
}

# Sort rank for effort (lower = quicker).
_EFFORT_RANK: dict[str, int] = {
    EffortLevel.MINUTES.value: 0,
    EffortLevel.HOURS.value: 1,
    EffortLevel.DAYS.value: 2,
}

# Common entry-point filenames used by `overview`.
_ENTRY_POINT_FILES = {
    "main.py", "app.py", "manage.py", "server.py", "run.py", "wsgi.py", "asgi.py",
    "index.js", "index.ts", "app.js", "app.ts", "server.js", "server.ts",
    "main.js", "main.ts",
}

# Framework fingerprint → files/patterns that indicate the framework.
_FRAMEWORK_MARKERS: dict[str, tuple[str, ...]] = {
    "fastapi": ("fastapi",),
    "flask": ("flask",),
    "django": ("django",),
    "typer": ("typer",),
    "react": ("react", '"react"'),
    "next.js": ("next", '"next"'),
    "vue": ("vue", '"vue"'),
    "express": ("express",),
}


def health_label(score: float) -> str:
    """Return a short human-readable label for a 0–100 health score."""
    if score >= 90:
        return "healthy"
    if score >= 70:
        return "needs review"
    if score >= 50:
        return "has significant issues"
    return "critical"


def finding_to_dict(f: Finding) -> dict:
    """Full finding → dict (includes benefit, unlike the lean _findings_list)."""
    return {
        "id": f.id,
        "category": f.category.value,
        "title": f.title,
        "description": f.description,
        "file": f.primary_file,
        "line": f.primary_line,
        "confidence": round(f.confidence, 2),
        "risk": f.risk.value,
        "effort": f.effort.value,
        "benefit": f.benefit,
    }


# ─── repository_overview ────────────────────────────────────────────────────

def overview(repo_path: Path) -> dict:
    """Filesystem-only repository overview (no scan, no git required).

    Counts source files by language, detects common frameworks and entry
    points, and lists top-level directories. Reads files via :class:`FileIndexer`
    so the same exclusion rules as a real scan apply.
    """
    from tiramisu_engine.indexer import FileIndexer, LANGUAGE_MAP

    files = FileIndexer().index(repo_path)

    by_language: Counter = Counter(f.language for f in files)
    total_lines = 0
    for f in files:
        try:
            total_lines += f.content.count("\n") + (0 if f.content.endswith("\n") else 1)
        except Exception:
            continue

    # Top-level directories of source files.
    dir_counts: Counter = Counter()
    for f in files:
        parts = Path(f.relative_path).parts
        if len(parts) > 1:
            dir_counts[parts[0]] += 1

    entry_points = sorted({
        f.relative_path for f in files
        if Path(f.relative_path).name in _ENTRY_POINT_FILES
    })

    frameworks = _detect_frameworks(repo_path)
    config_files = _config_files(repo_path)

    return {
        "repo_path": str(repo_path),
        "total_files": len(files),
        "total_lines": total_lines,
        "files_by_language": dict(by_language),
        "top_directories": dict(dir_counts.most_common(10)),
        "entry_points": entry_points,
        "detected_frameworks": frameworks,
        "config_files": config_files,
    }


def _detect_frameworks(repo_path: Path) -> list[str]:
    """Best-effort framework detection from dependency manifests."""
    manifests: list[str] = []
    for name in ("requirements.txt", "pyproject.toml", "package.json"):
        p = repo_path / name
        if p.exists():
            try:
                manifests.append(p.read_text(encoding="utf-8", errors="replace").lower())
            except OSError:
                continue

    if not manifests:
        return []

    blob = "\n".join(manifests)
    found = []
    for fw, markers in _FRAMEWORK_MARKERS.items():
        if any(m in blob for m in markers):
            found.append(fw)
    return found


def _config_files(repo_path: Path) -> list[str]:
    """Names of common config files that exist at or near the repo root."""
    candidates = (
        "pyproject.toml", "setup.py", "requirements.txt", "package.json",
        "tsconfig.json", ".env", ".env.example", "Dockerfile", "docker-compose.yml",
        "Makefile", "tox.ini",
    )
    return [c for c in candidates if (repo_path / c).exists()]


# ─── cleanup recommendations & effort estimation ────────────────────────────

def cleanup_recommendations(findings: Iterable[Finding], limit: int = 20) -> list[dict]:
    """Findings sorted as cleanup recommendations: quick wins first.

    Quick win = high confidence + low risk + low effort. Returns the top
    ``limit`` items as full finding dicts plus an ``est_hours`` estimate.
    """
    items = sorted(
        findings,
        key=lambda f: (-f.confidence, _RISK_RANK.get(f.risk.value, 9),
                       _EFFORT_RANK.get(f.effort.value, 9)),
    )
    out = []
    for f in items[:limit]:
        d = finding_to_dict(f)
        d["est_hours"] = _EFFORT_HOURS.get(f.effort.value, 2.0) * f.confidence
        out.append(d)
    return out


def estimate_effort(findings: Iterable[Finding]) -> dict:
    """Aggregate cleanup-effort estimate from a set of findings.

    Each finding contributes ``effort_hours * confidence`` to the total.
    """
    findings = list(findings)
    total_hours = 0.0
    by_effort: Counter = Counter()
    by_category: Counter = Counter()
    for f in findings:
        hours = _EFFORT_HOURS.get(f.effort.value, 2.0) * f.confidence
        total_hours += hours
        by_effort[f.effort.value] += 1
        by_category[f.category.value] += 1

    quick_wins = sum(
        1 for f in findings
        if f.confidence >= 0.7 and f.risk.value == RiskLevel.LOW.value
        and f.effort.value in (EffortLevel.MINUTES.value, EffortLevel.HOURS.value)
    )

    return {
        "total_findings": len(findings),
        "estimated_hours": round(total_hours, 1),
        "estimated_days": round(total_hours / 8.0, 1),
        "by_effort": dict(by_effort),
        "by_category": dict(by_category),
        "quick_wins_count": quick_wins,
    }


def build_cleanup_plan(findings: Iterable[Finding], health_score: HealthScore) -> dict:
    """A phased, ordered cleanup plan grouped by effort/risk.

    Phases:
      1. quick_wins   — high confidence, low risk, minutes/hours.
      2. quick_fixes  — medium-confidence or medium-risk routine fixes.
      3. refactors    — days-effort items (larger changes).
      4. strategic    — high-risk items requiring careful planning.
    """
    findings = list(findings)

    def _item(f: Finding) -> dict:
        d = finding_to_dict(f)
        d["est_hours"] = round(_EFFORT_HOURS.get(f.effort.value, 2.0) * f.confidence, 1)
        return d

    quick_wins: list[dict] = []
    quick_fixes: list[dict] = []
    refactors: list[dict] = []
    strategic: list[dict] = []

    for f in findings:
        item = _item(f)
        is_high_conf = f.confidence >= 0.7
        is_low_risk = f.risk.value == RiskLevel.LOW.value
        is_days = f.effort.value == EffortLevel.DAYS.value
        is_high_risk = f.risk.value == RiskLevel.HIGH.value

        if is_high_risk:
            strategic.append(item)
        elif is_days:
            refactors.append(item)
        elif is_high_conf and is_low_risk:
            quick_wins.append(item)
        else:
            quick_fixes.append(item)

    def _phase_summ(items: list[dict]) -> dict:
        return {
            "count": len(items),
            "est_hours": round(sum(i["est_hours"] for i in items), 1),
        }

    phases = {
        "1_quick_wins": {"summary": _phase_summ(quick_wins), "items": quick_wins},
        "2_quick_fixes": {"summary": _phase_summ(quick_fixes), "items": quick_fixes},
        "3_refactors": {"summary": _phase_summ(refactors), "items": refactors},
        "4_strategic": {"summary": _phase_summ(strategic), "items": strategic},
    }

    total_hours = sum(p["summary"]["est_hours"] for p in phases.values())
    recommended_order = [k for k, p in phases.items() if p["summary"]["count"] > 0]

    return {
        "health_score": round(health_score.overall, 1),
        "health_label": health_label(health_score.overall),
        "total_findings": len(findings),
        "total_estimated_hours": round(total_hours, 1),
        "phases": phases,
        "recommended_order": recommended_order,
        "summary": (
            f"{len(findings)} finding(s) across {len(recommended_order)} phase(s). "
            f"{quick_wins and len(quick_wins) or 0} quick win(s) available. "
            f"Estimated cleanup: {total_hours:.1f} hours."
        ),
    }


# ─── repository metrics ────────────────────────────────────────────────────

def metrics_dict(result: ScanResult, git_metrics: GitMetrics) -> dict:
    """Composite repository metrics: health, per-category scores, git signals."""
    hs = result.health_score
    category_scores = {
        "dead_code": hs.dead_code,
        "duplicate_logic": hs.duplicate_logic,
        "refactor_completion": hs.refactor_completion,
        "architectural_drift": hs.architectural_drift,
        "config_consistency": hs.config_consistency,
        "documentation_freshness": hs.documentation_freshness,
        "dependency_health": hs.dependency_health,
        "test_health": hs.test_health,
    }
    weakest = sorted(category_scores.items(), key=lambda kv: kv[1])[:3]

    findings = result.findings
    by_category: Counter = Counter(f.category.value for f in findings)

    # Complexity signals derivable without a separate engine.
    file_counts: Counter = Counter(f.primary_file for f in findings if f.primary_file)
    hotspot_files = [
        {"file": f, "finding_count": n}
        for f, n in file_counts.most_common(5)
    ]

    return {
        "health_score": round(hs.overall, 1),
        "health_label": health_label(hs.overall),
        "category_scores": {k: round(v, 1) for k, v in category_scores.items()},
        "weakest_categories": [{"category": c, "score": round(s, 1)} for c, s in weakest],
        "findings_total": len(findings),
        "findings_by_category": dict(by_category),
        "hotspot_files": hotspot_files,
        "files_scanned": result.files_scanned,
        "symbols_found": result.symbols_found,
        "git_metrics": _git_metrics_to_dict(git_metrics),
    }


def _git_metrics_to_dict(gm: GitMetrics) -> dict:
    return {
        "available": gm.available,
        "stability_index": gm.stability_index,
        "maintenance_velocity": round(gm.maintenance_velocity, 3),
        "refactor_completion_rate": gm.refactor_completion_rate,
        "friction_index": gm.friction_index,
        "total_commits_analyzed": gm.total_commits_analyzed,
        "repo_age_days": gm.repo_age_days,
        "top_contributors": gm.top_contributors,
    }


# ─── repository patterns ───────────────────────────────────────────────────

def patterns(findings: Iterable[Finding], repo_path: Path) -> dict:
    """Synthesize "repository patterns" from existing detector findings.

    No new detector is run — this groups and reframes what the scanners already
    found into pattern categories an AI assistant can act on.
    """
    findings = list(findings)

    # Duplication patterns: group duplicate_logic findings by title.
    duplication: list[dict] = []
    dup_groups: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        if f.category.value == "duplicate_logic":
            dup_groups[f.title].append(f)
    for title, group in dup_groups.items():
        duplication.append({
            "pattern": title,
            "occurrences": len(group),
            "files": sorted({g.primary_file for g in group if g.primary_file}),
        })
    duplication.sort(key=lambda d: -d["occurrences"])

    # Naming patterns: near-duplicate / duplicate model-like classes.
    naming = [
        finding_to_dict(f) for f in findings
        if f.category.value == "naming_consistency"
    ]

    # API proliferation: incomplete-refactor synonyms (get/fetch/load, etc.).
    api_proliferation = [
        finding_to_dict(f) for f in findings
        if f.category.value == "refactor_completion"
    ]

    # Directory-structure pattern (filesystem-only heuristic).
    structure = _directory_structure(repo_path)

    return {
        "duplication_patterns": duplication,
        "naming_patterns": naming,
        "api_proliferation": api_proliferation,
        "directory_structure": structure,
        "summary": (
            f"{len(duplication)} duplication pattern(s), "
            f"{len(naming)} naming issue(s), "
            f"{len(api_proliferation)} API-proliferation signal(s)."
        ),
    }


def _directory_structure(repo_path: Path) -> dict:
    """Lightweight view of the top-level source-directory layout."""
    from tiramisu_engine.indexer import EXCLUDE_DIRS

    top_dirs: Counter = Counter()
    source_exts = {".py", ".js", ".jsx", ".ts", ".tsx"}
    try:
        for p in repo_path.iterdir():
            if not p.is_dir() or p.name in EXCLUDE_DIRS or p.name.startswith("."):
                continue
            # Count source files one level deep as a cheap signal.
            count = 0
            try:
                for child in p.rglob("*"):
                    if child.is_file() and child.suffix in source_exts:
                        count += 1
            except OSError:
                continue
            if count:
                top_dirs[p.name] = count
    except OSError:
        pass

    return {"top_source_directories": dict(top_dirs.most_common(10))}


# ─── repository history (git) ──────────────────────────────────────────────

def explain_history(repo_path: Path, limit: int = 20) -> dict:
    """Best-effort git history narrative. Returns ``available=False`` if not git."""
    try:
        import git as gitpython
        repo = gitpython.Repo(repo_path, search_parent_directories=True)
    except Exception:
        return {"available": False, "message": "Not a git repository."}

    try:
        from tiramisu_engine.git_metrics import compute_git_metrics
        gm = compute_git_metrics(repo_path)
    except Exception:
        gm = GitMetrics(available=False)

    commits = []
    try:
        for c in repo.iter_commits(max_count=limit):
            commits.append({
                "sha": c.hexsha[:8],
                "author": (c.author.email or "").strip(),
                "date": c.committed_date,
                "message": c.message.strip().splitlines()[0][:200]
                if c.message.strip() else "",
            })
    except Exception:
        pass

    authors: Counter = Counter(c["author"] for c in commits if c["author"])

    return {
        "available": True,
        "total_commits_analyzed": gm.total_commits_analyzed,
        "repo_age_days": gm.repo_age_days,
        "contributors": [
            {"email": email, "commits": n} for email, n in authors.most_common(10)
        ],
        "git_metrics": _git_metrics_to_dict(gm),
        "recent_commits": commits,
        "narrative": _history_narrative(gm, len(commits)),
    }


def _history_narrative(gm: GitMetrics, recent_count: int) -> str:
    if not gm.available:
        return "No git metrics available."
    parts = [
        f"Repository is {gm.repo_age_days} days old across "
        f"{gm.total_commits_analyzed} analyzed commit(s)."
    ]
    parts.append(
        f"Stability index {gm.stability_index:.0f}/100 "
        f"(core-file churn in recent commits)."
    )
    parts.append(
        f"Maintenance velocity {gm.maintenance_velocity:.2f} "
        f"(share of fix-type commits in the last 90 days)."
    )
    parts.append(
        f"Friction index {gm.friction_index:.0f}/100 "
        f"(composite of churn, ownership fragmentation, and large files)."
    )
    return " ".join(parts)


# ─── repository knowledge search (deterministic) ───────────────────────────

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def search_knowledge(findings: Iterable[Finding], repo_path: Path,
                     query: str, limit: int = 20) -> dict:
    """Deterministic keyword search over findings and source files.

    No embeddings / no network — ranks matches by a simple word-overlap score.
    """
    query_words = {w.lower() for w in _WORD_RE.findall(query)}
    if not query_words:
        return {
            "query": query,
            "finding_matches": [],
            "file_matches": [],
            "message": "Empty query — nothing to search.",
        }

    # ── Finding matches ────────────────────────────────────────────────────
    finding_matches: list[tuple[float, Finding]] = []
    for f in findings:
        text = " ".join([
            f.title or "", f.description or "", f.category.value, f.primary_file,
            f.benefit or "",
        ]).lower()
        words = set(_WORD_RE.findall(text))
        overlap = len(query_words & words)
        # Bonus for an explicit substring hit (e.g. a function name).
        substr_bonus = 0.5 if query.lower() in text else 0.0
        score = overlap + substr_bonus
        if score > 0:
            finding_matches.append((score, f))

    finding_matches.sort(key=lambda t: (-t[0], -t[1].confidence))
    finding_out = [
        {**finding_to_dict(f), "score": round(s, 2)}
        for s, f in finding_matches[:limit]
    ]

    # ── File matches ───────────────────────────────────────────────────────
    file_out = _search_files(repo_path, query_words, query, limit)

    return {
        "query": query,
        "finding_matches": finding_out,
        "file_matches": file_out,
        "total_matches": len(finding_out) + len(file_out),
    }


def _search_files(repo_path: Path, query_words: set[str], query: str,
                  limit: int) -> list[dict]:
    """Scan source-file names + light content for query terms."""
    from tiramisu_engine.indexer import FileIndexer

    matches: list[dict] = []
    files = FileIndexer().index(repo_path)
    query_lower = query.lower()

    for f in files:
        name = Path(f.relative_path).name.lower()
        name_words = set(_WORD_RE.findall(name))
        name_overlap = len(query_words & name_words)
        name_substr = query_lower in name

        # Light content scan: count query-word occurrences in file content.
        content_lower = f.content.lower()
        content_hits = sum(content_lower.count(w) for w in query_words)
        content_substr = query_lower in content_lower

        score = name_overlap * 2.0 + (1.0 if name_substr else 0.0)
        score += min(content_hits, 10) * 0.1 + (0.5 if content_substr else 0.0)

        if score > 0:
            matches.append({
                "file": f.relative_path,
                "language": f.language,
                "score": round(score, 2),
            })

    matches.sort(key=lambda m: -m["score"])
    return matches[:limit]


# ─── scan timeline (SQLite history) ────────────────────────────────────────

def scan_timeline(records: list) -> dict:
    """Build a health-score timeline from persisted ``ScanRecord`` objects.

    ``records`` must be ordered oldest → newest (callers sort ascending by
    ``started_at``). Trend is derived from the first vs. latest score.
    """
    entries = []
    for r in records:
        entries.append({
            "scan_id": r.id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "health_score": r.health_score_overall,
            "files_scanned": r.files_scanned,
            "symbols_found": r.symbols_found,
            "findings_count": len(r.findings) if r.findings else 0,
        })

    scores = [e["health_score"] for e in entries if e["health_score"] is not None]
    trend = "stable"
    if len(scores) >= 2:
        delta = scores[-1] - scores[0]
        trend = "improving" if delta > 1 else "declining" if delta < -1 else "stable"

    latest = entries[-1] if entries else None
    oldest = entries[0] if entries else None

    summary = "No scan history yet."
    if entries:
        first_s = scores[0] if scores else None
        last_s = scores[-1] if scores else None
        if first_s is not None and last_s is not None:
            summary = (
                f"{len(entries)} scan(s) recorded. Score "
                f"{first_s:.1f} → {last_s:.1f} ({last_s - first_s:+.1f}); trend: {trend}."
            )
        else:
            summary = f"{len(entries)} scan(s) recorded."

    return {
        "available": len(entries) > 0,
        "scan_count": len(entries),
        "trend": trend,
        "latest": latest,
        "oldest": oldest,
        "entries": entries,
        "summary": summary,
    }
