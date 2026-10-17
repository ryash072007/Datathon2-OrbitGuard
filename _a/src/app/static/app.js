/* Dashboard behaviour. Vanilla JS + three.js r128 (CDN, pinned). */
'use strict';
const B = JSON.parse(document.getElementById('boot').textContent);
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const NS = 'http://www.w3.org/2000/svg';
const C = {act: '#ff5468', wait: '#ffb43c', monitor: '#5aa2ff', ok: '#3ddc97', cyan: '#38d6f5', orange: '#f4a261', mute: '#97a8c6', dim: '#6b7d9e', line: '#1b2944', line2: '#27385c'};
const ACT = {ACT: C.act, WAIT: C.wait, MONITOR: C.monitor};
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches || /[?&]still/.test(location.search);  // ?still: no animations, final values
const esc = t => String(t).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmtInt = n => Math.round(n).toLocaleString('en-US');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ease = t => 1 - Math.pow(1 - t, 4);
async function getJsonWhenReady(url, tries = 90) {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(url);
    if (r.status === 200) return r.json();
    if (r.status !== 202) throw new Error(url + ' -> HTTP ' + r.status);
    await sleep(2000);
  }
  throw new Error('timed out waiting for ' + url);
}
function onVisible(el, fn, opts = {}) {   // fires once (or toggles with opts.toggle)
  if (!el) return;
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (opts.toggle) { fn(e.isIntersecting); return; }
    if (e.isIntersecting) { io.disconnect(); fn(); }
  }), {threshold: opts.threshold ?? 0.25});
  io.observe(el);
}

/* ---------------------------------------------------------------- counters */
function countUp(el, to, ms = 1600) {
  const fmt = el.dataset.fmt, suf = el.dataset.suffix || '', dec = +el.dataset.dec || 0;
  const show = v => el.textContent = (fmt === 'sci' ? v.toExponential(1) : dec ? v.toFixed(dec) : fmtInt(v)) + suf;
  if (REDUCED) return show(to);
  const t0 = performance.now();
  (function f(t) {
    const k = Math.min(1, (t - t0) / ms);
    show(to * ease(k));
    if (k < 1) requestAnimationFrame(f); else show(to);
  })(t0);
  setTimeout(() => show(to), ms + 250);   // always land on the exact source value
}
$$('[data-count]').forEach(el => onVisible(el, () => countUp(el, parseFloat(el.dataset.count))));

/* ---------------------------------------------------------------- reveal, nav spy, progress */
$$('.panel, .sec h2, .lede, .bigstat, .pstat').forEach(el => el.classList.add('rv'));
const rvIO = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); rvIO.unobserve(e.target); } }), {threshold: 0.08});
$$('.rv').forEach(el => rvIO.observe(el));
setTimeout(() => $$('.rv').forEach(el => el.classList.add('in')), 6000);  // never leave content hidden
(function nav() {
  const links = $$('#steps a'), secs = links.map(a => document.getElementById(a.dataset.step));
  const bar = $('#progress');
  function upd() {
    const y = scrollY + innerHeight * 0.35;
    let cur = -1;
    secs.forEach((s, i) => { if (s && s.offsetTop <= y) cur = i; });
    links.forEach((a, i) => { a.classList.toggle('on', i === cur); a.classList.toggle('seen', i < cur); });
    const h = document.documentElement.scrollHeight - innerHeight;
    bar.style.width = (h > 0 ? 100 * scrollY / h : 0) + '%';
  }
  addEventListener('scroll', upd, {passive: true}); addEventListener('resize', upd); upd();
})();

/* ---------------------------------------------------------------- background jobs / run buttons */
let wasRunning = false;
async function poll() {
  try {
    const s = await (await fetch('/api/status')).json();
    const busy = $('#busy'), msg = $('#busy-msg');
    const running = Object.values(s.jobs).filter(j => j.state === 'running');
    const failed = Object.values(s.jobs).filter(j => j.state === 'error');
    busy.hidden = !(running.length || failed.length);
    msg.textContent = failed.length && !running.length ? 'FAILED: ' + failed[0].error : running.map(j => j.label + ' (' + j.elapsed_s + ' s)').join(', ');
    $$('button.run').forEach(b => b.disabled = running.length > 0);
    if (wasRunning && !running.length && !failed.length) { location.reload(); return; }
    wasRunning = running.length > 0;
    if (!wasRunning && !failed.length) return;          // idle: stop polling until a button is pressed
  } catch (e) { /* server restarting */ }
  setTimeout(poll, 2000);
}
$$('button.run').forEach(b => b.addEventListener('click', async () => {
  b.disabled = true; await fetch(b.dataset.url, {method: 'POST'}); wasRunning = true; poll();
}));
poll();
const regen = $('#regen');
if (regen) regen.addEventListener('click', async () => {
  regen.disabled = true; regen.textContent = 'computing...';
  await fetch('/api/brief/' + B.norad); location.reload();
});

/* ---------------------------------------------------------------- svg helper */
function svg(w, h, inner, label) {
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label || '')}">${inner}</svg>`;
}

/* ================================================================ 3D globe factory */
let threeP = null;
function loadThree() {
  if (window.THREE) return Promise.resolve();
  if (!threeP) threeP = new Promise((ok, bad) => {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
    s.onload = ok; s.onerror = () => bad(new Error('three.js CDN unreachable'));
    document.head.appendChild(s);
  });
  return threeP;
}
function glowTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const x = c.getContext('2d'), g = x.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(.25, 'rgba(255,255,255,.55)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g; x.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}
function buildGlobe(host, g, o) {
  const w = host.clientWidth || 800, h = host.clientHeight || 500;
  let renderer;
  try { renderer = new THREE.WebGLRenderer({antialias: true, alpha: true}); } catch (e) { throw new Error('WebGL unavailable'); }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(w, h); host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, w / h, 100, 600000);
  let dist = o.dist; camera.position.set(0, 0, dist);
  const pivot = new THREE.Group(); scene.add(pivot);
  const world = new THREE.Group(); world.rotation.x = -Math.PI / 2; pivot.add(world);
  pivot.rotation.x = 0.4;
  const R = g.earth_radius_km;
  const glow = glowTexture();

  // stars (fixed in the scene, not the pivot)
  { const n = 900, f = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const u = Math.random() * 2 - 1, t = Math.random() * 6.283, r = Math.sqrt(1 - u * u), D = 200000;
      f[3 * i] = D * r * Math.cos(t); f[3 * i + 1] = D * u; f[3 * i + 2] = D * r * Math.sin(t) - 20000; }
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(f, 3));
    scene.add(new THREE.Points(geo, new THREE.PointsMaterial({color: 0x9fb4d8, size: 1.3, sizeAttenuation: false, transparent: true, opacity: .55}))); }

  // earth: dark body, graticule, dotted surface, atmosphere
  world.add(new THREE.Mesh(new THREE.SphereGeometry(R * 0.995, 64, 48), new THREE.MeshBasicMaterial({color: 0x0a1c3a})));
  { const n = 2600, f = new Float32Array(n * 3), ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) { const z = 1 - 2 * (i + .5) / n, r = Math.sqrt(1 - z * z), a = i * ga;
      f[3 * i] = R * 1.002 * r * Math.cos(a); f[3 * i + 1] = R * 1.002 * r * Math.sin(a); f[3 * i + 2] = R * 1.002 * z; }
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(f, 3));
    world.add(new THREE.Points(geo, new THREE.PointsMaterial({color: 0x4aa3dc, size: 2, sizeAttenuation: false, transparent: true, opacity: .7}))); }
  const gm = new THREE.LineBasicMaterial({color: 0x2a5d94, transparent: true, opacity: 0.28});
  for (let lat = -60; lat <= 60; lat += 30) {
    const pts = [], z = R * Math.sin(lat * Math.PI / 180), rr = R * Math.cos(lat * Math.PI / 180);
    for (let a = 0; a <= 72; a++) pts.push(new THREE.Vector3(rr * Math.cos(a / 72 * 6.2832), rr * Math.sin(a / 72 * 6.2832), z));
    world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gm));
  }
  for (let lon = 0; lon < 360; lon += 30) {
    const pts = [], l = lon * Math.PI / 180;
    for (let a = 0; a <= 72; a++) { const t = a / 72 * 6.2832 - 3.1416;
      pts.push(new THREE.Vector3(R * Math.cos(t / 2) * Math.cos(l), R * Math.cos(t / 2) * Math.sin(l), R * Math.sin(t / 2))); }
    world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gm));
  }
  const atmo = new THREE.Mesh(new THREE.SphereGeometry(R * 1.16, 48, 32), new THREE.ShaderMaterial({
    transparent: true, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false,
    vertexShader: 'varying vec3 n;void main(){n=normalize(normalMatrix*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader: 'varying vec3 n;void main(){float i=pow(.72-dot(n,vec3(0.,0.,1.)),3.);gl_FragColor=vec4(.22,.7,1.,1.)*i*1.25;}'}));
  pivot.add(atmo);

  // orbits: line + additive point trail for a glowing look, and a moving head
  const heads = [];
  function orbit(arr, colour, head) {
    const pts = arr.map(p => new THREE.Vector3(p[0], p[1], p[2]));
    world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({color: colour, transparent: true, opacity: .9})));
    const f = new Float32Array(pts.length * 3); pts.forEach((p, i) => { f[3 * i] = p.x; f[3 * i + 1] = p.y; f[3 * i + 2] = p.z; });
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(f, 3));
    world.add(new THREE.Points(geo, new THREE.PointsMaterial({color: colour, size: 7, map: glow, sizeAttenuation: false, transparent: true, opacity: .55, depthWrite: false, blending: THREE.AdditiveBlending})));
    if (head) { const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, color: colour, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending}));
      sp.scale.set(1500, 1500, 1); world.add(sp); heads.push({sp, pts, ph: Math.random()}); }
  }
  orbit(g.tracks.primary, 0x38d6f5, true); orbit(g.tracks.threat, 0xf4a261, true);
  if (g.burn && o.burn !== false) {
    const pts = g.burn.points.map(p => new THREE.Vector3(p[0], p[1], p[2]));
    const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({color: 0x3ddc97, dashSize: 220, gapSize: 140}));
    l.computeLineDistances(); world.add(l);
  }
  function points(arr, colour, size, opacity, additive) {
    const f = new Float32Array(arr.length * 3);
    arr.forEach((p, i) => { f[3 * i] = p[0]; f[3 * i + 1] = p[1]; f[3 * i + 2] = p[2]; });
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(f, 3));
    const pt = new THREE.Points(geo, new THREE.PointsMaterial({color: colour, size, sizeAttenuation: false, transparent: true, opacity, depthWrite: false, blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending}));
    world.add(pt); return pt;
  }
  if (o.satellites !== false && g.satellites.length) points(g.satellites.map(s => s.xyz), 0x3ddc97, 6, 1);
  // collision point with pulsing ring
  const cpS = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, color: 0xff5468, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending}));
  cpS.position.set(...g.collision_point); cpS.scale.set(1100, 1100, 1); world.add(cpS);
  const cpCore = new THREE.Mesh(new THREE.SphereGeometry(70, 12, 8), new THREE.MeshBasicMaterial({color: 0xff8a96}));
  cpCore.position.copy(cpS.position); world.add(cpCore);

  // debris layers
  const layers = [];
  if (o.debris) g.snapshots.forEach((s, i) => { const p = points(s.points, [0xffd166, 0xff9f5a, 0xff6f91, 0x7fd6ff][i % 4], 3, 0, true); p.userData.target = 0; layers.push(p); });

  if (o.offsetX) pivot.position.x = o.offsetX;
  if (o.offsetY) pivot.position.y = o.offsetY;
  let drag = false, lx = 0, ly = 0, spin = o.spin ?? 0.0018, on = true, vel = 0;
  const el = renderer.domElement;
  if (o.interactive !== false) {
    el.addEventListener('pointerdown', e => { drag = true; lx = e.clientX; ly = e.clientY; el.setPointerCapture(e.pointerId); el.style.cursor = 'grabbing'; });
    el.addEventListener('pointerup', () => { drag = false; el.style.cursor = 'grab'; });
    el.addEventListener('pointermove', e => { if (!drag) return; vel = (e.clientX - lx) * 0.006; pivot.rotation.y += vel;
      pivot.rotation.x = Math.max(-1.5, Math.min(1.5, pivot.rotation.x + (e.clientY - ly) * 0.006)); lx = e.clientX; ly = e.clientY; });
    el.addEventListener('wheel', e => { e.preventDefault(); dist = Math.max(9000, Math.min(70000, dist * (1 + Math.sign(e.deltaY) * 0.08))); camera.position.z = dist; }, {passive: false});
  }
  function resize() { const W = host.clientWidth, H = host.clientHeight; if (!W || !H) return; renderer.setSize(W, H); camera.aspect = W / H; camera.updateProjectionMatrix(); if (o.onResize) o.onResize(W, H, pivot); }
  new ResizeObserver(resize).observe(host); if (o.onResize) o.onResize(w, h, pivot);
  onVisible(host, v => on = v, {toggle: true, threshold: 0.02});
  let t = 0;
  (function loop() {
    requestAnimationFrame(loop);
    if (!on) return;
    t += 0.016;
    if (!drag && !REDUCED) pivot.rotation.y += spin;
    heads.forEach(h => { const n = h.pts.length - 1, f = ((h.ph + t * 0.04) % 1) * n, i = Math.floor(f), a = h.pts[i], b = h.pts[Math.min(i + 1, n)];
      h.sp.position.lerpVectors(a, b, f - i); });
    const pulse = 1 + 0.35 * Math.sin(t * 3); cpS.scale.set(1100 * pulse, 1100 * pulse, 1);
    layers.forEach(p => { const m = p.material; m.opacity += (p.userData.target - m.opacity) * 0.08; p.visible = m.opacity > 0.01; });
    renderer.render(scene, camera);
  })();
  return {layers, pivot, setSpin: v => spin = v, setLayer(i) { layers.forEach((p, k) => p.userData.target = k === i ? 0.95 : 0); }};
}
function fallbackSvg(host, norad, why) {
  console.warn('globe fallback:', why);
  const img = document.createElement('img'); img.alt = 'static projection of the debris cloud';
  img.src = '/api/globe/' + norad + '/fallback.svg'; return img;
}
let globeData = null;
function getGlobe() {
  if (!B.have_facts) return Promise.reject(new Error('no analysis'));
  return globeData || (globeData = getJsonWhenReady('/api/globe/' + B.norad));
}

/* ---------------------------------------------------------------- hero */
(function hero() {
  // stat counters from real data
  const st = [];
  if (B.burns) st.push([B.burns.n_objects_screened, 'catalogue objects screened per burn', '']);
  if (B.burns) st.push([B.burns.n_screened, 'candidate burns screened in parallel; ' + B.burns.n_feasible + ' meet the target', '']);
  if (B.cons) st.push([B.cons.fragments_true, 'fragments if the two collide', '']);
  const sp = B.speedup && B.speedup.results && B.speedup.results.slice(-1)[0];
  if (sp) st.push([sp.speedup, 'faster on ' + sp.workers + ' workers than on one · ' + B.speedup.context, '×', 1]);
  else if (B.net) st.push([B.net.summary.n_objects, 'objects swept for super-spreaders', '']);
  if (B.cons && st.length < 4) st.push([B.cons.n_sats_ge1_encounter, 'satellites at risk', '']);
  const ul = $('#hero-stats');
  ul.innerHTML = st.slice(0, 4).map(s => `<li><b data-dec="${s[3] || 0}" data-to="${s[0]}">0</b><span>${esc(s[1])}</span></li>`).join('');
  $$('b', ul).forEach(b => { const to = +b.dataset.to, d = +b.dataset.dec; const suf = d ? '<u>×</u>' : '';
    if (REDUCED) { b.innerHTML = (d ? to.toFixed(2) : fmtInt(to)) + suf; return; }
    const t0 = performance.now() + 500;
    (function f(t) { const k = Math.max(0, Math.min(1, (t - t0) / 2200)), v = to * ease(k);
      b.innerHTML = (d ? v.toFixed(2) : fmtInt(v)) + suf; if (k < 1) requestAnimationFrame(f); })(performance.now());
    setTimeout(() => b.innerHTML = (d ? to.toFixed(2) : fmtInt(to)) + suf, 3000);
  });
  if (!B.have_facts) return;
  $('#hero-legend').innerHTML = `<span>${esc(B.event.primary.name)} orbit<i style="background:${C.cyan}"></i></span><span>${esc(B.event.threat.name)} orbit<i style="background:${C.orange}"></i></span><span>closest approach<i style="background:${C.act}"></i></span>`;
  (async () => {
    const host = $('#hero-canvas');
    try {
      const [g] = await Promise.all([getGlobe(), loadThree()]);
      buildGlobe(host, g, {dist: 33000, spin: 0.0012, interactive: false, satellites: false, burn: false,
        onResize: (W, H, pivot) => { pivot.position.x = W > 1150 ? Math.min(8200, W * 4.2) : 0; pivot.position.y = W > 1150 ? 0 : 3200; }});
      host.style.opacity = 0; host.style.transition = 'opacity 1.6s ease'; requestAnimationFrame(() => host.style.opacity = 1);
    } catch (e) {
      console.warn('hero globe unavailable:', e.message);
      $('#hero-legend').textContent = '';
    }
  })();
})();

/* ================================================================ 1. replay */
(function replay() {
  const sel = $('#rp-event'), chart = $('#rp-chart'), card = $('#rp-card'), playBtn = $('#rp-play');
  let steps = [], fin = null, idx = 0, timer = null, started = false, S = null;
  const ymin = -14, ymax = -3, YB = -15.2, W = 900, H = 440, L = 62, Rr = 24, T = 18, Bm = 120, pw = W - L - Rr, ph = H - T - Bm;
  const fmt = r => r <= ymin ? '≤ −14' : r.toFixed(2);
  function build() {
    const t0 = Math.ceil(steps[0].time_to_tca_days);
    const X = t => L + pw * (t0 - t) / t0;
    const Y = r => r <= ymin ? T + ph * (ymax - (ymin - 0.6)) / (ymax - YB) : T + ph * (ymax - r) / (ymax - YB);
    S = {X, Y, t0};
    let s = `<defs><clipPath id="rp-clip"><rect id="rp-cr" x="${L - 4}" y="0" width="0" height="${H}"/></clipPath>
      <linearGradient id="rp-fade" x1="0" x2="1"><stop offset="0" stop-color="${C.cyan}" stop-opacity=".7"/><stop offset="1" stop-color="${C.cyan}"/></linearGradient></defs>`;
    s += `<rect x="${L}" y="${Y(ymin)}" width="${pw}" height="${T + ph - Y(ymin)}" fill="#0f1a30"/>`;
    s += `<text x="${W - Rr - 8}" y="${T + ph - 7}" text-anchor="end" font-size="13" fill="${C.dim}">≤ −14 (≈ zero): hollow markers sit in this band</text>`;
    for (let v = -4; v >= ymin; v -= 2) s += `<line x1="${L}" x2="${W - Rr}" y1="${Y(v)}" y2="${Y(v)}" stroke="${C.line}"/><text x="${L - 10}" y="${Y(v) + 5}" font-size="14" text-anchor="end" fill="${C.mute}" font-family="Geist Mono,monospace">${v}</text>`;
    s += `<rect x="${L}" y="${T}" width="${pw}" height="${ph}" fill="none" stroke="${C.line2}"/>`;
    s += `<text x="16" y="${T + ph / 2}" font-size="14" fill="${C.mute}" transform="rotate(-90 16 ${T + ph / 2})" text-anchor="middle">log10 collision probability (latest CDM)</text>`;
    const ds = t0 > 8 ? 2 : 1;
    for (let d = t0; d >= 0; d -= ds) s += `<line x1="${X(d)}" x2="${X(d)}" y1="${T}" y2="${T + ph}" stroke="${C.line}" stroke-opacity=".6"/><text x="${X(d)}" y="${T + ph + 20}" font-size="14" fill="${C.mute}" text-anchor="middle" font-family="Geist Mono,monospace">${d === 0 ? 'TCA' : d + ' d'}</text>`;
    s += `<text x="${L + pw / 2}" y="${T + ph + 42}" font-size="14" fill="${C.mute}" text-anchor="middle">time to closest approach (decreasing to the right)</text>`;
    s += `<line x1="${L}" x2="${W - Rr}" y1="${Y(-6)}" y2="${Y(-6)}" stroke="${C.act}" stroke-dasharray="6 5" opacity=".8"/><text x="${L + 8}" y="${Y(-6) - 7}" font-size="13" fill="${C.act}">high-risk threshold (−6)</text>`;
    const by = T + ph + 56;
    steps.forEach((st, i) => { const xa = X(st.time_to_tca_days), xb = i < steps.length - 1 ? X(steps[i + 1].time_to_tca_days) : W - Rr;
      s += `<rect class="band" data-i="${i}" x="${xa}" y="${by}" width="${Math.max(xb - xa - 2, 3)}" height="18" rx="3" fill="${ACT[st.action]}" opacity=".16" style="transition:opacity .5s"><title>${st.action}</title></rect>`; });
    s += `<text x="${L}" y="${by + 40}" font-size="13" fill="${C.dim}">decision per warning: MONITOR (blue), WAIT (amber), ACT (red); faint = not yet arrived</text>`;
    const P = steps.map((st, i) => (i ? 'L' : 'M') + X(st.time_to_tca_days).toFixed(1) + ',' + Y(st.latest_risk).toFixed(1)).join('');
    s += `<path d="${P}" fill="none" stroke="${C.dim}" stroke-width="1.5" opacity=".25" stroke-dasharray="3 5"/>`;
    s += `<g clip-path="url(#rp-clip)"><path d="${P}" fill="none" stroke="url(#rp-fade)" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" style="filter:drop-shadow(0 0 6px rgba(56,214,245,.6))"/></g>`;
    steps.forEach((st, i) => { const hol = st.latest_risk <= ymin, c = ACT[st.action];
      s += `<circle class="mk" data-i="${i}" cx="${X(st.time_to_tca_days)}" cy="${Y(st.latest_risk)}" r="6" fill="${hol ? '#050912' : c}" stroke="${hol ? c : '#050912'}" stroke-width="${hol ? 2.5 : 1.5}" opacity="0" style="transition:opacity .4s,r .4s"><title>${st.time_to_tca_days.toFixed(1)} d: risk ${fmt(st.latest_risk)}, ${st.action}</title></circle>`; });
    if (fin) { const fx = X(0) - 10, fy = Y(fin.true_final_risk), col = fin.true_high ? C.act : C.ok;
      s += `<g id="rp-fin" opacity="0" style="transition:opacity .8s"><path d="M${fx},${fy - 11}L${fx + 10},${fy}L${fx},${fy + 11}L${fx - 10},${fy}Z" fill="${col}" stroke="#fff" stroke-width="2"/>
        <text x="${fx - 18}" y="${fy + (fy < T + 34 ? 20 : -14)}" font-size="14" text-anchor="end" font-weight="600" fill="#fff">what actually happened: ${fmt(fin.true_final_risk)}</text></g>`; }
    chart.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="risk over time">${s}</svg>`;
    chart.firstChild.style.maxHeight = '560px';
  }
  function update(prev) {
    if (!steps.length) return;
    const d = steps[idx], done = idx === steps.length - 1, {X} = S;
    $('#rp-cr').setAttribute('width', (idx === 0 ? 8 : X(d.time_to_tca_days) - L + 14));
    $('#rp-cr').style.transition = 'width 1s cubic-bezier(.16,1,.3,1)';
    $$('.mk', chart).forEach(m => { const i = +m.dataset.i; m.setAttribute('opacity', i <= idx ? 1 : 0.2); m.setAttribute('r', i === idx ? 9 : 5.5); });
    $$('.band', chart).forEach(b => b.setAttribute('opacity', +b.dataset.i <= idx ? 0.95 : 0.16));
    const f = $('#rp-fin'); if (f) f.setAttribute('opacity', done ? 1 : 0);
    const changed = prev !== idx || !card.firstChild;
    let h = `<div><span class="badge-xl ${d.action.toLowerCase()} ${changed ? 'pop' : ''}">${d.action}</span></div>
      <div class="big"><b>${d.time_to_tca_days.toFixed(1)} d</b> to closest approach &middot; warning ${d.n_cdms} of ${steps.length}</div>
      <div class="metrics"><div><small>latest risk</small><b>${fmt(d.latest_risk)}</b></div><div><small>predicted</small><b>${fmt(d.predicted_risk)}</b></div><div><small>P(high)</small><b>${Math.round(100 * d.p_high)}%</b></div></div>
      <ul>${d.reasons.map((r, i) => `<li style="animation-delay:${changed ? i * 160 : 0}ms">${esc(r)}</li>`).join('')}</ul>`;
    if (fin && done) { const ok = fin.true_high ? d.action === 'ACT' : d.action !== 'ACT';
      h += `<div class="outcome ${ok ? 'out-ok' : 'out-bad'}"><b>Actual outcome: ${fin.true_high ? 'high risk' : 'low risk'} (${fmt(fin.true_final_risk)})</b><br>Final decision was ${d.action}: ` +
        (fin.true_high ? (d.action === 'ACT' ? 'correctly flagged.' : 'a miss: the model did not recommend action.') : (d.action === 'ACT' ? 'a false alarm.' : 'correctly dismissed.')) + '</div>'; }
    else h += `<div class="outcome mute">Press Play to receive the warnings one by one. The actual outcome appears at the right edge.</div>`;
    card.innerHTML = h;
    playBtn.textContent = timer ? 'Pause' : (done ? 'Replay' : 'Play');
  }
  const stop = () => { if (timer) { clearInterval(timer); timer = null; } };
  function step() { const p = idx; if (idx < steps.length - 1) idx++; if (idx >= steps.length - 1) stop(); update(p); }
  function play() { if (timer) { stop(); update(idx); return; } if (idx >= steps.length - 1) { idx = 0; update(-1); } timer = setInterval(step, 1700); update(idx); }
  async function load(id) {
    stop(); chart.innerHTML = '<p class="mute">Loading replay&hellip;</p>';
    const r = await fetch('/api/replay/' + id);
    if (!r.ok) { chart.innerHTML = `<div class="empty slim"><p>Replay data not available (${r.status}).</p></div>`; return; }
    const data = await r.json(); steps = data.steps.filter(s => !s.final); fin = data.steps.find(s => s.final) || null; idx = 0;
    build(); update(-1);
    if (started) setTimeout(play, 600);
  }
  playBtn.onclick = play;
  $('#rp-step').onclick = () => { stop(); step(); };
  $('#rp-reset').onclick = () => { stop(); idx = 0; update(-1); };
  sel.onchange = () => { const o = sel.selectedOptions[0]; $('#rp-title').textContent = o ? o.dataset.sum : ''; load(sel.value); };
  onVisible($('#warning'), () => { started = true; if (steps.length && !timer && idx === 0) play(); }, {threshold: 0.35});
  (async () => {
    try {
      const picks = await getJsonWhenReady('/api/replay/demo');
      sel.innerHTML = picks.map(p => `<option value="${p.event_id}" data-sum="${esc(p.title + ' (' + p.summary.n_steps + ' CDMs, final action ' + p.summary.final_action + ')')}">Event ${p.event_id}: ${esc(p.title)}</option>`).join('');
      if (picks.length) sel.onchange(); else chart.innerHTML = '<div class="empty slim"><p>No replay events available.</p></div>';
    } catch (e) { chart.innerHTML = `<div class="empty slim"><p>Replay unavailable: ${esc(e.message)}</p></div>`; }
  })();
})();

/* ================================================================ 2. decision meters */
(function decision() {
  const m = $('#d-meters'); if (!m) return;
  const p = +m.dataset.p, lo = +m.dataset.lo, hi = +m.dataset.hi, pred = +m.dataset.pred, col = C[m.dataset.action] || C.cyan;
  const colAct = {act: C.act, wait: C.wait, monitor: C.monitor}[m.dataset.action];
  // thresholds parsed from the model's own reason text
  const txt = $$('.reasons li').map(l => l.textContent).join(' ');
  const a = /ACT if >= ([0-9.]+)/.exec(txt), w = /WAIT if >= ([0-9.]+)/.exec(txt);
  const tAct = a ? +a[1] : 0.09, tWait = w ? +w[1] : 0.04;
  const GW = 700, sx = v => 20 + (GW - 40) * Math.sqrt(v);        // square-root axis so the small thresholds stay legible
  let g = `<rect x="20" y="30" width="${sx(tWait) - 20}" height="16" rx="3" fill="${C.monitor}" opacity=".35"/>
    <rect x="${sx(tWait)}" y="30" width="${sx(tAct) - sx(tWait)}" height="16" fill="${C.wait}" opacity=".45"/>
    <rect x="${sx(tAct)}" y="30" width="${GW - 20 - sx(tAct)}" height="16" rx="3" fill="${C.act}" opacity=".4"/>
    <text x="${(20 + sx(tWait)) / 2}" y="68" font-size="14" fill="${C.monitor}" text-anchor="middle">MONITOR</text>
    <text x="${(sx(tWait) + sx(tAct)) / 2}" y="68" font-size="14" fill="${C.wait}" text-anchor="middle">WAIT</text>
    <text x="${(sx(tAct) + GW - 20) / 2}" y="68" font-size="14" fill="${C.act}" text-anchor="middle">ACT</text>
    <g id="g-mk" style="transition:transform 1.4s cubic-bezier(.16,1,.3,1)" transform="translate(20,0)"><path d="M0,22 L-9,6 L9,6Z" fill="#fff"/><line x1="0" x2="0" y1="22" y2="52" stroke="#fff" stroke-width="2.5"/></g>
    <text x="20" y="104" font-size="13" fill="${C.dim}">probability that the final risk is high (square-root scale)</text>`;
  $('#d-gauge').innerHTML = svg(GW, 112, g, 'P(high risk) gauge');
  const RW = 700, ax0 = -20, ax1 = -2, rx = v => 20 + (RW - 40) * (Math.max(ax0, Math.min(ax1, v)) - ax0) / (ax1 - ax0);
  let r = `<line x1="20" x2="${RW - 20}" y1="40" y2="40" stroke="${C.line2}" stroke-width="2"/>`;
  for (let v = -20; v <= -2; v += 4) r += `<line x1="${rx(v)}" x2="${rx(v)}" y1="34" y2="46" stroke="${C.dim}"/><text x="${rx(v)}" y="70" font-size="13" fill="${C.dim}" text-anchor="middle" font-family="Geist Mono,monospace">${v}</text>`;
  r += `<line x1="${rx(-6)}" x2="${rx(-6)}" y1="14" y2="50" stroke="${C.act}" stroke-dasharray="4 3"/><text x="${rx(-6) + 6}" y="20" font-size="13" fill="${C.act}">−6 high risk</text>`;
  r += `<rect id="r-int" x="${rx(lo)}" y="32" width="0" height="16" rx="8" fill="${colAct}" opacity=".85" style="transition:width 1.4s cubic-bezier(.16,1,.3,1)"/>
    <circle cx="${rx(pred)}" cy="40" r="7" fill="#fff" stroke="#050912" stroke-width="2"/>
    <text x="20" y="96" font-size="13" fill="${C.dim}">80% interval of log10 Pc (bar) and predicted value (dot)</text>`;
  $('#d-range').innerHTML = svg(RW, 104, r, 'prediction interval');
  onVisible(m, () => setTimeout(() => {
    $('#g-mk').setAttribute('transform', `translate(${sx(p)},0)`);
    $('#r-int').setAttribute('width', Math.max(10, rx(hi) - rx(lo)));
  }, 250));
})();

/* ================================================================ 3. dodge */
(function dodge() {
  const burns = (B.burns && B.burns.top) || [], host = $('#diag'); if (!burns.length || !host) return;
  const base = B.burns.baseline_miss_km, target = B.burns.target_km;
  const S = 560, cx = S / 2, cy = S / 2, rmax = Math.max(target * 1.15, ...burns.map(b => b.miss_km_threat)) * 1.08, k = (S / 2 - 34) / rmax;
  const pos = (i, r) => { const ang = (-90 + (i + 1) * (360 / (burns.length + 1))) * Math.PI / 180; return [cx + r * k * Math.cos(ang), cy + r * k * Math.sin(ang)]; };
  let s = `<circle cx="${cx}" cy="${cy}" r="${target * k}" fill="rgba(61,220,151,.05)" stroke="${C.ok}" stroke-dasharray="6 6" opacity=".7"/>
    <text x="${cx}" y="${cy - target * k - 8}" font-size="14" fill="${C.ok}" text-anchor="middle">target miss ${target.toFixed(0)} km</text>
    <circle cx="${cx}" cy="${cy}" r="${base * k}" fill="none" stroke="${C.act}" stroke-width="1.5" opacity=".8"/>
    <text x="${cx}" y="${cy + base * k + 18}" font-size="14" fill="${C.act}" text-anchor="middle">screener baseline miss ${base.toFixed(2)} km</text>
    <circle cx="${cx}" cy="${cy}" r="9" fill="${C.orange}"/><circle cx="${cx}" cy="${cy}" r="22" fill="${C.orange}" opacity=".15"/>
    <text x="${cx + 16}" y="${cy + 5}" font-size="14" fill="${C.orange}">threat</text>`;
  s += '<g id="d-links"></g>';
  burns.forEach((b, i) => { const [x, y] = pos(i, b.miss_km_threat), c = b.new_conjunctions ? C.wait : b.feasible ? C.ok : C.dim;
    s += `<g class="bd" data-i="${i}" style="cursor:pointer"><circle class="dot" cx="${x}" cy="${y}" r="9" fill="${c}" stroke="#050912" stroke-width="2"/>${b.new_conjunctions ? `<circle cx="${x}" cy="${y}" r="15" fill="none" stroke="${C.wait}" stroke-width="2" stroke-dasharray="3 3"/>` : ''}
      <text x="${x}" y="${y - 17}" font-size="13" fill="${C.mute}" text-anchor="middle" font-family="Geist Mono,monospace">${i + 1}</text></g>`; });
  s += `<g id="d-sel" opacity="0"><circle id="d-selc" r="16" fill="none" stroke="#fff" stroke-width="2.5"/></g>`;
  host.innerHTML = svg(S, S, s, 'close-approach diagram: miss distance from the threat for each burn');
  const info = $('#diag-info'), rows = $$('#burn-table tbody tr');
  function pick(i) {
    const b = burns[i], [x, y] = pos(i, b.miss_km_threat), [x0, y0] = pos(i, base);
    rows.forEach((r, j) => r.classList.toggle('sel', j === i));
    $('#d-links').innerHTML = `<line x1="${x0}" y1="${y0}" x2="${x}" y2="${y}" stroke="#fff" stroke-width="2" stroke-dasharray="${Math.hypot(x - x0, y - y0)}" stroke-dashoffset="${Math.hypot(x - x0, y - y0)}"><animate attributeName="stroke-dashoffset" to="0" dur="${REDUCED ? 0.01 : 0.8}s" fill="freeze"/></line>
      <circle cx="${x0}" cy="${y0}" r="6" fill="none" stroke="${C.act}" stroke-width="2"/>`;
    const sc = $('#d-sel'); sc.setAttribute('opacity', 1); const c = $('#d-selc'); c.setAttribute('cx', x); c.setAttribute('cy', y);
    $$('.bd .dot', host).forEach((d, j) => d.setAttribute('r', j === i ? 12 : 9));
    info.innerHTML = `<b class="mono">${esc(b.burn_id)}</b> &middot; ${esc(b.direction)}, ${b.dv_mps} m/s<br>Miss grows from ${base.toFixed(2)} to <b class="num">${b.miss_km_threat.toFixed(2)} km</b>` +
      (b.new_conjunctions ? `<br><span class="warnline">Creates ${b.new_conjunctions} new conjunction${b.new_conjunctions > 1 ? 's' : ''}: this dodge trades one problem for another.</span>`
        : `<br><span class="goodline">No new close approaches created.</span>`) + (b.feasible ? '' : '<br><span class="mute">Does not reach the target miss.</span>');
  }
  rows.forEach((r, i) => { r.onclick = () => pick(i); r.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(i); } }; });
  $$('.bd', host).forEach(g => g.onclick = () => pick(+g.dataset.i));
  const best = burns.findIndex(b => b.feasible && !b.new_conjunctions); pick(best >= 0 ? best : 0);
})();

/* ================================================================ 4. impact */
(function impact() {
  const host = $('#globe-canvas');
  if (host) (async () => {
    const msg = $('#globe-msg');
    try {
      const [g] = await Promise.all([getGlobe(), loadThree()]);
      const gl = buildGlobe(host, g, {dist: 29500, debris: true, spin: 0.0016, offsetY: 1900});
      msg.hidden = true;
      const days = g.snapshots.map(s => s.day), range = $('#sc-range'), dayEl = $('#sc-day'), ticks = $('#sc-ticks');
      range.max = days.length - 1; ticks.innerHTML = days.map((d, i) => `<span data-i="${i}">${d} d</span>`).join('');
      $('#scrub').hidden = false;
      let cur = 0, auto = true, timer = null;
      const set = i => { cur = i; range.value = i; gl.setLayer(i); dayEl.textContent = days[i] + (days[i] === 1 ? ' day' : ' days');
        $$('span', ticks).forEach((t, j) => t.classList.toggle('on', j === i)); };
      const run = () => { clearInterval(timer); timer = setInterval(() => { if (auto && inView) set((cur + 1) % days.length); }, 2600); };
      let inView = false; onVisible(host, v => inView = v, {toggle: true, threshold: 0.3});
      range.oninput = () => { auto = false; $('#sc-play').innerHTML = '&#9654;'; set(+range.value); };
      $('#sc-play').onclick = e => { auto = !auto; e.currentTarget.innerHTML = auto ? '&#10073;&#10073;' : '&#9654;'; e.currentTarget.setAttribute('aria-label', auto ? 'Pause auto-play' : 'Start auto-play'); };
      set(0); run();
    } catch (e) {
      msg.hidden = true;
      const fb = $('#globe-fallback'); if (!fb) return;
      $('#globe-canvas').style.display = 'none';
      fb.prepend(fallbackSvg(host, B.norad, e.message)); fb.hidden = false;
    }
  })();

  // constellation bars
  const bars = $('#bars');
  if (bars && B.cons) {
    const rows = Object.entries(B.cons.exposed_by_constellation || {}).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const vmax = Math.max(...rows.map(r => r[1]), 1), LW = 190, Wd = 760, rh = 58;
    let s = rows.map((r, i) => `<g class="bar"><text x="${LW - 14}" y="${i * rh + 33}" text-anchor="end" font-size="17" fill="#d3def2">${esc(r[0])}</text>
      <rect x="${LW}" y="${i * rh + 10}" width="${Wd - LW - 70}" height="34" rx="6" fill="#0f1a30"/>
      <rect class="fill" x="${LW}" y="${i * rh + 10}" width="0" height="34" rx="6" fill="${C.cyan}" data-w="${(Wd - LW - 70) * r[1] / vmax}"/>
      <text x="${Wd - 8}" y="${i * rh + 33}" text-anchor="end" font-size="17" font-family="Geist Mono,monospace" fill="#fff">${r[1]}</text></g>`).join('');
    bars.innerHTML = svg(Wd, rows.length * rh + 4, s, 'affected satellites by constellation');
    onVisible(bars, () => $$('.fill', bars).forEach((f, i) => setTimeout(() => f.setAttribute('width', f.dataset.w), i * 70)));
  }

  // slope chart
  const slope = $('#slope');
  if (slope && B.survey.length) {
    const rows = B.survey, n = Math.max(...rows.map(r => Math.max(r.rank_pc, r.rank_harm)));
    const Wd = 760, top = 44, st = 30, xl = 250, xr = Wd - 250, Hh = top + st * n + 10;
    let s = `<text x="${xl}" y="20" text-anchor="end" font-size="16" font-weight="600" fill="#fff">Rank by probability</text><text x="${xr}" y="20" font-size="16" font-weight="600" fill="#fff">Rank by harm</text>`;
    rows.slice().sort((a, b) => a.rank_pc - b.rank_pc).forEach((r, i) => {
      const y1 = top + st * (r.rank_pc - 1), y2 = top + st * (r.rank_harm - 1), sh = r.rank_pc - r.rank_harm, sel = r.norad === B.norad;
      const c = sel ? '#fff' : sh >= 3 ? C.act : sh <= -3 ? C.ok : '#5b6d8f', nm = esc(String(r.primary).slice(0, 18));
      s += `<g class="sl" data-i="${i}"><line class="ln" x1="${xl + 10}" y1="${y1}" x2="${xr - 10}" y2="${y2}" stroke="${c}" stroke-width="${sel ? 3.5 : 2}" stroke-linecap="round"/>
        <line x1="${xl + 10}" y1="${y1}" x2="${xr - 10}" y2="${y2}" stroke="transparent" stroke-width="14"/>
        <text class="lbl" x="${xl}" y="${y1 + 5}" text-anchor="end" font-size="14" fill="${c === '#5b6d8f' ? C.mute : c}">${r.rank_pc} ${nm}</text>
        <text class="lbl" x="${xr}" y="${y2 + 5}" font-size="14" fill="${c === '#5b6d8f' ? C.mute : c}">${r.rank_harm} ${nm}</text><title>${esc(r.primary)} vs ${esc(r.threat)}: rank ${r.rank_pc} by probability, ${r.rank_harm} by harm</title></g>`;
    });
    slope.innerHTML = svg(Wd, Hh, s, 'rank by probability versus rank by harm');
    $$('.sl', slope).forEach(g => {
      g.onmouseenter = () => { slope.classList.add('hov'); $$('.ln,.lbl', g).forEach(e => e.classList.add('on')); $$('.ln', g).forEach(e => e.setAttribute('stroke-width', 5)); };
      g.onmouseleave = () => { slope.classList.remove('hov'); $$('.ln,.lbl', g).forEach(e => e.classList.remove('on')); $$('.ln', g).forEach(e => e.setAttribute('stroke-width', 2)); };
    });
  }
})();

/* ================================================================ 5. network scatter */
(function network() {
  const host = $('#net'), net = B.net; if (!host || !net) return;
  const nodes = net.nodes, byId = new Map(nodes.map(n => [n.norad, n]));
  const TC = {PAYLOAD: C.cyan, 'ROCKET BODY': C.orange, DEBRIS: C.act, UNKNOWN: C.mute};
  const types = [...new Set(nodes.map(n => n.type))];
  let ft = new Set(types), mind = 0;
  const maxDeg = Math.max(...nodes.map(n => n.degree));
  const minDeg0 = Math.min(...nodes.map(n => n.degree)), deg = $('#deg-min'); deg.min = minDeg0; deg.max = maxDeg; deg.value = minDeg0; $('#deg-val').textContent = minDeg0;
  $('#type-chips').innerHTML = types.map(t => `<button class="chipbtn on" data-t="${esc(t)}">${esc(t.toLowerCase())}</button>`).join('');
  const W = 1000, Hh = 560, L = 76, Rr = 24, T = 20, Bm = 64;
  const jit = (n, k) => ((((n.norad * 2654435761 >>> 0) >> k) % 1000) / 1000 - 0.5);
  const alt = n => (n.perigee_km + n.apogee_km) / 2 + jit(n, 3) * 3.2;
  const incl = n => n.inclination_deg + jit(n, 11) * 3.5;
  const a0 = Math.floor(Math.min(...nodes.map(alt)) / 5) * 5 - 5, a1 = Math.ceil(Math.max(...nodes.map(alt)) / 5) * 5 + 5;
  const i0 = Math.floor(Math.min(...nodes.map(incl)) / 10) * 10 - 5, i1 = Math.ceil(Math.max(...nodes.map(incl)) / 10) * 10 + 5;
  const X = v => L + (W - L - Rr) * (v - a0) / ((a1 - a0) || 1), Y = v => T + (Hh - T - Bm) * (1 - (v - i0) / ((i1 - i0) || 1));
  const minDeg = Math.min(...nodes.map(n => n.degree)), Rd = d => 4 + 9 * Math.sqrt((d - minDeg) / ((maxDeg - minDeg) || 1));
  let s = '';
  const tk = (lo, hi, k) => { const o = [], st = (hi - lo) / k; for (let i = 0; i <= k; i++) o.push(lo + st * i); return o; };
  tk(a0, a1, 6).forEach(v => s += `<line x1="${X(v)}" x2="${X(v)}" y1="${T}" y2="${Hh - Bm}" stroke="${C.line}"/><text x="${X(v)}" y="${Hh - Bm + 24}" text-anchor="middle" font-size="14" fill="${C.mute}" font-family="Geist Mono,monospace">${Math.round(v)}</text>`);
  tk(i0, i1, 6).forEach(v => s += `<line x1="${L}" x2="${W - Rr}" y1="${Y(v)}" y2="${Y(v)}" stroke="${C.line}"/><text x="${L - 10}" y="${Y(v) + 5}" text-anchor="end" font-size="14" fill="${C.mute}" font-family="Geist Mono,monospace">${Math.round(v)}</text>`);
  s += `<text x="${(L + W - Rr) / 2}" y="${Hh - 12}" text-anchor="middle" font-size="15" fill="${C.mute}">mean altitude (km)</text><text x="18" y="${(T + Hh - Bm) / 2}" font-size="15" fill="${C.mute}" text-anchor="middle" transform="rotate(-90 18 ${(T + Hh - Bm) / 2})">inclination (deg)</text>`;
  s += '<g id="n-edges">' + net.edges.filter(e => byId.has(e[0]) && byId.has(e[1])).slice(0, 500).map(e => { const a = byId.get(e[0]), b = byId.get(e[1]);
    return `<line data-a="${a.norad}" data-b="${b.norad}" x1="${X(alt(a))}" y1="${Y(incl(a))}" x2="${X(alt(b))}" y2="${Y(incl(b))}" stroke="${C.cyan}" stroke-opacity=".08"/>`; }).join('') + '</g>';
  s += '<g id="n-nodes">' + nodes.slice().sort((a, b) => b.degree - a.degree).map(n =>
    `<circle data-n="${n.norad}" cx="${X(alt(n))}" cy="${Y(incl(n))}" r="0" data-r="${Rd(n.degree)}" fill="${TC[n.type] || C.cyan}" fill-opacity=".5" stroke="${TC[n.type] || C.cyan}" stroke-width="1" style="cursor:pointer"/>`).join('') + '</g>';
  host.innerHTML = svg(W, Hh, s, 'super-spreaders: altitude versus inclination, size by number of close approaches');
  const circles = $$('circle', host), tip = $('#net-tip'), wrap = $('#net-wrap');
  const apply = () => { circles.forEach(c => { const n = byId.get(+c.dataset.n), ok = ft.has(n.type) && n.degree >= mind; c.style.opacity = ok ? 1 : 0.05; c.style.pointerEvents = ok ? 'auto' : 'none'; });
    $$('#n-edges line', host).forEach(l => { const a = byId.get(+l.dataset.a), b = byId.get(+l.dataset.b); l.style.opacity = (ft.has(a.type) && ft.has(b.type) && a.degree >= mind && b.degree >= mind) ? 1 : 0; }); };
  onVisible(host, () => circles.forEach((c, i) => setTimeout(() => c.setAttribute('r', c.dataset.r), i * 4)));
  circles.forEach(c => {
    c.onmouseenter = c.onmousemove = e => { const n = byId.get(+c.dataset.n), r = wrap.getBoundingClientRect();
      tip.innerHTML = `<b>${esc(n.name)}</b><span>${esc(n.type.toLowerCase())}</span><span>degree ${n.degree} &middot; score ${n.score.toFixed(3)}</span><span>${Math.round(alt(n))} km &middot; ${n.inclination_deg.toFixed(1)}&deg;</span>`;
      tip.hidden = false; const tx = e.clientX - r.left + 18, ty = e.clientY - r.top + 12;
      tip.style.left = Math.min(tx, r.width - 230) + 'px'; tip.style.top = Math.min(ty, r.height - 120) + 'px';
      $$('#n-edges line', host).forEach(l => l.setAttribute('stroke-opacity', (+l.dataset.a === n.norad || +l.dataset.b === n.norad) ? .7 : .05));
      const tr = $(`#net-table tr[data-norad="${n.norad}"]`); if (tr) tr.classList.add('hl'); };
    c.onmouseleave = () => { tip.hidden = true; $$('#net-edges line, #n-edges line', host).forEach(l => l.setAttribute('stroke-opacity', .08)); $$('#net-table tr.hl').forEach(r => r.classList.remove('hl')); };
  });
  $$('#net-table tr[data-norad]').forEach(r => { r.onmouseenter = () => { const c = $(`circle[data-n="${r.dataset.norad}"]`, host); if (c) { c.setAttribute('r', +c.dataset.r + 6); c.setAttribute('fill-opacity', 1); } };
    r.onmouseleave = () => { const c = $(`circle[data-n="${r.dataset.norad}"]`, host); if (c) { c.setAttribute('r', c.dataset.r); c.setAttribute('fill-opacity', .55); } }; });
  $$('#type-chips .chipbtn').forEach(b => b.onclick = () => { const t = b.dataset.t;
    if (ft.has(t) && ft.size > 1) { ft.delete(t); b.classList.remove('on'); } else { ft.add(t); b.classList.add('on'); } apply(); });
  deg.oninput = () => { mind = +deg.value; $('#deg-val').textContent = mind; apply(); };
})();

/* ================================================================ 6. brief typewriter */
(function brief() {
  const body = $('#brief-body'); if (!body) return;
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT), items = [];
  let n; while ((n = walker.nextNode())) if (n.nodeValue.trim()) items.push([n, n.nodeValue]);
  if (REDUCED || !items.length) return;
  items.forEach(([nd]) => nd.nodeValue = '');
  const caret = document.createElement('span'); caret.className = 'caret';
  const total = items.reduce((a, i) => a + i[1].length, 0), dur = Math.min(5500, Math.max(2500, total * 6));
  let skip = false; body.style.cursor = 'pointer'; body.title = 'Click to skip'; body.onclick = () => skip = true;
  onVisible(body, () => {
    const t0 = performance.now();
    (function f(t) {
      let k = skip ? 1 : Math.min(1, (t - t0) / dur), shown = Math.floor(k * total), done = 0, last = null;
      for (const [nd, full] of items) { const take = Math.max(0, Math.min(full.length, shown - done)); nd.nodeValue = full.slice(0, take); if (take > 0) last = nd; done += full.length; }
      if (last) last.parentNode.insertBefore(caret, last.nextSibling);
      if (k < 1) requestAnimationFrame(f); else setTimeout(() => caret.remove(), 1500);
    })(t0);
  }, {threshold: 0.3});
})();

/* ================================================================ 7. speed-up chart */
(function speed() {
  const host = $('#speed-chart'), sp = B.speedup; if (!host || !sp) return;
  const res = sp.results, vmax = Math.max(...res.map(r => r.speedup), res[res.length - 1].workers);
  const Wd = 900, rh = 62, LW = 120, bw = Wd - LW - 190;
  let s = res.map((r, i) => `<text x="${LW - 16}" y="${i * rh + 36}" text-anchor="end" font-size="18" fill="#d3def2" font-family="Geist Mono,monospace">${r.workers} ${r.workers === 1 ? 'core' : 'cores'}</text>
    <rect x="${LW}" y="${i * rh + 10}" width="${bw}" height="38" rx="7" fill="#0f1a30"/>
    <rect class="sbar" x="${LW}" y="${i * rh + 10}" width="0" height="38" rx="7" fill="${i === res.length - 1 ? C.cyan : '#2a7f94'}" data-w="${bw * r.speedup / vmax}"/>
    <text x="${Wd - 6}" y="${i * rh + 37}" text-anchor="end" font-size="22" font-family="Geist Mono,monospace" fill="#fff">${r.speedup.toFixed(2)}× <tspan font-size="15" fill="${C.mute}">${r.wall_s.toFixed(1)} s</tspan></text>`).join('');
  s += `<line x1="${LW + bw}" x2="${LW + bw}" y1="2" y2="${res.length * rh - 6}" stroke="${C.dim}" stroke-dasharray="4 4"/><text x="${LW + bw - 6}" y="${res.length * rh + 14}" text-anchor="end" font-size="13" fill="${C.dim}">ideal linear scaling</text>`;
  host.innerHTML = svg(Wd, res.length * rh + 24, s, 'parallel speed-up versus cores');
  onVisible(host, () => $$('.sbar', host).forEach((b, i) => setTimeout(() => b.setAttribute('width', b.dataset.w), i * 120)));
})();

/* ?only=<section-id> shows one section (for stills / evidence screenshots) */
(function only() {
  const m = /[?&]only=([\w-]+)/.exec(location.search); if (!m) return;
  $$('main > section').forEach(s => { if (s.id !== m[1]) s.style.display = 'none'; else { s.querySelectorAll('.rv').forEach(e => e.classList.add('in')); } });
})();
