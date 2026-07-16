from __future__ import annotations
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from ghostlint_engine.models.findings import ScanResult, RiskLevel, HealthScore, GitMetrics

_RISK_COLOR = {
    RiskLevel.LOW: "#22c55e",
    RiskLevel.MEDIUM: "#f59e0b",
    RiskLevel.HIGH: "#ef4444",
}

_SCORE_COLOR = {
    (90, 101): "#22c55e",
    (70, 90): "#eab308",
    (50, 70): "#f97316",
    (0, 50): "#ef4444",
}


def _score_color(score: float) -> str:
    for (lo, hi), color in _SCORE_COLOR.items():
        if lo <= score < hi:
            return color
    return "#94a3b8"


def _score_label(score: float) -> str:
    if score >= 90:
        return "Healthy"
    if score >= 70:
        return "Review"
    if score >= 50:
        return "Caution"
    return "Critical"


def _h(text: str) -> str:
    return html.escape(str(text))


def _breakdown_rows_html(hs: HealthScore) -> str:
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
    html_rows = ""
    for name, score in rows:
        color = _score_color(score)
        label = _score_label(score)
        bar_w = max(int(score), 2)
        html_rows += f"""
        <tr>
          <td class="cat-name">{_h(name)}</td>
          <td class="cat-bar">
            <div class="bar-track">
              <div class="bar-fill" style="width:{bar_w}%;background:{color}"></div>
            </div>
          </td>
          <td class="cat-score" style="color:{color}">{score:.1f}</td>
          <td class="cat-label" style="color:{color}">{label}</td>
        </tr>"""
    return html_rows


def _findings_rows_html(result: ScanResult) -> str:
    if not result.findings:
        return '<tr><td colspan="6" style="text-align:center;color:#64748b">No issues found</td></tr>'
    rows = ""
    for i, f in enumerate(result.findings, 1):
        risk_color = _RISK_COLOR.get(f.risk, "#94a3b8")
        cat = f.category.value.replace("_", " ").title()
        file_short = f.primary_file[-50:] if len(f.primary_file) > 50 else f.primary_file
        rows += f"""
        <tr class="finding-row" data-risk="{_h(f.risk.value)}" data-category="{_h(f.category.value)}">
          <td style="color:#64748b;text-align:center">{i}</td>
          <td><span class="badge" style="background:{risk_color}22;color:{risk_color};border:1px solid {risk_color}44">{_h(f.risk.value.upper())}</span></td>
          <td style="color:#94a3b8;font-size:0.78rem">{_h(cat)}</td>
          <td>{_h(f.title)}</td>
          <td style="color:#64748b;font-size:0.78rem;font-family:monospace" title="{_h(f.primary_file)}">{_h(file_short)}</td>
          <td style="text-align:right;color:#94a3b8">{f.confidence:.0%}</td>
        </tr>"""
    return rows


def _recommendations_html(result: ScanResult) -> str:
    if not result.recommendations:
        return "<p style='color:#64748b'>No recommendations at this time.</p>"
    items = ""
    for i, rec in enumerate(result.recommendations[:10], 1):
        risk_color = _RISK_COLOR.get(rec.risk, "#94a3b8")
        items += f"""
        <div class="rec-item">
          <span class="rec-num" style="background:{risk_color}">{i}</span>
          <div class="rec-body">
            <div class="rec-title">{_h(rec.title)}</div>
            <div class="rec-meta">{_h(rec.description)}</div>
            <div class="rec-tags">
              <span class="tag">confidence {rec.confidence:.0%}</span>
              <span class="tag">{_h(rec.effort.value)}</span>
              {('<span class="tag tag-benefit">' + _h(rec.benefit) + '</span>') if rec.benefit else ''}
            </div>
          </div>
        </div>"""
    return items


def _git_metrics_html(gm: GitMetrics) -> str:
    if not gm.available:
        return """
        <div class="git-unavailable">
          <p>Git history metrics not available for this repository.</p>
        </div>"""

    def _metric_card(title: str, value: str, subtitle: str, color: str, note: str = "") -> str:
        return f"""
        <div class="metric-card">
          <div class="metric-title">{title}</div>
          <div class="metric-value" style="color:{color}">{value}</div>
          <div class="metric-subtitle">{subtitle}</div>
          {('<div class="metric-note">' + note + '</div>') if note else ''}
        </div>"""

    stability_color = _score_color(gm.stability_index)
    velocity_pct = gm.maintenance_velocity * 100
    velocity_color = "#22c55e" if velocity_pct >= 30 else ("#f59e0b" if velocity_pct >= 10 else "#ef4444")
    refactor_color = _score_color(gm.refactor_completion_rate)
    # friction: lower is better, invert for color
    friction_inv = 100 - gm.friction_index
    friction_color = _score_color(friction_inv)

    cards = (
        _metric_card(
            "Stability Index",
            f"{gm.stability_index:.1f}",
            "Architecture churn resistance",
            stability_color,
            "How often core files (models, routes, schemas) change",
        )
        + _metric_card(
            "Maintenance Velocity",
            f"{velocity_pct:.1f}%",
            "Fix-commit ratio (last 90 days)",
            velocity_color,
            "Share of commits with fix/resolve/close intent",
        )
        + _metric_card(
            "Refactor Completion",
            f"{gm.refactor_completion_rate:.1f}%",
            "Tech-debt marker trend",
            refactor_color,
            "TODO/FIXME/HACK count direction vs 30 commits ago",
        )
        + _metric_card(
            "Friction Index",
            f"{gm.friction_index:.1f}",
            "Cognitive overhead (lower = better)",
            friction_color,
            "Composite of file churn, ownership spread, large files",
        )
    )

    meta = f"""
    <div class="git-meta">
      <span>{gm.total_commits_analyzed} commits analyzed</span>
      <span>·</span>
      <span>{gm.repo_age_days} days old</span>
      <span>·</span>
      <span>{gm.top_contributors} contributors</span>
    </div>"""

    return f'<div class="metric-grid">{cards}</div>{meta}'


def _chart_data(hs: HealthScore) -> str:
    labels = ["Dead Code", "Dup. Logic", "Refactor", "Arch Drift",
              "Deps", "Docs", "Tests", "Config"]
    values = [
        hs.dead_code, hs.duplicate_logic, hs.refactor_completion,
        hs.architectural_drift, hs.dependency_health,
        hs.documentation_freshness, hs.test_health, hs.config_consistency,
    ]
    colors = [_score_color(v) for v in values]
    return json.dumps({"labels": labels, "values": values, "colors": colors})


def generate_html_report(result: ScanResult) -> str:
    repo_name = Path(result.repo_path).name
    scan_date = result.started_at.astimezone().strftime("%Y-%m-%d %H:%M")
    duration = (result.completed_at - result.started_at).total_seconds()
    overall_color = _score_color(result.health_score.overall)
    chart_data = _chart_data(result.health_score)

    category_options = sorted({f.category.value for f in result.findings})
    cat_options_html = "".join(
        f'<option value="{_h(c)}">{_h(c.replace("_", " ").title())}</option>'
        for c in category_options
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ghostlint · {_h(repo_name)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" integrity="sha384-e6nUZLBkQ86NJ6TVVKAeSaK8jWa3NhkYWZFomE39AvDbQWeie9PlQqM3pmYW5d1g" crossorigin="anonymous"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0f172a; --surface: #1e293b; --surface2: #263147;
    --border: #334155; --text: #e2e8f0; --muted: #94a3b8;
    --accent: #6366f1;
  }}
  body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg);
          color: var(--text); min-height: 100vh; }}
  header {{ background: var(--surface); border-bottom: 1px solid var(--border);
            padding: 1.25rem 2rem; display: flex; align-items: center; gap: 1rem; }}
  .logo {{ font-size: 1.4rem; font-weight: 700; color: var(--accent); letter-spacing: -0.5px; }}
  .header-meta {{ color: var(--muted); font-size: 0.85rem; margin-left: auto; text-align: right; }}
  main {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
  section {{ margin-bottom: 2.5rem; }}
  h2 {{ font-size: 1.05rem; font-weight: 600; color: var(--muted);
        text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 1rem;
        border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}

  /* Score hero */
  .score-hero {{ display: flex; gap: 2rem; align-items: stretch; flex-wrap: wrap; }}
  .score-circle {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
                   padding: 2.5rem; display: flex; flex-direction: column; align-items: center;
                   justify-content: center; min-width: 200px; }}
  .score-num {{ font-size: 4rem; font-weight: 800; line-height: 1; color: {overall_color}; }}
  .score-denom {{ font-size: 1.2rem; color: var(--muted); margin-top: 0.25rem; }}
  .score-label {{ font-size: 0.9rem; margin-top: 0.75rem; font-weight: 600;
                  color: {overall_color}; text-transform: uppercase; letter-spacing: 0.05em; }}
  .score-stats {{ display: flex; gap: 1rem; color: var(--muted); font-size: 0.82rem;
                  margin-top: 0.75rem; flex-wrap: wrap; justify-content: center; }}
  .chart-card {{ flex: 1; background: var(--surface); border: 1px solid var(--border);
                 border-radius: 16px; padding: 1.5rem; min-height: 220px; min-width: 300px; }}

  /* Breakdown table */
  .breakdown-table {{ width: 100%; border-collapse: collapse; }}
  .breakdown-table td {{ padding: 0.55rem 0.5rem; vertical-align: middle; }}
  .cat-name {{ color: var(--text); font-size: 0.9rem; width: 200px; }}
  .cat-bar {{ width: 100%; }}
  .bar-track {{ height: 8px; background: var(--surface2); border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ height: 8px; border-radius: 4px; transition: width 0.5s; }}
  .cat-score {{ width: 60px; text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .cat-label {{ width: 80px; font-size: 0.8rem; text-align: right; }}

  /* Git metrics */
  .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 1rem; }}
  .metric-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
                  padding: 1.25rem; }}
  .metric-title {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;
                   color: var(--muted); margin-bottom: 0.5rem; }}
  .metric-value {{ font-size: 2.2rem; font-weight: 700; line-height: 1; }}
  .metric-subtitle {{ font-size: 0.82rem; color: var(--muted); margin-top: 0.35rem; }}
  .metric-note {{ font-size: 0.75rem; color: #475569; margin-top: 0.5rem; }}
  .git-meta {{ display: flex; gap: 0.75rem; color: var(--muted); font-size: 0.8rem;
               margin-top: 1rem; flex-wrap: wrap; }}
  .git-unavailable {{ color: var(--muted); padding: 1.5rem; background: var(--surface);
                      border-radius: 12px; border: 1px solid var(--border); }}

  /* Findings */
  .filters {{ display: flex; gap: 0.75rem; margin-bottom: 1rem; flex-wrap: wrap; }}
  .filter-select {{ background: var(--surface); border: 1px solid var(--border); color: var(--text);
                    border-radius: 6px; padding: 0.4rem 0.75rem; font-size: 0.85rem; cursor: pointer; }}
  .findings-table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  .findings-table th {{ text-align: left; padding: 0.5rem 0.75rem; color: var(--muted);
                        font-weight: 500; font-size: 0.78rem; text-transform: uppercase;
                        letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }}
  .findings-table td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border)22; }}
  .findings-table tr:hover td {{ background: var(--surface2); }}
  .badge {{ display: inline-block; border-radius: 4px; padding: 0.15rem 0.45rem;
             font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em; }}
  .no-findings {{ text-align: center; padding: 2rem; color: var(--muted); }}

  /* Recommendations */
  .rec-item {{ display: flex; gap: 1rem; padding: 1rem; background: var(--surface);
               border: 1px solid var(--border); border-radius: 10px; margin-bottom: 0.75rem; }}
  .rec-num {{ width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center;
              justify-content: center; font-size: 0.8rem; font-weight: 700; color: white;
              flex-shrink: 0; margin-top: 0.1rem; }}
  .rec-body {{ flex: 1; }}
  .rec-title {{ font-weight: 600; color: var(--text); margin-bottom: 0.25rem; }}
  .rec-meta {{ font-size: 0.83rem; color: var(--muted); margin-bottom: 0.5rem; }}
  .rec-tags {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
  .tag {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 4px;
          padding: 0.1rem 0.45rem; font-size: 0.72rem; color: var(--muted); }}
  .tag-benefit {{ color: #6366f1; border-color: #6366f144; background: #6366f111; }}

  footer {{ text-align: center; padding: 2rem; color: #334155; font-size: 0.78rem; }}
</style>
</head>
<body>
<header>
  <span class="logo">ghostlint</span>
  <span style="color:#334155;font-size:1.2rem">/</span>
  <span style="font-weight:600">{_h(repo_name)}</span>
  <div class="header-meta">
    <div>Repository Health Report</div>
    <div>{_h(scan_date)} · {duration:.1f}s</div>
  </div>
</header>

<main>

<section>
  <h2>Health Score</h2>
  <div class="score-hero">
    <div class="score-circle">
      <div class="score-num">{result.health_score.overall:.1f}</div>
      <div class="score-denom">/ 100</div>
      <div class="score-label">{_score_label(result.health_score.overall)}</div>
      <div class="score-stats">
        <span>{result.files_scanned} files</span>
        <span>·</span>
        <span>{result.symbols_found} symbols</span>
        <span>·</span>
        <span>{len(result.findings)} findings</span>
      </div>
    </div>
    <div class="chart-card">
      <canvas id="breakdownChart"></canvas>
    </div>
  </div>
</section>

<section>
  <h2>Category Breakdown</h2>
  <table class="breakdown-table">
    <tbody>
      {_breakdown_rows_html(result.health_score)}
    </tbody>
  </table>
</section>

<section>
  <h2>Git Intelligence</h2>
  {_git_metrics_html(result.git_metrics)}
</section>

<section>
  <h2>Findings ({len(result.findings)})</h2>
  <div class="filters">
    <select class="filter-select" id="riskFilter" onchange="applyFilters()">
      <option value="">All risks</option>
      <option value="high">High</option>
      <option value="medium">Medium</option>
      <option value="low">Low</option>
    </select>
    <select class="filter-select" id="catFilter" onchange="applyFilters()">
      <option value="">All categories</option>
      {cat_options_html}
    </select>
    <input class="filter-select" id="searchInput" type="text" placeholder="Search titles…"
           oninput="applyFilters()" style="min-width:200px">
  </div>
  <table class="findings-table" id="findingsTable">
    <thead>
      <tr>
        <th style="width:40px">#</th>
        <th style="width:80px">Risk</th>
        <th style="width:140px">Category</th>
        <th>Title</th>
        <th>File</th>
        <th style="width:60px;text-align:right">Conf</th>
      </tr>
    </thead>
    <tbody id="findingsBody">
      {_findings_rows_html(result)}
    </tbody>
  </table>
  <div id="noResults" style="display:none" class="no-findings">No findings match the current filters.</div>
</section>

<section>
  <h2>Recommendations</h2>
  {_recommendations_html(result)}
</section>

</main>
<footer>Generated by ghostlint · {_h(scan_date)}</footer>

<script>
const chartData = {chart_data};

const ctx = document.getElementById('breakdownChart').getContext('2d');
new Chart(ctx, {{
  type: 'bar',
  data: {{
    labels: chartData.labels,
    datasets: [{{
      data: chartData.values,
      backgroundColor: chartData.colors.map(c => c + '99'),
      borderColor: chartData.colors,
      borderWidth: 1,
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{
      callbacks: {{ label: ctx => ` ${{ctx.raw.toFixed(1)}} / 100` }}
    }} }},
    scales: {{
      x: {{ ticks: {{ color: '#64748b', font: {{ size: 11 }} }}, grid: {{ color: '#1e293b' }} }},
      y: {{ min: 0, max: 100, ticks: {{ color: '#64748b' }}, grid: {{ color: '#263147' }} }}
    }}
  }}
}});

function applyFilters() {{
  const risk = document.getElementById('riskFilter').value;
  const cat = document.getElementById('catFilter').value;
  const q = document.getElementById('searchInput').value.toLowerCase();
  const rows = document.querySelectorAll('#findingsBody .finding-row');
  let visible = 0;
  rows.forEach(row => {{
    const riskMatch = !risk || row.dataset.risk === risk;
    const catMatch = !cat || row.dataset.category === cat;
    const textMatch = !q || row.textContent.toLowerCase().includes(q);
    const show = riskMatch && catMatch && textMatch;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('noResults').style.display = visible === 0 ? '' : 'none';
}}
</script>
</body>
</html>"""


def write_html_report(result: ScanResult, path: Path) -> None:
    path.write_text(generate_html_report(result), encoding="utf-8")
