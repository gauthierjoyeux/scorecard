#!/bin/bash
# ── Bigblue Happy Orders Scorecard — weekly update ────────────────────────────
# Usage: ./update_ho.sh
#
# Before running this script, fetch fresh data from Metabase:
#   1. Open https://metabase.internal.bigblue.co in Chrome (stay logged in)
#   2. Open DevTools console (Cmd+Option+J)
#   3. Paste and run the contents of fetch_ho_data.js
#   4. ho_data.json will download automatically
#   5. Then run this script

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

TOKEN_FILE="${SCRIPT_DIR}/.github_token"

# ── Find data file ─────────────────────────────────────────────────────────────
DATA_FILE=$(ls -t "${HOME}/Downloads/ho_data"*.json 2>/dev/null | head -1)
if [ -z "$DATA_FILE" ]; then
  echo "❌  No ho_data*.json found in ~/Downloads"
  echo "    Fetch it from Metabase first (see instructions above)."
  exit 1
fi
echo "📂  Using data file: $DATA_FILE"

AGE=$(( $(date +%s) - $(stat -f %m "$DATA_FILE") ))
if [ "$AGE" -gt 86400 ]; then
  echo "⚠️  Data file is more than 24h old (${AGE}s). Consider re-fetching."
  read -p "   Continue anyway? [y/N] " -n 1 -r; echo
  [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

# ── Generate HTML ──────────────────────────────────────────────────────────────
echo "🔄  Generating ho_index.html…"
DATA_FILE="$DATA_FILE" python3 "$SCRIPT_DIR/generate_ho_html.py"

# ── Git commit & push ──────────────────────────────────────────────────────────
WEEK=$(date +"%Y-W%W")
echo "📦  Committing…"
git add ho_index.html
git diff --cached --quiet && { echo "ℹ️  No changes to commit."; exit 0; }
git commit -m "HO Scorecard update ${WEEK}"

echo "🚀  Pushing to GitHub…"
if [ -f "$TOKEN_FILE" ]; then
  TOKEN=$(cat "$TOKEN_FILE")
  git remote set-url origin "https://${TOKEN}@github.com/gauthierjoyeux/scorecard.git"
else
  echo "   No token file found at .github_token"
  read -p "   GitHub token: " TOKEN
  git remote set-url origin "https://${TOKEN}@github.com/gauthierjoyeux/scorecard.git"
fi

git push origin main

echo ""
echo "✅  Done! Live in ~30s at:"
echo "    https://gauthierjoyeux.github.io/scorecard/ho_index.html"
