# 3D Terminal

Six live terminals on the faces of a cube. Roll the cube with a **3Dconnexion Spaceball / SpaceMouse**, a **Griffin PowerMate** knob,
or the keyboard; push to pick a face, push again to work in it full screen, pull to go back to the cube.

Built for running several AI coding sessions at once (each face names itself after the session running in it, e.g. Claude Code's
session title), but every face is just a normal shell.

**Mac:** native app today. **Linux:** the same cube runs in your browser now; a native Linux window is welcome (see below).

## How it feels
- One clean quarter-roll per push, in the direction you pushed. Endless in every direction.
- The face that rolls in always arrives **right side up** (the geometry cheats on purpose: it's built for working, not for physics).
- Push down = select the face (your typing goes there) · push again = full screen · pull up = back to the cube.
- Button 6 = hand the 3D mouse back to your Mac as an ordinary 3D mouse; press it again to take it back. Fewer buttons on yours?
  Open the ⚙ panel, click "change" and press the button you want (saved in ~/.config/3d-terminal/config.json).
- PowerMate: turn = roll · tap = switch side-to-side / top-to-bottom · double tap = select · long press = full screen on/off.
- Keyboard: Ctrl+Option + arrows to roll, Ctrl+Option+Return for full screen, Ctrl+Option+1…6 to jump to a face. Click a face to pick it.

## Run it
**macOS (13+):** `mac/build.sh` → open `mac/build/3D Terminal.app`. Needs Python 3 and the Xcode command-line tools; the build makes a
private Python with `hidapi` for the Spaceball / knob.

**PowerMate on macOS: turn on Input Monitoring, or the knob stays dead.** macOS treats the PowerMate as a mouse, and an app can only
read a mouse after you allow it in **System Settings → Privacy & Security → Input Monitoring**. Without it the knob silently does
nothing in the cube (it keeps moving your pointer instead) and no error shows up anywhere. Add **3D Terminal** there and turn it on; if
the list also shows **Python**, turn that on too (the app reads the devices through its own Python helper). Then quit and reopen the
app. The app is not signed with a developer certificate, so after you rebuild it macOS may forget the permission: if the knob goes
dead after an update, remove 3D Terminal from the list and add it again. The Spaceball needs none of this.

**Linux:** `pip install hidapi` (optional, for the devices), then `linux/run.sh`. It opens the cube in your browser. For device access,
give your user read/write on `/dev/hidraw*` with a udev rule. The Linux path is new and lightly tested.

**Anywhere (browser):** `python3 server.py` and open the URL it prints.

## Reopen your sessions (Claude Code)
Quit with Claude running on some faces, and next time each of those faces resumes the same conversation (same folder, same flags).
One-time setup: copy `hooks/claude-session-hook.py` to `~/.config/3d-terminal/` and add it as a **SessionStart** hook in
`~/.claude/settings.json`:

    {"matcher": "", "hooks": [{"type": "command", "command": "/usr/bin/python3 -I ~/.config/3d-terminal/claude-session-hook.py", "timeout": 5}]}

The hook only acts inside a 3D Terminal face; everywhere else it does nothing. Faces where you'd already closed Claude stay plain shells.

**Codex** sessions come back too, with no setup: at quit the app finds each face's Codex session (it needs at least one message sent)
and reopens it with `codex resume <id>`. If you start Codex through your own command per CODEX_HOME, map them in
`~/.config/3d-terminal/config.json`, e.g. `{"codex_launchers": {"~/.codex-work": "workcodex"}}`.

## Colours and groups
Give a face a group colour and it gets an etched, glowing double line around its edge (the terminal itself stays black and readable).
Four colour slots, set in the ⚙ panel (the default palette stays distinguishable for colour-blind eyes):
- **tap** a colour button = colour the face you're looking at (tap again = clear) · **double tap** = jump to the next face of that colour ·
  **hold** (3D mouse) = dim every face that isn't that colour until you let go.
- Buttons: 3D mouse buttons 4, 5, 7, 8 by default (each changeable in ⚙ by pressing the button you want) · keyboard Ctrl+Option+7 8 9 0 ·
  or the "colour this face" buttons in ⚙.
- **Group faces by colour** (⚙): same-colour faces move next to each other. It only moves where faces sit: every session, title and
  colour stays with its own terminal, nothing restarts. Switch it off and every face goes back to its own place.
- Glow strength and a low-effects mode are in ⚙. Settings are kept per computer in `~/.config/3d-terminal/config.json`.

## Attention: which session needs you
When a Claude Code session on another face is waiting for you (a permission prompt, a question, or it finished its turn), that face
pulses in its own colour and a small list top-right says so: `Face 4 · <session> · needs your approval`. Nothing takes your keyboard
away. Click an entry, press **jump** (Ctrl+Option+J, or 3D mouse button 9) to go to the oldest waiting face, and **back**
(Ctrl+Option+B, or button 10) to return exactly where you were. Looking at a face does not clear it: it clears when the session
actually moves again (you answered, a tool ran, you sent a prompt). × dismisses one by hand. The longer a face waits, the closer its pulse
fades toward white (⚙: minutes, 0 = never). ⚙ also has "quiet" (no list, faces still pulse) and whether a finished turn counts.
The app never answers, approves or types anything for you.

One-time setup (Claude Code): copy `hooks/cube-attention-hook.py` to `~/.config/3d-terminal/` and add it in `~/.claude/settings.json`
under each of `Notification`, `Stop`, `UserPromptSubmit`, `PostToolUse` and `SessionEnd`:

    {"matcher": "", "hooks": [{"type": "command", "command": "/usr/bin/python3 -I ~/.config/3d-terminal/cube-attention-hook.py", "timeout": 5, "async": true}]}

Like the reopen hook, it does nothing outside a 3D Terminal face. It takes effect for sessions started after you quit and reopen the app.
Codex sessions don't report attention yet.

## How it's built
- `server.py`: six pseudo-terminals (your own shell, login mode), one event stream to the page, keystrokes in by POST, and the Spaceball +
  PowerMate read with hidapi (on macOS it holds them exclusively, so they stop moving your pointer while the cube runs).
  It listens on 127.0.0.1 only and every request needs a random key generated at each start.
- `index.html`: the cube (CSS 3D) with real [xterm.js](https://xtermjs.org) terminals on the faces.
- `mac/`: a small Swift app that starts the server and shows the cube in a native window.
- `linux/`: a launcher script. A native Linux window (GTK + WebKitGTK, or anything that can show a web page) would be a great PR.

Stopping the server (or quitting the app) ends every shell on the cube. The helper never outlives the app (it stops itself if the app
crashes), falls back to a free port if its usual one is busy, and uses ~0% CPU while idle. Open the cube in ONE window at a time: two windows of different
sizes fight over each terminal's size and the text gets scrambled until one closes.

The ⚙ in the top-right corner shows all the controls.

## Devices tested
- Spaceball 5000 USB (3Dconnexion, 046d:c621): report 1 = slide/push xyz, report 2 = twist, report 3 = buttons. On this one a push
  down reads negative z.
- Griffin PowerMate (077d:0410): turn + press; its light is driven with the vendor request the Linux powermate driver uses.
**Other 3D mice:** 3D Terminal looks for any 3Dconnexion device: the older ones with Logitech's vendor id (046d:c6xx, e.g.
SpaceNavigator, SpacePilot, SpaceMouse Pro) and the newer ones with 3Dconnexion's own (256f, e.g. SpaceMouse Compact, Wireless,
Enterprise), including the newer one-message report format. **Only the Spaceball 5000 has been tested on real hardware so far.**
If yours doesn't work, or the axes or buttons are mixed up, please open an issue with the model name: a fix is usually a line or two.

## License
MIT (see LICENSE). xterm.js is MIT too (vendor/LICENSE-xterm.txt).
