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

_RISK_ORDER = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}

_SCORE_COLOR = {
    (90, 101): "#22c55e",
    (70, 90):  "#eab308",
    (50, 70):  "#f97316",
    (0,  50):  "#ef4444",
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
        ("Dead Code",           hs.dead_code),
        ("Duplicate Logic",     hs.duplicate_logic),
        ("Refactor Completion", hs.refactor_completion),
        ("Architectural Drift", hs.architectural_drift),
        ("Dependency Health",   hs.dependency_health),
        ("Documentation",       hs.documentation_freshness),
        ("Test Health",         hs.test_health),
        ("Config Consistency",  hs.config_consistency),
    ]
    html_rows = ""
    for name, score in rows:
        color = _score_color(score)
        label = _score_label(score)
        html_rows += f"""
        <tr>
          <td class="cat-name">{_h(name)}</td>
          <td class="cat-score" style="color:{color}">{score:.1f}</td>
          <td class="cat-label" style="color:{color}">{label}</td>
        </tr>"""
    return html_rows


def _findings_overview_html(result: ScanResult) -> str:
    counts = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 0, RiskLevel.LOW: 0}
    for f in result.findings:
        if f.risk in counts:
            counts[f.risk] += 1
    total = len(result.findings)
    pills = ""
    for level, label in [(RiskLevel.HIGH, "High"), (RiskLevel.MEDIUM, "Medium"), (RiskLevel.LOW, "Low")]:
        c = counts[level]
        color = _RISK_COLOR[level]
        pills += f'<span class="overview-pill" style="background:{color}18;color:{color};border:1px solid {color}44">{c} {label}</span>'
    return f"""
    <div class="findings-overview">
      <span class="overview-total">{total} findings</span>
      <span class="overview-sep">·</span>
      {pills}
    </div>"""


def _findings_rows_html(result: ScanResult) -> str:
    if not result.findings:
        return '<tr><td colspan="6" style="text-align:center;color:#64748b">No issues found</td></tr>'
    rows = ""
    for i, f in enumerate(result.findings, 1):
        risk_color = _RISK_COLOR.get(f.risk, "#94a3b8")
        cat = f.category.value.replace("_", " ").title()
        truncated = len(f.primary_file) > 50
        file_tail = _h(f.primary_file[-50:])
        file_cell = (
            f'<span style="color:#475569">…</span>{file_tail}' if truncated else file_tail
        )
        rows += f"""
        <tr class="finding-row" data-risk="{_h(f.risk.value)}" data-category="{_h(f.category.value)}" data-file="{_h(f.primary_file.lower())}">
          <td style="color:#64748b;text-align:center">{i}</td>
          <td><span class="badge" style="background:{risk_color}22;color:{risk_color};border:1px solid {risk_color}44">{_h(f.risk.value.upper())}</span></td>
          <td style="color:#94a3b8;font-size:0.78rem">{_h(cat)}</td>
          <td>{_h(f.title)}</td>
          <td style="color:#64748b;font-size:0.78rem;font-family:monospace;white-space:nowrap" title="{_h(f.primary_file)}">{file_cell}</td>
          <td style="text-align:right;color:#94a3b8">{f.confidence:.0%}</td>
        </tr>"""
    return rows


def _recommendations_html(result: ScanResult) -> str:
    if not result.recommendations:
        return "<p style='color:#64748b'>No recommendations at this time.</p>"

    finding_cat: dict[str, str] = {f.id: f.category.value for f in result.findings}

    sorted_recs = sorted(result.recommendations, key=lambda r: _RISK_ORDER.get(r.risk, 9))[:10]

    # collect unique effort + category values for filter dropdowns
    effort_values = sorted({rec.effort.value for rec in sorted_recs})
    cat_values = sorted({finding_cat.get(rec.finding_id, "") for rec in sorted_recs} - {""})

    effort_options = "".join(
        f'<option value="{_h(e)}">{_h(e.title())}</option>' for e in effort_values
    )
    cat_options = "".join(
        f'<option value="{_h(c)}">{_h(c.replace("_", " ").title())}</option>' for c in cat_values
    )

    items = ""
    for i, rec in enumerate(sorted_recs, 1):
        risk_color = _RISK_COLOR.get(rec.risk, "#94a3b8")
        risk_label = rec.risk.value.upper()
        cat_val = finding_cat.get(rec.finding_id, "")
        cat_label = cat_val.replace("_", " ").title() if cat_val else ""
        items += f"""
        <div class="rec-item" data-risk="{_h(rec.risk.value)}" data-effort="{_h(rec.effort.value)}" data-category="{_h(cat_val)}">
          <span class="rec-num" style="background:{risk_color}">{i}</span>
          <div class="rec-body">
            <div class="rec-header">
              <span class="rec-title">{_h(rec.title)}</span>
              <span class="rec-badge" style="background:{risk_color}22;color:{risk_color};border:1px solid {risk_color}44">{risk_label}</span>
            </div>
            <div class="rec-meta">{_h(rec.description)}</div>
            <div class="rec-tags">
              <span class="tag">confidence {rec.confidence:.0%}</span>
              <span class="tag">{_h(rec.effort.value)}</span>
              {(f'<span class="tag tag-area">{_h(cat_label)}</span>') if cat_label else ''}
              {(f'<span class="tag tag-benefit">{_h(rec.benefit)}</span>') if rec.benefit else ''}
            </div>
          </div>
        </div>"""

    filters = f"""
    <div class="filters" style="margin-bottom:1rem">
      <select class="filter-select" id="recRiskFilter" onchange="applyRecFilters()">
        <option value="">All impact</option>
        <option value="high">High</option>
        <option value="medium">Medium</option>
        <option value="low">Low</option>
      </select>
      <select class="filter-select" id="recEffortFilter" onchange="applyRecFilters()">
        <option value="">All effort</option>
        {effort_options}
      </select>
      <select class="filter-select" id="recCatFilter" onchange="applyRecFilters()">
        <option value="">All areas</option>
        {cat_options}
      </select>
    </div>"""

    return filters + f'<div id="recList">{items}</div><div id="recNoResults" style="display:none;color:var(--muted);padding:1rem 0">No recommendations match the current filters.</div>'


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
    friction_color = _score_color(100 - gm.friction_index)

    cards = (
        _metric_card("Stability Index",      f"{gm.stability_index:.1f}",          "Architecture churn resistance",       stability_color, "How often core files change")
        + _metric_card("Maintenance Velocity", f"{velocity_pct:.1f}%",             "Fix-commit ratio (last 90 days)",     velocity_color,  "Share of commits with fix intent")
        + _metric_card("Refactor Completion",  f"{gm.refactor_completion_rate:.1f}%", "Tech-debt marker trend",           refactor_color,  "TODO/FIXME trend vs 30 commits ago")
        + _metric_card("Friction Index",       f"{gm.friction_index:.1f}",         "Cognitive overhead (lower = better)", friction_color,  "Churn + ownership spread + large files")
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
  main {{ max-width: 1280px; margin: 0 auto; padding: 2rem; }}
  section {{ margin-bottom: 2.5rem; }}
  h2 {{ font-size: 1.05rem; font-weight: 600; color: var(--muted);
        text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 1rem;
        border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}

  /* Shared grid — score hero and category/git section use identical column proportions */
  .two-col, .score-hero {{ display: grid; grid-template-columns: minmax(220px, 1fr) minmax(360px, 2fr); gap: 2rem; }}
  @media (max-width: 860px) {{ .two-col, .score-hero {{ grid-template-columns: 1fr; }} }}

  /* Score hero */
  .score-circle {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
                   padding: 2.5rem; display: flex; flex-direction: column; align-items: center;
                   justify-content: center; }}
  .score-num {{ font-size: 4rem; font-weight: 800; line-height: 1; color: {overall_color}; }}
  .score-denom {{ font-size: 1.2rem; color: var(--muted); margin-top: 0.25rem; }}
  .score-label {{ font-size: 0.9rem; margin-top: 0.75rem; font-weight: 600;
                  color: {overall_color}; text-transform: uppercase; letter-spacing: 0.05em; }}
  .score-stats {{ display: flex; gap: 1rem; color: var(--muted); font-size: 0.82rem;
                  margin-top: 0.75rem; flex-wrap: wrap; justify-content: center; }}
  .chart-card {{ background: var(--surface); border: 1px solid var(--border);
                 border-radius: 16px; padding: 1.5rem; min-height: 220px; }}
  .col-panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem; }}
  .col-panel h3 {{ font-size: 0.82rem; font-weight: 600; color: var(--muted);
                   text-transform: uppercase; letter-spacing: 0.08em;
                   border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; margin-bottom: 1rem; }}

  /* Breakdown table — compact, score + label only */
  .breakdown-table {{ width: 100%; border-collapse: collapse; }}
  .breakdown-table td {{ padding: 0.55rem 0.4rem; vertical-align: middle; white-space: nowrap; }}
  .cat-name {{ color: var(--text); font-size: 0.88rem; padding-right: 1rem !important; }}
  .cat-score {{ text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; font-size: 1rem; width: 48px; }}
  .cat-label {{ width: 70px; font-size: 0.75rem; text-align: right; }}

  /* Git metrics — 2×2 grid with room to breathe */
  .metric-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.85rem; }}
  .metric-card {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 1rem 1.1rem; }}
  .metric-title {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
                   color: var(--muted); margin-bottom: 0.4rem; }}
  .metric-value {{ font-size: 1.8rem; font-weight: 700; line-height: 1; }}
  .metric-subtitle {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.3rem; }}
  .metric-note {{ font-size: 0.73rem; color: #64748b; margin-top: 0.45rem; line-height: 1.4; }}
  .git-meta {{ display: flex; gap: 0.75rem; color: var(--muted); font-size: 0.78rem;
               margin-top: 1rem; flex-wrap: wrap; }}
  .git-unavailable {{ color: var(--muted); padding: 1rem; }}

  /* Findings overview pills */
  .findings-overview {{ display: flex; align-items: center; gap: 0.75rem;
                         margin-bottom: 1.25rem; flex-wrap: wrap; }}
  .overview-total {{ font-size: 1rem; font-weight: 600; color: var(--text); }}
  .overview-sep {{ color: var(--muted); }}
  .overview-pill {{ border-radius: 20px; padding: 0.25rem 0.85rem;
                    font-size: 0.82rem; font-weight: 600; }}

  /* Filter bars */
  .filters {{ display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem; }}
  .filter-select {{ background: var(--surface); border: 1px solid var(--border); color: var(--text);
                    border-radius: 6px; padding: 0.4rem 0.75rem; font-size: 0.85rem; cursor: pointer; }}
  .findings-table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  .findings-table th {{ text-align: left; padding: 0.5rem 0.75rem; color: var(--muted);
                        font-weight: 500; font-size: 0.78rem; text-transform: uppercase;
                        letter-spacing: 0.05em; border-bottom: 1px solid var(--border);
                        position: sticky; top: 0; z-index: 10; background: var(--bg); }}
  .findings-table td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border)22; }}
  .findings-table tr:hover td {{ background: var(--surface2); }}
  .badge {{ display: inline-block; border-radius: 4px; padding: 0.15rem 0.45rem;
             font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em; }}
  .no-findings {{ text-align: center; padding: 2rem; color: var(--muted); }}

  /* Recommendations */
  .rec-item {{ display: flex; gap: 1rem; padding: 1rem; background: var(--surface);
               border: 1px solid var(--border); border-radius: 10px; margin-bottom: 0.6rem; }}
  .rec-item[style*="display:none"] {{ display: none !important; }}
  .rec-num {{ width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center;
              justify-content: center; font-size: 0.8rem; font-weight: 700; color: white;
              flex-shrink: 0; margin-top: 0.15rem; }}
  .rec-body {{ flex: 1; min-width: 0; }}
  .rec-header {{ display: flex; align-items: baseline; gap: 0.75rem; margin-bottom: 0.3rem; flex-wrap: wrap; }}
  .rec-title {{ font-weight: 600; color: var(--text); }}
  .rec-badge {{ border-radius: 4px; padding: 0.1rem 0.45rem; font-size: 0.68rem;
                font-weight: 700; letter-spacing: 0.05em; flex-shrink: 0; }}
  .rec-meta {{ font-size: 0.83rem; color: var(--muted); margin-bottom: 0.5rem; }}
  .rec-tags {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
  .tag {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 4px;
          padding: 0.1rem 0.45rem; font-size: 0.72rem; color: var(--muted); }}
  .tag-benefit {{ color: #6366f1; border-color: #6366f144; background: #6366f111; }}
  .tag-area {{ color: #38bdf8; border-color: #38bdf844; background: #38bdf811; }}

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
  <h2>Category Breakdown &amp; Git Intelligence</h2>
  <div class="two-col">
    <div class="col-panel">
      <h3>Category Scores</h3>
      <table class="breakdown-table">
        <tbody>
          {_breakdown_rows_html(result.health_score)}
        </tbody>
      </table>
    </div>
    <div class="col-panel">
      <h3>Git Intelligence</h3>
      {_git_metrics_html(result.git_metrics)}
    </div>
  </div>
</section>

<section>
  <h2>Findings</h2>
  {_findings_overview_html(result)}
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
    <input class="filter-select" id="fileInput" type="text" placeholder="Search files / folders…"
           oninput="applyFilters()" style="min-width:220px">
  </div>
  <table class="findings-table" id="findingsTable">
    <thead>
      <tr>
        <th style="width:40px">#</th>
        <th style="width:80px">Risk</th>
        <th style="width:140px">Category</th>
        <th>Title</th>
        <th>File</th>
        <th style="width:100px;text-align:right">Confidence</th>
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
  const cat  = document.getElementById('catFilter').value;
  const q    = document.getElementById('searchInput').value.toLowerCase();
  const file = document.getElementById('fileInput').value.toLowerCase();
  const rows = document.querySelectorAll('#findingsBody .finding-row');
  let visible = 0;
  rows.forEach(row => {{
    const show = (!risk || row.dataset.risk     === risk)
              && (!cat  || row.dataset.category === cat)
              && (!q    || row.textContent.toLowerCase().includes(q))
              && (!file || row.dataset.file.includes(file));
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('noResults').style.display = visible === 0 ? '' : 'none';
}}

function applyRecFilters() {{
  const risk   = document.getElementById('recRiskFilter')?.value   ?? '';
  const effort = document.getElementById('recEffortFilter')?.value ?? '';
  const cat    = document.getElementById('recCatFilter')?.value    ?? '';
  const items  = document.querySelectorAll('#recList .rec-item');
  let visible  = 0;
  items.forEach(item => {{
    const show = (!risk   || item.dataset.risk     === risk)
              && (!effort || item.dataset.effort   === effort)
              && (!cat    || item.dataset.category === cat);
    item.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  const noRes = document.getElementById('recNoResults');
  if (noRes) noRes.style.display = visible === 0 ? '' : 'none';
}}
</script>
</body>
</html>"""


def write_html_report(result: ScanResult, path: Path) -> None:
    path.write_text(generate_html_report(result), encoding="utf-8")
