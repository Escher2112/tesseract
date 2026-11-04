"""padglue.py — the ROLI Lightpad Block as a Tesseract input (2026-11-03). Optional and self-contained.

It SLEEPS until a Lightpad bridge answers (the real block first, else the iPad sim; homes ~/.lyra-lightpad and
~/.lyra-lightpad-sim, checked every couple of seconds). No pad = nothing happens: the Spaceball, PowerMate, keyboard
and mouse paths in server.py never pass through here. The server loads this file inside a try, so even a broken copy
can't stop the cube.

While a pad is live, both directions:
  PAD -> CUBE: it tails the bridge's append-only events.jsonl (read only, from the end; it never takes a touch from a
    session that's listening). What a touch does follows what the cube shows:
      * cube view: a wipe steps face to face; a DELIBERATE press held a moment dives into the front face (a firm press
        on the real block; one still finger on the iPad sim, which has no pressure). Taps never dive in.
      * face view (full screen): the touch belongs to the session in that face; this module leaves it alone.
      * either view: a corner_tap on a calling corner jumps into that face (the page's own jumpTo, so back works);
        the white return corner goes back (the page's own goBack).
  CUBE -> PAD: the page reports its view and the waiting faces (POST /blockview, only while the pad is on); this
    writes <pad home>/tesseract.json, which the bridge draws as calling corners (a face's group colour) or, during a
    visit, the white landing strip home. The visited face's session owns the pad while he's there.

Turn it off: TDT_PAD=0. A test copy (TDT_HOME set) leaves it off unless TDT_PAD=1, so two cubes never fight over a pad.
Rules checked by: python3 -I test_block_glue.py"""
import json, os, socket, subprocess, threading, time

DETECT_S = 2.0              # how often to look for a pad bridge
SIGNAL_S = 0.5              # how often the pad's calling-corner file is rewritten (the bridge treats >10 s old as stale)
JUMP_GRACE_S = 3.0          # the jump's zoom takes time; a visit isn't judged "left" until this passes
LOG_MAX = 200_000           # the log is trimmed past this (nothing reads stdout once the app has the URL)

DIRS = {  # swipe direction -> normalized (dx, dy) roll; dx = side-to-side, dy = top-to-bottom
    "left to right": (1.0, 0.0), "right to left": (-1.0, 0.0),
    "top to bottom": (0.0, -1.0), "bottom to top": (0.0, 1.0),
}
CORNER_ORDER = ("top_right", "top_left", "bottom_right", "bottom_left")
OPPOSITE = {"top_left": "bottom_right", "bottom_right": "top_left", "top_right": "bottom_left", "bottom_left": "top_right"}
WHITE = "#f7fbff"
LANE = ("#ff3dbb", "#6ec8ff", "#ffe14a", "#00e5ff")   # colour-blind-safe fallbacks for faces with no Tesseract colour

# Entering a face is DELIBERATE: a "press" >= ENTER_PRESSURE held >= ENTER_DWELL_S on the real block;
# one finger held still (the bridge's "rest", ~1 s) on the iPad sim.
ENTER_PRESSURE = 0.55   # of the calibrated 0..1 range; tune against a real hand on the real block
ENTER_DWELL_S = 0.35


# ---------------------------------------------------------------- the rules (pure; test_block_glue.py)

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


def route(g, view, dragging=False):
    """What a pad gesture does given the cube's view. Corner taps are handled by on_corner_tap.
    dragging: the live finger feed is on, so a finished wipe has already moved the cube (no extra quarter-roll)."""
    if (view or {}).get("mode") == "face":
        # inside a face the touch belongs to that face's session, EXCEPT the same deliberate hold that took him in: it brings him back
        # out (his design, 2026-11-02: "force press = into the face… force press again = back out"; switched on 2026-11-03 20:50)
        action, _ = decide(g, True)
        return "back" if action == "back" else None
    action, _ = decide(g, False)
    if dragging and isinstance(action, tuple) and action[0] == "spin":
        return None                              # the drag already rolled it, live
    return action                                # cube view: wipes roll, a deliberate hold dives in


def calls_for(view, corners):
    """(calls, corners_after): waiting faces -> pad corners, stable across polls."""
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


def cube_message(action):
    """A rule's action -> the message the page already understands (sent on /stream)."""
    if not action:
        return None
    if action == "enter" or action == "back":
        return {"k": action}
    if action == "goback":
        return {"k": "goback"}
    if isinstance(action, tuple) and action[0] == "jump":
        return {"k": "jump", "f": action[1]}
    if isinstance(action, tuple) and action[0] == "spin":
        # 20:17 Chris: "it went side to side. It would not go up and down… it barely registers." Vertical wipes were dropped (7 of his
        # 10 wipes did nothing) and side wipes used the knob's face-number dial. Now a wipe ROLLS the cube like the Spaceball, all four
        # ways, as if dragging its surface: the face on the side you wipe FROM rolls in (left to right brings the left face, top to
        # bottom brings the top face). The page's turn(dy, dp) does the roll; it never goes in or out of a face.
        dx, dy = action[1], action[2]
        if abs(dx) >= abs(dy) and dx:
            return {"k": "roll", "dy": 1 if dx > 0 else -1, "dp": 0}
        if dy:
            return {"k": "roll", "dy": 0, "dp": 1 if dy > 0 else -1}
    return None


# ---------------------------------------------------------------- dragging the cube with a finger (Chris 2026-11-03 20:58)
# "when I drag my finger, I'm actually pulling the cube around… like the space ball… like I'm touching it and rolling it with my
# finger." The bridge's touch_stream gives every raw reading live; one finger that has moved past DRAG_DEAD drags the solid through
# the page's own mouse-drag code (rotateBy), and letting go hands its speed to the page's release (coast, then click onto the nearest
# face). A finger held still (the hold that goes into a face) never moves the cube; a second finger ends the drag.
DRAG_DEAD = 0.04            # pad widths a finger must travel before it drags (a still finger and a tap never move the cube)
DRAG_STOPPED_S = 0.08       # lifted after holding still this long: no fling (same rule as the mouse)


class DragTracker:
    """Raw touch readings -> page messages {"k":"pdrag","dx","dy"} (pad widths) and {"k":"pdrag","end":True,"vx","vy"} (per ms)."""

    def __init__(self):
        self.fingers = {}       # (block, i) -> dict(x0, y0, lx, ly, lt, moved, vx, vy)
        self.multi = False      # more than one finger since the last all-up: no dragging until every finger lifts

    def reset(self):
        self.fingers, self.multi = {}, False

    def feed(self, r):
        key, kind = (r.get("block", 0), r.get("i")), r.get("kind")
        x, y, t = float(r.get("x", 0.0)), float(r.get("y", 0.0)), float(r.get("t", 0.0))
        out = []
        if kind == "start":
            self.fingers[key] = dict(x0=x, y0=y, lx=x, ly=y, lt=t, moved=False, vx=0.0, vy=0.0)
            if len(self.fingers) > 1 and not self.multi:
                self.multi = True
                if any(f["moved"] for f in self.fingers.values()):
                    out.append({"k": "pdrag", "end": True, "vx": 0.0, "vy": 0.0})
            return out
        f = self.fingers.get(key)
        if f is None:
            return out
        if kind == "move":
            if self.multi:
                return out
            if not f["moved"] and ((x - f["x0"]) ** 2 + (y - f["y0"]) ** 2) ** 0.5 < DRAG_DEAD:
                return out
            f["moved"] = True
            dx, dy, dt = x - f["lx"], y - f["ly"], max(1.0, (t - f["lt"]) * 1000.0)
            f["vx"], f["vy"] = 0.6 * f["vx"] + 0.4 * dx / dt, 0.6 * f["vy"] + 0.4 * dy / dt
            f["lx"], f["ly"], f["lt"] = x, y, t
            if dx or dy:
                out.append({"k": "pdrag", "dx": round(dx, 5), "dy": round(dy, 5)})
            return out
        if kind == "end":
            self.fingers.pop(key, None)
            if f["moved"] and not self.multi:
                fling = (t - f["lt"]) <= DRAG_STOPPED_S
                out.append({"k": "pdrag", "end": True, "vx": round(f["vx"], 6) if fling else 0.0, "vy": round(f["vy"], 6) if fling else 0.0})
            if not self.fingers:
                self.multi = False
        return out


def open_touch_stream(home, timeout=3.0):
    """A socket on the bridge's live touch feed, or None (an older bridge without touch_stream)."""
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.settimeout(timeout)
    try:
        c.connect(os.path.join(home, "sock"))
        c.sendall(b'{"command": "touch_stream"}\n')
        f = c.makefile("r")
        first = json.loads(f.readline() or "{}")
        if first.get("stream") != "touches":
            c.close(); return None
        c.settimeout(12.0)                        # the bridge pings every 5 s
        return c, f
    except (OSError, ValueError):
        c.close()
        return None


# ---------------------------------------------------------------- finding a pad

def pad_homes():
    return [os.path.expanduser(h) for h in ("~/.lyra-lightpad", "~/.lyra-lightpad-sim")]   # the real block wins


def bridge_status(home, timeout=0.6):
    """The bridge's own status answer on <home>/sock, or None when nothing answers."""
    path = os.path.join(home, "sock")
    if not os.path.exists(path):
        return None
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.settimeout(timeout)
    try:
        c.connect(path)
        c.sendall(b'{"command": "status"}\n')
        data = b""
        while b"\n" not in data:
            chunk = c.recv(65536)
            if not chunk:
                break
            data += chunk
        answer = json.loads(data)
        return answer if isinstance(answer, dict) and answer.get("ok") else None
    except (OSError, ValueError):
        return None
    finally:
        c.close()


def find_pad(homes=None):
    """(kind, home) of the first live bridge, or (None, None)."""
    for home in homes or pad_homes():
        if bridge_status(home) is not None:
            return ("sim" if home.rstrip("/").endswith("-sim") else "real"), home
    return None, None


def enabled(env=None):
    env = os.environ if env is None else env
    if env.get("TDT_PAD") in ("0", "off", "no"):
        return False
    if env.get("TDT_HOME") and env.get("TDT_PAD") not in ("1", "on", "yes"):
        return False                              # a test copy never grabs his pad unless asked
    return True


# ---------------------------------------------------------------- the link (one thread, started by server.py)

class PadLink:
    def __init__(self, send, cube_url, log_path=None, homes=None):
        self.send, self.cube_url, self.log_path, self.homes = send, cube_url, log_path, homes
        self.kind = self.home = None
        self.view, self.corners, self.visit = None, {}, None
        self.lock = threading.Lock()
        self._events = None                       # open events.jsonl, positioned at its end when the pad appeared
        self._events_ino = None
        self.drag = DragTracker()
        self.dragging = False                     # the live finger feed is connected

    # -- called by server.py
    def set_view(self, view):
        with self.lock:
            self.view = view

    def hello(self):
        """What a newly connected page needs to know (quiet: no toast on every reload)."""
        return {"k": "pad", "on": self.home is not None, "dev": self.kind, "quiet": True}

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="padglue").start()
        threading.Thread(target=self._drag_run, daemon=True, name="padglue-drag").start()
        return self

    def on_reading(self, r):
        """One live touch reading. Drags only in the cube view; inside a face the touch belongs to that session."""
        with self.lock:
            mode = (self.view or {}).get("mode")
        if mode == "face":
            self.drag.reset()
            return []
        out = self.drag.feed(r)
        for msg in out:
            self.send(msg)
        return out

    def _drag_run(self):
        while True:
            home = self.home
            if home is None:
                time.sleep(0.5); continue
            link = open_touch_stream(home)
            if link is None:
                time.sleep(2.0); continue         # older bridge: wipes still roll one face at a time
            c, f = link
            self.dragging = True
            self._log("live finger feed on: the pad drags the cube")
            try:
                while self.home == home:
                    line = f.readline()
                    if not line:
                        break
                    try: r = json.loads(line)
                    except ValueError: continue
                    if isinstance(r, dict) and "kind" in r:
                        self.on_reading(r)
            except OSError:
                pass
            finally:
                self.dragging = False
                self.drag.reset()
                try: c.close()
                except OSError: pass
            time.sleep(0.5)

    # -- internals
    def _log(self, text):
        if not self.log_path:
            return
        try:
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > LOG_MAX:
                os.replace(self.log_path, self.log_path + ".old")
            with open(self.log_path, "a") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
        except OSError:
            pass

    def _switch(self, kind, home):
        if home == self.home:
            return
        if self._events:
            self._events.close()
        self._events = self._events_ino = None
        self.kind, self.home = kind, home
        with self.lock:
            self.corners, self.visit = {}, None
        self.send({"k": "pad", "on": home is not None, "dev": kind})
        self._log(f"pad {'on: ' + kind + ' ' + home if home else 'off'}")

    def _open_events(self):
        path = os.path.join(self.home, "events.jsonl")
        try:
            ino = os.stat(path).st_ino
        except OSError:
            return
        if self._events is not None and ino == self._events_ino:
            return
        fresh = self._events_ino is not None      # the file was replaced while we watched: read the new one from its start
        if self._events:
            self._events.close()
        self._events = open(path, "r")
        self._events_ino = ino
        if not fresh:
            self._events.seek(0, os.SEEK_END)     # only touches from now on

    def _write_signal(self, now):
        with self.lock:
            view = self.view
            self.visit = visit_still_on(self.visit, view, now)
            state, self.corners = signal_state(view, self.corners, self.visit, now)
        path = os.path.join(self.home, "tesseract.json")
        try:
            with open(path + ".tmp", "w") as f:
                json.dump(state, f)
            os.replace(path + ".tmp", path)
        except OSError:
            pass

    def handle(self, g, now=None):
        """One pad gesture. Returns the message sent to the page (or None)."""
        now = time.time() if now is None else now
        with self.lock:
            view, visit = self.view, self.visit
        if g.get("gesture") == "corner_tap":
            action, visit = on_corner_tap(g, view, visit, now)
            with self.lock:
                self.visit = visit
            msg = cube_message(action)
            if msg:
                self.send(msg)
                self._log(f"corner tap -> {msg}")
                self._hand_pad_to(action[1] if action[0] == "jump" else g.get("face"))
            return msg
        msg = cube_message(route(g, view, dragging=self.dragging))
        if msg:
            self.send(msg)
            self._log(f"{g.get('gesture')} -> {msg}")
        return msg

    def _session_on_face(self, face):
        try:
            with open(os.path.join(self.home, "faces.json")) as f:
                return json.load(f).get(self.cube_url().rstrip("/"), {}).get(str(face))
        except (OSError, ValueError, AttributeError):
            return None

    def _hand_pad_to(self, face):
        """The face he's attending to owns the pad, when the presence hook has recorded which session is on it.
        A locked pad refuses this (the bridge's own rule), which is right."""
        session = self._session_on_face(face) if isinstance(face, int) else None
        if not session or not self.home:
            return
        try:
            with open(os.path.join(self.home, "bridge.json")) as f:
                info = json.load(f)
            python, project = info["python"], info["project"]
        except (OSError, ValueError, KeyError):
            return                                   # an older bridge that doesn't say where it lives
        sim = ["--sim"] if self.kind == "sim" else ["--real"]
        threading.Thread(target=lambda: subprocess.run(
            [python, "-m", "bridge.cli", "claim", *sim, "--session", session, "--take"],
            cwd=project, capture_output=True, timeout=20), daemon=True).start()

    def _run(self):
        next_detect = next_signal = 0.0
        while True:
            now = time.time()
            try:
                if now >= next_detect:
                    next_detect = now + DETECT_S
                    self._switch(*find_pad(self.homes))
                if self.home is None:
                    time.sleep(0.5)
                    continue
                if now >= next_signal:
                    next_signal = now + SIGNAL_S
                    self._write_signal(now)
                self._open_events()
                line = self._events.readline() if self._events else ""
                if not line:
                    time.sleep(0.05)
                    continue
                try:
                    g = json.loads(line)
                except ValueError:
                    continue
                if isinstance(g, dict):
                    self.handle(g)
            except Exception as e:                    # never let the pad take the cube down
                self._log(f"error: {e!r}")
                time.sleep(1.0)
