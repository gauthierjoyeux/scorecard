#!/bin/bash
# ── Bigblue Scorecard — weekly update ─────────────────────────────────────────
# Usage: ./update.sh
#
# Before running this script, fetch fresh data from Metabase:
#   1. Open https://metabase.internal.bigblue.co in Chrome (stay logged in)
#   2. Open DevTools console (Cmd+Option+J)
#   3. Paste and run the contents of fetch_data.js
#   4. A scorecard_data.json file will download automatically
#   5. Then run this script

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

DATA_FILE="${HOME}/Downloads/scorecard_data.json"
TOKEN_FILE="${SCRIPT_DIR}/.github_token"
GH_REMOTE="https://github.com/gauthierjoyeux/scorecard.git"

# ── Check data file ────────────────────────────────────────────────────────────
if [ ! -f "$DATA_FILE" ]; then
  echo "❌  Data file not found: $DATA_FILE"
  echo "    Fetch it from Metabase first (see instructions above)."
  exit 1
fi

AGE=$(( $(date +%s) - $(stat -f %m "$DATA_FILE") ))
if [ "$AGE" -gt 86400 ]; then
  echo "⚠️  scorecard_data.json is more than 24h old (${AGE}s). Consider re-fetching."
  read -p "   Continue anyway? [y/N] " -n 1 -r; echo
  [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

# ── Generate HTML ──────────────────────────────────────────────────────────────
echo "🔄  Generating index.html..."
python3 "$SCRIPT_DIR/generate_html.py"

# ── Git commit & push ──────────────────────────────────────────────────────────
WEEK=$(date +"%Y-W%W")
echo "📦  Committing..."
git add index.html
git diff --cached --quiet && { echo "ℹ️  No changes to commit."; exit 0; }
git commit -m "Scorecard update ${WEEK}"

echo "🚀  Pushing to GitHub..."
# Use stored token if available, otherwise prompt
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
echo "    https://gauthierjoyeux.github.io/scorecard/"
