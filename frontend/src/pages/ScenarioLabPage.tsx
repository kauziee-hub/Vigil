// SCENARIO LAB — reproducible demonstrations. Every scenario from /api/scenarios (payment · attack · control) with
// START / PAUSE / RESUME / RESET / REPLAY / COMPARE DETECTORS, a live step log fed by the realtime bus, the
// decisions it produced, and the scenario-scoped attack scene in Network Intelligence.
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { AttackRun, DetectorFamily, ScenarioCompare, ScenarioEvent, ScenarioExplain, ScenarioReplay, ScenarioStatus } from "../api/types";
import { ConsensusStrip, DetectorTable, detectorStatus } from "../components/intel";
import { AttackHistory, LastAttackResult } from "../components/live/AttackResults";
import { RunChips } from "../components/live/CommandCenter";
import { Synthetic } from "../components/ModelCard";
import { usePlatform, useConsoleEvents } from "../components/Shell";
import { Async, Glyph, PageHead, Panel, Pill, Sim, Tabs, TierPill } from "../components/ui";
import { formatINR, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";
import { useAttackRuns, type LiveSource } from "../lib/live";
import { FAMILY, KIND_LABEL, type Status } from "../lib/status";

type Cat = "payment" | "attack" | "control";
const CAT_LABEL: Record<Cat, string> = { payment: "Payment journeys", attack: "Attack patterns (network)", control: "Controls" };
const STATE_ST: Record<ScenarioStatus["state"], Status> = { idle: "unknown", running: "watch", paused: "watch", done: "normal" };
type Tab = "log" | "replay" | "compare";

const catOf = (s: ScenarioStatus): Cat => (s.category ?? (s.id.startsWith("atk_") ? "attack" : s.act === "Control" ? "control" : "payment"));

export function ScenarioLabPage() {
  const { health } = usePlatform();
  const [params, setParams] = useSearchParams();
  const list = useLoad<ScenarioStatus[]>(api.scenarios);
  const selId = params.get("s") || list.data?.[0]?.id || "";
  const tab = (params.get("tab") as Tab) || "log";
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [live, setLive] = useState<Record<string, ScenarioEvent>>({});
  const reloadList = useDebounced(() => list.reload(), 350);
  const runs = useAttackRuns();

  useConsoleEvents((e) => {
    if (e.type.startsWith("scenario.")) {
      const ev = e.data as ScenarioEvent;
      if (ev && ev.scenario_id) setLive((m) => ({ ...m, [ev.scenario_id]: ev }));
      reloadList();
    } else if (e.type === "demo.reset") { setLive({}); list.reload(); }
  });

  const setParam = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)));
    setParams(next, { replace: true });
  };

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setErr(null);
    try { await fn(); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); list.reload(); }
  };

  const groups = useMemo(() => {
    const g: Record<Cat, ScenarioStatus[]> = { payment: [], attack: [], control: [] };
    (list.data ?? []).forEach((s) => g[catOf(s)].push(s));
    return g;
  }, [list.data]);
  const sel = (list.data ?? []).find((s) => s.id === selId) ?? null;

  return (
    <>
      <PageHead crumb="Control" title="Scenario lab"
        lede="Deterministic demonstrations: the same inputs produce the same decisions after every reset. Attack patterns are injected as observed ledger postings; payment journeys run through the full pre-commit path."
        actions={<>
          <button className="btn sm" disabled={!health || busy === "ambient"} onClick={() => act("ambient", () => api.ambient(!health?.ambient))}
                  title="Background (ambient) payments keep the ledger and graph moving; turn off for a quiet demo">
            <span className={`dot ${health?.ambient ? "ok" : ""}`} /> Background stream {health ? (health.ambient ? "on" : "off") : "…"}
          </button>
          <button className="btn sm danger" disabled={busy === "reset"}
                  onClick={() => window.confirm("Reset the whole demo to its seeded starting state? Every scenario, decision, hold and trace since the seed is discarded.") && act("reset", api.reset)}>
            {busy === "reset" ? "Resetting…" : "Reset demo"}
          </button>
        </>} />
      {err && <div className="notice err" style={{ marginBottom: 10 }}>{err}</div>}

      <div className="grid cols-lab align-start">
        <Panel kicker="Scenarios" title={list.data ? `${list.data.length} available` : "…"} flush>
          <Async load={list} what="Scenarios" endpoint="/api/scenarios">
            {() => (
              <div>
                {(Object.keys(groups) as Cat[]).filter((c) => groups[c].length).map((c) => (
                  <div key={c}>
                    <div className="sect-t" style={{ padding: "8px 12px 4px", margin: 0 }}>{CAT_LABEL[c]} · {groups[c].length}</div>
                    {groups[c].map((s) => {
                      const ev = live[s.id];
                      const step = ev && ev.run_id ? Math.max(ev.step, s.step) : s.step;
                      return (
                        <button key={s.id} className={`scn-row ${s.id === selId ? "on" : ""}`} onClick={() => setParam({ s: s.id })}>
                          <span className="grow">
                            <span className="row tight"><b className="ell">{s.name}</b><span className="mono xs dim">{s.id}</span></span>
                            <span className="xs muted ell" style={{ display: "block" }}>{s.act} · {s.summary}</span>
                          </span>
                          <span className="stack tight" style={{ alignItems: "flex-end" }}>
                            <Pill status={STATE_ST[s.state]}>{s.state}</Pill>
                            <span className="mono xs dim">{step}/{s.total_steps}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </Async>
        </Panel>

        {sel ? <ScenarioDetail key={sel.id} s={sel} tab={tab} setTab={(t) => setParam({ tab: t === "log" ? null : t })}
                               busy={busy} act={act} runs={runs} /> : <Panel title="Select a scenario"><div className="empty">Pick a scenario on the left.</div></Panel>}
      </div>
    </>
  );
}

function ScenarioDetail({ s, tab, setTab, busy, act, runs }: {
  s: ScenarioStatus; tab: Tab; setTab: (t: Tab) => void; busy: string | null; act: (k: string, fn: () => Promise<unknown>) => Promise<void>;
  runs: LiveSource<AttackRun[]>;
}) {
  const cat = catOf(s);
  // run_id in the deps: re-running a 1-step scenario goes done 1/1 -> done 1/1, which alone would not refetch
  const runId = s.log.length ? s.log[s.log.length - 1].run_id : null;
  const explain = useLoad<ScenarioExplain>(() => api.scenarioExplain(s.id), [s.id, s.state === "done", s.step, runId]);
  const pct = s.total_steps ? (s.step / s.total_steps) * 100 : 0;
  const network = cat === "attack";
  const myRuns = (runs.data ?? []).filter((r) => r.scenario_id === s.id);
  const run = myRuns[0] ?? null;
  return (
    <div className="stack">
      <Panel kicker={s.act.toLowerCase() === cat ? `${CAT_LABEL[cat]} · ${s.id}` : `${s.act} · ${CAT_LABEL[cat]} · ${s.id}`} title={s.name}
             actions={<><Pill status={STATE_ST[s.state]}>{s.state}</Pill><span className="mono xs muted">step {s.step}/{s.total_steps}</span></>}
             footer={<span>Expected: {s.expected}</span>}>
        <div className="stack">
          <div className="md ink2">{s.summary}</div>
          <div className={`progress ${cat === "attack" ? "" : cat === "control" ? "ok" : "pay"}`}><i style={{ width: `${pct}%` }} /></div>
          {network && run && <RunChips run={run} />}
          <div className="row wrap">
            {(s.state === "idle" || s.state === "done") && (
              <button className="btn sm primary" disabled={!!busy} onClick={() => act(s.id, () => api.scenarioStart(s.id))}>▶ Start</button>
            )}
            {s.state === "running" && <button className="btn sm" disabled={!!busy} onClick={() => act(s.id, () => api.scenarioPause(s.id))}>❚❚ Pause</button>}
            {s.state === "paused" && <button className="btn sm primary" disabled={!!busy} onClick={() => act(s.id, () => api.scenarioResume(s.id))}>▶ Resume</button>}
            <button className="btn sm" disabled={!!busy}
                    onClick={() => window.confirm("Reset restores the whole demo to its seeded state (all scenarios). Continue?") && act(`r${s.id}`, () => api.scenarioReset(s.id))}>↺ Reset</button>
            <button className={`btn sm ${tab === "replay" ? "on" : ""}`} onClick={() => setTab("replay")}>⟲ Replay</button>
            <button className={`btn sm ${tab === "compare" ? "on" : ""}`} onClick={() => setTab("compare")}>Compare detectors</button>
            <span className="grow" />
            {network && <Link className="btn sm" to={`/network?scenario=${encodeURIComponent(s.id)}&replay=1`}>Attack scene in 3D ↗</Link>}
            {s.payer && <Link className="btn sm ghost" to={`/guard?as=${encodeURIComponent(s.payer)}`}>Payer device · {handle(s.payer)} ↗</Link>}
            {s.id === "s3" && <a className="btn sm ghost" href="/contact/arjun" target="_blank" rel="noreferrer">Trusted contact phone ↗</a>}
          </div>
          {explain.data && (
            <div className="row wrap tight">
              {explain.data.time_compressed && <Sim text="TIME-COMPRESSED" />}
              {explain.data.simulated_inputs && <Sim text="SIMULATED INPUTS" />}
              {network && <span className="xs muted">Injected as observed ledger postings, tagged with the scenario id for evaluation only.</span>}
            </div>
          )}
        </div>
      </Panel>

      <div className="grid cols-2 align-start">
          <Panel kicker="Explain" title="What this demonstrates">
            <Async load={explain} what="Scenario explanation" endpoint="/api/scenarios/{id}/explain">
              {(x) => <ul className="md ink2" style={{ display: "flex", flexDirection: "column", gap: 4 }}>{x.explain.map((t) => <li key={t}>{t}</li>)}</ul>}
            </Async>
          </Panel>
          {network ? <LastAttackResult runs={myRuns} unavailable={runs.unavailable} emptyText="This pattern has not run since the last reset. Press Start — the run is evaluated against the simulator's injected mule list when it completes." /> : (
          <Panel kicker="Outcome" title="Decisions produced" flush>
            {explain.data && explain.data.decisions.length === 0 && <div className="empty">{network ? "Attack patterns post ledger transfers; they create no payment decision. See the 3D scene and COMPARE DETECTORS." : "No decision yet — start the scenario."}</div>}
            {explain.data && explain.data.decisions.length > 0 && (
              <table className="dt compact">
                <thead><tr><th>Decision</th><th>Tier</th><th>State</th><th className="num">Score</th></tr></thead>
                <tbody>{explain.data.decisions.map((d) => (
                  <tr key={d.decision_id}>
                    <td className="mono xs"><Link to={`/investigations/decision/${d.decision_id}`}>{d.decision_id}</Link></td>
                    <td><TierPill tier={d.tier} /></td><td className="xs">{d.state.replace(/_/g, " ").toLowerCase()}</td>
                    <td className="num">{d.final_score.toFixed(3)}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </Panel>
          )}
      </div>
      {network && myRuns.length > 0 && <AttackHistory runs={myRuns} unavailable={runs.unavailable} />}
      <section className="panel">
        <div style={{ padding: "12px 12px 0" }}>
          <Tabs tabs={[["log", `Live step log · ${s.log.length}`], ["replay", "Replay"], ["compare", "Compare detectors"]]} value={tab} onChange={setTab} />
        </div>
        {tab === "log" && <StepLog s={s} />}
        {tab === "replay" && <ReplayView s={s} network={network} />}
        {tab === "compare" && <CompareView id={s.id} />}
      </section>
    </div>
  );
}

function StepLog({ s }: { s: ScenarioStatus }) {
  if (!s.log.length) return <div className="empty">No steps yet. Press START — each step appears here the moment the server publishes it.</div>;
  return (
    <div className="panel-b">
      <div className="tl">
        {s.log.map((l) => {
          const r = (l.result ?? null) as { decision_id?: string; tier?: number; state?: string } | null;
          return (
            <div key={`${l.run_id}-${l.step}`} className={`tl-i ${r?.tier !== undefined ? (r.tier >= 4 ? "crit" : r.tier >= 2 ? "hot" : "ok") : ""}`}>
              <div className="t">{formatTime(l.ts)} · step {l.step}/{l.total_steps} · {l.kind}</div>
              <div className="row wrap tight"><span>{l.title}</span>
                {r?.decision_id && <><TierPill tier={r.tier} /><Link className="xs" to={`/investigations/decision/${r.decision_id}`}>{r.decision_id} →</Link></>}
              </div>
              {l.detail && <div className="xs muted">{l.detail}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ReplayView({ s, network }: { s: ScenarioStatus; network: boolean }) {
  const rep = useLoad<ScenarioReplay>(() => api.scenarioReplay(s.id), [s.id, s.state === "done"]);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const n = rep.data?.events.length ?? 0;
  useEffect(() => { setI(0); setPlaying(false); }, [rep.data]);
  useEffect(() => {
    if (!playing) return;
    if (i >= n - 1) { setPlaying(false); return; }
    const t = window.setTimeout(() => setI((x) => Math.min(n - 1, x + 1)), 700);
    return () => window.clearTimeout(t);
  }, [playing, i, n]);
  return (
    <Async load={rep} what="Scenario replay" endpoint="/api/scenarios/{id}/replay">
      {(r) => r.events.length === 0 ? (
        <div className="empty">Nothing to replay: this scenario has not run since the last reset. Start it, then replay its recorded events.</div>
      ) : (
        <>
          <div className="replay-ctl">
            <button className="btn sm primary" onClick={() => { if (i >= n - 1) setI(0); setPlaying(!playing); }}>{playing ? "❚❚ Pause" : i >= n - 1 ? "↺ Replay" : "▶ Play"}</button>
            <input type="range" min={0} max={n - 1} value={i} onChange={(e) => { setPlaying(false); setI(Number(e.target.value)); }} aria-label="Replay position" />
            <span className="mono xs muted">{i + 1}/{n} · {formatTime(r.events[i].ts)}</span>
            {network && <Link className="btn sm" to={`/network?scenario=${encodeURIComponent(s.id)}&replay=1`}>Replay in 3D ↗</Link>}
          </div>
          <div className="tscroll" style={{ maxHeight: 420 }}>
            <table className="dt compact">
              <thead><tr><th>#</th><th>Time</th><th>Kind</th><th>Event</th><th>Flow</th><th className="num">Amount</th></tr></thead>
              <tbody>{r.events.map((ev, k) => (
                <tr key={k} className={k === i ? "sel" : ""} style={{ opacity: k > i ? 0.4 : 1, cursor: "pointer" }} onClick={() => { setPlaying(false); setI(k); }}>
                  <td className="mono xs">{k + 1}</td><td className="mono xs">{formatTime(ev.ts)}</td><td className="xs">{ev.kind}</td>
                  <td className="xs">{ev.title}{ev.tx_id && <span className="mono dim"> · {ev.tx_id}</span>}</td>
                  <td className="xs">{ev.source && ev.target ? `${handle(ev.source)} → ${handle(ev.target)}` : "—"}</td>
                  <td className="num">{ev.amount_paise ? formatINR(ev.amount_paise) : "—"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}
    </Async>
  );
}

const AGREE_ST: Record<string, Status> = { strong: "critical", moderate: "high", weak: "watch", none: "normal" };

/** COMPARE DETECTORS: every account the scenario touched × every detector family, one dense matrix. */
function CompareView({ id }: { id: string }) {
  const cmp = useLoad<ScenarioCompare>(() => api.intelCompare(id), [id]);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="panel-b">
      <Async load={cmp} what="Detector comparison" endpoint="/api/intel/scenarios/{id}/compare">
        {(c) => {
          if (c.accounts.length === 0) return <div className="empty">No accounts touched by this scenario yet. Start it first.</div>;
          const fams: DetectorFamily[] = [];
          c.accounts.forEach((a) => a.detectors.forEach((d) => { if (!fams.includes(d.family)) fams.push(d.family); }));
          const sel = c.accounts.find((a) => a.account_id === open) ?? null;
          return (
            <div className="stack">
              <div className="row wrap tight xs muted">
                <Synthetic />
                <span>Each account this scenario touched, every detector family side by side. Coloured = flagged by that family; grey = evaluated, not flagged. Scripted role is the scenario's ground truth, shown for evaluation only. Model families are corroborating evidence — they never set a tier.</span>
              </div>
              <div className="tscroll">
                <table className="dt compact matrix">
                  <thead>
                    <tr>
                      <th>Account</th><th>Scripted role</th>
                      {fams.map((f) => <th key={f} className="center" title={FAMILY[f]?.label}><Glyph family={f} /></th>)}
                      <th>Consensus</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.accounts.map((a) => (
                      <tr key={a.account_id} className={`click ${open === a.account_id ? "sel" : ""}`} onClick={() => setOpen(open === a.account_id ? null : a.account_id)}>
                        <td className="xs"><b>{handle(a.account_id)}</b></td>
                        <td className="xs muted nowrap" title={a.seed_role ?? undefined}>{a.seed_role ? a.seed_role.split(" · ")[0].replace(/_/g, " ") : "—"}</td>
                        {fams.map((f) => {
                          const d = a.detectors.find((x) => x.family === f);
                          if (!d) return <td key={f} className="center dim xs">—</td>;
                          const st = detectorStatus(d);
                          const short = d.display.split(" · ")[0];
                          return (
                            <td key={f} className="center" title={`${d.label}: ${d.display} (${KIND_LABEL[d.kind] ?? d.kind})`}>
                              {d.status !== "ok" ? <span className="xs dim">n/a</span>
                                : <span className={`cell ${d.flagged ? "on" : ""}`} style={d.flagged ? { color: `var(--st-${st})`, borderColor: `var(--st-${st})` } : undefined}>{short}</span>}
                            </td>
                          );
                        })}
                        <td className="xs nowrap"><Pill status={AGREE_ST[a.consensus.agreement] ?? "unknown"}>{a.consensus.families_flagging}/{a.consensus.families_evaluated} {a.consensus.agreement}</Pill></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {sel && (
                <div className="trace-col">
                  <div className="spread" style={{ marginBottom: 6 }}>
                    <Link className="b" to={`/investigations/account/${encodeURIComponent(sel.account_id)}`}>{handle(sel.account_id)} · open account investigation →</Link>
                    {sel.seed_role && <span className="tag">scripted role: {sel.seed_role}</span>}
                  </div>
                  <ConsensusStrip consensus={sel.consensus} detectors={sel.detectors} />
                  <div style={{ marginTop: 6 }}><DetectorTable detectors={sel.detectors} compact /></div>
                </div>
              )}
            </div>
          );
        }}
      </Async>
    </div>
  );
}
