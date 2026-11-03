#!/bin/sh
# run-block-cube.sh — FORK: start the Tesseract cube with Lightpad-block control (swipe-to-spin).
# Needs the Lightpad sim already running (bin/lightpad run --sim ...). See BLOCK-CONTROL.md.
set -eu
PORT="${PORT:-8900}"
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "starting forked cube on :$PORT ..."
python3 -I "$HERE/server.py" --port "$PORT" &
CUBE_PID=$!
sleep 2
# the server prints a URL with a per-run key; grab the key from its config/output isn't trivial here,
# so for the test, open the printed URL in your browser, then paste its k= value:
echo
echo "1) open the URL the server printed above in your browser (the cube)"
echo "2) copy the k=KEY from that URL and run, in another terminal:"
echo "   LIGHTPAD_DIR=$HOME/Master-Projects/roli-lightpad CUBE=http://127.0.0.1:$PORT KEY=<paste> python3 -I $HERE/block-to-cube.py"
echo "3) wipe across your iPad -> the cube spins."
echo
wait $CUBE_PID
