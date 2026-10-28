#!/usr/bin/env python3
"""claude-session-hook.py — Claude Code SessionStart hook for 3D Terminal (Lyra 2026-10-27).
Only acts inside a 3D Terminal face (SESSION_CUBE_FACE is set by the cube's server); everywhere else it does nothing.
Writes ~/.config/3d-terminal/faces/face-N.json = {session_id, cwd, args} so the cube can reopen that conversation on that face."""
import json, os, subprocess, sys
face = os.environ.get("SESSION_CUBE_FACE")
if not face: sys.exit(0)
try: data = json.load(sys.stdin)
except Exception: sys.exit(0)
sid = data.get("session_id")
if not sid: sys.exit(0)
args, pid = "claude", os.getppid()                      # walk up to the claude process to learn how it was started (its flags)
for _ in range(6):
    try: line = subprocess.run(["ps", "-o", "ppid=,args=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    except Exception: break
    if not line: break
    ppid, _, a = line.partition(" ")
    if os.path.basename(a.split(" ")[0]) == "claude" or " claude " in f" {a} ": args = a; break
    pid = int(ppid)
d = os.path.expanduser("~/.config/3d-terminal/faces"); os.makedirs(d, exist_ok=True)
json.dump({"session_id": sid, "cwd": data.get("cwd") or os.getcwd(), "args": args}, open(os.path.join(d, f"face-{face}.json"), "w"))
