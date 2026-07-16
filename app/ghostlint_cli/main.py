from __future__ import annotations
import shutil
import tempfile
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from ghostlint_engine.scanner import Scanner, ScanConfig, ALL_ENGINES, FAST_ENGINES
from ghostlint_cli.output import (
    print_scan_result, print_findings_summary, write_json_report,
)

app = typer.Typer(
    name="ghostlint",
    help=(
        "Repository Health Intelligence — detect dead code, duplicates, drift.\n\n"
        "Scan any local repo or a public GitHub repo directly:\n\n"
        "  ghostlint scan                              # current directory\n\n"
        "  ghostlint scan ~/myrepo                     # local path\n\n"
        "  ghostlint scan --github owner/repo          # public GitHub repo\n\n"
        "Run [bold]ghostlint scan --help[/bold] for the full option list."
    ),
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


def _resolve_github_url(github: str) -> str:
    """Normalize owner/repo shorthand or full URL to a cloneable HTTPS URL."""
    github = github.strip()
    if github.startswith("http://") or github.startswith("https://") or github.startswith("git@"):
        return github
    # owner/repo shorthand
    if "/" in github and not github.startswith("github.com"):
        return f"https://github.com/{github}.git"
    if github.startswith("github.com/"):
        return f"https://{github}.git"
    raise typer.BadParameter(f"Cannot parse GitHub reference: {github!r}")


def _clone_repo(url: str, depth: int | None = 200) -> Path:
    """Clone *url* into a temp directory and return its path.

    depth=200  → shallow clone (fast, default for single-commit scans)
    depth=None → full clone (slow, used when comparing distant commits)
    """
    import git as gitpython
    tmp = tempfile.mkdtemp(prefix="ghostlint_")
    label = f"depth={depth}" if depth else "full history"
    console.print(f"[dim]Cloning [bold]{url}[/bold] ({label}) …[/dim]")
    try:
        kwargs: dict = {"depth": depth} if depth else {}
        gitpython.Repo.clone_from(url, tmp, **kwargs)
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        console.print(f"[red]Clone failed:[/red] {exc}")
        raise typer.Exit(code=2)
    return Path(tmp)


def _compute_clone_depth(sha1: str, sha2: str) -> int | None:
    """Return the minimum clone depth needed to reach both SHAs, or None for full clone.

    Handles HEAD~N and HEAD^^^ notation.  Absolute SHAs and branch names return None
    because we cannot statically determine how deep they are in history.
    """
    import re
    _TILDE = re.compile(r"^HEAD~(\d+)$", re.IGNORECASE)
    _CARET = re.compile(r"^HEAD(\^+)$", re.IGNORECASE)
    _HEAD  = re.compile(r"^HEAD$", re.IGNORECASE)

    def _n(sha: str) -> int | None:
        if _HEAD.match(sha):
            return 0
        m = _TILDE.match(sha)
        if m:
            return int(m.group(1))
        m = _CARET.match(sha)
        if m:
            return len(m.group(1))
        return None  # absolute SHA or branch name — unknown depth

    d1, d2 = _n(sha1), _n(sha2)
    if d1 is None or d2 is None:
        return None
    return max(d1, d2, 1) + 20  # +20 buffer so git has room to resolve


def _print_git_metrics_summary(result) -> None:
    """Print a compact git-metrics block to the terminal."""
    from rich.table import Table
    from rich import box

    gm = result.git_metrics
    if not gm.available:
        console.print("[dim]Git intelligence: not available (no git history)[/dim]\n")
        return

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("Metric", style="dim", width=30)
    t.add_column("Value", justify="right", width=10)
    t.add_column("Note", style="dim")

    def _row(label, val_str, note, color):
        t.add_row(label, f"[{color}]{val_str}[/{color}]", note)

    # Stability Index
    si = gm.stability_index
    si_color = "green" if si >= 70 else ("yellow" if si >= 40 else "red")
    _row("Stability Index", f"{si:.1f}/100", "core-file churn resistance", si_color)

    # Maintenance Velocity
    mv = gm.maintenance_velocity * 100
    mv_color = "green" if mv >= 30 else ("yellow" if mv >= 10 else "red")
    _row("Maintenance Velocity", f"{mv:.1f}%", "fix-commit ratio (last 90d)", mv_color)

    # Refactor Completion Rate
    rc = gm.refactor_completion_rate
    rc_color = "green" if rc >= 60 else ("yellow" if rc >= 40 else "red")
    _row("Refactor Completion", f"{rc:.1f}%", "TODO/FIXME trend vs 30 commits ago", rc_color)

    # Friction Index (lower is better)
    fi = gm.friction_index
    fi_color = "green" if fi <= 30 else ("yellow" if fi <= 60 else "red")
    _row("Friction Index", f"{fi:.1f}/100", "churn + ownership spread + large files", fi_color)

    console.print("\n[bold]Git Intelligence[/bold]  "
                  f"[dim]({gm.total_commits_analyzed} commits · "
                  f"{gm.repo_age_days}d old · {gm.top_contributors} contributors)[/dim]")
    console.print(t)


@app.command()
def scan(
    path: Optional[Path] = typer.Argument(
        None,
        help="Path to the repository to scan (default: current directory). "
             "Ignored when --github is provided.",
        exists=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    github: Optional[str] = typer.Option(
        None, "--github", "-g",
        help="GitHub repository to clone and scan. "
             "Accepts 'owner/repo' or a full HTTPS/SSH URL.",
    ),
    engine: Optional[list[str]] = typer.Option(
        None, "--engine", "-e",
        help="Engine(s) to run. Repeat to run multiple: -e dead_code -e duplicates. "
             "Default: all phase-1 engines.",
    ),
    quick: bool = typer.Option(
        False, "--quick", "-q",
        help="Run only fast engines (suitable for pre-commit hooks, <10s target).",
    ),
    format: str = typer.Option("terminal", "--format", "-f", help="Output format: terminal | json"),
    min_confidence: float = typer.Option(0.6, "--min-confidence", help="Minimum confidence threshold (0.0–1.0)"),
    changed: bool = typer.Option(
        False, "--changed",
        help="Only report findings in files changed vs HEAD (git repos only).",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Write the full report to this file. When set, the console shows only "
             "progress and the findings table; the complete report (score breakdown, "
             "all findings, recommendations) is written to the file.",
    ),
    headless: bool = typer.Option(
        False, "--headless",
        help="Skip opening the browser after generating the HTML report.",
    ),
    exclude: Optional[list[str]] = typer.Option(
        None, "--exclude", "-x",
        help=(
            "Exclude paths or patterns from scanning. Repeat to add multiple. "
            "Accepts: directory names (web-new), relative path prefixes "
            "(frontend/store), or globs (*.generated.py). "
            "Also loaded automatically from ghostlint.toml in the repo root."
        ),
    ),
) -> None:
    """Scan a repository for health issues and open an HTML report in the browser.

    Works on local repos and public GitHub repos:

      ghostlint scan                               # current directory
      ghostlint scan ~/myrepo                      # local path
      ghostlint scan --github owner/repo           # public GitHub repo
      ghostlint scan --github astropy/astropy      # e.g. scan astropy
      ghostlint scan --github https://github.com/owner/repo

    Options:

      ghostlint scan --headless                    # no browser, terminal only
      ghostlint scan -e dead_code                  # single engine
      ghostlint scan --quick                       # fast engines (pre-commit)
      ghostlint scan --format json                 # CI / machine-readable
      ghostlint scan -x web-new -x node_modules   # exclude directories
      ghostlint scan -x "*.generated.py"           # exclude by glob
    """
    # ── Resolve repo path ──────────────────────────────────────────────────────
    cloned_tmp: Optional[Path] = None
    if github:
        clone_url = _resolve_github_url(github)
        cloned_tmp = _clone_repo(clone_url)
        repo_path = cloned_tmp
    else:
        repo_path = (path or Path(".")).resolve()
        if not repo_path.exists():
            console.print(f"[red]Path does not exist:[/red] {repo_path}")
            raise typer.Exit(code=2)

    try:
        _run_scan(
            repo_path=repo_path,
            engine=engine,
            quick=quick,
            format=format,
            min_confidence=min_confidence,
            changed=changed,
            output=output,
            headless=headless,
            exclude=exclude or [],
        )
    finally:
        if cloned_tmp is not None:
            shutil.rmtree(cloned_tmp, ignore_errors=True)


def _run_scan(
    repo_path: Path,
    engine,
    quick: bool,
    format: str,
    min_confidence: float,
    changed: bool,
    output: Optional[Path],
    headless: bool,
    exclude: list[str] | None = None,
) -> None:
    if quick:
        engines = [FAST_ENGINES]
    elif engine:
        engines = list(engine)
    else:
        engines = [ALL_ENGINES]

    changed_files: list[str] | None = None
    if changed:
        from ghostlint_engine.git_analyzer import GitAnalyzer
        analyzer = GitAnalyzer(repo_path)
        if analyzer.is_git_repo():
            changed_files = analyzer.get_changed_files()
            if not changed_files:
                console.print("[yellow]No changed files detected vs HEAD.[/yellow]")
        else:
            console.print("[yellow]Not a git repository — ignoring --changed flag.[/yellow]")

    from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn, MofNCompleteColumn

    config = ScanConfig(
        repo_path=repo_path,
        scan_mode="quick" if quick else "full",
        confidence_threshold=min_confidence,
        engines=engines,
        changed_files=changed_files,
        exclude_paths=exclude or [],
    )
    scanner = Scanner(config)

    with Progress(
        BarColumn(bar_width=32),
        MofNCompleteColumn(),
        TextColumn("[dim]{task.percentage:>3.0f}%[/dim]"),
        TextColumn(" [bold]{task.description}[/bold][dim]...[/dim]"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Starting", total=None)

        def _on_progress(stage: str, current: int, total: int) -> None:
            progress.update(task, description=stage, completed=current, total=total)

        config.on_progress = _on_progress
        result = scanner.scan()

        # Show "Preparing report" while HTML is generated — keeps the bar visible
        # during the delay between engines finishing and the browser opening.
        if format != "json":
            from ghostlint_cli.html_report import generate_html_report
            from ghostlint_cli.web_server import prepare_report_dir
            current_total = progress.tasks[task].total or 1
            progress.update(
                task,
                description="Preparing report",
                completed=current_total,
                total=current_total,
            )
            html_content = generate_html_report(result)
            serve_dir, html_path = prepare_report_dir(html_content)

    # ── Output ─────────────────────────────────────────────────────────────────
    if format == "json":
        import json
        payload = {
            "id": result.id,
            "repo_path": result.repo_path,
            "health_score": result.health_score.overall,
            "files_scanned": result.files_scanned,
            "symbols_found": result.symbols_found,
            "findings_count": len(result.findings),
            "git_metrics": {
                "available": result.git_metrics.available,
                "stability_index": result.git_metrics.stability_index,
                "maintenance_velocity": result.git_metrics.maintenance_velocity,
                "refactor_completion_rate": result.git_metrics.refactor_completion_rate,
                "friction_index": result.git_metrics.friction_index,
                "total_commits_analyzed": result.git_metrics.total_commits_analyzed,
                "repo_age_days": result.git_metrics.repo_age_days,
                "top_contributors": result.git_metrics.top_contributors,
            },
            "findings": [
                {
                    "id": f.id,
                    "category": f.category.value,
                    "title": f.title,
                    "file": f.primary_file,
                    "line": f.primary_line,
                    "confidence": f.confidence,
                    "risk": f.risk.value,
                }
                for f in result.findings
            ],
        }
        if output is not None:
            if output.parent and not output.parent.exists():
                console.print(f"[red]Error: output directory does not exist: {output.parent}[/red]")
                raise typer.Exit(code=2)
            output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            console.print(f"[dim]JSON report written to[/dim] [bold]{output}[/bold]\n")
        else:
            console.print_json(json.dumps(payload))

    elif output is not None:
        if output.parent and not output.parent.exists():
            console.print(f"[red]Error: output directory does not exist: {output.parent}[/red]")
            raise typer.Exit(code=2)
        file_console = Console(file=output.open("w", encoding="utf-8"),
                               width=120, force_terminal=False, no_color=True)
        print_scan_result(result, console=file_console)
        file_console.file.close()
        print_findings_summary(result)
        _print_git_metrics_summary(result)
        console.print(f"[dim]Full report written to[/dim] [bold]{output}[/bold]\n")

    else:
        # Terminal: always print summary + git metrics
        print_findings_summary(result)
        _print_git_metrics_summary(result)

    # ── HTML report + browser (unless JSON mode or headless) ───────────────────
    if format != "json":
        import time
        from ghostlint_cli.web_server import serve_and_open, cleanup_report_dir

        try:
            _port, url, _thread = serve_and_open(
                serve_dir, html_path, open_browser=not headless
            )

            if not headless:
                console.print(f"\n[dim]HTML report served at[/dim] [bold cyan]{url}[/bold cyan]")
                console.print("[dim]Press Ctrl-C to exit.[/dim]\n")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    console.print("\n[dim]Bye.[/dim]")
            else:
                console.print(f"\n[dim]HTML report (headless): {html_path}[/dim]")
        finally:
            if not headless:
                cleanup_report_dir(serve_dir)

    # Exit non-zero if health score is critically low (useful for CI)
    if result.health_score.overall < 50:
        raise typer.Exit(code=1)


@app.command()
def report() -> None:
    """Show the most recent scan report for this directory."""
    from ghostlint_engine.db.session import get_session
    from ghostlint_engine.db.models import ScanRecord
    from sqlalchemy import desc

    session = get_session()
    record = (
        session.query(ScanRecord)
        .order_by(desc(ScanRecord.started_at))
        .first()
    )
    session.close()

    if not record:
        console.print("[yellow]No scans found. Run [bold]ghostlint scan[/bold] first.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]Last scan:[/bold] {record.started_at.strftime('%Y-%m-%d %H:%M')}  "
                  f"[dim]{record.repo_path}[/dim]")
    console.print(f"[bold]Health Score:[/bold] {record.health_score_overall:.1f} / 100")
    console.print(f"Files: {record.files_scanned}  Symbols: {record.symbols_found}  "
                  f"Findings: {len(record.findings)}\n")

    if record.findings:
        from rich.table import Table
        from rich import box
        t = Table(box=box.SIMPLE)
        t.add_column("Category", style="dim")
        t.add_column("Title")
        t.add_column("File", style="dim")
        t.add_column("Conf", justify="right")
        for f in record.findings:
            t.add_row(f.category, f.title, f.file_path, f"{f.confidence:.0%}")
        console.print(t)


@app.command()
def engines() -> None:  # noqa: F811 (this is the actual CLI command, not a shadowed name)
    """List all available detection engines and their status."""
    from ghostlint_engine.detectors.registry import get_registry
    from rich.table import Table
    from rich import box

    t = Table(box=box.SIMPLE, header_style="bold dim")
    t.add_column("Engine", width=22)
    t.add_column("Label", width=24)
    t.add_column("Phase", justify="center", width=7)
    t.add_column("Speed", width=8)
    t.add_column("Description")

    for name, spec in get_registry().items():
        phase_style = "green" if spec.phase == 1 else "dim"
        status = f"[{phase_style}]Phase {spec.phase}[/{phase_style}]"
        t.add_row(name, spec.label, status, spec.speed, spec.description)

    console.print()
    console.print(t)
    console.print("[dim]Run a specific engine: ghostlint scan -e <engine>[/dim]\n")


@app.command()
def trends(
    path: Optional[Path] = typer.Argument(
        None, help="Repository path (default: current directory).",
        exists=False, file_okay=False, dir_okay=True, resolve_path=True,
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of past scans to show."),
) -> None:
    """Show health score trends and AI slop rate across past scans.

      ghostlint trends                 # current directory, last 10 scans
      ghostlint trends ~/myrepo -n 20  # specific repo, last 20 scans
    """
    from ghostlint_engine.db.session import get_session
    from ghostlint_engine.db.models import ScanRecord
    from sqlalchemy import asc
    from rich.table import Table
    from rich import box
    import json
    from collections import Counter

    repo_path = str((path or Path(".")).resolve())
    session = get_session()
    try:
        records = (
            session.query(ScanRecord)
            .filter(ScanRecord.repo_path == repo_path, ScanRecord.status == "completed")
            .order_by(asc(ScanRecord.started_at))
            .limit(limit)
            .all()
        )
        if not records:
            console.print(f"[yellow]No scan history for {repo_path}. Run [bold]ghostlint scan[/bold] first.[/yellow]")
            return

        # Materialise findings counts per category per record
        rows = []
        for r in records:
            scores = json.loads(r.health_score_json) if r.health_score_json else {}
            by_cat: Counter = Counter(f.category for f in r.findings)
            rows.append({
                "date": r.started_at.strftime("%Y-%m-%d %H:%M"),
                "sha": (r.commit_sha or "")[:8],
                "overall": r.health_score_overall or 0.0,
                "dead": scores.get("dead_code", 0.0),
                "dup": scores.get("duplicate_logic", 0.0),
                "arch": scores.get("architectural_drift", 0.0),
                "dead_n": by_cat.get("dead_code", 0),
                "dup_n": by_cat.get("duplicate_logic", 0),
                "files": r.files_scanned,
            })
    finally:
        session.close()

    def _arrow(prev: float, curr: float, higher_is_better: bool = True) -> str:
        delta = curr - prev
        if abs(delta) < 0.5:
            return "[dim]─[/dim]"
        up = delta > 0
        good = up if higher_is_better else not up
        symbol = "▲" if up else "▼"
        colour = "green" if good else "red"
        return f"[{colour}]{symbol}{abs(delta):.1f}[/{colour}]"

    def _score_style(s: float) -> str:
        if s >= 80: return f"[green]{s:.1f}[/green]"
        if s >= 60: return f"[yellow]{s:.1f}[/yellow]"
        return f"[red]{s:.1f}[/red]"

    t = Table(
        title=f"Trend — {repo_path}",
        box=box.SIMPLE,
        header_style="bold dim",
    )
    t.add_column("Date", width=16)
    t.add_column("SHA", width=9)
    t.add_column("Overall", justify="right", width=9)
    t.add_column("Δ", width=7)
    t.add_column("Dead code", justify="right", width=10)
    t.add_column("Dup logic", justify="right", width=10)
    t.add_column("Arch drift", justify="right", width=11)
    t.add_column("AI slop ¹", justify="right", width=10)
    t.add_column("Files", justify="right", width=6)

    for i, row in enumerate(rows):
        prev = rows[i - 1] if i > 0 else None
        overall_arrow = _arrow(prev["overall"], row["overall"]) if prev else ""
        # AI slop = dead code + duplicate logic finding count (size-normalised)
        slop = row["dead_n"] + row["dup_n"]
        prev_slop = (prev["dead_n"] + prev["dup_n"]) if prev else None
        if prev_slop is not None:
            slop_delta = slop - prev_slop
            slop_colour = "red" if slop_delta > 0 else "green" if slop_delta < 0 else "dim"
            slop_str = f"[{slop_colour}]{slop}[/{slop_colour}]"
        else:
            slop_str = str(slop)

        t.add_row(
            row["date"],
            f"[dim]{row['sha']}[/dim]" if row["sha"] else "[dim]—[/dim]",
            _score_style(row["overall"]),
            overall_arrow,
            _score_style(row["dead"]),
            _score_style(row["dup"]),
            _score_style(row["arch"]),
            slop_str,
            str(row["files"]),
        )

    console.print()
    console.print(t)
    console.print("[dim]¹ AI slop = dead code + duplicate logic finding count (lower is better)[/dim]\n")


@app.command()
def compare(
    sha1: str = typer.Argument(..., help="Older commit SHA (e.g. HEAD~10, abc1234)."),
    sha2: str = typer.Argument(..., help="Newer commit SHA (e.g. HEAD, def5678)."),
    path: Optional[Path] = typer.Option(
        None, "--path", "-p",
        help="Local repository path (default: current directory). Ignored when --github is set.",
        exists=False, file_okay=False, dir_okay=True, resolve_path=True,
    ),
    github: Optional[str] = typer.Option(
        None, "--github", "-g",
        help="GitHub repo to clone before comparing. Accepts 'owner/repo' or a full HTTPS URL.",
    ),
    exclude: Optional[list[str]] = typer.Option(
        None, "--exclude", "-x",
        help="Exclude paths or patterns (same semantics as ghostlint scan --exclude).",
    ),
) -> None:
    """Compare health scores between two commits.

      ghostlint compare HEAD~10 HEAD
      ghostlint compare abc1234 def5678 --path ~/myrepo
      ghostlint compare HEAD~50 HEAD --github django/django
      ghostlint compare HEAD~50 HEAD --github https://github.com/django/django.git
    """
    import subprocess
    import shutil
    from ghostlint_engine.scanner import Scanner, ScanConfig, ALL_ENGINES
    from rich.table import Table
    from rich import box

    cloned_tmp: Optional[Path] = None
    if github:
        clone_url = _resolve_github_url(github)
        depth = _compute_clone_depth(sha1, sha2)
        cloned_tmp = _clone_repo(clone_url, depth=depth)
        repo_path = cloned_tmp
    else:
        repo_path = (path or Path(".")).resolve()
        if not repo_path.exists():
            console.print(f"[red]Path does not exist: {repo_path}[/red]")
            raise typer.Exit(code=1)

    def _scan_at_sha(sha: str) -> tuple:
        """Check out sha into a git worktree, scan it, return (result, worktree_path)."""
        worktree = Path(tempfile.mkdtemp(prefix=f"ghostlint_cmp_"))
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_path), "worktree", "add", "--detach", str(worktree), sha],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                console.print(f"[red]git worktree add failed for {sha}:[/red] {proc.stderr.strip()}")
                raise typer.Exit(code=1)

            config = ScanConfig(
                repo_path=worktree,
                scan_mode="full",
                engines=[ALL_ENGINES],
                exclude_paths=exclude or [],
                skip_persist=True,  # don't pollute history with temp scans
            )
            result = Scanner(config).scan()
            return result, worktree
        except Exception:
            shutil.rmtree(worktree, ignore_errors=True)
            subprocess.run(
                ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(worktree)],
                capture_output=True,
            )
            raise

    def _cleanup(worktree: Path) -> None:
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
        )
        shutil.rmtree(worktree, ignore_errors=True)

    try:
        console.print(f"\n[dim]Checking out[/dim] [bold]{sha1}[/bold][dim] …[/dim]")
        r1, wt1 = _scan_at_sha(sha1)
        console.print(f"[dim]Checking out[/dim] [bold]{sha2}[/bold][dim] …[/dim]")
        r2, wt2 = _scan_at_sha(sha2)
        _cleanup(wt1)
        _cleanup(wt2)
    finally:
        if cloned_tmp:
            shutil.rmtree(cloned_tmp, ignore_errors=True)

    def _delta(a: float, b: float, higher_is_better: bool = True) -> str:
        d = b - a
        if abs(d) < 0.1:
            return "[dim]  ─[/dim]"
        up = d > 0
        good = up if higher_is_better else not up
        colour = "green" if good else "red"
        sign = "+" if d > 0 else ""
        return f"[{colour}]{sign}{d:.1f}[/{colour}]"

    def _finding_delta(a: int, b: int) -> str:
        d = b - a
        if d == 0: return "[dim]  ─[/dim]"
        colour = "red" if d > 0 else "green"
        sign = "+" if d > 0 else ""
        return f"[{colour}]{sign}{d}[/{colour}]"

    from collections import Counter
    cat1 = Counter(f.category.value for f in r1.findings)
    cat2 = Counter(f.category.value for f in r2.findings)

    hs1, hs2 = r1.health_score, r2.health_score

    t = Table(
        title=f"Compare  {sha1[:8]}  →  {sha2[:8]}",
        box=box.SIMPLE,
        header_style="bold dim",
    )
    t.add_column("Metric", width=26)
    t.add_column(sha1[:8], justify="right", width=10)
    t.add_column(sha2[:8], justify="right", width=10)
    t.add_column("Δ", width=8)

    def _row(label, v1, v2, fmt=".1f", higher_is_better=True):
        delta = _delta(v1, v2, higher_is_better)
        t.add_row(label, f"{v1:{fmt}}", f"{v2:{fmt}}", delta)

    def _cat_row(label, key):
        n1, n2 = cat1.get(key, 0), cat2.get(key, 0)
        t.add_row(label, str(n1), str(n2), _finding_delta(n1, n2))

    _row("Overall health score",   hs1.overall,              hs2.overall)
    _row("Dead code score",        hs1.dead_code,            hs2.dead_code)
    _row("Duplicate logic score",  hs1.duplicate_logic,      hs2.duplicate_logic)
    _row("Arch drift score",       hs1.architectural_drift,  hs2.architectural_drift)
    _row("Test health score",      hs1.test_health,          hs2.test_health)
    t.add_row("", "", "", "")  # spacer
    _row("Files scanned",          r1.files_scanned,         r2.files_scanned,         fmt="d")
    _row("Symbols found",          r1.symbols_found,         r2.symbols_found,          fmt="d")
    t.add_row("", "", "", "")  # spacer
    _cat_row("Dead code findings",      "dead_code")
    _cat_row("Duplicate logic findings","duplicate_logic")
    _cat_row("Arch drift findings",     "architectural_drift")
    _cat_row("Refactor findings",       "refactor_completion")
    _cat_row("Test health findings",    "test_health")
    t.add_row("", "", "", "")  # spacer
    slop1 = cat1.get("dead_code", 0) + cat1.get("duplicate_logic", 0)
    slop2 = cat2.get("dead_code", 0) + cat2.get("duplicate_logic", 0)
    t.add_row("AI slop total ¹", str(slop1), str(slop2), _finding_delta(slop1, slop2))

    console.print()
    console.print(t)
    console.print("[dim]¹ AI slop = dead code + duplicate logic findings (lower is better)[/dim]\n")


# ── MCP subcommand group ──────────────────────────────────────────────────────

mcp_app = typer.Typer(
    name="mcp",
    help="MCP (Model Context Protocol) server — connect ghostlint to AI coding tools.",
    invoke_without_command=True,
    add_completion=False,
)
app.add_typer(mcp_app)


@mcp_app.callback()
def mcp_callback(ctx: typer.Context) -> None:
    """Launch the ghostlint MCP stdio server, or run a subcommand (setup, info)."""
    if ctx.invoked_subcommand is None:
        # No subcommand → start the server
        _mcp_start()


def _mcp_start() -> None:
    """Start the ghostlint MCP stdio server."""
    from ghostlint_mcp.server import mcp as mcp_server
    mcp_server.run(transport="stdio")


@mcp_app.command("setup")
def mcp_setup(
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Preview config changes without writing any files.",
    ),
    tool: Optional[str] = typer.Option(
        None, "--tool", "-t",
        help="Limit setup to a specific AI tool (e.g. 'cursor', 'claude').",
    ),
) -> None:
    """Auto-configure ghostlint as an MCP server for installed AI coding tools.

    Detects Claude Code, Cursor, Windsurf, and Zed and writes or patches
    their MCP config files. Existing ghostlint entries are updated in-place;
    other tools in the config are untouched.

    Examples:

      ghostlint mcp setup              # configure all detected tools

      ghostlint mcp setup --dry-run    # preview without writing

      ghostlint mcp setup --tool cursor  # configure Cursor only
    """
    from ghostlint_cli.mcp_setup import run_setup, print_manual_snippet
    from rich.table import Table
    from rich import box

    console.print()
    if dry_run:
        console.print("[bold yellow]Dry run — no files will be written[/bold yellow]\n")

    results = run_setup(dry_run=dry_run, tool_filter=tool)

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
    t.add_column("AI Tool", width=16)
    t.add_column("Status")

    any_configured = False
    for tool_name, status in results:
        if "not detected" in status:
            t.add_row(tool_name, f"[dim]{status}[/dim]")
        elif "already configured" in status:
            t.add_row(tool_name, f"[green]✓[/green] {status}")
        elif "would write" in status or "written" in status:
            t.add_row(tool_name, f"[cyan]→[/cyan] {status}")
            any_configured = True
        else:
            t.add_row(tool_name, status)

    console.print(t)

    if not any_configured and not dry_run:
        console.print(
            "\n[yellow]No AI tools were detected automatically.[/yellow]\n"
            "Add the following to your tool's MCP config manually:\n"
        )
        console.print(print_manual_snippet())
    else:
        console.print(
            "\n[dim]Restart your AI tool to pick up the new MCP server.[/dim]\n"
            "[dim]Verify with:[/dim] [bold]ghostlint mcp info[/bold]\n"
        )


@mcp_app.command("info")
def mcp_info() -> None:
    """Show the MCP server entry point and available tools."""
    import sys
    from ghostlint_cli.mcp_setup import _server_entry, _ghostlint_on_path

    console.print("\n[bold]ghostlint MCP server[/bold]\n")

    entry = _server_entry()
    console.print(f"  command : [cyan]{entry['command']}[/cyan]")
    console.print(f"  args    : [cyan]{entry['args']}[/cyan]")
    if not _ghostlint_on_path():
        console.print(
            "  [yellow]Note: 'ghostlint' not found in PATH — using current Python interpreter.[/yellow]\n"
            "  [dim]Install globally with: pip install ghostlint  or  uv tool install ghostlint[/dim]"
        )

    console.print("\n[bold dim]Available MCP tools[/bold dim]\n")
    tools = [
        ("scan_repo",                    "Full health scan of a local path or GitHub repo"),
        ("scan_files",                   "Targeted scan scoped to specific files (partial context)"),
        ("get_health_context",           "Return the last cached scan without re-scanning"),
        ("list_findings",                "Filtered query over findings from the last scan"),
        ("check_diff",                   "Predict impact of a proposed diff before applying it"),
        ("repository_overview",          "Filesystem-only overview (languages, frameworks, entry points)"),
        ("repository_health",            "Lean health summary (score, findings, git signals)"),
        ("repository_metrics",           "Composite metrics (health, categories, hotspots, git)"),
        ("repository_timeline",          "Health-score trend from persisted scan history"),
        ("find_dead_code",               "Dead-code findings (unused functions/modules)"),
        ("find_duplicate_logic",         "Structurally identical function duplications"),
        ("find_incomplete_refactors",    "Coexisting old/new APIs and migration leftovers"),
        ("find_architecture_violations", "Layer violations and circular imports"),
        ("find_repository_patterns",     "Recurring patterns synthesized from findings"),
        ("explain_repository_history",   "Git-history narrative + contributors + metrics"),
        ("recommend_cleanup",            "Cleanup recommendations ordered quick-wins-first"),
        ("estimate_cleanup_effort",      "Aggregate effort estimate (hours/days, breakdowns)"),
        ("generate_cleanup_plan",        "Phased, ordered cleanup plan with effort per phase"),
        ("search_repository_knowledge",  "Deterministic keyword search over findings + files"),
    ]
    for name, desc in tools:
        console.print(f"  [bold cyan]{name:<32}[/bold cyan]  {desc}")
    console.print()


if __name__ == "__main__":
    app()
