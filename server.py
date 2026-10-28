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
        if not self.alive(): self.start()
        os.write(self.fd, data)
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
def device_loop(ids, parse):
    try: import hid
    except ImportError: print("no hidapi: pip install hidapi to use a Spaceball / PowerMate (keyboard and mouse still work)", flush=True); return
    while True:
        try:
            h = hid.device(); h.open(*ids); h.set_nonblocking(1)
            while True:
                r = h.read(16)
                if r: parse(r)
                else: time.sleep(0.003)
        except (OSError, IOError):
            try: h.close()
            except Exception: pass
            time.sleep(1.0)
def parse_sb(r):
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
threading.Thread(target=device_loop, args=((0x046d, 0xc621), parse_sb), daemon=True).start()
threading.Thread(target=device_loop, args=((0x077d, 0x0410), parse_knob), daemon=True).start()
print(f"Session Cube: http://127.0.0.1:{PORT}/?k={KEY}", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
