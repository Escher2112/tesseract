#!/bin/bash
# run.sh — Session Cube on Linux: starts the shared server and opens the cube in your browser. Ctrl+C stops it (and every shell on it).
# For the Spaceball / PowerMate: pip install hidapi, and give your user read access to /dev/hidraw* (a udev rule). Untested on Linux yet.
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
python3 -I "$ROOT/server.py" --port 8782 | while read -r line; do
  echo "$line"
  url=$(echo "$line" | grep -o 'http://127.0.0.1:[0-9]*/?k=[A-Za-z0-9_-]*') && [ -n "$url" ] && (xdg-open "$url" >/dev/null 2>&1 &)
done
