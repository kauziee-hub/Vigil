// Money Map card: Flat | Globe toggle (remembered per browser), layer chips, legend and a how-to-read line.
import { lazy, Suspense, useState } from "react";
import { formatPaiseShort } from "../../lib/format";
import { useSelection } from "../../lib/selection";
import { DEFAULT_LAYERS, MoneyMapFlat, type MapLayers } from "./MoneyMapFlat";
import { useGeoReference, useMapData } from "./useMapData";

const MoneyMapGlobe = lazy(() => import("./MoneyMapGlobe"));

const LAYER_LABEL: Record<keyof MapLayers, string> = {
  flows: "Money flows", fraud: "Fraud pulses", atm: "ATMs & cash-out", collection: "Collection points", labels: "City names",
};

function storedView(): "flat" | "globe" {
  try { return localStorage.getItem("vigil.ov.mapView") === "globe" ? "globe" : "flat"; } catch { return "flat"; }
}

export function MoneyMap({ height = 470 }: { height?: number }) {
  const { window, channel, selected, select } = useSelection();
  const { data, error, onPosting } = useMapData(window, channel);
  const reference = useGeoReference();
  const [view, setView] = useState<"flat" | "globe">(storedView);
  const [layers, setLayers] = useState<MapLayers>(DEFAULT_LAYERS);
  const pick = (v: "flat" | "globe") => {
    setView(v);
    try { localStorage.setItem("vigil.ov.mapView", v); } catch { /* private mode */ }
  };
  const fraudCities = (data?.cities ?? []).filter((c) => c.fraud_linked_paise > 0).length;
  const cash = (data?.clusters ?? []).filter((c) => c.kind === "cash_out").length;
  const coll = (data?.clusters ?? []).filter((c) => c.kind === "collection").length;
  return (
    <section className="stage mmap-card">
      <div className="stage-h">
        <div>
          <div className="t">Money map <span className="sim-badge" title="Every location is synthetic and labelled with how a bank would know it (basis) and how precise that is (accuracy).">Simulated locations</span></div>
          <div className="net-help">Where money moves right now, where it turns risky, and where it leaves the bank. {data
            ? <>{data.totals.postings.toLocaleString("en-IN")} postings · {formatPaiseShort(data.totals.value_paise)} in the last {window}
              {fraudCities ? <> · <b className="bad">{fraudCities} cities with fraud-linked money</b></> : null}
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
        <span className="spacer" />
        <span className="mmap-legend">
          <span><i className="lg flow" />normal flow</span><span><i className="lg sus" />early warning</span>
          <span><i className="lg fraud" />fraud-linked</span><span><i className="lg atmsq" />ATM</span>
          <span><i className="lg cash" />cash-out cluster</span><span><i className="lg coll" />collection point</span>
        </span>
      </div>
      {view === "flat"
        ? <MoneyMapFlat data={data} reference={reference} layers={layers} selected={selected} onSelect={select} onPosting={onPosting} height={height} />
        : <Suspense fallback={<div className="mmap-empty" style={{ height }}>Loading globe…</div>}>
            <MoneyMapGlobe data={data} layers={layers} selected={selected} onSelect={select} onPosting={onPosting} height={height} />
          </Suspense>}
      <div className="mmap-how"><b>How to read:</b> a dot is a city (size = money moved there in the window); an arc is money
        moving between cities (thicker = more value; <span className="bad">red</span> = an account involved is flagged, held, confirmed
        fraud or in a detected ring, <span className="warn">amber</span> = early warning). A moving spark is a real posting arriving now.
        Squares are ATM terminals; a red circle groups ≥ 3 risky withdrawals close in time and place (cash-out cluster); a
        diamond is a collection point (many distinct senders). Click a city or cluster to filter the tape; zoom in to see
        individual ATMs and the accuracy circle of the selected posting.</div>
    </section>
  );
}
