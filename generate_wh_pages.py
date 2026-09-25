#!/usr/bin/env python3
"""
Generates one self-contained HTML scorecard per warehouse.
Single table: rows = weeks, columns = metrics.
Each cell shows the warehouse UPH + network avg below it.
No cross-warehouse ranking, no Metabase links.

Output files: wh_<WAREHOUSE_ID>.html  (e.g. wh_EU-FRA-003.html)
"""

import os, json, warnings, glob
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")

def _latest_data_file() -> str:
    pattern = os.path.expanduser("~/Downloads/scorecard_data*.json")
    files = glob.glob(pattern)
    if not files:
        return os.path.expanduser("~/Downloads/scorecard_data.json")
    return max(files, key=os.path.getmtime)

DATA_FILE  = os.environ.get("DATA_FILE", _latest_data_file())
OUT_DIR    = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
N_WEEKS    = int(os.environ.get("WEEKS", "13"))
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wh_tokens.json")


def load_or_create_tokens(warehouses: list) -> dict:
    """Load stable random tokens for each warehouse, creating new ones as needed."""
    import secrets
    tokens = {}
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            tokens = json.load(f)
    changed = False
    for wh in warehouses:
        if wh not in tokens:
            tokens[wh] = secrets.token_hex(12)
            changed = True
    if changed:
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    return tokens

SCORECARD_QUESTIONS = [
    dict(id=26473, name="B2C Pack",          wh_col="warehouse_id",          date_col="week_start"),
    dict(id=26435, name="B2C NAC",           wh_col="warehouse_id",          date_col="preparation_day"),
    dict(id=26434, name="B2C Pick",          wh_col="warehouse_id",          date_col="preparation_day"),
    dict(id=26470, name="Ship",              wh_col="warehouse_external_id", date_col="ship_time"),
    dict(id=26471, name="Inbound",           wh_col="warehouse_external_id", date_col="create_time"),
    dict(id=26472, name="Replenishments",    wh_col="warehouse_external_id", date_col="update_time"),
]


# ── Data helpers ───────────────────────────────────────────────────────────────

def load_data(path: str) -> dict:
    with open(path) as f:
        records = json.load(f)
    return {r["id"]: r for r in records}


def prepare_pivot(record: dict, q: dict, n_weeks: int) -> pd.DataFrame:
    df = pd.DataFrame(record["rows"], columns=record["cols"])
    wh_col, date_col = q["wh_col"], q["date_col"]
    if "pivot-grouping" in df.columns:
        df = df[df["pivot-grouping"] == 0].copy()
    df["_week"] = df[date_col].apply(lambda v: str(v)[:10] if v else None)
    df = df[df["_week"].notna()].copy()
    df["avg"] = pd.to_numeric(df["avg"], errors="coerce")
    all_weeks = sorted(df["_week"].unique())
    latest = all_weeks[-n_weeks:]
    df = df[df["_week"].isin(latest)]
    pivot = df.pivot_table(index="_week", columns=wh_col, values="avg", aggfunc="mean")
    pivot.sort_index(ascending=False, inplace=True)
    return pivot


def trend_arrow(current, previous) -> str:
    if pd.isna(current) or pd.isna(previous) or previous == 0:
        return ""
    diff = (current - previous) / abs(previous)
    if diff > 0.02:
        return f'<span class="arr up" title="+{diff:.1%}">↑</span>'
    elif diff < -0.02:
        return f'<span class="arr dn" title="{diff:.1%}">↓</span>'
    return '<span class="arr flat">→</span>'


# ── Single unified table ───────────────────────────────────────────────────────

def build_table(pivots: dict, wh_id: str) -> str:
    # Collect the union of weeks across all metrics (sorted desc)
    all_weeks_set = set()
    for q in SCORECARD_QUESTIONS:
        p = pivots.get(q["id"])
        if p is not None and wh_id in p.columns:
            all_weeks_set.update(p.index.tolist())
    weeks = sorted(all_weeks_set, reverse=True)[:N_WEEKS]

    # Header
    header_cells = ""
    for q in SCORECARD_QUESTIONS:
        p = pivots.get(q["id"])
        has_data = p is not None and wh_id in p.columns and not p[wh_id].isna().all()
        cls = "metric-col" if has_data else "metric-col missing"
        header_cells += f'<th class="{cls}">{q["name"]}<span class="unit">UPH</span></th>'

    rows_html = ""
    for i, week in enumerate(weeks):
        week_fmt     = pd.Timestamp(week).strftime("%d %b")
        latest_badge = ' <span class="badge">latest</span>' if i == 0 else ""
        cells = ""
        for q in SCORECARD_QUESTIONS:
            p = pivots.get(q["id"])
            if p is None or wh_id not in p.columns or week not in p.index:
                cells += '<td class="metric-col">—</td>'
                continue

            val  = p.loc[week, wh_id]
            prev = p.loc[weeks[i + 1], wh_id] if i + 1 < len(weeks) and weeks[i + 1] in p.index else float("nan")
            net_avg = p.loc[week].mean()

            display  = f"{val:.1f}"  if not pd.isna(val)     else "—"
            net_disp = f"{net_avg:.1f}" if not pd.isna(net_avg) else "—"
            arrow    = trend_arrow(val, prev)

            cells += (
                f'<td class="metric-col">'
                f'<span class="wh-val">{display}{arrow}</span>'
                f'<span class="net-avg">avg {net_disp}</span>'
                f'</td>'
            )

        rows_html += f"<tr><td class='wk-label'>{week_fmt}{latest_badge}</td>{cells}</tr>"

    return f"""
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th class="wk-label">Week</th>
        {header_cells}
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""


# ── Full page ──────────────────────────────────────────────────────────────────

CSS = """
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --hdr:    #1e1b4b;
    --card:   #ffffff;
    --bg:     #f1f5f9;
    --border: #e2e8f0;
    --muted:  #64748b;
    --wh-txt: #1e293b;
    --avg-txt:#6366f1;
  }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: #1e293b; }

  .topbar { background: var(--hdr); color: white; padding: 18px 32px;
            display: flex; align-items: center; justify-content: space-between;
            position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px #0004; }
  .topbar .h1   { font-size: 1.1rem; font-weight: 700; letter-spacing: .04em; }
  .topbar .week { font-size: .8rem; color: #a5b4fc; margin-top: 2px; }
  .topbar .legend { display: flex; gap: 16px; font-size: .75rem; align-items: center; }
  .topbar .leg { display: flex; align-items: center; gap: 6px; }

  .main { max-width: 1100px; margin: 0 auto; padding: 28px 24px 60px; }

  .scorecard-card { background: var(--card); border: 1px solid var(--border);
                    border-radius: 12px; box-shadow: 0 1px 3px #0001; overflow: hidden; }
  .card-header { padding: 20px 24px 16px; border-bottom: 1px solid var(--border); }
  .card-header h2 { font-size: 1rem; font-weight: 700; color: var(--hdr); }
  .card-sub { font-size: .75rem; color: var(--muted); margin-top: 3px; }

  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .82rem; }

  th { padding: 10px 16px; text-align: center; background: #f8fafc;
       font-weight: 600; color: var(--muted); font-size: .75rem;
       border-bottom: 2px solid var(--border); white-space: nowrap; }
  th.wk-label { text-align: left; min-width: 90px; }
  th.metric-col { min-width: 110px; }
  th .unit { display: block; font-size: .65rem; font-weight: 400;
             color: #94a3b8; margin-top: 2px; letter-spacing: .04em; }

  td { padding: 10px 16px; text-align: center; border-bottom: 1px solid var(--border);
       vertical-align: middle; }
  td.wk-label { text-align: left; font-size: .8rem; color: var(--muted);
                font-weight: 500; white-space: nowrap; }
  td.metric-col { padding: 8px 16px; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #f8fafc; }

  .wh-val { display: block; font-weight: 700; font-size: .9rem; color: var(--wh-txt); }
  .net-avg { display: block; font-size: .72rem; color: var(--avg-txt);
             margin-top: 2px; font-weight: 500; }

  .badge { background: #6366f1; color: white; font-size: .62rem; font-weight: 700;
           padding: 1px 6px; border-radius: 20px; margin-left: 6px;
           vertical-align: middle; letter-spacing: .04em; }
  .arr { font-size: .7rem; margin-left: 3px; }
  .arr.up   { color: #16a34a; }
  .arr.dn   { color: #dc2626; }
  .arr.flat { color: #94a3b8; }

  .footer { text-align: center; font-size: .72rem; color: var(--muted); padding: 24px; }
"""

def build_page(wh_id: str, table_html: str, generated_at: str) -> str:
    week_label = datetime.now().strftime("Week %W · %d %B %Y")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{wh_id} · Scorecard · {week_label}</title>
<style>{CSS}</style>
</head>
<body>

<header class="topbar">
  <div>
    <div class="h1">BIGBLUE · {wh_id}</div>
    <div class="week">{week_label}</div>
  </div>
  <div class="legend">
    <span class="leg"><strong style="font-size:.9rem">123.4</strong>&nbsp;warehouse UPH</span>
    <span class="leg" style="color:#a5b4fc">avg 123.4 = network average</span>
  </div>
</header>

<main class="main">
  <div class="scorecard-card">
    <div class="card-header">
      <div class="h2">Productivity — last {N_WEEKS} weeks</div>
      <div class="card-sub">All metrics in UPH · Network avg shown below each value</div>
    </div>
    {table_html}
  </div>
</main>

<div class="footer">Generated {generated_at} · Bigblue Operations</div>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("── Bigblue Per-Warehouse Scorecard HTML ──────────────")
    print(f"  Data   : {DATA_FILE}")
    print(f"  Out dir: {OUT_DIR}")
    print(f"  Weeks  : {N_WEEKS}")

    if not os.path.exists(DATA_FILE):
        raise SystemExit(f"ERROR: data file not found: {DATA_FILE}")

    cache = load_data(DATA_FILE)

    pivots = {}
    all_warehouses: set = set()
    for q in SCORECARD_QUESTIONS:
        if q["id"] not in cache:
            print(f"    ↳ card {q['id']} ({q['name']}) missing from data (fetch failed), skipping")
            continue
        pivot = prepare_pivot(cache[q["id"]], q, N_WEEKS)
        pivots[q["id"]] = pivot
        all_warehouses.update(pivot.columns)

    all_warehouses = sorted(all_warehouses)
    tokens = load_or_create_tokens(all_warehouses)
    print(f"  Warehouses: {', '.join(all_warehouses)}")

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    written = []

    for wh_id in all_warehouses:
        # Skip warehouses with no data in any metric
        has_any = any(
            wh_id in pivots[q["id"]].columns and not pivots[q["id"]][wh_id].isna().all()
            for q in SCORECARD_QUESTIONS
        )
        if not has_any:
            print(f"  • {wh_id} — no data, skipping")
            continue

        token = tokens[wh_id]
        table_html = build_table(pivots, wh_id)
        html = build_page(wh_id, table_html, generated_at)
        out_path = os.path.join(OUT_DIR, f"sc_{token}.html")
        with open(out_path, "w") as f:
            f.write(html)
        written.append(out_path)
        print(f"  ✓ sc_{token}.html  ({wh_id})")

    print(f"\n  Done — {len(written)} files written.")
    return written


if __name__ == "__main__":
    main()
