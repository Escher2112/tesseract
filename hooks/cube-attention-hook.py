#!/usr/bin/env python3
"""cube-attention-hook.py — Claude Code hook for 3D Terminal's Attention Routing (Lyra 2026-10-28).
Only acts inside a 3D Terminal face (the cube's server sets SESSION_CUBE_FACE / _URL / _KEY); everywhere else it does nothing.
Tells the cube when this session needs a person, and when it is moving again:
  Notification (permission_prompt / elicitation_dialog / idle_prompt) → needs you · Stop → finished, your turn
  UserPromptSubmit / PostToolUse / SessionEnd → working again (the alert clears only on real progress, never on a visit).
Never answers anything, never blocks Claude: one quick local POST, every error ignored."""
import json, os, sys, urllib.request
face, url, key = os.environ.get("SESSION_CUBE_FACE"), os.environ.get("SESSION_CUBE_URL"), os.environ.get("SESSION_CUBE_KEY")
if not (face and url and key): sys.exit(0)
try: data = json.load(sys.stdin)
except Exception: sys.exit(0)
ev = data.get("hook_event_name", "")
REASONS = {"permission_prompt": "needs your approval", "elicitation_dialog": "has a question", "idle_prompt": "is waiting for you"}
if ev == "Notification":
    r = REASONS.get(data.get("notification_type", ""))
    if not r: sys.exit(0)                                   # auth_success and the like: nothing for a person to do
    msg = {"s": "needs", "r": r}
elif ev == "Stop": msg = {"s": "needs", "r": "finished: your turn"}
elif ev in ("UserPromptSubmit", "PostToolUse", "SessionEnd"): msg = {"s": "working"}
else: sys.exit(0)
try:
    req = urllib.request.Request(f"{url}/attn?k={key}&f={int(face) - 1}", data=json.dumps(msg).encode(), method="POST")
    urllib.request.urlopen(req, timeout=1).read()
except Exception: pass
