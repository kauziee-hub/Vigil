// SIGNAL MAP (v12.4) — what works inside each detector family. The Detection page stays as it is; this page is where the
// whole inside is visible: the eight canonical families (unchanged), every signal inside them, and the supporting signals
// outside them (payment-time evidence, location intelligence) with where each one feeds.
// Built to stay readable: it opens on "Firing now" (quiet signals hidden), one family is open at a time, and "Focus an
// account" lights up exactly which checks fire for that account and why. Metrics are shown only where a family was
// benchmarked on held-out synthetic worlds; sub-signals never get a made-up ROC-AUC.
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchSignalMap, VALIDATION_LABEL, type SignalGroup, type SignalMap, type SignalRow } from "../api/signals";
import { useConsoleEvents } from "../components/Shell";
import { Bar, Metric, PageHead, Panel, Seg } from "../components/ui";
import { useThrottled } from "../lib/live";

const DIM_LABEL: Record<string, string> = {
  external: "External intelligence", sequence: "TrailScore (journey)", behaviour: "Behaviour", context: "ContextFlag (simulated context)",
};
const STATUS_WORD: Record<string, string> = {
  flagged: "Flagged", early_warning: "Early warning", held: "Held", confirmed_fraud: "Confirmed fraud", new: "New", normal: "Normal", idle: "Idle",
};

export function useSignalMap(account: string | null) {
  const [data, setData] = useState<SignalMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fetchSignalMap(account).then((d) => { setData(d); setError(null); }).catch((e) => setError(String(e)));
  }, [account]);
  useEffect(() => { load(); }, [load]);
  const refresh = useThrottled(load, 4000);
  useConsoleEvents((e) => {
    if (["intel.account_status", "ledger.posted", "decision.created", "demo.reset", "attack.run_updated", "geo.location_intel",
         "taint.updated"].includes(e.type)) refresh();
  });
  return { data, error, reload: load };
}

function ValBadge({ g }: { g: SignalGroup }) {
  return <span className={`sm-val v-${g.validation.kind}`} title={g.validation.text}>{VALIDATION_LABEL[g.validation.kind]}</span>;
}

function Card({ g, on, onPick, focused }: { g: SignalGroup; on: boolean; onPick: () => void; focused: boolean }) {
  const quiet = g.firing_signals === 0 && !(focused && g.signals.some((s) => s.hit));
  const famLine = focused
    ? (g.account_flagged === true ? <><b className="bad">flags this account</b>{g.account_value ? ` · ${g.account_value}` : ""}</>
      : g.account_flagged === false ? <>does not flag it{g.account_value ? ` · ${g.account_value}` : ""}</>
      : <>{g.signals.filter((s) => s.hit).length} signal(s) fire for it</>)
    : g.flagged_now != null ? <>flags <b>{g.flagged_now}</b> account{g.flagged_now === 1 ? "" : "s"} now</> : <>{g.window ?? g.feeds[0]}</>;
  return (
    <button className={`sm-card ${on ? "on" : ""} ${quiet ? "quiet" : ""}`} onClick={onPick} aria-pressed={on}>
      <div className="sm-card-h"><b>{g.label}</b><ValBadge g={g} /></div>
      <div className="sm-card-n"><b>{g.firing_signals}</b> of {g.signal_count} signal{g.signal_count === 1 ? "" : "s"} firing</div>
      <div className="sm-card-m">{famLine}</div>
      <div className="sm-dots" aria-hidden="true">
        {g.signals.map((s) => <i key={s.id} className={focused && s.hit ? "hit" : s.firing > 0 ? "on" : ""} title={`${s.label}: ${s.firing}`} />)}
      </div>
    </button>
  );
}

function SignalTable({ g, focused, onlyFiring, showAll }: { g: SignalGroup; focused: boolean; onlyFiring: boolean; showAll: () => void }) {
  const rows = useMemo(() => {
    const all = [...g.signals];
    if (focused) all.sort((a, b) => Number(!!b.hit) - Number(!!a.hit) || b.firing - a.firing);
    else if (onlyFiring) all.sort((a, b) => b.firing - a.firing);
    return all;
  }, [g, focused, onlyFiring]);
  const visible = onlyFiring ? rows.filter((s) => s.firing > 0 || (focused && s.hit)) : rows;
  const hidden = rows.length - visible.length;
  const max = Math.max(1, ...g.signals.map((s) => s.firing));
  let lastGroup: string | undefined;
  const line = (s: SignalRow) => (
    <tr key={s.id} className={focused && s.hit ? "hit" : s.firing ? "" : "quiet"}>
      <td><b>{s.label}</b><div className="mono xs muted">{s.id}</div></td>
      <td className="xs">{s.checks}{s.live_route != null ? <div className="muted">{s.live_route} at the live model-route threshold</div> : null}</td>
      <td style={{ width: 170 }}><span className="row tight"><span className="grow"><Bar value={s.firing} max={max} status={s.firing ? "watch" : undefined} /></span><span className="mono xs">{s.firing}</span></span></td>
      {focused && <td className="xs">{s.hit ? <span className="sm-hit">✓</span> : <span className="muted">—</span>} {s.hit && s.why ? s.why : ""}</td>}
      {g.id === "location" && <td className="xs muted">{s.feeds}</td>}
    </tr>
  );
  return (
    <>
      {visible.length === 0 ? <div className="empty">No signal in this group is firing right now. <button className="link" onClick={showAll}>Show all {rows.length}</button></div> : (
        <table className="dt sm-table">
          <thead><tr><th>Signal</th><th>What it checks</th><th>Accounts now</th>{focused && <th>For this account</th>}{g.id === "location" && <th>Feeds</th>}</tr></thead>
          <tbody>
            {visible.map((s) => {
              const head = g.id === "payment" && s.group !== lastGroup;
              lastGroup = s.group;
              return head
                ? [<tr key={`g-${s.group}`} className="sm-grp"><td colSpan={focused ? 4 : 3}>{DIM_LABEL[s.group ?? ""] ?? s.group}</td></tr>, line(s)]
                : line(s);
            })}
          </tbody>
        </table>
      )}
      {hidden > 0 && visible.length > 0 && <div className="sm-more">{hidden} quiet signal{hidden === 1 ? "" : "s"} hidden · <button className="link" onClick={showAll}>show all {rows.length}</button></div>}
    </>
  );
}

function Detail({ g, focused, onlyFiring, showAll }: { g: SignalGroup; focused: boolean; onlyFiring: boolean; showAll: () => void }) {
  return (
    <Panel title={g.label} q={g.validation.headline ? `SYNTHETIC VALIDATION · ${g.validation.headline}` : VALIDATION_LABEL[g.validation.kind]}
           actions={g.validation.kind === "benchmarked" ? <Link className="btn xs" to="/detection#det-models">Validation record</Link> : undefined}>
      <div className="sm-facts">
        <div><span>What it does</span><p>{g.purpose}</p></div>
        <div><span>Its weight in a decision</span><p>{g.role}</p></div>
        <div><span>How it is validated</span><p><span className={`sm-val v-${g.validation.kind}`}>{VALIDATION_LABEL[g.validation.kind]}</span> {g.validation.text}</p></div>
        <div><span>Feeds</span><p className="row wrap tight">{g.feeds.map((f) => <span key={f} className="tag">{f}</span>)}</p></div>
      </div>
      {(g.inputs || g.note || g.window || g.changed_status_now != null) && (
        <div className="sm-note">
          {g.inputs && <div><b>One learned score, not separate signals.</b> Inputs: {g.inputs}.</div>}
          {g.note && <div>{g.note}</div>}
          {g.window && <div>Counted over {g.window}.</div>}
          {g.changed_status_now != null && <div>Live statuses changed by location right now: <b>{g.changed_status_now}</b>. Location only ever stands in for a missing second voice, so this is usually 0.</div>}
          {focused && g.account_decision && <div>This account's latest payment decision: <Link to={`/investigations/decision/${g.account_decision.decision_id}`}>Tier {g.account_decision.tier} · score {g.account_decision.score.toFixed(2)}</Link> (as {g.account_decision.as}).</div>}
        </div>
      )}
      <SignalTable g={g} focused={focused} onlyFiring={onlyFiring} showAll={showAll} />
    </Panel>
  );
}

export function SignalMapPage() {
  const [params, setParams] = useSearchParams();
  const account = params.get("account");
  const view = (params.get("view") as "firing" | "all" | null) ?? "firing";
  const { data, error } = useSignalMap(account);
  const [q, setQ] = useState(account ?? "");
  useEffect(() => { setQ(account ?? ""); }, [account]);
  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };
  const groups = useMemo(() => [...(data?.families ?? []), ...(data?.supporting ?? [])], [data]);
  const fallback = useMemo(() => {
    const byFiring = [...(data?.families ?? [])].sort((a, b) => b.firing_signals - a.firing_signals);
    return byFiring[0]?.id ?? "ringwatch";
  }, [data]);
  const famId = params.get("family") ?? fallback;
  const sel = groups.find((g) => g.id === famId) ?? groups[0];
  const focused = !!data?.account && !!account;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const id = q.trim();
    set("account", id ? (id.includes("@") || id.startsWith("ext:") ? id : `${id}@vigil`) : null);
  };
  const t = data?.totals;

  return (
    <>
      <PageHead crumb={<><Link to="/detection">Detection &amp; models</Link> · Signal map</>} title="Signal map"
        lede="What works inside each detector family: every check, how many accounts trip it right now, where it feeds, and how the family is validated. The eight families stay the same; this page only opens them up."
        actions={<Link className="btn sm" to="/detection">← Detection</Link>} />

      <div className="mstrip kpi-row" style={{ marginBottom: 12 }}>
        <Metric k="Detector families" v={t?.families ?? "…"} d="the canonical eight" />
        <Metric k="Signals inside them" v={t?.family_signals ?? "…"} d="rules, checks, aspects, signatures" />
        <Metric k="Supporting signals" v={t?.supporting_signals ?? "…"} d="payment-time evidence · location" />
        <Metric k="Firing now" v={t?.firing_now ?? "…"} d="signals tripped by at least one account" status={t && t.firing_now ? "watch" : undefined} />
        <Metric k="Accounts with 2+ families" v={t?.accounts_two_plus_families ?? "…"} d={t ? `of ${t.accounts_scored} scored` : undefined} />
      </div>

      <div className="sm-controls">
        <Seg options={[["firing", "Firing now"], ["all", "All signals"]]} value={view} onChange={(v) => set("view", v === "firing" ? null : v)} />
        <form onSubmit={submit} className="sm-focus">
          <input className="input sm" placeholder="Focus an account (e.g. kiran.traders)" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Focus an account" />
          <button className="btn sm" type="submit">Focus</button>
          {account && <button className="btn sm" type="button" onClick={() => set("account", null)}>Clear</button>}
        </form>
        {!account && (data?.top_accounts ?? []).length > 0 && (
          <div className="sm-picks"><span className="muted xs">Most families agreeing:</span>
            {data!.top_accounts.slice(0, 5).map((a) => <button key={a.id} className="chipbtn" onClick={() => set("account", a.id)}>{a.name} · {a.families}</button>)}
          </div>
        )}
      </div>

      {focused && data?.account && (
        <div className={`sm-acct s-${data.account.status ?? "normal"}`}>
          <b>{data.account.name}</b>
          <span className="sm-st">{STATUS_WORD[data.account.status ?? ""] ?? data.account.status ?? "—"}</span>
          <span>{data.account.families_flagging ?? 0} of 8 families flag it</span>
          {data.account.location && <span className="tag">location: {data.account.location.rules.join(", ")}{data.account.location.changed_status ? " (changed its status)" : ""}</span>}
          <span className="sm-acct-r">{data.account.reason}</span>
          <Link className="btn xs" to={`/investigations/account/${encodeURIComponent(data.account.id)}`}>Account page</Link>
        </div>
      )}

      {error && !data && <div className="empty">Signal map unavailable ({error}).</div>}

      <div className="sm-group-t"><b>The eight detector families</b><span>Each one alone never makes an account "flagged"; a status needs independent families to agree.</span></div>
      <div className="sm-cards">
        {(data?.families ?? []).map((g) => <Card key={g.id} g={g} on={sel?.id === g.id} focused={focused} onPick={() => set("family", g.id)} />)}
      </div>
      <div className="sm-group-t"><b>Outside the eight families</b><span>Supporting signals: they set the payment tier or corroborate a status, and are never counted as a family.</span></div>
      <div className="sm-cards two">
        {(data?.supporting ?? []).map((g) => <Card key={g.id} g={g} on={sel?.id === g.id} focused={focused} onPick={() => set("family", g.id)} />)}
      </div>

      {sel && <div style={{ marginTop: 14 }}><Detail g={sel} focused={focused} onlyFiring={view === "firing"} showAll={() => set("view", "all")} /></div>}

      {data && (
        <div className="sm-legend">
          <b>How each family is validated</b>
          {data.validation_legend.map((v) => <div key={v.kind}><span className={`sm-val v-${v.kind}`}>{v.label}</span> {v.text}</div>)}
          <div className="muted">Why some families have no accuracy numbers on the Detection page: RingWatch and the registry exist only in the live world,
            so there is nothing to measure them against on the test worlds; they are checked by every graded attack run instead. Individual signals
            (one rule, one drift aspect, one location check) are never given metrics of their own.</div>
        </div>
      )}
    </>
  );
}
