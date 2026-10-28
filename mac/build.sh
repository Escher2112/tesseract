#!/bin/bash
# build.sh — makes "3D Terminal.app" in mac/build/ from main.swift + the shared core (server.py, index.html, vendor/).
# Also makes a private Python with hidapi (for the Spaceball / PowerMate) in ~/Library/Application Support/3D Terminal/venv.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"; APP="$HERE/build/3D Terminal.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -swift-version 5 -O -o "$APP/Contents/MacOS/3D Terminal" "$HERE/main.swift" -framework AppKit -framework WebKit
cp "$HERE/AppIcon.icns" "$APP/Contents/Resources/"          # drawn by icon/make_icon.swift
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>3D Terminal</string>
  <key>CFBundleDisplayName</key><string>3D Terminal</string>
  <key>CFBundleIdentifier</key><string>io.github.escher2112.3dterminal</string>
  <key>CFBundleExecutable</key><string>3D Terminal</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
</dict></plist>
PLIST
SUP="$HOME/Library/Application Support/3D Terminal"
# The core goes OUTSIDE the app (see main.swift), so updating the page or server never changes the app's signature and macOS keeps
# the permissions you already gave it.
mkdir -p "$SUP/core/vendor"; cp "$ROOT/server.py" "$ROOT/index.html" "$SUP/core/"; cp "$ROOT/vendor/"* "$SUP/core/vendor/"
if [ ! -x "$SUP/venv/bin/python3" ]; then mkdir -p "$SUP"; python3 -m venv "$SUP/venv" && "$SUP/venv/bin/pip" -q install hidapi; fi
codesign --force -s - "$APP" >/dev/null 2>&1 || true
echo "built: $APP"
