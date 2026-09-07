#!/usr/bin/env python3
"""
Fetch Metabase data for both scorecards using a stored session token.

Setup (one-time):
  1. Open Chrome and log in to metabase.internal.bigblue.co
  2. Open DevTools → Application → Cookies → metabase.internal.bigblue.co
  3. Copy the value of the 'metabase.SESSION' cookie
  4. Paste it into .metabase_session (one line, no spaces)

The session token lasts ~2 weeks. Re-run setup when the script says "Session expired."
"""

import json
import os
import sys
import time
import requests

METABASE_URL  = "https://metabase.internal.bigblue.co"
TOKEN_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".metabase_session")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")

SCORECARD_QUESTIONS = [
    dict(id=26473, pivot=True),
    dict(id=26435, pivot=True),
    dict(id=26434, pivot=True),
    dict(id=26470, pivot=True),
    dict(id=26471, pivot=True),
    dict(id=26472, pivot=True),
]

HO_QUESTIONS = [
    dict(id=26830, pivot=True),
    dict(id=26831, pivot=False),
    dict(id=26829, pivot=False),
    dict(id=26832, pivot=False),
]


def load_token() -> str:
    if not os.path.exists(TOKEN_FILE):
        sys.exit(
            "❌  No session token found.\n"
            "    1. Open Chrome → metabase.internal.bigblue.co (stay logged in)\n"
            "    2. DevTools (Cmd+Option+J) → Application → Cookies → metabase.internal.bigblue.co\n"
            "    3. Copy the value of 'metabase.SESSION'\n"
            f"    4. Save it to: {TOKEN_FILE}"
        )
    token = open(TOKEN_FILE).read().strip()
    if not token:
        sys.exit(f"❌  {TOKEN_FILE} is empty. Paste your session token there.")
    return token


_HO_W1_QUERY_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ho_w1_query.json")
_HO_WEEKLY_QUERY_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ho_weekly_breakdown_query.json")
_HO_DAILY_QUERY_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ho_daily_breakdown_query.json")


def _post_dataset(session: str, query: dict) -> dict:
    resp = requests.post(
        f"{METABASE_URL}/api/dataset",
        headers={"X-Metabase-Session": session, "Content-Type": "application/json"},
        json=query,
        timeout=120,
    )
    if resp.status_code not in (200, 202):
        resp.raise_for_status()
    data = resp.json()["data"]
    return {"cols": [c["name"] for c in data["cols"]], "rows": data["rows"]}


def fetch_ho_w1_breakdown(session: str) -> dict:
    """Fetch W-1 failure-timestamp breakdown (all WHs) using the richer CASE-based query.

    The query is stored verbatim in ho_w1_query.json (extracted from the Metabase question URL).
    It returns (warehouse_id, expected_shipping_day week, First failed timestamp, count)
    filtered to last 1 week.
    """
    with open(_HO_W1_QUERY_FILE) as f:
        query = json.load(f)
    d = _post_dataset(session, query)
    return {"id": "ho_w1_breakdown", **d}


def fetch_ho_weekly_breakdown(session: str) -> dict:
    """Fetch per-WH weekly failure-timestamp breakdown using the richer CASE query (-3 months)."""
    with open(_HO_WEEKLY_QUERY_FILE) as f:
        query = json.load(f)
    d = _post_dataset(session, query)
    return {"id": "ho_weekly_breakdown", **d}


def fetch_ho_daily_breakdown(session: str) -> dict:
    """Fetch per-WH daily failure-timestamp breakdown using the richer CASE query (-7 days)."""
    with open(_HO_DAILY_QUERY_FILE) as f:
        query = json.load(f)
    d = _post_dataset(session, query)
    return {"id": "ho_daily_breakdown", **d}


def fetch_ho_daily(session: str) -> dict:
    """Fetch failure-timestamp breakdown at daily granularity (card 26829 modified to day-level)."""
    # Load card 26829's query and swap temporal-unit week→day, filter to last 14 days
    r = requests.get(
        f"{METABASE_URL}/api/card/26829",
        headers={"X-Metabase-Session": session},
        timeout=30,
    )
    r.raise_for_status()
    dq = r.json()["dataset_query"]

    import copy
    dq2 = copy.deepcopy(dq)
    stage = dq2["stages"][0]

    # Change temporal-unit week → day in breakout
    for b in stage.get("breakout", []):
        if isinstance(b, list) and len(b) >= 2 and isinstance(b[1], dict):
            if b[1].get("temporal-unit") == "week":
                b[1]["temporal-unit"] = "day"

    # Replace time-interval filter: last 14 days (covers W-1 fully)
    new_filters = []
    for f in stage.get("filters", []):
        if isinstance(f, list) and f[0] == "time-interval":
            # Replace with last-14-days
            f2 = copy.deepcopy(f)
            # f2 structure: ["time-interval", opts, field_ref, n, unit]
            if len(f2) >= 5:
                f2[3] = -14
                f2[4] = "day"
            new_filters.append(f2)
        else:
            new_filters.append(f)
    stage["filters"] = new_filters

    resp = requests.post(
        f"{METABASE_URL}/api/dataset",
        headers={"X-Metabase-Session": session, "Content-Type": "application/json"},
        json=dq2,
        timeout=120,
    )
    # Metabase returns 202 for async queries that resolve synchronously
    if resp.status_code not in (200, 202):
        resp.raise_for_status()
    data = resp.json()["data"]
    return {
        "id": "ho_daily",
        "cols": [c["name"] for c in data["cols"]],
        "rows": data["rows"],
    }


def fetch_card(session: str, card_id: int, pivot: bool) -> dict:
    endpoint = (
        f"{METABASE_URL}/api/card/pivot/{card_id}/query"
        if pivot
        else f"{METABASE_URL}/api/card/{card_id}/query"
    )
    r = requests.post(
        endpoint,
        headers={
            "X-Metabase-Session": session,
            "Content-Type": "application/json",
        },
        json={"ignore_cache": True},
        timeout=120,
    )
    if r.status_code == 401:
        sys.exit(
            "❌  Session expired.\n"
            "    1. Log in to metabase.internal.bigblue.co in Chrome\n"
            "    2. DevTools → Application → Cookies → copy 'metabase.SESSION'\n"
            f"    3. Save it to: {TOKEN_FILE}"
        )
    r.raise_for_status()
    data = r.json()["data"]
    return {
        "id":   card_id,
        "cols": [c["name"] for c in data["cols"]],
        "rows": data["rows"],
    }


def fetch_all(questions: list, label: str) -> list:
    session = load_token()
    results = []
    for q in questions:
        print(f"  → {label} card {q['id']}  ({'pivot' if q['pivot'] else 'regular'})…", flush=True)
        result = fetch_card(session, q["id"], q["pivot"])
        results.append(result)
        time.sleep(0.5)   # be kind to Metabase
    return results


def save(data: list, filename: str) -> str:
    path = os.path.join(DOWNLOADS_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def main():
    print("── Fetching Metabase data ───────────────────────────────────")

    print("\n[1/2] Warehouse Scorecard…")
    sc_data = fetch_all(SCORECARD_QUESTIONS, "scorecard")
    sc_path = save(sc_data, "scorecard_data.json")
    print(f"  ✓ {sc_path}")

    print("\n[2/2] Happy Orders Scorecard…")
    ho_data = fetch_all(HO_QUESTIONS, "HO")
    session = load_token()
    print("  → HO W-1 breakdown (richer CASE query · last 1 week)…", flush=True)
    ho_data.append(fetch_ho_w1_breakdown(session))
    print("  → HO weekly breakdown (richer CASE query · last 3 months)…", flush=True)
    ho_data.append(fetch_ho_weekly_breakdown(session))
    print("  → HO daily breakdown (richer CASE query · last 7 days)…", flush=True)
    ho_data.append(fetch_ho_daily_breakdown(session))
    ho_path = save(ho_data, "ho_data.json")
    print(f"  ✓ {ho_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
