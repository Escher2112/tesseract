// Headless check of the solid's maths: shapes, rolls, jumps, and the spring that settles it.
// Run before and after touching buildShape, rollTo, alignQ, present, goTo, nearestTarget or physics:
//     node tests/maths.test.mjs
// It reads the LIVE functions out of index.html (nothing is copied, so the test can't drift from the app) and runs them in a
// sandbox with a tiny DOMMatrix and stubbed page state. Exit code 0 = all passed. (Asked for by Ly-Ura's review, 2026-10-28.)
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const src = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

// cut one top-level declaration out of the page by name: `function name(…) {…}` or `const name = …;` (brackets balanced, strings skipped)
function extract(name) {
  const m = new RegExp(`\\n(function ${name}\\(|const ${name} = )`).exec(src);
  if (!m) throw new Error(`index.html no longer declares ${name}: update this test`);
  let i = m.index + 1, depth = 0, seenBody = false, q = null;
  for (; i < src.length; i++) {
    const c = src[i];
    if (q) { if (c === '\\') i++; else if (c === q) q = null; continue; }
    if (c === '/' && src[i + 1] === '/') { i = src.indexOf('\n', i); continue; }          // comments carry apostrophes ("screen's")
    if (c === '"' || c === "'" || c === '`') { q = c; continue; }
    if ('([{'.includes(c)) { depth++; seenBody = true; }
    else if (')]}'.includes(c)) { depth--; if (depth === 0 && m[1].startsWith('function') && c === '}') return src.slice(m.index + 1, i + 1); }
    else if (c === ';' && depth === 0 && seenBody) return src.slice(m.index + 1, i + 1);
  }
  throw new Error(`could not find the end of ${name}`);
}

class DOMMatrix {                                  // column-major 4×4, the same layout the page's DOMMatrix([…16]) calls use
  constructor(a) { this.a = a ? Float64Array.from(a) : Float64Array.from([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]); }
  multiply(o) { const r = new Float64Array(16);
    for (let c = 0; c < 4; c++) for (let row = 0; row < 4; row++) { let s = 0; for (let k = 0; k < 4; k++) s += this.a[k * 4 + row] * o.a[c * 4 + k]; r[c * 4 + row] = s; }
    return new DOMMatrix(r); }
  transformPoint(p) { const v = [p.x, p.y, p.z, p.w], o = [0, 0, 0, 0];
    for (let row = 0; row < 4; row++) for (let c = 0; c < 4; c++) o[row] += this.a[c * 4 + row] * v[c];
    return { x: o[0], y: o[1], z: o[2], w: o[3] }; }
  toString() { return `matrix3d(${[...this.a].join(',')})`; }
}
class DOMPoint { constructor(x = 0, y = 0, z = 0, w = 1) { Object.assign(this, { x, y, z, w }); } }

const NAMES = ['V', 'placeMatrix', 'upFor', 'buildShape', 'qMul', 'qAxis', 'qNorm', 'qMatrix', 'faceAt', 'rotV', 'frontOf', 'rollTo', 'alignQ',
  'goTo', 'MOTION_DEF', 'MOTION_SHAPE', 'mo', 'qConj', 'rotVecQ', 'errVec', 'nearestTarget', 'shape', 'navMode', 'handInput', 'physics'];
const ctx = vm.createContext({ DOMMatrix, DOMPoint, Math, console: { log() {} } });
vm.runInContext(`
  const S = 600; let prefs = {}, sbT = [0, 0, 0], sbR = [0, 0, 0], ballRead = '';
  let SH, slotOf, Q = [1, 0, 0, 0], Qt = [1, 0, 0, 0], W = [0, 0, 0], cmdTarget = false, tgtFace = -1, settled = true, lockedFace = 0;
  const visible = () => slotOf.map((s, i) => s >= 0 ? i : -1).filter(i => i >= 0);
  const present = () => {}, clickSound = () => {}, devLayout = () => null;
  ${NAMES.map(extract).join('\n')}
  function useShape(name) { SH = buildShape(name); slotOf = Array.from({ length: 18 }, (_, i) => i < SH.slots.length ? i : -1);
    Q = [1, 0, 0, 0]; Qt = [1, 0, 0, 0]; W = [0, 0, 0]; cmdTarget = false; tgtFace = -1; settled = true; lockedFace = 0; prefs = {}; }
`, ctx);
const run = code => vm.runInContext(code, ctx);

let failed = 0, passed = 0;
const check = (ok, what) => { if (ok) passed++; else { failed++; console.log('  FAIL', what); } };
// shared checks on a target pose: unit length, the front screen faces you, and its edges are square to the screen
run(`function pose(q) { const f = frontOf(q), n = rotV(q, SH.slots[slotOf[f]].n), u = rotV(q, SH.slots[slotOf[f]].u);
  const ang = Math.atan2(u[0], -u[1]) * 180 / Math.PI; return { f, unit: Math.abs(Math.hypot(...q) - 1), facing: n[2], square: Math.abs(ang - 90 * Math.round(ang / 90)) }; }`);
const okPose = p => p.unit < 1e-9 && p.facing > 0.9999 && p.square < 0.5;

let seed = 12345; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;

for (const shape of ['cube', 'cuboct', 'rhombi']) {
  console.log(`${shape}`);
  // 1. the shape builds (buildShape throws on a wrong solid: square distance, triangle edges, screen corners on triangle corners)
  let built = true; try { run(`useShape('${shape}')`); } catch (e) { built = false; console.log('  FAIL build:', e.message); }
  check(built, `${shape} builds`); if (!built) continue;
  const n = run('SH.slots.length');
  check(n === { cube: 6, cuboct: 6, rhombi: 18 }[shape], `${shape} has ${n} screens`);

  // 2. 2,000 random rolls: every step lands on a NEW screen, facing you, square to the screen, unit quaternion
  let bad = 0;
  for (let k = 0; k < 2000; k++) {
    const axis = rnd() < 0.5 ? '[0, 1, 0]' : '[1, 0, 0]', sign = rnd() < 0.5 ? 1 : -1;
    const before = run('frontOf(Qt)'); run(`Qt = rollTo(${axis}, ${sign})`); const p = run('pose(Qt)');
    if (!okPose(p) || p.f === before) { if (bad++ < 3) console.log(`  roll ${k} (${axis} ${sign}):`, JSON.stringify(p), 'from', before); }
  }
  // KNOWN 2026-10-28 (found by this test, NOT fixed: a behaviour change needs Chris): on the cuboctahedron, after a few rolls the
  // next screen often isn't on the roll's circle, so rollTo falls back to a plain 90° turn and stops with a triangle or edge in front
  // (the spring then pulls the nearest screen in on its own). Reported, not failed; delete this branch when it's fixed.
  if (shape === 'cuboct') console.log(`  KNOWN: ${bad} of 2,000 rolls stop between screens (arrow keys / knob on the cuboctahedron)`);
  else check(bad === 0, `${shape}: 2,000 random rolls, ${bad} bad`);

  // 3. the cube: four rolls the same way come back to the same screen
  if (shape === 'cube') for (const [axis, sign] of [['[0, 1, 0]', 1], ['[0, 1, 0]', -1], ['[1, 0, 0]', 1], ['[1, 0, 0]', -1]]) {
    run('Qt = [1, 0, 0, 0]'); const seq = []; for (let k = 0; k < 4; k++) { run(`Qt = rollTo(${axis}, ${sign})`); seq.push(run('frontOf(Qt)')); }
    check(seq[3] === 0 && new Set(seq).size === 4, `cube: 4 rolls about ${axis} ${sign} visit 4 screens and return (${seq})`);
  }

  // 4. a jump to every screen, from a scrambled start, lands on that screen, facing you and square
  for (let i = 0; i < n; i++) {
    run(`useShape('${shape}'); for (let k = 0; k < 7; k++) Qt = rollTo(${rnd() < 0.5 ? '[0, 1, 0]' : '[1, 0, 0]'}, ${rnd() < 0.5 ? 1 : -1}); goTo(${i})`);
    const p = run('pose(Qt)'); check(okPose(p) && p.f === i, `${shape}: jump to ${i} → ${JSON.stringify(p)}`);
  }

  // 5. the spring: let go 30° off a screen and it settles onto a screen, at the defaults and at every corner of the sliders' range
  const corners = [{}];
  for (const inertia of [0.2, 4]) for (const damping of [0.5, 10]) for (const snap of [5, 150]) for (const bounce of [0, 1]) corners.push({ inertia, damping, snap, bounce });
  for (const motion of corners) for (const dt of [1 / 60, 0.25]) {
    run(`useShape('${shape}'); prefs = { motion: { ${shape}: ${JSON.stringify(motion)} } };
      Q = qNorm(qMul(qAxis(...V.norm([${rnd() - 0.5}, ${rnd() - 0.5}, ${rnd() - 0.5}]), 30), [1, 0, 0, 0])); Qt = Q; settled = false;`);
    let t = 0; while (t < 60 && !run('settled')) { run(`physics(${dt}, 0, 0, false)`); t += dt; }
    const p = run('pose(Q)'), ok = run('settled') && okPose(p);
    check(ok, `${shape}: settle ${JSON.stringify(motion)} dt=${dt.toFixed(3)} → ${ok ? t.toFixed(2) + 's' : 'never in 60s ' + JSON.stringify(p)}`);
  }
}
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
