#!/usr/bin/env python3
"""tests/test_live.py — POST /live: which faces have something running (the Rolodex lists only those), 2026-11-17.
Run: python3 -I tests/test_live.py      (a throwaway server on its own port with its own TDT_HOME; never touches the real cube)"""
import json, os, re, shutil, signal, socket, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="tdt-live-"); HOME = os.path.join(T, "home"); os.makedirs(HOME)
PORT = 8798
fails, passes = [], 0
def ok(cond, what):
    global passes
    if cond: passes += 1; print("  ok  ", what)
    else: fails.append(what); print("  FAIL", what)
env = dict(os.environ, HOME=os.path.join(T, "user-home"), ZDOTDIR=os.path.join(T, "user-home"), TDT_HOME=HOME, TDT_NO_TERMINAL="1", TDT_PAD="0"); os.makedirs(env["HOME"], exist_ok=True)   # (HOME, ZDOTDIR: the shells on its faces start in a home of the test's own, so nothing a test types is saved into his shell history)
srv = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "server.py"), "--port", str(PORT), "--parent", str(os.getpid())], env=env, stdout=subprocess.PIPE, text=True)   # (--parent: a test run that is killed takes its server along)
out = {}
def reader(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data: "): continue
            m = json.loads(line[6:])
            if "o" in m and "k" not in m: out[m["f"]] = out.get(m["f"], "") + m["o"]
def wait(pred, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if pred(): return True
        time.sleep(0.1)
    return False
def post(path, data=b""):
    try: return 200, json.loads(urllib.request.urlopen(urllib.request.Request(path, data=data, method="POST")).read() or b"null")
    except urllib.error.HTTPError as e: return e.code, None
try:
    line = ""
    while "Session Cube:" not in line: line = srv.stdout.readline() or (_ for _ in ()).throw(RuntimeError("server died"))
    h = json.load(open(os.path.join(HOME, "server.json"))); U, K = h["url"], h["key"]
    threading.Thread(target=reader, args=(f"{U}/stream?k={K}",), daemon=True).start()
    ok(wait(lambda: all(f in out for f in range(6))), "the first six faces' shells started")
    time.sleep(2.5)                                                    # let the login shells settle (idle = no children)
    code, j = post(f"{U}/live?k={K}")
    ok(code == 200 and j == {"live": []}, f"six idle shells: nothing is running ({code} {j})")
    # WHAT EVERY SUITE HANDS THE SERVER IT STARTS: itself as the parent (a test run that is killed must not leave its server and its shells behind), and a
    # home of the test's own for the shells on its faces (a login shell in the home of whoever runs the test saves every line a test types into HIS shell history)
    urllib.request.urlopen(urllib.request.Request(f"{U}/in?k={K}&f=0", data=b"echo home-is=$HOME=\r", method="POST")).read()
    ok(wait(lambda: "home-is=" + os.path.join(T, "") in out.get(0, ""), 5), "the shell on a face starts in a home of this test's own, not in the home of whoever runs the test")
    mark, tests_dir, loose, homeless = 'os.path.join(ROOT, "server.py"), "--port"', os.path.dirname(os.path.abspath(__file__)), [], []
    for name in sorted(n for n in os.listdir(tests_dir) if n.startswith("test_") and n.endswith(".py")):
        rows = open(os.path.join(tests_dir, name), encoding="utf-8").read().split("\n")
        for i, row in enumerate(rows):
            if "Popen(" not in row or mark not in row: continue       # each place a suite starts a server
            if '"--parent", str(os.getpid())' not in row: loose.append("%s:%d no --parent" % (name, i + 1))
            handed = next((r for r in rows[i::-1] if r.strip().startswith("env = dict(os.environ")), "")
            if not (re.search(r"[ (]HOME=", handed) and "ZDOTDIR=" in handed): homeless.append("%s:%d" % (name, i + 1))
    ok(not loose, "every suite starts its server with itself as the parent" + ("" if not loose else " (not so: %s)" % ", ".join(loose)))
    ok(not homeless, "…and hands it a home of the test's own for its shells" + ("" if not homeless else " (not so: %s)" % ", ".join(homeless)))
    gone = subprocess.Popen([sys.executable, "-I", "-c", "pass"]); gone.wait()   # a starter that has already ended
    orphan = [sys.executable, "-I", os.path.join(ROOT, "server.py"), "--port", "8793", "--parent", str(gone.pid)]
    home2 = os.path.join(T, "home-two"); os.makedirs(home2); t0 = time.time(); s2 = subprocess.Popen(orphan, env=dict(env, TDT_HOME=home2), stdout=subprocess.DEVNULL)
    try: s2.wait(timeout=8)
    except subprocess.TimeoutExpired: s2.terminate(); s2.wait(timeout=10); t0 = 0
    ok(t0 and time.time() - t0 < 6 and not os.path.exists(os.path.join(home2, "server.json")), "a server whose starter is gone stops by itself within seconds, and takes its handle file with it")
    urllib.request.urlopen(urllib.request.Request(f"{U}/in?k={K}&f=2", data=b"sleep 30\r", method="POST")).read()
    urllib.request.urlopen(urllib.request.Request(f"{U}/in?k={K}&f=4", data=b"sleep 30\r", method="POST")).read()
    ok(wait(lambda: post(f"{U}/live?k={K}")[1] == {"live": [2, 4]}, 6), f"a program on faces 3 and 5 → exactly those ({post(f'{U}/live?k={K}')[1]})")
    urllib.request.urlopen(urllib.request.Request(f"{U}/in?k={K}&f=2", data=b"\x03", method="POST")).read()   # Ctrl+C
    ok(wait(lambda: post(f"{U}/live?k={K}")[1] == {"live": [4]}, 6), "it stops on face 3 → face 3 drops off the list")
    ok(post(f"{U}/live?k=wrong")[0] == 403, "a wrong key is refused")
    cfg = lambda: json.load(open(os.path.join(HOME, "config.json"))).get("prefs", {})
    post(f"{U}/config?k={K}&prefs=1", json.dumps({"fastSwap": True, "notASetting": 1}).encode())
    ok(wait(lambda: os.path.exists(os.path.join(HOME, "config.json")) and cfg().get("fastSwap") is True, 3), "the Fast Swap setting is saved")
    ok("notASetting" not in cfg(), "…and an unknown setting still is not")
    # THE LIST OF DOORS at the top of server.py is the one place where all of them are named: it must name every door the code answers
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read(); listed = set()
    for a, b in re.findall(r"(?:GET|POST) +(/[a-z./|]*)|· (/[a-z./]+)", src.split('"""')[1]):      # (a line of the list: GET or POST and a path)
        stem, _, last = (a or b).rpartition("/"); listed |= {stem + "/" + w for w in last.split("|")}
    doors = set(re.findall(r'u\.path [=!]= "(/[a-z./]*)"', src)) | {d for grp in re.findall(r"u\.path in \(([^)]*)\)", src) for d in re.findall(r'"(/[a-z/]+)"', grp)}
    unnamed = sorted(doors - listed)
    ok(len(doors) >= 10 and not unnamed, "the list of doors at the top of server.py names every door the code answers" + ("" if not unnamed else " (%d found in the code; not named: %s)" % (len(doors), ", ".join(unnamed))))
    # WHAT A DOOR READS: never more than it takes. A length the body does not have, or one over the door's limit, is refused: not cut short and read as something else
    HP = urlparse(U).port
    def raw(path, body=b"", length=None, hang_up=False):              # a POST written by hand, so its length can be one the body does not have → the status · 0 = the server never answered
        c = socket.create_connection(("127.0.0.1", HP), timeout=4)
        try:
            c.sendall(f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{HP}\r\nContent-Length: {len(body) if length is None else length}\r\n\r\n".encode() + body)
            if hang_up: c.shutdown(socket.SHUT_WR)
            got = c.recv(64).split()
            return int(got[1]) if len(got) > 1 and got[0].startswith(b"HTTP/") else 0
        except OSError: return 0
        finally: c.close()
    over = json.dumps({"fastSwap": "too-long", "layouts": {"pad": "x" * 70000}}).encode()      # more than /config takes (65536)
    ok(raw(f"/config?k={K}&prefs=1", over, length=-1, hang_up=True) == 400, "a length below zero is refused (it used to be read until the caller hung up, past every limit)")
    ok(raw(f"/config?k={K}&prefs=1", b"{}", length="many") == 400, "…and so is a length that is not a number")
    ok(raw(f"/config?k={K}&prefs=1", over) == 413 and raw(f"/take?k={K}", b'{"pid": 1, "pad": "' + b"x" * 5000 + b'"}') == 413, "a body longer than its door takes is refused as too long, and the caller is told so")
    ok(cfg().get("fastSwap") is True, "…and nothing of it is saved")
    ok(raw(f"/config?k={K}&prefs=1", json.dumps({"fastSwap": True}).encode()) == 204 and raw(f"/in?k={K}&f=1", b"") == 204, "a body of a size the door takes still goes through, and so does none at all")
    ok(raw(f"/config?k={K}&prefs=1", b"[1, 2]") == 400 and raw(f"/attn?k={K}&f=2", b"[1, 2]") == 400 and raw(f"/blockview?k={K}", b"[1, 2]") == 400 and raw(f"/take?k={K}", b"[1, 2]") == 400, "a list where settings, a face's state, the page's view or a hand-off is expected is refused (it used to break the request off with no answer)")
    # THE SETTINGS FILE IS NEVER LOST TO A SAVE: a read never meets a half-written file, and a file that cannot be read is set aside whole, never written over
    cpath = os.path.join(HOME, "config.json"); big = json.dumps({"layouts": {"pad": "x" * 50000}}).encode(); end = time.time() + 1.5; seen = {"whole": 0, "torn": 0}
    def saving():
        while time.time() < end: post(f"{U}/config?k={K}&prefs=1", big)
    th = threading.Thread(target=saving); th.start()
    while time.time() < end:
        try: json.load(open(cpath)); seen["whole"] += 1
        except ValueError: seen["torn"] += 1
    th.join()
    ok(seen["whole"] > 20 and not seen["torn"], "while his settings are being saved, a read of the file never meets a half-written one (%d reads, %d of them torn)" % (seen["whole"] + seen["torn"], seen["torn"]))
    broken = '{"toggle_button": 4, "codex_launchers": {"~/.codex-two": "second"}, "prefs": {"fastSwap": tr'      # a file cut off in the middle
    open(cpath, "w").write(broken); post(f"{U}/config?k={K}&prefs=1", json.dumps({"fastSwap": False}).encode())
    aside = [n for n in os.listdir(HOME) if n.startswith("config.json.unreadable-")]
    ok(len(aside) == 1 and open(os.path.join(HOME, aside[0])).read() == broken, "a settings file that cannot be read is set aside whole under another name when a save comes, never written over")
    ok(cfg() == {"fastSwap": False}, "…and that save begins a new file")
    good = open(cpath).read(); os.chmod(cpath, 0); code, _ = post(f"{U}/config?k={K}&prefs=1", json.dumps({"fastSwap": True}).encode()); os.chmod(cpath, 0o600)   # (there, but it cannot be OPENED just now)
    ok(code == 503 and open(cpath).read() == good and len([n for n in os.listdir(HOME) if n.startswith("config.json.unreadable-")]) == 1, "a settings file that could not be opened for a moment is neither set aside nor written over: that save is refused (%s), and the file is as it was" % code)
    real = os.path.join(T, "linked-settings.json"); os.replace(cpath, real); os.symlink(real, cpath); post(f"{U}/config?k={K}&prefs=1", json.dumps({"fastSwap": True}).encode())
    ok(os.path.islink(cpath) and json.load(open(real)).get("prefs") == {"fastSwap": True}, "a settings file that is a link to a file kept elsewhere stays a link: the save goes into the file it points at")
finally:
    srv.send_signal(signal.SIGTERM)
    try: srv.wait(timeout=10)
    except subprocess.TimeoutExpired: srv.kill()
    shutil.rmtree(T, ignore_errors=True)
print(f"\n{passes} passed, {len(fails)} failed" + ("" if not fails else ": " + "; ".join(fails)))
sys.exit(1 if fails else 0)
