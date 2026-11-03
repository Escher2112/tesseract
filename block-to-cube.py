#!/usr/bin/env python3
"""block-to-cube.py — FORK glue: the Lightpad and the Tesseract cube, both directions.

PAD → CUBE: OBSERVES the pad's append-only event log (never consumes wait-event, so it never steals
touches from a session holding his hand). What a touch means depends on what the cube shows (Chris,
2026-11-03: the pad's mode follows Tesseract; he never flips a switch):
  * CUBE view: a wipe steps face to face; a DELIBERATE press held a moment dives into the front
    face (firm press on the real block; one finger held still on the iPad sim, which has no pressure).
    Taps never enter.
  * FACE view (full screen): touches are the touch language with the Lyra in that face; the glue
    leaves them alone.
  * Either view: a `corner_tap` from the pad: a calling corner → jump into that face (the cube's own
    jumpTo, which remembers where he was); the white return corner → the cube's own back.

CUBE → PAD: polls the cube's /blockstate (the page reports its view + waiting faces, colours from his
Tesseract palette) and writes <pad home>/tesseract.json for the pad (bridge/padsignal.py):
  * every waiting face (except the one he's in) gets a stable corner (at most four, longest-waiting
    first) in its group colour; ungrouped faces get a colour from his lane; never white (white = return)
  * the VISIT tether (his design): after a corner jump, the pad shows the white landing strip home and
    no other calls; it ends when he taps the white corner, or leaves that face some other way.
  * the visited face's Lyra owns the pad (`bin/lightpad claim --take`), and the home face's again on
    the way back, when the presence hook has recorded which session is on which face (faces.json).

Run:  SIM_HOME=~/.lyra-lightpad-sim CUBE=http://127.0.0.1:PORT KEY=... python3 -I block-to-cube.py
See BLOCK-CONTROL.md. Rules checked by: python3 -I test_block_glue.py
"""
import json, os, subprocess, threading, time, urllib.request

PAD_HOME = os.path.expanduser(os.environ.get("SIM_HOME", "~/.lyra-lightpad-sim"))
EVENTS = os.path.join(PAD_HOME, "events.jsonl")
SIGNAL = os.path.join(PAD_HOME, "tesseract.json")      # read by bridge/padsignal.py
FACES_MAP = os.path.join(PAD_HOME, "faces.json")       # written by the presence hook: {cube url: {face: session}}
CUBE = os.environ.get("CUBE", "http://127.0.0.1:8900")
KEY = os.environ.get("KEY", "")
LIGHTPAD_DIR = os.path.expanduser(os.environ.get("LIGHTPAD_DIR", "~/Master-Projects/roli-lightpad"))
POLL_S = 0.5
JUMP_GRACE_S = 3.0          # the jump's zoom takes time; a visit isn't judged "left" until this passes

DIRS = {  # swipe direction -> normalized (dx, dy) roll; dx = side-to-side, dy = top-to-bottom
    "left to right": (1.0, 0.0), "right to left": (-1.0, 0.0),
    "top to bottom": (0.0, -1.0), "bottom to top": (0.0, 1.0),
}
CORNER_ORDER = ("top_right", "top_left", "bottom_right", "bottom_left")
OPPOSITE = {"top_left": "bottom_right", "bottom_right": "top_left", "top_right": "bottom_left", "bottom_left": "top_right"}
WHITE = "#f7fbff"
LANE = ("#ff3dbb", "#6ec8ff", "#ffe14a", "#00e5ff")   # his colour-blind-safe lane, for faces with no Tesseract colour

# Entering a face is DELIBERATE (Chris's design: "force press = go into the face"; Riven 2026-11-03:
# "a threshold plus a short dwell time"). The real block: a "press" >= ENTER_PRESSURE held >= ENTER_DWELL_S;
# the iPad sim: one finger held still (the classifier's "rest", ~1 s).
ENTER_PRESSURE = 0.55   # of the calibrated 0..1 range; tune on arrival day against his real hand
ENTER_DWELL_S = 0.35


def decide(g, inside):
    """CUBE-view gesture rules: (action, inside_after). action: ("spin", dx, dy) | "enter" | "back" | None."""
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


def route(g, view):
    """What a pad gesture does given the cube's view. Corner taps are handled by on_corner_tap."""
    if (view or {}).get("mode") == "face":
        return None                              # inside a face: the touch language belongs to that face's Lyra
    action, _ = decide(g, False)
    return action                                # cube view: wipes step, a deliberate hold dives in


def calls_for(view, corners):
    """(calls, corners_after): waiting faces → pad corners, stable across polls."""
    view = view or {}
    here = view.get("face") if view.get("mode") == "face" else None
    waiting = [w for w in (view.get("waiting") or []) if isinstance(w, dict) and w.get("f") != here]
    waiting.sort(key=lambda w: w.get("since") or 0)
    waiting = waiting[:len(CORNER_ORDER)]                      # the four that have waited longest
    keep = {w["f"] for w in waiting}
    corners = {f: c for f, c in corners.items() if f in keep}  # a face that stopped waiting frees its corner
    used_colours, calls = set(), []
    for w in waiting:
        if w["f"] not in corners:
            free = [c for c in CORNER_ORDER if c not in corners.values()]
            corners[w["f"]] = free[0]
    for w in waiting:
        colour = str(w.get("colour") or "").lower()
        if not colour.startswith("#") or len(colour) != 7 or colour == WHITE:
            colour = next((c for c in LANE if c not in used_colours), LANE[0])
        used_colours.add(colour)
        calls.append({"corner": corners[w["f"]], "colour": colour, "face": w["f"], "reason": str(w.get("r") or "")})
    return calls, corners


def on_corner_tap(g, view, visit, now):
    """(cube action, visit_after) for a corner_tap from the pad."""
    view = view or {}
    if g.get("kind") == "return":
        return ("goback", None), None
    face = g.get("face")
    if not isinstance(face, int):
        return None, visit
    home = view.get("face")
    return ("jump", face), {"entry": g.get("corner"), "return": OPPOSITE.get(g.get("corner"), "bottom_left"),
                            "face": face, "home_face": home, "home_mode": view.get("mode"), "since": now}


def visit_still_on(visit, view, now):
    """A visit ends when he leaves the visited face some other way (after the jump has had time to land)."""
    if visit is None:
        return None
    if now - visit["since"] < JUMP_GRACE_S:
        return visit
    view = view or {}
    if view.get("mode") == "face" and view.get("face") == visit["face"]:
        return visit
    return None


def signal_state(view, corners, visit, now):
    if visit is not None:
        return {"v": 1, "updated_at": now, "calls": [],
                "visit": {k: visit[k] for k in ("entry", "return", "face", "home_face")}}, corners
    calls, corners = calls_for(view, corners)
    return {"v": 1, "updated_at": now, "calls": calls, "visit": None}, corners


# ---------------------------------------------------------------- I/O (not unit-tested; thin on purpose)

def post(path):
    try: urllib.request.urlopen(urllib.request.Request(CUBE + path, method="POST"), timeout=2).read()
    except Exception as e: print(f"  (cube post failed: {e})", flush=True)


def get_view():
    try:
        with urllib.request.urlopen(f"{CUBE}/blockstate?k={KEY}", timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return None


def write_signal(state):
    tmp = SIGNAL + ".tmp"
    with open(tmp, "w") as f: json.dump(state, f)
    os.replace(tmp, SIGNAL)


def session_on_face(face):
    try:
        mapping = json.load(open(FACES_MAP)).get(CUBE.rstrip("/"), {})
        return mapping.get(str(face))
    except Exception:
        return None


def hand_pad_to(face):
    """The face he's attending to owns the pad (when we know which session is on it)."""
    session = session_on_face(face) if isinstance(face, int) else None
    if not session:
        return
    subprocess.run([os.path.join(LIGHTPAD_DIR, "bin", "lightpad"), "claim", "--session", session, "--take"],
                   capture_output=True, timeout=20)


class Glue:
    def __init__(self):
        self.view, self.corners, self.visit, self.lock = None, {}, None, threading.Lock()

    def poll_forever(self):
        while True:
            view = get_view()
            now = time.time()
            with self.lock:
                if view is not None:
                    self.view = view
                    self.visit = visit_still_on(self.visit, view, now)
                    state, self.corners = signal_state(view, self.corners, self.visit, now)
                    try: write_signal(state)
                    except OSError: pass
            time.sleep(POLL_S)

    def handle(self, g):
        with self.lock:
            view, visit = self.view, self.visit
        if g.get("gesture") == "corner_tap":
            action, visit = on_corner_tap(g, view, visit, time.time())
            with self.lock: self.visit = visit
            if action and action[0] == "jump":
                post(f"/blockin?k={KEY}&a=jump&f={action[1]}"); print(f"  corner tap -> face {action[1] + 1}", flush=True)
                hand_pad_to(action[1])
            elif action and action[0] == "goback":
                post(f"/blockin?k={KEY}&a=goback"); print("  white corner -> back home", flush=True)
                hand_pad_to((g.get("face")))
            return
        action = route(g, view)
        if not action:
            return
        if action[0] == "spin":
            _, dx, dy = action
            post(f"/blockin?k={KEY}&a=spin&dx={dx:.3f}&dy={dy:.3f}")
            print(f"  wipe {g.get('direction')} -> step", flush=True)
        else:
            post(f"/blockin?k={KEY}&a={action}")
            print(f"  deliberate {g.get('gesture')} -> {action}", flush=True)


def main():
    glue = Glue()
    threading.Thread(target=glue.poll_forever, daemon=True).start()
    print(f"block-to-cube: {EVENTS} <-> {CUBE}  (Ctrl-C to stop)", flush=True)
    while not os.path.exists(EVENTS):
        time.sleep(0.5)
    with open(EVENTS, "r") as f:
        f.seek(0, os.SEEK_END)                     # only new touches from now on
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.05); continue
            try: glue.handle(json.loads(line))
            except Exception as e: print(f"  (glue: {e})", flush=True)


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
