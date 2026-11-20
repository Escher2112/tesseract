#!/usr/bin/env python3
"""tests/test_handoff.py — the HAND-OFF (tess / Ctrl+Option+O), end to end against a throwaway server (Lyra 2026-11-12).
Run: python3 -I tests/test_handoff.py      (needs nothing installed; never touches Chris's real cube, sessions or Terminal.app)

A real server.py runs on its own port with its own TDT_HOME, a scratch ~/.claude/sessions (TDT_CLAUDE_SESSIONS), no Lightpad, and
TDT_NO_TERMINAL=1 (it logs the AppleScript it would run instead of driving Terminal). The "claude" is
a tiny compiled sleeper named claude, so `ps` sees a process called claude, exactly what the server checks. Checks: tess finds the server + its claude; a busy session waits for
its turn to end; the old claude is gone BEFORE the resume is typed; the face gets `--resume <id>` from the session's own folder; the page is
told to go there; the old tab would be closed; a second tess on a busy face is refused; /out ends the face's claude and would open Terminal."""
import json, os, shutil, signal, subprocess, sys, tempfile, threading, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="tdt-handoff-"); HOME, SESS, BIN = (os.path.join(T, d) for d in ("home", "sessions", "bin"))
for d in (HOME, SESS, BIN): os.makedirs(d)
FAKE = os.path.join(BIN, "claude")                                    # a copied /bin/sleep is killed by macOS (platform binary): compile one
# (it sleeps for its first word if that is a number, else 300 s: started with other words, as a session started with options or a prompt, it stays up too)
open(os.path.join(BIN, "fake.c"), "w").write('#include <unistd.h>\n#include <stdlib.h>\nint main(int c, char **v){ sleep(c > 1 && atoi(v[1]) > 0 ? atoi(v[1]) : 300); return 0; }\n')
subprocess.run(["cc", "-o", FAKE, os.path.join(BIN, "fake.c")], check=True)
PORT = 8797
fails, passes = [], 0
def ok(cond, what):
    global passes
    if cond: passes += 1; print("  ok  ", what)
    else: fails.append(what); print("  FAIL", what)

env = dict(os.environ, HOME=os.path.join(T, "user-home"), ZDOTDIR=os.path.join(T, "user-home"), TDT_HOME=HOME, TDT_CLAUDE_SESSIONS=SESS, TDT_NO_TERMINAL="1", TDT_PAD="0"); os.makedirs(env["HOME"], exist_ok=True)   # (HOME, ZDOTDIR: the shells on its faces start in a home of the test's own, so nothing a test types is saved into his shell history)
REAL = os.path.realpath(T)                                             # (the folder as a program that is IN it names it: /private/var/…, not /var/…)
srv = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "server.py"), "--port", str(PORT), "--parent", str(os.getpid())], env=env, stdout=subprocess.PIPE, text=True)   # (--parent: a test run that is killed takes its server along)
msgs, out = [], {}
def reader(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data: "): continue
            m = json.loads(line[6:]); msgs.append(m)
            if "o" in m and "k" not in m: out[m["f"]] = out.get(m["f"], "") + m["o"]
def wait(pred, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if pred(): return True
        time.sleep(0.1)
    return False
def alive(p): return p.poll() is None                                  # our own child: poll() reaps it, so no zombie fools us
def fake_claude(status, sid, cwd):
    p = subprocess.Popen([FAKE, "300"]); json.dump({"pid": p.pid, "sessionId": sid, "cwd": cwd, "name": "fake-" + sid[:4], "status": status},
                                                  open(os.path.join(SESS, f"{p.pid}.json"), "w")); return p
def set_status(p, st):
    f = os.path.join(SESS, f"{p.pid}.json"); j = json.load(open(f)); j["status"] = st; json.dump(j, open(f, "w"))
def log(): return open(os.path.join(HOME, "handoff.log")).read() if os.path.exists(os.path.join(HOME, "handoff.log")) else ""
def tess(*args, claude_pid):
    e = dict(env, CLAUDE_PID=str(claude_pid)); e.pop("SESSION_CUBE_FACE", None)
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tess"), *args], env=e, capture_output=True, text=True, timeout=15)
    return r.returncode, r.stdout.strip()
try:
    line = ""
    while "Session Cube:" not in line: line = srv.stdout.readline() or (_ for _ in ()).throw(RuntimeError("server died"))   # skip "no hidapi"…
    h = json.load(open(os.path.join(HOME, "server.json")))
    ok(oct(os.stat(os.path.join(HOME, "server.json")).st_mode & 0o777) == "0o600", "server.json is private (0600)")
    ok(h["url"].endswith(str(PORT)) and h["key"] in line, "server.json carries this run's url + key")
    threading.Thread(target=reader, args=(f"{h['url']}/stream?k={h['key']}",), daemon=True).start()
    ok(wait(lambda: all(f in out for f in range(6))), "the first six faces' shells started")
    for f in range(18):                                                # wide terminals, so a long command line isn't wrapped by zsh (every face: one that starts later keeps the size it was given)
        urllib.request.urlopen(urllib.request.Request(f"{h['url']}/resize?k={h['key']}&f={f}&c=400&r=40", data=b"", method="POST")).read()
    time.sleep(2.5)                                                    # let the login shells settle (idle = no children)

    # 1) tess while the session is mid-turn: it waits, then moves
    a = fake_claude("busy", "aaaa1111-0000-0000-0000-000000000000", T)
    code, said = tess(claude_pid=a.pid)
    ok(code == 0 and "face 1" in said and "turn ends" in said, f"tess picks face 1 and says it waits for the turn ({said!r})")
    time.sleep(1.5)
    ok(alive(a), "a busy session is NOT ended")
    code3, said3 = tess(claude_pid=a.pid)                              # 2026-11-12 09:43 live: tess twice → the same session on TWO faces
    ok(code3 == 1 and "already moving to face 1" in said3, f"tess again on a session already moving is refused ({said3!r})")
    ok(any(m.get("k") == "note" and "finishes this turn" in m.get("t", "") for m in msgs), "the page is told it will move after this turn")
    code2, said2 = tess("1", claude_pid=fake_claude("idle", "bbbb2222-0000-0000-0000-000000000000", T).pid)
    ok(code2 == 1 and "busy" in said2, f"a second tess onto the promised face is refused ({said2!r})")
    set_status(a, "idle")
    ok(wait(lambda: not alive(a), 8), "once idle, the old claude is ended")
    ok(wait(lambda: "--resume aaaa1111-0000-0000-0000-000000000000" in out.get(0, ""), 8), "face 1 got the resume command")
    ok(f"cd {T}" in out.get(0, ""), "…from the session's own folder")
    ok(wait(lambda: any(m.get("k") == "arrive" and m.get("f") == 0 for m in msgs), 5), "the page is told to go to face 1")
    ok("take aaaa1111" in log(), "handoff.log records the move")
    a.wait(timeout=5)

    # 2) tess with a face number, idle session: moves at once to that face
    c = fake_claude("idle", "cccc3333-0000-0000-0000-000000000000", T)
    code, said = tess("3", claude_pid=c.pid)
    ok(code == 0 and "face 3" in said, f"tess 3 → face 3 ({said!r})")
    ok(wait(lambda: "--resume cccc3333" in out.get(2, ""), 8) and not alive(c), "face 3 resumed it; the old one is gone")
    ok("close tab" not in log(), "no Terminal tab to close (a test process has no tty): nothing is touched")
    c.wait(timeout=5)

    # 3) /out: a claude running ON face 5 goes to a Terminal window
    e_line = f"{FAKE} 300\r"
    req = urllib.request.Request(f"{h['url']}/in?k={h['key']}&f=4", data=e_line.encode(), method="POST"); urllib.request.urlopen(req).read()
    def face5_claude():
        rows = subprocess.run(["ps", "-A", "-o", "pid=,command="], capture_output=True, text=True).stdout.split("\n")
        return next((int(r.split()[0]) for r in rows if r.strip().endswith(f"{FAKE} 300") and r.split()[0].isdigit()), None)
    ok(wait(lambda: face5_claude() is not None, 6), "a claude is running on face 5")
    # give every running fake a session record (only face 5's is found under a face shell, which is what /out looks for)
    rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True).stdout.split("\n")
    fakes = [int(r.split()[0]) for r in rows if r.strip().endswith(f"{FAKE} 300")]
    for pid in fakes: json.dump({"pid": pid, "sessionId": "eeee5555-0000-0000-0000-000000000000", "cwd": T, "name": "face5", "status": "idle"},
                                open(os.path.join(SESS, f"{pid}.json"), "w"))
    req = urllib.request.Request(f"{h['url']}/out?k={h['key']}&f=4", data=b"", method="POST")
    try: j = json.loads(urllib.request.urlopen(req).read()); oc = 200
    except urllib.error.HTTPError as e: j = json.loads(e.read()); oc = e.code
    ok(oc == 200 and "Terminal" in j.get("msg", ""), f"/out accepted ({j.get('msg')!r})")
    req = urllib.request.Request(f"{h['url']}/out?k={h['key']}&f=4", data=b"", method="POST")   # pressed twice: still ONE window
    try: urllib.request.urlopen(req).read(); oc2 = 200
    except urllib.error.HTTPError as e: oc2 = e.code
    ok(oc2 == 409, "Ctrl+Option+O twice opens one Terminal window, not two")
    ok(wait(lambda: any(m.get("k") == "left" and m.get("f") == 4 for m in msgs), 8), "the page is told face 5's session left")
    ok(wait(lambda: "out eeee5555" in log(), 5) and "--resume eeee5555" in log(), "it would open Terminal with the resume command (logged)")
    ok(log().count("out eeee5555") == 1, "…exactly once")
    ok(log().count("take aaaa1111") == 1, "the session that was tess'd twice landed on exactly one face")

    # 3b) WHAT IS TYPED TO REOPEN A SESSION: its OPTIONS, never a bare word it was started with (a prompt would be sent a second time). A command
    # line comes back from the system as plain words, its quotes gone. Each line below is started on face 5 as a session and moved out (/out);
    # the log holds the line that would be typed to reopen it.
    live = lambda: json.loads(urllib.request.urlopen(urllib.request.Request(f"{h['url']}/live?k={h['key']}", data=b"", method="POST")).read()).get("live") or []
    ok(wait(lambda: 4 not in live(), 8), "(face 5 is at its prompt again)")
    def typed_again(words, n):                                         # → the options that are typed again for a session that was started with these words after its name
        sid = "%02d%02d%02d%02d-0000-0000-0000-000000000000" % (n, n, n, n); mark = "out %s from face 5: " % sid
        def pid():
            rows = subprocess.run(["ps", "-A", "-o", "pid=,command="], capture_output=True, text=True).stdout.split("\n")
            return next((int(r.split()[0]) for r in rows if r.strip().endswith(f"{FAKE} {words}") and r.split()[0].isdigit()), None)
        urllib.request.urlopen(urllib.request.Request(f"{h['url']}/in?k={h['key']}&f=4", data=f"{FAKE} {words}\r".encode(), method="POST")).read()
        if not wait(lambda: pid() is not None, 6): return "(it did not start)"
        json.dump({"pid": pid(), "sessionId": sid, "cwd": REAL, "name": "line-%d" % n, "status": "idle"}, open(os.path.join(SESS, f"{pid()}.json"), "w"))
        try: urllib.request.urlopen(urllib.request.Request(f"{h['url']}/out?k={h['key']}&f=4", data=b"", method="POST")).read()
        except urllib.error.HTTPError as e: return "(not moved: %s)" % e.code
        if not wait(lambda: mark in log() and pid() is None, 8): return "(it was not moved)"
        line = log().split(mark)[1].split("\n")[0]
        return line.split(f"{FAKE}", 1)[1].rsplit("--resume", 1)[0].strip() if line.startswith(f"cd {REAL} && {FAKE}") and line.endswith(f"--resume {sid}") else "(another line: %s)" % line
    for n, (words, want, why) in enumerate((
            ("deploy it", "", "a bare word it was started with is not typed again (the prompt would be sent a second time)"),
            ("--model opus fix the bug", "--model opus", "an option with one plain value keeps it; the prompt after it is not typed"),
            ("--resume 1234 --session-id 5678 --fork-session --model opus", "--model opus", "its old --resume, --session-id and --fork-session are not typed (the conversation is named by us)"),
            # …and never a word from INSIDE a prompt or a text: a word of a prompt that begins with a dash looks like an option
            ("never run with --dangerously-skip-permissions please", "", "an option named inside a prompt is not typed (this one would have switched the permission questions off)"),
            ("--append-system-prompt you may switch with --permission-mode bypassPermissions when asked", "", "nor one named inside a system prompt's text"),
            ("do these: - first thing - second thing", "", "nor the dashes of a list in a prompt"),
            ("--model opus -- fix the bug", "--model opus", "the end-of-options mark is not typed (after it, our --resume would be read as a prompt), and what stood before it stays"),
            ("--max-turns 5", "", "an option this app does not know is not typed without the word that followed it (it would take our --resume as its value)"),
            ("-n acme build --model opus", "-n acme", "after the first bare word nothing more is typed: it could all be the prompt"),
            ("--dangerously-skip-permissions --model opus fix it", "--dangerously-skip-permissions --model opus", "and the options he did start it with, standing before any other word, are all typed again")), 1):
        got = typed_again(words, n)
        ok(got == want, "reopening `claude %s`: %s (typed again: %r)" % (words, why, got))
    # a face's record that names no folder (written by hand, or damaged): the session is reopened from his home folder
    import re as _re
    flat = lambda f: _re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[=>]|\s", "", out.get(f, ""))   # a face's screen as one run of characters (a narrow terminal wraps a long command line in the middle of a word)
    os.makedirs(os.path.join(HOME, "faces"), exist_ok=True); home = "".join(env["HOME"].split())   # (the home its shells were handed: the server runs in a home of the test's own)
    json.dump({"active": True, "session_id": "09090909-0000-0000-0000-000000000000", "args": FAKE}, open(os.path.join(HOME, "faces", "face-17.json"), "w"))
    json.dump({"kind": "codex", "active": True, "session_id": "0a0a0a0a-0000-0000-0000-000000000000", "launcher": FAKE}, open(os.path.join(HOME, "faces", "face-18.json"), "w"))
    for f in (16, 17): urllib.request.urlopen(urllib.request.Request(f"{h['url']}/start?k={h['key']}&f={f}", data=b"", method="POST")).read()   # (those two faces are shown for the first time: their sessions come back)
    ok(wait(lambda: "--resume09090909" in flat(16) and "resume0a0a0a0a" in flat(17), 10) and all(("cd" + home + "&&") in flat(f) and "cd'~'" not in flat(f) for f in (16, 17)), "a face's record without a folder (a Claude Code one, and a Codex one): its session is reopened from his home folder, not from a quoted ~, which no shell can go to")

    # 4) refusals
    req = urllib.request.Request(f"{h['url']}/take?k={h['key']}", data=json.dumps({"pid": os.getpid()}).encode(), method="POST")
    try: urllib.request.urlopen(req); rc = 200
    except urllib.error.HTTPError as e: rc = e.code
    ok(rc == 400, "a process that isn't claude is refused")
    # A FACE THAT IS NOT A SHELL AT ITS PROMPT. (a) Something is half-typed there (here: a quote left open): it is dropped first, never run together
    # with the line that reopens the session. (b) Its shell was REPLACED by a program (exec): what is typed there goes to that program, so it is not free.
    def face_in(f, data=b"", door="/in"): urllib.request.urlopen(urllib.request.Request(f"{h['url']}{door}?k={h['key']}&f={f}", data=data, method="POST")).read()
    for f in (12, 13, 14): face_in(f, door="/start")
    time.sleep(2.5)                                                    # (faces 13, 14 and 15: their shells settle)
    face_in(12, b'echo "half-typed')
    ok(wait(lambda: 'echo "half-typed' in out.get(12, ""), 5), "(something is half-typed on face 13, with a quote left open)")
    resumed = lambda sid: any(r.strip().endswith(f"--resume {sid}") for r in subprocess.run(["ps", "-A", "-o", "command="], capture_output=True, text=True).stdout.split("\n"))
    d = fake_claude("idle", "dddd4444-0000-0000-0000-000000000000", T); code, said = tess("13", claude_pid=d.pid)
    ok(code == 0 and wait(lambda: not alive(d), 8) and wait(lambda: resumed("dddd4444-0000-0000-0000-000000000000"), 8), f"tess 13 onto a face with something half-typed at its prompt: that is dropped first, and the session really comes up there ({said!r})")
    d.wait(timeout=5)
    swapped = lambda: len([r for r in subprocess.run(["ps", "-A", "-o", "ppid=,command="], capture_output=True, text=True).stdout.split("\n") if r.split()[:1] == [str(srv.pid)] and r.strip().endswith("sleep 300")])
    face_in(13, b"exec sleep 300\r"); ok(wait(lambda: swapped() == 1, 6), "(the shell of face 14 is replaced by another program)")
    e = fake_claude("idle", "eeee6666-0000-0000-0000-000000000000", T); code, said = tess("14", claude_pid=e.pid)
    ok(code == 1 and "busy" in said and not wait(lambda: not alive(e), 2), f"tess 14 onto a face whose shell was replaced by a program is refused, and the session is not ended ({said!r})")
    e.kill(); e.wait(timeout=5)
    g = fake_claude("busy", "abab7777-0000-0000-0000-000000000000", T); code, said = tess("15", claude_pid=g.pid)   # the same, when it happens WHILE a session waits for its turn to end
    face_in(14, b"exec sleep 300\r"); ok(code == 0 and wait(lambda: swapped() == 2, 6), "(a session is promised face 15; then that face's shell is replaced by another program)")
    set_status(g, "idle")
    ok(wait(lambda: "take abab7777" in log(), 12) and "take abab7777-0000-0000-0000-000000000000 → face 15:" not in log(), "…the face is looked at again before anything is typed: the session goes to another face, not into that program")
    g.wait(timeout=5)
    # (c) A face he has made a BROWSER: its shell is there, but nobody can see it. A session is not put under it.
    def browsers(v): urllib.request.urlopen(urllib.request.Request(f"{h['url']}/config?k={h['key']}&prefs=1", data=json.dumps({"web": v}).encode(), method="POST")).read()
    browsers({str(i): "https://example.invalid/" for i in range(18)}); b0 = fake_claude("idle", "b0b0b0b0-0000-0000-0000-000000000000", T); code, said = tess(claude_pid=b0.pid)
    ok(code == 1 and "no free face" in said and not wait(lambda: not alive(b0), 2), f"every face a browser: a session sent to any free face is put under none of them, and it is not ended ({said!r})")
    browsers({}); b0.kill(); b0.wait(timeout=5)
    browsers({"15": "https://example.invalid/"}); b = fake_claude("idle", "bcbc8888-0000-0000-0000-000000000000", T); code, said = tess("16", claude_pid=b.pid)
    ok(code == 1 and "browser" in said and not wait(lambda: not alive(b), 2), f"tess 16 onto a face he has made a browser is refused, and the session is not ended ({said!r})")
    browsers({}); b.kill(); b.wait(timeout=5)
    face_in(11, door="/start"); time.sleep(2.5)                        # (face 12 is at its prompt)
    b2 = fake_claude("busy", "cdcd9999-0000-0000-0000-000000000000", T); code, said = tess("12", claude_pid=b2.pid); browsers({"11": "https://example.invalid/"}); set_status(b2, "idle")
    ok(code == 0 and wait(lambda: "take cdcd9999" in log(), 12) and "take cdcd9999-0000-0000-0000-000000000000 → face 12:" not in log(), "…and a face he makes a browser WHILE a session waits for it is not used either: the session goes to another face")
    browsers({}); b2.wait(timeout=5)
    # (d) A FACE STAYS PROMISED UNTIL ITS SESSION HAS HAD TIME TO COME UP THERE. On a copy whose shells are slow to reach their prompt (a start-up
    # file that keeps the shell busy for a few seconds, with no program running in it), two sessions sent in one after the other must not land on one face.
    if os.path.exists("/bin/zsh"):
        ZD, SESS4, HOME4 = os.path.join(T, "slow-zsh"), os.path.join(T, "sessions4"), os.path.join(T, "home4")
        for dd in (ZD, SESS4, HOME4): os.makedirs(dd)
        open(os.path.join(ZD, ".zshenv"), "w").write("while (( SECONDS < 5 )); do :; done\n")
        env4 = dict(env, TDT_HOME=HOME4, TDT_CLAUDE_SESSIONS=SESS4, SHELL="/bin/zsh", ZDOTDIR=ZD)
        srv4 = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "server.py"), "--port", str(PORT + 2), "--parent", str(os.getpid())], env=env4, stdout=subprocess.PIPE, text=True)
        two = []
        try:
            line = ""
            while "Session Cube:" not in line: line = srv4.stdout.readline() or (_ for _ in ()).throw(RuntimeError("the fourth server died"))
            h4 = json.load(open(os.path.join(HOME4, "server.json")))
            log4 = lambda: open(os.path.join(HOME4, "handoff.log")).read() if os.path.exists(os.path.join(HOME4, "handoff.log")) else ""
            for sid in ("0a0a0a0a-0000-0000-0000-000000000000", "0b0b0b0b-0000-0000-0000-000000000000"):
                q = subprocess.Popen([FAKE, "300"]); two.append(q); json.dump({"pid": q.pid, "sessionId": sid, "cwd": REAL, "name": "slow-" + sid[:2], "status": "idle"}, open(os.path.join(SESS4, f"{q.pid}.json"), "w"))
                urllib.request.urlopen(urllib.request.Request(f"{h4['url']}/take?k={h4['key']}", data=json.dumps({"pid": q.pid}).encode(), method="POST")).read()
                ok(wait(lambda: ("take " + sid) in log4(), 10), "(on a copy with slow shells, session %s is ended and its reopening line typed on a face)" % sid[:4])
            went = [l.split("\u2192 face ")[1].split(":")[0] for l in log4().split("\n") if " take 0" in l and "\u2192 face " in l]
            ok(len(went) == 2 and went[0] != went[1], "…and the second does not land on the face the first was just sent to (faces %r)" % went)
        finally:
            srv4.send_signal(signal.SIGTERM)
            try: srv4.wait(timeout=10)
            except subprocess.TimeoutExpired: srv4.kill()
            for q in two: q.kill(); q.wait(timeout=5)
    # A TEST COPY THAT WAS HANDED NO PRETEND SESSIONS FOLDER (a home of its own, TDT_HOME, and nothing else: how every other suite starts its server).
    # The sessions folder of the home it runs in holds the record of a live session. The copy must not find it by its number, and must end nothing.
    HIS, HOME2 = os.path.join(T, "his-home"), os.path.join(T, "home2"); os.makedirs(os.path.join(HIS, ".claude", "sessions")); os.makedirs(HOME2)
    his = subprocess.Popen([FAKE, "300"]); json.dump({"pid": his.pid, "sessionId": "9e9e9e9e-0000-0000-0000-000000000000", "cwd": REAL, "name": "his-own", "status": "idle"}, open(os.path.join(HIS, ".claude", "sessions", f"{his.pid}.json"), "w"))
    env2 = dict(env, HOME=HIS, TDT_HOME=HOME2); env2.pop("TDT_CLAUDE_SESSIONS")
    srv2 = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "server.py"), "--port", str(PORT + 1), "--parent", str(os.getpid())], env=env2, stdout=subprocess.PIPE, text=True)
    try:
        line = ""
        while "Session Cube:" not in line: line = srv2.stdout.readline() or (_ for _ in ()).throw(RuntimeError("the second server died"))
        h2 = json.load(open(os.path.join(HOME2, "server.json")))
        def take2(body):
            req = urllib.request.Request(f"{h2['url']}/take?k={h2['key']}", data=json.dumps(body).encode(), method="POST")
            try: return 200, json.loads(urllib.request.urlopen(req).read())
            except urllib.error.HTTPError as e: return e.code, {}
        rc2, _ = take2({"pid": his.pid})
        ok(rc2 == 400, "a test copy without a pretend sessions folder, handed the number of a live session of the home it runs in: refused, its record is never read (%r)" % rc2)
        ok(not wait(lambda: not alive(his), 4), "…and that session is still running: a test copy ends nothing it was not handed in a pretend folder")
        ok(not os.path.exists(os.path.join(HOME2, "handoff.log")) or "take 9e9e9e9e" not in open(os.path.join(HOME2, "handoff.log")).read(), "…and nothing was typed on a face of the copy to reopen it")
    finally:
        srv2.send_signal(signal.SIGTERM)
        try: srv2.wait(timeout=10)
        except subprocess.TimeoutExpired: srv2.kill()
        his.kill(); his.wait(timeout=5)
    # Pretend sessions on a terminal of their own: each is started by a small program that takes a terminal (a pty) the way a terminal window does.
    import pty as _pty
    open(os.path.join(BIN, "onterm.c"), "w").write(r"""#include <unistd.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
int main(int c, char **v){ if (c < 2) return 2;
  setsid(); ioctl(0, TIOCSCTTY, 0);
  pid_t p = fork(); if (!p){ execv(v[1], v + 1); _exit(127); }
  printf("%d\n", (int)p); fflush(stdout); int st; waitpid(p, &st, 0); return 0; }
""")
    subprocess.run(["cc", "-o", os.path.join(BIN, "onterm"), os.path.join(BIN, "onterm.c")], check=True)
    held = []                                                          # (each pty's own end stays open, or its session would be hung up)
    # A THIRD COPY, started through a few lines that note every signal it sends (one "number signal" line each) and then run server.py as it is.
    SESS3, HOME_3 = os.path.join(T, "sessions3"), os.path.join(T, "home3"); os.makedirs(SESS3); os.makedirs(HOME_3)
    BIN3, NO_PS = os.path.join(T, "bin3"), os.path.join(T, "no-ps"); os.makedirs(BIN3)   # this copy's `ps` is the real one, except while the file NO_PS exists: then it fails, as when the system cannot start a program for a moment
    open(os.path.join(BIN3, "ps"), "w").write('#!/bin/sh\n[ -e "%s" ] && exit 1\nexec /bin/ps "$@"\n' % NO_PS); os.chmod(os.path.join(BIN3, "ps"), 0o755)
    env3 = dict(env, TDT_HOME=HOME_3, TDT_CLAUDE_SESSIONS=SESS3, PATH=BIN3 + os.pathsep + env.get("PATH", "/usr/bin:/bin"))
    env3.pop("TDT_NO_TERMINAL"); OSA = os.path.join(T, "osascript-was-run")   # this copy is NOT told to keep its hands off Terminal (a test that forgot to say so). Its `osascript` is a pretend one that only notes it was run
    open(os.path.join(BIN3, "osascript"), "w").write('#!/bin/sh\necho "$@" >> "%s"\necho ran\n' % OSA); os.chmod(os.path.join(BIN3, "osascript"), 0o755)
    if shutil.which("osascript", path=env3["PATH"]) != os.path.join(BIN3, "osascript"): raise RuntimeError("the pretend osascript is not the first one on the path: not started")
    KILLS = os.path.join(T, "signals3"); open(KILLS, "w").close()
    NOTED = "import os, runpy, sys\npath, out = sys.argv[1], sys.argv[2]; real = os.kill\ndef kill(pid, sig):\n    with open(out, 'a') as f: f.write('%d %d\\n' % (pid, sig))\n    return real(pid, sig)\nos.kill = kill; sys.argv = [path] + sys.argv[3:]\nrunpy.run_path(path, run_name='__main__')\n"
    srv3 = subprocess.Popen([sys.executable, "-I", "-c", NOTED, os.path.join(ROOT, "server.py"), KILLS, "--port", str(PORT + 1), "--parent", str(os.getpid())], env=env3, stdout=subprocess.PIPE, text=True)
    try:
        line = ""
        while "Session Cube:" not in line: line = srv3.stdout.readline() or (_ for _ in ()).throw(RuntimeError("the third server died"))
        h3 = json.load(open(os.path.join(HOME_3, "server.json")))
        tty_of = lambda pid: subprocess.run(["ps", "-o", "tty=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        log3 = lambda: open(os.path.join(HOME_3, "handoff.log")).read() if os.path.exists(os.path.join(HOME_3, "handoff.log")) else ""
        post3 = lambda path, body: json.loads(urllib.request.urlopen(urllib.request.Request(f"{h3['url']}{path}?k={h3['key']}", data=json.dumps(body).encode(), method="POST")).read())
        def sent(): return [(int(l.split()[0]), int(l.split()[1])) for l in open(KILLS).read().split("\n") if len(l.split()) == 2]
        def start_face(f):                                             # start that face's shell → its process number (the copy tells a new shell its window size with a signal: that is how its number is known here)
            n = len([1 for _, sg in sent() if sg == signal.SIGWINCH])
            urllib.request.urlopen(urllib.request.Request(f"{h3['url']}/start?k={h3['key']}&f={f}", data=b"", method="POST")).read()
            wait(lambda: len([1 for _, sg in sent() if sg == signal.SIGWINCH]) > n, 5)
            return [q for q, sg in sent() if sg == signal.SIGWINCH][-1]
        # THE SYSTEM CANNOT BE ASKED FOR A MOMENT (`ps` fails) while a session that is still in its turn waits to move. It must not be taken for
        # gone: its conversation would be opened on a face while the old one is still at work in its window (two programs writing one conversation).
        busy = subprocess.Popen([FAKE, "300"]); r5 = os.path.join(SESS3, f"{busy.pid}.json")
        j5 = {"pid": busy.pid, "sessionId": "d5d5d5d5-0000-0000-0000-000000000000", "cwd": REAL, "name": "in-a-turn", "status": "busy"}; json.dump(j5, open(r5, "w"))
        said5 = post3("/take", {"pid": busy.pid}).get("msg", "")
        time.sleep(1.2); open(NO_PS, "w").close(); time.sleep(1.6); os.remove(NO_PS)
        ok("turn ends" in said5 and not wait(lambda: "take d5d5d5d5" in log3(), 4) and alive(busy), "while the system cannot be asked, a session still in its turn is not taken for gone: nothing is typed to reopen it, and it runs on")
        j5["status"] = "idle"; json.dump(j5, open(r5, "w"))
        ok(wait(lambda: not alive(busy), 8) and wait(lambda: "take d5d5d5d5" in log3(), 8), "…and when its turn is over it is ended and moves, as always")
        def on_term(sid, name, status="idle"):                         # a pretend session on a terminal of its own → its process number
            m, sl = _pty.openpty(); p = subprocess.Popen([os.path.join(BIN, "onterm"), FAKE, "300"], stdin=sl, stdout=subprocess.PIPE, start_new_session=True); os.close(sl)
            pid = int(p.stdout.readline()); held.append((m, p, pid))
            json.dump({"pid": pid, "sessionId": sid, "cwd": REAL, "name": name, "status": status}, open(os.path.join(SESS3, f"{pid}.json"), "w")); return pid
        # A SESSION THAT ENDED BY ITSELF while it waited to move (he closed it). This hand-off did not end it, so its old Terminal tab is his
        # shell again by now: nothing is typed there ("exit" would close a tab he is working in). A tab whose session the hand-off ended is closed.
        t_plain = on_term("d1d1d1d1-0000-0000-0000-000000000000", "on-a-terminal"); tty1 = tty_of(t_plain)
        post3("/take", {"pid": t_plain})
        ok(wait(lambda: tty_of(t_plain) == "", 8) and wait(lambda: "take d1d1d1d1" in log3(), 8), "(a session on a terminal of its own is ended and its conversation reopened on a face)")
        t_left = on_term("d7d7d7d7-0000-0000-0000-000000000000", "he-closed-it", "busy"); tty7 = tty_of(t_left)
        post3("/take", {"pid": t_left}); time.sleep(1.2); os.kill(t_left, signal.SIGKILL)
        ok(wait(lambda: "take d7d7d7d7" in log3(), 8), "(a session that waits to move is ended by something else: its conversation is still reopened on a face)")
        time.sleep(1.5)
        ok(tty1 not in ("", "??") and ("close tab /dev/" + tty1 + ":") in log3(), "the old Terminal tab of a session the hand-off itself ended would be closed (logged, with its terminal's name)")
        ok(tty7 not in ("", "??") and ("close tab /dev/" + tty7 + ":") not in log3(), "…but nothing is typed into the tab of a session that ended by itself while it waited: this hand-off did not end it")
        ok(not os.path.exists(OSA) and "would run AppleScript" in log3(), "a test copy (a home of its own) never drives Terminal, even when the test did not tell it to keep off: what it would have run is only written down")
        # a face whose shell was replaced by a program (exec) is never picked as a free face
        swap_sh = start_face(5)
        urllib.request.urlopen(urllib.request.Request(f"{h3['url']}/in?k={h3['key']}&f=5", data=b"exec sleep 300\r", method="POST")).read()
        comm_of = lambda pid: os.path.basename(subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True).stdout.strip())
        ok(wait(lambda: comm_of(swap_sh) == "sleep", 8), "(on this copy, face 6 is the only face with a running shell and nothing running in it; then its shell is replaced by another program)")
        anyf = subprocess.Popen([FAKE, "300"]); json.dump({"pid": anyf.pid, "sessionId": "d6d6d6d6-0000-0000-0000-000000000000", "cwd": REAL, "name": "to-any-face", "status": "idle"}, open(os.path.join(SESS3, f"{anyf.pid}.json"), "w"))
        j6 = post3("/take", {"pid": anyf.pid})
        ok(j6.get("face") not in (None, 6) and wait(lambda: "take d6d6d6d6" in log3(), 8) and "take d6d6d6d6-0000-0000-0000-000000000000 → face 6:" not in log3(), "a session sent to any free face does not go to the face whose shell was replaced by a program (%r)" % j6.get("msg"))
        # QUIT. A face whose shell has ended keeps that shell's old process number, and by quitting time that number can belong to another
        # program. So at quit the hang-up signal goes to the shells that are still running, and to no other number.
        gone_sh, live_sh = start_face(16), start_face(17)
        urllib.request.urlopen(urllib.request.Request(f"{h3['url']}/in?k={h3['key']}&f=16", data=b"exit\r", method="POST")).read()
        ok(gone_sh != live_sh and wait(lambda: tty_of(gone_sh) == "", 10) and tty_of(live_sh) != "", "(two faces: the shell of one is ended by typing exit there, the other's keeps running)")
        time.sleep(0.5); srv3.send_signal(signal.SIGTERM); srv3.wait(timeout=10)
        hups = [q for q, sg in sent() if sg == signal.SIGHUP]
        ok(live_sh in hups, "at quit, the shell still running on a face is hung up")
        ok(gone_sh not in hups, "…and no signal goes to the number of the shell that had already ended")
    finally:
        if srv3.poll() is None:
            srv3.send_signal(signal.SIGTERM)
            try: srv3.wait(timeout=10)
            except subprocess.TimeoutExpired: srv3.kill()
        for m, p, pid in held:                                         # (each pretend session's own starter is stopped and its terminal closed, which hangs the session up: never a signal to a bare number that may have been handed out again)
            os.close(m); p.kill(); p.wait(timeout=5)
    req = urllib.request.Request(f"{h['url']}/take?k=wrong", data=b"{}", method="POST")
    try: urllib.request.urlopen(req); rc = 200
    except urllib.error.HTTPError as e: rc = e.code
    ok(rc == 403, "a wrong key is refused")
finally:
    srv.send_signal(signal.SIGTERM)
    try: srv.wait(timeout=10)
    except subprocess.TimeoutExpired: srv.kill()
    ok(not os.path.exists(os.path.join(HOME, "server.json")), "server.json is removed on quit")
    subprocess.run(["pkill", "-f", FAKE])
    shutil.rmtree(T, ignore_errors=True)
print(f"\n{passes} passed, {len(fails)} failed" + ("" if not fails else ": " + "; ".join(fails)))
sys.exit(1 if fails else 0)
