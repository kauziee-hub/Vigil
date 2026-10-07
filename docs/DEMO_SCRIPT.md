# Demo Script — five acts + platform tour, ~10 minutes (v2 UI)

Every act below was walked through in the browser on the merged v2 build (2026-10-07; record in `AGENT_HANDOFF/runs/20261007-0110_claude3_frontend-redesign-run3.md`). Scenario tiers are deterministic at any time of day: scripted scenarios evaluate time-of-day rules at a pinned 14:00 IST and the decision record says so.

## Before you start (2 minutes, once)

1. `powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Reset` (or `./run_demo.sh --reset`). It prints the URLs.
2. Laptop, two windows side by side:
   * **Transaction Guard** `http://localhost:8000/guard` — the customer's device and the bank's pre-commit assessment on one screen;
   * **Scenario Lab** `http://localhost:8000/lab` (or **Overview** `/`).
3. Phone on the same Wi-Fi: the printed **trusted-contact URL** `http://<laptop-ip>:8000/contact/arjun`. Fallback: a second browser tab.
4. Top status strip: **MODE ACTIVE**, payments chip (*Mock* or *Razorpay TEST*), **REALTIME live**, policy version. System Health (`/health`) should say **Intel layer ON**.
5. If anything looks off: **Reset demo** (Scenario Lab, top right). Every act gives the same result after a reset. If the browser shows an old-looking UI after an upgrade, reload once (`index.html` is never cached from now on).

---

## ACT 1 — Normal customer (45 s)

**Do:** Transaction Guard, *Paying as* **ramesh** → demo input *Act 1 · Grocer ₹500* → **Pay ₹500**.
**See:** device: **Paid ₹500**, *DEMO PAYMENT (mock provider)* (or Razorpay TEST). Right: the structured pre-commit assessment — sender, recipient, amount (robust z), relationship *ESTABLISHED*, device *PRIMARY*, behaviour, network, external (*SIMULATED*), journey, context → **T0 · PASS**, evaluated in ~1 ms. *Model evidence — corroborating only*: RF / GNN / rules / drift / pattern memory all quiet.
**Say:** "Every payment is evaluated before the provider is called. Known recipient, usual amount, known device, clean network: Tier 0, zero added friction." Point at *Outcome*: provider succeeded, ledger edge added, recipient risk unchanged.

## ACT 2 — Suspicious recipient, before payment (60 s)

**Do:** **New payment** → *Act 2 · Kiran Traders ₹45,000* → **Pay**.
**See:** **T2 · Confirm before paying** (score 0.34). Assessment: External intel *Registry: reported* (**SIMULATED**), RingWatch *Rapid pass-through* + *New account, large inflow*, behaviour *amount outlier*, *first-time payee*. Model evidence beside it: **RF 1.00 · GNN 1.00 · drift HIGH · pattern memory 81 % "Rapid Fan-In / Pass-Through"** — and the tier is still T2.
**Say:** "The risk is the recipient: a 9-day-old account whose money leaves within ~17 minutes. Nothing has been sent — PRIMA intervenes before irreversible commitment. And notice: the machine-learning models are certain, but they do **not** set the tier. The transparent policy engine decides; the models corroborate."
**Do (optional, 30 s):** **Investigate** → case page → **▶ Play** the Decision Replay (score builds frame by frame); scroll to the **counterfactual ladder** ("with a clean recipient record → T0"), then the two separate panels: *ReasonLine — explains the OPERATIONAL DECISION* vs *Detector consensus · SHAP — explains the MODEL*.

## ACT 3 — Where that intelligence comes from (2–3 min)

**Do:** Scenario Lab → **Money-mule network (s2)** → **▶ Start** (17 steps, ~20 s; live step log). Marked *SIMULATED INPUTS*.
**Do:** **Compare detectors** → one matrix, accounts × detector families: kiran.traders 8/8 *strong*, zenith.exports and pooja.m *strong*, the victims only *drift* (1/8 weak — they genuinely changed behaviour), rahul.m weak (an honest miss).
**Do:** **Attack scene in 3D ↗** → Network Intelligence scoped to s2 (~22 nodes; layout frozen on the server, no physics). Switch modes **RISK → MULE ROLES → GNN SCORE**. **Attack replay** to scrub the transfers in order.
**Do:** Select **Kiran Traders** (or open `/network?focus=kiran.traders@vigil`) → drawer: RingWatch flags, *8 of 8 signal families agree*, SHAP (*explains the MODEL*), drift baseline → current, pattern memory (*structural similarity, not attribution*), role *Collector*.
**Do:** Drawer → *Recent postings* → **Confirm scam** on `← anita.s ₹48,000` ("a verified 1930 report confirmed by the bank").
**See:** TaintTrace panel: LIBR vs pro rata side by side, both conserved — ₹21,500 still attributable at Kiran Traders, ₹26,500 at Zenith Exports (= ₹48,000).
**Say:** "We don't claim a better mule detector — banks have MuleHunter and DPIP. This is the post-payment half of the same lifecycle: where the money went, how much is still attributable, under which rule."
**Do:** Back to **Transaction Guard** → *Act 2 · Kiran Traders ₹45,000* again → **Pay**.
**See:** **T3 · Scoped hold** (score 0.58) with two new reasons: *labelled account* and *taint exposure*. The cap `CAP_NO_SENDER_EVIDENCE` keeps it at T3: trusted-contact escalation is reserved for sender compromise.
**Say:** "Same recipient, same customer — the network learned something, and the very next decision inherited it."

## ACT 4 — Coerced customer (90 s)

**Do:** Transaction Guard → *Paying as* **sunita**. Scenario Lab → **Coerced / digital-arrest payment (s3)** → **▶ Start**.
**See (Lab log):** new device → payee added → limit raised → *simulated* threat call → 95 % of savings. *(TIME-COMPRESSED; the UI says so.)*
**See (Sunita's device, by itself):** **T4 · Hold + CircuitBreaker** (score 0.64): only ₹5,61,600 is held; the account keeps working.
**See (phone):** Arjun's alert arrives live — "An unusually large payment from Sunita's account to a newly-added recipient is awaiting confirmation" + three facts. Tap **I'm calling them now** → the phone confirms "Your response was sent to the bank: Arjun Rao (son) is calling"; Sunita's device shows the same line and the bank's Interventions queue shows *Arjun Rao · calling user*.
**Say:** "None of these events alone proves anything. Together, within 8 minutes, the sequence is highly abnormal. Vigil chose a proportionate intervention: hold only this amount, tell a trusted person facts, not accusations." Note the models do *not* flag this recipient — coercion is caught by the journey and context, not by mule structure.
**Do:** **Interventions** (`/interventions`) → the T4 row (review clock, CircuitBreaker response) → **Reject** → confirm (nothing sent; hold closed).

## ACT 5 — Explainability and governance (60 s)

**Do:** Interventions → **Case →** (or Governance & Audit → *Decision records*) → the Act 4 decision → **Decision record**.
**See:** identity, chosen action, *evaluation context* (pinned scenario hour), subscores, reason codes incl. `ADJ_CORROBORATION` (3 independent dimensions), the **policy ladder at decision time** with this decision marked, every component and model version, data provenance with *SIMULATED* markers, the operator trail ending in the bank's **Rejected**, payment result *provider not called · no posting*. **View raw record** shows the append-only JSON with its SHA-256 integrity hash.
**Do:** Governance & Audit → **ACTIVE / SHADOW** (confirm) → the amber *SHADOW MODE* band appears on every page; a payment is now recorded with Vigil's recommendation beside the bank baseline, but not intervened. Switch back to **ACTIVE**.
**Close:** "We are not proposing another fraud classifier. India already has sophisticated detection — bank EFRMS, MuleHunter and DPIP. Vigil is the layer that converts those signals — plus local journey and network evidence — into an explainable, governable intervention at the last reversible moment." Optionally open *Deployment positioning*.

## Platform tour (if there is time, 1–2 min)

* **Detection & Models** `/detection` — *SYNTHETIC VALIDATION* banner and *Operational use: corroborating evidence only*; per-family agreement; the model registry (confusion matrix, calibration raw vs calibrated, per-attack and leave-one-attack-family-out recall — including where the GNN fails on unseen families).
* **Scenario Lab** — any of the 10 attack patterns (fan-in, fan-out, circular ring, velocity chain, cross-channel, shared device, behavioural drift, volume spike, smurfing, dormant) → **Compare detectors** → **Attack scene in 3D**.
* **System Health** `/health` — decision p95 (~2 ms), realtime sockets, ledger conservation (₹0), caches, intel availability, endpoint coverage. No polling anywhere.

## Control (if asked "doesn't it flag everything?")

Transaction Guard as Ramesh → *Control · Landlord ₹1,20,000* → **T0**. Behaviour notes the amount is unusual; known payee, known device, clean registry → no friction.

## Fallbacks

| Problem | Do this |
|---|---|
| Razorpay Checkout fails / offline | Click **Complete as DEMO payment** — same lifecycle, labelled DEMO PAYMENT. Or start with `-Mock`. |
| Phone can't reach laptop | Open `/contact/arjun` in a second browser tab. Check Windows firewall allows Python on private networks. |
| 3D view doesn't render (no WebGL) | Toggle **2D** on Network Intelligence; the drawer, TaintTrace panel and Compare detectors prove the same thing. |
| Old-looking UI after an upgrade | Reload once (the cached v1 shell; `index.html` is served `no-cache` now). |
| Anything inconsistent | **Reset demo** — deterministic. |
| Internet down | Everything except Razorpay works locally. |
