"""tiramisu MCP server — stdio transport, FastMCP-based."""
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from tiramisu_engine.scanner import Scanner, ScanConfig, ALL_ENGINES, FAST_ENGINES
from tiramisu_engine.db.session import get_session
from tiramisu_engine.db.models import ScanRecord
from tiramisu_mcp.context_builder import (
    build_full_scan_response,
    build_file_context_prose,
    findings_to_dicts,
    git_metrics_to_dict,
    findings_summary_dict,
)

mcp = FastMCP(
    "tiramisu",
    instructions=(
        "Repository Health Intelligence. "
        "Use scan_repo to get a full health analysis of a codebase. "
        "Use scan_files when you have partial context (specific files you are about to edit). "
        "Use get_health_context to retrieve the last cached scan without triggering a new one. "
        "Use list_findings to filter findings by category, risk level, or file path. "
        "Use check_diff to predict the impact of a proposed code change before applying it."
    ),
)


def _run_scan(repo_path: Path, engines: list[str] | None = None,
              min_confidence: float = 0.6, changed_files: list[str] | None = None,
              skip_persist: bool = False):
    resolved_engines = engines if engines else [ALL_ENGINES]
    config = ScanConfig(
        repo_path=repo_path,
        scan_mode="full",
        confidence_threshold=min_confidence,
        engines=resolved_engines,
        changed_files=changed_files,
        skip_persist=skip_persist,
    )
    return Scanner(config).scan()


def _clone_repo(github: str) -> Path:
    import git as gitpython
    url = github.strip()
    if not (url.startswith("http") or url.startswith("git@")):
        url = f"https://github.com/{url}.git"
    tmp = Path(tempfile.mkdtemp(prefix="tiramisu_mcp_"))
    gitpython.Repo.clone_from(url, str(tmp), depth=200)
    return tmp


@mcp.tool()
def scan_repo(
    path: str = ".",
    github: str = "",
    engines: list[str] = [],
    min_confidence: float = 0.6,
) -> dict:
    """Perform a full repository health scan.

    Scans for dead code, duplicate logic, architectural drift, test health,
    dependency issues, and more. Also computes git-history metrics (stability,
    maintenance velocity, refactor completion, friction index) when git history
    is available.

    Args:
        path: Absolute or relative path to a local repository. Ignored when
              `github` is provided. Defaults to current directory.
        github: GitHub repository to clone and scan. Accepts 'owner/repo'
                shorthand or a full HTTPS URL. Takes precedence over `path`.
        engines: Specific engines to run. Empty list runs all phase-1 engines.
                 Valid values: dead_code, duplicate_logic, refactor, arch_drift,
                 config_health, doc_health, dependency_health, test_health, naming.
        min_confidence: Minimum confidence threshold for findings (0.0–1.0).

    Returns:
        health_score, git_metrics, findings_summary, top_findings,
        recommendations, and a prose health_context summary.
    """
    cloned_tmp: Path | None = None
    try:
        if github:
            cloned_tmp = _clone_repo(github)
            repo_path = cloned_tmp
        else:
            repo_path = Path(path).resolve()
            if not repo_path.exists():
                return {"error": f"Path does not exist: {repo_path}"}

        result = _run_scan(repo_path, engines or None, min_confidence)
        return build_full_scan_response(result)

    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if cloned_tmp:
            shutil.rmtree(cloned_tmp, ignore_errors=True)


@mcp.tool()
def scan_files(
    repo_path: str,
    files: list[str],
    min_confidence: float = 0.6,
) -> dict:
    """Scan specific files within a repository for health issues.

    Builds the full cross-file symbol graph (for accurate dead-code and
    duplicate detection) but only returns findings whose primary location
    is one of the requested files. Use this when you have partial context —
    e.g., the files you are about to edit.

    Args:
        repo_path: Absolute path to the repository root.
        files: List of file paths to focus on. Can be relative to repo_path
               or absolute.
        min_confidence: Minimum confidence threshold for findings (0.0–1.0).

    Returns:
        findings scoped to the given files, a prose health_context, and the
        overall repository health score for background context.
    """
    try:
        root = Path(repo_path).resolve()
        if not root.exists():
            return {"error": f"repo_path does not exist: {root}"}

        # Normalise: relative paths → relative to repo_path; strip repo_path prefix
        normalised: list[str] = []
        for f in files:
            fp = Path(f)
            if fp.is_absolute():
                try:
                    normalised.append(str(fp.relative_to(root)))
                except ValueError:
                    normalised.append(str(fp))
            else:
                normalised.append(str(fp))

        # skip_persist=True: partial scans must not overwrite full-scan DB records
        result = _run_scan(root, None, min_confidence, changed_files=None,
                           skip_persist=True)

        scoped_findings = [
            f for f in result.findings
            if any(nf in f.primary_file for nf in normalised)
        ]
        return {
            "health_score": result.health_score.overall,
            "files_requested": files,
            "findings_count": len(scoped_findings),
            "findings": _findings_list(scoped_findings),
            "health_context": build_file_context_prose(scoped_findings, files),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _findings_list(findings) -> list[dict]:
    return [
        {
            "id": f.id,
            "category": f.category.value,
            "title": f.title,
            "description": f.description,
            "file": f.primary_file,
            "line": f.primary_line,
            "confidence": round(f.confidence, 2),
            "risk": f.risk.value,
            "effort": f.effort.value,
        }
        for f in findings
    ]


@mcp.tool()
def get_health_context(repo_path: str = ".") -> dict:
    """Return the most recent cached scan for a repository without re-scanning.

    Fast — reads from the local SQLite scan history. Use this at session start
    to load background context before the user asks anything specific.

    Args:
        repo_path: Absolute path to the repository root. Defaults to ".".

    Returns:
        Cached scan result (same shape as scan_repo) with a `cached` flag and
        `scan_age_minutes`. Returns a prompt to run scan_repo if no scan exists.
    """
    try:
        from sqlalchemy import desc
        root = str(Path(repo_path).resolve())
        session = get_session()
        record = (
            session.query(ScanRecord)
            .filter(ScanRecord.repo_path == root)
            .order_by(desc(ScanRecord.started_at))
            .first()
        )

        if not record:
            session.close()
            return {
                "cached": False,
                "message": "No scan found for this repository. Call scan_repo first.",
                "repo_path": root,
            }

        from datetime import datetime, timezone
        age_min = round(
            (datetime.now(timezone.utc) - record.started_at.replace(tzinfo=timezone.utc))
            .total_seconds() / 60,
            1,
        )

        # Materialise all attributes before closing the session (lazy-load guard)
        findings_raw = [
            {
                "id": f.id,
                "category": f.category,
                "title": f.title,
                "file": f.file_path,
                "line": f.line_start,
                "confidence": round(f.confidence, 2),
                "risk": f.risk,
            }
            for f in record.findings
        ]
        health_score_overall = record.health_score_overall
        files_scanned = record.files_scanned
        symbols_found = record.symbols_found
        scores = json.loads(record.health_score_json) if record.health_score_json else {}
        session.close()

        return {
            "cached": True,
            "scan_age_minutes": age_min,
            "repo_path": root,
            "health_score": health_score_overall,
            "files_scanned": files_scanned,
            "symbols_found": symbols_found,
            "scores_by_category": scores,
            "findings_count": len(findings_raw),
            "top_findings": findings_raw[:10],
            "health_context": (
                f"Cached scan ({age_min}m ago): health score {health_score_overall:.1f}/100, "
                f"{len(findings_raw)} finding(s) across {files_scanned} files."
            ),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_findings(
    repo_path: str = ".",
    category: str = "",
    risk: str = "",
    file_pattern: str = "",
    limit: int = 50,
) -> dict:
    """Query findings from the last scan with optional filters.

    Args:
        repo_path: Absolute path to the repository root.
        category: Filter by category (e.g. dead_code, duplicate_logic, refactor,
                  arch_drift, config_health, doc_health, dependency_health,
                  test_health, naming). Empty string = all categories.
        risk: Filter by risk level: high | medium | low. Empty = all.
        file_pattern: Substring match against the finding's file path.
        limit: Maximum number of findings to return (default 50).

    Returns:
        Filtered list of findings from the most recent scan.
    """
    try:
        from sqlalchemy import desc
        root = str(Path(repo_path).resolve())
        session = get_session()
        record = (
            session.query(ScanRecord)
            .filter(ScanRecord.repo_path == root)
            .order_by(desc(ScanRecord.started_at))
            .first()
        )

        if not record:
            session.close()
            return {
                "findings": [],
                "message": "No scan found. Call scan_repo first.",
            }

        # Materialise findings before closing session (lazy-load guard)
        all_findings_raw = [
            {
                "id": f.id,
                "category": f.category,
                "title": f.title,
                "description": f.description,
                "file": f.file_path,
                "line": f.line_start,
                "confidence": round(f.confidence, 2),
                "risk": f.risk,
                "effort": f.effort,
            }
            for f in record.findings
        ]
        session.close()

        results = []
        for f in all_findings_raw:
            if category and f["category"] != category:
                continue
            if risk and f["risk"] != risk:
                continue
            if file_pattern and file_pattern not in (f["file"] or ""):
                continue
            results.append(f)
            if len(results) >= limit:
                break

        return {
            "findings": results,
            "total_matching": len(results),
            "filters_applied": {
                "category": category or None,
                "risk": risk or None,
                "file_pattern": file_pattern or None,
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def check_diff(
    repo_path: str,
    diff: str,
    engines: list[str] = [],
    min_confidence: float = 0.6,
) -> dict:
    """Predict the health impact of a proposed code change before applying it.

    Applies the diff to a temporary copy of the repository, re-scans the
    affected files, and returns the score delta and any new or resolved findings.
    Use this to evaluate 'what if I make this change?' before committing.

    Args:
        repo_path: Absolute path to the repository root (the baseline).
        diff: Unified diff string (output of `git diff` or `diff -u`).
              For best accuracy, the diff should describe changes relative to
              the committed HEAD (uncommitted files in the working tree are not
              included in the patched copy).
        engines: Engines to run. Empty = all phase-1 engines.
        min_confidence: Confidence threshold for findings (0.0–1.0).

    Returns:
        score_before, score_after, delta, regression_risk, new_findings,
        resolved_findings, and a prose summary.
    """
    try:
        root = Path(repo_path).resolve()
        if not root.exists():
            return {"error": f"repo_path does not exist: {root}"}

        # ── Baseline scan (not persisted — ephemeral comparison) ──────────────
        baseline = _run_scan(root, engines or None, min_confidence, skip_persist=True)

        # ── Apply diff to a temp copy ─────────────────────────────────────────
        import subprocess
        tmp_dir = Path(tempfile.mkdtemp(prefix="tiramisu_diff_"))
        try:
            # Copy repo (shallow — only tracked files via git, fallback to shutil)
            try:
                import git as gitpython
                gitpython.Repo(root).clone(str(tmp_dir) + "_clone")
                patched_dir = Path(str(tmp_dir) + "_clone")
                shutil.rmtree(tmp_dir, ignore_errors=True)
                tmp_dir = patched_dir
            except Exception:
                shutil.copytree(root, tmp_dir, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(".git", ".venv", "node_modules"))

            # Write diff to a temp file and apply with `patch`
            diff_file = tmp_dir / ".tiramisu_patch.diff"
            diff_file.write_text(diff, encoding="utf-8")
            result_apply = subprocess.run(
                ["patch", "-p1", "--batch", "-i", str(diff_file)],
                cwd=str(tmp_dir),
                capture_output=True,
                text=True,
            )
            diff_file.unlink(missing_ok=True)
            if result_apply.returncode not in (0, 1):
                return {
                    "error": "Failed to apply diff",
                    "patch_stderr": result_apply.stderr[:500],
                }

            # Extract changed files from diff header lines
            changed_files: list[str] = []
            for line in diff.splitlines():
                if line.startswith("+++ b/") or line.startswith("+++ "):
                    fp = line[6:] if line.startswith("+++ b/") else line[4:]
                    if fp and fp != "/dev/null":
                        changed_files.append(fp.strip())

            # ── Patched scan (not persisted — ephemeral) ─────────────────────
            patched = _run_scan(
                tmp_dir,
                engines or None,
                min_confidence,
                changed_files=changed_files or None,
                skip_persist=True,
            )

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # ── Delta computation ────────────────────────────────────────────────
        baseline_ids = {f.id for f in baseline.findings}
        # For new scan findings we can't match by id (different repo copy),
        # so match by (category, title, file, line) as a fingerprint.
        def _fp(f):
            return (f.category.value, f.title, Path(f.primary_file).name, f.primary_line)

        baseline_fps = {_fp(f) for f in baseline.findings}
        patched_fps = {_fp(f) for f in patched.findings}

        new_findings = [f for f in patched.findings if _fp(f) not in baseline_fps]
        resolved_findings = [f for f in baseline.findings if _fp(f) not in patched_fps]

        score_before = baseline.health_score.overall
        score_after = patched.health_score.overall
        delta = round(score_after - score_before, 1)

        new_highs = sum(1 for f in new_findings if f.risk.value == "high")
        regression_risk = (
            "HIGH" if new_highs > 0 or delta < -10
            else "MEDIUM" if delta < -4 or len(new_findings) > 2
            else "LOW"
        )

        summary_parts = [f"Score: {score_before:.1f} → {score_after:.1f} ({delta:+.1f})."]
        if new_findings:
            summary_parts.append(
                f"{len(new_findings)} new finding(s) introduced"
                + (f", including {new_highs} HIGH risk" if new_highs else "") + "."
            )
        if resolved_findings:
            summary_parts.append(f"{len(resolved_findings)} existing finding(s) resolved.")
        if not new_findings and not resolved_findings:
            summary_parts.append("No net change in findings.")

        return {
            "score_before": score_before,
            "score_after": score_after,
            "delta": delta,
            "regression_risk": regression_risk,
            "new_findings": _findings_list(new_findings),
            "resolved_findings": _findings_list(resolved_findings),
            "summary": " ".join(summary_parts),
        }

    except Exception as exc:
        return {"error": str(exc)}
