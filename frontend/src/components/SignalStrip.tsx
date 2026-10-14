// The Detection page's one-line view of everything working underneath it: the eight families and the two supporting
// layers, each as "signals firing / signals inside", linking into the Signal map. Nothing else on the page changes.
import { Link } from "react-router-dom";
import type { SignalMap } from "../api/signals";

const SHORT: Record<string, string> = {
  ringwatch: "RingWatch", random_forest: "Random Forest", gnn: "GNN", rules: "Rules", drift: "Drift", early_warning: "Early warning",
  pattern_memory: "Pattern memory", external: "Registry", payment: "Payment-time", location: "Location",
};

export function SignalStrip({ data }: { data: SignalMap | null }) {
  if (!data) return null;
  const t = data.totals;
  const chip = (id: string, firing: number, total: number, sup = false) => (
    <Link key={id} className={`sig-chip ${firing ? "firing" : ""} ${sup ? "sup" : ""}`} to={`/detection/signals?family=${id}`}
          title={`${firing} of ${total} signals inside ${SHORT[id] ?? id} are firing now`}>
      {SHORT[id] ?? id} <b>{firing}/{total}</b>
    </Link>
  );
  return (
    <div className="sig-strip">
      <span className="sig-t">{t.families} detector families · {t.family_signals} signals inside them · {t.supporting_signals} supporting · <b>{t.firing_now} firing now</b></span>
      {data.families.map((f) => chip(f.id, f.firing_signals, f.signal_count))}
      {data.supporting.map((s) => chip(s.id, s.firing_signals, s.signal_count, true))}
      <span className="grow" />
      <Link className="btn xs" to="/detection/signals">Open the signal map</Link>
    </div>
  );
}

/** Small "all signals" link for a Detection panel header. */
export function SigLink({ family, label = "all signals" }: { family?: string; label?: string }) {
  return <Link className="sig-link" to={family ? `/detection/signals?family=${family}&view=all` : "/detection/signals"}>{label} →</Link>;
}
