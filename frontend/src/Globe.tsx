import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { geoEquirectangular, geoGraticule10, geoPath } from 'd3-geo';
import { feature } from 'topojson-client';
import type { Topology } from 'topojson-specification';
import landTopology from 'world-atlas/land-110m.json';
import { Minus, Plus, RotateCcw } from 'lucide-react';

/** Earth-centred inertial position in kilometres. */
export type Vec3 = [number, number, number];
export type GlobeOrbit = {id: string, color: string, points: Vec3[], width?: number, dashed?: boolean, opacity?: number, closed?: boolean};
export type GlobeMarker = {id: string, position: Vec3, color: string, label?: string, kind?: 'object' | 'event' | 'minor', labelLeft?: boolean};

const EARTH_RADIUS_KM = 6378.137;
// ECI z (north) becomes three.js y (up).
const toScene = ([x, y, z]: Vec3) => new THREE.Vector3(x / EARTH_RADIUS_KM, z / EARTH_RADIUS_KM, -y / EARTH_RADIUS_KM);

function earthTexture(ocean: string, land: string, grid: string) {
  const canvas = document.createElement('canvas');
  canvas.width = 2048; canvas.height = 1024;
  const ctx = canvas.getContext('2d')!;
  const projection = geoEquirectangular().scale(1024 / Math.PI).translate([1024, 512]);
  const path = geoPath(projection, ctx);
  ctx.fillStyle = ocean; ctx.fillRect(0, 0, 2048, 1024);
  ctx.beginPath(); path(geoGraticule10()); ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.stroke();
  const topology = landTopology as unknown as Topology;
  ctx.beginPath(); path(feature(topology, topology.objects.land) as never); ctx.fillStyle = land; ctx.fill();
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function readTheme() {
  const style = getComputedStyle(document.documentElement);
  const get = (name: string) => style.getPropertyValue(name).trim();
  return {ocean: get('--globe-ocean'), land: get('--globe-land'), grid: get('--globe-grid')};
}

type Props = {orbits: GlobeOrbit[], markers: GlobeMarker[], focus?: Vec3 | null, height?: number, label: string, fitRadiusKm?: number};

export default function Globe({orbits, markers, focus, height = 460, label, fitRadiusKm}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<{
    renderer: THREE.WebGLRenderer, labels: CSS2DRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera,
    controls: OrbitControls, earth: THREE.Mesh, orbitGroup: THREE.Group, markerObjects: Map<string, CSS2DObject>,
    materials: LineMaterial[], flight: {from: THREE.Vector3, to: THREE.Vector3, start: number} | null, home: THREE.Vector3,
  } | null>(null);

  // Scene set-up, once.
  useEffect(() => {
    const element = host.current!;
    const width = element.clientWidth || 600;
    const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    element.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.setSize(width, height);
    labels.domElement.className = 'globe-labels';
    element.appendChild(labels.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, width / height, 0.01, 200);
    const home = new THREE.Vector3(2.2, 3.4, 3.0).setLength(Math.max(4.2, (fitRadiusKm ?? 8000) / EARTH_RADIUS_KM * 3.4));
    camera.position.copy(home);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.08;
    controls.enablePan = false; controls.enableZoom = false; // zoom with the buttons so the page still scrolls
    controls.rotateSpeed = 0.6;
    const theme = readTheme();
    const earth = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 64), new THREE.MeshBasicMaterial({map: earthTexture(theme.ocean, theme.land, theme.grid)}));
    scene.add(earth);
    const orbitGroup = new THREE.Group();
    scene.add(orbitGroup);
    state.current = {renderer, labels, scene, camera, controls, earth, orbitGroup, markerObjects: new Map(), materials: [], flight: null, home};

    const resize = () => {
      const w = element.clientWidth || width;
      renderer.setSize(w, height); labels.setSize(w, height);
      camera.aspect = w / height; camera.updateProjectionMatrix();
      state.current?.materials.forEach(m => m.resolution.set(w, height));
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    const media = matchMedia('(prefers-color-scheme: dark)');
    const retheme = () => {const t = readTheme(); const material = earth.material as THREE.MeshBasicMaterial; material.map?.dispose(); material.map = earthTexture(t.ocean, t.land, t.grid); material.needsUpdate = true;};
    media.addEventListener('change', retheme);

    let frame = 0;
    const toCamera = new THREE.Vector3();
    const loop = (now: number) => {
      frame = requestAnimationFrame(loop);
      const s = state.current!;
      if (s.flight) {
        const k = Math.min(1, (now - s.flight.start) / 700);
        const eased = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        camera.position.copy(s.flight.from).lerp(s.flight.to, eased).setLength(THREE.MathUtils.lerp(s.flight.from.length(), s.flight.to.length(), eased));
        if (k >= 1) s.flight = null;
      }
      controls.update();
      // Dim labels that sit behind the Earth from the camera's point of view.
      for (const object of s.markerObjects.values()) {
        const p = object.position;
        toCamera.copy(camera.position).sub(p);
        const distance = toCamera.length();
        toCamera.normalize();
        const b = p.dot(toCamera), c = p.lengthSq() - 1;
        const disc = b * b - c;
        const hidden = disc > 0 && (-b - Math.sqrt(disc)) > 0 && (-b - Math.sqrt(disc)) < distance;
        object.element.classList.toggle('behind', hidden);
      }
      renderer.render(scene, camera);
      labels.render(scene, camera);
    };
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      media.removeEventListener('change', retheme);
      controls.dispose();
      renderer.dispose();
      scene.traverse(o => {const mesh = o as THREE.Mesh; mesh.geometry?.dispose?.(); const m = mesh.material as THREE.Material | undefined; m?.dispose?.();});
      element.replaceChildren();
      state.current = null;
    };
  }, [height]);

  // Orbits: rebuilt whenever their data changes.
  useEffect(() => {
    const s = state.current;
    if (!s) return;
    s.orbitGroup.children.forEach(child => {const line = child as Line2; line.geometry.dispose(); (line.material as LineMaterial).dispose();});
    s.orbitGroup.clear();
    s.materials = [];
    const size = new THREE.Vector2(); s.renderer.getSize(size);
    for (const orbit of orbits) {
      if (orbit.points.length < 2) continue;
      const pts = orbit.points.map(toScene);
      if (orbit.closed) pts.push(pts[0]);
      const geometry = new LineGeometry();
      geometry.setPositions(pts.flatMap(p => [p.x, p.y, p.z]));
      const material = new LineMaterial({color: new THREE.Color(orbit.color).getHex(), linewidth: orbit.width ?? 1.5, transparent: true, opacity: orbit.opacity ?? 1, dashed: Boolean(orbit.dashed), dashSize: 0.03, gapSize: 0.025});
      material.resolution.set(size.x, size.y);
      const line = new Line2(geometry, material);
      if (orbit.dashed) line.computeLineDistances();
      s.orbitGroup.add(line);
      s.materials.push(material);
    }
  }, [orbits]);

  // Markers: HTML labels reused by id so moving objects update smoothly.
  useEffect(() => {
    const s = state.current;
    if (!s) return;
    const seen = new Set<string>();
    for (const marker of markers) {
      seen.add(marker.id);
      let object = s.markerObjects.get(marker.id);
      if (!object) {
        const element = document.createElement('div');
        element.innerHTML = '<span class="globe-dot"></span><span class="globe-text"></span>';
        object = new CSS2DObject(element);
        object.center.set(0, 0.5);
        s.scene.add(object);
        s.markerObjects.set(marker.id, object);
      }
      object.element.className = `globe-marker ${marker.kind ?? 'object'}${marker.labelLeft ? ' label-left' : ''}`;
      object.center.set(marker.labelLeft ? 1 : 0, 0.5); // anchor the dot, whichever side the text is on
      (object.element.firstChild as HTMLElement).style.setProperty('--marker', marker.color);
      (object.element.lastChild as HTMLElement).textContent = marker.label ?? '';
      object.position.copy(toScene(marker.position));
    }
    for (const [id, object] of s.markerObjects) if (!seen.has(id)) {s.scene.remove(object); object.element.remove(); s.markerObjects.delete(id);}
  }, [markers]);

  // Fly the camera to look at a point of interest.
  useEffect(() => {
    const s = state.current;
    if (!s || !focus) return;
    const target = toScene(focus).normalize().multiplyScalar(Math.max(2.6, s.camera.position.length() * 0.75));
    target.add(new THREE.Vector3(0.25, 0.35, 0).multiplyScalar(target.length() * 0.15));
    s.flight = {from: s.camera.position.clone(), to: target, start: performance.now()};
  }, [focus?.[0], focus?.[1], focus?.[2]]);

  const zoom = (factor: number) => {const s = state.current; if (!s) return; s.flight = {from: s.camera.position.clone(), to: s.camera.position.clone().multiplyScalar(factor).clampLength(1.35, 30), start: performance.now()};};
  const reset = () => {const s = state.current; if (!s) return; s.flight = {from: s.camera.position.clone(), to: s.home.clone(), start: performance.now()};};

  return <div className="globe" style={{height}}>
    <div ref={host} className="globe-canvas" role="img" aria-label={label}/>
    <div className="globe-controls">
      <button className="btn icon" aria-label="Zoom in" onClick={() => zoom(0.75)}><Plus size={14}/></button>
      <button className="btn icon" aria-label="Zoom out" onClick={() => zoom(1.33)}><Minus size={14}/></button>
      <button className="btn icon" aria-label="Reset view" onClick={reset}><RotateCcw size={14}/></button>
    </div>
    <span className="globe-hint">Drag to rotate</span>
  </div>;
}
