// The Rolodex (a twist inside a face) and Fast Swap, checked headless (2026-11-17).   Run: node tests/rolodex.test.mjs
// Like maths.test.mjs it reads the LIVE functions out of index.html (nothing is copied, so the test can't drift from the app) and runs
// them in a sandbox with stubbed page state: a pretend ball (sbT / sbR), pretend faces, a fake clock. Exit code 0 = all passed.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const src = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
function extract(name) {                             // one top-level `function name(…) {…}` or `const name = …;` (same cutter as maths.test.mjs)
  const m = new RegExp(`\\n(function ${name}\\(|const ${name} = )`).exec(src);
  if (!m) throw new Error(`index.html no longer declares ${name}: update this test`);
  let i = m.index + 1, depth = 0, seenBody = false, q = null;
  for (; i < src.length; i++) {
    const c = src[i];
    if (q) { if (c === '\\') i++; else if (c === q) q = null; continue; }
    if (c === '/' && src[i + 1] === '/') { i = src.indexOf('\n', i); continue; }
    if (c === '"' || c === "'" || c === '`') { q = c; continue; }
    if ('([{'.includes(c)) { depth++; seenBody = true; }
    else if (')]}'.includes(c)) { depth--; if (depth === 0 && m[1].startsWith('function') && c === '}') return src.slice(m.index + 1, i + 1); }
    else if (c === ';' && depth === 0 && seenBody) return src.slice(m.index + 1, i + 1);
  }
  throw new Error(`could not find the end of ${name}`);
}
class DOMMatrix { constructor(a) { this.a = a; } toString() { return 'matrix3d(' + [...(this.a || [])].join(',') + ')'; } }

const NAMES = ['V', 'placeMatrix', 'upFor', 'buildShape', 'qMul', 'qAxis', 'qNorm', 'qMatrix', 'rotV', 'frontOf', 'alignQ', 'goTo', 'hist', 'noteVisit',
  'drumPhys', 'shape', 'MOTION_DEF', 'MOTION_SHAPE', 'mo', 'ROLO', 'roloTwist', 'roloPush', 'roloWatch', 'roloRows', 'placeSolid', 'fastSwap', 'openFace', 'jumpTo'];
const ctx = vm.createContext({ DOMMatrix, Math, console: { log() {} } });
vm.runInContext(`
  const S = 600, window = {}; let T = 0; const performance = { now: () => T };
  let prefs = { colors: {}, palette: ['#111111', '#222222', '#333333', '#444444'] }, sbT = [0, 0, 0], sbR = [0, 0, 0];
  let SH, slotOf, Q = [1, 0, 0, 0], Qt = [1, 0, 0, 0], W = [0, 0, 0], cmdTarget = false, tgtFace = -1, settled = true, lockedFace = 0;
  let hpos = -1, histNav = 0, ballHush = false, fullFace = -1, zooming = false, selFace = -1;
  let roloSince = 0, roloBusy = false, roloCool = 0, liveFaces = null, drumIsOpen = false, calls = [];
  const visible = () => slotOf.map((s, i) => s >= 0 ? i : -1).filter(i => i >= 0);
  const present = () => {}, renderAttn = () => {}, paint = () => {}, label = () => {}, refit = () => {}, webBar = () => {}, showWeb = () => {}, NATIVE = null;
  const select = i => { selFace = i; }, toggleFull = () => calls.push('toggleFull'), enterFace = i => calls.push('enter' + i), arrivalPulse = i => calls.push('pulse' + i);
  const drumOpen = () => drumIsOpen, qrefOpen = () => false, showDrum = on => { drumIsOpen = !!on; }, openRolo = () => calls.push('openRolo');
  const help = { classList: { contains: () => false } }, waitingSet = new Set(), webSet = new Set(), waiting = i => waitingSet.has(i), isWeb = i => webSet.has(i);
  const frontFace = () => frontOf(Qt), cur = () => (fullFace >= 0 ? fullFace : frontFace());
  const faces = Array.from({ length: 18 }, (_, i) => { const host = { at: 'inner' + i, classList: { add() {}, remove() {} } };
    return { i, host, title: '', inner: { insertBefore(h) { h.at = 'inner' + i; }, querySelector: () => null }, term: { options: { fontSize: 10 }, focus() { calls.push('focus' + i); } } }; });
  const full = { appendChild(h) { h.at = 'full'; } }, fullSnap = { style: {} }, cube = { style: {} };
  function frame() {}
  ${NAMES.map(extract).join('\n')}
  function useShape(name) { SH = buildShape(name); slotOf = Array.from({ length: 18 }, (_, i) => i < SH.slots.length ? i : -1);
    Q = [1, 0, 0, 0]; Qt = [1, 0, 0, 0]; W = [0, 0, 0]; cmdTarget = false; tgtFace = -1; settled = true; lockedFace = 0; fullFace = -1; zooming = false;
    hist.length = 0; hpos = -1; histNav = 0; calls = []; faces.forEach(f => { f.host.at = 'inner' + f.i; f.term.options.fontSize = 10; }); }
  function inFace(i) { goTo(i); Q = Qt; fullFace = i; selFace = i; faces[i].host.at = 'full'; faces[i].term.options.fontSize = 14; }
  function pose(q) { const f = frontOf(q), n = rotV(q, SH.slots[slotOf[f]].n), u = rotV(q, SH.slots[slotOf[f]].u);
    const ang = Math.atan2(u[0], -u[1]) * 180 / Math.PI; return { f, facing: n[2], square: Math.abs(ang - 90 * Math.round(ang / 90)) }; }
`, ctx);
const run = code => vm.runInContext(code, ctx);
let failed = 0, passed = 0;
const check = (ok, what) => { if (ok) passed++; else { failed++; console.log('  FAIL', what); } };
const ball = (t, r, flip = '{}') => run(`sbT = ${JSON.stringify(t)}; sbR = ${JSON.stringify(r)}; prefs.flip = ${flip};`);

console.log('the twist');
ball([0, 0, 0], [0, 0, -200]); check(run('roloTwist()') === 200, `a clean twist is read (${run('roloTwist()')}, want 200)`);
ball([0, 0, 0], [0, 0, -200], '{ t: true }'); check(run('roloTwist()') === -200, 'his "flip twist" setting turns it round');
ball([0, 0, 0], [180, 0, -200]); check(run('roloTwist()') === 0, 'a twist with nearly as much tilt in it is not a twist (200 vs tilt 180)');
ball([0, 0, 300], [0, 0, -120]); check(run('roloTwist()') === 0, 'a pull up that leaks twist is not a twist (pull 300, twist 120)');
ball([0, 0, 0], [40, 30, -150]); check(run('roloTwist()') === 150, 'a twist with a little tilt leak still counts (150 vs 40)');

console.log('opening');
// (the page's clock is never 0, and 0 is how roloWatch says "no twist yet": the test clock starts at 1000)
const watch = (...times) => { run('calls = []; roloSince = 0;'); for (const t of times) run(`T = ${t + 1000}; roloWatch(${t + 1000})`); return run('calls.join()'); };
ball([0, 0, 0], [0, 0, -200]);
check(watch(0, 50) === '', 'a firm twist held 50 ms: not yet');
check(watch(0, 50, 100) === 'openRolo', 'a firm twist held 100 ms opens it, once');
ball([0, 0, 0], [0, 0, -100]); check(watch(0, 50, 100, 200, 400) === '', 'a soft twist (100, under the 110 it takes) never opens it');
{ run('calls = []; roloSince = 0;'); ball([0, 0, 0], [0, 0, -200]); run('roloWatch(1000)'); ball([0, 0, 0], [0, 0, 0]); run('roloWatch(1050)');
  ball([0, 0, 0], [0, 0, -200]); run('roloWatch(1100); roloWatch(1150)');
  check(run('calls.join()') === '', 'a twist that let go in between starts its count again (no open 50 ms after the second start)'); }
ball([0, 0, 0], [0, 0, -200]);
run('drumIsOpen = true'); check(watch(0, 100, 200) === '', 'never while a drum is already open'); run('drumIsOpen = false');
run('ballHush = true'); check(watch(0, 100, 200) === '', 'never while the ball is hushed (the hand has not let go after a push)'); run('ballHush = false');
run('roloCool = 1500'); check(watch(0, 100, 200) === '' && watch(600, 700) === 'openRolo', 'not straight after closing; again once the pause is over'); run('roloCool = 0');
run('roloBusy = true'); check(watch(0, 100, 200) === '', 'not twice while the first open is still asking the server'); run('roloBusy = false');

console.log('rolling');
const roll = (twist, gl) => { ball([0, 0, 0], [0, 0, -twist]); return run(`(() => { const d = { p: 0, v: 0 }; for (let t = 0; t < 0.8; t += 1 / 60) drumPhys(d, roloPush(mo(), ${gl}), 1 / 60);
  sbR = [0, 0, 0]; for (let k = 0; k < 600; k++) drumPhys(d, roloPush(mo(), ${gl}), 1 / 60); return d; })()`); };
run(`useShape('rhombi')`);
{ const r = roll(300, true), l = roll(-300, true);
  check(r.p < 0 && r.p === Math.round(r.p) && r.v === 0, `3D reel: a right twist rolls it UP (position falls: ${r.p}) and it locks on a row`);
  check(l.p > 0 && l.p === Math.round(l.p) && l.v === 0, `3D reel: a left twist rolls it DOWN (position rises: ${l.p}) and it locks on a row`);
  check(r.p === -l.p, `both ways travel the same (${r.p} and ${l.p})`); }
{ const r = roll(300, false); check(r.p > 0, `flat fallback reel: the same right twist also rolls it up (its position rises: ${r.p})`); }
{ const d = roll(60, true); check(d.p === 0 && d.v === 0, 'a light twist only leans on the detent: the row stays put'); }
ball([0, 0, 0], [0, 0, -300]); run('ballHush = true'); check(run('roloPush(mo(), true)') === 0, 'a hushed ball does not roll it'); run('ballHush = false');
ball([0, 0, 0], [0, 0, 0]);

console.log('the list');
run(`useShape('rhombi'); inFace(4); liveFaces = new Set([1, 4, 9, 17]); waitingSet.clear(); webSet.clear(); waitingSet.add(12); webSet.add(14);`);
check(run('roloRows().join()') === '1,4,9,12,14,17', `running faces + the waiting one + the browser face, in face order (${run('roloRows().join()')})`);
run('inFace(6)'); check(run('roloRows().join()') === '1,4,6,9,12,14,17', 'the face you are on is always listed, even an idle shell');
run(`useShape('cube'); inFace(2); liveFaces = new Set([1, 9, 15]); waitingSet.clear(); webSet.clear();`);
check(run('roloRows().join()') === '1,2', `sessions parked off this shape are left out (${run('roloRows().join()')}, want 1,2)`);
run(`useShape('rhombi'); inFace(0); liveFaces = null; faces[3].title = 'claude'; faces[8].title = 'codex';`);
check(run('roloRows().join()') === '0,3,8', 'an older server that cannot say: faces whose session set a title'); run(`faces[3].title = ''; faces[8].title = '';`);

console.log('fast swap');
run(`useShape('rhombi'); inFace(1); prefs.fastSwap = true; prefs.colors = { 9: 2 };`);
{ const ok = run('fastSwap(9)'), p = run('pose(Q)');
  check(ok === true && run('fullFace') === 9, 'from inside face 2 straight into face 10');
  check(p.f === 9 && p.facing > 0.9999 && p.square < 0.5 && run('Q === Qt'), `the solid has turned to it behind the scenes, square (${JSON.stringify(p)})`);
  check(run(`faces[1].host.at`) === 'inner1' && run('faces[1].term.options.fontSize') === 10, 'the terminal you left is back on its face, small text');
  check(run(`faces[9].host.at`) === 'full' && run('faces[9].term.options.fontSize') === 14, 'the new terminal fills the screen, working-size text');
  check(run(`calls.includes('pulse9') && calls.includes('focus9')`), 'it pulses the border and takes your typing');
  check(run('hist[hpos].i') === 9, 'the landing is in the history');
  check(typeof run('cube.style.transform') === 'string', 'the solid itself was redrawn (pulling out shrinks into the right face)');
  check(run('settled && !cmdTarget && lockedFace === 9'), 'no stray click or roll is left pending for when you pull out'); }
check(run('fastSwap(9)') === false, 'onto the face you are in: nothing');
run('zooming = true'); check(run('fastSwap(3)') === false && run('fullFace') === 9, 'never in the middle of a zoom'); run('zooming = false');
run(`useShape('cube'); inFace(0); prefs.fastSwap = true;`); check(run('fastSwap(12)') === false && run('fullFace') === 0, 'a session parked off this shape: refused (the caller falls back)');
{ let bad = 0; for (let i = 1; i < 18; i++) { run(`useShape('rhombi'); inFace(0); fastSwap(${i})`); const p = run('pose(Q)'); if (!(run('fullFace') === i && p.f === i && p.facing > 0.9999 && p.square < 0.5)) bad++; }
  check(bad === 0, `rhombicuboctahedron: a fast swap to each of the other 17 faces lands on it, facing you and square (${bad} bad)`); }
run(`useShape('rhombi'); inFace(1); prefs.fastSwap = false; openFace(3, true);`);
check(run('calls.join()') === 'toggleFull,enter3' && run('fullFace') === 1, `Fast Swap off: the old out / roll / in runs (${run('calls.join()')})`);
run(`useShape('rhombi'); inFace(1); prefs.fastSwap = true; openFace(3, true);`);
check(run(`!calls.includes('toggleFull')`) && run('fullFace') === 3, 'Fast Swap on: no zoom out, you are simply there');
run(`useShape('rhombi'); inFace(1); prefs.fastSwap = true; jumpTo(5);`);
check(run('JSON.stringify(hist.map(e => [e.i, e.full]))') === '[[1,true],[5,false]]', `history back returns to the face you left, full screen (${run('JSON.stringify(hist.map(e => [e.i, e.full]))')})`);
run(`useShape('rhombi'); goTo(1); Q = Qt; prefs.fastSwap = true; openFace(3, true);`);
check(run('calls.join()') === 'enter3', 'from the solid (not inside a face) nothing changes: it rolls there and zooms in');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
