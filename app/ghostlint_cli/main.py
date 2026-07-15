from __future__ import annotations
import shutil
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from ghostlint_engine.scanner import Scanner, ScanConfig, ALL_ENGINES, FAST_ENGINES
from ghostlint_cli.output import (
    print_scan_result, print_findings_summary, write_json_report, scan_spinner,
)

app = typer.Typer(
    name="ghostlint",
    help="Repository Health Intelligence — detect dead code, duplicates, drift.",
    add_completion=False,
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


def _clone_repo(url: str) -> Path:
    """Clone *url* into a temp directory and return its path."""
    import git as gitpython
    tmp = tempfile.mkdtemp(prefix="ghostlint_")
    console.print(f"[dim]Cloning [bold]{url}[/bold] …[/dim]")
    try:
        gitpython.Repo.clone_from(url, tmp, depth=200)
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        console.print(f"[red]Clone failed:[/red] {exc}")
        raise typer.Exit(code=2)
    return Path(tmp)


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
) -> None:
    """Scan a repository for health issues and open an HTML report in the browser.

    Examples:

      ghostlint scan                                     # current directory

      ghostlint scan ~/myrepo                            # specific local path

      ghostlint scan --github owner/repo                 # clone & scan GitHub repo

      ghostlint scan --github https://github.com/o/r    # full URL

      ghostlint scan --headless                          # terminal-only, no browser

      ghostlint scan -e dead_code                        # single engine

      ghostlint scan --quick                             # fast engines only (pre-commit)

      ghostlint scan --format json                       # machine-readable for CI
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

    config = ScanConfig(
        repo_path=repo_path,
        scan_mode="quick" if quick else "full",
        confidence_threshold=min_confidence,
        engines=engines,
        changed_files=changed_files,
    )
    scanner = Scanner(config)

    with scan_spinner() as progress:
        task = progress.add_task(f"Scanning [bold]{repo_path}[/bold] …", total=None)
        result = scanner.scan()
        progress.update(task, completed=True)

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
        from ghostlint_cli.html_report import generate_html_report
        from ghostlint_cli.web_server import prepare_report_dir, serve_and_open, cleanup_report_dir

        html_content = generate_html_report(result)
        serve_dir, html_path = prepare_report_dir(html_content)

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
