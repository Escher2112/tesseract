#!/bin/bash
# install-rebuild.sh — put a fresh mac/build/Tesseract.app into /Applications (run from a PLAIN Terminal, not a cube face: it quits the app).
# Every rebuild changes the app's ad-hoc signature, and macOS then drops the PowerMate's Input Monitoring (2026-10-28 22:05), so this
# also resets that permission; the knob works again after the reopen.
set -e
NEW="$(cd "$(dirname "$0")" && pwd)/build/Tesseract.app"
[ -d "$NEW" ] || { echo "no build at $NEW — run mac/build.sh first"; exit 1; }
osascript -e 'tell application "Tesseract" to quit' 2>/dev/null || true
for i in $(seq 1 30); do pgrep -f "/Applications/Tesseract.app/Contents/MacOS/Tesseract" >/dev/null || break; sleep 0.5; done
rm -rf /Applications/Tesseract.app && ditto "$NEW" /Applications/Tesseract.app
tccutil reset ListenEvent io.github.escher2112.3dterminal
open -a /Applications/Tesseract.app
echo "Tesseract reinstalled and reopened. Turn the PowerMate once; if macOS asks, allow Tesseract."
