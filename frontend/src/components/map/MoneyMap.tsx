// Money Map card: Flat | Globe toggle (remembered per browser), layer chips, the map itself (nothing floats over it),
// and the LOCATION INTELLIGENCE rail on the right with two tabs — Signals (impossible travel, coordinated cash-out,
// unusual geography, and the context of whatever is selected) and Between states (where money crosses state lines,
// risky first) — then a fold-out how-to-read with the legend. Every location is SIMULATED and labelled.
import { lazy, Suspense, useState } from "react";
import { formatPaiseShort } from "../../lib/format";
import { useSelection } from "../../lib/selection";
import { LocationIntel, useGeoIntel } from "./LocationIntel";
import { DEFAULT_LAYERS, MoneyMapFlat, type MapLayers } from "./MoneyMapFlat";
import { useGeoReference, useMapData } from "./useMapData";

const MoneyMapGlobe = lazy(() => import("./MoneyMapGlobe"));

const LAYER_LABEL: Record<keyof MapLayers, string> = {
  flows: "Money flows", fraud: "Fraud pulses", atm: "ATMs & cash-out", collection: "Collection points", location: "Location signals",
  labels: "City names",
};

function storedView(): "flat" | "globe" {
  try { return localStorage.getItem("vigil.ov.mapView") === "globe" ? "globe" : "flat"; } catch { return "flat"; }
}

export function MoneyMap({ height = 470, onAsk }: { height?: number; onAsk?: (question: string) => void }) {
  const { window, channel, selected, select } = useSelection();
  const { data, error, onPosting } = useMapData(window, channel);
  const reference = useGeoReference();
  const intel = useGeoIntel(window, selected);
  const [view, setView] = useState<"flat" | "globe">(storedView);
  const [layers, setLayers] = useState<MapLayers>(DEFAULT_LAYERS);
  const pick = (v: "flat" | "globe") => {
    setView(v);
    try { localStorage.setItem("vigil.ov.mapView", v); } catch { /* private mode */ }
  };
  const fraudCities = (data?.cities ?? []).filter((c) => c.fraud_linked_paise > 0).length;
  const cash = (data?.clusters ?? []).filter((c) => c.kind === "cash_out").length;
  const coll = (data?.clusters ?? []).filter((c) => c.kind === "collection").length;
  const city = selected?.kind === "city" ? (data?.cities ?? []).find((c) => c.city === selected.id) ?? null : null;
  const locCount = intel ? intel.impossible_travel.length + intel.anomalies.filter((a) => a.corroborates).length : 0;

  return (
    <section className="stage mmap-card">
      <div className="stage-h">
        <div>
          <div className="t">Money map <span className="sim-badge" title="Every location is synthetic and labelled with how a bank would know it (basis) and how precise that is (accuracy).">Simulated locations</span></div>
          <div className="net-help">{data
            ? <>{data.totals.postings.toLocaleString("en-IN")} postings · {formatPaiseShort(data.totals.value_paise)} in the last {window}
              {fraudCities ? <> · <b className="bad">{fraudCities} cit{fraudCities > 1 ? "ies" : "y"} with fraud-linked money</b></> : null}
              {cash ? <> · <b className="bad">{cash} cash-out cluster{cash > 1 ? "s" : ""}</b></> : null}
              {coll ? <> · {coll} collection point{coll > 1 ? "s" : ""}</> : null}
              {locCount ? <> · <b className="bad">{locCount} location signal{locCount > 1 ? "s" : ""}</b></> : null}</> : error ? "Map unavailable." : "Loading…"}</div>
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
      <div className="mmap-body">
      <div className="mmap-wrap">
        {view === "flat"
          ? <MoneyMapFlat data={data} reference={reference} layers={layers} selected={selected} onSelect={select} onPosting={onPosting} height={height}
                          intel={layers.location ? intel : null} />
          : <Suspense fallback={<div className="mmap-empty" style={{ height }}>Loading globe…</div>}>
              <MoneyMapGlobe data={data} layers={layers} selected={selected} onSelect={select} onPosting={onPosting} height={height} />
            </Suspense>}

      </div>
      <LocationIntel intel={intel} selected={selected} onSelect={select} cityData={city} onAsk={onAsk} height={height}
                     states={data?.state_flows ?? []} window={window} />
      </div>
      <details className="mmap-how">
        <summary><b>How to read the map</b>
          <span className="mmap-legend">
            <span><i className="lg flow" />normal flow</span><span><i className="lg sus" />early warning</span>
            <span><i className="lg fraud" />fraud-linked</span><span><i className="lg atmsq" />ATM</span>
            <span><i className="lg cash" />cash-out cluster</span><span><i className="lg coll" />collection point</span>
            <span><i className="lg travel" />impossible travel</span><span><i className="lg route" />selected account's moves</span>
          </span></summary>
        A dot is a city (size = money moved there in the window); an arc is money moving between cities (thicker = more
        value; <span className="bad">red</span> = an account involved is flagged, held, confirmed fraud or in a detected ring,
        <span className="warn"> amber</span> = early warning; risky arcs carry moving dashes in the direction the money goes).
        A moving spark is a real posting arriving now. Squares are ATM terminals; a red circle groups ≥ 3 risky withdrawals
        close in time and place (cash-out cluster); a diamond is a collection point (many distinct senders). Hover an arc
        for the corridor, click a city or cluster to filter the tape and network; zoom in to see individual ATMs and the
        accuracy circle of the selected posting. <b>Location intelligence</b> (right): a violet dashed line joins two places
        one account could not have travelled between (implied speed above the limit, after subtracting both points'
        accuracy); selecting an account draws its recent moves in order (1, 2, 3…) from its home ring; a selected cash-out
        cluster lights its ATMs. Card-POS points (the merchant's city) and the KYC address never count as where a customer
        is, and the distance between sender and recipient is never a signal. Location is corroborating evidence only.
      </details>
    </section>
  );
}
