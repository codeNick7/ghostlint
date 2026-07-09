from __future__ import annotations
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
from tiramasu_engine.models.findings import ScanResult, RiskLevel

console = Console()

_SCORE_COLOR = {
    (90, 101): "bold green",
    (70, 90): "bold yellow",
    (50, 70): "bold orange1",
    (0, 50): "bold red",
}

_RISK_STYLE = {
    RiskLevel.LOW: "green",
    RiskLevel.MEDIUM: "yellow",
    RiskLevel.HIGH: "red",
}


def _score_color(score: float) -> str:
    for (lo, hi), color in _SCORE_COLOR.items():
        if lo <= score < hi:
            return color
    return "white"


def print_scan_result(result: ScanResult) -> None:
    hs = result.health_score
    score_color = _score_color(hs.overall)
    duration = (result.completed_at - result.started_at).total_seconds()

    console.print()
    console.print(Panel.fit(
        f"[{score_color}]{hs.overall:.1f} / 100[/{score_color}]  Repository Health Score",
        title="[bold]tiramasu[/bold]",
        subtitle=f"{result.files_scanned} files · {result.symbols_found} symbols · {duration:.1f}s",
        border_style="dim",
    ))
    console.print()

    # Score breakdown table
    breakdown = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
    breakdown.add_column("Category", style="dim", width=28)
    breakdown.add_column("Score", justify="right", width=8)
    breakdown.add_column("Status", width=12)

    rows = [
        ("Dead Code", hs.dead_code),
        ("Duplicate Logic", hs.duplicate_logic),
        ("Refactor Completion", hs.refactor_completion),
        ("Architectural Drift", hs.architectural_drift),
        ("Dependency Health", hs.dependency_health),
        ("Documentation", hs.documentation_freshness),
        ("Test Health", hs.test_health),
        ("Config Consistency", hs.config_consistency),
    ]
    for name, score in rows:
        color = _score_color(score)
        status = "✓ Healthy" if score >= 90 else ("⚠ Review" if score >= 70 else "✗ Issues")
        breakdown.add_row(name, f"[{color}]{score:.1f}[/{color}]", status)

    console.print(breakdown)

    if not result.findings:
        console.print("[bold green]No issues found.[/bold green]")
        return

    console.print(f"[bold]Findings[/bold]  ({len(result.findings)} total)\n")

    findings_table = Table(box=box.ROUNDED, show_lines=True)
    findings_table.add_column("#", style="dim", width=4)
    findings_table.add_column("Title", width=42)
    findings_table.add_column("File", style="dim", width=36)
    findings_table.add_column("Line", justify="right", width=6)
    findings_table.add_column("Conf", justify="right", width=6)
    findings_table.add_column("Risk", width=8)

    for i, f in enumerate(result.findings, 1):
        risk_style = _RISK_STYLE.get(f.risk, "white")
        findings_table.add_row(
            str(i),
            f.title,
            f.primary_file,
            str(f.primary_line),
            f"{f.confidence:.0%}",
            f"[{risk_style}]{f.risk.value}[/{risk_style}]",
        )

    console.print(findings_table)
    console.print()

    console.print("[bold]Top Recommendations[/bold]\n")
    for i, rec in enumerate(result.recommendations[:10], 1):
        risk_style = _RISK_STYLE.get(rec.risk, "white")
        console.print(
            f"  [{risk_style}]{i:2}.[/{risk_style}] {rec.title}  "
            f"[dim](confidence {rec.confidence:.0%} · {rec.effort.value})[/dim]"
        )
    console.print()


def scan_spinner() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    )
