// Money Map card: Flat | Globe toggle (remembered per browser), layer chips, and overlays shared by both views —
// the busiest corridors right now (risky first), a card for the selected city with "Ask Vigilance", and a fold-out
// how-to-read with the legend. Every location is SIMULATED and labelled.
import { lazy, Suspense, useMemo, useState } from "react";
import type { MapFlow } from "../../api/v10";
import { RAIL_LABEL, type Rail } from "../../api/v10";
import { formatPaiseShort } from "../../lib/format";
import { useSelection } from "../../lib/selection";
import { DEFAULT_LAYERS, MoneyMapFlat, type MapLayers } from "./MoneyMapFlat";
import { useGeoReference, useMapData } from "./useMapData";

const MoneyMapGlobe = lazy(() => import("./MoneyMapGlobe"));

const LAYER_LABEL: Record<keyof MapLayers, string> = {
  flows: "Money flows", fraud: "Fraud pulses", atm: "ATMs & cash-out", collection: "Collection points", labels: "City names",
};
const RISK_WORD = { normal: "normal", suspicious: "early warning", fraud: "fraud-linked" } as const;

function storedView(): "flat" | "globe" {
  try { return localStorage.getItem("vigil.ov.mapView") === "globe" ? "globe" : "flat"; } catch { return "flat"; }
}

export function railsText(rails: Record<string, number>): string {
  return Object.entries(rails).sort((a, b) => b[1] - a[1]).slice(0, 3)
    .map(([r, n]) => `${RAIL_LABEL[r as Rail] ?? r.toUpperCase()} ${n}`).join(" · ");
}

export function MoneyMap({ height = 470, onAsk }: { height?: number; onAsk?: (question: string) => void }) {
  const { window, channel, selected, select } = useSelection();
  const { data, error, onPosting } = useMapData(window, channel);
  const reference = useGeoReference();
  const [view, setView] = useState<"flat" | "globe">(storedView);
  const [layers, setLayers] = useState<MapLayers>(DEFAULT_LAYERS);
  const [corridorsOpen, setCorridorsOpen] = useState(true);
  const pick = (v: "flat" | "globe") => {
    setView(v);
    try { localStorage.setItem("vigil.ov.mapView", v); } catch { /* private mode */ }
  };
  const fraudCities = (data?.cities ?? []).filter((c) => c.fraud_linked_paise > 0).length;
  const cash = (data?.clusters ?? []).filter((c) => c.kind === "cash_out").length;
  const coll = (data?.clusters ?? []).filter((c) => c.kind === "collection").length;
  const corridors = useMemo(() => {
    const rank = { fraud: 2, suspicious: 1, normal: 0 } as const;
    return [...(data?.flows ?? [])].filter((f) => f.from_city !== f.to_city)
      .sort((a, b) => rank[b.risk] - rank[a.risk] || b.value_paise - a.value_paise).slice(0, 4);
  }, [data]);
  const maxCorr = Math.max(1, ...corridors.map((f) => f.value_paise));
  const city = selected?.kind === "city" ? (data?.cities ?? []).find((c) => c.city === selected.id) ?? null : null;
  const cityFlows = city ? (data?.flows ?? []).filter((f) => f.from_city === city.city || f.to_city === city.city) : [];
  // a corridor selects its origin city and frames both ends (peer = the destination)
  const pickCorridor = (f: MapFlow) => select({ kind: "city", id: f.from_city, lat: f.from_lat, lng: f.from_lng, label: f.from_city,
                                                peer: { lat: f.to_lat, lng: f.to_lng } });

  return (
    <section className="stage mmap-card">
      <div className="stage-h">
        <div>
          <div className="t">Money map <span className="sim-badge" title="Every location is synthetic and labelled with how a bank would know it (basis) and how precise that is (accuracy).">Simulated locations</span></div>
          <div className="net-help">{data
            ? <>{data.totals.postings.toLocaleString("en-IN")} postings · {formatPaiseShort(data.totals.value_paise)} in the last {window}
              {fraudCities ? <> · <b className="bad">{fraudCities} cit{fraudCities > 1 ? "ies" : "y"} with fraud-linked money</b></> : null}
              {cash ? <> · <b className="bad">{cash} cash-out cluster{cash > 1 ? "s" : ""}</b></> : null}
              {coll ? <> · {coll} collection point{coll > 1 ? "s" : ""}</> : null}</> : error ? "Map unavailable." : "Loading…"}</div>
        </div>
        <div className="row tight">
          <div className="seg seg-dark" role="group" aria-label="Map view">
            <button className={view === "flat" ? "on" : ""} onClick={() => pick("flat")}>Flat</button>
            <button className={view === "globe" ? "on" : ""} onClick={() => pick("globe")}>Globe</button>
          </div>
        </div>
      </div>
      <div className="stage-filter mmap-layers">
        {(Object.keys(LAYER_LABEL) as (keyof MapLayers)[]).map((k) => (
          <button key={k} className={`chipbtn ${layers[k] ? "on" : ""}`} aria-pressed={layers[k]}
                  onClick={() => setLayers((l) => ({ ...l, [k]: !l[k] }))}>{LAYER_LABEL[k]}</button>
        ))}
      </div>
      <div className="mmap-wrap">
        {view === "flat"
          ? <MoneyMapFlat data={data} reference={reference} layers={layers} selected={selected} onSelect={select} onPosting={onPosting} height={height} />
          : <Suspense fallback={<div className="mmap-empty" style={{ height }}>Loading globe…</div>}>
              <MoneyMapGlobe data={data} layers={layers} selected={selected} onSelect={select} onPosting={onPosting} height={height} />
            </Suspense>}

        {corridors.length > 0 && (
          <div className={`mmap-corr ${corridorsOpen ? "" : "folded"}`} onPointerDown={(e) => e.stopPropagation()}>
            <button className="mmap-corr-h" onClick={() => setCorridorsOpen((v) => !v)} aria-expanded={corridorsOpen}>
              <span className="mmap-live"><i />Live</span> Top corridors · {window}<span className="caret">{corridorsOpen ? "▾" : "▸"}</span>
            </button>
            {corridorsOpen && corridors.map((f) => (
              <button key={`${f.from_city}-${f.to_city}`} className={`mmap-corr-row r-${f.risk}`} onClick={() => pickCorridor(f)}
                      title={`${f.tx_count} postings · ${RISK_WORD[f.risk]} · ${railsText(f.rails)}`}>
                <span className="mmap-corr-n">{f.from_city} → {f.to_city}</span>
                <span className="mmap-corr-v">{formatPaiseShort(f.value_paise)}</span>
                <span className="mmap-corr-bar"><i style={{ width: `${Math.max(6, (100 * f.value_paise) / maxCorr)}%` }} /></span>
              </button>
            ))}
          </div>
        )}

        {city && (
          <div className="mmap-city" onPointerDown={(e) => e.stopPropagation()}>
            <div className="mmap-city-h"><b>{city.city}</b>{city.state && city.kind !== "foreign" ? <span className="dim"> · {city.state}</span> : null}
              <button className="vg-x" onClick={() => select(null)} aria-label="Clear the city selection">✕</button></div>
            <div className="mmap-city-g">
              <div><span>Postings</span><b>{city.tx_count}</b></div>
              <div><span>Value</span><b>{formatPaiseShort(city.value_paise)}</b></div>
              <div><span>Fraud-linked</span><b className={city.fraud_linked_paise ? "bad" : ""}>{formatPaiseShort(city.fraud_linked_paise)}</b></div>
              <div><span>At-risk accounts</span><b className={city.at_risk_accounts ? "warn" : ""}>{city.at_risk_accounts}</b></div>
            </div>
            {cityFlows.length > 0 && <div className="mmap-city-f">{cityFlows.slice(0, 3).map((f) => (
              <div key={`${f.from_city}-${f.to_city}`} className={`r-${f.risk}`}>{f.from_city === city.city ? `→ ${f.to_city}` : `← ${f.from_city}`}
                <b>{formatPaiseShort(f.value_paise)}</b></div>))}</div>}
            <div className="mmap-city-a">
              {onAsk && <button className="btn xs primary" onClick={() => onAsk(`What is happening in ${city.city} right now? Any risky accounts or cash-outs?`)}>Ask Vigilance</button>}
              <span className="dim xs">The tape and network are filtered to this city.</span>
            </div>
          </div>
        )}
      </div>
      <details className="mmap-how">
        <summary><b>How to read the map</b>
          <span className="mmap-legend">
            <span><i className="lg flow" />normal flow</span><span><i className="lg sus" />early warning</span>
            <span><i className="lg fraud" />fraud-linked</span><span><i className="lg atmsq" />ATM</span>
            <span><i className="lg cash" />cash-out cluster</span><span><i className="lg coll" />collection point</span>
          </span></summary>
        A dot is a city (size = money moved there in the window); an arc is money moving between cities (thicker = more
        value; <span className="bad">red</span> = an account involved is flagged, held, confirmed fraud or in a detected ring,
        <span className="warn"> amber</span> = early warning; risky arcs carry moving dashes in the direction the money goes).
        A moving spark is a real posting arriving now. Squares are ATM terminals; a red circle groups ≥ 3 risky withdrawals
        close in time and place (cash-out cluster); a diamond is a collection point (many distinct senders). Hover an arc
        for the corridor, click a city or cluster to filter the tape and network; zoom in to see individual ATMs and the
        accuracy circle of the selected posting.
      </details>
    </section>
  );
}
