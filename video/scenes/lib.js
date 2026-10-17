// Shared animation helpers for the video's narrative scenes. Bundled with esbuild into out/lib.js.
import { geoDistance, geoGraticule10, geoOrthographic, geoPath } from 'd3-geo';
import { feature } from 'topojson-client';
import landTopology from 'world-atlas/land-110m.json';

const land = feature(landTopology, landTopology.objects.land);
const graticule = geoGraticule10();
const DEG = 180 / Math.PI;

export const COLORS = {a: '#3987e5', b: '#e2672f', c: '#22a87a', ink: '#eef0f3', muted: '#8a93a0', faint: 'rgba(200,210,225,0.35)', bad: '#e5534b'};

/** Unit vector on an orbit (inclination, node, argument in radians) as lon/lat in degrees. */
function orbitLonLat(inc, raan, u) {
  const x = Math.cos(u) * Math.cos(raan) - Math.sin(u) * Math.cos(inc) * Math.sin(raan);
  const y = Math.cos(u) * Math.sin(raan) + Math.sin(u) * Math.cos(inc) * Math.cos(raan);
  const z = Math.sin(u) * Math.sin(inc);
  return [Math.atan2(y, x) * DEG, Math.asin(z) * DEG];
}

function seeded(seed) {let s = seed >>> 0; return () => {s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296;};}

/**
 * A rotating Earth with orbits, satellites, an optional debris swarm and collision bursts.
 * orbits: [{inc, raan, alt, color, width, sats: [{phase, color, size, label}], speed, alpha}]
 */
export function earth(canvas, options = {}) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const R = options.radius ?? Math.min(W, H) * 0.34;
  const cx = options.cx ?? W / 2, cy = options.cy ?? H / 2;
  const tilt = options.tilt ?? -20;
  const state = {rot: options.rotation ?? 20, spin: options.spin ?? 4, orbits: options.orbits || [], swarm: [], bursts: [], t: 0, alpha: 1};
  const projection = geoOrthographic().scale(R).translate([cx, cy]).clipAngle(90);
  const path = geoPath(projection, ctx);

  function setSwarm(count, seed = 7) {
    const rnd = seeded(seed);
    const belts = [53, 70, 74, 82, 86, 98, 98, 99, 65, 28, 45];
    state.swarm = Array.from({length: count}, () => ({
      inc: (belts[Math.floor(rnd() * belts.length)] + (rnd() - 0.5) * 4) / DEG,
      raan: rnd() * Math.PI * 2, phase: rnd() * Math.PI * 2, alt: 0.07 + rnd() * 0.1, speed: 0.22 + rnd() * 0.08,
    }));
  }
  if (options.swarm) setSwarm(options.swarm);

  function project(lonlat, alt) {
    const p = projection(lonlat);
    const center = [-state.rot, -tilt];
    const front = geoDistance(lonlat, center) < Math.PI / 2;
    const x = cx + (p[0] - cx) * (1 + alt), y = cy + (p[1] - cy) * (1 + alt);
    const visible = front || Math.hypot(x - cx, y - cy) > R;
    return {x, y, front, visible};
  }

  function drawOrbit(o, layer) {
    const steps = 220;
    ctx.lineWidth = o.width ?? 1.4;
    ctx.strokeStyle = o.color;
    let drawing = false;
    ctx.beginPath();
    for (let k = 0; k <= steps; k++) {
      const q = project(orbitLonLat(o.inc, o.raan, (k / steps) * Math.PI * 2), o.alt);
      const mine = layer === 'front' ? q.front : !q.front && q.visible;
      if (mine) {if (!drawing) {ctx.moveTo(q.x, q.y); drawing = true;} else ctx.lineTo(q.x, q.y);} else drawing = false;
    }
    ctx.globalAlpha = state.alpha * (layer === 'front' ? (o.alpha ?? 1) : (o.alpha ?? 1) * 0.45);
    ctx.stroke();
    ctx.globalAlpha = state.alpha;
  }

  function dot(q, color, size, label) {
    if (!q.visible) return;
    ctx.globalAlpha = state.alpha * (q.front ? 1 : 0.5);
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(q.x, q.y, size, 0, Math.PI * 2); ctx.fill();
    if (label) {ctx.font = '500 22px "IBM Plex Sans"'; ctx.fillStyle = COLORS.ink; ctx.fillText(label, q.x + size + 8, q.y - size - 4);}
    ctx.globalAlpha = state.alpha;
  }

  function frame(dt) {
    state.t += dt;
    state.rot += state.spin * dt;
    projection.rotate([state.rot, tilt]);
    ctx.clearRect(0, 0, W, H);
    ctx.globalAlpha = state.alpha;
    // Far side of orbits, then the planet, then the near side.
    for (const o of state.orbits) drawOrbit(o, 'back');
    ctx.fillStyle = '#121a24'; ctx.beginPath(); path({type: 'Sphere'}); ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.05)'; ctx.lineWidth = 1; ctx.beginPath(); path(graticule); ctx.stroke();
    ctx.fillStyle = '#2b3644'; ctx.beginPath(); path(land); ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.18)'; ctx.lineWidth = 1.2; ctx.beginPath(); path({type: 'Sphere'}); ctx.stroke();
    for (const o of state.orbits) drawOrbit(o, 'front');
    for (const s of state.swarm) dot(project(orbitLonLat(s.inc, s.raan, s.phase + state.t * s.speed), s.alt), 'rgba(190,200,215,0.75)', 2.1);
    for (const o of state.orbits) for (const sat of o.sats || []) dot(project(orbitLonLat(o.inc, o.raan, sat.phase + state.t * (o.speed ?? 0.25)), o.alt), sat.color ?? o.color, sat.size ?? 6, sat.label);
    for (const b of state.bursts) {
      const age = state.t - b.t0;
      if (age < 0) continue;
      const flash = Math.max(0, 1 - age / 0.8);
      const q0 = project(orbitLonLat(b.inc, b.raan, b.phase + b.t0 * 0.25), b.alt);
      if (flash > 0 && q0.visible) {ctx.globalAlpha = flash; ctx.strokeStyle = COLORS.bad; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(q0.x, q0.y, 10 + age * 90, 0, Math.PI * 2); ctx.stroke(); ctx.globalAlpha = state.alpha;}
      for (const f of b.fragments) {
        const spread = Math.min(age, 6);
        const q = project(orbitLonLat(b.inc + f.di * spread, b.raan + f.dr * spread, b.phase + b.t0 * 0.25 + age * (0.25 + f.dv) ), b.alt + f.da * spread);
        dot(q, age < 1.2 ? COLORS.b : 'rgba(229,140,100,0.85)', 2.8);
      }
    }
  }

  let last = performance.now(), running = true;
  const loop = now => {if (!running) return; frame(Math.min(0.05, (now - last) / 1000)); last = now; requestAnimationFrame(loop);};
  requestAnimationFrame(loop);
  return {
    state, setSwarm,
    burst(inc, raan, phase, alt, count = 160, seed = 3) {
      const rnd = seeded(seed);
      state.bursts.push({inc, raan, phase, alt, t0: state.t, fragments: Array.from({length: count}, () => ({di: (rnd() - 0.5) * 0.02, dr: (rnd() - 0.5) * 0.03, dv: (rnd() - 0.5) * 0.12, da: (rnd() - 0.5) * 0.006}))});
    },
    // Burst at a point on the visible face, offset from the view centre, so the collision is seen.
    burstFront(count = 200, dLon = -18, dLat = 14, seed = 3) {
      const inc = 86 / DEG;
      const lat0 = (-tilt + dLat) / DEG, lon0 = (-state.rot + dLon) / DEG;
      const u = Math.asin(Math.max(-1, Math.min(1, Math.sin(lat0) / Math.sin(inc))));
      const raan = lon0 - Math.atan2(Math.cos(inc) * Math.sin(u), Math.cos(u));
      this.burst(inc, raan, u - state.t * 0.25, 0.1, count, seed);
    },
    stop() {running = false;},
  };
}

/** Simple timeline helper: run(fn) at cue n; scenes expose window.cue(n). */
export function cues(handlers) {window.cue = n => {const h = handlers[n]; if (h) h();};}
export function reveal(selector, delay = 0) {setTimeout(() => document.querySelectorAll(selector).forEach(el => el.classList.add('in')), delay);}
export function countUp(el, to, ms = 1200, format = v => Math.round(v).toLocaleString('en-US')) {
  const start = performance.now();
  const tick = now => {const k = Math.min(1, (now - start) / ms); const e = 1 - Math.pow(1 - k, 3); el.textContent = format(to * e); if (k < 1) requestAnimationFrame(tick);};
  requestAnimationFrame(tick);
}

window.OG = {earth, cues, reveal, countUp, COLORS};
