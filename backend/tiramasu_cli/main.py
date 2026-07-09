from __future__ import annotations
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from tiramasu_engine.scanner import Scanner, ScanConfig, ALL_ENGINES, FAST_ENGINES
from tiramasu_cli.output import print_scan_result, scan_spinner

app = typer.Typer(
    name="tiramasu",
    help="Repository Health Intelligence — detect dead code, duplicates, drift.",
    add_completion=False,
)
console = Console()


@app.command()
def scan(
    path: Path = typer.Argument(
        Path("."),
        help="Path to the repository to scan (default: current directory)",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
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
) -> None:
    """Scan a repository for health issues.

    Examples:

      tiramasu scan                          # all engines, current directory

      tiramasu scan ~/myrepo                 # all engines, specific path

      tiramasu scan -e dead_code             # dead code engine only

      tiramasu scan -e dead_code -e refactor # two engines

      tiramasu scan --quick                  # fast engines only (pre-commit)

      tiramasu scan --format json            # machine-readable output for CI
    """
    if quick:
        engines = [FAST_ENGINES]
    elif engine:
        engines = list(engine)
    else:
        engines = [ALL_ENGINES]

    config = ScanConfig(
        repo_path=path,
        scan_mode="quick" if quick else "full",
        confidence_threshold=min_confidence,
        engines=engines,
    )
    scanner = Scanner(config)

    with scan_spinner() as progress:
        task = progress.add_task(f"Scanning [bold]{path}[/bold] …", total=None)
        result = scanner.scan()
        progress.update(task, completed=True)

    if format == "json":
        import json, dataclasses
        console.print_json(json.dumps({
            "id": result.id,
            "repo_path": result.repo_path,
            "health_score": result.health_score.overall,
            "files_scanned": result.files_scanned,
            "symbols_found": result.symbols_found,
            "findings_count": len(result.findings),
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
        }))
    else:
        print_scan_result(result)

    # Exit non-zero if health score is critically low (useful for CI)
    if result.health_score.overall < 50:
        raise typer.Exit(code=1)


@app.command()
def report() -> None:
    """Show the most recent scan report for this directory."""
    from tiramasu_engine.db.session import get_session
    from tiramasu_engine.db.models import ScanRecord
    from sqlalchemy import desc

    session = get_session()
    record = (
        session.query(ScanRecord)
        .order_by(desc(ScanRecord.started_at))
        .first()
    )
    session.close()

    if not record:
        console.print("[yellow]No scans found. Run [bold]tiramasu scan[/bold] first.[/yellow]")
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
def engines() -> None:
    """List all available detection engines and their status."""
    from tiramasu_engine.detectors.registry import get_registry
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
    console.print("[dim]Run a specific engine: tiramasu scan -e <engine>[/dim]\n")


if __name__ == "__main__":
    app()
