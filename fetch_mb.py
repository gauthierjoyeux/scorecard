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
    ho_path = save(ho_data, "ho_data.json")
    print(f"  ✓ {ho_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
