#!/usr/bin/env python3
"""server.py — Session Cube: six shells on the faces of a cube in Chrome, turned by the Spaceball / PowerMate (Lyra 2026-10-27).
Run:  python3 -I server.py [--port N]      → open the URL it prints (pip install hidapi for the Spaceball / PowerMate) (it carries a per-run key).
  GET  /                      the cube page (index.html) · /gl.js = what draws the solid · /vendor/<file> = xterm.js files
  GET  /stream?k=KEY          ONE event stream for everything (Chrome allows ~6 connections per host, so no per-face streams):
                                {"f": face, "o": text} terminal output · {"f": face, "exit": true} shell ended
                                {"k": "sb", "a": "t"|"r", "v": [x,y,z]} · {"k": "sbb", "m": mask} · {"k": "knob", "t": clicks, "b": 0/1}
  POST /in?k=KEY&f=N          body = keystrokes for face N (a dead shell is restarted first)
  POST /start?k=KEY&f=N       the page shows face N now: its shell is started if it is not running
  POST /resize?k=KEY&f=N&c=COLS&r=ROWS
  POST /attn?k=KEY&f=N        body {"s": "needs"|"working", "r": reason} from hooks/cube-attention-hook.py (Claude Code hooks)
  POST /config?k=KEY&prefs=1  body = page preferences to save (colors, palette, bindings, attention settings)
                                ?learn=1 = the next button pressed becomes the hand-back button · ?learn=jump / back / color1… = that button is learned for the page instead
                                ?knob=toggle|free|grab = hand the PowerMate to the Mac / take it back
  POST /take?k=KEY            body {"pid": claude pid, "face": 1-18 optional} from `tess`: that session moves onto a face (HAND-OFF)
  POST /out?k=KEY&f=N         face N's Claude session moves to a new Terminal window (Ctrl+Option+O in the page)
  POST /live?k=KEY            → {"live": [faces whose shell has something running]} (the Rolodex lists only those; null = can't tell)
  POST /blockview?k=KEY       body = the page's view and its waiting faces, for the Lightpad (padglue.py, optional)
                                (a POST that declares more than its door takes is refused, 413: H.MOST; one that declares a length below zero, 400)
  ~/.config/3d-terminal/server.json (0600) = this run's url + key, so `tess` can find it; removed on quit
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
        cmd = resume_cmd(r)
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
ARG_ONE = {"--model", "--effort", "--permission-mode", "-n", "--name", "--agent", "--settings", "--fallback-model", "--add-dir", "--mcp-config", "--plugin-dir", "--debug-file", "--autocompact"}   # options with one plain value
ARG_TEXT = {"--append-system-prompt", "--system-prompt", "--agents", "--json-schema", "--from-pr", "--cloud", "--environment", "--file", "--betas", "--allowedTools", "--allowed-tools", "--disallowedTools", "--disallowed-tools"}   # options whose value is a text or a list: dropped whole
SKIP_PERMS = "--dangerously-skip-permissions"                         # an option that takes no value (a word after it is the first word of a prompt)
def resume_cmd(r):                                                   # the shell line that reopens a recorded conversation (restore + hand-off)
    if r.get("kind") == "codex":
        return f"cd {shlex.quote(os.path.expanduser(r.get('cwd') or '~'))} && {r.get('launcher') or 'codex'} resume {shlex.quote(r['session_id'])}"   # (a record without a folder: his home, spelled out. A quoted ~ is not a folder to a shell)
    # The session's command line comes back from `ps` as plain words: its quotes are gone. So what is typed again is its OPTIONS only.
    # ⛔ Never a bare word: `claude "deploy it"` would otherwise send "deploy it" to the session a second time at every reopening. An option
    # that takes one plain value keeps it; one whose value is a text of several words (a system prompt, a list of tools) is dropped whole,
    # because the half of it that could be told apart would be a different instruction. (Options as of Claude Code 2.1.328.)
    # ⛔ WHAT IS TYPED INTO HIS SHELL IS NEVER CHANGED BY A WORD FROM INSIDE A PROMPT OR A TEXT. A word that begins with a dash looks like an option
    # wherever it stands: `claude never run with --dangerously-skip-permissions please` was reopened with that option. So the options are read only
    # up to the first word that is not one (a prompt begins there), up to `--`, and up to an option whose value is a text; nothing after that is typed.
    toks, keep = r.get("args", "claude").split(), []
    i = 2 if len(toks) > 1 and os.path.basename(toks[0]) != "claude" and os.path.basename(toks[1]) == "claude" else 1   # (started through another program: its own name is the second word, and its options begin after that)
    keep.append(toks[0] if toks else "claude")
    while i < len(toks):
        a = toks[i]; i += 1; name = a.split("=", 1)[0]
        value = i < len(toks) and not toks[i].startswith("-")          # is the next word a value (not another option)?
        if a in ("-", "--") or not a.startswith("-") or name in ARG_TEXT: break   # a bare word, the end-of-options mark, or a text: from here on no word can be told from the words of a prompt
        if name in ("--resume", "-r", "--continue", "-c", "--session-id", "--fork-session"):                # (the conversation is named by us, below)
            if value and "=" not in a and name not in ("--continue", "-c", "--fork-session"): i += 1
        elif name in ARG_ONE:
            if "=" in a: keep.append(a)
            elif value: keep += [a, toks[i]]; i += 1                    # (without its value it is not typed: it would take our --resume for one)
        elif value and "=" not in a and a != SKIP_PERMS: break          # an option this list does not know, and a word after it: its value, or the first word of a prompt. Typed without that word it would take our --resume as its value; so it is not typed, and nothing after it
        else: keep.append(a)
    if not keep or os.path.basename(keep[0]) != "claude": keep = ["claude"] + keep[1:]
    return f"cd {shlex.quote(os.path.expanduser(r.get('cwd') or '~'))} && " + " ".join(shlex.quote(a) for a in keep) + f" --resume {shlex.quote(r['session_id'])}"
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
# 2026-11-03 the Lightpad Block (padglue.py, optional): it sleeps until a pad bridge answers, then the page reports its view + waiting
# faces (POST /blockview) and the pad's calling corners / wipes / corner taps come back as the page's own step, enter, jump and goBack.
pad = None
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

# ---------- HAND-OFF (Chris 2026-11-12: "take this window… throw them onto a face in tesseract without having to reopen them… loses no
# continuity, and back again"). macOS can't move a running program between terminal windows, so a hand-off moves the CONVERSATION:
# wait until the session finishes its turn (never cut it off mid-work), end that claude the way closing its window would (SIGHUP), and
# resume the same session id on a face (`tess`, POST /take) or in a new Terminal window (Ctrl+Option+O, POST /out). Nothing new runs in the
# background: this server only works while Tesseract is open, and each hand-off is one short thread. The old claude is always gone before
# the new one starts, so two processes never write one conversation. Claude Code only (Codex: not yet). Log: HOME3/handoff.log.
SESS_DIR = os.path.expanduser(os.environ.get("TDT_CLAUDE_SESSIONS") or ("~/.claude/sessions" if not os.environ.get("TDT_HOME") else os.path.join(HOME3, "claude-sessions")))   # Claude Code's own <pid>.json per session
# (⛔ a test copy, TDT_HOME set, that was handed no pretend folder reads a place of its own that holds nothing, never his real one: handed a real session's number it finds no record, so it ends nothing)
NO_TERMINAL = os.environ.get("TDT_NO_TERMINAL") == "1" or sys.platform != "darwin" or bool(os.environ.get("TDT_HOME"))   # tests (and Linux): never drive Terminal.app. Every test copy (TDT_HOME set), also one that did not ask for it
reserved, reserved_lock = set(), threading.Lock()                     # faces promised to a hand-off still waiting for its turn to end
moving = {}                                                           # session id → where it is going ("face N" / "a Terminal window"), under
                                                                      # reserved_lock. 2026-11-12 09:43: `tess` twice on one session put it on
                                                                      # faces 2 AND 3 (two claudes, one conversation). A move in flight refuses another.
def hlog(msg):
    try:
        with open(os.path.join(HOME3, "handoff.log"), "a") as f: f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError: pass
def note(t): send({"k": "note", "t": t}); hlog(t)
def ps1(field, pid):
    try: return subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception: return ""
def claude_info(pid):                                                 # a live claude of this user → its session record, else None
    try: pid = int(pid)
    except (TypeError, ValueError): return None
    if os.path.basename(ps1("comm", pid)) != "claude": return None
    try: j = json.load(open(os.path.join(SESS_DIR, f"{pid}.json")))
    except Exception: return None
    if not j.get("sessionId"): return None
    return {"pid": pid, "session_id": j["sessionId"], "cwd": j.get("cwd") or os.path.expanduser("~"), "args": ps1("args", pid) or "claude",
            "name": j.get("name") or j["sessionId"][:8], "tty": ps1("tty", pid)}
def status_of(pid):
    try: return json.load(open(os.path.join(SESS_DIR, f"{pid}.json"))).get("status", "")
    except Exception: return ""
def alive_pid(pid):                                                   # a zombie (ended, not yet reaped by its parent) counts as gone
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: pass
    st = ps1("stat", pid)
    return not st.startswith("Z")                                     # (no answer from `ps`: the system has just said the process is there, so it is not taken for gone. If it ended meanwhile, the next look says so)
def wait_idle(pid, timeout=900):                                      # "gone" · "idle" (twice in a row, 0.5 s apart) · None = gave up
    end, streak = time.time() + timeout, 0
    while time.time() < end:
        if not alive_pid(pid): return "gone"
        streak = streak + 1 if status_of(pid) == "idle" else 0
        if streak >= 2: return "idle"
        time.sleep(0.5)
    return None
def end_claude(pid):                                                  # what closing its window does; SIGTERM if that's ignored. True = gone
    for sig in (signal.SIGHUP, signal.SIGTERM):
        try: os.kill(pid, sig)
        except ProcessLookupError: return True
        for _ in range(40):
            if not alive_pid(pid): return True
            time.sleep(0.2)
    return False
def has_children(pid):
    try: rows = subprocess.run(["ps", "-A", "-o", "ppid="], capture_output=True, text=True, timeout=5).stdout.split()
    except Exception: return True
    return str(pid) in rows
SHELLS = {"zsh", "bash", "sh", "fish", "dash", "ksh", "tcsh", "csh"}
def at_prompt(s):                                                     # this face's shell runs, nothing runs in it, and it is still a shell (a program that took the shell's place would be sent whatever is typed there)
    if not s.alive() or has_children(s.pid): return False
    name = os.path.basename(ps1("comm", s.pid)).lstrip("-")            # (no answer from `ps`: cannot tell, so not free)
    return bool(name) and name in SHELLS | {os.path.basename(os.environ.get("SHELL") or "")}
def live_faces():                                                     # the faces whose shell has something running in it (a claude, a codex,
    try: rows = set(subprocess.run(["ps", "-A", "-o", "ppid="], capture_output=True, text=True, timeout=5).stdout.split())   # any program)
    except Exception: return None                                     # can't tell: the page falls back to faces whose session set a title
    return [s.face for s in shells if s.alive() and s.pid and str(s.pid) in rows]
def web_faces():                                                      # the faces he has made into BROWSERS: their shell is there, but nobody can see it
    try: return {int(k) for k in (load_config().get("prefs", {}).get("web") or {})}
    except Exception: return set()
def free_face():                                                      # a face with an idle shell (nothing running in it), lowest number first;
    web = web_faces()                                                 # else a face whose shell never started and has no session to reopen. Never a browser face.
    with reserved_lock:
        for f in list(range(6)) + list(range(6, FACES)):
            s = shells[f]
            if f not in reserved and f not in web and at_prompt(s): reserved.add(f); return f
        for f in range(FACES):
            s = shells[f]
            if f not in reserved and f not in web and not s.alive() and not s.had_session(): reserved.add(f); return f
    return None
def osa(script, *args):
    if NO_TERMINAL: hlog("would run AppleScript with " + json.dumps(args)); return "skipped"
    try: return subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e: return f"error {e!r}"
CLOSE_TAB = '''on run argv
  tell application "Terminal"
    repeat with w in windows
      repeat with b in tabs of w
        if tty of b is (item 1 of argv) then
          if busy of b then return "busy"
          do script "exit" in b
          return "closed"
        end if
      end repeat
    end repeat
  end tell
  return "no tab"
end run'''
OPEN_WINDOW = '''on run argv
  tell application "Terminal"
    activate
    do script (item 1 of argv)
  end tell
  return "opened"
end run'''
def take_worker(info, f):                                             # Terminal → face f
    typed = False
    try:
        pid, cmd = info["pid"], resume_cmd(info)
        if status_of(pid) != "idle": note(f"{info['name']} moves to face {f + 1} when it finishes this turn")
        w = wait_idle(pid)
        if w is None: note(f"hand-off of {info['name']} cancelled: it never finished its turn (15 min)"); return
        if w == "idle" and not end_claude(pid): note(f"hand-off cancelled: {info['name']} would not close"); return
        s = shells[f]
        if f in web_faces() or (s.alive() and not at_prompt(s)):     # someone started something on that face while we waited (or made it a browser): pick again
            with reserved_lock: reserved.discard(f)
            nf = free_face()
            if nf is None: note(f"no free face for {info['name']}: in any terminal type: {cmd}"); return
            f, s = nf, shells[nf]
        if not s.alive(): s.restored = True; s.start(); time.sleep(1.5)
        else: os.write(s.fd, b"\x03"); time.sleep(0.25)               # (a shell that was already there: anything half-typed, or a quote left open, is dropped first, never run with this line)
        os.write(s.fd, (cmd + "\r").encode()); typed = True; hlog(f"take {info['session_id']} → face {f + 1}: {cmd}")
        send({"k": "arrive", "f": f, "t": info["name"]})
        if w == "idle" and info.get("tty") and info["tty"] not in ("??", ""):   # (only the tab of a session WE ended: one that ended by itself while it waited has left a shell that is his again, and "exit" is not typed there)
            time.sleep(0.5); hlog(f"close tab /dev/{info['tty']}: {osa(CLOSE_TAB, '/dev/' + info['tty'])}")
    except Exception as e: note(f"hand-off failed: {e!r}")
    finally:
        def free(f=f):
            with reserved_lock: reserved.discard(f)
        with reserved_lock: moving.pop(info["session_id"], None)
        if not typed: free()
        else: t = threading.Timer(25, free); t.daemon = True; t.start()   # (the face stays promised until its session has had time to come up there: a shell slow to reach its prompt looks idle meanwhile, and a second session must not land on it)
def out_worker(info, f):                                              # face f → a new Terminal window
    try:
        pid, cmd = info["pid"], resume_cmd(info)
        if status_of(pid) != "idle": note(f"face {f + 1} moves to a Terminal window when it finishes this turn")
        w = wait_idle(pid)
        if w is None: note(f"hand-off of face {f + 1} cancelled: it never finished its turn (15 min)"); return
        if w == "idle" and not end_claude(pid): note(f"hand-off cancelled: face {f + 1} would not close"); return
        send({"k": "left", "f": f}); hlog(f"out {info['session_id']} from face {f + 1}: {cmd}")
        r = osa(OPEN_WINDOW, cmd)
        note(f"{info['name']} is in a Terminal window now" if r in ("opened", "skipped") else f"couldn't open Terminal ({r}); in any terminal type: {cmd}")
    except Exception as e: note(f"hand-off failed: {e!r}")
    finally:
        with reserved_lock: moving.pop(info["session_id"], None)

# ---------- the Spaceball + PowerMate (exclusive while this runs, so macOS stops scrolling/pointing with them)
# Button 6 (Chris 23:12): hand the Spaceball back to the Mac as an ordinary 3D mouse, and press 6 again to take it back.
# While it's handed back we open it SHARED (macOS gets it too), ignore all movement and only watch for button 6.
SB_IDS = "3dconnexion"; sb = {"free": False, "reopen": False, "mask": 0, "learn": False}
# Which button hands the ball back to the Mac is a setting (23:23, Chris: smaller 3D mice have only 2 buttons). Default: button 6.
# Kept per computer in ~/.config/3d-terminal/config.json; set from the page's ⚙ panel by pressing the button you want.
CONFIG = os.path.join(HOME3, "config.json")
config_lock = threading.Lock()                                        # one save at a time: each reads the file, changes it and writes it back
def load_config(aside=False):                                        # his settings · {} when there are none (a first start)
    try: raw = open(CONFIG, "rb").read()
    except FileNotFoundError: return {}
    except OSError:                                                   # there, but it could not be opened or read just now (no permission, too many open files): a passing error, not a broken file
        if aside: raise                                               # (a save is coming: nothing is set aside and nothing is written; the caller refuses the save)
        return {}
    try:
        c = json.loads(raw)
        if isinstance(c, dict): return c
    except Exception: pass
    if aside:                                                         # a file that is there and cannot be read, and a save is coming: SET ASIDE WHOLE under another name, never written over (if even that fails this raises, and nothing is written)
        keep = "%s.unreadable-%s-%s" % (CONFIG, time.strftime("%Y%m%d-%H%M%S"), os.urandom(2).hex()); os.replace(CONFIG, keep)
        hlog("settings: config.json could not be read; that file was set aside whole as %s, and a new one begun" % os.path.basename(keep))
    return {}
def save_config(c):                                                  # written beside it and moved into place: a read never meets half a file, and a stop in the middle of a save leaves the old one whole
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True); p = os.path.realpath(CONFIG)   # (the file itself, should config.json be a link to it: the link stays a link)
    with open(p + ".new", "w") as f: json.dump(c, f)
    os.replace(p + ".new", p)
sb["toggle"] = int(load_config().get("toggle_button", 6))            # 1-based button number
PAGE_BUTTONS = {"select", "full", "home", "jump", "back", "forward", "quickref", "color1", "color2", "color3", "color4"}   # (22:00 + forward/quickref: re-learning them silently did nothing)   # buttons the page binds (it stores them in its prefs)
PREF_KEYS = {"sbBias", "buttonsByDevice", "buttonsDevice", "material", "bloom", "gl", "light", "quality", "matrixPalette", "web", "offer", "offerDelay", "sndRise", "sndAttn", "bgDim", "colors", "palette", "buttons", "glow", "lowfx", "cluster", "attnFinished", "attnDone", "quiet", "ageMin", "shape", "layouts", "theme", "motes", "nav", "motion", "click", "handSrc", "flip", "cubeClassic", "oneAxis", "upright", "homeFace", "drumAll", "fastSwap"}
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
# 2026-10-28 22:00 Chris: "the PowerMate is not functioning… just doing normal cursor things, scrolling very slowly." hidapi's grab/share
# switch is ONE GLOBAL for every device: handing the ball back (button 6) flipped it to "share", and a PowerMate (re)opening in that moment
# was opened SHARED and stayed that way, so macOS kept scrolling with it. Now every open sets the switch for ITS device under one lock,
# and the PowerMate has its own hand-back (Ctrl+Option+K or ⚙ → Buttons), like the ball's button 6.
HID_LOCK = threading.Lock(); knob = {"free": False, "reopen": False, "status": "missing"}
# 2026-10-29 Chris: "figure out this PowerMate mess". The knob failed SILENTLY when macOS withheld Input Monitoring (after every rebuild).
# Now its state is reported to the page: "ok" (the cube has it) · "missing" (not plugged in) · "blocked" (plugged in, macOS refuses to let
# us open it = Input Monitoring is off for Tesseract). ⚙ → Buttons shows it, with a button that opens the right Settings page.
def knob_status(s):
    if knob.get("status") != s: knob["status"] = s; send({"k": "knobstat", "s": s})
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
            st = sb if ids == SB_IDS else knob                           # this device's own state: grabbed (cube) or shared (handed to the Mac)
            with HID_LOCK:                                             # the switch is global: set it for THIS open only, then put it back
                if ids == SB_IDS:
                    path = find_3d_mouse(hid)
                    if path is None: raise OSError("no 3D mouse plugged in")
                    set_exclusive(not st["free"]); h = hid.device(); h.open_path(path)
                else: set_exclusive(not st["free"]); h = hid.device(); h.open(*ids)
                set_exclusive(True)
            h.set_nonblocking(1); st["reopen"] = False
            if ids != SB_IDS: knob_status("ok")
            while not st["reopen"]:
                r = h.read(16, 250)                                    # blocks up to 250 ms: ~0 CPU while the ball sits still
                if r: parse(r)
            h.close()                                                  # a hand-back flipped the mode: reopen grabbed or shared
        except (OSError, IOError):
            try: h.close()
            except Exception: pass
            if ids != SB_IDS:
                try: knob_status("blocked" if hid.enumerate(*ids) else "missing")   # plugged in but unopenable = no permission
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
            try:
                with config_lock: c = load_config(True); c["toggle_button"] = b; save_config(c)
            except OSError: hlog("settings: the new hand-back button is in use, but could not be saved: the settings file could not be read or written just now")
            send({"k": "config", "toggle": b, "learned": True}); return
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
def parse_knob(r):
    if knob["free"]: return                                            # handed to the Mac: the cube ignores it (macOS scrolls with it)
    send({"k": "knob", "t": r[1] - 256 if r[1] > 127 else r[1], "b": r[0]})

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
        mine.put(json.dumps({"k": "config", "toggle": sb["toggle"], "prefs": load_config().get("prefs", {})})); mine.put(json.dumps({"k": "knobfree", "free": knob["free"], "quiet": True})); mine.put(json.dumps({"k": "knobstat", "s": knob["status"], "quiet": True}))
        if pad is not None: mine.put(json.dumps(pad.hello()))          # is a Lightpad here (the page reports to it only if so)
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
    MOST = {"/config": 65536, "/take": 4096}                           # the most each door reads (the doors not named have no limit of their own)
    def fits(self, path):                                             # may this door read what the caller says it sends? If not it is REFUSED here: never cut short and then read as something else
        try: n = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError: n = -1
        most = self.MOST.get(path)
        if n < 0: self.deny(400); return False                        # (a length below zero would be read until the caller hangs up, past every limit)
        if most is not None and n > most:
            left = min(n, 100_000_000)                                 # (what was sent is read off and thrown away first, so the caller gets this answer and not a broken connection)
            while left > 0:
                got = self.rfile.read(min(left, 65536))
                if not got: break
                left -= len(got)
            self.deny(413); return False
        self.sent = n; return True
    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if not self.guard(q): return self.deny()
        if not self.fits(u.path): return
        if u.path == "/config":                                       # ⚙: ?learn=1 = the next button pressed becomes the hand-back button
            what = q.get("learn", [""])[0]                             # ?learn=jump / back / color1… = learn a button for the page instead
            if what == "1": sb["learn"] = True
            elif what in PAGE_BUTTONS: sb["learn"] = what
            kn = q.get("knob", [""])[0]                                # ?knob=toggle|free|grab: hand the PowerMate to the Mac / take it back
            if kn in ("toggle", "free", "grab"):
                knob["free"] = (not knob["free"]) if kn == "toggle" else (kn == "free"); knob["reopen"] = True
                send({"k": "knobfree", "free": knob["free"]})
            if q.get("prefs", ["0"])[0] == "1":                        # the page's own settings, kept per computer in config.json
                try: new = json.loads(self.rfile.read(self.sent))
                except Exception: return self.deny(400)
                if not isinstance(new, dict): return self.deny(400)
                try:
                    with config_lock:
                        c = load_config(True); p = c.get("prefs", {})
                        p.update({k: v for k, v in new.items() if k in PREF_KEYS}); c["prefs"] = p; save_config(c)
                except OSError: return self.deny(503)                   # (his settings file could not be read or written just now: this save is refused, and the file is left exactly as it was)
            self.send_response(204); self.end_headers(); return
        if u.path == "/blockview":                                    # the page reports its view + waiting faces for the Lightpad
            try: v = json.loads(self.rfile.read(self.sent) or b"{}")
            except Exception: return self.deny(400)
            if not isinstance(v, dict): return self.deny(400)
            if pad is not None:
                pad.set_view(dict(mode="face" if v.get("mode") == "face" else "cube",
                                  face=v.get("face") if isinstance(v.get("face"), int) else None,
                                  waiting=[w for w in (v.get("waiting") or []) if isinstance(w, dict) and isinstance(w.get("f"), int)][:FACES]))
            self.send_response(204); self.end_headers(); return
        if u.path == "/live":                                         # the Rolodex (2026-11-17): which faces have something running
            return self.reply(200, {"live": live_faces()})
        if u.path in ("/take", "/out"): return self.handoff(u.path, q)
        try: f = int(q.get("f", ["-1"])[0]); s = shells[f] if 0 <= f < FACES else None
        except ValueError: s = None
        if s is None: return self.deny(400)
        body = self.rfile.read(self.sent)
        if u.path == "/in": s.write(body)
        elif u.path == "/start":                                      # the page shows this face now: make sure its shell runs
            if not s.alive(): s.start()
        elif u.path == "/attn":
            try: m = json.loads(body)
            except Exception: return self.deny(400)
            if not isinstance(m, dict): return self.deny(400)
            if m.get("s") in ("needs", "working"): set_attn(f, m["s"], str(m.get("r", "")))
        elif u.path == "/resize":
            c, r = int(q.get("c", ["80"])[0]), int(q.get("r", ["24"])[0])
            if 10 <= c <= 500 and 4 <= r <= 300: s.resize(r, c)
        else: return self.deny(404)
        self.send_response(204); self.end_headers()
    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def handoff(self, path, q):
        if path == "/take":                                            # body {"pid": <claude pid>, "face": 1-18 (optional)} from `tess`
            try: m = json.loads(self.rfile.read(self.sent) or b"{}")
            except Exception: return self.reply(400, {"msg": "bad request"})
            if not isinstance(m, dict): return self.reply(400, {"msg": "bad request"})
            info = claude_info(m.get("pid"))
            if not info: return self.reply(400, {"msg": "that isn't a running Claude Code session I can read"})
            for s in shells:                                           # already on a face: nothing to move
                c = program_under(s.pid, {"claude"}) if s.pid else None
                if c and c[0] == info["pid"]:
                    return self.reply(409, {"msg": f"this session is already on face {s.face + 1}"})
            with reserved_lock:
                if info["session_id"] in moving:
                    return self.reply(409, {"msg": f"this session is already moving to {moving[info['session_id']]} when its turn ends"})
            want = m.get("face")
            if want is not None:
                try: f = int(want) - 1
                except (TypeError, ValueError): return self.reply(400, {"msg": "face must be a number 1-18"})
                if not 0 <= f < FACES: return self.reply(400, {"msg": "face must be 1-18"})
                if f in web_faces(): return self.reply(409, {"msg": f"face {f + 1} is a browser: a session there could not be seen"})
                with reserved_lock:
                    s = shells[f]
                    if f in reserved or (s.alive() and not at_prompt(s)):
                        return self.reply(409, {"msg": f"face {f + 1} is busy: something is running there"})
                    reserved.add(f)
            else:
                f = free_face()
                if f is None: return self.reply(409, {"msg": "no free face: every face has something running"})
            with reserved_lock:                                        # (re-checked: a second tess may have raced in between the two locks)
                if info["session_id"] in moving:
                    reserved.discard(f); return self.reply(409, {"msg": f"this session is already moving to {moving[info['session_id']]} when its turn ends"})
                moving[info["session_id"]] = f"face {f + 1}"
            threading.Thread(target=take_worker, args=(info, f), daemon=True).start()
            st = status_of(info["pid"])
            return self.reply(200, {"face": f + 1, "msg": f"→ face {f + 1}" + ("" if st == "idle" else " as soon as this turn ends")})
        try: f = int(q.get("f", ["-1"])[0])                            # /out?f=N (0-based, from the page): that face's session → Terminal
        except ValueError: f = -1
        if not 0 <= f < FACES or not shells[f].pid: return self.reply(400, {"msg": "no session on that face"})
        c = program_under(shells[f].pid, {"claude"}); info = claude_info(c[0]) if c else None
        if not info: return self.reply(400, {"msg": f"no Claude session on face {f + 1} (Codex can't move yet)"})
        with reserved_lock:                                            # Ctrl+Option+O twice = one Terminal window, not two
            if info["session_id"] in moving: return self.reply(409, {"msg": f"face {f + 1} is already moving to {moving[info['session_id']]}"})
            moving[info["session_id"]] = "a Terminal window"
        threading.Thread(target=out_worker, args=(info, f), daemon=True).start()
        return self.reply(200, {"msg": f"face {f + 1} → a Terminal window" + ("" if status_of(info["pid"]) == "idle" else " when this turn ends")})

HANDLE = os.path.join(HOME3, "server.json")                           # how `tess` finds this run (port + key); 0600, removed on quit
def stop(*_):
    try: os.remove(HANDLE)
    except OSError: pass
    stop_and_remember()
    for s in shells:
        if s.pid and s.alive():                                        # (a shell that has already ended keeps its old number, which may be another program's by now: no signal goes there)
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
# the Lightpad (2026-11-03): optional. Loaded by path (python -I leaves this folder off sys.path); if it's missing or broken the cube
# runs exactly as before. It does nothing at all until a pad bridge answers. TDT_PAD=0 turns it off; a TDT_HOME test copy needs TDT_PAD=1.
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location("padglue", os.path.join(HERE, "padglue.py"))
    padglue = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(padglue)
    if padglue.enabled():
        pad = padglue.PadLink(send, lambda: f"http://127.0.0.1:{PORT}", log_path=os.path.join(HOME3, "pad-link.log")).start()
except Exception as e:
    pad = None; print(f"(Lightpad link off: {e!r})", flush=True)
try:
    os.makedirs(HOME3, exist_ok=True)
    fd = os.open(HANDLE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh: json.dump({"url": f"http://127.0.0.1:{PORT}", "key": KEY, "pid": os.getpid()}, fh)
    os.chmod(HANDLE, 0o600)
except OSError as e: print(f"(no server.json: {e!r})", flush=True)
print(f"Session Cube: http://127.0.0.1:{PORT}/?k={KEY}", flush=True)
httpd.serve_forever()
