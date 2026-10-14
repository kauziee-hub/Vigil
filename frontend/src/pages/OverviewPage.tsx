// OPERATIONS CENTER (Overview v11) — everything about money and accounts that can be seen at once, nothing that has
// a home elsewhere (detector families, SHAP and scoring live on Detection). Layout, top to bottom:
//   header (window · rail · incident mode · search)
//   VIGILANCE bar — the open alerts, classified, on top of everything
//   KPI strip
//   live network (left, large)   | live transactions (right)
//   money map (left)             | needs attention (right)
//   situation brief  | money by channel
//   close monitoring | mule pipeline
// One shared selection (lib/selection) links the map, tape, network, lists and Vigilance. Every number comes from the
// backend; live updates arrive over the console WebSocket (no polling). Locations are SIMULATED and labelled.
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { UniverseAccount } from "../api/types";
import type { KpiTile, Window } from "../api/v10";
import { RAILS, RAIL_LABEL } from "../api/v10";
import { EdgeViewSeg, LiveUniverse3D, UniverseLegend, type EdgeView, type UniverseInfo } from "../components/LiveUniverse3D";
import { MoneyMap } from "../components/map/MoneyMap";
import { useGeoReference } from "../components/map/useMapData";
import { ChannelChart, KpiStripV10, MulePipeline, NeedsAttention, SituationBrief } from "../components/overview/V10Panels";
import { usePlatform } from "../components/Shell";
import { ConnectionsDrawer } from "../components/tape/ConnectionsDrawer";
import { LiveTape } from "../components/tape/LiveTape";
import { UniverseDrawer } from "../components/UniverseDrawer";
import { SEV_LABEL, useIncidents, VigilanceBar } from "../components/vigilance/Vigilance";
import { WatchlistCard } from "../components/Watchlist";
import { formatPaiseShort } from "../lib/format";
import { SelectionProvider, selectionAccounts, useSelection } from "../lib/selection";
import { useVigilance } from "../lib/vigilance";
import { runAction, type ActionDeps } from "../lib/vigilanceActions";

const WINDOWS: Window[] = ["15m", "1h", "24h", "7d"];
const ROW1_H = 668;     // live network | live transactions (v12: bigger network, same orientation)
const ROW2_H = 700;     // money map + location intelligence | needs attention (v12: bigger map)

function Header({ hasIncidents, top }: { hasIncidents: boolean; top: () => void }) {
  const nav = useNavigate();
  const { conn, mode } = usePlatform();
  const { window, setWindow, channel, setChannel, incident, setIncident } = useSelection();
  const [q, setQ] = useState("");
  const go = (e: FormEvent) => {
    e.preventDefault();
    const id = q.trim();
    if (id) nav(`/investigations/account/${encodeURIComponent(id.includes("@") ? id : `${id}@vigil`)}`);
  };
  return (
    <div className="oc-head v10">
      <h1>Operations center</h1>
      <span className="chip live" title="Realtime push channel"><span className={`dot ${conn === "open" ? "ok pulse" : conn === "connecting" ? "warn" : "bad"}`} />{conn === "open" ? "Live" : conn}</span>
      <span className="chip" title={mode?.note}>{mode?.mode === "shadow" ? "Shadow mode" : "Active mode"}</span>
      <span className="spacer" />
      <div className="seg" role="group" aria-label="Time window">
        {WINDOWS.map((w) => <button key={w} className={window === w ? "on" : ""} onClick={() => setWindow(w)}>{w}</button>)}
      </div>
      <select className="input sm" value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="Payment rail">
        <option value="all">All rails</option>
        {RAILS.map((r) => <option key={r} value={r}>{RAIL_LABEL[r]}</option>)}
      </select>
      <button className={`btn sm ${incident ? "on danger" : ""}`} disabled={!incident && !hasIncidents}
              title={hasIncidents ? "Focus the whole page on the top alert" : "No open alert"}
              onClick={() => (incident ? setIncident(null) : top())}>{incident ? "Exit incident mode" : "Incident mode"}</button>
      <form onSubmit={go} style={{ flex: "0 1 260px", minWidth: 180 }}>
        <input className="input search sm" placeholder="Find an account" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search an account" />
      </form>
    </div>
  );
}

function Overview() {
  const nav = useNavigate();
  const sel = useSelection();
  const { selected, select, incident, setIncident, setTapeOnly, setChannel, openVigilance } = sel;
  const { list: incidents, loaded } = useIncidents();
  const { registerPage, takePending } = useVigilance();
  const reference = useGeoReference();
  const [edgeView, setEdgeView] = useState<EdgeView>("recent");
  const [focus, setFocus] = useState<{ ids: string[]; seq: number } | null>(null);
  const [netSel, setNetSel] = useState<{ id: string; acct: UniverseAccount | null } | null>(null);
  const [drawerTx, setDrawerTx] = useState<string | null>(null);
  const accounts = useRef(new Map<string, UniverseAccount>());
  const netRef = useRef<HTMLElement>(null);
  const mapRef = useRef<HTMLDivElement>(null);
  const attnRef = useRef<HTMLDivElement>(null);
  const pipeRef = useRef<HTMLDivElement>(null);
  // row 1 takes row 2's height (measured from the map card), so the network and the money map are the same size
  const [rowH, setRowH] = useState(ROW1_H);
  useEffect(() => {
    const el = mapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => { const h = Math.round(el.getBoundingClientRect().height); if (h > 300) setRowH(h); });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // selection → network focus
  useEffect(() => {
    const ids = selectionAccounts(selected);
    if (ids.length) { setEdgeView("risk"); setFocus({ ids, seq: Date.now() }); }
  }, [selected?.kind, selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  // incident mode → everything focuses on the incident
  useEffect(() => {
    if (!incident) return;
    const c = incident.city ? reference?.cities.find((x) => x.city === incident.city) : null;
    select({ kind: "incident", id: incident.id, accounts: incident.entities, lat: c?.lat ?? null, lng: c?.lng ?? null, label: incident.title });
  }, [incident?.id, reference]); // eslint-disable-line react-hooks/exhaustive-deps
  // an incident that closes ends incident mode
  useEffect(() => { if (incident && loaded && !incidents.some((i) => i.id === incident.id)) setIncident(null); }, [incidents]); // eslint-disable-line react-hooks/exhaustive-deps

  const scrollTo = (el: HTMLElement | null) => { if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 84, behavior: "smooth" }); };
  const focusNetwork = useCallback((ids: string[]) => { setEdgeView("risk"); setFocus({ ids, seq: Date.now() }); scrollTo(netRef.current); }, []);
  const deps: Omit<ActionDeps, "confirmWatch"> = useMemo(() => ({
    select: (s) => { select(s); if (s && (s.kind === "city" || s.kind === "cluster")) scrollTo(mapRef.current); },
    navigate: nav, openConnections: (tx: string) => setDrawerTx(tx), focusNetwork, setTapeOnly,
    cityPoint: (city: string) => { const c = reference?.cities.find((x) => x.city.toLowerCase() === city.toLowerCase()); return c ? { lat: c.lat, lng: c.lng } : null; },
  }), [select, nav, focusNetwork, setTapeOnly, reference]);
  // Vigilance (global dock) runs its map / network / tape actions through these handlers while the Overview is on screen
  useEffect(() => {
    registerPage({ select: deps.select, openConnections: deps.openConnections, focusNetwork: deps.focusNetwork,
                   setTapeOnly: deps.setTapeOnly, cityPoint: deps.cityPoint, focusIncident: (i) => setIncident(i) });
  }, [deps, registerPage, setIncident]);
  useEffect(() => () => registerPage(null), [registerPage]);
  // …and an action started on another page is carried here: run it once the city reference is ready (or after 2 s)
  useEffect(() => {
    const t = window.setTimeout(() => {
      const p = takePending();
      if (p?.focus) setIncident(p.focus);
      if (p?.action) runAction(p.action, { ...deps, confirmWatch: () => undefined });
    }, reference ? 250 : 2000);
    return () => window.clearTimeout(t);
  }, [reference]); // eslint-disable-line react-hooks/exhaustive-deps
  const onTile = (k: KpiTile["key"]) => {
    if (k === "fraud") setTapeOnly("fraud");
    else if (k === "moved") { setTapeOnly("all"); setChannel("all"); }
    else if (k === "at_risk") scrollTo(attnRef.current);
    else if (k === "stopped") nav("/interventions");
    else if (k === "left") setChannel("atm");
    else if (k === "new") scrollTo(pipeRef.current);
  };
  const onInfo = useCallback((i: UniverseInfo) => { accounts.current = i.accounts; }, []);
  const onNetSelect = useCallback((id: string | null, acct: UniverseAccount | null) => {
    setNetSel(id ? { id, acct } : null);
    if (id) select({ kind: "account", id, label: acct?.label });
  }, [select]);

  return (
    <>
      <Header hasIncidents={incidents.length > 0} top={() => setIncident(incidents[0] ?? null)} />
      {incident && (
        <div className={`inc-banner sev-${incident.severity}`}>
          <b>Incident mode</b> · {SEV_LABEL[incident.severity]} · {incident.classification}: {incident.subject}
          {incident.value_paise ? ` · ${formatPaiseShort(incident.value_paise)} at stake` : ""}
          <span className="spacer" />
          <button className="btn xs" onClick={() => openVigilance({ incidentId: incident.id })}>Open case</button>
          <button className="btn xs" onClick={() => { setIncident(null); select(null); }}>Exit incident mode</button>
        </div>
      )}
      <VigilanceBar />
      <KpiStripV10 onTile={onTile} />

      <div className="v11-row r1">
        <section className="stage net-main" ref={netRef} style={{ height: rowH }}>
          <div className="stage-h">
            <div><div className="t">Live network</div><div className="net-help">Accounts and the payments between them, live. Selecting anything elsewhere frames it here.</div></div>
            <button className="btn xs on" onClick={() => nav("/network")}>Full view</button>
          </div>
          <div className="stage-filter"><EdgeViewSeg value={edgeView} onChange={setEdgeView} /></div>
          <div className="net-canvas" style={{ position: "relative" }}>
            <LiveUniverse3D mode="live" edgeView={edgeView} autoRotate={!netSel} size="compact" selected={netSel?.id ?? null}
                            onSelect={onNetSelect} onInfo={onInfo} focus={focus} />
            {netSel && <UniverseDrawer id={netSel.id} acct={accounts.current.get(netSel.id) ?? netSel.acct} onClose={() => setNetSel(null)}
                                       onFocus={() => setFocus({ ids: [netSel.id], seq: Date.now() })} />}
          </div>
          <div className="net-legend"><UniverseLegend /></div>
        </section>
        <LiveTape height={rowH} onOpen={(r) => setDrawerTx(r.tx_id)} />
      </div>

      <div className="v11-row r2">
        <div ref={mapRef} className="map-col">
          <MoneyMap height={ROW2_H - 92} onAsk={(q) => openVigilance({ prompt: q })} />
        </div>
        <div ref={attnRef} className="attn-col">
          <NeedsAttention onAsk={(id) => openVigilance({ prompt: `Tell me about ${id} — why is it flagged and where did its money go?` })} />
        </div>
      </div>

      <div className="v10-row two eq">
        <SituationBrief onAsk={() => openVigilance({ prompt: "Give me a situation summary and what to look at first." })} />
        <ChannelChart />
      </div>
      <div className="v10-row two eq ov-bottom-row">
        <WatchlistCard />
        <div ref={pipeRef} className="pipe-col"><MulePipeline /></div>
      </div>

      {drawerTx && (
        <ConnectionsDrawer txId={drawerTx} onClose={() => setDrawerTx(null)}
          onShowMap={(c) => { select({ kind: "tx", id: c.tx.tx_id, accounts: [c.sender.id, c.recipient.id], lat: c.tx.geo.lat, lng: c.tx.geo.lng,
                                       peer: { lat: c.tx.geo.peer_lat, lng: c.tx.geo.peer_lng }, label: c.tx.geo.label }); scrollTo(mapRef.current); }}
          onShowNetwork={focusNetwork}
          onAsk={(tx) => openVigilance({ prompt: `Tell me about ${tx}: who funded the sender, where did the money go, and is it risky?` })} />
      )}
    </>
  );
}

export function OverviewPage() {
  return <SelectionProvider><Overview /></SelectionProvider>;
}
