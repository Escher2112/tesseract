#!/usr/bin/env python3
"""block-to-cube.py — FORK glue: drive the Tesseract cube with the Lightpad sim.

OBSERVES the sim's append-only event log (does NOT consume from wait-event, so it
never steals touches from another listener, e.g. a sister session holding hands).
A wipe across the pad rolls the cube; a tap brings the front face forward.
Force-press (enter/exit) is specced but needs a pressure device (the real block).
See BLOCK-CONTROL.md.

Run via run-block-cube.sh, or:
  SIM_HOME=~/.lyra-lightpad-sim CUBE=http://127.0.0.1:PORT KEY=... python3 -I block-to-cube.py
"""
import json, os, time, urllib.request

SIM_HOME = os.path.expanduser(os.environ.get("SIM_HOME", "~/.lyra-lightpad-sim"))
EVENTS = os.path.join(SIM_HOME, "events.jsonl")
CUBE = os.environ.get("CUBE", "http://127.0.0.1:8900")
KEY = os.environ.get("KEY", "")

DIRS = {  # swipe direction -> normalized (dx, dy) roll; dx = side-to-side, dy = top-to-bottom
    "left to right": (1.0, 0.0), "right to left": (-1.0, 0.0),
    "top to bottom": (0.0, -1.0), "bottom to top": (0.0, 1.0),
}

def post(path):
    try: urllib.request.urlopen(urllib.request.Request(CUBE + path, method="POST"), timeout=2).read()
    except Exception as e: print(f"  (cube post failed: {e})", flush=True)

def handle(g):
    kind = g.get("gesture")
    if kind == "stroke":
        dx, dy = DIRS.get(str(g.get("direction", "")), (0.0, 0.0))
        dist = min(1.5, float(g.get("distance", 1.0)))
        if dx or dy:
            post(f"/blockin?k={KEY}&a=spin&dx={dx*dist:.3f}&dy={dy*dist:.3f}")
            print(f"  wipe {g.get('direction')} (block {g.get('block')}) -> spin", flush=True)
    elif kind == "tap":
        post(f"/blockin?k={KEY}&a=select")
        print("  tap -> bring face forward", flush=True)

def main():
    print(f"block-to-cube: tailing {EVENTS} -> {CUBE}  (Ctrl-C to stop)", flush=True)
    while not os.path.exists(EVENTS):
        time.sleep(0.5)
    with open(EVENTS, "r") as f:
        f.seek(0, os.SEEK_END)                     # only new touches from now on
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.05); continue
            try: handle(json.loads(line))
            except Exception: pass

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
