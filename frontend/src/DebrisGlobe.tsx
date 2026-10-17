import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { geoEquirectangular, geoGraticule10, geoPath } from 'd3-geo';
import { feature } from 'topojson-client';
import type { Topology } from 'topojson-specification';
import landTopology from 'world-atlas/land-110m.json';
import { Pause, Play } from 'lucide-react';
import { Empty, Loading, Notice } from './ui';
import { number } from './api';
import type { Json } from './api';

const AMBER = '#FFB547';
const TAU = 2 * Math.PI;
const FALLBACK_RE_KM = 6378.137;

type Elements = {a_km: number[], e: number[], m0_rad: number[], p: number[], q: number[], n_rad_s?: number[]};
type Kepler = {count: number, a: Float64Array, e: Float64Array, m0: Float64Array, n: Float64Array, p: Float64Array, q: Float64Array, raanDot: Float64Array, argpDot: Float64Array};

/** Per-orbit constants for the client-side copy of the engine's propagation (two-body + J2 secular rates, no drag). */
function prepare(el: Elements, mu: number, re: number, j2: number): Kepler {
  const count = el.a_km.length;
  const k: Kepler = {count, a: Float64Array.from(el.a_km), e: Float64Array.from(el.e), m0: Float64Array.from(el.m0_rad), n: new Float64Array(count),
    p: Float64Array.from(el.p), q: Float64Array.from(el.q), raanDot: new Float64Array(count), argpDot: new Float64Array(count)};
  for (let i = 0; i < count; i++) {
    const a = k.a[i], e = k.e[i];
    const nk = Math.sqrt(mu / (a * a * a));
    k.n[i] = el.n_rad_s ? el.n_rad_s[i] : nk;
    const cosI = k.p[3 * i] * k.q[3 * i + 1] - k.p[3 * i + 1] * k.q[3 * i]; // z of w = p x q
    const semi = a * (1 - e * e);
    const f = j2 * (re / semi) ** 2 * nk;
    k.raanDot[i] = -1.5 * f * cosI;
    k.argpDot[i] = 0.75 * f * (5 * cosI * cosI - 1);
  }
  return k;
}

/** ECI km at t seconds after the event, written as three.js scene units (Earth radius = 1; ECI z -> up). */
function propagateInto(k: Kepler, tSeconds: number, re: number, out: Float32Array) {
  for (let i = 0; i < k.count; i++) {
    const a = k.a[i], e = k.e[i];
    const dw = k.argpDot[i] * tSeconds, dO = k.raanDot[i] * tSeconds;
    const cw = Math.cos(dw), sw = Math.sin(dw), cO = Math.cos(dO), sO = Math.sin(dO);
    const px = k.p[3 * i], py = k.p[3 * i + 1], pz = k.p[3 * i + 2], qx = k.q[3 * i], qy = k.q[3 * i + 1], qz = k.q[3 * i + 2];
    const p0 = cw * px + sw * qx, p1 = cw * py + sw * qy, p2 = cw * pz + sw * qz;
    const q0 = -sw * px + cw * qx, q1 = -sw * py + cw * qy, q2 = -sw * pz + cw * qz;
    const pxr = cO * p0 - sO * p1, pyr = sO * p0 + cO * p1, qxr = cO * q0 - sO * q1, qyr = sO * q0 + cO * q1;
    let m = (k.m0[i] + k.n[i] * tSeconds) % TAU;
    if (m < 0) m += TAU;
    let big = e < 0.8 ? m : Math.PI;
    for (let it = 0; it < 12; it++) big -= (big - e * Math.sin(big) - m) / (1 - e * Math.cos(big));
    const x = a * (Math.cos(big) - e), y = a * Math.sqrt(1 - e * e) * Math.sin(big);
    const ex = x * pxr + y * qxr, ey = x * pyr + y * qyr, ez = x * p2 + y * q2;
    out[3 * i] = ex / re; out[3 * i + 1] = ez / re; out[3 * i + 2] = -ey / re;
  }
}

/** Slider position (0..6, one unit per published epoch) to hours after the event. */
function hoursAt(pos: number, epochs: number[]) {
  const i = Math.min(Math.floor(pos), epochs.length - 2);
  return epochs[i] + (epochs[i + 1] - epochs[i]) * (pos - i);
}
function timeLabel(h: number) {
  if (h < 1) return `T+${Math.round(h * 60)} min`;
  if (h < 48) return `T+${h < 10 ? h.toFixed(1).replace(/\.0$/, '') : Math.round(h)} h`;
  const d = h / 24;
  return `T+${d < 10 ? d.toFixed(1).replace(/\.0$/, '') : Math.round(d)} d`;
}
function gmstRad(utcMs: number) {
  const jd = utcMs / 86400000 + 2440587.5;
  return (((280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360) + 360) % 360 * Math.PI / 180;
}

function earthTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 2048; canvas.height = 1024;
  const ctx = canvas.getContext('2d')!;
  const path = geoPath(geoEquirectangular().scale(1024 / Math.PI).translate([1024, 512]), ctx);
  ctx.fillStyle = '#0a1a38'; ctx.fillRect(0, 0, 2048, 1024);
  ctx.beginPath(); path(geoGraticule10()); ctx.strokeStyle = 'rgba(120,160,255,0.12)'; ctx.lineWidth = 1; ctx.stroke();
  const topology = landTopology as unknown as Topology;
  ctx.beginPath(); path(feature(topology, topology.objects.land) as never); ctx.fillStyle = '#24395f'; ctx.fill();
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace; texture.anisotropy = 4;
  return texture;
}

function spriteTexture(draw: (ctx: CanvasRenderingContext2D, size: number) => void) {
  const size = 64;
  const canvas = document.createElement('canvas'); canvas.width = size; canvas.height = size;
  draw(canvas.getContext('2d')!, size);
  return new THREE.CanvasTexture(canvas);
}
const glowTexture = () => spriteTexture((ctx, s) => {
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.25, 'rgba(255,255,255,0.55)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, s, s);
});
const ringTexture = () => spriteTexture((ctx, s) => {
  ctx.strokeStyle = '#fff'; ctx.lineWidth = s * 0.09; ctx.shadowColor = '#fff'; ctx.shadowBlur = s * 0.08;
  ctx.beginPath(); ctx.arc(s / 2, s / 2, s * 0.36, 0, TAU); ctx.stroke();
});

const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

function Stage({data}: {data: Json}) {
  const host = useRef<HTMLDivElement>(null);
  const epochs: number[] = data.epochs_h;
  const [pos, setPos] = useState(2); // T+6 h: the stream along the orbit is already visible
  const [playing, setPlaying] = useState(false);
  const posRef = useRef(pos);
  const playRef = useRef(false);
  const applyRef = useRef<(p: number) => void>(() => undefined);
  posRef.current = pos;
  playRef.current = playing;

  useEffect(() => {if (!reducedMotion()) setPlaying(true);}, []);

  useEffect(() => {
    const element = host.current!;
    const width0 = element.clientWidth || 600;
    const height = () => (element.clientWidth < 520 ? 360 : 460);
    const consts = data.constants || {};
    const re: number = consts.re_km ?? FALLBACK_RE_KM, mu: number = consts.mu_km3_s2 ?? 398600.4418, j2: number = consts.j2 ?? 1.08262668e-3;
    const frag = prepare(data.fragments.elements, mu, re, j2);
    const sats = prepare(data.satellite_elements, mu, re, j2);
    const fragBuf = new Float32Array(frag.count * 3), satBuf = new Float32Array(sats.count * 3);
    const tcaMs = Date.parse(data.tca_utc);

    const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width0, height());
    element.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.setSize(width0, height());
    labels.domElement.className = 'globe-labels';
    element.appendChild(labels.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, width0 / height(), 0.01, 400);
    const cp = new THREE.Vector3(data.collision_point_km[0], data.collision_point_km[2], -data.collision_point_km[1]).divideScalar(re);
    camera.position.copy(cp.clone().normalize().multiplyScalar(width0 < 520 ? 5.0 : 3.7)).add(new THREE.Vector3(0.9, 1.0, 0.4));
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.08; controls.enablePan = false; controls.enableZoom = false;
    controls.rotateSpeed = 0.6; controls.autoRotateSpeed = 0.5; controls.autoRotate = !reducedMotion();
    controls.addEventListener('start', () => {controls.autoRotate = false;});

    const earthMap = earthTexture();
    const earth = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 64), new THREE.MeshBasicMaterial({map: earthMap}));
    scene.add(earth);
    const rim = new THREE.Mesh(new THREE.SphereGeometry(1.07, 64, 48), new THREE.ShaderMaterial({
      transparent: true, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false,
      vertexShader: 'varying vec3 vN; void main(){ vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: 'varying vec3 vN; void main(){ float k = pow(0.72 - dot(vN, vec3(0.0,0.0,1.0)), 3.0); gl_FragColor = vec4(0.27,0.54,1.0,1.0) * clamp(k,0.0,1.0) * 0.9; }'}));
    scene.add(rim);

    const glow = glowTexture(), ring = ringTexture();
    const fragGeometry = new THREE.BufferGeometry();
    fragGeometry.setAttribute('position', new THREE.BufferAttribute(fragBuf, 3));
    const fragMaterial = new THREE.PointsMaterial({map: glow, color: AMBER, size: 0.075, sizeAttenuation: true, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false});
    const fragPoints = new THREE.Points(fragGeometry, fragMaterial);
    fragPoints.frustumCulled = false;
    scene.add(fragPoints);
    const satGeometry = new THREE.BufferGeometry();
    satGeometry.setAttribute('position', new THREE.BufferAttribute(satBuf, 3));
    const satMaterial = new THREE.PointsMaterial({map: ring, color: AMBER, size: 0.3, sizeAttenuation: true, transparent: true, depthWrite: false});
    const satPoints = new THREE.Points(satGeometry, satMaterial);
    satPoints.frustumCulled = false;
    scene.add(satPoints);

    const flashMaterial = new THREE.SpriteMaterial({map: glow, color: '#bfe0ff', transparent: true, blending: THREE.AdditiveBlending, depthWrite: false});
    const flash = new THREE.Sprite(flashMaterial);
    flash.position.copy(cp); flash.scale.setScalar(0.5);
    scene.add(flash);
    const core = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, color: '#ffffff', transparent: true, blending: THREE.AdditiveBlending, depthWrite: false}));
    core.position.copy(cp); core.scale.setScalar(0.16);
    scene.add(core);
    const label = document.createElement('div');
    label.className = 'globe-marker event label-left';
    label.innerHTML = '<span class="globe-dot"></span><span class="globe-text"></span>';
    (label.firstChild as HTMLElement).style.setProperty('--marker', '#bfe0ff');
    const labelText = label.lastChild as HTMLElement;
    labelText.textContent = `Collision point: ${data.primary.name} × ${data.threat.name}`;
    const labelObject = new CSS2DObject(label);
    labelObject.position.copy(cp);
    labelObject.center.set(1, 0.5);
    scene.add(labelObject);

    const apply = (p: number) => {
      const t = hoursAt(p, epochs) * 3600;
      propagateInto(frag, t, re, fragBuf); propagateInto(sats, t, re, satBuf);
      (fragGeometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
      (satGeometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
      earth.rotation.y = gmstRad(tcaMs + t * 1000); // Earth turns under the inertial frame the model uses
      flashMaterial.opacity = Math.max(0.35, 1 - hoursAt(p, epochs) / 24);
    };
    applyRef.current = apply;
    apply(posRef.current);

    const resize = () => {
      const w = element.clientWidth || width0;
      renderer.setSize(w, height()); labels.setSize(w, height());
      camera.aspect = w / height(); camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);

    let frame = 0, last = performance.now(), sincePos = 0;
    const loop = (now: number) => {
      frame = requestAnimationFrame(loop);
      const dt = Math.min(0.1, (now - last) / 1000); last = now;
      if (playRef.current) {
        let next = posRef.current + dt * 0.3; // one epoch step per ~3 s; the whole run takes 20 s
        if (next >= epochs.length - 1) next = 0;
        posRef.current = next;
        apply(next);
        sincePos += dt;
        if (sincePos > 0.08) {sincePos = 0; setPos(next);} // keep the slider in step without a React render per frame
      }
      controls.update();
      renderer.render(scene, camera);
      labels.render(scene, camera);
    };
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      [earthMap, glow, ring].forEach(t => t.dispose());
      scene.traverse(o => {const m = o as THREE.Mesh; m.geometry?.dispose?.(); (m.material as THREE.Material | undefined)?.dispose?.();});
      renderer.dispose();
      element.replaceChildren();
    };
  }, [data]);

  const hours = hoursAt(pos, epochs);
  const scrub = (value: number) => {setPlaying(false); posRef.current = value; setPos(value); applyRef.current(value);};
  const nSampled = number(data.n_sampled, 0), nTotal = number(data.n_fragments_total, 0);
  return <div className="debris-viz">
    <div className="globe debris-stage" style={{height: 'auto', background: '#04060c', border: '1px solid var(--border, transparent)'}}>
      <div ref={host} role="img" style={{width: '100%', minHeight: 360, cursor: 'grab'}}
        aria-label={`Three-dimensional view of ${nSampled} simulated debris fragments from a collision of ${data.primary.name} and ${data.threat.name}, and the ${data.satellites.length} most exposed satellites, at ${timeLabel(hours)}. Drag to rotate.`}/>
      <span className="globe-hint" style={{bottom: 'auto', top: 10}}>Drag to rotate</span>
      <span className="debris-time mono" style={{position: 'absolute', right: 12, top: 10, fontSize: 13, color: '#e6edf7', background: 'rgba(4,6,12,.7)', padding: '2px 8px', borderRadius: 4}} aria-live="off">{timeLabel(hours)}</span>
    </div>
    <div style={{display: 'flex', alignItems: 'center', gap: 12, margin: '10px 0 2px'}}>
      <button className="btn small" onClick={() => {if (!playing && posRef.current >= epochs.length - 1) scrub(0); setPlaying(v => !v);}} aria-label={playing ? 'Pause animation' : 'Play animation'}>
        {playing ? <Pause size={13}/> : <Play size={13}/>} {playing ? 'Pause' : 'Play'}
      </button>
      <input type="range" min={0} max={epochs.length - 1} step={0.01} value={pos} onChange={e => scrub(Number(e.target.value))}
        aria-label="Time after the collision" aria-valuetext={timeLabel(hours)} style={{flex: 1, minWidth: 0, accentColor: AMBER}}/>
    </div>
    <div className="small muted" style={{display: 'flex', justifyContent: 'space-between'}}><span>T+0 h</span><span>T+1 h</span><span>T+6 h</span><span>T+1 d</span><span>T+3 d</span><span>T+7 d</span><span>T+30 d</span></div>
    <div className="small" style={{display: 'flex', flexWrap: 'wrap', gap: '4px 18px', margin: '10px 0 4px'}}>
      <span><span aria-hidden="true" style={{display: 'inline-block', width: 9, height: 9, borderRadius: '50%', background: AMBER, boxShadow: `0 0 6px ${AMBER}`, marginRight: 6}}/>Simulated fragments (sample of {nSampled} of {nTotal})</span>
      <span><span aria-hidden="true" style={{display: 'inline-block', width: 11, height: 11, borderRadius: '50%', border: `2px solid ${AMBER}`, marginRight: 6, verticalAlign: '-2px'}}/>Exposed satellites (top {data.satellites.length})</span>
      <span><span aria-hidden="true" style={{display: 'inline-block', width: 9, height: 9, borderRadius: '50%', background: '#bfe0ff', boxShadow: '0 0 6px #bfe0ff', marginRight: 6}}/>Collision point</span>
    </div>
    <p className="small muted" style={{margin: '4px 0 0'}}>{data.note} Fragments that re-enter within days are not drawn; {number(data.n_fragments_surviving, 0)} of {number(data.n_fragments_modelled, 0)} modelled fragments stay in orbit. Motion between the published epochs uses the same two-body + J2 model.</p>
  </div>;
}

export default function DebrisGlobe({norad}: {norad: number}) {
  const [data, setData] = useState<Json | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true, timer = 0;
    setData(null); setError('');
    const load = async () => {
      try {
        const response = await fetch(`/api/live/debris?norad=${norad}`);
        const result = await response.json().catch(() => ({}));
        if (!alive) return;
        if (response.status === 202) {timer = window.setTimeout(load, 2000); return;}
        if (!response.ok) throw new Error(result.error?.message || `Request failed (${response.status})`);
        setData(result);
      } catch (exc) {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      }
    };
    load();
    return () => {alive = false; window.clearTimeout(timer);};
  }, [norad, attempt]);
  if (error) return <Notice retry={() => setAttempt(v => v + 1)}>Debris cloud unavailable: {error}</Notice>;
  if (!data) return <Loading label="Simulating the debris cloud"/>;
  if (!data.fragments?.elements?.a_km?.length) return <Empty title="No fragments to draw"/>;
  return <Stage data={data}/>;
}
