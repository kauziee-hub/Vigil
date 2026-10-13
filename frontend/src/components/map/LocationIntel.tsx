// LOCATION INTELLIGENCE — the right-hand rail of the Money Map card (v12). Everything comes from /api/geo/intel
// (stored postings → vigil/geo/intel.py); nothing is computed or invented here. It answers, for whatever is selected
// (an account, a posting, a city, a cash-out cluster, an alert): is this geography normal, and if not, which rule
// fired, on what evidence (basis + accuracy), against which threshold. Locations are SIMULATED; location is
// corroborating evidence only — it can support, never decide, an account's status.
import { useCallback, useEffect, useState } from "react";
import type { CashOutCluster, GeoIntel, LocFinding, LocSelectedAccount, LocSelectedCity, MapCity, StateFlow, Window } from "../../api/v10";
import { v10 } from "../../api/v10";
import { formatPaiseShort } from "../../lib/format";
import { useThrottled } from "../../lib/live";
import type { Selection } from "../../lib/selection";
import { useConsoleEvents } from "../Shell";

export const RULE_LABEL: Record<string, string> = {
  LOC_IMPOSSIBLE_TRAVEL: "Impossible travel", LOC_UNUSUAL_REGION: "Unusual region", LOC_MULTI_CITY_BURST: "Multi-city burst",
};
const STATUS_WORD: Record<string, string> = {
  flagged: "flagged", held: "held", confirmed_fraud: "confirmed fraud", early_warning: "early warning", new: "new",
  normal: "normal", idle: "idle",
};

/** What the rail asks the backend about, for the current selection. */
function selParams(s: Selection | null): { account?: string; city?: string; cluster?: string } {
  if (!s) return {};
  if (s.kind === "account") return { account: s.id };
  if (s.kind === "tx" || s.kind === "incident") return s.accounts?.[0] ? { account: s.accounts[0] } : {};
  if (s.kind === "city") return { city: s.id };
  if (s.kind === "cluster") return s.id.startsWith("CASH-") ? { cluster: s.id } : {};
  return {};
}

export function useGeoIntel(window: Window, selected: Selection | null) {
  const [data, setData] = useState<GeoIntel | null>(null);
  const p = selParams(selected);
  const key = `${window}|${p.account ?? ""}|${p.city ?? ""}|${p.cluster ?? ""}`;
  const load = useCallback(() => {
    v10.geoIntel(window, p).then(setData).catch(() => undefined);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  const refresh = useThrottled(load, 3000);
  useConsoleEvents((e) => {
    if (["geo.location_intel", "ledger.posted", "intel.account_status", "demo.reset", "attack.run_updated"].includes(e.type)) refresh();
  });
  return data;
}

const span = (m?: number) => (m == null ? "" : m < 1 ? "under a minute" : m < 90 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} h`);
const km = (n?: number | null) => (n == null ? "—" : `${Math.round(n).toLocaleString("en-IN")} km`);
const basisShort = (label: string) => label.replace("Simulated location · ", "");

function Conf({ c }: { c: "high" | "low" }) {
  return <span className={`li-conf ${c}`} title={c === "high" ? "Both points are precise (device GPS / ATM terminal / branch)"
    : "One point is an IP estimate (±3–15 km): shown, never used as evidence"}>{c === "high" ? "high confidence" : "low precision"}</span>;
}

function TravelCard({ t, on, onPick }: { t: LocFinding; on: boolean; onPick: () => void }) {
  return (
    <button className={`li-card travel ${on ? "on" : ""}`} onClick={onPick}>
      <div className="li-card-h"><i className="li-dot travel" />Impossible travel<Conf c={t.confidence} /></div>
      <div className="li-card-t"><b>{t.from_city} → {t.to_city}</b> · {t.name ?? t.account}</div>
      <div className="li-card-m">{km(t.km)} in {span(t.minutes)} · <b className="bad">{t.speed_text ?? `${(t.kmh ?? 0).toLocaleString("en-IN")} km/h`}</b>
        <span className="dim"> (limit {(t.threshold_kmh ?? 900).toLocaleString("en-IN")})</span></div>
      <div className="li-card-s">{t.points.map((p) => basisShort(p.label)).join(" → ")}</div>
    </button>
  );
}

function ClusterCard({ c, on, onPick }: { c: CashOutCluster; on: boolean; onPick: () => void }) {
  return (
    <button className={`li-card cash ${on ? "on" : ""}`} onClick={onPick}>
      <div className="li-card-h"><i className="li-dot cash" />Coordinated cash-out<span className="li-conf high">ATM ±25 m</span></div>
      <div className="li-card-t"><b>{c.city}</b> · {c.accounts.length} suspicious accounts · {c.atm_count} ATM{c.atm_count > 1 ? "s" : ""}</div>
      <div className="li-card-m"><b className="bad">{formatPaiseShort(c.value_paise)}</b> withdrawn · radius {c.radius_km} km · {Math.max(1, Math.round(c.minutes))}-minute window</div>
      <div className="li-card-s">{c.account_names.slice(0, 4).join(", ")}{c.account_names.length > 4 ? ` +${c.account_names.length - 4}` : ""}</div>
    </button>
  );
}

function RuleBlock({ r }: { r: LocFinding }) {
  return (
    <div className={`li-rule ${r.confidence}`}>
      <div className="li-rule-h"><b>{RULE_LABEL[r.rule]}</b><Conf c={r.confidence} /></div>
      <div>{r.reason}</div>
      {r.rule === "LOC_IMPOSSIBLE_TRAVEL"
        ? <div className="li-kv"><span>Observed</span><b>{r.speed_text ?? `${(r.kmh ?? 0).toLocaleString("en-IN")} km/h`} over {km(r.effective_km)} (after accuracy)</b>
            <span>Threshold</span><b>{(r.threshold_kmh ?? 900).toLocaleString("en-IN")} km/h, ≥ 50 km</b></div>
        : <div className="li-kv"><span>Observed</span><b>{r.observed}</b><span>Threshold</span><b>{r.threshold}</b></div>}
      <div className="li-rule-b">{r.points.map((p) => `${p.city} · ${basisShort(p.label)}`).join(" → ")}</div>
    </div>
  );
}

function AccountContext({ a, contributed, onAsk }: { a: LocSelectedAccount; contributed: boolean; onAsk?: (q: string) => void }) {
  const rules = a.evidence?.rules ?? [];
  return (
    <div className="li-ctx">
      <div className="li-ctx-h"><b>{a.name}</b><span className={`li-st s-${a.status}`}>{STATUS_WORD[a.status] ?? a.status}</span></div>
      <div className={`li-verdict ${a.verdict}`}>
        {a.verdict === "normal" ? "Normal geography" : a.verdict === "suspicious" ? "Suspicious geography" : "Unconfirmed (low-precision location only)"}
        <span>{a.verdict === "normal"
          ? (a.has_baseline ? "every recent point fits where this account usually is" : "too little history to judge geography — never judged as unusual")
          : contributed ? "used as corroborating evidence in its live status" : "shown as corroborating evidence; the detectors decide the status"}</span>
      </div>
      <div className="li-kv">
        <span>Home</span><b>{a.home_city ?? "—"}</b>
        <span>Usual places</span><b>{a.usual_cities.join(", ") || "—"} <i className="dim">({a.baseline_points} points)</i></b>
      </div>
      {a.route.length > 0 && (
        <ol className="li-route">{a.route.map((p, i) => (
          <li key={p.tx_id}><i>{i + 1}</i><b>{p.city}</b><span>{p.ts.slice(11, 16)}</span><span className="dim">{basisShort(p.label)}</span></li>))}</ol>
      )}
      {rules.map((r, i) => <RuleBlock key={i} r={r} />)}
      {onAsk && <button className="btn xs primary" onClick={() => onAsk(`Explain ${a.name}'s geography: where is it usually, what changed, and is it a takeover or a mule moving cash?`)}>Ask Vigilance</button>}
    </div>
  );
}

function CityContext({ c, map, onSelect, onAsk }: { c: LocSelectedCity; map: MapCity | null; onSelect: (s: Selection) => void; onAsk?: (q: string) => void }) {
  return (
    <div className="li-ctx">
      <div className="li-ctx-h"><b>{c.city}</b>{map?.state && map.kind !== "foreign" ? <span className="dim"> · {map.state}</span> : null}</div>
      <div className="li-grid">
        <div><span>Money here</span><b>{formatPaiseShort(map?.value_paise ?? 0)}</b></div>
        <div><span>Fraud-linked</span><b className={map?.fraud_linked_paise ? "bad" : ""}>{formatPaiseShort(map?.fraud_linked_paise ?? 0)}</b></div>
        <div><span>Cash out (ATM)</span><b className={c.atm_risky ? "bad" : ""}>{formatPaiseShort(c.atm_value_paise)}</b></div>
        <div><span>Risky cash-out</span><b className={c.atm_risky ? "bad" : ""}>{c.atm_risky} · {formatPaiseShort(c.atm_risky_value_paise)}</b></div>
      </div>
      <div className="li-sub">Who is operating here ({c.accounts_here} accounts, {c.precise_here} precise fixes)</div>
      {c.risky_accounts.length
        ? c.risky_accounts.map((r) => (
            <button key={r.account} className="li-row" onClick={() => onSelect({ kind: "account", id: r.account, label: r.name, accounts: [r.account] })}>
              <span className={`li-st s-${r.status}`}>{STATUS_WORD[r.status] ?? r.status}</span><b>{r.name}</b><span>{formatPaiseShort(r.value_paise)}</span></button>))
        : <div className="dim xs">No flagged or early-warning account is active here.</div>}
      {c.newcomers.length > 0 && <div className="li-sub warn">New to this city: {c.newcomers.map((n) => `${n.name} (home ${n.home_city ?? "?"})`).join(", ")}</div>}
      {c.travel.length > 0 && <div className="li-sub bad">{c.travel.length} impossible-travel move{c.travel.length > 1 ? "s" : ""} start or end here</div>}
      {onAsk && <button className="btn xs primary" onClick={() => onAsk(`What is happening in ${c.city} right now? Any risky accounts, cash-outs or unusual movements?`)}>Ask Vigilance</button>}
    </div>
  );
}

function ClusterContext({ c }: { c: Omit<CashOutCluster, "kind"> }) {
  return (
    <div className="li-ctx">
      <div className="li-ctx-h"><b>Cash-out cluster · {c.city}</b></div>
      <div className="li-grid">
        <div><span>Withdrawn</span><b className="bad">{formatPaiseShort(c.value_paise)}</b></div>
        <div><span>Accounts</span><b>{c.accounts.length}</b></div>
        <div><span>ATMs</span><b>{c.atm_count}</b></div>
        <div><span>Radius · window</span><b>{c.radius_km} km · {Math.max(1, Math.round(c.minutes))} min</b></div>
      </div>
      <ol className="li-route">{c.withdrawals.map((w, i) => (
        <li key={w.tx_id}><i>{i + 1}</i><b>{c.account_names[c.accounts.indexOf(w.account)] ?? w.account}</b><span>{w.ts.slice(11, 16)}</span>
          <span>{formatPaiseShort(w.amount_paise)}</span></li>))}</ol>
      <div className="li-rule-b">{c.rule}. {c.basis}. ATMs: {c.atms.map((a) => `${a.terminal_id} (${a.site})`).join(", ")}</div>
    </div>
  );
}

/** Where money crosses state lines in the window, risky first: the country-level view of the map's corridors. */
function BetweenStates({ states, window, onSelect }: { states: StateFlow[]; window: Window; onSelect: (s: Selection) => void }) {
  if (!states.length) return <div className="li-normal"><b>No money crossed a state line</b>in the last {window}.</div>;
  const max = Math.max(1, ...states.map((x) => x.value_paise));
  const risky = states.reduce((n, x) => n + x.fraud_linked_paise, 0);
  const byDest = new Map<string, number>();
  states.forEach((x) => byDest.set(x.to_state, (byDest.get(x.to_state) ?? 0) + x.fraud_linked_paise));
  const top = [...byDest.entries()].sort((a, b) => b[1] - a[1])[0];
  return (
    <>
      <div className="li-note">{risky && top && top[1]
        ? <><b className="bad">{Math.round((100 * top[1]) / risky)}%</b> of the fraud-linked money crossing state lines ends in <b>{top[0]}</b>.</>
        : <>No fraud-linked money crossed a state line in the last {window}.</>}</div>
      <div className="li-states">
        {states.slice(0, 8).map((x) => (
          <button key={`${x.from_state}>${x.to_state}`} className={`li-state r-${x.risk}`}
                  title={`${x.top_pair.from_city} → ${x.top_pair.to_city} is the main city pair`}
                  onClick={() => onSelect({ kind: "city", id: x.top_pair.from_city, label: x.top_pair.from_city,
                                            lat: x.top_pair.from_lat, lng: x.top_pair.from_lng,
                                            peer: { lat: x.top_pair.to_lat, lng: x.top_pair.to_lng } })}>
            <span className="li-state-n">{x.from_state} → {x.to_state}</span>
            <span className="li-state-v">{formatPaiseShort(x.value_paise)}</span>
            <span className="li-state-bar"><i className="all" style={{ width: `${Math.max(4, (100 * x.value_paise) / max)}%` }}>
              <i className="fraud" style={{ width: `${(100 * x.fraud_linked_paise) / Math.max(1, x.value_paise)}%` }} />
              <i className="sus" style={{ width: `${(100 * x.suspicious_paise) / Math.max(1, x.value_paise)}%` }} /></i></span>
            <span className="li-state-why">{x.risk === "normal" ? `ordinary · ${x.tx_count} postings` :
              `${x.risky_accounts} risky account${x.risky_accounts === 1 ? "" : "s"} · ${formatPaiseShort(x.fraud_linked_paise || x.suspicious_paise)} ${x.risk === "fraud" ? "fraud-linked" : "early warning"}`}
              {" · "}{x.top_pair.from_city} → {x.top_pair.to_city}</span>
          </button>
        ))}
      </div>
    </>
  );
}

export function LocationIntel({ intel, selected, onSelect, cityData, onAsk, height, states = [], window = "1h" }: {
  intel: GeoIntel | null; selected: Selection | null; onSelect: (s: Selection | null) => void;
  cityData: MapCity | null; onAsk?: (q: string) => void; height?: number; states?: StateFlow[]; window?: Window;
}) {
  const style = height ? { height } : undefined;     // the rail never makes the card taller than the map
  const [tab, setTab] = useState<"signals" | "states">("signals");
  if (!intel) return <aside className="li-rail" style={style}><div className="li-h"><b>Location intelligence</b></div><div className="dim xs">Loading…</div></aside>;
  const travel = intel.impossible_travel;
  const cash = intel.cash_out;
  const anomalies = intel.anomalies.filter((a) => a.rules.some((r) => r.rule !== "LOC_IMPOSSIBLE_TRAVEL"));
  const sel = intel.selected;
  const contributed = sel?.kind === "account" ? !!intel.anomalies.find((x) => x.account === sel.account)?.contributed : false;
  const selAccount = selected?.kind === "account" ? selected.id : selected?.accounts?.[0];
  const pickTravel = (t: LocFinding) => {
    const [a, b] = t.points;
    onSelect({ kind: "account", id: t.account, accounts: [t.account], label: `${t.from_city} → ${t.to_city}`,
               lat: a.lat, lng: a.lng, peer: { lat: b.lat, lng: b.lng } });
  };
  const pickCluster = (c: CashOutCluster) => onSelect({ kind: "cluster", id: c.id, accounts: c.accounts, lat: c.center?.lat, lng: c.center?.lng, label: c.city ?? c.id });
  const n = intel.normal;
  const quiet = travel.length === 0 && cash.length === 0 && anomalies.length === 0;
  return (
    <aside className="li-rail" style={style} onPointerDown={(e) => e.stopPropagation()} aria-label="Location intelligence">
      <div className="li-h">
        <b>Location intelligence</b><span className="mmap-live"><i />Live</span>
        {selected && <button className="vg-x" onClick={() => onSelect(null)} aria-label="Clear the selection">✕</button>}
      </div>
      <div className="seg li-tabs" role="tablist" aria-label="Location intelligence view">
        <button role="tab" aria-selected={tab === "signals"} className={tab === "signals" ? "on" : ""} onClick={() => setTab("signals")}>Signals</button>
        <button role="tab" aria-selected={tab === "states"} className={tab === "states" ? "on" : ""} onClick={() => setTab("states")}>Between states</button>
      </div>
      {tab === "states" ? <div className="li-list"><BetweenStates states={states} window={window} onSelect={onSelect} /></div> : <>
      <div className="li-sum">
        <span className={travel.length ? "bad" : ""}>{travel.length} impossible travel</span>
        <span className={cash.length ? "bad" : ""}>{cash.length} cash-out cluster{cash.length === 1 ? "" : "s"}</span>
        <span className={anomalies.length ? "warn" : ""}>{anomalies.length} unusual geography</span>
      </div>

      {sel?.kind === "account" && <AccountContext a={sel} contributed={contributed} onAsk={onAsk} />}
      {sel?.kind === "city" && <CityContext c={sel} map={cityData} onSelect={onSelect} onAsk={onAsk} />}
      {sel?.kind === "cluster" && <ClusterContext c={sel} />}
      {selected?.kind === "tx" && selected.label && <div className="li-note">This posting: {basisShort(selected.label)}</div>}

      <div className="li-list">
        {travel.map((t) => <TravelCard key={t.tx_ids.join("-")} t={t} on={selAccount === t.account} onPick={() => pickTravel(t)} />)}
        {cash.map((c) => <ClusterCard key={c.id} c={c} on={selected?.id === c.id} onPick={() => pickCluster(c)} />)}
        {anomalies.map((a) => {
          const r = a.rules.find((x) => x.rule !== "LOC_IMPOSSIBLE_TRAVEL")!;
          const p = r.points[0];
          return (
            <button key={a.account} className={`li-card anom ${selAccount === a.account ? "on" : ""}`}
                    onClick={() => onSelect({ kind: "account", id: a.account, accounts: [a.account], label: a.name, lat: p?.lat, lng: p?.lng })}>
              <div className="li-card-h"><i className="li-dot anom" />{RULE_LABEL[r.rule]}<Conf c={r.confidence} /></div>
              <div className="li-card-t"><b>{a.name}</b> · {r.rule === "LOC_UNUSUAL_REGION" ? `${r.city} (home ${r.home_city ?? "?"})` : r.cities?.join(" → ")}</div>
              <div className="li-card-s">{r.observed}</div>
            </button>
          );
        })}
        {quiet && <div className="li-normal"><b>Geography looks normal</b>Every located posting in the window fits a plausible movement for its account.</div>}
      </div>
      </>}

      <div className="li-foot">
        <div>Checked {n.located_postings.toLocaleString("en-IN")} located postings · {n.accounts} accounts · {n.cities} cities
          <span className="dim"> ({n.precise_postings} precise, {n.coarse_postings} IP-based)</span></div>
        <div className="dim">{n.fastest_normal_kmh ? `Fastest ordinary move ${n.fastest_normal_kmh.toLocaleString("en-IN")} km/h. ` : "No long ordinary moves. "}
          {intel.low_confidence.length ? `${intel.low_confidence.length} low-precision move(s) shown in data, not counted. ` : ""}
          Location corroborates; it never decides a status.</div>
        <details>
          <summary>Rules &amp; thresholds</summary>
          <ul>
            <li>Impossible travel: consecutive device-GPS / ATM / branch points, &gt; {intel.thresholds.impossible_travel_kmh} km/h over ≥ {intel.thresholds.min_km} km after subtracting both accuracies.</li>
            <li>Unusual region: a city outside the account's usual places, ≥ {intel.thresholds.unusual_region_min_km} km from home and every usual point (needs history).</li>
            <li>Multi-city burst: {intel.thresholds.multi_city}.</li>
            <li>Cash-out cluster: ≥ {intel.thresholds.cash_out.cash_out_min_withdrawals} risky ATM withdrawals within {intel.thresholds.cash_out.cash_out_radius_km} km and {intel.thresholds.cash_out.cash_out_window_min} min.</li>
            <li>Card POS (merchant's city) and KYC address are never treated as where the customer is; sender–recipient distance is never a signal.</li>
          </ul>
        </details>
      </div>
    </aside>
  );
}
