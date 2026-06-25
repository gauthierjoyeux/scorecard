#!/usr/bin/env python3
"""
Generates a self-contained HTML scorecard dashboard.
Reads from ~/Downloads/scorecard_data.json (fetched via browser).
Writes index.html ready to commit to GitHub Pages.
"""

import os
import json
import warnings
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")

DATA_FILE = os.environ.get("DATA_FILE", os.path.expanduser("~/Downloads/scorecard_data.json"))
OUTPUT    = os.environ.get("OUTPUT", "index.html")
N_WEEKS   = int(os.environ.get("WEEKS", "8"))

METABASE_URL = "https://metabase.internal.bigblue.co"

SCORECARD_QUESTIONS = [
    dict(id=26473, name="B2C Pack",          wh_col="warehouse_id",          date_col="week_start",      color=True),
    dict(id=26435, name="B2C NAC",           wh_col="warehouse_id",          date_col="preparation_day", color=False),
    dict(id=26434, name="B2C Pick",          wh_col="warehouse_id",          date_col="preparation_day", color=True),
    dict(id=26470, name="Ship",              wh_col="warehouse_external_id", date_col="ship_time",       color=True),
    dict(id=26471, name="Inbound (Receive)", wh_col="warehouse_external_id", date_col="create_time",     color=True),
    dict(id=26472, name="Replenishments",    wh_col="warehouse_external_id", date_col="update_time",     color=True),
]

# ── Data ───────────────────────────────────────────────────────────────────────

def load_data(path: str) -> dict:
    with open(path) as f:
        records = json.load(f)
    return {r["id"]: r for r in records}


def prepare_pivot(record: dict, q: dict, n_weeks: int) -> pd.DataFrame:
    df = pd.DataFrame(record["rows"], columns=record["cols"])
    wh_col, date_col = q["wh_col"], q["date_col"]

    if "pivot-grouping" in df.columns:
        df = df[df["pivot-grouping"] == 0].copy()

    df[date_col] = pd.to_datetime(df[date_col], utc=True).dt.tz_localize(None).dt.normalize()
    df["avg"]    = pd.to_numeric(df["avg"], errors="coerce")

    latest = sorted(df[date_col].unique())[-n_weeks:]
    df = df[df[date_col].isin(latest)]

    pivot = df.pivot_table(index=date_col, columns=wh_col, values="avg", aggfunc="mean")
    pivot.sort_index(ascending=False, inplace=True)   # newest first
    return pivot


def row_rank_colors(pivot: pd.DataFrame, week, warehouses: list, enable_color: bool) -> dict:
    """Returns {warehouse: css_class} for a given week row."""
    if not enable_color:
        return {wh: "" for wh in warehouses}

    vals = {wh: pivot.loc[week, wh] for wh in warehouses if not pd.isna(pivot.loc[week, wh])}
    if not vals:
        return {wh: "" for wh in warehouses}

    sorted_wh = sorted(vals, key=lambda w: vals[w], reverse=True)
    colors = {wh: "" for wh in warehouses}
    colors[sorted_wh[0]] = "top"
    for wh in sorted_wh[-3:]:
        if colors[wh] != "top":
            colors[wh] = "bot"
    return colors


def trend_arrow(current, previous) -> str:
    if pd.isna(current) or pd.isna(previous) or previous == 0:
        return ""
    diff = (current - previous) / abs(previous)
    if diff > 0.02:
        return f'<span class="arr up" title="+{diff:.1%}">↑</span>'
    elif diff < -0.02:
        return f'<span class="arr dn" title="{diff:.1%}">↓</span>'
    return '<span class="arr flat">→</span>'


# ── HTML builders ──────────────────────────────────────────────────────────────

def build_metric_section(q: dict, pivot: pd.DataFrame) -> str:
    warehouses = list(pivot.columns)
    weeks      = list(pivot.index)

    metabase_link = f"{METABASE_URL}/question/{q['id']}"

    # Sparkline data per warehouse: list of values oldest→newest
    spark_data = {}
    for wh in warehouses:
        vals = [pivot.loc[w, wh] for w in reversed(weeks)]   # oldest first
        vals = [round(v, 2) if not pd.isna(v) else None for v in vals]
        spark_data[wh] = vals

    spark_json = json.dumps(spark_data)
    week_labels_json = json.dumps([pd.Timestamp(w).strftime("%d %b") for w in reversed(weeks)])

    # Table HTML
    header_cells = "".join(
        f'<th>{wh}<canvas class="spark" data-wh="{wh}" data-metric="{q["id"]}"></canvas></th>'
        for wh in warehouses
    )
    header_cells += '<th class="avg-col">Network avg</th>'

    rows_html = ""
    for i, week in enumerate(weeks):
        net_avg = pivot.loc[week, warehouses].mean()
        colors  = row_rank_colors(pivot, week, warehouses, q["color"])
        cells   = ""
        for wh in warehouses:
            val  = pivot.loc[week, wh]
            prev = pivot.loc[weeks[i + 1], wh] if i + 1 < len(weeks) else float("nan")
            arrow = trend_arrow(val, prev)
            display = f"{val:.1f}" if not pd.isna(val) else "—"
            cls = f' class="{colors[wh]}"' if colors.get(wh) else ""
            cells += f"<td{cls}>{display}{arrow}</td>"
        cells += f'<td class="avg-col">{net_avg:.1f}</td>'

        week_fmt = pd.Timestamp(week).strftime("%d %b")
        latest_badge = ' <span class="badge">latest</span>' if i == 0 else ""
        rows_html += f"<tr><td class='wk-label'>{week_fmt}{latest_badge}</td>{cells}</tr>"

    return f"""
<section class="metric-card" id="metric-{q['id']}">
  <div class="card-header">
    <div>
      <h2>{q['name']}</h2>
      <span class="card-sub">Last {len(weeks)} weeks · UPH</span>
    </div>
    <a class="mb-link" href="{metabase_link}" target="_blank">Open in Metabase ↗</a>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th class="wk-label">Week</th>{header_cells}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <script>
    (function(){{
      var data  = {spark_json};
      var weeks = {week_labels_json};
      document.querySelectorAll('[data-metric="{q["id"]}"]').forEach(function(canvas) {{
        var wh   = canvas.getAttribute('data-wh');
        var vals = data[wh];
        var ctx  = canvas.getContext('2d');
        new Chart(ctx, {{
          type: 'line',
          data: {{
            labels: weeks,
            datasets: [{{
              data: vals,
              borderColor: '#6366f1',
              borderWidth: 1.5,
              pointRadius: 0,
              tension: 0.3,
              fill: false,
            }}]
          }},
          options: {{
            animation: false,
            plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: true }} }},
            scales: {{ x: {{ display: false }}, y: {{ display: false }} }},
          }}
        }});
      }});
    }})();
  </script>
</section>"""


# ── Full page ──────────────────────────────────────────────────────────────────

def build_html(sections: str, generated_at: str) -> str:
    nav_links = "\n".join(
        f'<a href="#metric-{q["id"]}">{q["name"]}</a>'
        for q in SCORECARD_QUESTIONS
    )
    week_label = datetime.now().strftime("Week %W · %d %B %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bigblue Warehouse Scorecard · {week_label}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --green:  #dcfce7; --green-txt: #166534;
    --red:    #fee2e2; --red-txt:   #991b1b;
    --avg-bg: #eff6ff; --avg-txt:   #1e40af;
    --hdr:    #1e1b4b;
    --card:   #ffffff;
    --bg:     #f1f5f9;
    --border: #e2e8f0;
    --muted:  #64748b;
  }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: #1e293b; }}

  /* ── Top bar ── */
  .topbar {{ background: var(--hdr); color: white; padding: 18px 32px;
             display: flex; align-items: center; justify-content: space-between;
             position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px #0004; }}
  .topbar h1 {{ font-size: 1.1rem; font-weight: 700; letter-spacing: .04em; }}
  .topbar .week {{ font-size: .8rem; color: #a5b4fc; margin-top: 2px; }}
  .topbar .legend {{ display: flex; gap: 12px; font-size: .75rem; }}
  .topbar .leg {{ display: flex; align-items: center; gap: 5px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 3px; }}

  /* ── Nav ── */
  .nav {{ background: white; border-bottom: 1px solid var(--border);
          padding: 0 32px; display: flex; gap: 4px; overflow-x: auto;
          position: sticky; top: 57px; z-index: 99; }}
  .nav a {{ padding: 10px 14px; font-size: .82rem; font-weight: 500; color: var(--muted);
            text-decoration: none; border-bottom: 2px solid transparent; white-space: nowrap; }}
  .nav a:hover {{ color: var(--hdr); border-color: var(--hdr); }}

  /* ── Cards ── */
  .main {{ max-width: 1300px; margin: 0 auto; padding: 28px 24px 60px; }}
  .metric-card {{ background: var(--card); border: 1px solid var(--border);
                  border-radius: 12px; margin-bottom: 28px;
                  box-shadow: 0 1px 3px #0001; overflow: hidden; }}
  .card-header {{ padding: 18px 24px 14px; display: flex;
                  align-items: flex-start; justify-content: space-between;
                  border-bottom: 1px solid var(--border); }}
  .card-header h2 {{ font-size: 1.05rem; font-weight: 700; }}
  .card-sub {{ font-size: .75rem; color: var(--muted); margin-top: 3px; display: block; }}
  .mb-link {{ font-size: .78rem; color: #6366f1; text-decoration: none; font-weight: 500;
              white-space: nowrap; padding: 6px 12px; border: 1px solid #c7d2fe;
              border-radius: 6px; background: #eef2ff; }}
  .mb-link:hover {{ background: #e0e7ff; }}

  /* ── Table ── */
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .82rem; }}
  th {{ padding: 10px 14px; text-align: center; background: #f8fafc;
        font-weight: 600; color: var(--muted); font-size: .75rem;
        border-bottom: 2px solid var(--border); white-space: nowrap; }}
  th.wk-label, td.wk-label {{ text-align: left; }}
  td {{ padding: 9px 14px; text-align: center; border-bottom: 1px solid var(--border);
        transition: background .15s; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f8fafc !important; }}

  /* ── Cell colors ── */
  td.top {{ background: var(--green); color: var(--green-txt); font-weight: 600; }}
  td.bot {{ background: var(--red);   color: var(--red-txt);   font-weight: 600; }}
  td.avg-col {{ background: var(--avg-bg); color: var(--avg-txt); font-weight: 600; }}
  th.avg-col {{ background: var(--avg-bg); color: var(--avg-txt); }}

  /* ── Badges & arrows ── */
  .badge {{ background: #6366f1; color: white; font-size: .65rem; font-weight: 700;
            padding: 1px 6px; border-radius: 20px; margin-left: 6px;
            vertical-align: middle; letter-spacing: .04em; }}
  .arr {{ font-size: .7rem; margin-left: 3px; }}
  .arr.up {{ color: #16a34a; }}
  .arr.dn {{ color: #dc2626; }}
  .arr.flat {{ color: var(--muted); }}

  /* ── Sparklines ── */
  .spark {{ display: block; width: 80px; height: 24px; margin: 4px auto 0; }}

  /* ── Info banner ── */
  .info-banner {{ background: white; border: 1px solid var(--border); border-radius: 10px;
                  padding: 14px 20px; margin-bottom: 24px; font-size: .82rem;
                  color: #334155; line-height: 1.6; }}
  .info-banner strong {{ color: #1e293b; }}
  .pill {{ display: inline-block; padding: 1px 8px; border-radius: 20px;
           font-size: .75rem; font-weight: 600; }}
  .pill.green {{ background: var(--green); color: var(--green-txt); }}
  .pill.red   {{ background: var(--red);   color: var(--red-txt); }}
  .pill.blue  {{ background: var(--avg-bg); color: var(--avg-txt); }}

  /* ── Footer ── */
  .footer {{ text-align: center; font-size: .72rem; color: var(--muted);
             padding: 20px; }}
</style>
</head>
<body>

<header class="topbar">
  <div>
    <div class="h1">BIGBLUE · Warehouse Scorecard</div>
    <div class="week">{week_label}</div>
  </div>
  <div class="legend">
    <div class="leg"><div class="swatch" style="background:#86efac"></div> Top performer</div>
    <div class="leg"><div class="swatch" style="background:#fca5a5"></div> Bottom 3</div>
    <div class="leg"><div class="swatch" style="background:#bfdbfe"></div> Network avg</div>
  </div>
</header>

<nav class="nav">
  {nav_links}
</nav>

<main class="main">
  <div class="info-banner">
    <strong>How to read this scorecard</strong> — Each table shows the last {N_WEEKS} weeks of productivity data (UPH) per warehouse.
    For each week, the <span class="pill green">top performer</span> is highlighted green and the
    <span class="pill red">bottom 3</span> are highlighted red. Rankings reset every week — a warehouse can move between categories.
    The <span class="pill blue">Network avg</span> column shows the mean across all warehouses for that week.
    Arrows (↑↓) indicate change vs the previous week. Click <em>Open in Metabase</em> on any metric to explore the underlying data.
  </div>
  {sections}
</main>

<div class="footer">Generated {generated_at} · Bigblue Operations</div>

</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("── Bigblue Scorecard HTML ────────────────────────")
    print(f"  Data  : {DATA_FILE}")
    print(f"  Output: {OUTPUT}")
    print(f"  Weeks : {N_WEEKS}")

    if not os.path.exists(DATA_FILE):
        raise SystemExit(f"ERROR: data file not found: {DATA_FILE}")

    cache = load_data(DATA_FILE)
    sections = []

    for q in SCORECARD_QUESTIONS:
        print(f"  • {q['name']}...")
        record = cache[q["id"]]
        pivot  = prepare_pivot(record, q, N_WEEKS)
        if pivot.empty:
            print("    ↳ no data, skipping")
            continue
        sections.append(build_metric_section(q, pivot))

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = build_html("\n".join(sections), generated_at)

    with open(OUTPUT, "w") as f:
        f.write(html)

    print(f"\n  ✓ Saved {OUTPUT}")
    print(f"  Open: file://{os.path.abspath(OUTPUT)}")


if __name__ == "__main__":
    main()
