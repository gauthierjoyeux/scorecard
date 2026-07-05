#!/bin/bash
# ── Install weekly launchd timer for scorecard auto-update ────────────────────
# Runs update_all.sh every Monday at 09:00.
# Re-run this script any time you move the folder.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_LABEL="co.bigblue.scorecard"
PLIST_PATH="${HOME}/Library/LaunchAgents/${PLIST_LABEL}.plist"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SCRIPT_DIR}/update_all.sh</string>
  </array>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key> <integer>1</integer>
    <key>Hour</key>    <integer>9</integer>
    <key>Minute</key>  <integer>0</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>${SCRIPT_DIR}/update.log</string>
  <key>StandardErrorPath</key>
  <string>${SCRIPT_DIR}/update.log</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF

# Load (or reload) the agent
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load  "$PLIST_PATH"

echo "✅  Weekly timer installed: every Monday at 09:00"
echo "    Plist: $PLIST_PATH"
echo "    Log:   ${SCRIPT_DIR}/update.log"
echo ""
echo "Manual trigger (to test right now):"
echo "  launchctl start ${PLIST_LABEL}"
