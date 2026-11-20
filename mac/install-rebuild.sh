#!/bin/bash
# install-rebuild.sh — put a fresh mac/build/Tesseract.app into /Applications (run from a PLAIN Terminal, not a cube face: it quits the app).
# Ad-hoc builds change signature every time and macOS drops the PowerMate's Input Monitoring (2026-10-28); certificate-signed builds
# (2026-10-29) keep it. See the reset rule below.
set -e
NEW="$(cd "$(dirname "$0")" && pwd)/build/Tesseract.app"
[ -d "$NEW" ] || { echo "no build at $NEW — run mac/build.sh first"; exit 1; }
osascript -e 'tell application "Tesseract" to quit' 2>/dev/null || true
for i in $(seq 1 30); do pgrep -f "/Applications/Tesseract.app/Contents/MacOS/Tesseract" >/dev/null || break; sleep 0.5; done
# 2026-10-29: builds signed with Chris's "Tesseract Local Signing" certificate keep the permission. Reset it only when the OLD or the NEW
# copy is ad-hoc (its signature changes every build, so the stored grant no longer matches). Needs -dvv: plain -dv hides the Authority line.
local_signed() { [ -d "$1" ] && codesign -dvv "$1" 2>&1 | grep -q "Authority=Tesseract Local Signing"; }
KEEP=no; local_signed /Applications/Tesseract.app && local_signed "$NEW" && KEEP=yes
rm -rf /Applications/Tesseract.app && ditto "$NEW" /Applications/Tesseract.app
if [ $KEEP = yes ]; then echo "signed with the local certificate: PowerMate permission kept"
else tccutil reset ListenEvent io.github.escher2112.3dterminal; echo "permission reset (ad-hoc involved): allow Tesseract once when macOS asks"; fi
open -a /Applications/Tesseract.app
echo "Tesseract reinstalled and reopened. Turn the PowerMate once; if macOS asks, allow Tesseract."
