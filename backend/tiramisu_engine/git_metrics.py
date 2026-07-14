from __future__ import annotations
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from tiramisu_engine.models.findings import GitMetrics

# Commit message keywords that indicate a fix/resolution
_FIX_PATTERN = re.compile(
    r"\b(fix|fixes|fixed|close|closes|closed|resolve|resolves|resolved|patch|hotfix|bugfix|repair)\b",
    re.IGNORECASE,
)

# Files considered "core architecture" — churn here signals instability
_ARCH_PATTERNS = re.compile(
    r"(model|schema|router|route|controller|service|interface|types?|config|settings|base|core|auth)",
    re.IGNORECASE,
)

# Tech-debt markers in source
_DEBT_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|XXX|DEPRECATED|NOQA)\b")

# Source file extensions to count lines and authors on
_SOURCE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".rs", ".cpp", ".c"}


def compute_git_metrics(repo_path: Path, lookback_commits: int = 200) -> GitMetrics:
    """Compute git-history-based metrics. Returns unavailable GitMetrics if not a git repo."""
    try:
        import git as gitpython
        repo = gitpython.Repo(repo_path, search_parent_directories=True)
    except Exception:
        return GitMetrics(available=False)

    try:
        return _compute(repo, repo_path, lookback_commits)
    except Exception:
        return GitMetrics(available=False)


def _compute(repo, repo_path: Path, lookback_commits: int) -> GitMetrics:
    commits = list(repo.iter_commits(max_count=lookback_commits))
    if not commits:
        return GitMetrics(available=False)

    total = len(commits)
    now = datetime.now(timezone.utc)

    # Repo age
    oldest = commits[-1]
    oldest_dt = datetime.fromtimestamp(oldest.committed_date, tz=timezone.utc)
    repo_age_days = (now - oldest_dt).days

    # Unique contributor count across analyzed commits
    authors: set[str] = {c.author.email for c in commits if c.author.email}

    # ── 1. Stability Index ─────────────────────────────────────────────────────
    # Measure % of commits that did NOT touch any "core" file in the last N commits.
    # Inverted: more core-file churn → lower stability.
    recent_window = min(30, total)
    recent_commits = commits[:recent_window]
    core_churn_commits = 0
    for c in recent_commits:
        try:
            files_changed = list(c.stats.files.keys())
        except Exception:
            continue
        if any(_ARCH_PATTERNS.search(f) for f in files_changed):
            core_churn_commits += 1
    stability_ratio = 1.0 - (core_churn_commits / recent_window) if recent_window else 1.0
    stability_index = round(stability_ratio * 100, 1)

    # ── 2. Maintenance Velocity ────────────────────────────────────────────────
    # Ratio of fix-type commits to all commits in last 90 days
    cutoff_90d = now - timedelta(days=90)
    recent_90d = [
        c for c in commits
        if datetime.fromtimestamp(c.committed_date, tz=timezone.utc) >= cutoff_90d
    ]
    if recent_90d:
        fix_commits = sum(1 for c in recent_90d if _FIX_PATTERN.search(c.message))
        maintenance_velocity = round(fix_commits / len(recent_90d), 3)
    else:
        maintenance_velocity = 0.0

    # ── 3. Refactor Completion Rate ────────────────────────────────────────────
    # Compare tech-debt markers in HEAD vs a historical snapshot.
    # A decreasing count → high completion rate.
    refactor_completion_rate = _compute_refactor_completion(repo, repo_path, commits)

    # ── 4. Repository Friction Index ───────────────────────────────────────────
    friction_index = _compute_friction(repo, repo_path, commits)

    return GitMetrics(
        available=True,
        stability_index=stability_index,
        maintenance_velocity=maintenance_velocity,
        refactor_completion_rate=refactor_completion_rate,
        friction_index=friction_index,
        total_commits_analyzed=total,
        repo_age_days=repo_age_days,
        top_contributors=len(authors),
    )


def _count_debt_markers_in_tree(repo, commit) -> int:
    """Count TODO/FIXME/HACK markers across all source blobs at a given commit."""
    count = 0
    try:
        for blob in commit.tree.traverse():
            if blob.type != "blob":
                continue
            if Path(blob.path).suffix not in _SOURCE_EXTS:
                continue
            try:
                content = blob.data_stream.read().decode("utf-8", errors="ignore")
                count += len(_DEBT_PATTERN.findall(content))
            except Exception:
                continue
    except Exception:
        pass
    return count


def _compute_refactor_completion(repo, repo_path: Path, commits: list) -> float:
    """Return 0–100 completion rate based on debt marker trend."""
    if len(commits) < 2:
        return 50.0  # insufficient history — neutral

    head_commit = commits[0]
    # Use a reference commit ~30 commits back, or oldest available
    ref_idx = min(30, len(commits) - 1)
    ref_commit = commits[ref_idx]

    current_count = _count_debt_markers_in_tree(repo, head_commit)
    past_count = _count_debt_markers_in_tree(repo, ref_commit)

    if past_count == 0 and current_count == 0:
        return 100.0  # no debt ever
    if past_count == 0:
        # Debt introduced since reference — completion rate is low
        return max(0.0, round(100.0 - min(current_count * 2, 100), 1))

    # Positive rate: debt went down. Negative: debt increased.
    improvement = (past_count - current_count) / past_count  # -∞ to 1.0
    rate = round(max(0.0, min(100.0, 50.0 + improvement * 50.0)), 1)
    return rate


def _compute_friction(repo, repo_path: Path, commits: list) -> float:
    """Return 0–100 friction index (higher = more friction)."""
    # Component a: average churn per file (commits/file)
    file_commit_counts: dict[str, int] = defaultdict(int)
    for c in commits:
        try:
            for f in c.stats.files:
                if Path(f).suffix in _SOURCE_EXTS:
                    file_commit_counts[f] += 1
        except Exception:
            continue

    if not file_commit_counts:
        return 0.0

    avg_churn = sum(file_commit_counts.values()) / len(file_commit_counts)
    # Normalize: churn of 10+ commits per file is considered high friction
    churn_score = min(avg_churn / 10.0, 1.0)

    # Component b: ownership fragmentation — % files with >3 authors
    file_authors: dict[str, set[str]] = defaultdict(set)
    for c in commits:
        if not c.author.email:
            continue
        try:
            for f in c.stats.files:
                if Path(f).suffix in _SOURCE_EXTS:
                    file_authors[f].add(c.author.email)
        except Exception:
            continue

    if file_authors:
        fragmented = sum(1 for authors in file_authors.values() if len(authors) > 3)
        fragmentation_score = fragmented / len(file_authors)
    else:
        fragmentation_score = 0.0

    # Component c: large files (>500 lines)
    large_file_score = _large_file_ratio(repo_path)

    # Weighted composite
    friction = (churn_score * 0.4 + fragmentation_score * 0.35 + large_file_score * 0.25) * 100
    return round(min(friction, 100.0), 1)


def _large_file_ratio(repo_path: Path) -> float:
    """Return ratio of source files that exceed 500 lines."""
    source_files = [
        p for p in repo_path.rglob("*")
        if p.is_file() and p.suffix in _SOURCE_EXTS
        and not any(part.startswith(".") for part in p.parts)
        and "node_modules" not in p.parts
        and "__pycache__" not in p.parts
        and ".venv" not in p.parts
        and "venv" not in p.parts
    ]
    if not source_files:
        return 0.0
    large = 0
    for f in source_files:
        try:
            lines = f.read_text(errors="ignore").count("\n")
            if lines > 500:
                large += 1
        except Exception:
            continue
    return large / len(source_files)
