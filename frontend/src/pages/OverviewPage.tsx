// OPERATIONS CENTER (Overview v10) — everything about money and accounts that can be seen at once, nothing that has
// a home elsewhere (detector families, SHAP and scoring live on Detection):
//   header (window · rail · incident mode) → KPI strip → Copilot incident strip → money map | live tape →
//   compact 3D network | needs attention | situation brief → close monitoring | mule pipeline → money by channel.
// One shared selection (lib/selection) links the map, tape, 3D network, lists and Copilot. Every number comes from the
// backend; live updates arrive over the console WebSocket (no polling). Locations are SIMULATED and labelled.
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { UniverseAccount } from "../api/types";
import type { KpiTile, Window } from "../api/v10";
import { RAILS, RAIL_LABEL } from "../api/v10";
import { CopilotDock, IncidentStrip, useIncidents } from "../components/copilot/Copilot";
import { EdgeViewSeg, LiveUniverse3D, UniverseLegend, type EdgeView, type UniverseInfo } from "../components/LiveUniverse3D";
import { MoneyMap } from "../components/map/MoneyMap";
import { useGeoReference } from "../components/map/useMapData";
import { ChannelChart, KpiStripV10, MulePipeline, NeedsAttention, SituationBrief } from "../components/overview/V10Panels";
import { usePlatform } from "../components/Shell";
import { ConnectionsDrawer } from "../components/tape/ConnectionsDrawer";
import { LiveTape } from "../components/tape/LiveTape";
import { UniverseDrawer } from "../components/UniverseDrawer";
import { WatchlistCard } from "../components/Watchlist";
import type { ActionDeps } from "../lib/copilotActions";
import { formatPaiseShort } from "../lib/format";
import { SelectionProvider, selectionAccounts, useSelection } from "../lib/selection";

const WINDOWS: Window[] = ["15m", "1h", "24h", "7d"];

function Header({ incidents }: { incidents: { id: string; title: string }[] }) {
  const nav = useNavigate();
  const { conn, mode } = usePlatform();
  const { window, setWindow, channel, setChannel, incident, setIncident } = useSelection();
  const all = useIncidents();
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
      <button className={`btn sm ${incident ? "on danger" : ""}`} disabled={!incident && incidents.length === 0}
              title={incidents.length ? "Focus the whole page on the top incident" : "No open incident"}
              onClick={() => setIncident(incident ? null : all.list[0] ?? null)}>{incident ? "Exit incident mode" : "Incident mode"}</button>
      <form onSubmit={go} style={{ flex: "0 1 260px", minWidth: 180 }}>
        <input className="input search sm" placeholder="Find an account" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search an account" />
      </form>
    </div>
  );
}

function Overview() {
  const nav = useNavigate();
  const sel = useSelection();
  const { selected, select, incident, setIncident, setTapeOnly, setChannel, openCopilot } = sel;
  const { list: incidents, max } = useIncidents();
  const reference = useGeoReference();
  const [edgeView, setEdgeView] = useState<EdgeView>("recent");
  const [focus, setFocus] = useState<{ ids: string[]; seq: number } | null>(null);
  const [netSel, setNetSel] = useState<{ id: string; acct: UniverseAccount | null } | null>(null);
  const [drawerTx, setDrawerTx] = useState<string | null>(null);
  const accounts = useRef(new Map<string, UniverseAccount>());
  const netRef = useRef<HTMLElement>(null);
  const attnRef = useRef<HTMLDivElement>(null);
  const pipeRef = useRef<HTMLDivElement>(null);

  // selection → 3D network focus
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
  useEffect(() => { if (incident && !incidents.some((i) => i.id === incident.id)) setIncident(null); }, [incidents]); // eslint-disable-line react-hooks/exhaustive-deps

  const scrollTo = (el: HTMLElement | null) => { if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 84, behavior: "smooth" }); };
  const focusNetwork = useCallback((ids: string[]) => { setEdgeView("risk"); setFocus({ ids, seq: Date.now() }); scrollTo(netRef.current); }, []);
  const deps: Omit<ActionDeps, "confirmWatch"> = useMemo(() => ({
    select, navigate: nav, openConnections: (tx: string) => setDrawerTx(tx), focusNetwork, setTapeOnly,
    cityPoint: (city: string) => { const c = reference?.cities.find((x) => x.city.toLowerCase() === city.toLowerCase()); return c ? { lat: c.lat, lng: c.lng } : null; },
  }), [select, nav, focusNetwork, setTapeOnly, reference]);
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
      <Header incidents={incidents} />
      {incident && (
        <div className={`inc-banner sev-${incident.severity}`}>
          <b>Incident mode</b> · {incident.kind_label}: {incident.title}{incident.value_paise ? ` · ${formatPaiseShort(incident.value_paise)} at stake` : ""}
          <span className="spacer" />
          <button className="btn xs" onClick={() => openCopilot({ incidentId: incident.id })}>Briefing</button>
          <button className="btn xs" onClick={() => { setIncident(null); select(null); }}>Exit incident mode</button>
        </div>
      )}
      <KpiStripV10 onTile={onTile} />
      <IncidentStrip incidents={incidents} max={max} />

      <div className="v10-row map-row">
        <MoneyMap height={470} />
        <LiveTape height={470} onOpen={(r) => setDrawerTx(r.tx_id)} />
      </div>

      <div className="v10-row three">
        <section className="stage net-compact" ref={netRef}>
          <div className="stage-h">
            <div><div className="t">Live network</div><div className="net-help">Accounts and the payments between them; selection elsewhere frames it here.</div></div>
            <button className="btn xs on" onClick={() => nav("/network")}>Full view</button>
          </div>
          <div className="stage-filter"><EdgeViewSeg value={edgeView} onChange={setEdgeView} /></div>
          <div style={{ position: "relative" }}>
            <LiveUniverse3D mode="live" edgeView={edgeView} autoRotate={!netSel} size="compact" selected={netSel?.id ?? null}
                            onSelect={onNetSelect} onInfo={onInfo} focus={focus} />
            {netSel && <UniverseDrawer id={netSel.id} acct={accounts.current.get(netSel.id) ?? netSel.acct} onClose={() => setNetSel(null)}
                                       onFocus={() => setFocus({ ids: [netSel.id], seq: Date.now() })} />}
          </div>
          <div className="net-legend"><UniverseLegend /></div>
        </section>
        <div ref={attnRef}><NeedsAttention onAsk={(id) => openCopilot({ prompt: `Tell me about ${id} — why is it flagged and where did its money go?` })} /></div>
        <SituationBrief onAsk={() => openCopilot({ prompt: "Give me a situation summary and what to look at first." })} />
      </div>

      <div className="v10-row two">
        <WatchlistCard />
        <div ref={pipeRef}><MulePipeline /></div>
      </div>

      <div className="v10-row one"><ChannelChart /></div>

      {drawerTx && (
        <ConnectionsDrawer txId={drawerTx} onClose={() => setDrawerTx(null)}
          onShowMap={(c) => select({ kind: "tx", id: c.tx.tx_id, accounts: [c.sender.id, c.recipient.id], lat: c.tx.geo.lat, lng: c.tx.geo.lng,
                                    peer: { lat: c.tx.geo.peer_lat, lng: c.tx.geo.peer_lng }, label: c.tx.geo.label })}
          onShowNetwork={focusNetwork}
          onAsk={(tx) => openCopilot({ prompt: `Tell me about ${tx}: who funded the sender, where did the money go, and is it risky?` })} />
      )}
      <CopilotDock incidents={incidents} deps={deps} />
    </>
  );
}

export function OverviewPage() {
  return <SelectionProvider><Overview /></SelectionProvider>;
}
