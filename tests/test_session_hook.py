#!/usr/bin/env python3
"""tests/test_session_hook.py — which folder hooks/claude-session-hook.py records for a face (Lyra 2026-11-13).
Run: python3 -I tests/test_session_hook.py      (scratch folders only; never touches the real ~/.config/3d-terminal or ~/.claude)
Why: SessionStart also fires mid-conversation (after a compaction or /clear). A face's record once named a subfolder, the folder that
session had cd'd into, while the conversation lives under the home folder; reopening it from there would not find it. The hook must record
the folder the claude STARTED in. A tiny compiled program named claude runs the hook as its child, exactly as Claude Code does."""
import json, os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="tdt-sesshook-"); HOME3, SESS = os.path.join(T, "cube"), os.path.join(T, "sessions")
os.makedirs(os.path.join(HOME3, "faces")); os.makedirs(SESS)
FAKE = os.path.join(T, "claude")                                       # runs: the hook < its input file, and waits for it
open(FAKE + ".c", "w").write('#include <stdlib.h>\nint main(int c, char **v){ return system(v[1]); }\n')
subprocess.run(["cc", "-o", FAKE, FAKE + ".c"], check=True)
fails, passes = [], 0
def ok(cond, what):
    global passes
    if cond: passes += 1; print("  ok  ", what)
    else: fails.append(what); print("  FAIL", what)
def run(face, hook_in, started_in=None):
    """Run the hook under a process named claude. started_in = the folder Claude Code's own session record says it started in."""
    inp = os.path.join(T, "in.json"); json.dump(hook_in, open(inp, "w"))
    env = dict(os.environ, SESSION_CUBE_FACE=str(face), SESSION_CUBE_HOME=HOME3, TDT_CLAUDE_SESSIONS=SESS)
    p = subprocess.Popen([FAKE, f"/usr/bin/python3 -I {os.path.join(ROOT, 'hooks', 'claude-session-hook.py')} < {inp}"], env=env)
    if started_in: json.dump({"pid": p.pid, "sessionId": hook_in["session_id"], "cwd": started_in}, open(os.path.join(SESS, f"{p.pid}.json"), "w"))
    p.wait(timeout=15)
    return json.load(open(os.path.join(HOME3, "faces", f"face-{face}.json")))
try:
    # (the session record is written just after the fake starts; the hook's python takes far longer to boot than that)
    r = run(3, {"session_id": "aaa", "cwd": "/Users/x/project/app"}, started_in="/Users/x")
    ok(r["cwd"] == "/Users/x", f"mid-conversation (cd'd into app): records the folder it STARTED in ({r['cwd']})")
    ok(r["session_id"] == "aaa" and os.path.basename(r["args"].split()[0]) == "claude", "…with its session id and its claude command")
    r = run(3, {"session_id": "aaa", "cwd": "/somewhere/else"})
    ok(r["cwd"] == "/Users/x", f"no session record: keeps the folder already on record for the SAME conversation ({r['cwd']})")
    r = run(3, {"session_id": "bbb", "cwd": "/fresh/dir"})
    ok(r["cwd"] == "/fresh/dir", f"a different conversation, no record: the hook's own folder ({r['cwd']})")
    r = run(4, {"session_id": "ccc", "cwd": "/Users/x"}, started_in="/Users/x")
    ok(r["cwd"] == "/Users/x", "a fresh start: the folder it started in")
    env = dict(os.environ); env.pop("SESSION_CUBE_FACE", None)
    subprocess.run(["/usr/bin/python3", "-I", os.path.join(ROOT, "hooks", "claude-session-hook.py")], input='{"session_id":"zzz"}', text=True, env=env)
    ok(sorted(os.listdir(os.path.join(HOME3, "faces"))) == ["face-3.json", "face-4.json"], "outside a face it writes nothing")
finally:
    shutil.rmtree(T, ignore_errors=True)
print(f"\n{passes} passed, {len(fails)} failed" + ("" if not fails else ": " + "; ".join(fails)))
sys.exit(1 if fails else 0)
