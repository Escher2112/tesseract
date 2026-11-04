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


def route(g, view):
    """What a pad gesture does given the cube's view. Corner taps are handled by on_corner_tap."""
    if (view or {}).get("mode") == "face":
        return None                              # inside a face: the touch belongs to that face's session
    action, _ = decide(g, False)
    return action                                # cube view: wipes step, a deliberate hold dives in


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
        dx = action[1]
        return {"k": "step", "d": 1 if dx > 0 else -1} if dx else None   # vertical wipes don't step (or dive in)
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

    # -- called by server.py
    def set_view(self, view):
        with self.lock:
            self.view = view

    def hello(self):
        """What a newly connected page needs to know (quiet: no toast on every reload)."""
        return {"k": "pad", "on": self.home is not None, "dev": self.kind, "quiet": True}

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="padglue").start()
        return self

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
        msg = cube_message(route(g, view))
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
