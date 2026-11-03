#!/usr/bin/env python3
"""block-to-cube.py — FORK glue: drive the Tesseract cube with the Lightpad sim.

OBSERVES the sim's append-only event log (does NOT consume from wait-event, so it
never steals touches from another listener, e.g. a sister session holding hands).
A wipe across the pad steps the cube face to face. A DELIBERATE press held a moment goes into the
face and the same again comes back out (firm press on the real block; a still one-finger hold on
the iPad sim, which has no pressure). Taps never enter.
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

# Entering a face is DELIBERATE (Chris's design: "force press = go into the face"; Riven 2026-11-03:
# "a pressure-to-enter gesture [should] require a threshold plus a short dwell time, otherwise a
# particularly enthusiastic swipe could accidentally launch you into a terminal face").
#   real block: a "press" at or above ENTER_PRESSURE, held at least ENTER_DWELL_S
#   iPad sim (no pressure): a "rest", one finger held still (the classifier's rest boundary, ~1 s)
# The same deliberate press/hold comes back OUT. Taps and wipes never enter (they used to: a stray
# tap at the end of a wipe dove into a face, 2026-11-02 "it's wanting to go into the face too easily").
ENTER_PRESSURE = 0.55   # of the calibrated 0..1 range; tune on arrival day against his real hand
ENTER_DWELL_S = 0.35

def decide(g, inside):
    """(action, inside_after) for one classified gesture. action: spin dx dy | enter | back | None."""
    kind = g.get("gesture")
    if kind == "stroke":
        dx, dy = DIRS.get(str(g.get("direction", "")), (0.0, 0.0))
        dist = min(1.5, float(g.get("distance", 1.0)))
        return (("spin", dx * dist, dy * dist) if (dx or dy) else None), inside
    deliberate = (
        (kind == "press" and float(g.get("pressure", 0.0)) >= ENTER_PRESSURE
         and float(g.get("duration", 0.0)) >= ENTER_DWELL_S)
        or (kind == "rest" and int(g.get("fingers", 1) or 1) == 1
            and float(g.get("duration", 0.0)) >= ENTER_DWELL_S)
    )
    if deliberate:
        return ("back", False) if inside else ("enter", True)
    return None, inside                          # taps, light presses, palms: never dive in

_inside = False

def handle(g):
    global _inside
    action, _inside = decide(g, _inside)
    if not action:
        return
    if action[0] == "spin":
        _, dx, dy = action
        post(f"/blockin?k={KEY}&a=spin&dx={dx:.3f}&dy={dy:.3f}")
        print(f"  wipe {g.get('direction')} (block {g.get('block')}) -> spin", flush=True)
    else:
        post(f"/blockin?k={KEY}&a={action}")
        print(f"  deliberate {g.get('gesture')} -> {action}", flush=True)

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
