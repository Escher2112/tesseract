# Controlling Tesseract with the Lightpad Block

Chris's design, 2026-11-02 ~23:22. The block becomes a **pressure-aware trackpad for the cube** — the whole thing navigated by hand, no keyboard, no Spaceball. This is a fork (`block-control` branch / `session-cube-blocktest` worktree) so nothing touches the working app.

## Why it fits cleanly
Tesseract already takes an **abstract input protocol**, not raw devices: `server.py` emits `{"k":"sb","a":"r","v":[x,y,z]}` (rotate), `{"k":"sbb","m":mask}` (buttons), `{"k":"knob","t":clicks}` events onto `/stream`, and `index.html`/`gl.js` turn those into roll / step / enter / full-screen. So the block is just **another emitter of those events** — the cube's logic doesn't change. New code adds a block-input source; the Spaceball and knob paths are untouched.

## The gesture language (Chris's words, verbatim intent)
| Gesture | Action | Cube event |
|---|---|---|
| **Wipe across** (trackpad swipe) — right→left spins it left→right | roll/spin the cube between faces | `sb` rotate (dx→yaw, dy→pitch), or `knob` turn |
| **Scroll/keep wiping** | keep rolling the ball | continued `sb` rotate |
| **Force press** | go INTO the face (zoom/enter) | enter — needs real-block pressure |
| **Release** (after a force-press-in) | come back OUT of the face | toggle out |
| **Quick lean off + tap** | bring that face forward / select | `sbb` button (select) |
| **Force press + release again** | back out of the face → return to move-around mode | toggle out |
| **Two fingers + twist** (trackpad rotate) | rotate about the axis of the face you're looking at | `sb` rotate on the view axis |

**The pressure is the Z-axis:** push in → enter, pull out → leave. That's what a normal trackpad can't do and the Lightpad can (on real hardware).

## What prototypes on the SIM now vs needs the real block
- **Sim-testable tonight:** wipe-to-spin, two-finger-twist — motion only. The iPad reports position, not force.
- **Needs the real block:** every **force-press** gesture (enter / exit). The iPad touchscreen has no pressure sensor (reports zero force). Force-click arrives with the hardware.

## Prototype wiring (this fork)
- `server.py`: add `POST /blockin?k=KEY` → maps an action (`spin` dx,dy / `select` / `enter` / `back`) to the existing `send(...)` event. No change to Spaceball/knob paths.
- `block-to-cube.py`: a glue process — reads the Lightpad sim's gestures (`bin/lightpad wait-event --sim`), maps swipes → `/blockin spin`, taps → `/blockin select`, and (on real hardware later) force-press → `/blockin enter`.
- `run-block-cube.sh`: one command — starts the forked cube on an alt port and the glue, prints the URL to open.

## Pressure sourcing — HOT-SWAP by device (Chris, 2026-11-02 23:26)
Pressure is a per-device property, auto-detected, feeding ONE unified value the gesture code consumes:
- **iPad / touchscreen connected** → derive pressure from **finger contact area** (capture `radiusX/radiusY`, calibrate to the observed min/max range — the sim page already has the "no guessed area range" logic). Small area = light, large area = force-press.
- **Real Lightpad block connected** → use the **hardware force channel** directly.
- The device declares which it is (extends the existing `SimDevice`/`RealDevice` split in roli-lightpad `bridge/`). Force-press gestures (enter/exit) read the unified value and work identically on either. Canonical home for this: roli-lightpad's pressure/calibration handling; mirrored here because the cube's force-press depends on it.
- Open check: whether iOS Safari exposes a *varying* finger radius on Chris's iPad. If yes, the full force-press language is testable with no hardware.

## Status
First pass: swipe→spin + tap→select on the sim. Force-press gestures are specced and wired on the cube side, dormant until a pressure device (the real block) feeds them. Trackpad-for-the-whole-OS (drive the macOS cursor) is a separate overlay mode needing Accessibility permission — noted, not built here.

## TODO (Chris, 2026-11-02 23:37 — "close enough for tonight")
- **Entering a face triggers too easily.** A left/right wipe meant to step faces has a small vertical component, so `dy>0 → enter` fires by accident. Fix: require a much stronger vertical-vs-horizontal ratio before enter/back (or gate enter behind force-press only), and add a horizontal deadzone so a clean side-wipe never reads as vertical.
- **Do the force-touch properly** via the contact-area → pressure hot-swap (see "Pressure sourcing" above): force-press = enter, release = back out. That's the right model; the swipe-direction hack for enter/exit is a placeholder. Needs the radiusX/radiusY capture wired into the sim page + the iOS-exposes-varying-radius check.
- Status tonight: swipe → step faces works ("close enough, not right"). enter/exit needs the two fixes above.
