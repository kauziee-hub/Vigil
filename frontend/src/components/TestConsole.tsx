// Test inputs — demo-only controls kept OUT of the product screens (PRIMA /ops style). Every action is a real
// backend call: payments go through the customer device and the full pre-commit path; injected patterns are real
// ledger postings scored live; reports create a real fraud label that TaintTrace follows.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { AttackRun, ScenarioStatus } from "../api/types";
import { formatINR, handle } from "../lib/format";
import { useConsoleEvents, usePlatform } from "./Shell";

const PAYERS = [
  { id: "ramesh@vigil", label: "Ramesh Kumar (salaried)" },
  { id: "sunita@vigil", label: "Sunita Rao (retired, 67)" },
];
const PAYEES = ["meena.grocer@vigil", "kiran.traders@vigil", "landlord.iyer@vigil", "medplus.pharma@vigil", "rk.legal.services@vigil"];
const COERCION = "Caller says he is from CBI, do not tell anyone, transfer immediately";
const POLICE = "Caller says he is from the police, keep this secret, pay now or you will be arrested";
// `expect` is what docs/DEMO_TEST_BOOK.md records for each input after a reset (scripts/test_book_check.py re-verifies it).
type Preset = { label: string; payer: string; to: string; amount: string; note: string; ctx?: string; expect: string };
const PRESETS: Preset[] = [
  { label: "Everyday · grocer ₹500", payer: "ramesh@vigil", to: "meena.grocer@vigil", amount: "500", note: "groceries",
    expect: "Tier 0 · approved instantly · score 0.00" },
  { label: "Risky recipient · ₹45,000", payer: "ramesh@vigil", to: "kiran.traders@vigil", amount: "45000", note: "advance for goods",
    expect: "Tier 2 · customer confirms the purpose · score 0.34 (Tier 3 hold once a scam into Kiran is confirmed, section 4)" },
  { label: "Large but legitimate · ₹1,20,000", payer: "ramesh@vigil", to: "landlord.iyer@vigil", amount: "120000", note: "deposit + October rent",
    expect: "Tier 0 · large amount noted, no friction · score 0.05" },
];
const MORE_PRESETS: Preset[] = [
  { label: "T0 · new payee ₹8,000", payer: "ramesh@vigil", to: "medplus.pharma@vigil", amount: "8000", note: "medicines",
    expect: "Tier 0 · first-time payee + unusual amount are noted, not enough to interrupt · score 0.07" },
  { label: "T1 · pressure words only", payer: "sunita@vigil", to: "rk.legal.services@vigil", amount: "50000", note: "fees", ctx: COERCION,
    expect: "Tier 1 · heads-up, customer may continue · score 0.20 (words alone never hold a payment)" },
  { label: "T3 · registry-confirmed mule", payer: "ramesh@vigil", to: "quickloan.agent@vigil", amount: "15000", note: "loan processing fee",
    expect: "Tier 3 · held · score 0.32 is Tier 2 on the ladder; the confirmed-mule floor lifts it to Tier 3" },
  { label: "T3 · risky + pressure words", payer: "ramesh@vigil", to: "kiran.traders@vigil", amount: "45000", note: "advance for goods", ctx: POLICE,
    expect: "Tier 3 · held · score 0.54 (two independent kinds of evidence agree: +0.10)" },
];
// Expected outcome of each injected pattern after a reset (detection run graded against simulator ground truth).
const PATTERN_EXPECT: Record<string, string> = {
  s2: "3 of 4 mules flagged, the 4th at early warning · Vigilance: Critical · Ring formed (Mumbai)",
  atk_fan_in: "Swift Collect flagged as a collector · Vigilance: High · Account flagged",
  atk_fan_out: "Bulk Payouts flagged as a distributor · Vigilance: High · Account flagged",
  atk_circular: "all 4 ring members flagged · Vigilance: Critical · Ring formed (Ahmedabad)",
  atk_velocity_chain: "3 of 5 flagged, first and last at early warning · Vigilance: Critical · Ring formed (Kolkata)",
  atk_cross_channel: "the hub flagged · Vigilance: High · Account flagged + Medium · Impossible travel (Delhi → Kolkata)",
  atk_shared_device: "all 5 flagged · Vigilance: Critical · Device farm + Critical · Ring formed (Mumbai)",
  atk_behavioural_drift: "the drifting account flagged · Vigilance: Medium · Account flagged",
  atk_volume_spike: "Fresh Wallet flagged · Vigilance: Medium · Account flagged",
  atk_smurfing: "the structuring account flagged as a distributor · Vigilance: High · Account flagged",
  atk_dormant: "Dormant Savings flagged as a collector · Vigilance: Medium · Account flagged",
};

function err(e: unknown) { return e instanceof ApiError ? e.message : String(e); }

export function TestConsole({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const { health, mode, refreshMode } = usePlatform();
  const [payer, setPayer] = useState("ramesh@vigil");
  const [to, setTo] = useState("meena.grocer@vigil");
  const [amount, setAmount] = useState("500");
  const [note, setNote] = useState("groceries");
  const [ctx, setCtx] = useState("");
  const [preset, setPreset] = useState<Preset | null>(null);
  const [scen, setScen] = useState<ScenarioStatus[]>([]);
  const [pattern, setPattern] = useState("s2");
  const [run, setRun] = useState<AttackRun | null>(null);
  const [txId, setTxId] = useState("");
  const [msg, setMsg] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const say = (k: string, v: string) => setMsg((m) => ({ ...m, [k]: v }));

  const loadScen = () => api.scenarios().then(setScen).catch(() => undefined);
  useEffect(() => { loadScen(); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useConsoleEvents((e) => {
    if (e.type.startsWith("scenario.") || e.type === "demo.reset") loadScen();
    if (e.type === "attack.run_updated") setRun(e.data as AttackRun);
  });

  const network = scen.filter((s) => s.category === "attack" || s.id === "s2");
  const running = scen.find((s) => s.state === "running" || s.state === "paused");

  const choose = (p: Preset) => { setPayer(p.payer); setTo(p.to); setAmount(p.amount); setNote(p.note); setCtx(p.ctx ?? ""); setPreset(p); };
  const edited = preset && (preset.payer !== payer || preset.to !== to || preset.amount !== amount || (preset.ctx ?? "") !== ctx);
  useEffect(() => { if (edited) setPreset(null); }, [edited]);

  const openOnDevice = () => {
    const q = new URLSearchParams({ as: payer, to, amount, note });
    if (ctx.trim()) q.set("context", ctx.trim());
    nav(`/guard?${q.toString()}`);
    onClose();
  };
  const submitDirect = async () => {
    const paise = Math.round(Number(amount) * 100);
    if (!to || !(paise > 0)) { say("pay", "Enter a recipient and an amount."); return; }
    setBusy("pay");
    try {
      const r = await api.createIntent({ sender_id: payer, recipient_id: to.trim(), amount_paise: paise, note: note || undefined,
                                         context_text: ctx.trim() || undefined });
      const d = r.decision;
      say("pay", d ? `${r.intent.intent_id} → Tier ${d.tier} · ${d.intervention.title} · score ${d.final_score.toFixed(2)}|${d.decision_id}` : `${r.intent.intent_id} created`);
    } catch (e) { say("pay", err(e)); } finally { setBusy(null); }
  };
  const inject = async () => {
    setBusy("inject"); setRun(null);
    try { await api.scenarioStart(pattern); say("inject", "Started — postings stream into the live network."); loadScen(); }
    catch (e) { say("inject", err(e)); } finally { setBusy(null); }
  };
  const coerced = async () => {
    setBusy("s3");
    try { await api.scenarioStart("s3"); say("s3", "Started — Sunita's payment is assessed; the trusted contact is alerted on Tier 4."); loadScen(); }
    catch (e) { say("s3", err(e)); } finally { setBusy(null); }
  };
  const findSource = async () => {
    setBusy("find");
    try {
      const txs = await api.accountTransactions("kiran.traders@vigil");
      const inbound = txs.filter((t) => t.recipient_id === "kiran.traders@vigil" && t.kind === "transfer" && t.sender_id !== "ramesh@vigil")
        .sort((a, b) => a.seq - b.seq);
      if (inbound[0]) { setTxId(inbound[0].id); say("label", `Found ${inbound[0].id}: ${handle(inbound[0].sender_id)} → Kiran Traders ${formatINR(inbound[0].amount_paise)}`); }
      else say("label", "No inbound transfer into Kiran Traders yet — inject the money-mule network first.");
    } catch (e) { say("label", err(e)); } finally { setBusy(null); }
  };
  const report = async () => {
    if (!txId.trim()) { say("label", "Enter a transaction id."); return; }
    setBusy("label");
    try { const r = await api.label(txId.trim()); say("label", `Labelled ${r.label_id}. TaintTrace re-ran: ${r.taint.exposure.length} account(s) hold traced value.`); }
    catch (e) { say("label", err(e)); } finally { setBusy(null); }
  };
  const toggleAmbient = async () => {
    setBusy("amb");
    try { const r = await api.ambient(!health?.ambient); say("env", `Background traffic ${r.enabled ? "resumed" : "paused"}.`); }
    catch (e) { say("env", err(e)); } finally { setBusy(null); }
  };
  const toggleMode = async () => {
    const next = mode?.mode === "shadow" ? "active" : "shadow";
    setBusy("mode");
    try { await api.setMode(next); refreshMode(); say("env", `Mode set to ${next.toUpperCase()}.`); }
    catch (e) { say("env", err(e)); } finally { setBusy(null); }
  };
  const reset = async () => {
    if (!window.confirm("Reset the demo world? Every posting, decision and attack run since seeding is discarded.")) return;
    setBusy("reset");
    try { await api.reset(); setRun(null); say("env", "World re-seeded — identical starting state."); loadScen(); }
    catch (e) { say("env", err(e)); } finally { setBusy(null); }
  };

  const payMsg = msg.pay?.split("|");
  return (
    <>
      <div className="tc-backdrop" onClick={onClose} />
      <aside className="tc" role="dialog" aria-label="Test inputs">
        <div className="tc-h">
          <div className="grow">
            <div className="t">Test inputs</div>
            <div className="s">Demo environment only — minimal inputs that drive the real system. Every action below is a real
              API call: payments run the full pre-commit path, patterns are real ledger postings scored live.</div>
          </div>
          <button className="btn xs" onClick={onClose} aria-label="Close">Close</button>
        </div>
        <div className="tc-b">
          <section className="tc-sec">
            <h4><span className="n">1</span>Customer payment</h4>
            <div className="row wrap tight">
              {PRESETS.map((p) => (
                <button key={p.label} className="btn xs" onClick={() => choose(p)}>{p.label}</button>
              ))}
            </div>
            <div className="row wrap tight">
              <span className="tc-res">More tiers:</span>
              {MORE_PRESETS.map((p) => (
                <button key={p.label} className="btn xs" onClick={() => choose(p)}>{p.label}</button>
              ))}
            </div>
            {preset && <div className="tc-res">Expected: <b>{preset.expect}</b></div>}
            <div className="tc-row">
              <label className="field">Paying as
                <select className="select" value={payer} onChange={(e) => setPayer(e.target.value)}>
                  {PAYERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </label>
              <label className="field">Amount (₹)
                <input className="input" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} />
              </label>
            </div>
            <label className="field">To (UPI id)
              <input className="input" list="tc-payees" value={to} onChange={(e) => setTo(e.target.value)} />
              <datalist id="tc-payees">{PAYEES.map((p) => <option key={p} value={p} />)}</datalist>
            </label>
            <label className="field">Note
              <input className="input" value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <label className="field">Simulated call / message context <span className="sim">simulated</span>
              <input className="input" placeholder="e.g. caller says they are from police, keep it secret" value={ctx} onChange={(e) => setCtx(e.target.value)} />
            </label>
            <div className="row tight">
              <button className="btn primary" onClick={openOnDevice}>Open on customer device</button>
              <button className="btn" disabled={busy === "pay"} onClick={submitDirect}>{busy === "pay" ? "Submitting…" : "Submit directly"}</button>
            </div>
            {payMsg && <div className="tc-res">{payMsg[0]}{payMsg[1] && <> · <a href={`/investigations/decision/${payMsg[1]}`} onClick={(e) => { e.preventDefault(); nav(`/investigations/decision/${payMsg[1]}`); onClose(); }}>open case</a></>}</div>}
          </section>

          <section className="tc-sec">
            <h4><span className="n">2</span>Inject a mule-network pattern</h4>
            <div className="row tight">
              <select className="select" value={pattern} onChange={(e) => setPattern(e.target.value)}>
                {network.map((s) => <option key={s.id} value={s.id}>{s.name}{s.id === "s2" ? " (scam ring + cash-out)" : ""}</option>)}
              </select>
              <button className="btn primary" disabled={busy === "inject" || !!running} onClick={inject}>{busy === "inject" ? "…" : "Inject"}</button>
            </div>
            {PATTERN_EXPECT[pattern] && <div className="tc-res">Expected: <b>{PATTERN_EXPECT[pattern]}</b> · no false positives</div>}
            {running && <div className="tc-res"><b>{running.name}</b> · {running.state} · step {running.step}/{running.total_steps}
              {running.state === "running"
                ? <> · <a href="#" onClick={(e) => { e.preventDefault(); api.scenarioPause(running.id).then(loadScen); }}>pause</a></>
                : <> · <a href="#" onClick={(e) => { e.preventDefault(); api.scenarioResume(running.id).then(loadScen); }}>resume</a></>}</div>}
            {run && <div className="tc-res">{run.run_id} · {run.status}: detected <b>{run.detected.length}</b> of {run.injected.length} injected accounts
              {run.false_positives.length ? `, ${run.false_positives.length} false positive(s)` : ", no false positives"}
              {run.detection_ms != null ? ` · ${(run.detection_ms / 1000).toFixed(1)} s to detection` : ""} <span className="sim gt">simulator ground truth</span></div>}
            {msg.inject && !run && <div className="tc-res">{msg.inject}</div>}
            <div className="tc-res">Watch it in <a href="/network" onClick={(e) => { e.preventDefault(); nav("/network"); onClose(); }}>Network</a> and <a href="/" onClick={(e) => { e.preventDefault(); nav("/"); onClose(); }}>Overview</a>.</div>
          </section>

          <section className="tc-sec">
            <h4><span className="n">3</span>Coerced payment (digital-arrest journey)</h4>
            <div className="tc-res">Sunita: new device → payee added → limit raised → threatening call (simulated) → 95% of savings.</div>
            <div className="row tight">
              <button className="btn primary" disabled={busy === "s3" || !!running} onClick={coerced}>{busy === "s3" ? "…" : "Run journey"}</button>
              <a className="btn" href="/contact/arjun" target="_blank" rel="noreferrer">Trusted contact's phone ↗</a>
            </div>
            {msg.s3 && <div className="tc-res">{msg.s3}</div>}
          </section>

          <section className="tc-sec">
            <h4><span className="n">4</span>Report a confirmed scam</h4>
            <div className="row tight">
              <input className="input mono" placeholder="transaction id, e.g. TX-030990" value={txId} onChange={(e) => setTxId(e.target.value)} />
              <button className="btn" disabled={busy === "find"} onClick={findSource}>Find ring source</button>
            </div>
            <button className="btn primary" disabled={busy === "label"} onClick={report}>{busy === "label" ? "Reporting…" : "Report as confirmed scam"}</button>
            {msg.label && <div className="tc-res">{msg.label}</div>}
          </section>

          <section className="tc-sec">
            <h4><span className="n">5</span>Environment</h4>
            <div className="row wrap tight">
              <button className="btn sm" disabled={busy === "amb" || !health} onClick={toggleAmbient}>{health?.ambient ? "Pause background traffic" : "Resume background traffic"}</button>
              <button className="btn sm" disabled={busy === "mode" || !mode} onClick={toggleMode}>{mode?.mode === "shadow" ? "Switch to ACTIVE" : "Switch to SHADOW"}</button>
              <button className="btn sm danger" disabled={busy === "reset"} onClick={reset}>{busy === "reset" ? "Resetting…" : "Reset demo world"}</button>
            </div>
            {msg.env && <div className="tc-res">{msg.env}</div>}
            <div className="tc-res">Advanced: <a href="/lab" onClick={(e) => { e.preventDefault(); nav("/lab"); onClose(); }}>scenario lab</a> (all 15 scenarios, replay, detector comparison).</div>
          </section>
        </div>
      </aside>
    </>
  );
}
