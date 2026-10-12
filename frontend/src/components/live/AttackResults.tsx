// LAST ATTACK RESULT + ATTACK HISTORY — AttackRun records evaluated against SIMULATOR GROUND TRUTH
// (injected = the scenario's scripted mule accounts). Detected / missed / false positives / latency / precision / recall.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { AttackRun } from "../../api/types";
import { formatTime, handle } from "../../lib/format";
import { msLabel } from "../../lib/live";
import { Panel, Unavailable } from "../ui";

function Tokens({ ids, kind }: { ids: string[]; kind?: "danger" | "warn" | "ok" }) {
  if (!ids.length) return <div className="token-row"><span className="xs muted">none</span></div>;
  return (
    <div className="token-row">
      {ids.map((id) => <Link key={id} className={`token ${kind ?? ""}`} to={`/investigations/account/${encodeURIComponent(id)}`}>{handle(id)}</Link>)}
    </div>
  );
}

const fx = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : v.toFixed(d));

export function LastAttackResult({ runs, unavailable, emptyText, compact = false, footer }: {
  runs: AttackRun[] | null; unavailable: boolean; emptyText?: string; compact?: boolean; footer?: ReactNode;
}) {
  const r = (runs ?? []).find((x) => x.status === "completed") ?? (runs ?? [])[0] ?? null;
  const caught = r ? r.injected.filter((x) => r.detected.includes(x)) : [];
  const surfaced = r ? r.missed.filter((x) => r.warned.includes(x)) : [];
  return (
    <Panel kicker="Outcome" title="Last attack result" actions={<span className="sim gt">simulator ground truth</span>}>
      {unavailable ? <Unavailable what="Attack-run evaluation" endpoint="/api/attacks/runs" /> : !r ? (
        <div className="empty">{emptyText ?? "No pattern has been injected since the last reset."}</div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          <div className="ink2">{r.run_id} · {r.name} — {r.status === "completed" ? "evaluated against the simulator's injected mule list." : `${r.status} (${r.steps_done}/${r.steps_total} steps)…`}</div>
          <div className="mstrip dense">
            <div className="m"><div className="k">Mules injected</div><div className="v">{r.injected.length}</div></div>
            <div className="m st-critical"><div className="k">Detected</div><div className="v">{caught.length}</div></div>
            <div className="m st-watch"><div className="k">Missed</div><div className="v">{r.missed.length}</div></div>
            <div className="m"><div className="k">First warning</div><div className="v">{msLabel(r.first_warning_ms)}</div></div>
            <div className="m"><div className="k">Detection</div><div className="v">{msLabel(r.detection_ms)}</div></div>
            <div className="m"><div className="k">False positives</div><div className="v">{r.false_positives.length}</div></div>
          </div>
          {compact ? (
            <>
              <div className="sm ink2">
                {r.missed.length === 0 ? "Every injected mule account was flagged." :
                  `${r.missed.length} not flagged${surfaced.length ? ` — ${surfaced.length === r.missed.length ? "all" : surfaced.length} still surfaced at early warning` : ""}.`}
                {" "}{r.false_positives.length === 0 ? "No other account was flagged." : `${r.false_positives.length} other account(s) flagged.`}
              </div>
              {r.missed.length > 0 && <Tokens ids={r.missed} kind="warn" />}
            </>
          ) : <>
          <div><div className="sect-t">Detected mules · {caught.length}</div><Tokens ids={r.detected} kind="danger" /></div>
          <div><div className="sect-t">Missed mules · {r.missed.length}</div><Tokens ids={r.missed} kind="warn" /></div>
          <div><div className="sect-t">Warned (early warning or worse) · {r.warned.length}</div><Tokens ids={r.warned} kind="warn" /></div>
          <div><div className="sect-t">False positives during the run · {r.false_positives.length}</div><Tokens ids={r.false_positives} /></div>
          <div className="xs muted">Precision {fx(r.precision)} · recall {fx(r.recall)}{r.model_threshold != null ? ` · model-evidence threshold ${r.model_threshold.toFixed(3)}` : ""}. The threshold adapts only model evidence; PRIMA tiers are never touched.</div>
          </>}
        </div>
      )}
      {footer}
    </Panel>
  );
}

export function AttackHistory({ runs, unavailable, onPick }: { runs: AttackRun[] | null; unavailable: boolean; onPick?: (r: AttackRun) => void }) {
  const list = runs ?? [];
  return (
    <Panel id="attack-history" kicker="Audit trail" title="Attack history" flush
           actions={<span className="chip mute">{list.length} run{list.length === 1 ? "" : "s"} · /api/attacks/runs</span>}>
      {unavailable ? <div style={{ padding: "0 20px 12px" }}><Unavailable what="Attack history" endpoint="/api/attacks/runs" /></div> : (
        <div className="tscroll" style={{ maxHeight: 380 }}>
          <table className="dt">
            <thead><tr><th>Run</th><th>Pattern</th><th>Started</th><th className="num">Tx</th><th className="num">Mules detected</th><th className="num">First warning</th>
              <th className="num">Detection</th><th className="num">Precision</th><th className="num">Recall</th><th className="num">Threshold</th><th>Status</th></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.run_id} className={onPick ? "click" : ""} onClick={() => onPick?.(r)}>
                  <td className="mono" style={{ color: "var(--accent)" }}>{r.run_id}</td>
                  <td>{r.name}</td>
                  <td className="mono xs">{formatTime(r.started_at)}</td>
                  <td className="num">{r.tx_count}</td>
                  <td className="num">{r.detected.length}/{r.injected.length}</td>
                  <td className="num">{msLabel(r.first_warning_ms)}</td>
                  <td className="num">{msLabel(r.detection_ms)}</td>
                  <td className="num">{fx(r.precision)}</td>
                  <td className="num">{fx(r.recall)}</td>
                  <td className="num">{r.model_threshold != null ? r.model_threshold.toFixed(3) : "—"}</td>
                  <td><span className={`pill ${r.status === "completed" ? "s-accent" : "s-critical"}`}>{r.status}</span></td>
                </tr>
              ))}
              {list.length === 0 && <tr><td colSpan={11} className="empty">No attack runs since the last reset.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
