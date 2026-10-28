#!/usr/bin/env python3
"""server.py — Session Cube: six shells on the faces of a cube in Chrome, turned by the Spaceball / PowerMate (Lyra 2026-10-27).
Run:  python3 -I server.py [--port N]      → open the URL it prints (pip install hidapi for the Spaceball / PowerMate) (it carries a per-run key).
  GET  /                      the cube page (index.html) · /vendor/<file> = xterm.js files
  GET  /stream?k=KEY          ONE event stream for everything (Chrome allows ~6 connections per host, so no per-face streams):
                                {"f": face, "o": text} terminal output · {"f": face, "exit": true} shell ended
                                {"k": "sb", "a": "t"|"r", "v": [x,y,z]} · {"k": "sbb", "m": mask} · {"k": "knob", "t": clicks, "b": 0/1}
  POST /in?k=KEY&f=N          body = keystrokes for face N (a dead shell is restarted first)
  POST /resize?k=KEY&f=N&c=COLS&r=ROWS
  POST /attn?k=KEY&f=N        body {"s": "needs"|"working", "r": reason} from hooks/cube-attention-hook.py (Claude Code hooks)
  POST /config?k=KEY&prefs=1  body = page preferences to save (colors, palette, bindings, attention settings)
Only 127.0.0.1, only with the key, only with the right Host header. Stopping this server ends every shell (and any claude in them)."""
import codecs, fcntl, json, os, pty, queue, secrets, shlex, signal, struct, subprocess, sys, termios, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
# TDT_HOME: a test copy gets its own settings + session records (2026-10-28: Lyra's test servers read and rewrote the REAL ones,
# reopening Chris's sessions inside the test cube and marking faces "not running" on shutdown). Default = the real place.
HOME3 = os.path.expanduser(os.environ.get("TDT_HOME") or "~/.config/3d-terminal")
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8781   # the Mac app uses 8782
KEY = secrets.token_urlsafe(18); FACES = 18   # 2026-10-28 shapes: up to 18 sessions (rhombicuboctahedron); started only when needed
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
listeners, listeners_lock = [], threading.Lock()
def send(obj):
    msg = json.dumps(obj)
    with listeners_lock:
        for q in listeners: q.put(msg)

# ---------- the shells: clean environment (no Anthropic keys, nothing that tells claude it is nested inside this session)
def clean_env(face=None):
    env = {k: v for k, v in os.environ.items() if not (k.startswith("ANTHROPIC_") or k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_")
                                                        or k in ("CLAUDE_PID", "CLAUDE_EFFORT"))}
    env.update(TERM="xterm-256color", COLORTERM="truecolor", SESSION_CUBE="1")
    if face is not None: env["SESSION_CUBE_FACE"] = str(face + 1)   # 1-6: lets the Claude hook record which conversation is on which face
    # 2026-10-28 Attention Routing: the attention hook reports "needs you" / "working" back to THIS server (port + this run's key)
    env.update(SESSION_CUBE_URL=f"http://127.0.0.1:{PORT}", SESSION_CUBE_KEY=KEY, SESSION_CUBE_HOME=HOME3)
    return env

class Shell:
    def __init__(self, face):
        self.face, self.buf, self.lock, self.pid, self.fd, self.size = face, bytearray(), threading.Lock(), None, None, (24, 80)
        self.restored = False
    def alive(self): return self.fd is not None
    def had_session(self):                                            # this face had Claude/Codex running at the last quit: bring it back
        try: return bool(json.load(open(os.path.join(FACES_DIR, f"face-{self.face + 1}.json"))).get("active"))
        except Exception: return False
    def start(self):
        pid, fd = pty.fork()
        if pid == 0:                                                   # child: a login zsh in Chris's home
            sh = os.environ.get("SHELL") or ("/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/bash")   # Mac or Linux
            os.chdir(os.path.expanduser("~")); os.execve(sh, ["-" + os.path.basename(sh), "-l"], clean_env(self.face))
        self.pid, self.fd = pid, fd; self.resize(*self.size)
        threading.Thread(target=self.reader, daemon=True).start()
        if not self.restored: self.restored = True; threading.Thread(target=self.restore, daemon=True).start()
    # 23:39 Chris: reopen the same sessions after quitting. hooks/claude-session-hook.py records face-N.json when Claude starts on a face;
    # at quit we keep the record only for faces that still had Claude running (stop_and_remember); here we type the resume command back in.
    def restore(self):
        rec = os.path.join(FACES_DIR, f"face-{self.face + 1}.json")
        try: r = json.load(open(rec))
        except Exception: return
        if not r.get("active") or not r.get("session_id"): return
        if r.get("kind") == "codex":
            cmd = f"cd {shlex.quote(r.get('cwd') or '~')} && {r.get('launcher') or 'codex'} resume {shlex.quote(r['session_id'])}"
            time.sleep(1.5)
            if self.alive(): os.write(self.fd, (cmd + "\r").encode())
            return
        parts = r.get("args", "claude").split()
        keep, skip = [], False
        for a in parts:                                                   # drop any old --resume/--continue, keep the other flags
            if skip: skip = False; continue
            if a in ("--resume", "-r"): skip = True; continue
            if a in ("--continue", "-c") or a.startswith("--resume="): continue
            keep.append(a)
        if not keep or os.path.basename(keep[0]) != "claude": keep = ["claude"] + keep[1:]
        cmd = f"cd {shlex.quote(r.get('cwd') or '~')} && " + " ".join(shlex.quote(a) for a in keep) + f" --resume {shlex.quote(r['session_id'])}"
        time.sleep(1.5)                                                   # let the login shell finish starting
        if self.alive(): os.write(self.fd, (cmd + "\r").encode())
    def reader(self):
        dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            try: data = os.read(self.fd, 65536)
            except OSError: data = b""
            if not data: break
            with self.lock:
                self.buf += data
                if len(self.buf) > 300_000: del self.buf[:-200_000]   # keep the recent screen history for page reloads
            send({"f": self.face, "o": dec.decode(data)})
        try: os.close(self.fd)
        except OSError: pass
        try: os.waitpid(self.pid, 0)
        except ChildProcessError: pass
        self.fd = None; send({"f": self.face, "exit": True}); set_attn(self.face, "working", "")
    def write(self, data):
        for _ in range(2):
            try:
                if not self.alive(): self.start()
                os.write(self.fd, data); return
            except OSError: self.fd = None                          # it died between the check and the write: start a fresh one
    def resize(self, rows, cols):
        self.size = (rows, cols)
        if self.alive():
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            try: os.kill(self.pid, signal.SIGWINCH)
            except ProcessLookupError: pass
    def replay(self):
        with self.lock: return self.buf.decode("utf-8", errors="replace")
FACES_DIR = os.path.join(HOME3, "faces")
# ---------- Attention Routing (Chris + Riven's spec, 2026-10-28): which faces are waiting on a person. Set ONLY by the hook's real
# events (a permission prompt, a question, a finished turn) and cleared ONLY by real progress (you typed a prompt, a tool ran, the
# session ended, the shell died). Looking at a face never clears it. "since" stays the time it FIRST started waiting.
attn, attn_lock = [{"s": "working", "r": "", "since": 0} for _ in range(FACES)], threading.Lock()
def set_attn(face, state, reason):
    with attn_lock:
        a = attn[face]
        if state == "needs":
            if a["s"] != "needs": a["since"] = int(time.time() * 1000)
            a["s"], a["r"] = "needs", reason[:60]
        elif a["s"] == "working": return
        else: a.update(s="working", r="", since=0)
        msg = dict(k="attn", f=face, **a)
    send(msg)
shells = [Shell(i) for i in range(FACES)]
def program_under(pid, names):                                       # first process below this shell whose name is in names → (pid, name)
    try: rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True, text=True, timeout=5).stdout.split("\n")
    except Exception: return None
    kids = {}
    for row in rows:
        f = row.split(None, 2)
        if len(f) == 3: kids.setdefault(int(f[1]), []).append((int(f[0]), os.path.basename(f[2])))
    todo = [pid]
    while todo:
        for c, name in kids.get(todo.pop(), []):
            if name in names: return (c, name)
            todo.append(c)
    return None
def claude_running_under(pid): return program_under(pid, {"claude"}) is not None
# 23:47 Codex too (Chris opened Riven on face 1 to test against). Codex has no start hook, so at quit we look at the codex process
# itself: its CODEX_HOME (from its environment), its folder, and its newest session file started after it (Codex writes
# CODEX_HOME/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl once the first message is sent). Which command reopens it: the
# "codex_launchers" map in ~/.config/3d-terminal/config.json (CODEX_HOME → e.g. "riven"); default "codex".
def codex_record(cpid):
    try:
        env = subprocess.run(["ps", "eww", "-o", "command=", "-p", str(cpid)], capture_output=True, text=True, timeout=5).stdout
        home = next((w.split("=", 1)[1] for w in env.split() if w.startswith("CODEX_HOME=")), os.path.expanduser("~/.codex"))
        cwd = next((l[1:] for l in subprocess.run(["lsof", "-a", "-p", str(cpid), "-d", "cwd", "-Fn"], capture_output=True, text=True,
                    timeout=5).stdout.split("\n") if l.startswith("n")), os.path.expanduser("~"))
        started = time.mktime(time.strptime(subprocess.run(["ps", "-o", "lstart=", "-p", str(cpid)], capture_output=True, text=True,
                    timeout=5).stdout.strip(), "%a %b %d %H:%M:%S %Y"))
        import glob
        files = sorted(glob.glob(os.path.join(home, "sessions", "*", "*", "*", "rollout-*.jsonl")), key=os.path.getmtime, reverse=True)
        for f in files[:40]:
            if os.path.getctime(f) < started - 5: continue                # made before this codex started: someone else's
            first = json.loads(open(f).readline()); pl = first.get("payload", first)
            if pl.get("cwd", cwd) == cwd and pl.get("id"):
                launch = load_config().get("codex_launchers", {}).get(home.replace(os.path.expanduser("~"), "~"), "codex")
                return {"kind": "codex", "session_id": pl["id"], "cwd": cwd, "codex_home": home, "launcher": launch, "active": True}
    except Exception: pass
    return None
def stop_and_remember():                                             # before the shells close: which faces had Claude running?
    for s in shells:
        if s.pid is None: continue                                     # never started this run (a parked face): keep its record as it was
        rec = os.path.join(FACES_DIR, f"face-{s.face + 1}.json")
        try:
            cx = program_under(s.pid, {"codex"}) if s.pid else None
            r = codex_record(cx[0]) if cx else None
            if r: os.makedirs(FACES_DIR, exist_ok=True); json.dump(r, open(rec, "w")); continue
            if not os.path.exists(rec): continue
            r = json.load(open(rec)); r["active"] = bool(s.pid and claude_running_under(s.pid)) and r.get("kind", "claude") == "claude"
            json.dump(r, open(rec, "w"))
        except Exception: pass

# ---------- the Spaceball + PowerMate (exclusive while this runs, so macOS stops scrolling/pointing with them)
# Button 6 (Chris 23:12): hand the Spaceball back to the Mac as an ordinary 3D mouse, and press 6 again to take it back.
# While it's handed back we open it SHARED (macOS gets it too), ignore all movement and only watch for button 6.
SB_IDS = "3dconnexion"; sb = {"free": False, "reopen": False, "mask": 0, "learn": False}
# Which button hands the ball back to the Mac is a setting (23:23, Chris: smaller 3D mice have only 2 buttons). Default: button 6.
# Kept per computer in ~/.config/3d-terminal/config.json; set from the page's ⚙ panel by pressing the button you want.
CONFIG = os.path.join(HOME3, "config.json")
def load_config():
    try: return json.load(open(CONFIG))
    except Exception: return {}
def save_config(c):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True); json.dump(c, open(CONFIG, "w"))
sb["toggle"] = int(load_config().get("toggle_button", 6))            # 1-based button number
PAGE_BUTTONS = {"select", "full", "home", "jump", "back", "color1", "color2", "color3", "color4"}   # buttons the page binds (it stores them in its prefs)
PREF_KEYS = {"buttonsByDevice", "buttonsDevice", "material", "bloom", "gl", "light", "quality", "matrixPalette", "web", "offer", "offerDelay", "sndRise", "sndAttn", "bgDim", "colors", "palette", "buttons", "glow", "lowfx", "cluster", "attnFinished", "quiet", "ageMin", "shape", "layouts", "theme", "motes", "nav", "motion", "click", "handSrc", "flip", "cubeClassic", "oneAxis", "upright"}
# Any 3Dconnexion 3D mouse (23:23, before the public post): the old ones carry Logitech's vendor id 0x046d with product 0xc6xx
# (Spaceball 5000 = c621, SpaceNavigator = c626, SpacePilot = c625, SpaceMouse Pro = c62b…); the newer ones carry 3Dconnexion's own
# 0x256f (SpaceMouse Compact c635, Wireless c62e/c62f, Enterprise c633…). Only the Spaceball 5000 has been tried on real hardware.
def find_3d_mouse(hid):
    for d in hid.enumerate():
        v, p = d["vendor_id"], d["product_id"]
        if v == 0x256f or (v == 0x046d and 0xc600 <= p <= 0xc6ff):
            sb["vendor"] = v; sb["dev"] = {"k": "device", "name": d.get("product_string") or "3D mouse", "vid": f"{v:04x}", "pid": f"{p:04x}"}
            return d["path"]
    return None
def set_exclusive(on):                                                  # macOS only: hidapi's switch between grabbing and sharing
    try:
        import ctypes, hid
        ctypes.CDLL(hid.__file__).hid_darwin_set_open_exclusive(1 if on else 0)
    except Exception: pass
def device_loop(ids, parse):
    try: import hid
    except ImportError: print("no hidapi: pip install hidapi to use a Spaceball / PowerMate (keyboard and mouse still work)", flush=True); return
    while True:
        try:
            if ids == SB_IDS:
                path = find_3d_mouse(hid)
                if path is None: raise OSError("no 3D mouse plugged in")
                set_exclusive(not sb["free"]); h = hid.device(); h.open_path(path)
            else: h = hid.device(); h.open(*ids)
            h.set_nonblocking(1)
            if ids == SB_IDS: set_exclusive(True); sb["reopen"] = False
            while not (ids == SB_IDS and sb["reopen"]):
                r = h.read(16, 250)                                    # blocks up to 250 ms: ~0 CPU while the ball sits still
                if r: parse(r)
            h.close()                                                  # button 6 flipped the mode: reopen grabbed or shared
        except (OSError, IOError):
            try: h.close()
            except Exception: pass
            time.sleep(1.0)
def parse_sb(r):
    if r[0] == 3 and len(r) >= 3:
        # 09:55 research: SpaceMouse Pro / Enterprise put buttons on bits up to 26 (Esc/Alt/Shift/Ctrl/Lock 22–26), so read up to 4 bytes
        # (32 buttons), not 2. Sources: Blender GHOST_NDOFManager.cc, spacenavd dev.c, PySpaceMouse devices.toml (all report id 3).
        m = int.from_bytes(bytes(r[1:5]), "little"); pressed = m & ~sb["mask"]; sb["mask"] = m
        if pressed and sb["learn"] and sb["learn"] is not True:        # learning a button for the page (jump / back / a colour)
            b = (pressed & -pressed).bit_length(); send({"k": "learned", "target": sb["learn"], "b": b}); sb["learn"] = False; return
        if pressed and sb["learn"]:                                   # ⚙ "change": the next button pressed becomes the hand-back button
            b = (pressed & -pressed).bit_length(); sb["toggle"] = b; sb["learn"] = False
            c = load_config(); c["toggle_button"] = b; save_config(c); send({"k": "config", "toggle": b, "learned": True}); return
        tbit = 1 << (sb["toggle"] - 1)
        if pressed & tbit:
            sb["free"] = not sb["free"]; sb["reopen"] = True
            send({"k": "sbfree", "free": sb["free"]}); return
        r = [r[0]] + list((m & ~tbit).to_bytes(4, "little"))            # the cube never sees the hand-back button
    if sb["free"]: return                                              # handed back to the Mac: the cube ignores it
    if sb.get("vendor") == 0x256f and r[0] == 1 and len(r) >= 13:      # newer (0x256f) models: push AND twist in one 12-byte report
        v = struct.unpack("<6h", bytes(r[1:13]))
        send({"k": "sb", "a": "t", "v": list(v[:3])}); send({"k": "sb", "a": "r", "v": list(v[3:])}); return
    if r[0] in (1, 2) and len(r) >= 7: send({"k": "sb", "a": "t" if r[0] == 1 else "r", "v": list(struct.unpack("<3h", bytes(r[1:7])))})
    elif r[0] == 3 and len(r) >= 3: send({"k": "sbb", "m": int.from_bytes(bytes(r[1:5]), "little")})
def parse_knob(r): send({"k": "knob", "t": r[1] - 256 if r[1] > 127 else r[1], "b": r[0]})

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def deny(self, code=403): self.send_response(code); self.end_headers()
    def guard(self, q):
        return self.headers.get("Host", "") in HOSTS and secrets.compare_digest(q.get("k", [""])[0], KEY)
    def file(self, path, ctype):
        body = open(path, "rb").read()
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if self.headers.get("Host", "") not in HOSTS: return self.deny()
        if u.path == "/": return self.file(os.path.join(HERE, "index.html"), "text/html; charset=utf-8")
        if u.path == "/gl.js": return self.file(os.path.join(HERE, "gl.js"), "text/javascript")
        if u.path.startswith("/vendor/"):                              # anything under vendor/ (xterm, three.js + its addons), never outside it
            real, root = os.path.realpath(os.path.join(HERE, u.path.lstrip("/"))), os.path.realpath(os.path.join(HERE, "vendor"))
            ext = os.path.splitext(real)[1]
            if real.startswith(root + os.sep) and os.path.isfile(real) and ext in (".js", ".css"):
                return self.file(real, "text/javascript" if ext == ".js" else "text/css")
            return self.deny(404)
        if u.path != "/stream": return self.deny(404)
        if not self.guard(q): return self.deny()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
        self.end_headers(); mine = queue.Queue()
        for s in shells:                                               # the first six always run; more start when a shape shows them
            if not s.alive() and (s.face < 6 or s.pid is not None or s.had_session()): s.start()
            mine.put(json.dumps({"f": s.face, "o": s.replay(), "replay": True}))
        mine.put(json.dumps({"k": "config", "toggle": sb["toggle"], "prefs": load_config().get("prefs", {})}))
        if sb.get("dev"): mine.put(json.dumps(sb["dev"]))                # which 3D mouse this is (the page shows its own button labels)
        with attn_lock:
            for i, a in enumerate(attn): mine.put(json.dumps(dict(k="attn", f=i, **a)))
        with listeners_lock: listeners.append(mine)
        try:
            while True:
                try: self.wfile.write(f"data: {mine.get(timeout=10)}\n\n".encode())
                except queue.Empty: self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError): pass
        finally:
            with listeners_lock: listeners.remove(mine)
    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if not self.guard(q): return self.deny()
        if u.path == "/config":                                       # ⚙: ?learn=1 = the next button pressed becomes the hand-back button
            what = q.get("learn", [""])[0]                             # ?learn=jump / back / color1… = learn a button for the page instead
            if what == "1": sb["learn"] = True
            elif what in PAGE_BUTTONS: sb["learn"] = what
            if q.get("prefs", ["0"])[0] == "1":                        # the page's own settings, kept per computer in config.json
                try: new = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", "0") or 0), 65536)))
                except Exception: return self.deny(400)
                c = load_config(); p = c.get("prefs", {})
                p.update({k: v for k, v in new.items() if k in PREF_KEYS}); c["prefs"] = p; save_config(c)
            self.send_response(204); self.end_headers(); return
        try: f = int(q.get("f", ["-1"])[0]); s = shells[f] if 0 <= f < FACES else None
        except ValueError: s = None
        if s is None: return self.deny(400)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        if u.path == "/in": s.write(body)
        elif u.path == "/start":                                      # the page shows this face now: make sure its shell runs
            if not s.alive(): s.start()
        elif u.path == "/attn":
            try: m = json.loads(body)
            except Exception: return self.deny(400)
            if m.get("s") in ("needs", "working"): set_attn(f, m["s"], str(m.get("r", "")))
        elif u.path == "/resize":
            c, r = int(q.get("c", ["80"])[0]), int(q.get("r", ["24"])[0])
            if 10 <= c <= 500 and 4 <= r <= 300: s.resize(r, c)
        else: return self.deny(404)
        self.send_response(204); self.end_headers()

def stop(*_):
    stop_and_remember()
    for s in shells:
        if s.pid:
            try: os.kill(s.pid, signal.SIGHUP)
            except ProcessLookupError: pass
    sys.exit(0)
signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
threading.Thread(target=device_loop, args=(SB_IDS, parse_sb), daemon=True).start()
threading.Thread(target=device_loop, args=((0x077d, 0x0410), parse_knob), daemon=True).start()
try: httpd = ThreadingHTTPServer(("127.0.0.1", PORT), H)
except OSError:                                                      # port busy (an old copy still running?): take any free one
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H); PORT = httpd.server_address[1]
    HOSTS.clear(); HOSTS.update({f"127.0.0.1:{PORT}", f"localhost:{PORT}"})
# 2) never outlive whoever started us: with --parent PID, stop as soon as that process is gone (app crashed or was force-quit)
if "--parent" in sys.argv:
    PARENT = int(sys.argv[sys.argv.index("--parent") + 1])
    def watch_parent():
        while True:
            time.sleep(1.0)
            try: os.kill(PARENT, 0)
            except ProcessLookupError: os.kill(os.getpid(), signal.SIGTERM); return
    threading.Thread(target=watch_parent, daemon=True).start()
print(f"Session Cube: http://127.0.0.1:{PORT}/?k={KEY}", flush=True)
httpd.serve_forever()
