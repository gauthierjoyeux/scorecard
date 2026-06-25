#!/usr/bin/env python3
"""
Bigblue Weekly Scorecard Report
Pulls data from Metabase, generates a color-coded PDF (1 page per metric),
and optionally posts it to Slack.

Required env vars:
  METABASE_USER      - Metabase login email
  METABASE_PASSWORD  - Metabase password

Optional env vars:
  METABASE_URL       - default: https://metabase.internal.bigblue.co
  SLACK_TOKEN        - Slack Bot token (xoxb-...)
  SLACK_CHANNEL      - Slack channel ID (e.g. C12345678)
  WEEKS              - number of weeks to display (default: 8)
"""

import os
import sys
import warnings
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────────────

METABASE_URL   = os.environ.get("METABASE_URL", "https://metabase.internal.bigblue.co")
METABASE_USER  = os.environ.get("METABASE_USER", "")
METABASE_PASS  = os.environ.get("METABASE_PASSWORD", "")
SLACK_TOKEN    = os.environ.get("SLACK_TOKEN", "")
SLACK_CHANNEL  = os.environ.get("SLACK_CHANNEL", "")
N_WEEKS        = int(os.environ.get("WEEKS", "8"))

# Scorecard questions — each metric produces one PDF page.
# color=False disables rank-based coloring for that metric.
SCORECARD_QUESTIONS = [
    dict(id=26473, name="B2C Pack UPH",      wh_col="warehouse_id",          date_col="week_start",      color=True),
    dict(id=26435, name="B2C NAC",           wh_col="warehouse_id",          date_col="preparation_day", color=False),
    dict(id=26434, name="B2C Pick UPH",      wh_col="warehouse_id",          date_col="preparation_day", color=True),
    dict(id=26470, name="Ship UPH",          wh_col="warehouse_external_id", date_col="ship_time",       color=True),
    dict(id=26471, name="Inbound (Receive)", wh_col="warehouse_external_id", date_col="create_time",     color=True),
    dict(id=26472, name="Replenishments",    wh_col="warehouse_external_id", date_col="update_time",     color=True),
]

# ── Colors ─────────────────────────────────────────────────────────────────────

GREEN  = "#C8E6C9"   # top 1 warehouse per week
RED    = "#FFCDD2"   # bottom 3 warehouses per week
WHITE  = "#FFFFFF"   # mid-rank or no coloring
BLUE   = "#BBDEFB"   # network average column
HEADER = "#37474F"   # table header background

# ── Metabase helpers ───────────────────────────────────────────────────────────

def get_session_token() -> str:
    if not METABASE_USER or not METABASE_PASS:
        sys.exit("ERROR: Set METABASE_USER and METABASE_PASSWORD environment variables.")
    r = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_USER, "password": METABASE_PASS},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def query_card(token: str, card_id: int) -> pd.DataFrame:
    r = requests.post(
        f"{METABASE_URL}/api/card/{card_id}/query",
        headers={"X-Metabase-Session": token, "Content-Type": "application/json"},
        json={},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()["data"]
    cols = [c["name"] for c in data["cols"]]
    return pd.DataFrame(data["rows"], columns=cols)

# ── Data processing ────────────────────────────────────────────────────────────

def prepare_pivot(df: pd.DataFrame, q: dict, n_weeks: int) -> pd.DataFrame:
    """Return pivot: index=week label, columns=warehouses + 'Network Avg'."""
    wh_col   = q["wh_col"]
    date_col = q["date_col"]

    # Drop pivot subtotal rows
    if "pivot-grouping" in df.columns:
        df = df[df["pivot-grouping"] == 0].copy()

    df[date_col] = pd.to_datetime(df[date_col], utc=True).dt.tz_localize(None).dt.normalize()
    df["avg"]    = pd.to_numeric(df["avg"], errors="coerce")

    # Keep last n_weeks
    latest = sorted(df[date_col].unique())[-n_weeks:]
    df = df[df[date_col].isin(latest)]

    pivot = df.pivot_table(index=date_col, columns=wh_col, values="avg", aggfunc="mean")
    pivot.sort_index(ascending=False, inplace=True)   # most recent week first
    pivot.index = [pd.Timestamp(d).strftime("%d %b %Y") for d in pivot.index]

    # Network average column (mean across warehouses)
    pivot["Network Avg"] = pivot.mean(axis=1)
    return pivot

# ── Row-level color assignment ─────────────────────────────────────────────────

def row_colors(pivot: pd.DataFrame, week: str, enable_color: bool) -> list:
    """
    For a single week row, return a list of background colors.
    Columns order: warehouses... + Network Avg.
    Coloring rule (when enable_color=True):
      - highest value → GREEN
      - bottom 3 values → RED
      - rest → WHITE
    Network Avg column is always BLUE.
    """
    warehouses = [c for c in pivot.columns if c != "Network Avg"]
    n_wh = len(warehouses)

    if not enable_color or n_wh == 0:
        return [WHITE] * n_wh + [BLUE]

    vals = {wh: pivot.loc[week, wh] for wh in warehouses}
    valid = {wh: v for wh, v in vals.items() if not pd.isna(v)}

    colors_map = {wh: WHITE for wh in warehouses}
    if valid:
        sorted_wh = sorted(valid, key=lambda w: valid[w], reverse=True)
        # Top 1
        colors_map[sorted_wh[0]] = GREEN
        # Bottom 3 (only if they are not also the top)
        for wh in sorted_wh[-3:]:
            if colors_map[wh] != GREEN:
                colors_map[wh] = RED

    return [colors_map[wh] for wh in warehouses] + [BLUE]

# ── PDF page builder ───────────────────────────────────────────────────────────

def add_page(pdf: PdfPages, q: dict, pivot: pd.DataFrame) -> None:
    warehouses = [c for c in pivot.columns if c != "Network Avg"]
    all_cols   = warehouses + ["Network Avg"]
    pivot      = pivot[all_cols]
    n_rows     = len(pivot)
    n_cols     = len(all_cols)

    fig = plt.figure(figsize=(14, 8.5))
    ax  = fig.add_subplot(111)
    ax.axis("off")

    # Title
    week_range = f'{pivot.index[-1]}  →  {pivot.index[0]}'   # oldest → newest
    fig.suptitle(f'Bigblue Scorecard  ·  {q["name"]}', fontsize=15, fontweight="bold", y=0.97, x=0.5)
    ax.set_title(f'Last {n_rows} weeks  ({week_range})', fontsize=9, color="#666666", pad=6)

    # Build cell text and colors
    cell_text   = []
    cell_colors = []
    for week in pivot.index:
        row_text = []
        for col in all_cols:
            val = pivot.loc[week, col]
            row_text.append(f"{val:.1f}" if not pd.isna(val) else "—")
        cell_text.append(row_text)
        cell_colors.append(row_colors(pivot, week, q["color"]))

    # Draw table
    tbl = ax.table(
        cellText=cell_text,
        rowLabels=list(pivot.index),
        colLabels=all_cols,
        cellColours=cell_colors,
        cellLoc="center",
        loc="center",
        bbox=[0.0, 0.08, 1.0, 0.85],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)

    # Header row
    for j in range(n_cols):
        hcell = tbl[0, j]
        hcell.set_facecolor(HEADER)
        hcell.set_text_props(color="white", fontweight="bold", fontsize=8)
        hcell.set_height(0.06)

    # Row-label column
    for i in range(1, n_rows + 1):
        lcell = tbl[i, -1]
        lcell.set_facecolor("#ECEFF1")
        lcell.set_text_props(fontweight="bold", fontsize=8)

    # Widen Network Avg column
    for i in range(n_rows + 1):
        tbl[i, n_cols - 1].set_width(0.14)

    # Legend (only for colored metrics)
    if q["color"]:
        legend = [
            mpatches.Patch(color=GREEN, label="Top performer (week)"),
            mpatches.Patch(color=RED,   label="Bottom 3 (week)"),
            mpatches.Patch(color=BLUE,  label="Network average"),
        ]
        ax.legend(handles=legend, loc="lower right", fontsize=8, framealpha=0.9,
                  bbox_to_anchor=(1.0, -0.04), ncol=3)

    # Footer
    fig.text(0.5, 0.01,
             f'Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}  ·  Bigblue Operations',
             ha="center", fontsize=7, color="#BDBDBD")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

# ── Slack upload ───────────────────────────────────────────────────────────────

def post_to_slack(pdf_path: str) -> None:
    week_label = datetime.now().strftime("W%W – %d %b %Y")
    file_size  = os.path.getsize(pdf_path)

    r = requests.post(
        "https://slack.com/api/files.getUploadURLExternal",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
        json={"filename": os.path.basename(pdf_path), "length": file_size},
        timeout=30,
    )
    r.raise_for_status()
    info = r.json()
    if not info.get("ok"):
        raise RuntimeError(f"Slack getUploadURLExternal error: {info.get('error')}")

    with open(pdf_path, "rb") as fh:
        up = requests.post(info["upload_url"], files={"file": fh}, timeout=60)
        up.raise_for_status()

    r = requests.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
        json={
            "files":           [{"id": info["file_id"]}],
            "channel_id":      SLACK_CHANNEL,
            "initial_comment": (
                f":bar_chart: *Weekly Scorecard — {week_label}*\n"
                "One page per metric  ·  :green_circle: top performer  ·  :red_circle: bottom 3"
            ),
        },
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()
    if not result.get("ok"):
        raise RuntimeError(f"Slack completeUpload error: {result.get('error')}")
    print(f"  ✓ Posted to Slack channel {SLACK_CHANNEL}")

# ── Main ───────────────────────────────────────────────────────────────────────

def load_data_from_file(path: str) -> dict:
    """Load pre-fetched data from a JSON file (browser export)."""
    import json
    with open(path) as f:
        records = json.load(f)
    # Index by card id for easy lookup
    return {r["id"]: r for r in records}


def query_card_from_cache(cache: dict, card_id: int) -> pd.DataFrame:
    record = cache[card_id]
    return pd.DataFrame(record["rows"], columns=record["cols"])


def main():
    import json

    # Support two modes:
    #   1. DATA_FILE env var (or default Downloads location) — no Metabase auth needed
    #   2. Live Metabase API (requires METABASE_USER + METABASE_PASSWORD)
    data_file = os.environ.get(
        "DATA_FILE",
        os.path.expanduser("~/Downloads/scorecard_data.json")
    )

    use_file = os.path.exists(data_file)

    print("── Bigblue Scorecard Report ──────────────────────")
    if use_file:
        print(f"  Mode     : local file ({data_file})")
        cache = load_data_from_file(data_file)
    else:
        print(f"  Mode     : live Metabase ({METABASE_URL})")
        print("\n[1/3] Authenticating with Metabase...")
        token = get_session_token()

    print(f"  Weeks    : {N_WEEKS}")

    output = f"scorecard_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    print(f"\n[{'1' if use_file else '2'}/{'2' if use_file else '3'}] Building PDF → {output}")

    with PdfPages(output) as pdf:
        # Cover page
        fig = plt.figure(figsize=(14, 8.5))
        ax  = fig.add_subplot(111)
        ax.axis("off")
        ax.set_facecolor("#1A237E")
        fig.patch.set_facecolor("#1A237E")
        week_label = datetime.now().strftime("Week %W  ·  %d %B %Y")
        ax.text(0.5, 0.58, "BIGBLUE", transform=ax.transAxes,
                ha="center", va="center", fontsize=40, fontweight="bold", color="white")
        ax.text(0.5, 0.47, "Warehouse Scorecard", transform=ax.transAxes,
                ha="center", va="center", fontsize=22, color="#90CAF9")
        ax.text(0.5, 0.36, week_label, transform=ax.transAxes,
                ha="center", va="center", fontsize=14, color="#B3E5FC")
        ax.text(0.5, 0.22,
                "  ·  ".join(q["name"] for q in SCORECARD_QUESTIONS),
                transform=ax.transAxes, ha="center", va="center", fontsize=9, color="#78909C")
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        for q in SCORECARD_QUESTIONS:
            print(f"  • {q['name']}...")
            try:
                if use_file:
                    df = query_card_from_cache(cache, q["id"])
                else:
                    df = query_card(token, q["id"])
                pivot = prepare_pivot(df, q, N_WEEKS)
                if pivot.empty:
                    print(f"    ↳ no data, skipping")
                    continue
                add_page(pdf, q, pivot)
            except Exception as exc:
                print(f"    ↳ ERROR: {exc}")

    print(f"  ✓ Saved {output}")

    if SLACK_TOKEN and SLACK_CHANNEL:
        step = "2" if use_file else "3"
        print(f"\n[{step}/{step}] Posting to Slack...")
        post_to_slack(output)
    else:
        print("\nSlack not configured — skipping.")
        print("Set SLACK_TOKEN and SLACK_CHANNEL to enable auto-posting.")

    print("\nDone.")


if __name__ == "__main__":
    main()
