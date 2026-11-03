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

## ✓ 2026-11-03 (Lyra, walking Riven's list with Chris's go): entering is deliberate now
- **The cause of "it's wanting to go into the face too easily":** `server.py` `/blockin` mapped a tap (`select`) straight to `enter`, and any vertical wipe to enter/back. A stray tap at the end of a wipe dove into a face.
- **Now:** wipes only step face to face; taps do nothing. Going **in** takes a deliberate press held a moment (Riven: "a threshold plus a short dwell"): on the real block a `press` ≥ `ENTER_PRESSURE` (0.55) held ≥ `ENTER_DWELL_S` (0.35 s); on the iPad sim, which has no pressure, one finger held still (the classifier's `rest`, ~1 s). The same deliberate press/hold comes back **out**. Logic in `decide()` in `block-to-cube.py`; rules checked by `python3 -I test_block_glue.py` (9/9).
- **Still to do:** tune `ENTER_PRESSURE` against his real hand on arrival day; the contact-area pressure hot-swap (the iPad "rest" stand-in covers the sim meanwhile).
- ⚠ This branch is **local only**: the repo (Escher2112/tesseract) is PUBLIC and these notes quote Chris; push only with his OK (or to a private remote).

## ✓ 2026-11-03 evening: calling corners + the visit tether, LIVE end to end (Chris: "i love it!")
Designed with Chris (roli-lightpad `IDEAS.md` §H). Proven live against the running iPad sim with an isolated test cube:
face 3 marked "needs you" → a magenta corner lit on the pad → a tap on it → the cube jumped into face 3 full screen and the pad
showed the white landing strip home → a tap on the white corner → back on the cube at face 1; face 3's corner returned (it still
needed him: looking never clears a face, only real progress does).
- **Page** (`index.html`): `padReport()` posts the view (cube/face + which face) and the waiting faces (with his group colours) to
  `/blockview` every 0.7 s when it changes; handlers `jump` → the cube's own `jumpTo()`, `goback` → its own `goBack()` (same history
  as the Spaceball's back).
- **Server** (`server.py`): `POST /blockview`, `GET /blockstate`, `/blockin a=jump&f=N` and `a=goback`. All behind the run's key.
- **Glue** (`block-to-cube.py`): polls `/blockstate`, writes the pad's `tesseract.json` (stable corners, max four, longest-waiting
  first; colour = his Tesseract group colour, or his lane for ungrouped faces; never white); runs the visit; routes touches by
  mode (cube: wipes step, a deliberate hold dives in; face: touches are left to that face's Lyra); hands the pad to the visited
  face's session via `bin/lightpad claim --take` when the presence hook has recorded it (`faces.json`). Rules: `python3 -I test_block_glue.py` (26/26).
- **Run the test cube** (never his real sessions): `TDT_HOME=~/.config/3d-terminal-blocktest python3 -I server.py --port 8905`,
  open the printed URL, then `KEY=<k from the URL> CUBE=http://127.0.0.1:8905 SIM_HOME=~/.lyra-lightpad-sim python3 -I block-to-cube.py`.
  `node tests/maths.test.mjs` = 176/176 (⛔ never `tests/drive.mjs` on the M32: it launches headless Chrome).
- **Open:** (1) putting this into his REAL Tesseract app is his call (this is the fork; the branch is local-only, the repo is public);
  (2) trackpad mode inside a face (three fingers, tap twice; needs the Accessibility permission he grants); (3) a pad gesture to back
  out of a face to the cube was left open (he moved to the trackpad idea instead).
