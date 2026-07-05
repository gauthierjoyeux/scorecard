#!/bin/bash
# ── Bigblue Scorecards — full automated update ────────────────────────────────
# Fetches fresh data from Metabase, regenerates both HTML files, and pushes.
# Designed to run unattended (e.g. via launchd weekly timer).
#
# First-time setup:
#   1. Log in to metabase.internal.bigblue.co in Chrome
#   2. DevTools → Application → Cookies → copy value of 'metabase.SESSION'
#   3. echo "YOUR_TOKEN" > .metabase_session
#   4. Run ./setup_launchd.sh   (sets up the weekly timer)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

TOKEN_FILE="${SCRIPT_DIR}/.metabase_session"
GH_TOKEN_FILE="${SCRIPT_DIR}/.github_token"
LOG_FILE="${SCRIPT_DIR}/update.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M')] $*" | tee -a "$LOG_FILE"; }

log "═══════════════════════════════════════════════"
log "Starting scorecard update"

# ── 1. Fetch data ──────────────────────────────────────────────────────────────
if [ ! -f "$TOKEN_FILE" ]; then
  log "❌  No .metabase_session file found."
  log "    See fetch_mb.py header for setup instructions."
  exit 1
fi

log "Fetching Metabase data…"
if ! python3 "${SCRIPT_DIR}/fetch_mb.py"; then
  log "❌  Fetch failed — see output above (session may be expired)."
  exit 1
fi

# ── 2. Generate HTML files ─────────────────────────────────────────────────────
log "Generating index.html (Warehouse Scorecard)…"
python3 "${SCRIPT_DIR}/generate_html.py"

log "Generating ho_index.html (Happy Orders Scorecard)…"
python3 "${SCRIPT_DIR}/generate_ho_html.py"

# ── 3. Commit & push ───────────────────────────────────────────────────────────
WEEK=$(date +"%Y-W%W")
log "Committing…"
git add index.html ho_index.html
if git diff --cached --quiet; then
  log "ℹ️  No changes — already up to date."
  exit 0
fi
git commit -m "Scorecard auto-update ${WEEK}"

log "Pushing to GitHub…"
if [ -f "$GH_TOKEN_FILE" ]; then
  GH_TOKEN=$(cat "$GH_TOKEN_FILE")
  git remote set-url origin "https://${GH_TOKEN}@github.com/gauthierjoyeux/scorecard.git"
fi
git push origin main

log "✅  Done — live at:"
log "    https://gauthierjoyeux.github.io/scorecard/"
log "    https://gauthierjoyeux.github.io/scorecard/ho_index.html"
