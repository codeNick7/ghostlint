from __future__ import annotations
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
from tiramisu_engine.models.findings import ScanResult, RiskLevel

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


def _print_score_panel(result: ScanResult, console: Console) -> None:
    hs = result.health_score
    score_color = _score_color(hs.overall)
    duration = (result.completed_at - result.started_at).total_seconds()
    console.print()
    console.print(Panel.fit(
        f"[{score_color}]{hs.overall:.1f} / 100[/{score_color}]  Repository Health Score",
        title="[bold]tiramisu[/bold]",
        subtitle=f"{result.files_scanned} files · {result.symbols_found} symbols · {duration:.1f}s",
        border_style="dim",
    ))
    console.print()


def _print_breakdown(result: ScanResult, console: Console) -> None:
    hs = result.health_score
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


def _print_findings_table(result: ScanResult, console: Console) -> None:
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


def _print_recommendations(result: ScanResult, console: Console) -> None:
    console.print("[bold]Top Recommendations[/bold]\n")
    for i, rec in enumerate(result.recommendations[:10], 1):
        risk_style = _RISK_STYLE.get(rec.risk, "white")
        console.print(
            f"  [{risk_style}]{i:2}.[/{risk_style}] {rec.title}  "
            f"[dim](confidence {rec.confidence:.0%} · {rec.effort.value})[/dim]"
        )
    console.print()


def print_scan_result(result: ScanResult, console: Console | None = None) -> None:
    """Print the full report: score panel + breakdown + findings + recommendations.

    When ``console`` is given (e.g. a Console writing to a file), the full
    report is rendered there — used by the ``--output`` option to dump the
    complete report to a text file.
    """
    c = console if console is not None else globals()["console"]
    _print_score_panel(result, c)
    _print_breakdown(result, c)

    if not result.findings:
        c.print("[bold green]No issues found.[/bold green]")
        return

    _print_findings_table(result, c)
    _print_recommendations(result, c)


def print_findings_summary(result: ScanResult, console: Console | None = None) -> None:
    """Compact terminal view: score panel + findings table only.

    Shown on the console when ``--output`` redirects the full report to a file,
    so the user still sees progress and the findings at a glance.
    """
    c = console if console is not None else globals()["console"]
    _print_score_panel(result, c)

    if not result.findings:
        c.print("[bold green]No issues found.[/bold green]")
        return

    _print_findings_table(result, c)


def write_json_report(result: ScanResult, path: Path) -> None:
    """Write the scan result as JSON to ``path`` (for ``--output --format json``)."""
    payload = {
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
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def scan_spinner() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    )
