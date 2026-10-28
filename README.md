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
- PowerMate: turn = roll · tap = switch side-to-side / top-to-bottom · double tap = select · long press = full screen on/off.
- Keyboard: Ctrl+Option + arrows to roll, Ctrl+Option+Return for full screen, Ctrl+Option+1…6 to jump to a face. Click a face to pick it.

## Run it
**macOS (13+):** `mac/build.sh` → open `mac/build/3D Terminal.app`. Needs Python 3 and the Xcode command-line tools; the build makes a
private Python with `hidapi` for the Spaceball / knob.

**Linux:** `pip install hidapi` (optional, for the devices), then `linux/run.sh`. It opens the cube in your browser. For device access,
give your user read/write on `/dev/hidraw*` with a udev rule. The Linux path is new and lightly tested.

**Anywhere (browser):** `python3 server.py` and open the URL it prints.

## How it's built
- `server.py`: six pseudo-terminals (your own shell, login mode), one event stream to the page, keystrokes in by POST, and the Spaceball +
  PowerMate read with hidapi (on macOS it holds them exclusively, so they stop moving your pointer while the cube runs).
  It listens on 127.0.0.1 only and every request needs a random key generated at each start.
- `index.html`: the cube (CSS 3D) with real [xterm.js](https://xtermjs.org) terminals on the faces.
- `mac/`: a small Swift app that starts the server and shows the cube in a native window.
- `linux/`: a launcher script. A native Linux window (GTK + WebKitGTK, or anything that can show a web page) would be a great PR.

Stopping the server (or quitting the app) ends every shell on the cube. Open the cube in ONE window at a time: two windows of different
sizes fight over each terminal's size and the text gets scrambled until one closes.

The ⚙ in the top-right corner shows all the controls.

## Devices tested
- Spaceball 5000 USB (3Dconnexion, 046d:c621): report 1 = slide/push xyz, report 2 = twist, report 3 = buttons. On this one a push
  down reads negative z.
- Griffin PowerMate (077d:0410): turn + press; its light is driven with the vendor request the Linux powermate driver uses.
Other 3Dconnexion devices should work with small changes to the ids in `server.py`.

## License
MIT (see LICENSE). xterm.js is MIT too (vendor/LICENSE-xterm.txt).
