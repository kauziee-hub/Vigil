// UniverseEngine — imperative three.js renderer for the live transaction universe.
// A TypeScript port of the refined reference's LiveGraph3D cost model, extended for Vigil:
//   • nodes = 2 InstancedMeshes (core + additive glow) → 2 draw calls; status rings = 1 more (held / confirmed / selected);
//   • live edges = ONE LineSegments buffer rewritten in place; history "constellation" = one more, faint;
//   • travellers (live postings) = one InstancedMesh;
//   • deterministic layout by stable hash (customers in a sphere, merchants in a core shell, demo customers in their own
//     shell, external counterparties on an outer ring) — no physics;
//   • raycast only after the pointer moved; render paused while off-screen or the tab is hidden;
//   • no per-frame allocation; LOD labels (hover / selected / alarm statuses only) as a small DOM pool.
// It owns no data and never fetches: the React wrapper feeds it the API payload and WebSocket deltas.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { AccountStatus } from "../api/types";

export type UniverseMode = "live" | "risk" | "model" | "roles" | "taint";

export interface UNode {
  id: string;
  label: string;
  group: "customer" | "merchant" | "demo" | "mule_attack" | "external";
  status: AccountStatus;
  risk: number;
  model_risk: number | null;
  role: string | null;
  last_active?: string | null;
}
export interface UEdge {
  id: string; source: string; target: string; ts: string; amount_paise: number; origin?: string; scenario?: string | null;
}
export interface UStats { nodes: number; liveEdges: number; pairs: number; active: number; byStatus: Record<string, number> }
export interface UHover { id: string; x: number; y: number }

const C = (h: string) => new THREE.Color(h);
const STATUS_COLOR: Record<string, THREE.Color> = {
  normal: C("#5f86b8"), idle: C("#2c3a4e"), new: C("#5fb0d6"), early_warning: C("#d6a23f"), flagged: C("#e2564e"),
  held: C("#9283d6"), confirmed_fraud: C("#e23a55"), external: C("#4a5260"),
};
const STATUS_SCALE: Record<string, number> = {
  normal: 1, idle: 0.72, new: 1.45, early_warning: 1.55, flagged: 2.0, held: 1.9, confirmed_fraud: 2.25, external: 0.8,
};
const BAND = { normal: C("#5f86b8"), watch: C("#d6a23f"), high: C("#dd7a3e"), critical: C("#e2564e") };
const DIM = C("#1e2530");
const ROLE_ON = C("#dfe4ec");
const TAINT = C("#e23a55");
const EDGE = C("#6a84aa");
const EDGE_EARLY = C("#d6a23f");
const EDGE_ALARM = C("#e2564e");
const EDGE_HELD = C("#9283d6");
const EDGE_GT = C("#c56fb0");
const RING_FRAUD = C("#e23a55");
const RING_HELD = C("#a99be6");
const RING_SEL = C("#5b93f0");

export function hashUnit(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i += 1) { h ^= seed.charCodeAt(i); h = Math.imul(h, 16777619); }
  // murmur3 finaliser: FNV alone barely changes the high bits for ids differing only in their last characters.
  h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b); h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35); h ^= h >>> 16;
  return (h >>> 0) / 4294967295;
}

function band(v: number | null | undefined): THREE.Color | null {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  if (v >= 0.75) return BAND.critical;
  if (v >= 0.5) return BAND.high;
  if (v >= 0.3) return BAND.watch;
  return BAND.normal;
}

const ALARM = new Set(["flagged", "held", "confirmed_fraud"]);
const ROLE_NONE = new Set(["", "normal", "unclassified", "victim"]);

interface NState {
  id: string; label: string; group: UNode["group"]; status: AccountStatus; risk: number; modelRisk: number | null;
  role: string | null; taint: number; phase: number; lastSeen: number; pulseUntil: number; painted: string;
}
interface Pair { key: string; i: number; j: number; count: number; last: number; gt: boolean; amount: number }
interface Traveller { i: number; j: number; t0: number; dur: number; color: THREE.Color }

export class UniverseEngine {
  private container: HTMLElement;
  private labelsHost: HTMLElement | null;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private root = new THREE.Group();
  private raycaster = new THREE.Raycaster();
  private core!: THREE.InstancedMesh;
  private glow!: THREE.InstancedMesh;
  private rings: THREE.InstancedMesh;
  private lines!: THREE.LineSegments;
  private hist!: THREE.LineSegments;
  private trav: THREE.InstancedMesh;
  private capacity = 0;
  private edgeCap = 0;
  private histCap = 0;
  private nodes: NState[] = [];
  private index = new Map<string, number>();
  private base = new Float32Array(0);
  private cur = new Float32Array(0);
  private pairs = new Map<string, Pair>();
  private histPairs: { i: number; j: number }[] = [];
  private travellers: Traveller[] = [];
  private maxTravellers = 120;
  private colorsDirty = true;
  private histDirty = true;
  private mode: UniverseMode = "live";
  private groundTruth = false;
  private selected = -1;
  private hover = -1;
  private mouse = new THREE.Vector2(2, 2);
  private pointer = { x: 0, y: 0 };
  private pointerMoved = false;
  private downAt: { x: number; y: number } | null = null;
  private visible = true;
  private disposed = false;
  private raf = 0;
  private windowMs = 10 * 60 * 1000;
  private skew = 0;
  private lastHousekeeping = 0;
  private lastLabels = 0;
  private handlers: { hover?: (h: UHover | null) => void; click?: (id: string) => void; stats?: (s: UStats) => void } = {};
  private labelPool: HTMLDivElement[] = [];
  private ro: ResizeObserver | null = null;
  private io: IntersectionObserver | null = null;
  private tween: { t0: number; dur: number; fp: THREE.Vector3; tp: THREE.Vector3; ft: THREE.Vector3; tt: THREE.Vector3 } | null = null;
  // scratch (no per-frame allocation)
  private m4 = new THREE.Matrix4();
  private q = new THREE.Quaternion();
  private v3 = new THREE.Vector3();
  private s3 = new THREE.Vector3();
  private col = new THREE.Color();

  constructor(container: HTMLElement, labelsHost: HTMLElement | null, opts: { autoRotate?: boolean; distance?: number } = {}) {
    this.container = container;
    this.labelsHost = labelsHost;
    this.scene.fog = new THREE.FogExp2(0x0a0d12, 0.00016);
    this.camera = new THREE.PerspectiveCamera(58, 1, 1, 20000);
    this.camera.position.set(0, 260, opts.distance ?? 1750);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);
    container.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.cursor = "grab";
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.minDistance = 80;
    this.controls.maxDistance = 6000;
    this.controls.autoRotate = !!opts.autoRotate;
    this.controls.autoRotateSpeed = 0.25;
    this.scene.add(this.root);
    this.initBackground();
    this.initNodes(512);
    this.initEdges(1024);
    this.initHistory(1024);
    this.rings = new THREE.InstancedMesh(new THREE.TorusGeometry(1, 0.09, 6, 40),
      new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthWrite: false }), 96);
    this.rings.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    for (let i = 0; i < 96; i++) this.rings.setColorAt(i, RING_SEL);
    this.rings.count = 0;
    this.rings.frustumCulled = false;
    this.root.add(this.rings);
    this.trav = new THREE.InstancedMesh(new THREE.SphereGeometry(2.6, 8, 6),
      new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95, depthWrite: false, blending: THREE.AdditiveBlending }),
      this.maxTravellers);
    this.trav.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    for (let i = 0; i < this.maxTravellers; i++) this.trav.setColorAt(i, EDGE);
    this.trav.count = 0;
    this.trav.frustumCulled = false;
    this.root.add(this.trav);
    this.bind();
    this.resize();
    this.raf = requestAnimationFrame(this.loop);
  }

  // ───────────────────────────────────────────────────────────── setup
  /** A neutral floor grid as the only spatial reference — no decorative starfield. */
  private initBackground() {
    const grid = new THREE.GridHelper(4600, 72, 0x2a3240, 0x1a2029);
    grid.position.y = -780;
    const gm = grid.material as THREE.Material;
    gm.transparent = true;
    gm.opacity = 0.35;
    this.scene.add(grid);
  }

  private initNodes(capacity: number) {
    if (this.core) {
      this.root.remove(this.core, this.glow);
      this.core.geometry.dispose(); this.glow.geometry.dispose();
      (this.core.material as THREE.Material).dispose(); (this.glow.material as THREE.Material).dispose();
      this.core.dispose(); this.glow.dispose();
    }
    const prev = this.capacity;
    this.capacity = capacity;
    this.core = new THREE.InstancedMesh(new THREE.SphereGeometry(4.6, 14, 10), new THREE.MeshBasicMaterial({ color: 0xffffff }), capacity);
    this.glow = new THREE.InstancedMesh(new THREE.SphereGeometry(4.6 * 2.2, 12, 8), new THREE.MeshBasicMaterial({
      color: 0xffffff, transparent: true, opacity: 0.07, depthWrite: false, blending: THREE.AdditiveBlending,
    }), capacity);
    for (const m of [this.core, this.glow]) {
      m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      // instanceColor must exist before the first render or the shader compiles without per-instance colour
      for (let i = 0; i < capacity; i++) m.setColorAt(i, STATUS_COLOR.idle);
      m.count = this.nodes.length;
      m.frustumCulled = false;
      this.root.add(m);
    }
    if (prev < capacity) {
      const grow = (old: Float32Array) => { const next = new Float32Array(capacity * 3); next.set(old); return next; };
      this.base = grow(this.base);
      this.cur = grow(this.cur);
    }
    for (let i = 0; i < this.nodes.length; i++) this.nodes[i].painted = "";
  }

  private lineSeg(capacity: number, opacity: number): THREE.LineSegments {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(capacity * 6), 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(capacity * 6), 3).setUsage(THREE.DynamicDrawUsage));
    g.setDrawRange(0, 0);
    const l = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity, depthWrite: false, blending: THREE.NormalBlending,
    }));
    l.frustumCulled = false;
    return l;
  }

  private initEdges(capacity: number) {
    if (this.lines) { this.root.remove(this.lines); this.lines.geometry.dispose(); }
    this.edgeCap = capacity;
    this.lines = this.lineSeg(capacity, 0.9);
    this.root.add(this.lines);
    this.colorsDirty = true;
  }

  private initHistory(capacity: number) {
    if (this.hist) { this.root.remove(this.hist); this.hist.geometry.dispose(); }
    this.histCap = capacity;
    this.hist = this.lineSeg(capacity, 0.16);
    this.root.add(this.hist);
    this.histDirty = true;
  }

  private bind() {
    const el = this.renderer.domElement;
    el.addEventListener("pointermove", this.onMove, { passive: true });
    el.addEventListener("pointerleave", this.onLeave, { passive: true });
    el.addEventListener("pointerdown", this.onDown, { passive: true });
    el.addEventListener("pointerup", this.onUp, { passive: true });
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.container);
    this.io = new IntersectionObserver((es) => { this.visible = es.some((e) => e.isIntersecting); });
    this.io.observe(this.container);
  }
  private onMove = (e: PointerEvent) => {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.mouse.x = ((e.clientX - r.left) / Math.max(r.width, 1)) * 2 - 1;
    this.mouse.y = -((e.clientY - r.top) / Math.max(r.height, 1)) * 2 + 1;
    this.pointer.x = e.clientX - r.left;
    this.pointer.y = e.clientY - r.top;
    this.pointerMoved = true;
  };
  private onLeave = () => { this.mouse.set(2, 2); this.pointerMoved = true; };
  private onDown = (e: PointerEvent) => {
    this.downAt = { x: e.clientX, y: e.clientY };
    this.renderer.domElement.style.cursor = "grabbing";
    this.tween = null;
  };
  private onUp = (e: PointerEvent) => {
    this.renderer.domElement.style.cursor = this.hover >= 0 ? "pointer" : "grab";
    if (!this.downAt) return;
    const moved = Math.hypot(e.clientX - this.downAt.x, e.clientY - this.downAt.y);
    this.downAt = null;
    if (moved < 5 && this.hover >= 0) this.handlers.click?.(this.nodes[this.hover].id);
  };

  on<K extends keyof UniverseEngine["handlers"]>(k: K, fn: NonNullable<UniverseEngine["handlers"][K]>) { this.handlers[k] = fn as never; }

  resize() {
    const w = Math.max(this.container.clientWidth, 1);
    const h = Math.max(this.container.clientHeight, 1);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.ro?.disconnect();
    this.io?.disconnect();
    const el = this.renderer.domElement;
    el.removeEventListener("pointermove", this.onMove);
    el.removeEventListener("pointerleave", this.onLeave);
    el.removeEventListener("pointerdown", this.onDown);
    el.removeEventListener("pointerup", this.onUp);
    this.controls.dispose();
    this.scene.traverse((o) => {
      const any = o as THREE.Mesh;
      any.geometry?.dispose?.();
      const mat = any.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose()); else mat?.dispose?.();
    });
    this.renderer.dispose();
    el.remove();
    this.labelPool.forEach((d) => d.remove());
  }

  // ───────────────────────────────────────────────────────────── layout
  private position(id: string, group: UNode["group"]): [number, number, number] {
    const th = hashUnit(`${id}|t`) * Math.PI * 2;
    const ph = Math.acos(hashUnit(`${id}|p`) * 2 - 1);
    const u = hashUnit(`${id}|r`);
    let r: number;
    let ySquash = 0.78;
    switch (group) {
      case "merchant": r = 180 + 200 * u; break;                   // inner shell: merchants are where everyday money converges
      case "demo": r = 420 + 30 * u; break;                        // demo customers: their own thin shell
      case "external": {                                           // outside the bank's view: an outer equatorial ring
        const a = hashUnit(`${id}|a`) * Math.PI * 2;
        return [Math.cos(a) * 1180, (u - 0.5) * 80, Math.sin(a) * 1180];
      }
      default: r = 300 + 640 * Math.cbrt(u); ySquash = 0.74;        // customers (incl. new accounts) — one sphere, no ground truth
    }
    return [Math.sin(ph) * Math.cos(th) * r, Math.cos(ph) * r * ySquash, Math.sin(ph) * Math.sin(th) * r];
  }

  // ───────────────────────────────────────────────────────────── data
  /** Server clock − local clock (ms); edge ages are computed on the server's clock. */
  setClock(serverIso: string) {
    const t = Date.parse(serverIso);
    if (!Number.isNaN(t)) this.skew = t - Date.now();
  }
  private now() { return Date.now() + this.skew; }

  setWindow(minutes: number) { this.windowMs = Math.max(1, minutes) * 60_000; }

  clear() {
    this.nodes = [];
    this.index.clear();
    this.pairs.clear();
    this.histPairs = [];
    this.travellers = [];
    this.selected = -1;
    this.hover = -1;
    this.core.count = 0;
    this.glow.count = 0;
    this.trav.count = 0;
    this.rings.count = 0;
    this.lines.geometry.setDrawRange(0, 0);
    this.hist.geometry.setDrawRange(0, 0);
    this.colorsDirty = true;
    this.histDirty = true;
  }

  upsertNode(n: Partial<UNode> & { id: string }, opts: { pulse?: boolean } = {}): number {
    let i = this.index.get(n.id);
    if (i === undefined) {
      i = this.nodes.length;
      if (i >= this.capacity) this.initNodes(this.capacity * 2);
      const group = n.group ?? "customer";
      this.nodes.push({
        id: n.id, label: n.label ?? n.id, group, status: n.status ?? "normal", risk: n.risk ?? 0, modelRisk: n.model_risk ?? null,
        role: n.role ?? null, taint: 0, phase: hashUnit(`${n.id}|ph`) * Math.PI * 2,
        lastSeen: n.last_active ? Date.parse(n.last_active) || 0 : 0, pulseUntil: 0, painted: "",
      });
      this.index.set(n.id, i);
      const p = this.position(n.id, group);
      this.base.set(p, i * 3);
      this.cur.set(p, i * 3);
      this.core.count = this.nodes.length;
      this.glow.count = this.nodes.length;
    } else {
      const s = this.nodes[i];
      if (n.label !== undefined) s.label = n.label;
      if (n.status !== undefined && n.status !== s.status) { s.status = n.status; this.colorsDirty = true; }
      if (n.risk !== undefined) s.risk = n.risk;
      if (n.model_risk !== undefined) s.modelRisk = n.model_risk;
      if (n.role !== undefined) s.role = n.role;
      if (n.last_active) s.lastSeen = Math.max(s.lastSeen, Date.parse(n.last_active) || 0);
    }
    if (opts.pulse) this.nodes[i].pulseUntil = performance.now() + 1400;
    this.nodes[i].painted = "";
    return i;
  }

  setStatus(id: string, status: AccountStatus, extra: { risk?: number | null; role?: string | null; model_risk?: number | null } = {}) {
    const i = this.index.get(id);
    if (i === undefined) return;
    const s = this.nodes[i];
    if (s.status !== status) { s.status = status; s.pulseUntil = performance.now() + 1800; }
    if (extra.risk !== undefined && extra.risk !== null) s.risk = extra.risk;
    if (extra.model_risk !== undefined) s.modelRisk = extra.model_risk;
    if (extra.role !== undefined) s.role = extra.role;
    s.painted = "";
    this.colorsDirty = true;
  }

  setTaint(map: Map<string, number>) {
    this.nodes.forEach((s) => { s.taint = map.get(s.id) ?? 0; s.painted = ""; });
    this.colorsDirty = true;
  }

  setMode(mode: UniverseMode) {
    if (mode === this.mode) return;
    this.mode = mode;
    this.nodes.forEach((s) => { s.painted = ""; });
    this.colorsDirty = true;
  }

  setGroundTruth(on: boolean) { this.groundTruth = on; this.colorsDirty = true; }
  setAutoRotate(on: boolean) { this.controls.autoRotate = on; }

  /** Add one posting: aggregates per (sender, recipient) pair in the live window. */
  addEdge(e: UEdge, traveller = true) {
    const i = this.index.get(e.source);
    const j = this.index.get(e.target);
    if (i === undefined || j === undefined) return;
    const t = Date.parse(e.ts) || this.now();
    const key = `${e.source}>${e.target}`;
    const p = this.pairs.get(key);
    const gt = !!e.scenario;
    if (p) { p.count += 1; p.last = Math.max(p.last, t); p.gt = p.gt || gt; p.amount += e.amount_paise; }
    else this.pairs.set(key, { key, i, j, count: 1, last: t, gt, amount: e.amount_paise });
    this.nodes[i].lastSeen = Math.max(this.nodes[i].lastSeen, t);
    this.nodes[j].lastSeen = Math.max(this.nodes[j].lastSeen, t);
    this.nodes[i].painted = ""; this.nodes[j].painted = "";
    this.colorsDirty = true;
    if (traveller) {
      this.nodes[i].pulseUntil = this.nodes[j].pulseUntil = performance.now() + 1200;
      if (this.travellers.length >= this.maxTravellers) this.travellers.shift();
      const a = this.nodes[i].status, b = this.nodes[j].status;
      const color = this.groundTruth && gt ? EDGE_GT
        : ALARM.has(a) || ALARM.has(b) ? EDGE_ALARM : a === "early_warning" || b === "early_warning" ? EDGE_EARLY : EDGE;
      this.travellers.push({ i, j, t0: performance.now(), dur: 1100, color });
    }
  }

  setHistory(edges: UEdge[]) {
    const seen = new Set<string>();
    this.histPairs = [];
    for (const e of edges) {
      const i = this.index.get(e.source); const j = this.index.get(e.target);
      if (i === undefined || j === undefined) continue;
      const k = i < j ? `${i}|${j}` : `${j}|${i}`;
      if (seen.has(k)) continue;
      seen.add(k);
      this.histPairs.push({ i, j });
    }
    if (this.histPairs.length > this.histCap) this.initHistory(Math.max(this.histCap * 2, this.histPairs.length));
    this.histDirty = true;
  }

  setSelected(id: string | null) {
    this.selected = id ? this.index.get(id) ?? -1 : -1;
    this.lastLabels = 0;
  }

  has(id: string) { return this.index.has(id); }

  stats(): UStats {
    const cutoff = this.now() - this.windowMs;
    const byStatus: Record<string, number> = {};
    let active = 0;
    for (const s of this.nodes) {
      const k = this.visualStatus(s, cutoff);
      byStatus[k] = (byStatus[k] ?? 0) + 1;
      if (s.lastSeen >= cutoff) active++;
    }
    let liveEdges = 0;
    this.pairs.forEach((p) => { liveEdges += p.count; });
    return { nodes: this.nodes.length, liveEdges, pairs: this.pairs.size, active, byStatus };
  }

  // ───────────────────────────────────────────────────────────── camera
  focus(ids: string[], dur = 900) {
    const pts: THREE.Vector3[] = [];
    ids.forEach((id) => { const i = this.index.get(id); if (i !== undefined) pts.push(new THREE.Vector3().fromArray(this.base, i * 3)); });
    if (!pts.length) return;
    const box = new THREE.Box3().setFromPoints(pts);
    const center = box.getCenter(new THREE.Vector3());
    const size = Math.max(box.getSize(new THREE.Vector3()).length(), 160);
    const dist = THREE.MathUtils.clamp(size * 1.6, 260, 2600);
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    this.tween = { t0: performance.now(), dur, fp: this.camera.position.clone(), tp: center.clone().add(dir.multiplyScalar(dist)),
                   ft: this.controls.target.clone(), tt: center };
  }
  resetView(dur = 900) {
    this.tween = { t0: performance.now(), dur, fp: this.camera.position.clone(), tp: new THREE.Vector3(0, 260, 1750),
                   ft: this.controls.target.clone(), tt: new THREE.Vector3() };
  }

  // ───────────────────────────────────────────────────────────── paint
  private visualStatus(s: NState, cutoff: number): string {
    if (s.group === "external" && !ALARM.has(s.status) && s.status !== "early_warning") return "external";
    if (s.status === "normal" && s.lastSeen < cutoff) return "idle";
    if (s.status === "idle" && s.lastSeen >= cutoff) return "normal";
    return s.status;
  }

  // paint result scratch (no per-frame allocation)
  private pkKey = "";
  private pkColor: THREE.Color = DIM;
  private pkScale = 1;
  private pk(key: string, color: THREE.Color, scale: number) { this.pkKey = key; this.pkColor = color; this.pkScale = scale; }

  /** Colour + base scale for a node under the current mode → pkKey / pkColor / pkScale. */
  private paintKey(s: NState, cutoff: number) {
    switch (this.mode) {
      case "risk": {
        const c = s.group === "external" ? STATUS_COLOR.external : band(s.risk) ?? DIM;
        return this.pk(c === BAND.critical ? "rc" : c === BAND.high ? "rh" : c === BAND.watch ? "rw" : c === BAND.normal ? "rn" : "rx",
          c, 0.9 + Math.min(1, s.risk) * 1.3);
      }
      case "model": {
        const c = band(s.modelRisk);
        if (!c) return this.pk("mdim", DIM, 0.6);
        return this.pk(c === BAND.critical ? "mc" : c === BAND.high ? "mh" : c === BAND.watch ? "mw" : "mn", c,
          0.9 + Math.min(1, s.modelRisk ?? 0) * 1.3);
      }
      case "roles":
        return !!s.role && !ROLE_NONE.has(s.role) ? this.pk("role", ROLE_ON, 1.8) : this.pk("rdim", DIM, 0.6);
      case "taint":
        return s.taint > 0 ? this.pk("taint", TAINT, 1.4 + Math.min(1.4, Math.log10(1 + s.taint / 100) / 4)) : this.pk("tdim", DIM, 0.6);
      default: {
        const vs = this.visualStatus(s, cutoff);
        return this.pk(vs, STATUS_COLOR[vs] ?? STATUS_COLOR.normal, STATUS_SCALE[vs] ?? 1);
      }
    }
  }

  private edgeColor(p: Pair, now: number, out: THREE.Color): THREE.Color {
    const a = this.nodes[p.i].status, b = this.nodes[p.j].status;
    if (this.mode === "live") {
      if (this.groundTruth && p.gt) return out.copy(EDGE_GT).multiplyScalar(0.95);
      if (a === "confirmed_fraud" || b === "confirmed_fraud" || a === "flagged" || b === "flagged") return out.copy(EDGE_ALARM).multiplyScalar(0.95);
      if (a === "held" || b === "held") return out.copy(EDGE_HELD).multiplyScalar(0.85);
      if (a === "early_warning" || b === "early_warning") return out.copy(EDGE_EARLY).multiplyScalar(0.65);
    } else if (this.mode === "taint") {
      if (this.nodes[p.i].taint > 0 && this.nodes[p.j].taint > 0) return out.copy(TAINT).multiplyScalar(0.9);
    }
    const age = Math.max(0, now - p.last) / this.windowMs;          // 0 = just now, 1 = leaving the window
    // ordinary flows stay quiet (additive blending piles up at busy merchants) so alarm edges read first
    const k = Math.min(0.4, 0.12 + p.count * 0.05) * (1 - 0.7 * Math.min(1, age));
    return out.copy(EDGE).multiplyScalar(this.mode === "live" ? k : k * 0.55);
  }

  private writeEdges(now: number) {
    if (this.pairs.size > this.edgeCap) this.initEdges(Math.max(this.edgeCap * 2, this.pairs.size));
    const pos = this.lines.geometry.attributes.position.array as Float32Array;
    const col = this.lines.geometry.attributes.color.array as Float32Array;
    let n = 0;
    const paint = this.colorsDirty;
    this.pairs.forEach((p) => {
      const a = p.i * 3, b = p.j * 3, o = n * 6;
      pos[o] = this.cur[a]; pos[o + 1] = this.cur[a + 1]; pos[o + 2] = this.cur[a + 2];
      pos[o + 3] = this.cur[b]; pos[o + 4] = this.cur[b + 1]; pos[o + 5] = this.cur[b + 2];
      if (paint) {
        this.edgeColor(p, now, this.col);
        col[o] = col[o + 3] = this.col.r; col[o + 1] = col[o + 4] = this.col.g; col[o + 2] = col[o + 5] = this.col.b;
      }
      n++;
    });
    this.lines.geometry.setDrawRange(0, n * 2);
    this.lines.geometry.attributes.position.needsUpdate = true;
    if (paint) this.lines.geometry.attributes.color.needsUpdate = true;

    // history constellation: positions follow the (slow) drift; colour fixed and faint
    const hp = this.hist.geometry.attributes.position.array as Float32Array;
    const hc = this.hist.geometry.attributes.color.array as Float32Array;
    let m = 0;
    for (const h of this.histPairs) {
      const a = h.i * 3, b = h.j * 3, o = m * 6;
      hp[o] = this.cur[a]; hp[o + 1] = this.cur[a + 1]; hp[o + 2] = this.cur[a + 2];
      hp[o + 3] = this.cur[b]; hp[o + 4] = this.cur[b + 1]; hp[o + 5] = this.cur[b + 2];
      if (this.histDirty) { hc[o] = hc[o + 3] = 0.24; hc[o + 1] = hc[o + 4] = 0.29; hc[o + 2] = hc[o + 5] = 0.36; }   // faint: live postings must read first
      m++;
    }
    this.hist.geometry.setDrawRange(0, m * 2);
    this.hist.geometry.attributes.position.needsUpdate = true;
    if (this.histDirty) this.hist.geometry.attributes.color.needsUpdate = true;
    this.histDirty = false;
    this.colorsDirty = false;
  }

  private housekeeping(now: number) {
    // expire pairs whose newest posting left the window; re-fade colours once a second
    const cutoff = now - this.windowMs;
    this.pairs.forEach((p, k) => { if (p.last < cutoff) this.pairs.delete(k); });
    this.colorsDirty = true;                                  // edge age fade; node idle/active is re-derived per frame
    this.handlers.stats?.(this.stats());
  }

  // ───────────────────────────────────────────────────────────── labels
  private updateLabels() {
    const host = this.labelsHost;
    if (!host) return;
    const want: number[] = [];
    if (this.selected >= 0) want.push(this.selected);
    if (this.hover >= 0 && this.hover !== this.selected) want.push(this.hover);
    if (this.mode === "live") {
      for (let i = 0; i < this.nodes.length && want.length < 22; i++) {
        if (i !== this.selected && i !== this.hover && ALARM.has(this.nodes[i].status)) want.push(i);
      }
    }
    const w = host.clientWidth, h = host.clientHeight;
    while (this.labelPool.length < want.length) {
      const d = document.createElement("div");
      d.className = "uni-label";
      host.appendChild(d);
      this.labelPool.push(d);
    }
    for (let k = 0; k < this.labelPool.length; k++) {
      const d = this.labelPool[k];
      if (k >= want.length) { if (d.style.display !== "none") d.style.display = "none"; continue; }
      const i = want[k];
      const s = this.nodes[i];
      this.v3.fromArray(this.cur, i * 3).project(this.camera);
      if (this.v3.z > 1 || this.v3.x < -1.05 || this.v3.x > 1.05 || this.v3.y < -1.05 || this.v3.y > 1.05) { d.style.display = "none"; continue; }
      const x = ((this.v3.x + 1) / 2) * w, y = ((1 - this.v3.y) / 2) * h;
      d.style.display = "";
      const text = s.label.replace("@vigil", "");
      if (d.textContent !== text) d.textContent = text;
      const cls = `uni-label${i === this.selected ? " sel" : s.status === "held" ? " held" : ALARM.has(s.status) ? " flag" : ""}`;
      if (d.className !== cls) d.className = cls;
      d.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -160%)`;
    }
  }

  // ───────────────────────────────────────────────────────────── loop
  private loop = (tMs: number) => {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.loop);
    if (!this.visible || document.hidden) return;
    const nowP = performance.now();
    const now = this.now();
    if (nowP - this.lastHousekeeping > 1000) { this.lastHousekeeping = nowP; this.housekeeping(now); }
    if (this.tween) {
      const tw = this.tween;
      const t = Math.min((nowP - tw.t0) / tw.dur, 1);
      const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      this.controls.target.lerpVectors(tw.ft, tw.tt, e);
      this.camera.position.lerpVectors(tw.fp, tw.tp, e);
      if (t >= 1) this.tween = null;
    }
    this.controls.update();
    const t = tMs * 0.001;
    const cutoff = now - this.windowMs;
    let ringN = 0;
    this.q.copy(this.camera.quaternion);
    for (let i = 0; i < this.nodes.length; i++) {
      const s = this.nodes[i];
      const o = i * 3;
      const drift = s.group === "external" ? 3 : 7;
      this.cur[o] = this.base[o] + Math.sin(t * 0.6 + s.phase) * drift;
      this.cur[o + 1] = this.base[o + 1] + Math.cos(t * 0.55 + s.phase) * drift;
      this.cur[o + 2] = this.base[o + 2] + Math.sin(t * 0.5 + s.phase * 1.3) * drift;
      this.paintKey(s, cutoff);
      if (this.pkKey !== s.painted) {
        s.painted = this.pkKey;
        this.core.setColorAt(i, this.pkColor);
        this.glow.setColorAt(i, this.pkColor);
        if (this.core.instanceColor) this.core.instanceColor.needsUpdate = true;
        if (this.glow.instanceColor) this.glow.instanceColor.needsUpdate = true;
      }
      let sc = this.pkScale;
      if (this.mode === "live" && (s.status === "flagged" || s.status === "confirmed_fraud")) sc *= 1 + Math.sin(t * 4 + s.phase) * 0.12;
      if (s.pulseUntil > nowP) sc *= 1 + 0.35 * ((s.pulseUntil - nowP) / 1400);
      if (i === this.hover) sc *= 1.35;
      if (i === this.selected) sc *= 1.5;
      this.m4.makeScale(sc, sc, sc);
      this.m4.setPosition(this.cur[o], this.cur[o + 1], this.cur[o + 2]);
      this.core.setMatrixAt(i, this.m4);
      this.glow.setMatrixAt(i, this.m4);
      // rings: confirmed fraud (crimson), held (violet), selected (mint) — billboarded to face the camera
      const ring = i === this.selected ? RING_SEL : this.mode === "live" && s.status === "confirmed_fraud" ? RING_FRAUD
        : this.mode === "live" && s.status === "held" ? RING_HELD : null;
      if (ring && ringN < 96) {
        const rs = 4.6 * sc * 2.3;
        this.s3.set(rs, rs, rs);
        this.v3.set(this.cur[o], this.cur[o + 1], this.cur[o + 2]);
        this.m4.compose(this.v3, this.q, this.s3);
        this.rings.setMatrixAt(ringN, this.m4);
        this.rings.setColorAt(ringN, ring);
        ringN++;
      }
    }
    this.core.instanceMatrix.needsUpdate = true;
    this.glow.instanceMatrix.needsUpdate = true;
    this.rings.count = ringN;
    this.rings.instanceMatrix.needsUpdate = true;
    if (this.rings.instanceColor) this.rings.instanceColor.needsUpdate = true;
    this.writeEdges(now);

    let live = 0;
    let w = 0;
    for (let k = 0; k < this.travellers.length; k++) {
      const tr = this.travellers[k];
      const p = (nowP - tr.t0) / tr.dur;
      if (p >= 1) continue;
      this.travellers[w++] = tr;
      const a = tr.i * 3, b = tr.j * 3;
      this.m4.makeScale(1, 1, 1);
      this.m4.setPosition(this.cur[a] + (this.cur[b] - this.cur[a]) * p, this.cur[a + 1] + (this.cur[b + 1] - this.cur[a + 1]) * p,
        this.cur[a + 2] + (this.cur[b + 2] - this.cur[a + 2]) * p);
      this.trav.setMatrixAt(live, this.m4);
      this.trav.setColorAt(live, tr.color);
      live++;
    }
    this.travellers.length = w;
    this.trav.count = live;
    this.trav.instanceMatrix.needsUpdate = true;
    if (this.trav.instanceColor) this.trav.instanceColor.needsUpdate = true;

    if (this.pointerMoved) {
      this.pointerMoved = false;
      let next = -1;
      if (this.mouse.x <= 1 && this.nodes.length) {
        this.raycaster.setFromCamera(this.mouse, this.camera);
        const hit = this.raycaster.intersectObject(this.glow, false)[0];
        next = hit && hit.instanceId !== undefined ? hit.instanceId : -1;
      }
      if (next !== this.hover) {
        this.hover = next;
        this.renderer.domElement.style.cursor = next >= 0 ? "pointer" : "grab";
        this.lastLabels = 0;
      }
      this.handlers.hover?.(next >= 0 ? { id: this.nodes[next].id, x: this.pointer.x, y: this.pointer.y } : null);
    }
    if (nowP - this.lastLabels > 33) { this.lastLabels = nowP; this.updateLabels(); }
    this.renderer.render(this.scene, this.camera);
  };
}
