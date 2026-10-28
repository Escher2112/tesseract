// gl.js — 3D Terminal's real renderer for the SOLID (Lyra 2026-10-28, Chris: "real deal textures, bump mapped materials and actual
// lighting with full 3D rendered WebGL eye candy… marble, brushed steel, jade, onyx… transparent jade… make this thing look amazing").
// The live terminals stay DOM (crisp, typeable) and sit exactly in the faces: this camera is built to match the page's CSS perspective
// (2200 px), so a CSS pixel IS a world unit here. index.html owns geometry maths + motion; it exposes SH (the shape) and cubeShown
// (the solid's orientation this frame). This file only DRAWS.
//
// PORTABILITY (Chris: "we will be moving this to a native app… simple to port to Metal and Linux shaders"): everything below is
// standard metallic-roughness PBR described as DATA (MATERIALS, LIGHTS), procedural textures as plain images, no custom shaders.
// A native port (Filament on Metal/Vulkan, or wgpu) maps these tables 1:1. Swap this file, keep the rest.
//
// REUSED FROM THE FORGE (HR-Chat v0.52 avatar-builder.js, the quarry): the material preset numbers, the five light presets, the
// painted equirectangular environment (sky gradient + key/fill/rim glows → PMREM), the height-map → normal-map conversion, ACES at 1.6.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

// ---------- MATERIALS (data). tex = which procedural texture; normal = bump strength. Forge numbers where the Forge had the material.
export const MATERIALS = {
  brushed_steel:     { label: 'brushed steel',     color: '#c8ccd3', metalness: 1.0, roughness: 0.3, tex: 'brushed', normal: 0.25 },
  polished_chrome:   { label: 'polished chrome',   color: '#f4f5f7', metalness: 1.0, roughness: 0.04 },
  polished_gold:     { label: 'polished gold',     color: '#FFD700', metalness: 1.0, roughness: 0.07 },
  satin_brass:       { label: 'satin brass',       color: '#C5A54E', metalness: 0.85, roughness: 0.25, tex: 'brushed', normal: 0.3 },
  copper:            { label: 'brushed copper',    color: '#c97b52', metalness: 1.0, roughness: 0.28, tex: 'brushed', normal: 0.35 },
  dark_iron:         { label: 'dark iron',         color: '#333340', metalness: 0.9, roughness: 0.6, tex: 'brushed', normal: 0.7 },
  oxidized_bronze:   { label: 'oxidized bronze',   color: '#8B7355', metalness: 0.85, roughness: 0.5, tex: 'jade', normal: 0.5 },
  white_marble:      { label: 'white marble',      color: '#ffffff', metalness: 0.0, roughness: 0.2, clearcoat: 0.6, tex: 'marble', normal: 0.15 },
  black_onyx:        { label: 'black onyx',        color: '#ffffff', metalness: 0.0, roughness: 0.06, clearcoat: 1.0, tex: 'onyx', normal: 0.1 },
  obsidian:          { label: 'obsidian',          color: '#0a0a12', metalness: 0.0, roughness: 0.05, clearcoat: 0.8, emissive: '#0a0a18', emissiveIntensity: 0.1 },
  jade:              { label: 'jade',              color: '#ffffff', metalness: 0.0, roughness: 0.24, clearcoat: 0.35, sheen: 0.4, sheenColor: '#bff0cc', tex: 'jade', normal: 0.12 },
  translucent_jade:  { label: 'translucent jade',  color: '#ffffff', metalness: 0.0, roughness: 0.28, tex: 'jade', normal: 0.1,
                       transmission: 0.75, thickness: 45, ior: 1.62, attenuationColor: '#1f7a45', attenuationDistance: 90 },
  translucent_brass: { label: 'translucent brass', color: '#C5A54E', metalness: 0.0, roughness: 0.1, transmission: 0.6, thickness: 35, attenuationColor: '#C5A54E', attenuationDistance: 140 },
};
// ---------- LIGHTS (data, the Forge's five). env = painted sky; key/fill/rim = glows painted into it (x,y in a 512×256 sky) and
// matching real lights; exposure feeds ACES tone mapping.
export const LIGHTS = {
  // 08:2x first look: the Forge's studio sky is mostly dark navy and fully metallic faces only show what they reflect, so steel read
  // dark and blue. Default = a neutral studio ROOM (bright softboxes all round); the Forge's painted skies stay as moods.
  room:     { room: true, exposure: 0.85, ambient: 0.15, env: 1.0, key: ['#FFF5E1', 1.0, 100, 370, 50], fill: ['#ffffff', 0.4], rim: ['#ffffff', 0.4], direct: [0.9, 0.3, 0.6] },
  studio:   { exposure: 1.6, ambient: 0.30, env: 1.0, key: ['#FFF5E1', 1.00, 100, 370, 50], fill: ['#8CAAF0', 0.60, 120, 80, 90], rim: ['#DCB95A', 0.45, 160, 256, 220], sky: ['#1a1a2e', '#050508'], noise: 18, direct: [0.8, 0.4, 0.5] },
  dramatic: { exposure: 2.0, ambient: 0.10, env: 1.2, key: ['#FFFFFF', 1.00, 70, 400, 30],  fill: ['#334466', 0.20, 100, 60, 128], rim: ['#FF6633', 0.70, 140, 256, 240], sky: ['#0a0a18', '#020204'], noise: 22, direct: [1.5, 0.2, 0.8] },
  warm:     { exposure: 1.8, ambient: 0.35, env: 1.0, key: ['#FFD4A0', 0.90, 130, 340, 60], fill: ['#D4A060', 0.50, 140, 100, 100], rim: ['#C08030', 0.55, 180, 256, 230], sky: ['#2a1a0e', '#0a0604'], noise: 14, direct: [0.6, 0.5, 0.3] },
  cool:     { exposure: 1.5, ambient: 0.25, env: 1.1, key: ['#C0D8FF', 0.85, 110, 350, 40], fill: ['#6688CC', 0.55, 130, 90, 80],  rim: ['#4466AA', 0.40, 150, 256, 210], sky: ['#101830', '#040810'], noise: 16, direct: [0.5, 0.4, 0.3] },
  rimOnly:  { exposure: 2.2, ambient: 0.05, env: 1.3, key: ['#FFF5E1', 0.10, 60, 370, 50],  fill: ['#8CAAF0', 0.10, 60, 80, 90],  rim: ['#C5A54E', 1.00, 200, 256, 230], sky: ['#0a0a0e', '#020204'], noise: 24, direct: [0.0, 0.0, 1.5] },
};

let renderer, scene, camera, composer, bloom, body, mesh, envRT, bgTex, keyL, fillL, rimL, amb, builtFor = null, matKey = null, lightKey = null;
const prefs = () => window.cubePrefs || {};                          // the page hands these over every frame (its let-variables aren't window properties)

// ---------- procedural textures (plain images: portable). Value noise + fbm, seeded.
function noise2(seed) {
  const p = new Uint8Array(512); let s = seed >>> 0 || 1; const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  const perm = [...Array(256).keys()]; for (let i = 255; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [perm[i], perm[j]] = [perm[j], perm[i]]; }
  for (let i = 0; i < 512; i++) p[i] = perm[i & 255]; const val = new Float32Array(256).map(() => rnd());
  const f = t => t * t * (3 - 2 * t);
  const n = (x, y) => { const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi, X = xi & 255, Y = yi & 255;
    const a = val[p[X + p[Y]]], b = val[p[X + 1 + p[Y]]], c = val[p[X + p[Y + 1]]], d = val[p[X + 1 + p[Y + 1]]], u = f(xf), v = f(yf);
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v; };
  return (x, y, oct = 5) => { let t = 0, amp = 0.5, fr = 1; for (let o = 0; o < oct; o++) { t += amp * n(x * fr, y * fr); amp *= 0.5; fr *= 2; } return t; };
}
const hex = h => { const n = parseInt(h.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; };
function makeTextures(kind) {
  const N = 512, col = document.createElement('canvas'), ht = new Float32Array(N * N); col.width = col.height = N;
  const cx = col.getContext('2d'), img = cx.createImageData(N, N), d = img.data, fbm = noise2(kind.length * 7919 + 17);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    let c = [255, 255, 255], h = 0;
    if (kind === 'brushed') { h = 0.7 * fbm(x * 0.002, y * 0.35, 4) + 0.3 * fbm(x * 0.01, y * 0.8, 2); const g = 232 + 22 * h; c = [g, g, g]; }   // fine, long grain (08:2x: was a coarse 'barcode')
    else if (kind === 'marble') { const t = Math.abs(Math.sin(x * 0.012 + y * 0.004 + fbm(x * 0.006, y * 0.006, 6) * 7)), v = Math.pow(1 - t, 6), s = fbm(x * 0.05, y * 0.05, 3) * 0.08;
      const base = hex('#f3f0ea'), vein = hex('#7d7a78'); c = base.map((b, i) => b + (vein[i] - b) * Math.min(1, v * 0.9) - s * 40); h = 0.6 - v * 0.6; }
    else if (kind === 'onyx') { const t = Math.sin(y * 0.035 + fbm(x * 0.004, y * 0.01, 5) * 9) * 0.5 + 0.5, w = Math.pow(t, 10) * 0.6 + fbm(x * 0.02, y * 0.02, 3) * 0.1;
      const base = hex('#0c0b0d'), band = hex('#4a4542'); c = base.map((b, i) => b + (band[i] - b) * w); h = w; }
    else if (kind === 'jade') { const a = fbm(x * 0.006, y * 0.006, 6), b = fbm(x * 0.03 + 9, y * 0.03, 3), sp = fbm(x * 0.2, y * 0.2, 2) > 0.72 ? 0.25 : 0;
      const lo = hex('#1f6b3a'), hi = hex('#7fd19a'), t = Math.min(1, Math.max(0, a * 1.3 - 0.15 + b * 0.25 + sp)); c = lo.map((l, i) => l + (hi[i] - l) * t); h = a; }
    const k = (y * N + x) * 4; d[k] = c[0]; d[k + 1] = c[1]; d[k + 2] = c[2]; d[k + 3] = 255; ht[y * N + x] = h;
  }
  cx.putImageData(img, 0, 0);
  const nrm = document.createElement('canvas'); nrm.width = nrm.height = N; const nx = nrm.getContext('2d'), ni = nx.createImageData(N, N), nd = ni.data;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {                // the Forge's height → normal conversion (tangent space)
    const l = ht[y * N + ((x + N - 1) % N)], r = ht[y * N + ((x + 1) % N)], t = ht[((y + N - 1) % N) * N + x], b = ht[((y + 1) % N) * N + x];
    const k = (y * N + x) * 4; nd[k] = 128 + (l - r) * 127 * 2; nd[k + 1] = 128 + (t - b) * 127 * 2; nd[k + 2] = 255; nd[k + 3] = 255;
  }
  nx.putImageData(ni, 0, 0);
  const tex = (cv, srgb) => { const t = new THREE.CanvasTexture(cv); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; if (srgb) t.colorSpace = THREE.SRGBColorSpace; return t; };
  return { map: tex(col, true), normalMap: tex(nrm, false) };
}
const texCache = {};
function makeMaterial(key) {
  const m = MATERIALS[key] || MATERIALS.brushed_steel;
  const mat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(m.color), metalness: m.metalness, roughness: m.roughness,
    clearcoat: m.clearcoat || 0, clearcoatRoughness: 0.08, envMapIntensity: 1.0, flatShading: false });
  if (m.emissive) { mat.emissive = new THREE.Color(m.emissive); mat.emissiveIntensity = m.emissiveIntensity || 0; }
  if (m.sheen) { mat.sheen = m.sheen; mat.sheenColor = new THREE.Color(m.sheenColor || '#ffffff'); mat.sheenRoughness = 0.5; }
  if (m.transmission) { Object.assign(mat, { transmission: m.transmission, thickness: m.thickness || 30, ior: m.ior || 1.5 });
    mat.attenuationColor = new THREE.Color(m.attenuationColor || m.color); mat.attenuationDistance = m.attenuationDistance || 100; mat.side = THREE.DoubleSide; }
  if (m.tex) { const t = texCache[m.tex] || (texCache[m.tex] = makeTextures(m.tex)); mat.map = t.map; mat.normalMap = t.normalMap;
    mat.normalScale = new THREE.Vector2(m.normal || 0.3, m.normal || 0.3); }
  return mat;
}

// ---------- the painted environment (the Forge's rebuildEnvMap): sky gradient + key / fill / rim glows → PMREM reflections
function paintEnv(L) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 256; const x = c.getContext('2d');
  const g = x.createLinearGradient(0, 0, 0, 256); g.addColorStop(0, L.sky[0]); g.addColorStop(1, L.sky[1]); x.fillStyle = g; x.fillRect(0, 0, 512, 256);
  for (const [col, inten, size, px, py] of [L.key, L.fill, L.rim]) { if (inten <= 0) continue; const [r, gg, b] = hex(col);
    const rg = x.createRadialGradient(px, py, 0, px, py, size); rg.addColorStop(0, `rgba(${r},${gg},${b},${inten})`);
    rg.addColorStop(0.3, `rgba(${r},${gg},${b},${inten * 0.65})`); rg.addColorStop(0.6, `rgba(${r * 0.6 | 0},${gg * 0.6 | 0},${b * 0.6 | 0},${inten * 0.25})`);
    rg.addColorStop(1, 'rgba(0,0,0,0)'); x.fillStyle = rg; x.fillRect(0, 0, 512, 256); }
  if (L.noise) { const im = x.getImageData(0, 0, 512, 256), d = im.data; for (let i = 0; i < d.length; i += 4) { const n = (Math.random() - 0.5) * L.noise; d[i] += n; d[i + 1] += n; d[i + 2] += n; } x.putImageData(im, 0, 0); }
  const t = new THREE.CanvasTexture(c); t.mapping = THREE.EquirectangularReflectionMapping; t.colorSpace = THREE.SRGBColorSpace;
  const pm = new THREE.PMREMGenerator(renderer); if (envRT) envRT.dispose(); envRT = pm.fromEquirectangular(t); t.dispose(); pm.dispose();
  scene.environment = envRT.texture;
}
function applyLights(name) {
  const L = LIGHTS[name] || LIGHTS.room;
  if (L.room) { const pm = new THREE.PMREMGenerator(renderer); if (envRT) envRT.dispose(); envRT = pm.fromScene(new RoomEnvironment(), 0.04); pm.dispose(); scene.environment = envRT.texture; }
  else paintEnv(L); renderer.toneMappingExposure = L.exposure; amb.intensity = L.ambient;
  keyL.color.set(L.key[0]); fillL.color.set(L.fill[0]); rimL.color.set(L.rim[0]);
  [keyL.intensity, fillL.intensity, rimL.intensity] = L.direct.map(v => v * 2.2);
  if (mesh) mesh.material.envMapIntensity = L.env;
}

// ---------- the solid's body from the SAME geometry index.html uses (SH): screens' squares + metal triangles, with chamfered edges
// (each face shrunk inward a little; the gaps become bevel strips and corner caps that catch the light).
function buildBody() {
  const S = window.cubeSH, a = S.a, r = S.r, V3 = (x, y, z) => new THREE.Vector3(x, -y, z);    // page coords (y down) → GL (y up)
  const polys = [];
  S.slots.forEach(sl => { const n = V3(...sl.n), u = V3(...sl.u), y = u.clone().negate(), x = new THREE.Vector3().crossVectors(y, n);
    const c = n.clone().multiplyScalar(r), h = a / 2;
    polys.push({ n, x: x.clone(), y: u.clone(), rho: h, v: [[1, 1], [-1, 1], [-1, -1], [1, -1]].map(([p, q]) => c.clone().addScaledVector(x, p * h).addScaledVector(y, q * h)) }); });
  S.tris.forEach(t => { const n = V3(...t.n), u = V3(...t.u), c = V3(...t.c), R = a / Math.sqrt(3), w = new THREE.Vector3().crossVectors(n, u);
    polys.push({ n, x: w.clone(), y: u.clone(), rho: a / (2 * Math.sqrt(3)),
      v: [0, 120, 240].map(d => { const th = d * Math.PI / 180; return c.clone().addScaledVector(u, Math.cos(th) * R).addScaledVector(w, Math.sin(th) * R); }) }); });
  const ch = a * 0.018, pos = [], nor = [], uv = [], key = v => `${v.x.toFixed(1)},${v.y.toFixed(1)},${v.z.toFixed(1)}`;
  const edges = new Map(), corners = new Map();
  const emit = (pts, want, P) => {                                         // a flat polygon, wound to face outward, fan-triangulated
    const nn = new THREE.Vector3().crossVectors(pts[1].clone().sub(pts[0]), pts[2].clone().sub(pts[0])); if (nn.dot(want) < 0) pts = [...pts].reverse();
    const C = pts.reduce((s, p) => s.add(p), new THREE.Vector3()).multiplyScalar(1 / pts.length);
    for (let i = 1; i < pts.length - 1; i++) for (const p of [pts[0], pts[i], pts[i + 1]]) {
      pos.push(p.x, p.y, p.z); nor.push(want.x, want.y, want.z); const d = p.clone().sub(C);
      uv.push(P.off + d.dot(P.x) / a, P.off * 1.7 + d.dot(P.y) / a); }
  };
  polys.forEach((P, pi) => {
    P.off = (pi * 0.37) % 1; const C = P.v.reduce((s, p) => s.add(p.clone()), new THREE.Vector3()).multiplyScalar(1 / P.v.length);
    P.s = P.v.map(v => C.clone().add(v.clone().sub(C).multiplyScalar(1 - ch / P.rho)));
    emit(P.s, P.n, P);
    P.v.forEach((v, i) => { const j = (i + 1) % P.v.length, k = [key(v), key(P.v[j])].sort().join('|');
      (edges.get(k) || edges.set(k, []).get(k)).push({ P, a: key(v), A: P.s[i], b: key(P.v[j]), B: P.s[j] });
      (corners.get(key(v)) || corners.set(key(v), { at: v, pts: [] }).get(key(v))).pts.push(P.s[i]); });
  });
  edges.forEach(list => { if (list.length !== 2) return; const [e, f] = list, at = q => (q.a === e.a ? q.A : q.B), bt = q => (q.a === e.b ? q.A : q.B);
    emit([e.A, e.B, bt(f), at(f)], e.P.n.clone().add(f.P.n).normalize(), e.P); });
  corners.forEach(({ at, pts }) => { if (pts.length < 3) return; const n = at.clone().normalize(), ref = new THREE.Vector3().subVectors(pts[0], at);
    const t1 = ref.clone().sub(n.clone().multiplyScalar(ref.dot(n))).normalize(), t2 = new THREE.Vector3().crossVectors(n, t1);
    const sorted = [...pts].sort((p, q) => Math.atan2(p.clone().sub(at).dot(t2), p.clone().sub(at).dot(t1)) - Math.atan2(q.clone().sub(at).dot(t2), q.clone().sub(at).dot(t1)));
    emit(sorted, n, polys[0]); });
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  if (mesh) { body.remove(mesh); mesh.geometry.dispose(); }
  mesh = new THREE.Mesh(g, makeMaterial(prefs().material || 'brushed_steel')); body.add(mesh); builtFor = S; matKey = prefs().material || 'brushed_steel';
  console.log(`[gl] body: ${polys.length} faces, ${edges.size} edges, ${corners.size} corners, chamfer ${ch.toFixed(1)}px, ${pos.length / 9} triangles`);
}

function size() {
  const W = innerWidth, H = innerHeight; renderer.setSize(W, H); composer.setSize(W, H);
  camera.fov = 2 * Math.atan(H / 2 / 2200) * 180 / Math.PI; camera.aspect = W / H; camera.updateProjectionMatrix();   // = the page's CSS perspective
}
function init() {
  const cv = document.createElement('canvas'); cv.id = 'gl'; document.getElementById('bg').after(cv);
  renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1)); renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
  scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(30, 1, 100, 20000); camera.position.set(0, 0, 2200);
  bgTex = new THREE.CanvasTexture(document.getElementById('bg')); bgTex.colorSpace = THREE.SRGBColorSpace; scene.background = bgTex;   // the motes, in the scene (jade refracts them)
  body = new THREE.Group(); scene.add(body);
  amb = new THREE.AmbientLight(0xffffff, 0.3); scene.add(amb);
  keyL = new THREE.DirectionalLight(0xffffff, 1); keyL.position.set(-1400, 1800, 2000); scene.add(keyL);       // up-left-front, like the old CSS light
  fillL = new THREE.DirectionalLight(0xffffff, 0.5); fillL.position.set(1800, -400, 1400); scene.add(fillL);
  rimL = new THREE.DirectionalLight(0xffffff, 0.5); rimL.position.set(0, -1200, -2400); scene.add(rimL);
  composer = new EffectComposer(renderer); composer.addPass(new RenderPass(scene, camera));
  bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.18, 0.4, 0.95); composer.addPass(bloom); composer.addPass(new OutputPass());
  size(); addEventListener('resize', size); apply();
  document.body.classList.add('gl'); requestAnimationFrame(loop);
}
export function apply() {                                                  // re-read prefs (⚙ calls this)
  if (!renderer) return; const p = prefs(), on = p.gl !== false;
  document.body.classList.toggle('gl', on); renderer.domElement.style.display = on ? '' : 'none';
  if (lightKey !== (p.light || 'room')) { lightKey = p.light || 'room'; applyLights(lightKey); }
  if (mesh && matKey !== (p.material || 'brushed_steel')) { mesh.material.dispose(); matKey = p.material || 'brushed_steel'; mesh.material = makeMaterial(matKey);
    mesh.material.envMapIntensity = (LIGHTS[lightKey] || LIGHTS.room).env; }
  bloom.enabled = p.bloom !== false && !p.lowfx;
}
let lastBg = 0;
function loop(now) {
  requestAnimationFrame(loop);
  if (prefs().gl === false || document.hidden || !window.cubeSH) return;
  if (builtFor !== window.cubeSH) { buildBody(); apply(); if (mesh) mesh.material.envMapIntensity = (LIGHTS[lightKey] || LIGHTS.room).env; }
  const q = window.cubeShown || [1, 0, 0, 0];                               // the page's rotation (y down) → GL (y up): (w, -x, y, -z)
  body.quaternion.set(-q[1], q[2], -q[3], q[0]); body.position.set(0, 0, -window.cubeSH.r);
  if (now - lastBg > 32) { bgTex.needsUpdate = true; lastBg = now; }
  composer.render();
}
try { init(); window.GL = { apply, MATERIALS, LIGHTS }; window.dispatchEvent(new Event('gl-ready')); }
catch (e) { console.warn('[gl] WebGL renderer unavailable, keeping the CSS look:', e); }
