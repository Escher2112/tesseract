// gl.js — 3D Terminal's real renderer for the SOLID (Lyra 2026-10-28, Chris: "real deal textures, bump mapped materials and actual
// lighting with full 3D rendered WebGL eye candy… marble, brushed steel, jade, onyx… transparent jade… make this thing look amazing").
// The live terminals stay DOM (crisp, typeable) and sit exactly in the faces: this camera is built to match the page's CSS perspective
// (2200 px), so a CSS pixel IS a world unit here. index.html owns geometry maths + motion and hands over, every frame, cubeSH (the
// shape), cubeShown (its orientation) and cubePrefs (settings). This file only DRAWS.
//
// PORTABILITY (Chris: "we will be moving this to a native app… simple to port to Metal and Linux shaders"): standard metallic-roughness
// PBR described as DATA (MATERIALS, LIGHTS), textures baked into ordinary images, motes as ordinary points, no custom shaders. A native
// port (Filament on Metal/Vulkan, or wgpu: to verify then) maps these 1:1. Swap this file, keep the rest.
//
// REUSED FROM THE FORGE (HR-Chat v0.52 avatar-builder.js, the quarry; read 2099/2099): the material preset numbers, the five painted
// light moods (sky gradient + key/fill/rim glows → PMREM), the height → normal-map conversion, ACES tone mapping.
//
// 08:22 Chris: "texture seams… hard edges are jagged… a bit of lag". Answers, in order: (1) stone/jade are SOLID textures: 3D noise
// sampled at each texel's real position on the solid and baked into one atlas, so a vein runs on over an edge (brushed metals stay
// brushed per face, like real ones, and the grain follows each bevel); (2) the bloom chain rendered into a non-multisampled target,
// throwing away anti-aliasing → 4× MSAA target, and bevel strips get per-vertex normals blending face to face (they read ROUNDED);
// (3) the full-screen 2D motes canvas was re-uploaded to the GPU 30×/s → motes are now GL points over a once-painted backdrop, frames
// with nothing moving render at 30 fps, and ⚙ quality caps pixel ratio / MSAA / bloom.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

// ---------- MATERIALS (data). tex = procedural pattern (brushed = per face; marble / onyx / jade = solid 3D, continuous over edges)
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
// ---------- LIGHTS (data). 'room' = a neutral studio room (default: the Forge's navy sky left full metals dark). The rest are the
// Forge's five moods: env = painted sky; key/fill/rim = [colour, intensity, glow size, x, y in a 512×256 sky]; direct = real lights.
export const LIGHTS = {
  room:     { room: true, exposure: 0.85, ambient: 0.15, env: 1.0, key: ['#FFF5E1'], fill: ['#ffffff'], rim: ['#ffffff'], direct: [0.9, 0.3, 0.6] },
  studio:   { exposure: 1.6, ambient: 0.30, env: 1.0, key: ['#FFF5E1', 1.00, 100, 370, 50], fill: ['#8CAAF0', 0.60, 120, 80, 90], rim: ['#DCB95A', 0.45, 160, 256, 220], sky: ['#1a1a2e', '#050508'], noise: 18, direct: [0.8, 0.4, 0.5] },
  dramatic: { exposure: 2.0, ambient: 0.10, env: 1.2, key: ['#FFFFFF', 1.00, 70, 400, 30],  fill: ['#334466', 0.20, 100, 60, 128], rim: ['#FF6633', 0.70, 140, 256, 240], sky: ['#0a0a18', '#020204'], noise: 22, direct: [1.5, 0.2, 0.8] },
  warm:     { exposure: 1.8, ambient: 0.35, env: 1.0, key: ['#FFD4A0', 0.90, 130, 340, 60], fill: ['#D4A060', 0.50, 140, 100, 100], rim: ['#C08030', 0.55, 180, 256, 230], sky: ['#2a1a0e', '#0a0604'], noise: 14, direct: [0.6, 0.5, 0.3] },
  cool:     { exposure: 1.5, ambient: 0.25, env: 1.1, key: ['#C0D8FF', 0.85, 110, 350, 40], fill: ['#6688CC', 0.55, 130, 90, 80],  rim: ['#4466AA', 0.40, 150, 256, 210], sky: ['#101830', '#040810'], noise: 16, direct: [0.5, 0.4, 0.3] },
  rimOnly:  { exposure: 2.2, ambient: 0.05, env: 1.3, key: ['#FFF5E1', 0.10, 60, 370, 50],  fill: ['#8CAAF0', 0.10, 60, 80, 90],  rim: ['#C5A54E', 1.00, 200, 256, 230], sky: ['#0a0a0e', '#020204'], noise: 24, direct: [0.0, 0.0, 1.5] },
};
// ---------- QUALITY (⚙): pixel-ratio cap, MSAA samples, bloom allowed
const QUALITY = { high: { dpr: 2, msaa: 4, bloom: true }, balanced: { dpr: 1.5, msaa: 4, bloom: true }, fast: { dpr: 1, msaa: 0, bloom: false } };

let renderer, scene, camera, composer, rt, bloom, body, mesh, envRT, keyL, fillL, rimL, amb, polys = null;
let builtFor = null, matKey = null, lightKey = null, qualKey = null, themeKey = null, moteN = -1, motes = null, sparkle = null, backdrop = null, rain = null;
let last = 0, lastQ = '', dirty = true;
const prefs = () => window.cubePrefs || {};                            // the page hands these over every frame (its let-variables aren't window properties)
const hex = h => { const n = parseInt(h.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; };

// ---------- 3D value noise + fbm (seeded): the same function everywhere on the solid, so patterns cross edges unbroken
function noise3(seed) {
  let s = seed >>> 0 || 1; const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  const perm = new Uint8Array(512), base = [...Array(256).keys()];
  for (let i = 255; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [base[i], base[j]] = [base[j], base[i]]; }
  for (let i = 0; i < 512; i++) perm[i] = base[i & 255]; const val = new Float32Array(256).map(() => rnd());
  const n = (x, y, z) => { const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z), X = xi & 255, Y = yi & 255, Z = zi & 255;
    let u = x - xi, v = y - yi, w = z - zi; u = u * u * (3 - 2 * u); v = v * v * (3 - 2 * v); w = w * w * (3 - 2 * w);
    const h = (a, b, c) => val[perm[perm[perm[a] + b] + c]], l = (a, b, t) => a + (b - a) * t;
    return l(l(l(h(X, Y, Z), h(X + 1, Y, Z), u), l(h(X, Y + 1, Z), h(X + 1, Y + 1, Z), u), v),
             l(l(h(X, Y, Z + 1), h(X + 1, Y, Z + 1), u), l(h(X, Y + 1, Z + 1), h(X + 1, Y + 1, Z + 1), u), v), w); };
  return (x, y, z, oct = 5) => { let t = 0, amp = 0.5, f = 1; for (let o = 0; o < oct; o++) { t += amp * n(x * f, y * f, z * f); amp *= 0.5; f *= 2.03; } return t; };
}
// the pattern at object-space point p (in edge lengths): {c: rgb, h: height}. Brushed uses the piece's own grain axes (gx, gy) instead.
function sampler(kind) {
  const fbm = noise3(kind.length * 7919 + 17), MARB = [hex('#f3f0ea'), hex('#7d7a78')], ONYX = [hex('#0c0b0d'), hex('#4a4542')], JADE = [hex('#1f6b3a'), hex('#7fd19a')];
  const mix = (A, B, t) => [A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t];
  if (kind === 'brushed') return (p, gx, gy, fi) => { const h = 0.7 * fbm(gx * 1.2, gy * 90, fi * 7.3, 4) + 0.3 * fbm(gx * 5, gy * 200, fi * 3.1, 2); const g = 232 + 22 * h; return { c: [g, g, g], h }; };
  if (kind === 'marble') return p => { const t = Math.abs(Math.sin(p.x * 4 + p.y * 1.5 + p.z * 2.5 + fbm(p.x * 2, p.y * 2, p.z * 2, 6) * 7)), v = Math.pow(1 - t, 6);
    return { c: mix(MARB[0], MARB[1], Math.min(1, v * 0.9)).map(x => x - fbm(p.x * 18, p.y * 18, p.z * 18, 3) * 3), h: 0.6 - v * 0.6 }; };
  if (kind === 'onyx') return p => { const t = Math.sin(p.y * 12 + p.x * 3 + fbm(p.x * 1.5, p.y * 3, p.z * 1.5, 5) * 9) * 0.5 + 0.5, w = Math.pow(t, 10) * 0.6 + fbm(p.x * 8, p.y * 8, p.z * 8, 3) * 0.1;
    return { c: mix(ONYX[0], ONYX[1], w), h: w }; };
  return p => { const a = fbm(p.x * 2.2, p.y * 2.2, p.z * 2.2, 6), b = fbm(p.x * 10 + 9, p.y * 10, p.z * 10, 3), sp = fbm(p.x * 60, p.y * 60, p.z * 60, 2) > 0.72 ? 0.25 : 0;   // jade
    return { c: mix(JADE[0], JADE[1], Math.min(1, Math.max(0, a * 1.3 - 0.15 + b * 0.25 + sp))), h: a }; };
}
// ---------- the atlas: every piece of the body gets a cell; each texel = the pattern at that texel's real 3D point (no seams)
const atlasCache = {};
function bakeAtlas(kind) {
  const key = kind + '|' + builtFor.name; if (atlasCache[key]) return atlasCache[key];
  const t0 = performance.now(), A = 2048, smp = sampler(kind), a = builtFor.a;
  const col = document.createElement('canvas'), nrm = document.createElement('canvas'); col.width = col.height = nrm.width = nrm.height = A;
  const ci = col.getContext('2d').createImageData(A, A), ni = nrm.getContext('2d').createImageData(A, A), cd = ci.data, nd = ni.data;
  polys.forEach(P => {
    const R = P.cell, H = new Float32Array(R.n * R.n), ox = P.O.dot(P.x) / a, oy = P.O.dot(P.y) / a;
    for (let j = 0; j < R.n; j++) for (let i = 0; i < R.n; i++) {
      const u = (i + 0.5) / R.n * P.span, v = (j + 0.5) / R.n * P.span, p = P.O.clone().addScaledVector(P.x, u).addScaledVector(P.y, v).multiplyScalar(1 / a);
      const s = smp(p, ox + u / a, oy + v / a, P.fi), k = ((R.y + j) * A + R.x + i) * 4;
      cd[k] = s.c[0]; cd[k + 1] = s.c[1]; cd[k + 2] = s.c[2]; cd[k + 3] = 255; H[j * R.n + i] = s.h;
    }
    for (let j = 0; j < R.n; j++) for (let i = 0; i < R.n; i++) {     // the Forge's height → normal, inside the cell
      const at = (x, y) => H[Math.min(R.n - 1, Math.max(0, y)) * R.n + Math.min(R.n - 1, Math.max(0, x))], k = ((R.y + j) * A + R.x + i) * 4;
      nd[k] = 128 + (at(i - 1, j) - at(i + 1, j)) * 127 * 2; nd[k + 1] = 128 + (at(i, j - 1) - at(i, j + 1)) * 127 * 2; nd[k + 2] = 255; nd[k + 3] = 255;
    }
  });
  col.getContext('2d').putImageData(ci, 0, 0); nrm.getContext('2d').putImageData(ni, 0, 0);
  const tex = (cv, srgb) => { const t = new THREE.CanvasTexture(cv); t.flipY = false; t.anisotropy = 8; if (srgb) t.colorSpace = THREE.SRGBColorSpace; return t; };
  console.log(`[gl] baked ${kind} atlas for ${builtFor.name}: ${polys.length} cells in ${(performance.now() - t0).toFixed(0)} ms`);
  return (atlasCache[key] = { map: tex(col, true), normalMap: tex(nrm, false) });
}
function makeMaterial(key) {
  const m = MATERIALS[key] || MATERIALS.brushed_steel;
  const mat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(m.color), metalness: m.metalness, roughness: m.roughness,
    clearcoat: m.clearcoat || 0, clearcoatRoughness: 0.08, envMapIntensity: (LIGHTS[lightKey] || LIGHTS.room).env });
  if (m.emissive) { mat.emissive = new THREE.Color(m.emissive); mat.emissiveIntensity = m.emissiveIntensity || 0; }
  if (m.sheen) { mat.sheen = m.sheen; mat.sheenColor = new THREE.Color(m.sheenColor || '#ffffff'); mat.sheenRoughness = 0.5; }
  if (m.transmission) { Object.assign(mat, { transmission: m.transmission, thickness: m.thickness || 30, ior: m.ior || 1.5 });
    mat.attenuationColor = new THREE.Color(m.attenuationColor || m.color); mat.attenuationDistance = m.attenuationDistance || 100; mat.side = THREE.DoubleSide; }
  if (m.tex) { const t = bakeAtlas(m.tex); mat.map = t.map; mat.normalMap = t.normalMap; mat.normalScale = new THREE.Vector2(m.normal || 0.3, m.normal || 0.3); }
  return mat;
}

// ---------- environment: the studio room, or a painted Forge sky → PMREM reflections; plus real key / fill / rim lights
function paintEnv(L) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 256; const x = c.getContext('2d');
  const g = x.createLinearGradient(0, 0, 0, 256); g.addColorStop(0, L.sky[0]); g.addColorStop(1, L.sky[1]); x.fillStyle = g; x.fillRect(0, 0, 512, 256);
  for (const [cl, inten, size, px, py] of [L.key, L.fill, L.rim]) { if (inten <= 0) continue; const [r, gg, b] = hex(cl);
    const rg = x.createRadialGradient(px, py, 0, px, py, size); rg.addColorStop(0, `rgba(${r},${gg},${b},${inten})`);
    rg.addColorStop(0.3, `rgba(${r},${gg},${b},${inten * 0.65})`); rg.addColorStop(0.6, `rgba(${r * 0.6 | 0},${gg * 0.6 | 0},${b * 0.6 | 0},${inten * 0.25})`);
    rg.addColorStop(1, 'rgba(0,0,0,0)'); x.fillStyle = rg; x.fillRect(0, 0, 512, 256); }
  if (L.noise) { const im = x.getImageData(0, 0, 512, 256), d = im.data; for (let i = 0; i < d.length; i += 4) { const n = (Math.random() - 0.5) * L.noise; d[i] += n; d[i + 1] += n; d[i + 2] += n; } x.putImageData(im, 0, 0); }
  const t = new THREE.CanvasTexture(c); t.mapping = THREE.EquirectangularReflectionMapping; t.colorSpace = THREE.SRGBColorSpace; return t;
}
function applyLights(name) {
  const L = LIGHTS[name] || LIGHTS.room, pm = new THREE.PMREMGenerator(renderer); if (envRT) envRT.dispose();
  if (L.room) envRT = pm.fromScene(new RoomEnvironment(), 0.04); else { const t = paintEnv(L); envRT = pm.fromEquirectangular(t); t.dispose(); }
  pm.dispose(); scene.environment = envRT.texture; renderer.toneMappingExposure = L.exposure; amb.intensity = L.ambient;
  keyL.color.set(L.key[0]); fillL.color.set(L.fill[0]); rimL.color.set(L.rim[0]); [keyL.intensity, fillL.intensity, rimL.intensity] = L.direct.map(v => v * 2.2);
  if (mesh) mesh.material.envMapIntensity = L.env;
}

// ---------- the space (replaces the 2D canvas while GL runs): a once-painted backdrop + motes and the odd sparkle as GL points
function spriteTex(star) {
  const c = document.createElement('canvas'); c.width = c.height = 64; const x = c.getContext('2d'), g = x.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(star ? 0.08 : 0.3, 'rgba(225,230,255,0.6)'); g.addColorStop(1, 'rgba(0,0,0,0)'); x.fillStyle = g; x.fillRect(0, 0, 64, 64);
  if (star) { x.strokeStyle = 'rgba(255,255,255,0.9)'; x.lineWidth = 1.5; x.beginPath(); x.moveTo(4, 32); x.lineTo(60, 32); x.moveTo(32, 4); x.lineTo(32, 60); x.stroke(); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
function buildSpace() {
  const p = prefs(), theme = p.theme || 'liminal', n = theme === 'liminal' ? Math.round(140 * (p.motes ?? 1)) : 0, tk = theme + '|' + (p.matrixPalette || '') + '|' + (p.motes ?? 1);
  if (tk === themeKey && n === moteN) return; themeKey = tk; moteN = n; rain = null;
  if (backdrop) backdrop.dispose();
  if (theme === 'matrix' && window.MatrixRain) {                        // Alcove's rain, drawn at 1 CSS px per pixel, copied to the GPU only when it steps (~17×/s)
    const c = document.createElement('canvas'); c.width = innerWidth; c.height = innerHeight;
    rain = new window.MatrixRain(c.getContext('2d'), c.width, c.height, p.motes || 1); backdrop = new THREE.CanvasTexture(c); backdrop.colorSpace = THREE.SRGBColorSpace;
    scene.background = backdrop; if (motes) { scene.remove(motes); motes.geometry.dispose(); motes = null; } if (sparkle) { scene.remove(sparkle); sparkle = null; } return;
  } if (motes) { scene.remove(motes); motes.geometry.dispose(); motes = null; } if (sparkle) { scene.remove(sparkle); sparkle = null; }
  const c = document.createElement('canvas'); c.width = c.height = 512; const x = c.getContext('2d'), g = x.createRadialGradient(256, 230, 0, 256, 256, 380);
  if (theme === 'void') { x.fillStyle = '#000'; x.fillRect(0, 0, 512, 512); }
  else { (theme === 'classic' ? [[0, '#15112a'], [0.7, '#07060d'], [1, '#07060d']] : [[0, '#1d1d22'], [0.45, '#101013'], [1, '#030304']]).forEach(([o, cl]) => g.addColorStop(o, cl));
    x.fillStyle = g; x.fillRect(0, 0, 512, 512); }
  backdrop = new THREE.CanvasTexture(c); backdrop.colorSpace = THREE.SRGBColorSpace; scene.background = backdrop;
  if (!n) return;
  const pos = new Float32Array(n * 3), W = 4 * 6000 * Math.tan(camera.fov * Math.PI / 360) * camera.aspect, Hh = W / camera.aspect;
  for (let i = 0; i < n; i++) { pos[i * 3] = (Math.random() - 0.5) * W; pos[i * 3 + 1] = (Math.random() - 0.5) * Hh; pos[i * 3 + 2] = -3800 + Math.random() * 1600; }
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  motes = new THREE.Points(geo, new THREE.PointsMaterial({ size: 4.5, map: spriteTex(false), transparent: true, opacity: 0.45, depthWrite: false, blending: THREE.AdditiveBlending, color: 0xdce2ff }));
  motes.userData = { W, H: Hh, ph: Float32Array.from({ length: n }, () => Math.random() * 6.28) }; scene.add(motes);
  sparkle = new THREE.Sprite(new THREE.SpriteMaterial({ map: spriteTex(true), transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
  sparkle.scale.set(70, 70, 1); sparkle.userData = { life: 0 }; scene.add(sparkle);
}
function driftSpace(dt) {
  if (rain) { if (!prefs().lowfx && rain.step(dt * 1000)) backdrop.needsUpdate = true; return; }
  if (!motes || prefs().lowfx) return; const a = motes.geometry.attributes.position.array, { W, H, ph } = motes.userData;
  for (let i = 0; i < ph.length; i++) { ph[i] += dt * 0.4; a[i * 3 + 1] += dt * 14; a[i * 3] += Math.sin(ph[i]) * dt * 4;
    if (a[i * 3 + 1] > H / 2) { a[i * 3 + 1] = -H / 2; a[i * 3] = (Math.random() - 0.5) * W; } }
  motes.geometry.attributes.position.needsUpdate = true;
  const s = sparkle.userData; if (s.life <= 0 && Math.random() < dt * 0.25) { const k = Math.floor(Math.random() * ph.length) * 3; sparkle.position.set(a[k], a[k + 1], a[k + 2]); s.life = 1; }
  if (s.life > 0) { s.life -= dt * 0.7; sparkle.material.opacity = Math.max(0, Math.sin(Math.PI * Math.max(0, s.life))); }
}

// ---------- the body from the SAME geometry index.html uses: screen squares + metal triangles, chamfered. Bevel strips and corner caps
// carry per-vertex normals from the faces they join, so the light rolls across them: the edges read rounded, not sharp.
function buildBody() {
  const S = window.cubeSH, a = S.a, r = S.r, V3 = (x, y, z) => new THREE.Vector3(x, -y, z);    // page coords (y down) → GL (y up)
  const faces = [];
  S.slots.forEach(sl => { const n = V3(...sl.n), u = V3(...sl.u), y = u.clone().negate(), x = new THREE.Vector3().crossVectors(y, n), c = n.clone().multiplyScalar(r), h = a / 2;
    faces.push({ n, rho: h, v: [[1, 1], [-1, 1], [-1, -1], [1, -1]].map(([p, q]) => c.clone().addScaledVector(x, p * h).addScaledVector(y, q * h)) }); });
  S.tris.forEach(t => { const n = V3(...t.n), u = V3(...t.u), c = V3(...t.c), R = a / Math.sqrt(3), w = new THREE.Vector3().crossVectors(n, u);
    faces.push({ n, rho: a / (2 * Math.sqrt(3)), v: [0, 120, 240].map(d => { const th = d * Math.PI / 180; return c.clone().addScaledVector(u, Math.cos(th) * R).addScaledVector(w, Math.sin(th) * R); }) }); });
  const ch = a * 0.03, key = v => `${v.x.toFixed(1)},${v.y.toFixed(1)},${v.z.toFixed(1)}`, edges = new Map(), corners = new Map();
  polys = [];                                                             // every flat piece we draw: {pts, nrm (per point), want}
  faces.forEach(F => { const C = F.v.reduce((s, p) => s.add(p.clone()), new THREE.Vector3()).multiplyScalar(1 / F.v.length);
    F.s = F.v.map(v => C.clone().add(v.clone().sub(C).multiplyScalar(1 - ch / F.rho)));
    polys.push({ pts: F.s, nrm: F.s.map(() => F.n), want: F.n });
    F.v.forEach((v, i) => { const j = (i + 1) % F.v.length, k = [key(v), key(F.v[j])].sort().join('|');
      (edges.get(k) || edges.set(k, []).get(k)).push({ F, a: key(v), A: F.s[i], b: key(F.v[j]), B: F.s[j] });
      (corners.get(key(v)) || corners.set(key(v), { at: v, pts: [] }).get(key(v))).pts.push({ p: F.s[i], n: F.n }); }); });
  let open = 0; edges.forEach(list => { if (list.length !== 2) { open++; return; } const [e, f] = list, at = q => (q.a === e.a ? q.A : q.B), bt = q => (q.a === e.b ? q.A : q.B);
    polys.push({ pts: [e.A, e.B, bt(f), at(f)], nrm: [e.F.n, e.F.n, f.F.n, f.F.n], want: e.F.n.clone().add(f.F.n).normalize() }); });
  if (open) console.warn(`[gl] ${open} edges are not shared by exactly two faces: the body has a gap`);
  corners.forEach(({ at, pts }) => { if (pts.length < 3) return; const n = at.clone().normalize(), ref = pts[0].p.clone().sub(at);
    const t1 = ref.sub(n.clone().multiplyScalar(ref.dot(n))).normalize(), t2 = new THREE.Vector3().crossVectors(n, t1), ang = q => Math.atan2(q.p.clone().sub(at).dot(t2), q.p.clone().sub(at).dot(t1));
    const s = [...pts].sort((p, q) => ang(p) - ang(q)); polys.push({ pts: s.map(q => q.p), nrm: s.map(q => q.n), want: n }); });
  // atlas cells: big for faces, small for strips and caps; each piece gets its own flat frame (O, x, y, span) for baking + UVs
  let cx = 0, cy = 0, rowH = 0; const A = 2048;
  polys.forEach((P, fi) => {
    P.fi = fi; const p0 = P.pts[0], e = P.pts[1].clone().sub(p0).normalize(), m = P.want.clone().cross(e).normalize();
    let lo = [1e9, 1e9], hi = [-1e9, -1e9]; P.pts.forEach(p => { const d = p.clone().sub(p0), u = d.dot(e), v = d.dot(m); lo = [Math.min(lo[0], u), Math.min(lo[1], v)]; hi = [Math.max(hi[0], u), Math.max(hi[1], v)]; });
    P.x = e; P.y = m; P.span = Math.max(hi[0] - lo[0], hi[1] - lo[1]) * 1.04; P.O = p0.clone().addScaledVector(e, lo[0] - P.span * 0.02).addScaledVector(m, lo[1] - P.span * 0.02);
    const n = fi < faces.length ? 248 : 56; if (cx + n + 8 > A) { cx = 0; cy += rowH + 8; rowH = 0; } P.cell = { x: cx + 4, y: cy + 4, n }; cx += n + 8; rowH = Math.max(rowH, n);
  });
  if (cy + rowH > A) console.warn('[gl] atlas overflow: some cells fall outside 2048²');
  const pos = [], nor = [], uv = [];
  polys.forEach(P => {
    let pts = P.pts, nrm = P.nrm; const nn = new THREE.Vector3().crossVectors(pts[1].clone().sub(pts[0]), pts[2].clone().sub(pts[0]));
    if (nn.dot(P.want) < 0) { pts = [...pts].reverse(); nrm = [...nrm].reverse(); }
    const uvOf = p => { const d = p.clone().sub(P.O); return [(P.cell.x + d.dot(P.x) / P.span * P.cell.n) / A, (P.cell.y + d.dot(P.y) / P.span * P.cell.n) / A]; };
    for (let i = 1; i < pts.length - 1; i++) for (const k of [0, i, i + 1]) { const p = pts[k], n = nrm[k]; pos.push(p.x, p.y, p.z); nor.push(n.x, n.y, n.z); uv.push(...uvOf(p)); }
  });
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  builtFor = S; if (mesh) { body.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); }
  matKey = prefs().material || 'brushed_steel'; mesh = new THREE.Mesh(g, makeMaterial(matKey)); body.add(mesh);
  console.log(`[gl] body ${S.name}: ${faces.length} faces, ${edges.size} rounded edges, ${corners.size} corners, bevel ${ch.toFixed(1)}px, ${pos.length / 9} triangles`);
}

function size() {
  const W = innerWidth, H = innerHeight, Q = QUALITY[qualKey] || QUALITY.balanced;
  renderer.setPixelRatio(Math.min(Q.dpr, devicePixelRatio || 1)); renderer.setSize(W, H);
  const pr = renderer.getPixelRatio(); if (rt) rt.dispose();
  rt = new THREE.WebGLRenderTarget(Math.round(W * pr), Math.round(H * pr), { type: THREE.HalfFloatType, samples: Q.msaa });
  composer = new EffectComposer(renderer, rt); composer.addPass(new RenderPass(scene, camera));
  bloom = new UnrealBloomPass(new THREE.Vector2(W, H), 0.18, 0.4, 0.95); composer.addPass(bloom); composer.addPass(new OutputPass());
  composer.setPixelRatio(pr); composer.setSize(W, H);
  camera.fov = 2 * Math.atan(H / 2 / 2200) * 180 / Math.PI; camera.aspect = W / H; camera.updateProjectionMatrix();   // = the page's CSS perspective
  themeKey = null; buildSpace(); apply();
}
function init() {
  const cv = document.createElement('canvas'); cv.id = 'gl'; document.getElementById('bg').after(cv);
  renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: false, powerPreference: 'high-performance' });   // AA comes from the MSAA target
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
  scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(30, 1, 100, 20000); camera.position.set(0, 0, 2200);
  body = new THREE.Group(); scene.add(body);
  amb = new THREE.AmbientLight(0xffffff, 0.3); scene.add(amb);
  keyL = new THREE.DirectionalLight(0xffffff, 1); keyL.position.set(-1400, 1800, 2000); scene.add(keyL);       // up-left-front, like the old CSS light
  fillL = new THREE.DirectionalLight(0xffffff, 0.5); fillL.position.set(1800, -400, 1400); scene.add(fillL);
  rimL = new THREE.DirectionalLight(0xffffff, 0.5); rimL.position.set(0, -1200, -2400); scene.add(rimL);
  qualKey = prefs().quality || 'balanced'; size(); addEventListener('resize', size);
  document.body.classList.add('gl'); requestAnimationFrame(loop);
}
export function apply() {                                                  // re-read prefs (⚙ calls this)
  if (!renderer) return; const p = prefs(), on = p.gl !== false;
  document.body.classList.toggle('gl', on); renderer.domElement.style.display = on ? '' : 'none';
  if (qualKey !== (p.quality || 'balanced')) { qualKey = p.quality || 'balanced'; size(); return; }
  if (lightKey !== (p.light || 'room')) { lightKey = p.light || 'room'; applyLights(lightKey); }
  if (mesh && matKey !== (p.material || 'brushed_steel')) { mesh.material.dispose(); matKey = p.material || 'brushed_steel'; mesh.material = makeMaterial(matKey); }
  buildSpace(); bloom.enabled = p.bloom !== false && !p.lowfx && (QUALITY[qualKey] || QUALITY.balanced).bloom; dirty = true;
}
function loop(now) {
  requestAnimationFrame(loop);
  if (prefs().gl === false || document.hidden || !window.cubeSH) return;
  if (builtFor !== window.cubeSH) { buildBody(); dirty = true; }
  const q = window.cubeShown || [1, 0, 0, 0], qs = q.map(v => v.toFixed(5)).join(), moving = qs !== lastQ;
  if (!moving && !dirty && now - last < (rain ? 50 : 33)) return;         // nothing turning: 30 fps for motes, 20 for the rain (it steps every 58 ms)                      // nothing turning: 30 fps is plenty for drifting motes
  const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now; lastQ = qs; dirty = false;
  body.quaternion.set(-q[1], q[2], -q[3], q[0]); body.position.set(0, 0, -window.cubeSH.r);   // page rotation (y down) → GL (y up)
  driftSpace(dt); composer.render();
}
try { init(); window.GL = { apply, MATERIALS, LIGHTS, QUALITY: Object.keys(QUALITY) }; window.dispatchEvent(new Event('gl-ready')); }
catch (e) { console.warn('[gl] WebGL renderer unavailable, keeping the CSS look:', e); }
