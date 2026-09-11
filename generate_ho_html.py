#!/usr/bin/env python3
"""Bigblue Happy Orders Scorecard — HTML generator.

Reads ho_data.json (downloaded via fetch_mb.py) and writes ho_index.html.
"""

import glob
import json
import os
from datetime import datetime

import pandas as pd

# ── Config ─────────────────────────────────────────────────────────────────────
N_WEEKS_HO   = int(os.environ.get("WEEKS_HO",   "6"))  # weeks shown in HO ratio table
SKIP_RECENT  = int(os.environ.get("SKIP_RECENT", "2"))  # most-recent weeks to skip (data lag)
N_WEEKS_PRED = int(os.environ.get("WEEKS_PRED",  "8"))  # weeks in predictor chart/table

WH_ACTIONABLE = {
    "1.Start of prep", "2. picking commited", "3. picking ended",
    "4. packed", "5. End of prep", "6.Handed over",
}

ALL_BUCKETS = [
    "1.Start of prep", "2. picking commited", "3. picking ended",
    "4. packed", "5. End of prep", "6.Handed over",
    "7. shipped", "8.all timestamps on the correct day",
]

BUCKET_LABELS = [
    "1. Start of prep", "2. Picking committed", "3. Picking ended",
    "4. Packed", "5. End of prep", "6. Handed over",
    "7. Shipped", "8. All timestamps OK",
]

BUCKET_COLORS = [
    "#EF5350", "#FF7043", "#FFA726",
    "#FFCA28", "#AB47BC", "#7E57C2",
    "#42A5F5", "#66BB6A",
]


def _latest(pattern: str) -> str:
    files = glob.glob(os.path.expanduser(pattern))
    return max(files, key=os.path.getmtime) if files else os.path.expanduser(pattern.replace("*", ""))


DATA_FILE = os.environ.get("DATA_FILE", _latest("~/Downloads/ho_data*.json"))
OUTPUT    = os.environ.get(
    "OUTPUT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ho_index.html"),
)


# ── Data loading ───────────────────────────────────────────────────────────────

def _week(val):
    return str(val)[:10] if val else None


def load_data() -> dict:
    with open(DATA_FILE) as f:
        records = json.load(f)
    return {r["id"]: r for r in records}


def prepare_ho_ratio(rec: dict) -> pd.DataFrame:
    """26830: pivot WH × week → HO ratio."""
    df = pd.DataFrame(rec["rows"], columns=rec["cols"])
    if "pivot-grouping" in df.columns:
        df = df[df["pivot-grouping"] == 0]
    df["_week"] = df["submit_time"].apply(_week)
    df = df[df["_week"].notna()].copy()
    df["Happy Order Ratio"] = pd.to_numeric(df["Happy Order Ratio"], errors="coerce")
    pivot = df.pivot_table(index="_week", columns="warehouse_id",
                           values="Happy Order Ratio", aggfunc="mean")
    pivot.sort_index(ascending=False, inplace=True)
    return pivot


def prepare_bb_avg(rec: dict) -> dict:
    """26832: BB network average by week → {week: ratio}."""
    df = pd.DataFrame(rec["rows"], columns=rec["cols"])
    df["_week"] = df["submit_time"].apply(_week)
    df = df[df["_week"].notna()].copy()
    df["Happy Order Ratio"] = pd.to_numeric(df["Happy Order Ratio"], errors="coerce")
    return df.set_index("_week")["Happy Order Ratio"].to_dict()


def prepare_predictor(rec: dict) -> dict:
    """26829: % WH-actionable per (wh, week). Returns {wh: {week: pct}}."""
    df = pd.DataFrame(rec["rows"], columns=rec["cols"])
    df["_week"] = df["expected_shipping_day"].apply(_week)
    df = df[df["_week"].notna()].copy()
    df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0)

    result: dict = {}
    for (week, wh), grp in df.groupby(["_week", "warehouse_id"]):
        total      = grp["count"].sum()
        actionable = grp[grp["First failed timestamp"].isin(WH_ACTIONABLE)]["count"].sum()
        pct = round(float(actionable / total * 100), 1) if total > 0 else None
        result.setdefault(wh, {})[week] = pct
    return result


def prepare_failure_drivers(rec: dict) -> dict:
    """26829: bucket counts per (wh, week). Returns {wh: {week: {bucket: count}}}."""
    df = pd.DataFrame(rec["rows"], columns=rec["cols"])
    df["_week"] = df["expected_shipping_day"].apply(_week)
    df = df[df["_week"].notna()].copy()
    df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0)

    result: dict = {}
    for _, row in df.iterrows():
        wh     = row["warehouse_id"]
        week   = row["_week"]
        bucket = row["First failed timestamp"]
        count  = int(row["count"])
        result.setdefault(wh, {}).setdefault(week, {})[bucket] = count
    return result


def prepare_failure_breakdown_weekly(rec: dict) -> dict:
    """26829: % per bucket per (wh, week). Returns {wh: {week: {bucket: pct}}, "Network": {week: {bucket: pct}}}."""
    df = pd.DataFrame(rec["rows"], columns=rec["cols"])
    df["_week"] = df["expected_shipping_day"].apply(_week)
    df = df[df["_week"].notna()].copy()
    df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0)

    result: dict = {}
    for (week, wh), grp in df.groupby(["_week", "warehouse_id"]):
        total = grp["count"].sum()
        if total == 0:
            continue
        buckets = {}
        for _, row in grp.iterrows():
            b = row["First failed timestamp"]
            buckets[b] = round(float(row["count"] / total * 100), 1)
        result.setdefault(wh, {})[week] = buckets

    # Network: sum counts across all WHs per week
    for week, grp in df.groupby("_week"):
        total = grp["count"].sum()
        if total == 0:
            continue
        buckets = {}
        for b, sub in grp.groupby("First failed timestamp"):
            buckets[b] = round(float(sub["count"].sum() / total * 100), 1)
        result.setdefault("Network", {})[week] = buckets

    return result


def prepare_failure_breakdown_daily(rec: dict) -> dict:
    """ho_daily: % per bucket per (wh, day). Returns {wh: {day: {bucket: pct}}, "Network": {day: {bucket: pct}}}."""
    df = pd.DataFrame(rec["rows"], columns=rec["cols"])
    df["_day"] = df["expected_shipping_day"].apply(_week)  # truncates to date
    df = df[df["_day"].notna()].copy()
    df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0)

    result: dict = {}
    for (day, wh), grp in df.groupby(["_day", "warehouse_id"]):
        total = grp["count"].sum()
        if total == 0:
            continue
        buckets = {}
        for _, row in grp.iterrows():
            b = row["First failed timestamp"]
            buckets[b] = round(float(row["count"] / total * 100), 1)
        result.setdefault(wh, {})[day] = buckets

    # Network: across all WHs per day
    for day, grp in df.groupby("_day"):
        total = grp["count"].sum()
        if total == 0:
            continue
        buckets = {}
        for b, sub in grp.groupby("First failed timestamp"):
            buckets[b] = round(float(sub["count"].sum() / total * 100), 1)
        result.setdefault("Network", {})[day] = buckets

    return result


def prepare_merchants(rec: dict) -> dict:
    """26831: merchant breakdown per (wh, week). Returns {wh: {week: [{…}]}}."""
    df = pd.DataFrame(rec["rows"], columns=rec["cols"])
    df["_week"] = df["submit_time"].apply(_week)
    df = df[df["_week"].notna()].copy()
    df["Happy Order Ratio"] = pd.to_numeric(df["Happy Order Ratio"], errors="coerce")
    df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0)

    result: dict = {}
    for (wh, week), grp in df.groupby(["warehouse_id", "_week"]):
        merchants = []
        for _, r in grp.sort_values("count", ascending=False).iterrows():
            ho = r["Happy Order Ratio"]
            merchants.append({
                "merchant_id": r["merchant_id"],
                "ho_ratio": round(float(ho), 4) if not pd.isna(ho) else None,
                "count": int(r["count"]),
            })
        result.setdefault(wh, {})[week] = merchants
    return result


# ── JSON data blob ─────────────────────────────────────────────────────────────

def build_blob() -> dict:
    data = load_data()

    ho_pivot  = prepare_ho_ratio(data[26830])
    bb_avg    = prepare_bb_avg(data[26832])
    predictor = prepare_predictor(data[26829])
    fail_driv = prepare_failure_drivers(data[26829])
    merchants = prepare_merchants(data[26831])

    # Per-WH weekly breakdown: use the richer CASE-based query (ho_weekly_breakdown, -3 months).
    # Fall back to card 26829 if not present (backwards compat with older ho_data.json).
    _weekly_rec = data.get("ho_weekly_breakdown") or data.get(26829)
    fail_weekly = prepare_failure_breakdown_weekly(_weekly_rec)

    # W-1 Recap table: use the dedicated -1 week richer query (ho_w1_breakdown).
    # Its week IS the W-1 week — no need to compute via SKIP_RECENT.
    _w1_canonical = None
    _w1_rec = data.get("ho_w1_breakdown")
    if _w1_rec and _w1_rec["rows"]:
        w1_breakdown = prepare_failure_breakdown_weekly(_w1_rec)
        _w1_weeks = sorted(
            {w for wh_d in w1_breakdown.values() for w in wh_d},
            reverse=True,
        )
        _w1_week = _w1_weeks[0] if _w1_weeks else None
        if _w1_week:
            _w1_canonical = _w1_week   # authoritative W-1 week from the dedicated query
            for entity, week_data in w1_breakdown.items():
                if _w1_week in week_data:
                    fail_weekly.setdefault(entity, {})[_w1_week] = week_data[_w1_week]

    # Per-WH daily breakdown: use the richer CASE-based query (ho_daily_breakdown, -7 days).
    # Fall back to ho_daily (card 26829 day-level) if not present.
    _daily_rec = data.get("ho_daily_breakdown") or data.get("ho_daily") or {"rows": [], "cols": ["warehouse_id", "expected_shipping_day", "First failed timestamp", "count"]}
    fail_daily = prepare_failure_breakdown_daily(_daily_rec)

    warehouses    = sorted(ho_pivot.columns.tolist())
    all_ho_weeks  = ho_pivot.index.tolist()   # newest first

    # HO ratio: skip only 1 most recent week (current week, data incomplete), show N_WEEKS_HO
    ho_weeks = all_ho_weeks[1 : 1 + N_WEEKS_HO]

    # Predictor: N_WEEKS_PRED most recent
    all_pred_weeks = sorted(
        {w for wh_d in predictor.values() for w in wh_d},
        reverse=True,
    )
    pred_weeks = all_pred_weeks[:N_WEEKS_PRED]

    # W-1: prefer the week from the dedicated ho_w1_breakdown query (it targets last complete week).
    # Fall back to SKIP_RECENT logic only when that record is absent.
    all_fail_weeks = sorted(
        {w for wh_d in fail_weekly.values() for w in wh_d if wh_d},
        reverse=True,
    )
    if _w1_canonical:
        w1 = _w1_canonical
    else:
        w1 = all_fail_weeks[SKIP_RECENT] if len(all_fail_weeks) > SKIP_RECENT else (all_fail_weeks[0] if all_fail_weeks else None)

    # Serialize HO ratio
    ho_ratio_out: dict = {}
    for wh in warehouses:
        ho_ratio_out[wh] = {}
        for week in all_ho_weeks:
            if week in ho_pivot.index and wh in ho_pivot.columns:
                v = ho_pivot.loc[week, wh]
                if not pd.isna(v):
                    ho_ratio_out[wh][week] = round(float(v), 4)

    return {
        "generated_at":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "warehouses":       warehouses,
        "ho_weeks":         ho_weeks,
        "pred_weeks":       pred_weeks,
        "w1":               w1,
        "fail_weeks":       all_fail_weeks[:N_WEEKS_PRED],
        "ho_ratio":         ho_ratio_out,
        "bb_avg":           {k: round(float(v), 4) for k, v in bb_avg.items() if not pd.isna(v)},
        "predictor":        predictor,
        "failure_drivers":  fail_driv,
        "failure_weekly":   fail_weekly,
        "failure_daily":    fail_daily,
        "merchants":        merchants,
        "all_buckets":      ALL_BUCKETS,
        "bucket_labels":    BUCKET_LABELS,
        "bucket_colors":    BUCKET_COLORS,
        "wh_actionable":    list(WH_ACTIONABLE),
    }


# ── HTML template ──────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bigblue Happy Orders Scorecard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 14px;
       background: #F5F7FA; color: #1a1a2e; }

/* ── Header ── */
#header { background: #1A237E; color: white; padding: 18px 28px;
          display: flex; align-items: center; justify-content: space-between; }
#header h1 { font-size: 1.3rem; font-weight: 700; }
.meta { font-size: 0.78rem; color: #90CAF9; }

/* ── Tab bar ── */
#tab-bar { background: white; border-bottom: 2px solid #E0E4EF;
           display: flex; flex-wrap: wrap; gap: 2px; padding: 0 20px;
           position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.tab-btn { border: none; background: none; cursor: pointer; padding: 12px 16px;
           font-size: 13px; font-weight: 500; color: #5c6780;
           border-bottom: 3px solid transparent; transition: all .15s; }
.tab-btn:hover  { color: #1A237E; background: #F0F2FF; }
.tab-btn.active { color: #1A237E; border-bottom-color: #1A237E; font-weight: 700; }

/* ── Content ── */
#content { max-width: 1280px; margin: 0 auto; padding: 28px 24px; }
.tab-pane { display: none; }
.tab-pane.active { display: block; }

section { background: white; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.06);
          padding: 20px 22px; margin-bottom: 24px; }
section h2 { font-size: 1rem; color: #1A237E; margin-bottom: 4px; }
section h3 { font-size: 1rem; color: #1A237E; margin-bottom: 4px; }
a.title-link { color: inherit; text-decoration: none; }
a.title-link:hover { text-decoration: underline; opacity: .8; }
section h4 { font-size: .85rem; color: #444; margin-bottom: 8px; }
.subtitle  { font-size: .78rem; color: #888; margin-bottom: 14px; }

/* ── Legend ── */
.legend { display: flex; gap: 18px; margin-bottom: 12px; font-size: .78rem; flex-wrap: wrap; }
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-dot  { width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; }

/* ── Tables ── */
.table-wrap { overflow-x: auto; }
table.sc { border-collapse: collapse; width: 100%; font-size: 13px; }
table.sc th { background: #37474F; color: white; font-weight: 600; font-size: 12px;
              padding: 8px 10px; text-align: center; white-space: nowrap; }
table.sc td { padding: 7px 10px; text-align: center; border-bottom: 1px solid #F0F2F5;
              white-space: nowrap; }
table.sc td.wh-label { text-align: left; font-weight: 600; color: #333; background: #FAFBFC;
                        border-right: 2px solid #E0E4EF; min-width: 120px; }
table.sc tr:last-child td { border-bottom: none; }
table.sc tr.bb-row td { background: #E3F2FD; font-weight: 600; }
table.sc tr.bb-row td.wh-label { background: #BBDEFB; }
table.sc tr:hover td:not(.wh-label) { filter: brightness(.95); }

/* ── Breakdown table ── */
table.sc td.act  { background: #FFF3E0; color: #E65100; font-weight: 600; }
table.sc td.ok   { background: #E8F5E9; color: #2E7D32; font-weight: 600; }
table.sc th.act  { background: #BF360C; }
table.sc th.ok   { background: #1B5E20; }

/* ── Charts ── */
.chart-wrap { position: relative; height: 260px; }
.charts-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }
.chart-half { }

/* ── Merchant table small ── */
table.mcht { border-collapse: collapse; width: 100%; font-size: 12px; max-height: 320px; }
table.mcht th { background: #ECEFF1; color: #333; font-weight: 600; font-size: 11px;
                padding: 6px 8px; text-align: left; position: sticky; top: 0; }
table.mcht td { padding: 5px 8px; border-bottom: 1px solid #F5F5F5; }
table.mcht tr:nth-child(even) td { background: #FAFAFA; }

/* ── Responsive ── */
@media (max-width: 600px) {
  #header h1 { font-size: 1rem; }
  .tab-btn    { padding: 10px 10px; font-size: 12px; }
  #content    { padding: 16px 12px; }
}
</style>
</head>
<body>

<div id="header">
  <h1>Bigblue — Happy Orders Scorecard</h1>
  <span class="meta">Generated <span id="gen-date"></span></span>
</div>

<div id="tab-bar">
  <button class="tab-btn active" data-tab="recap" onclick="switchTab('recap')">Recap</button>
</div>

<div id="content">
  <div id="tab-recap" class="tab-pane active">

    <section>
      <h2>Happy Orders Ratio — by Warehouse</h2>
      <p class="subtitle">
        Weeks W-1 to W-6 (current week excluded — data not yet complete).
        <strong>Higher % = better.</strong>
        Coloring applied to most recent shown week only.
      </p>
      <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background:#C8E6C9"></div> Top warehouse</div>
        <div class="legend-item"><div class="legend-dot" style="background:#FFCDD2"></div> Bottom 3 warehouses</div>
        <div class="legend-item"><div class="legend-dot" style="background:#E3F2FD"></div> BB Network average</div>
      </div>
      <div class="table-wrap" id="ho-ratio-table"></div>
    </section>

    <section>
      <h2>First Failure Point Breakdown — W-1</h2>
      <p class="subtitle">
        % of orders by first failure timestamp for last complete week.
        <strong>Buckets 1–6</strong> are WH-actionable (orange). <strong>Buckets 7–8</strong> are not (green).
      </p>
      <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background:#FFF3E0;border:1px solid #E65100"></div> WH-actionable (1–6)</div>
        <div class="legend-item"><div class="legend-dot" style="background:#E8F5E9;border:1px solid #2E7D32"></div> Not actionable (7–8)</div>
      </div>
      <div class="table-wrap" id="breakdown-w1-table"></div>
    </section>

  </div>
</div>

<script>
const DATA = __DATA_PLACEHOLDER__;

// ── Formatting helpers ──────────────────────────────────────────────────────
function fmtPct(v, dec=0) {
  return v == null ? '—' : (v * 100).toFixed(dec) + '%';
}
function fmtPred(v) {
  return v == null ? '—' : v.toFixed(1) + '%';
}
function fmtBucket(v) {
  return v == null ? '—' : v.toFixed(1) + '%';
}
function fmtWeek(w) {
  const d = new Date(w + 'T12:00:00');
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' });
}
function fmtDay(w) {
  const d = new Date(w + 'T12:00:00');
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short' });
}

// ── Color ranking ───────────────────────────────────────────────────────────
function rankColors(valueMap, higherIsBetter) {
  const whs = Object.keys(valueMap).filter(k => valueMap[k] != null);
  const sorted = [...whs].sort((a, b) =>
    higherIsBetter ? valueMap[b] - valueMap[a] : valueMap[a] - valueMap[b]
  );
  const colors = {};
  whs.forEach(wh => colors[wh] = '#ffffff');
  if (sorted.length > 0) colors[sorted[0]] = '#C8E6C9';
  sorted.slice(-3).forEach(wh => { if (colors[wh] !== '#C8E6C9') colors[wh] = '#FFCDD2'; });
  return colors;
}

// ── Tab switching ───────────────────────────────────────────────────────────
const chartsReady = {};

function switchTab(id) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelector(`.tab-btn[data-tab="${id}"]`).classList.add('active');
  document.getElementById(`tab-${id}`).classList.add('active');
  if (id !== 'recap' && !chartsReady[id]) {
    renderWhTab(id);
    chartsReady[id] = true;
  }
}

// ── Render HO ratio table ───────────────────────────────────────────────────
function renderHoRatioTable() {
  const { ho_weeks, warehouses, ho_ratio, bb_avg } = DATA;
  if (!ho_weeks.length) {
    document.getElementById('ho-ratio-table').innerHTML = '<p style="color:#999">No data.</p>';
    return;
  }

  let html = '<table class="sc"><thead><tr><th>Warehouse</th>';
  ho_weeks.forEach(w => html += `<th>${fmtWeek(w)}</th>`);
  html += '</tr></thead><tbody>';

  warehouses.forEach(wh => {
    const latestWeek = ho_weeks[0];
    const latestVals = {};
    warehouses.forEach(w2 => latestVals[w2] = ho_ratio[w2]?.[latestWeek] ?? null);
    const colors = rankColors(latestVals, true);

    html += `<tr><td class="wh-label">${wh}</td>`;
    ho_weeks.forEach((week, i) => {
      const val = ho_ratio[wh]?.[week];
      const bg  = i === 0 ? (colors[wh] || '#fff') : '#fff';
      html += `<td style="background:${bg}">${fmtPct(val)}</td>`;
    });
    html += '</tr>';
  });

  // BB average row
  html += '<tr class="bb-row"><td class="wh-label">BB Average</td>';
  ho_weeks.forEach(week => {
    const val = bb_avg[week];
    html += `<td>${val != null ? fmtPct(val) : '—'}</td>`;
  });
  html += '</tr></tbody></table>';
  document.getElementById('ho-ratio-table').innerHTML = html;
}

// ── Render First Failure breakdown W-1 table ────────────────────────────────
function renderBreakdownW1Table() {
  const { warehouses, w1, failure_weekly, all_buckets, bucket_labels, bucket_colors } = DATA;
  if (!w1) {
    document.getElementById('breakdown-w1-table').innerHTML = '<p style="color:#999">No data.</p>';
    return;
  }

  const actionable = new Set(DATA.wh_actionable);
  const rows = ['Network', ...warehouses];

  let html = `<table class="sc"><thead><tr><th>Warehouse</th>`;
  all_buckets.forEach((b, i) => {
    const cls = actionable.has(b) ? 'act' : 'ok';
    html += `<th class="${cls}">${bucket_labels[i]}</th>`;
  });
  html += '</tr></thead><tbody>';

  rows.forEach(row => {
    const isNetwork = row === 'Network';
    const data = failure_weekly[row]?.[w1] || {};
    html += `<tr${isNetwork ? ' class="bb-row"' : ''}>`;
    html += `<td class="wh-label">${isNetwork ? `Network (${fmtWeek(w1)})` : row}</td>`;
    all_buckets.forEach(b => {
      const v = data[b];
      const actionCls = actionable.has(b) ? 'act' : 'ok';
      html += `<td class="${actionCls}">${v != null ? v.toFixed(1) + '%' : '—'}</td>`;
    });
    html += '</tr>';
  });

  html += '</tbody></table>';
  document.getElementById('breakdown-w1-table').innerHTML = html;
}

// ── Build breakdown table HTML ──────────────────────────────────────────────
function buildBreakdownTable(data, periods, fmtFn) {
  // data: {period: {bucket: pct}}
  // periods: sorted array (desc)
  const { all_buckets, bucket_labels, wh_actionable } = DATA;
  const actionable = new Set(wh_actionable);

  let html = '<table class="sc"><thead><tr><th>Period</th>';
  all_buckets.forEach((b, i) => {
    const cls = actionable.has(b) ? 'act' : 'ok';
    html += `<th class="${cls}">${bucket_labels[i]}</th>`;
  });
  html += '</tr></thead><tbody>';

  periods.forEach((p, idx) => {
    const row = data[p] || {};
    html += `<tr><td class="wh-label">${fmtFn(p)}${idx === 0 ? ' <span style="font-size:10px;background:#1A237E;color:white;padding:1px 5px;border-radius:3px;margin-left:4px">latest</span>' : ''}</td>`;
    all_buckets.forEach(b => {
      const v = row[b];
      const cls = actionable.has(b) ? 'act' : 'ok';
      html += `<td class="${cls}">${v != null ? v.toFixed(1) + '%' : '—'}</td>`;
    });
    html += '</tr>';
  });

  html += '</tbody></table>';
  return html;
}

// ── Render per-WH tab ───────────────────────────────────────────────────────
function renderWhTab(wh) {
  const { pred_weeks, fail_weeks, predictor, failure_drivers, failure_weekly, failure_daily,
          merchants, all_buckets, bucket_labels, bucket_colors } = DATA;

  const pane = document.getElementById(`tab-${wh}`);
  const latestWeeks = pred_weeks.slice(0, 2);
  const latestWeek  = pred_weeks[0];

  // Daily: all days for this WH, sorted desc
  const dailyData = failure_daily[wh] || {};
  const dailyDays = Object.keys(dailyData).sort().reverse();

  // Weekly breakdown for this WH
  const weeklyData = failure_weekly[wh] || {};
  const weeklyWeeks = fail_weeks.filter(w => weeklyData[w]);

  pane.innerHTML = `
    <section>
      <h3>Predictor Metric Trend — ${wh}</h3>
      <p class="subtitle">% of orders with WH-actionable failure timestamp (buckets 1–6). Lower = better.</p>
      <div class="chart-wrap"><canvas id="cp-${wh}"></canvas></div>
    </section>

    <section>
      <h3>Failure Drivers — ${wh}</h3>
      <p class="subtitle">Order count by first failure timestamp. Orange/red = WH-actionable. Blue/green = not WH-actionable.</p>
      <div class="charts-row">
        ${latestWeeks.map((w, i) => `
          <div class="chart-half">
            <h4>${fmtWeek(w)}</h4>
            <div class="chart-wrap"><canvas id="cf-${wh}-${i}"></canvas></div>
          </div>`).join('')}
      </div>
    </section>

    <section>
      <h3><a href="https://metabase.internal.bigblue.co/question/29962-failure-timestamp-per-day-week-12" target="_blank" rel="noopener" class="title-link">First Failure Breakdown by Week — ${wh}</a></h3>
      <p class="subtitle">% of orders per failure bucket, by week. Buckets 1–6 are WH-actionable (orange).</p>
      <div class="table-wrap" id="wkb-${wh}"></div>
    </section>

    <section>
      <h3><a href="https://metabase.internal.bigblue.co/question/27734-failure-timestamp-per-day-week-1" target="_blank" rel="noopener" class="title-link">First Failure Breakdown by Day — W-1 — ${wh}</a></h3>
      <p class="subtitle">Daily breakdown for the last 14 days. Buckets 1–6 are WH-actionable (orange).</p>
      <div class="table-wrap" id="dayb-${wh}"></div>
    </section>

    <section>
      <h3>Merchant Breakdown — ${wh}</h3>
      <p class="subtitle">Latest week available (${fmtWeek(latestWeek)}). Sorted by order count.</p>
      <div class="table-wrap" id="mt-${wh}"></div>
    </section>
  `;

  // Predictor trend chart
  const predLabels  = [...pred_weeks].reverse().map(fmtWeek);
  const predValues  = [...pred_weeks].reverse().map(w => predictor[wh]?.[w] ?? null);
  new Chart(document.getElementById(`cp-${wh}`), {
    type: 'line',
    data: {
      labels: predLabels,
      datasets: [{
        label: 'WH Actionable %',
        data: predValues,
        borderColor: '#EF5350',
        backgroundColor: 'rgba(239,83,80,.1)',
        fill: true,
        tension: 0.3,
        spanGaps: true,
        pointRadius: 4,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: '% WH-actionable' } },
      },
    },
  });

  // Failure driver charts
  latestWeeks.forEach((week, i) => {
    const drivers = failure_drivers[wh]?.[week] || {};
    const vals = all_buckets.map(b => drivers[b] || 0);
    new Chart(document.getElementById(`cf-${wh}-${i}`), {
      type: 'bar',
      data: {
        labels: bucket_labels,
        datasets: [{
          data: vals,
          backgroundColor: bucket_colors,
          borderWidth: 0,
        }],
      },
      options: {
        indexAxis: 'y',
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, title: { display: true, text: 'Orders' } } },
      },
    });
  });

  // Weekly breakdown table
  document.getElementById(`wkb-${wh}`).innerHTML =
    weeklyWeeks.length ? buildBreakdownTable(weeklyData, weeklyWeeks, fmtWeek) : '<p style="color:#999">No data.</p>';

  // Daily breakdown table
  document.getElementById(`dayb-${wh}`).innerHTML =
    dailyDays.length ? buildBreakdownTable(dailyData, dailyDays, fmtDay) : '<p style="color:#999">No daily data available.</p>';

  // Merchant table
  const mData = merchants[wh]?.[latestWeek] || [];
  let mHtml = '<table class="mcht"><thead><tr><th>Merchant</th><th>Orders</th><th>HO Ratio</th></tr></thead><tbody>';
  mData.forEach(m => {
    mHtml += `<tr><td>${m.merchant_id}</td><td>${m.count}</td><td>${fmtPct(m.ho_ratio)}</td></tr>`;
  });
  if (!mData.length) mHtml += '<tr><td colspan="3" style="color:#999;text-align:center">No data</td></tr>';
  mHtml += '</tbody></table>';
  document.getElementById(`mt-${wh}`).innerHTML = mHtml;
}

// ── Bootstrap ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('gen-date').textContent = DATA.generated_at;

  const tabBar = document.getElementById('tab-bar');
  const content = document.getElementById('content');

  DATA.warehouses.forEach(wh => {
    const btn = document.createElement('button');
    btn.className = 'tab-btn';
    btn.dataset.tab = wh;
    btn.textContent = wh;
    btn.onclick = () => switchTab(wh);
    tabBar.appendChild(btn);

    const pane = document.createElement('div');
    pane.id = `tab-${wh}`;
    pane.className = 'tab-pane';
    content.appendChild(pane);
  });

  renderHoRatioTable();
  renderBreakdownW1Table();
});
</script>
</body>
</html>
"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("── Bigblue HO Scorecard HTML Generator ──")
    print(f"  Data file : {DATA_FILE}")
    print(f"  Output    : {OUTPUT}")

    blob = build_blob()
    print(f"  Warehouses: {', '.join(blob['warehouses'])}")
    print(f"  HO weeks  : {blob['ho_weeks'][:3]}…")
    print(f"  Pred weeks: {blob['pred_weeks'][:3]}…")
    print(f"  W-1       : {blob['w1']}")
    daily_whs = [wh for wh in blob['warehouses'] if blob['failure_daily'].get(wh)]
    print(f"  Daily data: {', '.join(daily_whs) if daily_whs else 'none'}")

    html = HTML_TEMPLATE.replace(
        "__DATA_PLACEHOLDER__",
        json.dumps(blob, ensure_ascii=False),
    )

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ Written {OUTPUT}")


if __name__ == "__main__":
    main()
