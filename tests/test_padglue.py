"""The Lightpad link's rules (run: python3 -I tests/test_padglue.py). Taps and wipes never enter; a deliberate press/hold does.
The last part runs the real PadLink thread against a fake bridge in a temp folder (never the real pad homes)."""
import importlib.util, json, os, socket, sys, tempfile, threading, time
spec = importlib.util.spec_from_file_location("glue", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "padglue.py"))
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
    ("face view: the same hold backs out (iPad)",    glue.route({"gesture": "rest", "fingers": 1, "duration": 1.05}, {"mode": "face", "face": 2}), "back"),
    ("face view: a firm held press backs out",       glue.route({"gesture": "press", "pressure": 0.9, "duration": 0.5}, {"mode": "face", "face": 2}), "back"),
    ("face view: taps stay with the Lyra there",     glue.route({"gesture": "tap", "fingers": 1, "duration": 0.1}, {"mode": "face", "face": 2}), None),
    ("face view: a resting palm stays with her",     glue.route({"gesture": "rest", "fingers": 4, "duration": 3}, {"mode": "face", "face": 2}), None),
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

# ------------------------------------------------------------ the messages the page gets, and when the link is on at all
more3 = [
    ("left to right rolls the left face in",         glue.cube_message(glue.route({"gesture": "stroke", "direction": "left to right", "distance": 0.8}, {"mode": "cube"})), {"k": "roll", "dy": 1, "dp": 0}),
    ("right to left rolls the right face in",        glue.cube_message(glue.route({"gesture": "stroke", "direction": "right to left", "distance": 0.8}, {"mode": "cube"})), {"k": "roll", "dy": -1, "dp": 0}),
    ("top to bottom rolls the top face in",          glue.cube_message(glue.route({"gesture": "stroke", "direction": "top to bottom", "distance": 0.8}, {"mode": "cube"})), {"k": "roll", "dy": 0, "dp": -1}),
    ("bottom to top rolls the bottom face in",       glue.cube_message(glue.route({"gesture": "stroke", "direction": "bottom to top", "distance": 0.8}, {"mode": "cube"})), {"k": "roll", "dy": 0, "dp": 1}),
    ("his 20:16 vertical wipes all roll now",        all(glue.cube_message(glue.route({"gesture": "stroke", "direction": d, "distance": x}, {"mode": "cube"})) for d, x in
                                                         [("top to bottom", .82), ("top to bottom", .77), ("bottom to top", .72), ("top to bottom", .79), ("bottom to top", .62), ("top to bottom", .79), ("bottom to top", .82)]), True),
    ("jump carries its face",                        glue.cube_message(("jump", 3)), {"k": "jump", "f": 3}),
    ("enter / back / goback pass through",           [glue.cube_message(a) for a in ("enter", "back", "goback")], [{"k": "enter"}, {"k": "back"}, {"k": "goback"}]),
    ("on by default",                                glue.enabled({}), True),
    ("TDT_PAD=0 turns it off",                       glue.enabled({"TDT_PAD": "0"}), False),
    ("a TDT_HOME test copy leaves his pad alone",    glue.enabled({"TDT_HOME": "/tmp/x"}), False),
    ("... unless asked with TDT_PAD=1",              glue.enabled({"TDT_HOME": "/tmp/x", "TDT_PAD": "1"}), True),
]

# ------------------------------------------------------------ dragging the cube with a finger
def run(readings):
    tr = glue.DragTracker(); out = []
    for r in readings: out += tr.feed(r)
    return out
R = lambda kind, x, y, t, i=0, b=0: {"kind": kind, "x": x, "y": y, "t": t, "i": i, "block": b}
still = run([R("start", .5, .5, 0), R("move", .51, .505, .3), R("move", .505, .51, .9), R("end", .505, .51, 1.1)])
drag = run([R("start", .2, .5, 0), R("move", .3, .5, .02), R("move", .4, .5, .04), R("end", .45, .5, .06)])
stopped = run([R("start", .2, .5, 0), R("move", .4, .5, .05), R("end", .4, .5, .5)])
two = run([R("start", .2, .5, 0), R("move", .4, .5, .05), R("start", .7, .5, .06, i=1), R("move", .5, .5, .07), R("end", .5, .5, .1), R("end", .7, .5, .1, i=1)])
more3 += [
    ("a still finger (the hold that goes in) never moves the cube", still, []),
    ("a drag moves it with the finger, live",        [m["dx"] for m in drag if "dx" in m], [0.1, 0.1]),
    ("letting go mid-swipe flings it",               drag[-1]["end"] and drag[-1]["vx"] > 0, True),
    ("stopping before letting go doesn't fling",     stopped[-1], {"k": "pdrag", "end": True, "vx": 0.0, "vy": 0.0}),
    ("a second finger ends the drag and stops it",   [m for m in two if m.get("end")], [{"k": "pdrag", "end": True, "vx": 0.0, "vy": 0.0}]),
    ("a dragged wipe doesn't ALSO roll a quarter",   glue.route({"gesture": "stroke", "direction": "left to right", "distance": 1}, {"mode": "cube"}, dragging=True), None),
    ("a hold still dives in while dragging is on",   glue.route({"gesture": "rest", "fingers": 1, "duration": 1.05}, {"mode": "cube"}, dragging=True), "enter"),
]

# ------------------------------------------------------------ the real thread against a fake bridge
def fake_bridge(home):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); srv.bind(os.path.join(home, "sock")); srv.listen(4)
    def serve():
        while True:
            try: c, _ = srv.accept()
            except OSError: return
            try: c.recv(1024); c.sendall(b'{"ok": true, "mode": "idle"}\n')
            finally: c.close()
    threading.Thread(target=serve, daemon=True).start(); return srv

def wait_for(test, secs=6.0):
    end = time.time() + secs
    while time.time() < end:
        if test(): return True
        time.sleep(0.05)
    return False

root = tempfile.mkdtemp(prefix="padglue-test-", dir="/tmp")    # short path: unix sockets have a ~100-char limit
real, sim = os.path.join(root, "lp"), os.path.join(root, "lp-sim")
os.makedirs(real); os.makedirs(sim)
open(os.path.join(sim, "events.jsonl"), "w").write(json.dumps({"gesture": "stroke", "direction": "left to right", "distance": 1}) + "\n")
sent = []
glue.DETECT_S = 0.2
link = glue.PadLink(sent.append, lambda: "http://127.0.0.1:1", homes=[real, sim]).start()
time.sleep(0.6)
more3.append(("no bridge: nothing at all is sent", list(sent), []))
srv = fake_bridge(sim)
more3.append(("a live bridge turns the pad on",  wait_for(lambda: {"k": "pad", "on": True, "dev": "sim"} in sent), True))
more3.append(("old touches from before are skipped", [m for m in sent if m.get("k") == "roll"], []))
link.set_view({"mode": "cube", "face": 0, "waiting": [{"f": 2, "since": 1, "colour": "#00c7be"}]})
with open(os.path.join(sim, "events.jsonl"), "a") as f: f.write(json.dumps({"gesture": "stroke", "direction": "right to left", "distance": 1}) + "\n")
more3.append(("a new wipe reaches the page",      wait_for(lambda: {"k": "roll", "dy": -1, "dp": 0} in sent), True))
sig = os.path.join(sim, "tesseract.json")
more3.append(("the waiting face lights a corner", wait_for(lambda: os.path.exists(sig) and json.load(open(sig))["calls"][:1] == [
    {"corner": "top_right", "colour": "#00c7be", "face": 2, "reason": ""}]), True))
more3.append(("hello says the pad is here",       link.hello(), {"k": "pad", "on": True, "dev": "sim", "quiet": True}))
srv.close(); os.remove(os.path.join(sim, "sock"))
more3.append(("the bridge goes: the pad turns off", wait_for(lambda: sent[-1] == {"k": "pad", "on": False, "dev": None}), True))

bad3 = [name for name, got, want in more3 if got != want]
for name, got, want in more3:
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else f"got {got} want {want}")
print(f"{len(cases) + len(more) + len(more3) - len(bad) - len(bad2) - len(bad3)}/{len(cases) + len(more) + len(more3)} padglue rules")
sys.exit(1 if (bad or bad2 or bad3) else 0)
