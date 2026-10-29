// End-to-end driver: runs the REAL page in headless Chrome against an ISOLATED server (its own TDT_HOME, its own port: never Chris's
// sessions), presses the ball the way a Spaceball does (it feeds the page's own ball variables + button masks), and checks what happens.
//     node tests/drive.mjs            (all scenarios)      node tests/drive.mjs drum perf   (some)
// Why it exists (2026-10-28): tests/maths.test.mjs proves the maths, but the day's worst bugs lived BETWEEN functions: openFace was
// deleted and five buttons silently threw; the drum never reached the face; the page rewrote itself every frame and lagged the Mac.
// None of that is visible to unit tests. This drives the page like a hand on the ball and reads the result.
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..'), PORT = 8793, DEVTOOLS = 9335;
const PY = join(homedir(), 'Library/Application Support/3D Terminal/venv/bin/python3');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const want = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- an isolated server with Chris's button map, tilt-to-roll (his Spaceball), the 18-face shape
const home = mkdtempSync(join(tmpdir(), 'tesseract-drive-'));
writeFileSync(join(home, 'config.json'), JSON.stringify({ prefs: {
  buttons: { color1: 1, color2: 2, color3: 3, color4: 4, jump: 5, home: 7, select: 8, full: 9, forward: 10, quickref: 11, back: 12 },
  handSrc: 'tilt', shape: 'rhombi', theme: 'void', motes: 0, colors: { 3: 1, 9: 1 } } }));
const server = spawn(existsSync(PY) ? PY : 'python3', ['-I', join(ROOT, 'server.py'), '--port', String(PORT)], { env: { ...process.env, TDT_HOME: home } });
let url = ''; server.stdout.on('data', d => { const m = String(d).match(/http:\/\/127\.0\.0\.1:\d+\/\?k=\S+/); if (m) url = m[0]; });
// the REAL GPU: software rendering runs a few fps, and every motion check then fails in slow motion (physics caps time per frame)
const chrome = spawn(CHROME, ['--headless=new', '--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', `--remote-debugging-port=${DEVTOOLS}`,
  `--user-data-dir=${join(home, 'chrome')}`, '--window-size=1400,900', 'about:blank'], { stdio: 'ignore' });
const cleanup = () => { try { chrome.kill(); } catch {} try { server.kill(); } catch {} try { rmSync(home, { recursive: true, force: true }); } catch {} };
process.on('exit', cleanup); process.on('SIGINT', () => process.exit(130));

// ---------- DevTools protocol
for (let k = 0; k < 60 && !url; k++) await sleep(100); if (!url) { console.error('server did not start'); process.exit(2); }
let tab; for (let k = 0; k < 150 && !tab; k++) { await sleep(100); try { tab = (await (await fetch(`http://127.0.0.1:${DEVTOOLS}/json/list`)).json()).find(t => t.type === 'page'); } catch {} }
const ws = new WebSocket(tab.webSocketDebuggerUrl); let id = 0; const pend = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
await new Promise(r => ws.onopen = r);
const call = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const page = async expr => { const r = await call('Runtime.evaluate', { expression: `(async () => { ${expr} })()`, awaitPromise: true, returnByValue: true });
  if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result.result.value; };
const fresh = async () => { await call('Page.navigate', { url }); await sleep(3500);
  await page(`window.__w = ms => new Promise(r => setTimeout(r, ms));
    // the ball, as the server delivers it: hold a reading for ms (re-sent every 16 ms, like a moving Spaceball), then let go
    window.__ball = async (t, r, ms) => { const until = performance.now() + ms; while (performance.now() < until) { sbT = t.slice(); sbR = r.slice(); sbAt = performance.now(); await __w(16); } sbT = [0, 0, 0]; sbR = [0, 0, 0]; sbAt = performance.now(); };
    window.__btn = async (n, ms = 80) => { sbButtons(1 << (n - 1)); await __w(ms); sbButtons(0); };
    window.__at = () => ({ front: frontFace() + 1, full: fullFace + 1, drum: drumOpen(), hist: hist.map(e => e.i + 1).join(' '), toast: document.getElementById('toast').textContent });`); };

// ---------- scenarios
let pass = 0, fail = 0; const check = (ok, what, detail) => { if (ok) { pass++; console.log('  ok  ', what); } else { fail++; console.log('  FAIL', what, detail ? JSON.stringify(detail) : ''); } };
const S = {
  async drum() {
    console.log('drum (hold 5, roll with a TILT, push in)');
    await fresh();
    const fps = await page(`let n = 0; const t0 = performance.now(); await new Promise(r => { (function f() { n++; if (performance.now() - t0 < 1000) requestAnimationFrame(f); else r(); })(); }); return n;`);
    check(fps > 30, `the page runs at a real frame rate (${fps} fps; below ~30 every motion check fails in slow motion)`);
    let a = await page(`await __btn(5, 650); return { open: drumOpen(), gl: drum.gl, n: drum.items.length, framed: drum.items[drumIdx(drum)].i + 1 };`);
    check(a.open && a.n === 18, 'hold 5 opens the drum with every session', a);
    a = await page(`const p0 = drum.p; await __ball([0, 0, 0], [-260, 0, 0], 500); await __w(1400); return { moved: Math.round(drum.p - p0), framed: drum.items[drumIdx(drum)].i + 1, settled: drum.v === 0 };`);
    check(a.moved !== 0 && a.settled, 'tilting rolls it and it settles on a row', a);
    const target = a.framed;
    a = await page(`await __ball([0, 0, -330], [0, 0, 0], 300); await __w(2200); return __at();`);
    check(!a.drum && a.front === target && a.full === target, `a clean push goes to the framed row (face ${target}) and zooms in`, a);
    // the suspect for Chris's real ball: the hand still tilting while it pushes
    await page(`await __ball([0, 0, 320], [0, 0, 0], 300); await __w(1200);`);   // pull out
    a = await page(`await __btn(5, 650); await __ball([0, 0, 0], [-260, 0, 0], 450); await __w(1400); const t = drum.items[drumIdx(drum)].i + 1;
      await __ball([0, 0, -300], [-170, 60, 0], 300); await __w(2200); return { target: t, ...__at() };`);
    check(!a.drum && a.front === a.target, 'a push WITH some tilt still in the hand goes too (tilt 170 vs push 300)', a);
    a = await page(`if (fullFace >= 0) { await __ball([0, 0, 320], [0, 0, 0], 300); await __w(1200); } await __btn(5, 650);
      await __ball([0, 0, 0], [-260, 0, 0], 450); await __w(1400); await __ball([0, 0, 0], [-260, 0, 0], 300); return { framed: drum.items[drumIdx(drum)].i + 1, ...__at() };`);
    check(a.drum, 'a firm tilt alone never counts as a push', a);
    a = await page(`await __ball([0, 0, 320], [0, 0, 0], 300); await __w(500); return __at();`);
    check(!a.drum, 'pull up closes the drum', a);
    // the two sides of the drum's push rule (16:20): a push beating the tilt goes; a tilt that leaks a little z doesn't
    a = await page(`await __btn(5, 650); await __ball([0, 0, 0], [-260, 0, 0], 450); await __w(1400); const t = drum.items[drumIdx(drum)].i + 1;
      await __ball([0, 0, -300], [-250, 0, 0], 300); await __w(2200); return { target: t, ...__at() };`);
    check(!a.drum && a.front === a.target, 'a push of 300 with a tilt of 250 still in the hand goes', a);
    a = await page(`if (fullFace >= 0) { await __ball([0, 0, 320], [0, 0, 0], 300); await __w(1200); } await __btn(5, 650);
      await __ball([0, 0, -140], [-300, 0, 0], 400); await __w(300); return __at();`);
    check(a.drum, 'a hard tilt (300) leaking a push (140) does not go', a);
    a = await page(`await __ball([0, 0, 320], [0, 0, 0], 300); await __w(400); prefs.drumAll = false; [6, 11].forEach(i => Object.assign(att[i], { s: 'needs', r: 'needs approval', since: Date.now() - 60000 * (i === 6 ? 9 : 2) })); renderAttn();
      await __btn(5, 650); const r = { n: drum.items.length, first: drum.items[drumIdx(drum)].i + 1, title: document.querySelector('.dttl').textContent }; prefs.drumAll = true; showDrum(false); return r;`);
    check(a.n === 2 && a.first === 7 && /2 WAITING/.test(a.title), 'toggle off: the drum holds only the waiting sessions, oldest first', a);
    await page(`await __ball([0, 0, 320], [0, 0, 0], 300); await __w(500);`);
  },
  async slow() {
    console.log('slow machine (CPU throttled 6×: the drum must still land where you point)');
    await fresh(); await call('Emulation.setCPUThrottlingRate', { rate: 6 });
    try {
      const a = await page(`await __btn(5, 650); await __ball([0, 0, 0], [-260, 0, 0], 600); await __w(2500); const t = drum.items[drumIdx(drum)].i + 1;
        await __ball([0, 0, -330], [-120, 0, 0], 400); await __w(4000); return { target: t, ...__at() };`);
      check(!a.drum && a.front === a.target, 'under heavy load a push still goes to the framed row', a);
    } finally { await call('Emulation.setCPUThrottlingRate', { rate: 1 }); }
  },
  async history() {
    console.log('history (C back · A forward) and tap 5');
    await fresh();
    let a = await page(`goTo(3); await __w(1500); goTo(9); await __w(1500); return __at();`);
    check(a.hist === '1 4 10' || a.hist.endsWith('4 10'), 'landing on faces is remembered', a);
    a = await page(`await __btn(12); await __w(1600); return __at();`);
    check(a.front === 4, 'C goes back', a);
    a = await page(`await __btn(10); await __w(1600); return __at();`);
    check(a.front === 10, 'A goes forward', a);
    a = await page(`await __btn(5); await __w(300); return __at();`);
    check(/nothing is waiting/.test(a.toast), 'tap 5 with nothing waiting says so', a);
    a = await page(`await __btn(1); await __w(1600); return __at();`);
    check(a.front === 4 || a.front === 10, 'tap colour 1 goes to a face of that colour', a);
    // 22:00 the PowerMate's hand-back: Ctrl+Option+K → the server flips it and tells the page; again → back to the cube
    a = await page(`dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyK', key: 'k', ctrlKey: true, altKey: true })); await __w(600); const one = { free: knobFree, toast: document.getElementById('toast').textContent };
      dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyK', key: 'k', ctrlKey: true, altKey: true })); await __w(600); return { one, two: { free: knobFree, toast: document.getElementById('toast').textContent } };`);
    check(a.one.free === true && /PowerMate → your Mac/.test(a.one.toast) && a.two.free === false && /PowerMate → the cube/.test(a.two.toast), 'Ctrl+Option+K hands the PowerMate to the Mac and back', a);
  },
  async shots() {   // not a check: pictures to LOOK at (SHOTS=/some/dir node tests/drive.mjs shots)
    const dir = process.env.SHOTS; if (!dir) { console.log('shots: set SHOTS=<folder> to save pictures'); return; }
    const { writeFileSync: w } = await import('node:fs'); const shot = async name => { const r = await call('Page.captureScreenshot', { format: 'png' }); w(join(dir, name), Buffer.from(r.result.data, 'base64')); console.log('  saved', join(dir, name)); };
    await fresh(); await page(`[0, 1].forEach(i => Object.assign(att[i], { s: 'needs', r: 'needs approval', since: Date.now() - 300000 })); renderAttn(); await __w(1200);`); await shot('waiting-pulse.png');
    await page(`await __btn(5, 650); await __w(900); sbT = [0, 0, -150]; sbR = [-90, 20, 0]; sbAt = performance.now(); await __w(200);`); await shot('drum-readout.png');
    await page(`sbT = [0, 0, 0]; sbR = [0, 0, 0]; showDrum(false);`);
  },
  async knob() {
    console.log('PowerMate (a dial through the faces on the big shapes; rolls on the cube)');
    await fresh();
    let a = await page(`goTo(0); await __w(1500); knob(8, 0); await __w(1500); const one = frontFace() + 1; knob(-16, 0); await __w(1500); return { one, back: frontFace() + 1 };`);
    check(a.one === 2 && a.back === 18, 'rhombi: one detent = the next face by number, and it wraps backwards (1 → 2, then back two → 18)', a);
    a = await page(`setShape('cube'); await __w(1500); goTo(0); await __w(1500); const q0 = Qt.slice(); knob(8, 0); await __w(1500); return { name: SH.name, front: frontFace() + 1, rolled: q0.some((v, k) => Math.abs(v - Qt[k]) > 0.1) };`);
    check(a.name === 'cube' && a.rolled && a.front !== 1, 'cube: the knob still ROLLS a quarter turn (unchanged)', a);
    a = await page(`setShape('cuboct'); await __w(1500); goTo(0); await __w(1500); const seq = [frontFace() + 1]; for (let k = 0; k < 7; k++) { knob(8, 0); await __w(1300); seq.push(frontFace() + 1); } return { seq: seq.join(' ') };`);
    check(a.seq === '1 2 3 4 5 6 1 2', `cuboctahedron: the knob walks the faces in order (${a.seq})`, a);
    await page(`setShape('rhombi'); await __w(800);`);
  },
  async perf() {
    console.log('perf (a still solid must not rewrite the page)');
    await fresh();
    const count = `const c = {}; const mo = new MutationObserver(l => l.forEach(m => { const k = m.target.id || m.target.className || m.target.nodeName; c[k] = (c[k] || 0) + 1; }));
      mo.observe(document.documentElement, { attributes: true, childList: true, subtree: true, characterData: true }); await __w(2000); mo.disconnect(); return c;`;
    let a = await page(`await __w(2500); ${count}`);
    const n = Object.values(a).reduce((x, y) => x + y, 0);
    check(n <= 4, `at rest the page writes nothing (${n} DOM changes in 2 s; 120 before the 15:45 fix)`, a);
    a = await page(`[2, 9].forEach(i => Object.assign(att[i], { s: 'needs', r: 'needs approval', since: Date.now() })); renderAttn(); await __w(500);
      const el = faces[2].inner, after = getComputedStyle(faces[2].el, '::after'); return { innerAnim: getComputedStyle(el).animationName, glowAnim: after.animationName, glowTiming: after.animationTimingFunction };`);
    check(a.innerAnim === 'none' && a.glowAnim === 'pulse' && /steps/.test(a.glowTiming), 'the waiting pulse fades a pre-drawn glow in steps (never animates box-shadow)', a);
  },
};
for (const [name, run] of Object.entries(S)) if (!want.length || want.includes(name)) { try { await run(); } catch (e) { fail++; console.log('  FAIL', name, 'threw:', e.message); } }
console.log(`\n${pass} passed, ${fail} failed`); ws.close(); process.exit(fail ? 1 : 0);
