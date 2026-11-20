// tests/knob.test.cjs — the PowerMate's button and wheel, driven through the page's OWN knob() code (cut out of index.html) with a fake
// clock, a fake full screen and fake rolls (Lyra 2026-11-13, Chris: "single tap is out"). Run: node tests/knob.test.cjs
const fs = require('fs'), path = require('path');
const page = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const src = page.slice(page.indexOf('let knobAcc = 0'), page.indexOf('// 22:11 Chris: the PowerMate on the cuboctahedron')).replace(/^let /gm, 'var '); let T = 0, timers = [], calls = [];
global.performance = { now: () => T };
global.setTimeout = (f, ms) => { const t = { f, at: T + ms }; timers.push(t); return t; };
global.clearTimeout = t => { timers = timers.filter(x => x !== t); };
const tick = ms => { T += ms; for (const t of timers.filter(x => x.at <= T)) { timers = timers.filter(x => x !== t); t.f(); } };
global.fullFace = -1; global.SH = { name: 'cube' };
global.toggleFull = () => { calls.push('full'); fullFace = fullFace >= 0 ? -1 : 0; };
global.turn = (a, b) => calls.push(`turn${a},${b}`); global.select = () => calls.push('select'); global.frontFace = () => 0;
global.showMode = () => calls.push('mode'); global.knobStep = d => calls.push('step' + d);
eval(src);
let fails = 0; const ok = (c, w) => { console.log(c ? '  ok  ' : '  FAIL', w); if (!c) fails++; };
const reset = () => { calls = []; timers = []; tick(1000); };
// 1 in full screen: one tap = out, the instant the button goes down
fullFace = 2; reset(); knob(0, 1); ok(calls.join() === 'full' && fullFace === -1, 'full screen: button down → out at once');
tick(50); knob(0, 0); tick(500); ok(calls.join() === 'full', '…and letting go does nothing more (no mode swap)');
// 2 on the cube: hold 0.4 s → in, while still holding
reset(); knob(0, 1); tick(390); ok(calls.length === 0, 'cube: nothing before 0.4 s'); tick(20); ok(calls.join() === 'full', 'cube: full screen at 0.4 s, still holding');
knob(0, 0); tick(500); ok(calls.join() === 'full', '…release adds nothing');
// 3 a press that wobbles 2 clicks still counts
fullFace = -1; reset(); knob(0, 1); tick(100); knob(1, 1); knob(1, 1); tick(400); ok(calls.join() === 'full', 'cube: 2 stray clicks during the hold are forgiven');
knob(0, 0);
// 4 a real turn while pressed is a turn, not a press
fullFace = -1; reset(); knob(0, 1); for (let i = 0; i < 12; i++) knob(1, 1); tick(500); knob(0, 0); tick(500);
ok(!calls.includes('full') && calls.includes('turn1,0'), 'cube: turning while pressed rolls and never toggles');
// 5 tap and double tap on the cube unchanged
fullFace = -1; reset(); knob(0, 1); tick(80); knob(0, 0); tick(350); ok(calls.join() === 'mode', 'cube: single tap still swaps roll direction');
reset(); knob(0, 1); tick(80); knob(0, 0); tick(100); knob(0, 1); tick(80); knob(0, 0); tick(400); ok(calls.join() === 'select', 'cube: double tap still selects');
// 6 plain turning unchanged: 8 clicks = one roll
reset(); knobAcc = 0; kMode = "side"; for (let i = 0; i < 8; i++) knob(1, 0);  ok(calls.join() === 'turn1,0', 'cube: 8 clicks = one roll');
console.log(fails ? `${fails} failed` : 'all passed'); process.exit(fails ? 1 : 0);
