#!/usr/bin/env python3
"""server.py — Session Cube: six shells on the faces of a cube in Chrome, turned by the Spaceball / PowerMate (Lyra 2026-10-27).
Run:  python3 -I server.py [--port N]      → open the URL it prints (pip install hidapi for the Spaceball / PowerMate) (it carries a per-run key).
  GET  /                      the cube page (index.html) · /vendor/<file> = xterm.js files
  GET  /stream?k=KEY          ONE event stream for everything (Chrome allows ~6 connections per host, so no per-face streams):
                                {"f": face, "o": text} terminal output · {"f": face, "exit": true} shell ended
                                {"k": "sb", "a": "t"|"r", "v": [x,y,z]} · {"k": "sbb", "m": mask} · {"k": "knob", "t": clicks, "b": 0/1}
  POST /in?k=KEY&f=N          body = keystrokes for face N (a dead shell is restarted first)
  POST /resize?k=KEY&f=N&c=COLS&r=ROWS
Only 127.0.0.1, only with the key, only with the right Host header. Stopping this server ends every shell (and any claude in them)."""
import codecs, fcntl, json, os, pty, queue, secrets, signal, struct, sys, termios, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8781   # the Mac app uses 8782
KEY = secrets.token_urlsafe(18); FACES = 6
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
listeners, listeners_lock = [], threading.Lock()
def send(obj):
    msg = json.dumps(obj)
    with listeners_lock:
        for q in listeners: q.put(msg)

# ---------- the shells: clean environment (no Anthropic keys, nothing that tells claude it is nested inside this session)
def clean_env():
    env = {k: v for k, v in os.environ.items() if not (k.startswith("ANTHROPIC_") or k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_")
                                                        or k in ("CLAUDE_PID", "CLAUDE_EFFORT"))}
    env.update(TERM="xterm-256color", COLORTERM="truecolor", SESSION_CUBE="1")
    return env

class Shell:
    def __init__(self, face):
        self.face, self.buf, self.lock, self.pid, self.fd, self.size = face, bytearray(), threading.Lock(), None, None, (24, 80)
    def alive(self): return self.fd is not None
    def start(self):
        pid, fd = pty.fork()
        if pid == 0:                                                   # child: a login zsh in Chris's home
            sh = os.environ.get("SHELL") or ("/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/bash")   # Mac or Linux
            os.chdir(os.path.expanduser("~")); os.execve(sh, ["-" + os.path.basename(sh), "-l"], clean_env())
        self.pid, self.fd = pid, fd; self.resize(*self.size)
        threading.Thread(target=self.reader, daemon=True).start()
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
        self.fd = None; send({"f": self.face, "exit": True})
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
shells = [Shell(i) for i in range(FACES)]

# ---------- the Spaceball + PowerMate (exclusive while this runs, so macOS stops scrolling/pointing with them)
# Button 6 (Chris 23:12): hand the Spaceball back to the Mac as an ordinary 3D mouse, and press 6 again to take it back.
# While it's handed back we open it SHARED (macOS gets it too), ignore all movement and only watch for button 6.
SB_IDS = "3dconnexion"; sb = {"free": False, "reopen": False, "mask": 0}
# Any 3Dconnexion 3D mouse (23:23, before the public post): the old ones carry Logitech's vendor id 0x046d with product 0xc6xx
# (Spaceball 5000 = c621, SpaceNavigator = c626, SpacePilot = c625, SpaceMouse Pro = c62b…); the newer ones carry 3Dconnexion's own
# 0x256f (SpaceMouse Compact c635, Wireless c62e/c62f, Enterprise c633…). Only the Spaceball 5000 has been tried on real hardware.
def find_3d_mouse(hid):
    for d in hid.enumerate():
        v, p = d["vendor_id"], d["product_id"]
        if v == 0x256f or (v == 0x046d and 0xc600 <= p <= 0xc6ff): sb["vendor"] = v; return d["path"]
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
        m = r[1] | (r[2] << 8); pressed = m & ~sb["mask"]; sb["mask"] = m
        if pressed & 0x20:                                             # button 6
            sb["free"] = not sb["free"]; sb["reopen"] = True
            send({"k": "sbfree", "free": sb["free"]}); return
    if sb["free"]: return                                              # handed back to the Mac: the cube ignores it
    if sb.get("vendor") == 0x256f and r[0] == 1 and len(r) >= 13:      # newer (0x256f) models: push AND twist in one 12-byte report
        v = struct.unpack("<6h", bytes(r[1:13]))
        send({"k": "sb", "a": "t", "v": list(v[:3])}); send({"k": "sb", "a": "r", "v": list(v[3:])}); return
    if r[0] in (1, 2) and len(r) >= 7: send({"k": "sb", "a": "t" if r[0] == 1 else "r", "v": list(struct.unpack("<3h", bytes(r[1:7])))})
    elif r[0] == 3 and len(r) >= 3: send({"k": "sbb", "m": r[1] | (r[2] << 8)})
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
        if u.path in ("/vendor/xterm.js", "/vendor/addon-fit.js"): return self.file(HERE + u.path, "text/javascript")
        if u.path == "/vendor/xterm.css": return self.file(HERE + u.path, "text/css")
        if u.path != "/stream": return self.deny(404)
        if not self.guard(q): return self.deny()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
        self.end_headers(); mine = queue.Queue()
        for s in shells:
            if not s.alive(): s.start()
            mine.put(json.dumps({"f": s.face, "o": s.replay(), "replay": True}))
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
        try: f = int(q.get("f", ["-1"])[0]); s = shells[f] if 0 <= f < FACES else None
        except ValueError: s = None
        if s is None: return self.deny(400)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        if u.path == "/in": s.write(body)
        elif u.path == "/resize":
            c, r = int(q.get("c", ["80"])[0]), int(q.get("r", ["24"])[0])
            if 10 <= c <= 500 and 4 <= r <= 300: s.resize(r, c)
        else: return self.deny(404)
        self.send_response(204); self.end_headers()

def stop(*_):
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
