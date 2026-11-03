#!/usr/bin/env python3
"""block-to-cube.py — FORK glue: drive the Tesseract cube with the Lightpad sim.

Reads the Lightpad sim's gestures and POSTs them to the forked cube's /blockin:
a wipe across the pad rolls the cube, a tap brings the front face forward.
Force-press (enter/exit) is specced but needs a pressure device (the real block);
the iPad reports no force, so it is dormant here. See BLOCK-CONTROL.md.

Run via run-block-cube.sh, or:
  LIGHTPAD_DIR=~/Master-Projects/roli-lightpad CUBE=http://127.0.0.1:PORT KEY=... python3 -I block-to-cube.py
"""
import json, os, subprocess, sys, urllib.request

LIGHTPAD_DIR = os.path.expanduser(os.environ.get("LIGHTPAD_DIR", "~/Master-Projects/roli-lightpad"))
CUBE = os.environ.get("CUBE", "http://127.0.0.1:8900")
KEY = os.environ.get("KEY", "")
LIGHTPAD = os.path.join(LIGHTPAD_DIR, "bin", "lightpad")

# a swipe's direction -> a normalized (dx, dy) roll; dx rolls side-to-side, dy top-to-bottom
DIRS = {
    "left to right": (1.0, 0.0), "right to left": (-1.0, 0.0),
    "top to bottom": (0.0, -1.0), "bottom to top": (0.0, 1.0),
}

def post(path):
    try:
        urllib.request.urlopen(urllib.request.Request(CUBE + path, method="POST"), timeout=2).read()
    except Exception as e:
        print(f"  (cube post failed: {e})", flush=True)

def handle(g):
    kind = g.get("gesture")
    if kind == "stroke":
        dx, dy = DIRS.get(str(g.get("direction", "")), (0.0, 0.0))
        dist = min(1.5, float(g.get("distance", 1.0)))          # longer wipe = bigger roll
        if dx or dy:
            post(f"/blockin?k={KEY}&a=spin&dx={dx*dist:.3f}&dy={dy*dist:.3f}")
            print(f"  wipe {g.get('direction')} -> spin", flush=True)
    elif kind == "tap":
        post(f"/blockin?k={KEY}&a=select")
        print("  tap -> bring face forward", flush=True)

def main():
    print(f"block-to-cube: sim gestures -> {CUBE}  (Ctrl-C to stop)", flush=True)
    while True:
        try:
            out = subprocess.run([LIGHTPAD, "wait-event", "--sim", "--timeout", "3000"],
                                 cwd=LIGHTPAD_DIR, capture_output=True, text=True, timeout=10).stdout
        except Exception as e:
            print(f"  (wait-event failed: {e}); is the sim running?", flush=True); continue
        try:
            data = json.loads(out)
        except Exception:
            continue
        for u in data.get("utterances", []):
            for g in u.get("gestures", []):
                handle(g)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: sys.exit(0)
