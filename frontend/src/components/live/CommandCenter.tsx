// SIMULATION COMMAND CENTER — every scenario from /api/scenarios grouped attack / payment / control; START / PAUSE /
// RESUME / RESET; description; step progress (scenario.* events); run chips from AttackRun (attack.run_updated).
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { AttackRun, ScenarioStatus } from "../../api/types";
import { msLabel } from "../../lib/live";
import { Panel, Sim } from "../ui";

const GROUPS: [string, string][] = [["attack", "Attack patterns · mule networks"], ["payment", "Payments · PRIMA pre-commit"], ["control", "Controls"]];

export function catOf(s: ScenarioStatus): "attack" | "payment" | "control" {
  if (s.category) return s.category;
  return s.id.startsWith("atk_") ? "attack" : "payment";
}

export function RunChips({ run }: { run: AttackRun }) {
  return (
    <div className="run-chips">
      {run.first_warning_ms != null && <span className="run-chip warn">warning +{msLabel(run.first_warning_ms)}</span>}
      {run.detection_ms != null && <span className="run-chip det">detected +{msLabel(run.detection_ms)}</span>}
      <span className={`run-chip ${run.status === "completed" ? "ok" : ""}`}>{run.status}</span>
      {run.status === "completed" && <span className="run-chip">{run.detected.length}/{run.injected.length} mules detected</span>}
    </div>
  );
}

export function CommandCenter({ scenarios, runs, runsUnavailable, selected, onSelect, onChanged, compact }: {
  scenarios: ScenarioStatus[] | null; runs: AttackRun[] | null; runsUnavailable: boolean;
  selected: string | null; onSelect: (id: string) => void; onChanged: () => void; compact?: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const list = scenarios ?? [];
  const s = list.find((x) => x.id === selected) ?? null;
  const running = list.filter((x) => x.state === "running").length;
  const run = s ? (runs ?? []).find((r) => r.scenario_id === s.id) ?? null : null;
  const pct = s && s.total_steps ? Math.round((s.step / s.total_steps) * 100) : 0;
  const cat = s ? catOf(s) : "attack";

  const act = async (what: "start" | "pause" | "resume" | "reset") => {
    if (!s) return;
    setBusy(what); setErr(null);
    try {
      if (what === "start") await api.scenarioStart(s.id);
      else if (what === "pause") await api.scenarioPause(s.id);
      else if (what === "resume") await api.scenarioResume(s.id);
      else await api.scenarioReset(s.id);
      onChanged();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  return (
    <Panel kicker="Attack controls" title="Simulation Command Center"
           actions={<span className={`chip ${running ? "danger" : "mute"}`}>Running: {running}</span>}
           footer={<span>Every injected step is a real ledger posting scored live. <Sim text="SIMULATED INPUTS" /> Scenario tags are simulator ground truth — used for evaluation only, never scored. <Link to="/lab">Scenario Lab →</Link></span>}>
      <div className="stack" style={{ gap: 12 }}>
        {GROUPS.map(([g, label]) => {
          const items = list.filter((x) => catOf(x) === g);
          if (!items.length) return null;
          return (
            <div key={g}>
              <div className="cmd-group">{label}</div>
              <div className="scn-grid">
                {items.map((x) => (
                  <button key={x.id} className={`scn-btn ${x.id === selected ? "on" : ""} ${x.state === "running" ? "running" : ""}`} onClick={() => onSelect(x.id)}>
                    <span className="ell" style={{ fontWeight: 600 }}>{x.name}</span>
                    <span className="st">{x.state === "idle" ? x.id : `${x.state} · ${x.step}/${x.total_steps}`}</span>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
        {!scenarios && <div className="xs muted">Loading scenarios…</div>}
        {s && (
          <div className="run-card">
            <div className="spread">
              <b>{s.name}</b>
              <span className="mono xs muted">{s.id} · {s.act}</span>
            </div>
            <div className="sm ink2" style={{ lineHeight: 1.55 }}>{s.summary}</div>
            {!compact && s.expected && <div className="xs muted"><b className="ink2">Expected:</b> {s.expected}</div>}
            <div className="row wrap">
              {s.state === "idle" || s.state === "done"
                ? <button className="btn primary grow" disabled={!!busy} onClick={async () => { if (s.state === "done") await act("reset"); await act("start"); }}>
                    {busy === "start" ? "Starting…" : cat === "attack" ? "Spawn attack" : "Start scenario"}</button>
                : s.state === "running"
                  ? <button className="btn grow" disabled={!!busy} onClick={() => act("pause")}>❚❚ Pause</button>
                  : <button className="btn primary grow" disabled={!!busy} onClick={() => act("resume")}>▶ Resume</button>}
              <button className="btn ghost" disabled={!!busy || s.state === "idle"} onClick={() => act("reset")}>Reset</button>
            </div>
            <div className="spread xs"><span className="muted">{s.state}{s.log.length ? ` · ${s.log[s.log.length - 1].title}` : ""}</span><span className="mono">{s.step}/{s.total_steps} steps</span></div>
            <div className={`progress ${cat === "attack" ? "" : cat === "control" ? "ok" : "pay"}`}><i style={{ width: `${pct}%` }} /></div>
            {run && <RunChips run={run} />}
            {run && run.status === "completed" && (
              <div className="notice sm">{run.run_id} completed. Detected {run.detected.length} of {run.injected.length} injected mules
                {run.false_positives.length ? ` · ${run.false_positives.length} false positive${run.false_positives.length > 1 ? "s" : ""}` : ""} (evaluated against simulator ground truth).</div>
            )}
            {cat === "attack" && !run && runsUnavailable && <div className="xs muted">Run evaluation (<span className="mono">/api/attacks/runs</span>) is not served yet — progress comes from scenario events only.</div>}
            {err && <div className="notice err sm">{err}</div>}
          </div>
        )}
      </div>
    </Panel>
  );
}
