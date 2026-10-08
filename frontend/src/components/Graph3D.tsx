// WebGL network view, engineered for a calm 60 fps:
//  • node positions come from GraphScene (frozen, precomputed server-side) — no force physics at all;
//  • one InstancedMesh per role shape, one for edge shafts, one for arrowheads, one for rings, one for particles;
//  • geometry is rebuilt ONLY when the scene version changes; colour/selection/replay changes only rewrite
//    instance attributes; unrelated React state never touches the GPU buffers;
//  • render-on-demand: frames are drawn only while the camera moves, a focus tween runs, or particles
//    (selected / replayed money movement only) are active;
//  • labels are DOM overlays, level-of-detail: hovered, selected and caller-chosen important nodes only.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { GraphScene, SceneEdge, SceneNode } from "../api/types";
import { ROLE_SHAPE, roleKey, type ShapeKey } from "../lib/graphStyle";

export interface Graph3DStyle {
  nodeColor: (n: SceneNode) => string;
  nodeDim: (n: SceneNode) => boolean;
  edgeColor: (e: SceneEdge) => string;
  ringColor: (n: SceneNode) => string | null;
  label: (n: SceneNode) => string | null;     // LOD label for important nodes (null = no permanent label)
}

export interface Graph3DProps {
  scene: GraphScene;
  style: Graph3DStyle;
  selected: string | null;
  selectedEdge: string | null;
  /** Replay clock in epoch ms; null when not replaying. */
  replayT: number | null;
  replayWindowMs?: number;
  focusSeq: number;                              // bump to request a camera focus on `selected`
  onSelect: (id: string | null) => void;
  onSelectEdge: (id: string | null) => void;
  onHover?: (info: { x: number; y: number; text: string } | null) => void;
  hoverText: (n: SceneNode) => string;
  hoverEdgeText: (e: SceneEdge) => string;
}

const BG = 0x0a0d12;
const ACCENT = "#5b93f0";
const SHAPES: ShapeKey[] = ["sphere", "octa", "cone", "dodeca", "cyl", "tetra", "ico", "hex", "box"];

function makeGeometry(k: ShapeKey): THREE.BufferGeometry {
  switch (k) {
    case "octa": return new THREE.OctahedronGeometry(1.3);
    case "cone": return new THREE.ConeGeometry(1.05, 2, 16);
    case "dodeca": return new THREE.DodecahedronGeometry(1.25);
    case "cyl": return new THREE.CylinderGeometry(0.95, 0.95, 1.5, 18);
    case "tetra": return new THREE.TetrahedronGeometry(1.4);
    case "ico": return new THREE.IcosahedronGeometry(1.2);
    case "hex": return new THREE.CylinderGeometry(1.1, 1.1, 1.3, 6);
    case "box": return new THREE.BoxGeometry(1.9, 1.1, 1.1);
    default: return new THREE.SphereGeometry(1, 22, 16);
  }
}

function nodeRadius(n: SceneNode): number {
  if (n.kind === "external") return 3.2;
  return 3 + Math.min(1, n.risk) * 3.6 + (n.labelled ? 0.8 : 0);
}

interface Built {
  nodes: SceneNode[];
  index: Map<string, number>;                                   // node id → index in nodes
  pos: THREE.Vector3[];
  radius: number[];
  meshOf: { mesh: THREE.InstancedMesh; slot: number }[];        // node index → mesh + instance
  slotNode: Map<THREE.InstancedMesh, number[]>;                 // mesh → instance → node index
  meshes: THREE.InstancedMesh[];
  edges: SceneEdge[];
  edgeIndex: Map<string, number>;
  shaft: THREE.InstancedMesh;
  arrow: THREE.InstancedMesh;
  edgeFrom: THREE.Vector3[];
  edgeTo: THREE.Vector3[];
  edgeR: number[];
  edgeFirst: number[];                                          // first tx time (ms) per edge
  edgeTimes: number[][];                                        // tx times per edge
  group: THREE.Group;
  center: THREE.Vector3;
  span: number;
  size: THREE.Vector3;
  k: number;                                                    // world-units scale for glyphs (∝ layout span)
}

export function Graph3D(p: Graph3DProps) {
  const host = useRef<HTMLDivElement>(null);
  const labelsHost = useRef<HTMLDivElement>(null);
  const props = useRef(p);
  props.current = p;

  // long-lived three.js context (created once)
  const ctx = useRef<{
    renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls;
    rings: THREE.InstancedMesh; particles: THREE.InstancedMesh; raycaster: THREE.Raycaster;
    built: Built | null; request: () => void; tween: null | { t0: number; dur: number; fromP: THREE.Vector3; toP: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3 };
    particleEdges: { e: number; color: THREE.Color; n: number }[]; ringList: { node: number; color: THREE.Color; scale: number }[];
    labels: Map<string, HTMLDivElement>; labelIds: { id: string; text: string; cls: string }[]; hovered: number | null;
    lastVersion: string | null; geos: Map<ShapeKey, THREE.BufferGeometry>; nodeMat: THREE.MeshStandardMaterial;
  } | null>(null);

  // ── create context once ──────────────────────────────────────────────────
  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(BG, 1);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(BG, 500, 1400);
    const w0 = el.clientWidth || 800, h0 = el.clientHeight || 600;
    renderer.setSize(w0, h0, false);
    renderer.domElement.style.width = `${w0}px`;
    renderer.domElement.style.height = `${h0}px`;
    const camera = new THREE.PerspectiveCamera(42, w0 / h0, 1, 6000);
    camera.position.set(0, 120, 520);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.rotateSpeed = 0.6;
    controls.zoomSpeed = 0.9;
    controls.minDistance = 30;
    controls.maxDistance = 2200;

    scene.add(new THREE.HemisphereLight(0xdfe4ec, 0x0d1015, 1.35));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(240, 400, 300);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x5b93f0, 0.45);
    rim.position.set(-300, -120, -260);
    scene.add(rim);

    const ringGeo = new THREE.TorusGeometry(1, 0.07, 6, 48);
    const rings = new THREE.InstancedMesh(ringGeo, new THREE.MeshBasicMaterial({ color: 0xffffff, fog: true }), 512);
    rings.count = 0;
    rings.frustumCulled = false;
    scene.add(rings);
    const particles = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 10, 8), new THREE.MeshBasicMaterial({ color: 0xffffff }), 600);
    particles.count = 0;
    particles.frustumCulled = false;
    scene.add(particles);

    const geos = new Map<ShapeKey, THREE.BufferGeometry>(SHAPES.map((k) => [k, makeGeometry(k)]));
    const nodeMat = new THREE.MeshStandardMaterial({ roughness: 0.48, metalness: 0.12, flatShading: false });

    let raf = 0;
    let scheduled = false;
    const dummy = new THREE.Object3D();
    const tmp = new THREE.Vector3();
    const q = new THREE.Quaternion();

    const c = {
      renderer, scene, camera, controls, rings, particles, raycaster: new THREE.Raycaster(), built: null as Built | null,
      request: () => undefined as void, tween: null as never, particleEdges: [] as { e: number; color: THREE.Color; n: number }[],
      ringList: [] as { node: number; color: THREE.Color; scale: number }[], labels: new Map<string, HTMLDivElement>(),
      labelIds: [] as { id: string; text: string; cls: string }[], hovered: null as number | null, lastVersion: null as string | null,
      geos, nodeMat,
    };
    ctx.current = c as never;

    const frame = (now: number) => {
      scheduled = false;
      let animate = false;
      const tw = ctx.current!.tween;
      if (tw) {
        const k = Math.min(1, (now - tw.t0) / tw.dur);
        const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        camera.position.lerpVectors(tw.fromP, tw.toP, e);
        controls.target.lerpVectors(tw.fromT, tw.toT, e);
        if (k >= 1) ctx.current!.tween = null; else animate = true;
      }
      if (controls.update()) animate = true;
      const b = ctx.current!.built;
      // rings face the camera
      const rl = ctx.current!.ringList;
      if (b) {
        camera.getWorldQuaternion(q);
        rl.forEach((r, i) => {
          dummy.position.copy(b.pos[r.node]);
          dummy.quaternion.copy(q);
          const s = b.radius[r.node] * r.scale;
          dummy.scale.set(s, s, s);
          dummy.updateMatrix();
          rings.setMatrixAt(i, dummy.matrix);
        });
        rings.count = rl.length;
        rings.instanceMatrix.needsUpdate = true;
      }
      // particles: only for selected / replayed money movement
      const pe = ctx.current!.particleEdges;
      if (b && pe.length) {
        let i = 0;
        const t = now / 1000;
        for (const it of pe) {
          const from = b.edgeFrom[it.e], to = b.edgeTo[it.e];
          for (let j = 0; j < it.n && i < 600; j++, i++) {
            const f = (t * 0.45 + j / it.n) % 1;
            tmp.lerpVectors(from, to, f);
            dummy.position.copy(tmp);
            dummy.quaternion.identity();
            const s = 0.9 * b.k + b.edgeR[it.e] * 0.9;
            dummy.scale.set(s, s, s);
            dummy.updateMatrix();
            particles.setMatrixAt(i, dummy.matrix);
            particles.setColorAt(i, it.color);
          }
        }
        particles.count = i;
        particles.instanceMatrix.needsUpdate = true;
        if (particles.instanceColor) particles.instanceColor.needsUpdate = true;
        animate = true;
      } else {
        particles.count = 0;
      }
      renderer.render(scene, camera);
      placeLabels();
      if (animate) schedule();
    };
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      raf = requestAnimationFrame(frame);
    };
    c.request = schedule;

    const placeLabels = () => {
      const cc = ctx.current!;
      const b = cc.built;
      const hostEl = labelsHost.current;
      if (!b || !hostEl) return;
      const w = renderer.domElement.clientWidth, h = renderer.domElement.clientHeight;
      const want = new Set(cc.labelIds.map((l) => l.id));
      cc.labels.forEach((div, id) => { if (!want.has(id)) { div.remove(); cc.labels.delete(id); } });
      // Screen-space declutter: labelIds are in priority order (selected, hovered, then by risk); a label that would
      // overlap one already placed is hidden. ≤ 24 labels, recomputed only when the camera moves.
      const placed: [number, number, number, number][] = [];
      for (const l of cc.labelIds) {
        const idx = b.index.get(l.id);
        if (idx === undefined) continue;
        let div = cc.labels.get(l.id);
        if (!div) { div = document.createElement("div"); hostEl.appendChild(div); cc.labels.set(l.id, div); }
        if (div.textContent !== l.text) div.textContent = l.text;
        const cls = `net-label ${l.cls}`;
        if (div.className !== cls) div.className = cls;
        tmp.copy(b.pos[idx]);
        tmp.y += b.radius[idx] * 1.2;
        tmp.project(camera);
        const sx = ((tmp.x + 1) / 2) * w, sy = ((1 - tmp.y) / 2) * h;
        const bw = l.text.length * 6.4 + 10, bh = 17;
        const box: [number, number, number, number] = [sx - bw / 2, sy - bh, sx + bw / 2, sy];
        const clash = !l.cls && placed.some((p) => box[0] < p[2] && box[2] > p[0] && box[1] < p[3] && box[3] > p[1]);
        const behind = tmp.z > 1;
        div.style.display = behind || clash ? "none" : "block";
        if (!behind && !clash) placed.push(box);
        div.style.transform = `translate(${sx}px, ${sy}px) translate(-50%, -100%)`;
      }
    };

    controls.addEventListener("change", schedule);
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth, h = el.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = `${w}px`;
      renderer.domElement.style.height = `${h}px`;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      schedule();
    });
    ro.observe(el);

    // picking (hover throttled to one raycast per animation frame)
    const mouse = new THREE.Vector2();
    let hoverRaf = 0;
    let downAt = { x: 0, y: 0 };
    const pick = (ev: PointerEvent): { node?: number; edge?: number } => {
      const cc = ctx.current!;
      const b = cc.built;
      if (!b) return {};
      const r = renderer.domElement.getBoundingClientRect();
      mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      cc.raycaster.setFromCamera(mouse, camera);
      const hit = cc.raycaster.intersectObjects([...b.meshes, b.shaft], false)[0];
      if (!hit || hit.instanceId === undefined) return {};
      const obj = hit.object as THREE.InstancedMesh;
      if (obj === b.shaft) return { edge: hit.instanceId };
      const list = b.slotNode.get(obj);
      return list ? { node: list[hit.instanceId] } : {};
    };
    const onMove = (ev: PointerEvent) => {
      cancelAnimationFrame(hoverRaf);
      hoverRaf = requestAnimationFrame(() => {
        const cc = ctx.current!;
        const b = cc.built;
        const res = pick(ev);
        const r = renderer.domElement.getBoundingClientRect();
        const prev = cc.hovered;
        cc.hovered = res.node ?? null;
        renderer.domElement.style.cursor = res.node !== undefined || res.edge !== undefined ? "pointer" : "grab";
        if (b && res.node !== undefined) props.current.onHover?.({ x: ev.clientX - r.left, y: ev.clientY - r.top, text: props.current.hoverText(b.nodes[res.node]) });
        else if (b && res.edge !== undefined) props.current.onHover?.({ x: ev.clientX - r.left, y: ev.clientY - r.top, text: props.current.hoverEdgeText(b.edges[res.edge]) });
        else props.current.onHover?.(null);
        if (prev !== cc.hovered) { refreshLabels(); schedule(); }
      });
    };
    const onDown = (ev: PointerEvent) => { downAt = { x: ev.clientX, y: ev.clientY }; };
    const onUp = (ev: PointerEvent) => {
      if (Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y) > 4) return;   // a drag, not a click
      const b = ctx.current!.built;
      const res = pick(ev);
      if (b && res.node !== undefined) props.current.onSelect(b.nodes[res.node].id);
      else if (b && res.edge !== undefined) props.current.onSelectEdge(b.edges[res.edge].id);
      else { props.current.onSelect(null); props.current.onSelectEdge(null); }
    };
    const onLeave = () => { props.current.onHover?.(null); if (ctx.current!.hovered !== null) { ctx.current!.hovered = null; refreshLabels(); schedule(); } };
    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("pointerleave", onLeave);
    renderer.domElement.style.cursor = "grab";

    return () => {
      cancelAnimationFrame(raf);
      cancelAnimationFrame(hoverRaf);
      ro.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointerleave", onLeave);
      const b = ctx.current?.built;
      if (b) disposeBuilt(b);
      geos.forEach((g) => g.dispose());
      nodeMat.dispose();
      ringGeo.dispose();
      (rings.material as THREE.Material).dispose();
      particles.geometry.dispose();
      (particles.material as THREE.Material).dispose();
      renderer.dispose();
      renderer.domElement.remove();
      ctx.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── (re)build geometry only when the scene version changes ───────────────
  useEffect(() => {
    const c = ctx.current;
    if (!c) return;
    const s = p.scene;
    if (c.lastVersion === s.version && c.built) return;
    const keepCamera = !!c.built;
    if (c.built) { c.scene.remove(c.built.group); disposeBuilt(c.built); }
    c.built = build(s, c.geos, c.nodeMat);
    c.scene.add(c.built.group);
    c.lastVersion = s.version;
    if (!keepCamera) {
      const b = c.built;
      c.controls.target.copy(b.center);
      const dist = fitDistance(c.camera, b.size);
      c.camera.position.copy(b.center).add(new THREE.Vector3(0.1, 0.32, 1).normalize().multiplyScalar(dist));
      c.scene.fog = new THREE.Fog(BG, dist * 0.75, dist * 2.4);
      c.controls.maxDistance = Math.max(2200, dist * 3);
      c.camera.far = Math.max(6000, dist * 6);
      c.camera.updateProjectionMatrix();
      c.controls.update();
    }
    applyStyle();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.scene.version]);

  // ── restyle without rebuild ────────────────────────────────────────────────
  useEffect(() => { applyStyle(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [p.style, p.selected, p.selectedEdge, p.replayT]);

  // ── camera focus on request ────────────────────────────────────────────────
  useEffect(() => {
    const c = ctx.current;
    if (!c || !c.built || !p.selected || !p.focusSeq) return;
    const i = c.built.index.get(p.selected);
    if (i === undefined) return;
    const target = c.built.pos[i].clone();
    const dir = c.camera.position.clone().sub(c.controls.target).normalize();
    const dist = Math.max(c.built.radius[i] * 16, Math.min(900, c.built.span * 0.4));
    c.tween = { t0: performance.now(), dur: 650, fromP: c.camera.position.clone(), toP: target.clone().add(dir.multiplyScalar(dist)),
                fromT: c.controls.target.clone(), toT: target };
    c.request();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.focusSeq]);

  function refreshLabels() {
    const c = ctx.current;
    if (!c || !c.built) return;
    const { style, selected } = props.current;
    const out: { id: string; text: string; cls: string }[] = [];
    const seen = new Set<string>();
    const hov = c.hovered !== null ? c.built.nodes[c.hovered] : null;
    if (selected && c.built.index.has(selected)) {
      const n = c.built.nodes[c.built.index.get(selected)!];
      out.push({ id: n.id, text: style.label(n) ?? n.label, cls: "sel" }); seen.add(n.id);
    }
    if (hov && !seen.has(hov.id)) { out.push({ id: hov.id, text: style.label(hov) ?? hov.label, cls: "hov" }); seen.add(hov.id); }
    const important = c.built.nodes.filter((n) => !seen.has(n.id) && style.label(n) !== null);
    important.sort((a, b) => b.risk - a.risk);
    for (const n of important.slice(0, 22)) out.push({ id: n.id, text: style.label(n)!, cls: "" });
    c.labelIds = out;
  }

  function applyStyle() {
    const c = ctx.current;
    if (!c || !c.built) return;
    const b = c.built;
    const { style, selected, selectedEdge, replayT } = props.current;
    const replayWindow = props.current.replayWindowMs ?? 60_000;
    const bg = new THREE.Color(BG);
    const col = new THREE.Color();
    const dummy = new THREE.Object3D();
    const selIdx = selected ? b.index.get(selected) : undefined;
    const incident = new Set<number>();
    const neighbours = new Set<number>();
    if (selIdx !== undefined) {
      neighbours.add(selIdx);
      b.edges.forEach((e, i) => {
        if (e.source === selected || e.target === selected) {
          incident.add(i); neighbours.add(b.index.get(e.source)!); neighbours.add(b.index.get(e.target)!);
        }
      });
    }

    // replay visibility
    const edgeVisible = b.edges.map((_, i) => replayT === null || b.edgeFirst[i] <= replayT);
    const nodeActive = new Set<number>();
    if (replayT !== null) {
      b.edges.forEach((e, i) => { if (edgeVisible[i]) { nodeActive.add(b.index.get(e.source)!); nodeActive.add(b.index.get(e.target)!); } });
    }

    // nodes
    b.nodes.forEach((n, i) => {
      const { mesh, slot } = b.meshOf[i];
      col.set(style.nodeColor(n));
      let dim = style.nodeDim(n);
      if (replayT !== null && !nodeActive.has(i)) dim = true;
      if (dim) col.lerp(bg, 0.72);
      else if (selIdx !== undefined && !neighbours.has(i)) col.lerp(bg, 0.45);
      mesh.setColorAt(slot, col);
    });
    b.meshes.forEach((m) => { if (m.instanceColor) m.instanceColor.needsUpdate = true; });

    // edges
    const accent = new THREE.Color(ACCENT);
    const active: { e: number; color: THREE.Color; n: number }[] = [];
    b.edges.forEach((e, i) => {
      const vis = edgeVisible[i];
      col.set(style.edgeColor(e));
      const isSel = incident.has(i) || selectedEdge === e.id;
      if (isSel) col.copy(e.tainted_paise > 0 ? col : accent);
      else if (selIdx !== undefined || selectedEdge) col.lerp(bg, 0.55);
      // shaft
      const from = b.edgeFrom[i], to = b.edgeTo[i];
      const len = from.distanceTo(to);
      const r = vis ? b.edgeR[i] * (isSel ? 1.35 : 1) : 0.0001;
      dummy.position.copy(from);
      dummy.lookAt(to);
      dummy.scale.set(r, r, vis ? Math.max(0.001, len - b.edgeR[i] * 5) : 0.0001);
      dummy.updateMatrix();
      b.shaft.setMatrixAt(i, dummy.matrix);
      b.shaft.setColorAt(i, col);
      // arrowhead at the target surface
      const aw = vis ? 1.3 * b.k + b.edgeR[i] * 2.4 : 0.0001;
      dummy.position.copy(to);
      dummy.scale.set(aw, aw, aw * 2.3);
      dummy.updateMatrix();
      b.arrow.setMatrixAt(i, dummy.matrix);
      b.arrow.setColorAt(i, col);
      // particles: selected movement, or money moving at the replay clock
      if (vis && (isSel && (incident.size <= 24 || selectedEdge === e.id))) {
        active.push({ e: i, color: col.clone().lerp(new THREE.Color(0xffffff), 0.25), n: Math.min(4, 1 + e.count) });
      } else if (replayT !== null && b.edgeTimes[i].some((t) => t <= replayT && t > replayT - replayWindow)) {
        active.push({ e: i, color: col.clone().lerp(new THREE.Color(0xffffff), 0.3), n: 3 });
      }
    });
    b.shaft.instanceMatrix.needsUpdate = true;
    b.arrow.instanceMatrix.needsUpdate = true;
    if (b.shaft.instanceColor) b.shaft.instanceColor.needsUpdate = true;
    if (b.arrow.instanceColor) b.arrow.instanceColor.needsUpdate = true;
    b.shaft.computeBoundingSphere();
    c.particleEdges = active;

    // rings: confirmed source / held / victim (status), selection (accent)
    const rings: { node: number; color: THREE.Color; scale: number }[] = [];
    b.nodes.forEach((n, i) => {
      const rc = style.ringColor(n);
      if (rc) rings.push({ node: i, color: new THREE.Color(rc), scale: 1.75 });
      if (n.victim) rings.push({ node: i, color: new THREE.Color("#e4e7ec"), scale: 2.1 });
    });
    if (selIdx !== undefined) rings.push({ node: selIdx, color: accent.clone(), scale: 2.45 });
    rings.slice(0, 512).forEach((r, i) => c.rings.setColorAt(i, r.color));
    if (c.rings.instanceColor) c.rings.instanceColor.needsUpdate = true;
    c.ringList = rings.slice(0, 512);

    refreshLabels();
    c.request();
  }

  return (
    <div ref={host} style={{ position: "absolute", inset: 0 }}>
      <div ref={labelsHost} style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }} />
    </div>
  );
}

function build(s: GraphScene, geos: Map<ShapeKey, THREE.BufferGeometry>, nodeMat: THREE.MeshStandardMaterial): Built {
  const group = new THREE.Group();
  const nodes = s.nodes;
  const index = new Map(nodes.map((n, i) => [n.id, i]));
  const pos = nodes.map((n) => new THREE.Vector3(n.x, n.y, n.z));
  const box = new THREE.Box3();
  pos.forEach((v) => box.expandByPoint(v));
  const center = box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3());
  const span = box.isEmpty() ? 200 : Math.max(120, box.getSize(new THREE.Vector3()).length());
  // glyph scale follows the layout's extent so nodes stay legible whatever units the server uses
  const k = Math.max(1, Math.min(6, span / 620));
  const radius = nodes.map((n) => nodeRadius(n) * k);

  // nodes: one InstancedMesh per role shape
  const byShape = new Map<ShapeKey, number[]>();
  nodes.forEach((n, i) => {
    const k = ROLE_SHAPE[roleKey(n.role, n.kind)].shape;
    byShape.set(k, [...(byShape.get(k) ?? []), i]);
  });
  const meshOf: Built["meshOf"] = new Array(nodes.length);
  const slotNode = new Map<THREE.InstancedMesh, number[]>();
  const meshes: THREE.InstancedMesh[] = [];
  const dummy = new THREE.Object3D();
  byShape.forEach((list, k) => {
    const mesh = new THREE.InstancedMesh(geos.get(k)!, nodeMat, list.length);
    list.forEach((ni, slot) => {
      dummy.position.copy(pos[ni]);
      dummy.rotation.set(0, 0, 0);
      const r = radius[ni];
      dummy.scale.set(r, r, r);
      dummy.updateMatrix();
      mesh.setMatrixAt(slot, dummy.matrix);
      mesh.setColorAt(slot, new THREE.Color(0x4a5260));
      meshOf[ni] = { mesh, slot };
    });
    mesh.computeBoundingSphere();
    slotNode.set(mesh, list);
    meshes.push(mesh);
    group.add(mesh);
  });

  // edges: shafts (cylinders along +Z from 0..1) and arrowheads (cone tip at origin, pointing +Z)
  const edges = s.edges.filter((e) => index.has(e.source) && index.has(e.target) && e.source !== e.target);
  const shaftGeo = new THREE.CylinderGeometry(1, 1, 1, 7, 1, true);
  shaftGeo.translate(0, 0.5, 0);
  shaftGeo.rotateX(Math.PI / 2);
  const arrowGeo = new THREE.ConeGeometry(0.5, 1, 12);
  arrowGeo.translate(0, -0.5, 0);
  arrowGeo.rotateX(Math.PI / 2);
  const edgeMat = new THREE.MeshBasicMaterial({ color: 0xffffff, fog: true });
  const shaft = new THREE.InstancedMesh(shaftGeo, edgeMat, Math.max(1, edges.length));
  const arrow = new THREE.InstancedMesh(arrowGeo, edgeMat, Math.max(1, edges.length));
  shaft.count = edges.length;
  arrow.count = edges.length;
  shaft.frustumCulled = false;
  arrow.frustumCulled = false;
  const maxAmt = Math.max(1, ...edges.map((e) => e.amount_paise));
  const edgeFrom: THREE.Vector3[] = [];
  const edgeTo: THREE.Vector3[] = [];
  const edgeR: number[] = [];
  const edgeFirst: number[] = [];
  const edgeTimes: number[][] = [];
  const dir = new THREE.Vector3();
  edges.forEach((e, i) => {
    const a = index.get(e.source)!, b = index.get(e.target)!;
    dir.subVectors(pos[b], pos[a]).normalize();
    edgeFrom.push(pos[a].clone().addScaledVector(dir, radius[a] * 1.05));
    edgeTo.push(pos[b].clone().addScaledVector(dir, -radius[b] * 1.15));
    edgeR.push((0.28 + 1.25 * Math.sqrt(e.amount_paise / maxAmt)) * k * 0.7);
    const times = e.txs.map((t) => Date.parse(t.ts)).filter((t) => !Number.isNaN(t)).sort((x, y) => x - y);
    edgeTimes.push(times.length ? times : [Date.parse(e.first_ts)]);
    edgeFirst.push(times.length ? times[0] : Date.parse(e.first_ts));
    shaft.setColorAt(i, new THREE.Color(0x33455e));
    arrow.setColorAt(i, new THREE.Color(0x33455e));
  });
  group.add(shaft, arrow);

  return {
    nodes, index, pos, radius, meshOf, slotNode, meshes, edges, edgeIndex: new Map(edges.map((e, i) => [e.id, i])),
    shaft, arrow, edgeFrom, edgeTo, edgeR, edgeFirst, edgeTimes, group, center, span, k, size: box.isEmpty() ? new THREE.Vector3(200, 200, 200) : box.getSize(new THREE.Vector3()),
  };
}

/** Camera distance that frames the layout's bounding box in the current viewport. */
function fitDistance(camera: THREE.PerspectiveCamera, size: THREE.Vector3): number {
  const vfov = (camera.fov * Math.PI) / 180;
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * Math.max(0.5, camera.aspect));
  const dW = (size.x / 2) / Math.tan(hfov / 2);
  const dH = (Math.max(size.y, size.z) / 2) / Math.tan(vfov / 2);
  return Math.max(160, Math.max(dW, dH) * 1.08 + size.z / 2);
}

function disposeBuilt(b: Built) {
  b.shaft.geometry.dispose();
  b.arrow.geometry.dispose();
  (b.shaft.material as THREE.Material).dispose();
  b.group.traverse((o) => {
    if (o instanceof THREE.Line || (o instanceof THREE.Mesh && !(o instanceof THREE.InstancedMesh))) {
      o.geometry.dispose();
      (o.material as THREE.Material).dispose();
    }
  });
  b.meshes.forEach((m) => m.dispose());
  b.shaft.dispose();
  b.arrow.dispose();
}
