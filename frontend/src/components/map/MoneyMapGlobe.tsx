// MONEY MAP (globe) — the same data, selection and filters as the flat map, on a 3D globe. Lazy-loaded.
// The land texture is drawn ONCE from the bundled Natural Earth (India point of view) GeoJSON onto an offscreen
// canvas — no external image. Great-circle arcs (lifted with distance), a particle per real new posting, red pulse
// rings on fraud-linked cities. Pauses when the tab is hidden or the globe is scrolled out of view; disposes every
// geometry / material / texture on unmount. Locations are SIMULATED.
import { geoEquirectangular, geoPath } from "d3-geo";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import world from "../../assets/geo/india_pov.geo.json";
import type { GeoMap } from "../../api/v10";
import type { Selection } from "../../lib/selection";
import type { LivePosting } from "./useMapData";
import type { MapLayers } from "./MoneyMapFlat";

const R = 1;
const DEG = Math.PI / 180;
const RISK_HEX = { normal: 0x4fd6b8, suspicious: 0xf0b040, fraud: 0xf05252 } as const;

function v3(lat: number, lng: number, r = R): THREE.Vector3 {
  const phi = (90 - lat) * DEG, theta = (lng + 180) * DEG;
  return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
}

function arcPoints(a: THREE.Vector3, b: THREE.Vector3, n = 48): THREE.Vector3[] {
  const ang = a.angleTo(b);
  const lift = 0.04 + 0.32 * (ang / Math.PI);
  const pts: THREE.Vector3[] = [];
  const an = a.clone().normalize(), bn = b.clone().normalize();
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const p = new THREE.Vector3().copy(an).multiplyScalar(Math.sin((1 - t) * ang)).add(bn.clone().multiplyScalar(Math.sin(t * ang)));
    if (ang > 1e-6) p.divideScalar(Math.sin(ang)); else p.copy(an);
    p.multiplyScalar(R * (1 + lift * Math.sin(Math.PI * t)));
    pts.push(p);
  }
  return pts;
}

function landTexture(): THREE.CanvasTexture {
  const W = 2048, H = 1024;
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d")!;
  ctx.fillStyle = "#0a1016"; ctx.fillRect(0, 0, W, H);
  const proj = geoEquirectangular().scale(W / (2 * Math.PI)).translate([W / 2, H / 2]);
  const path = geoPath(proj, ctx);
  ctx.strokeStyle = "rgba(120,140,160,0.10)"; ctx.lineWidth = 1;
  for (let lng = -180; lng <= 180; lng += 15) { const x = ((lng + 180) / 360) * W; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let lat = -75; lat <= 75; lat += 15) { const y = ((90 - lat) / 180) * H; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  const feats = (world as unknown as { features: { properties: { layer: string; iso?: string } }[] }).features;
  for (const f of feats) {
    if (f.properties.layer !== "country") continue;
    ctx.beginPath(); path(f as never);
    ctx.fillStyle = f.properties.iso === "IND" ? "#173540" : "#1c2631"; ctx.fill();
    ctx.strokeStyle = f.properties.iso === "IND" ? "#4fd6b8" : "#2c3846"; ctx.lineWidth = f.properties.iso === "IND" ? 1.6 : 0.8; ctx.stroke();
  }
  ctx.strokeStyle = "rgba(79,214,184,0.25)"; ctx.lineWidth = 0.6;
  for (const f of feats) { if (f.properties.layer === "state") { ctx.beginPath(); path(f as never); ctx.stroke(); } }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

export default function MoneyMapGlobe({ data, layers, selected, onSelect, onPosting, height = 470 }: {
  data: GeoMap | null; layers: MapLayers; selected: Selection | null; onSelect: (s: Selection | null) => void;
  onPosting: (fn: (p: LivePosting) => void) => () => void; height?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const api = useRef<{ setData: (d: GeoMap | null, l: MapLayers) => void; fly: (lat: number, lng: number) => void;
    spawn: (p: LivePosting) => void; highlight: (s: Selection | null) => void } | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(el.clientWidth, height);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, el.clientWidth / height, 0.1, 100);
    camera.position.copy(v3(20, 80, 3.1));
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.08; controls.minDistance = 1.35; controls.maxDistance = 6;
    controls.autoRotate = true; controls.autoRotateSpeed = 0.35; controls.enablePan = false;
    controls.addEventListener("start", () => { controls.autoRotate = false; });

    const tex = landTexture();
    const globe = new THREE.Mesh(new THREE.SphereGeometry(R, 96, 64), new THREE.MeshBasicMaterial({ map: tex }));
    scene.add(globe);
    const atmo = new THREE.Mesh(new THREE.SphereGeometry(R * 1.06, 64, 48), new THREE.ShaderMaterial({
      side: THREE.BackSide, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: "varying vec3 vN; void main(){ vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader: "varying vec3 vN; void main(){ float i = pow(0.62 - dot(vN, vec3(0.0,0.0,1.0)), 3.0); gl_FragColor = vec4(0.31,0.84,0.72,1.0) * i; }",
    }));
    scene.add(atmo);
    const dyn = new THREE.Group();
    scene.add(dyn);
    const markers: THREE.Mesh[] = [];
    const pulses: { m: THREE.Mesh; phase: number }[] = [];
    const parts: { m: THREE.Mesh; pts: THREE.Vector3[]; t0: number }[] = [];
    let selMesh: THREE.Object3D | null = null;
    const markerGeo = new THREE.SphereGeometry(0.0085, 10, 8);
    const partGeo = new THREE.SphereGeometry(0.007, 8, 6);
    const ringGeo = new THREE.RingGeometry(0.012, 0.018, 32);

    const clearDyn = () => {
      for (const o of [...dyn.children]) {
        dyn.remove(o);
        const m = o as THREE.Mesh;
        if (m.geometry && m.geometry !== markerGeo && m.geometry !== ringGeo && m.geometry !== partGeo) m.geometry.dispose();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose()); else mat?.dispose();
      }
      markers.length = 0; pulses.length = 0;
    };
    const setData = (d: GeoMap | null, l: MapLayers) => {
      clearDyn();
      if (!d) return;
      const maxV = Math.max(1, ...d.cities.map((c) => c.value_paise));
      for (const c of d.cities) {
        if (c.lat == null) continue;
        const color = c.kind === "foreign" ? 0x7d8794 : c.fraud_linked_paise ? 0xf05252 : c.suspicious_count ? 0xf0b040 : 0x4fd6b8;
        const m = new THREE.Mesh(markerGeo, new THREE.MeshBasicMaterial({ color }));
        m.position.copy(v3(c.lat, c.lng, R * 1.002));
        const s = 0.7 + 1.6 * Math.sqrt(c.value_paise / maxV);
        m.scale.setScalar(s);
        m.userData = { city: c.city, lat: c.lat, lng: c.lng };
        dyn.add(m); markers.push(m);
        if (l.fraud && c.fraud_linked_paise > 0) {
          const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: 0xf05252, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
          ring.position.copy(v3(c.lat, c.lng, R * 1.003));
          ring.lookAt(ring.position.clone().multiplyScalar(2));
          dyn.add(ring); pulses.push({ m: ring, phase: Math.random() });
        }
      }
      if (l.flows) {
        const maxF = Math.max(1, ...d.flows.map((f) => f.value_paise));
        for (const f of d.flows) {
          if (f.from_lat == null || f.to_lat == null) continue;
          const pts = arcPoints(v3(f.from_lat, f.from_lng), v3(f.to_lat, f.to_lng));
          const g = new THREE.BufferGeometry().setFromPoints(pts);
          const op = f.risk === "normal" ? 0.18 + 0.4 * Math.sqrt(f.value_paise / maxF) : 0.85;
          dyn.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: RISK_HEX[f.risk], transparent: true, opacity: op })));
        }
      }
      if (l.atm) {
        for (const c of d.clusters) {
          if (!c.center) continue;
          const ring = new THREE.Mesh(new THREE.RingGeometry(0.02, 0.026, 40),
            new THREE.MeshBasicMaterial({ color: c.kind === "cash_out" ? 0xf05252 : 0xf0b040, side: THREE.DoubleSide, transparent: true, opacity: 0.9 }));
          ring.position.copy(v3(c.center.lat, c.center.lng, R * 1.004));
          ring.lookAt(ring.position.clone().multiplyScalar(2));
          dyn.add(ring);
        }
      }
    };
    let tween: { from: THREE.Vector3; to: THREE.Vector3; t0: number } | null = null;
    const fly = (lat: number, lng: number) => {
      controls.autoRotate = false;
      tween = { from: camera.position.clone(), to: v3(lat, lng, Math.max(1.9, Math.min(3.1, camera.position.length()))), t0: performance.now() };
    };
    const spawn = (p: LivePosting) => {
      if (!p.from || parts.length >= 150 || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
      const a = v3(p.from[1], p.from[0]);
      const b = p.to && !p.atm ? v3(p.to[1], p.to[0]) : a.clone().multiplyScalar(1.05);
      const m = new THREE.Mesh(partGeo, new THREE.MeshBasicMaterial({ color: p.risky ? 0xff6b6b : 0x9ff5e1 }));
      scene.add(m);
      parts.push({ m, pts: p.to && !p.atm ? arcPoints(a, b, 40) : [a, b], t0: performance.now() });
    };
    const highlight = (s: Selection | null) => {
      if (selMesh) { scene.remove(selMesh); (selMesh as THREE.Mesh).geometry?.dispose(); ((selMesh as THREE.Mesh).material as THREE.Material)?.dispose(); selMesh = null; }
      if (!s || s.lat == null || s.lng == null) return;
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.03, 0.038, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }));
      ring.position.copy(v3(s.lat, s.lng, R * 1.005));
      ring.lookAt(ring.position.clone().multiplyScalar(2));
      scene.add(ring); selMesh = ring;
      fly(s.lat, s.lng);
    };
    api.current = { setData, fly, spawn, highlight };

    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let down = { x: 0, y: 0 };
    const pd = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY }; };
    const pu = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return;
      const r = renderer.domElement.getBoundingClientRect();
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      ray.params.Points = { threshold: 0.02 };
      const hit = ray.intersectObjects(markers, false)[0];
      if (hit) {
        const u = hit.object.userData as { city: string; lat: number; lng: number };
        onSelectRef.current({ kind: "city", id: u.city, lat: u.lat, lng: u.lng, label: u.city });
      }
    };
    renderer.domElement.addEventListener("pointerdown", pd);
    renderer.domElement.addEventListener("pointerup", pu);

    let visible = true;
    const io = new IntersectionObserver((ents) => { visible = ents[0]?.isIntersecting ?? true; });
    io.observe(el);
    const ro = new ResizeObserver(() => {
      renderer.setSize(el.clientWidth, height);
      camera.aspect = el.clientWidth / height; camera.updateProjectionMatrix();
    });
    ro.observe(el);
    let raf = 0;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (!visible || document.visibilityState === "hidden") return;
      if (tween) {
        const s = Math.min(1, (now - tween.t0) / 1100);
        const e = s < 0.5 ? 2 * s * s : 1 - Math.pow(-2 * s + 2, 2) / 2;
        camera.position.copy(tween.from.clone().lerp(tween.to, e).normalize().multiplyScalar(tween.from.length() + (tween.to.length() - tween.from.length()) * e));
        if (s >= 1) tween = null;
      }
      for (const p of pulses) {
        const s = ((now / 2200) + p.phase) % 1;
        p.m.scale.setScalar(1 + 2.6 * s);
        (p.m.material as THREE.MeshBasicMaterial).opacity = 0.85 * (1 - s);
      }
      for (let i = parts.length - 1; i >= 0; i--) {
        const p = parts[i];
        const s = Math.max(0, (now - p.t0) / 1800);
        if (s >= 1 || p.pts.length === 0) { scene.remove(p.m); (p.m.material as THREE.Material).dispose(); parts.splice(i, 1); continue; }
        const idx = s * (p.pts.length - 1);
        const a = p.pts[Math.floor(idx)], b = p.pts[Math.min(p.pts.length - 1, Math.floor(idx) + 1)];
        if (a && b) p.m.position.copy(a).lerp(b, idx - Math.floor(idx));   // a spark that started before its arc was built
      }
      controls.update();
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect(); ro.disconnect();
      renderer.domElement.removeEventListener("pointerdown", pd);
      renderer.domElement.removeEventListener("pointerup", pu);
      clearDyn();
      for (const p of parts) { scene.remove(p.m); (p.m.material as THREE.Material).dispose(); }
      if (selMesh) { (selMesh as THREE.Mesh).geometry?.dispose(); ((selMesh as THREE.Mesh).material as THREE.Material)?.dispose(); }
      markerGeo.dispose(); partGeo.dispose(); ringGeo.dispose();
      globe.geometry.dispose(); (globe.material as THREE.Material).dispose(); tex.dispose();
      atmo.geometry.dispose(); (atmo.material as THREE.Material).dispose();
      controls.dispose(); renderer.dispose(); renderer.forceContextLoss();
      el.removeChild(renderer.domElement);
      api.current = null;
    };
  }, [height]);

  useEffect(() => { api.current?.setData(data, layers); }, [data, layers]);
  useEffect(() => onPosting((p) => api.current?.spawn(p)), [onPosting]);
  useEffect(() => { api.current?.highlight(selected); }, [selected?.kind, selected?.id, selected?.lat, selected?.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="mglobe" style={{ height }}>
      <div ref={host} className="mglobe-host" aria-label="Money map globe (simulated locations). Drag to rotate, scroll to zoom." role="img" />
      <div className="mmap-ctrl">
        <button onClick={() => api.current?.fly(22, 80)} title="Fly to India">IN</button>
      </div>
    </div>
  );
}
