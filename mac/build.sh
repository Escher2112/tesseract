#!/bin/bash
# build.sh — makes "Tesseract.app" (named "3D Terminal" until 2026-10-28) in mac/build/ from main.swift + the shared core (server.py, index.html, vendor/).
# Also makes a private Python with hidapi (for the Spaceball / PowerMate) in ~/Library/Application Support/3D Terminal/venv.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"; APP="$HERE/build/Tesseract.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -swift-version 5 -O -o "$APP/Contents/MacOS/Tesseract" "$HERE/main.swift" -framework AppKit -framework WebKit
cp "$HERE/AppIcon.icns" "$APP/Contents/Resources/"          # drawn by icon/make_icon.swift
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Tesseract</string>
  <key>CFBundleDisplayName</key><string>Tesseract</string>
  <key>CFBundleIdentifier</key><string>io.github.escher2112.3dterminal</string>
  <key>CFBundleExecutable</key><string>Tesseract</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>A browser face (ChatGPT, Grok…) wants your microphone for voice.</string>
  <key>NSCameraUsageDescription</key><string>A browser face wants your camera.</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
</dict></plist>
PLIST
# the bundle id and this folder keep the OLD name on purpose: renaming them would orphan prefs, saved sessions and the venv
SUP="$HOME/Library/Application Support/3D Terminal"
# The core goes OUTSIDE the app (see main.swift), so updating the page or server never changes the app's signature and macOS keeps
# the permissions you already gave it.
mkdir -p "$SUP/core"; cp "$ROOT/server.py" "$ROOT/index.html" "$ROOT/gl.js" "$SUP/core/"; rm -rf "$SUP/core/vendor"; cp -R "$ROOT/vendor" "$SUP/core/vendor"
if [ ! -x "$SUP/venv/bin/python3" ]; then mkdir -p "$SUP"; python3 -m venv "$SUP/venv" && "$SUP/venv/bin/pip" -q install hidapi; fi
# 2026-10-29: sign with Chris's home-made "Tesseract Local Signing" certificate when it exists, so macOS keeps the PowerMate's Input
# Monitoring across rebuilds (an ad-hoc signature is new every build, and macOS forgets the permission each time). Fallback: ad-hoc.
SIGN_ID="Tesseract Local Signing"
if security find-identity -p codesigning 2>/dev/null | grep -q "$SIGN_ID"; then codesign --force -s "$SIGN_ID" "$APP" && echo "signed with: $SIGN_ID"
else codesign --force -s - "$APP" >/dev/null 2>&1 || true; echo "signed ad-hoc (no '$SIGN_ID' certificate yet: the PowerMate permission resets on each rebuild)"; fi
echo "built: $APP"
