"""FORK glue rules (run: python3 -I test_block_glue.py). Taps and wipes never enter; a deliberate press/hold does."""
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("glue", os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-to-cube.py"))
glue = importlib.util.module_from_spec(spec); spec.loader.exec_module(glue)
d = glue.decide
cases = [
    ("tap never enters",                d({"gesture": "tap"}, False),                                        (None, False)),
    ("wipe spins, stays outside",       d({"gesture": "stroke", "direction": "left to right", "distance": 1}, False), (("spin", 1.0, 0.0), False)),
    ("vertical wipe only spins",        d({"gesture": "stroke", "direction": "top to bottom", "distance": 1}, False), (("spin", 0.0, -1.0), False)),
    ("light press never enters",        d({"gesture": "press", "pressure": 0.3, "duration": 1.0}, False),     (None, False)),
    ("quick firm press never enters",   d({"gesture": "press", "pressure": 0.9, "duration": 0.1}, False),     (None, False)),
    ("firm held press enters",          d({"gesture": "press", "pressure": 0.9, "duration": 0.5}, False),     ("enter", True)),
    ("the same again comes back out",   d({"gesture": "press", "pressure": 0.9, "duration": 0.5}, True),      ("back", False)),
    ("iPad: one still finger enters",   d({"gesture": "rest", "fingers": 1, "duration": 1.1}, False),         ("enter", True)),
    ("iPad: a resting palm doesn't",    d({"gesture": "rest", "fingers": 4, "duration": 3.0}, False),         (None, False)),
]
bad = [name for name, got, want in cases if got != want]
for name, got, want in cases:
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else f"got {got} want {want}")
# (exit deferred to the end)

# ------------------------------------------------------------ 2026-11-03: corners, the visit, mode routing
C = glue.calls_for
cube = {"mode": "cube", "face": 0, "waiting": [{"f": 4, "since": 20, "colour": "#0d47a1"}, {"f": 2, "since": 10, "colour": "#00c7be"}]}
calls, corners = C(cube, {})
more = [
    ("oldest waiter gets the first corner",          (calls[0]["face"], calls[0]["corner"]), (2, "top_right")),
    ("its colour is its Tesseract group colour",     calls[0]["colour"], "#00c7be"),
    ("corners stay put across polls",                C(cube, corners)[1], corners),
    ("the face you're IN never calls",               [c["face"] for c in C(dict(cube, mode="face", face=2), {})[0]], [4]),
    ("ungrouped faces get a lane colour, never white", C({"mode": "cube", "waiting": [{"f": 1, "since": 1, "colour": None}, {"f": 3, "since": 2, "colour": "#f7fbff"}]}, {})[0][1]["colour"] != "#f7fbff", True),
    ("at most four corners",                         len(C({"mode": "cube", "waiting": [{"f": i, "since": i} for i in range(7)]}, {})[0]), 4),
    ("a stopped waiter frees its corner",            C({"mode": "cube", "waiting": [{"f": 4, "since": 20}]}, corners)[1], {4: "top_left"}),
    ("cube view: a wipe steps",                      glue.route({"gesture": "stroke", "direction": "left to right", "distance": 1}, {"mode": "cube"}), ("spin", 1.0, 0.0)),
    ("face view: touches are left to the Lyra there", glue.route({"gesture": "stroke", "direction": "left to right", "distance": 1}, {"mode": "face", "face": 2}), None),
    ("face view: a hold doesn't navigate",           glue.route({"gesture": "rest", "fingers": 1, "duration": 2}, {"mode": "face", "face": 2}), None),
]
action, visit = glue.on_corner_tap({"gesture": "corner_tap", "kind": "call", "corner": "top_right", "face": 2}, {"mode": "face", "face": 0}, None, 100.0)
more += [
    ("a calling corner jumps to its face",           action, ("jump", 2)),
    ("the visit remembers home and the way back",    (visit["home_face"], visit["return"]), (0, "bottom_left")),
    ("no calls during a visit",                      glue.signal_state(cube, {}, visit, 101.0)[0]["calls"], []),
    ("still visiting while the jump lands",          glue.visit_still_on(visit, {"mode": "cube"}, 101.0) is visit, True),
    ("still visiting while he's in that face",       glue.visit_still_on(visit, {"mode": "face", "face": 2}, 110.0) is visit, True),
    ("left that face some other way: visit over",    glue.visit_still_on(visit, {"mode": "face", "face": 5}, 110.0), None),
    ("the white corner goes back",                   glue.on_corner_tap({"gesture": "corner_tap", "kind": "return", "corner": "bottom_left", "face": 0}, {}, visit, 120.0), (("goback", None), None)),
]
bad2 = [name for name, got, want in more if got != want]
for name, got, want in more:
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else f"got {got} want {want}")
sys.exit(1 if (bad or bad2) else 0)
