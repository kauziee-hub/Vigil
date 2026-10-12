# Demo script — final demonstration (v6 UI, ~12 minutes)

Every step below was run end to end on the live backend on 2026-10-12. The results shown are what the system produced, not mock-ups. The record is in `AGENT_HANDOFF/runs/20261012-2130_claude1_v5-final-demo.md`.

The product screens show no simulation controls. Everything you drive for the demo comes from **Test inputs** (top bar, or **Alt + T**). This is a small drawer of minimal inputs, in the style of PRIMA's `/ops` page. Every input is a real API call.

## Before you start (once)

1. `powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Reset` (or `./run_demo.sh --reset`). It prints the URLs.
2. Browser at `http://localhost:8000/` (Operations center), full-screen, 1440–1920 px wide.
3. Phone on the same Wi-Fi: the printed trusted-contact URL `http://<laptop-ip>:8000/contact/arjun` (fallback: a second browser tab).
4. Top bar: the health icon has a green dot, the user chip says **Active mode · live**, and the footer says **Payments: Mock provider**. The Razorpay test keys in `.env` are rejected (HTTP 401), so payments use the clearly labelled mock provider. Put fresh `rzp_test_` keys in `.env` and restart to use the real gateway.
5. If anything looks off: **Test inputs → Reset demo world** (about 5–20 s). Every step gives the same result after a reset.

---

## 1. The operations center (1 min)
**Say:** "This is the bank's fraud operations view: what needs action first, then how money is moving, then why accounts are flagged, then how well detection performs."
**Point at:** the **KPI strip** (payments assessed, postings, open interventions, last-run detection, models active, ledger integrity), the live transaction network (each node is an account, each live posting draws an edge), **Accounts at risk**, **Payments protected**, **Detector families**, **Needs attention**, **Transaction traffic**.
**Edge filter** (top left of the network): **Recent** shows only the last two minutes, **Risk only** shows flows touching risky accounts, **All** adds the faint history. Further down: **What drives the model** (SHAP), **Pattern memory & early warning**, **Decisions by tier**, **Detection performance**, the live streams and **Account scoring**, which covers every scored account (549) and can be sorted by rules / Random Forest / GNN.

## 2. An everyday payment (1 min)
**Do:** Test inputs → *Everyday · grocer ₹500* → **Open on customer device** → **Pay**.
**See:** the iPhone shows **Paid ₹500**. On the right, the bank sees the full pre-commit assessment (sender, recipient, amount, relationship, device, behaviour, network, external intel (simulated), journey, context) → **Tier 0 · pass**, evaluated in milliseconds.

## 3. A risky recipient (1.5 min)
**Do:** Test inputs → *Risky recipient · ₹45,000* → **Open on customer device** → **Pay**.
**See:** **Tier 2 · "Please confirm before you pay"**, with four plain questions for the customer. The bank side shows why: first-time payee, outlier amount, recipient linked to rapid pass-through, a registry report (simulated).
**Note:** after midnight, an "unusual hour" signal (+0.05) lifts this payment to Tier 3. That is real policy behaviour, and the case page's counterfactuals show it.

## 4. A money-mule network forms (2 min)
**Do:** Test inputs → *Inject a mule-network pattern* → **Money-mule network** → **Inject** (17 real ledger postings over about 20 s). Close the drawer and watch the Overview.
**See:** the ring lights up in the network (Kiran Traders → Zenith Exports → Pooja M). Switch the edge filter to **Risk only** to see just the ring's flows; **Detection performance** fills in the run (detected / missed / first warning / latency). **Accounts at risk** shows *action needed* and toasts appear. The console shows **detected 3 of 4 injected accounts, no false positives, about 27 ms after the closing posting** (simulator ground truth).
**Then:** Overview → **Needs attention** → *Kiran Traders* → the account page: why it is flagged (RingWatch rules in plain language), detector consensus **8 of 8 families agree**, role **collector**, SHAP per feature, drift baseline → current, pattern memory.

## 5. Confirm the scam, and the next payment is held (1.5 min)
**Do:** Test inputs → *Report a confirmed scam* → **Find ring source** → **Report as confirmed scam**.
**See:** label created; TaintTrace follows the money downstream (2 accounts hold traced value).
**Do:** *Risky recipient · ₹45,000* again → **Open on customer device** → **Pay**.
**See:** **Tier 3 · scoped hold**. The same payment is now held because of what the network learned. No account is frozen, and only this payment is paused.

## 6. Coerced payment, "digital arrest" (2 min)
**Do:** Test inputs → *Coerced payment* → **Run journey**. Open the trusted contact's phone.
**See:** Sunita's journey: new device → payee added → limit raised → threatening call (simulated) → ₹5,61,600 → **Tier 4 · hold + trusted contact alerted**. Arjun's phone shows the alert card with facts, never accusations. Tap **I'm calling them now**; the bank's case shows the response.
**Then:** **Cases → the Tier 4 case → Decision Replay → Play**. The score builds frame by frame (new device 0.04 → payee 0.07 → limit 0.11 → context 0.36 → transfer 0.64). Below it: the **counterfactual ladder** (what would make it safe) and **provenance** for every signal.

## 7. The bank acts and governs (1.5 min)
**Do:** **Interventions** → **Release** one hold and **Reject** another (real state changes). Then **Governance**: policy weights and the tier ladder, model versions, decision records (view raw / replay), and **Shadow mode** (Test inputs → *Switch to SHADOW*): Vigil records its recommendation next to the bank's baseline without intervening.

## 8. Detection & models (1 min)
**Do:** **Detection**.
**See:** model metrics labelled **SYNTHETIC VALIDATION** (held-out synthetic worlds, not real-bank accuracy), per-attack recall, live detection runs (each injected pattern evaluated: detected / missed / false positives / latency), rules firing now, early warning, roles, pattern memory. Say: **"Rules decide the payment; models corroborate. SHAP explains the model; the reason line explains the decision."**

---

### Honesty points to state if asked
* Synthetic data; not connected to any bank, regulator or payment network. External intelligence and call context are **simulated** and labelled.
* Model metrics are **synthetic validation**. Models are corroborating evidence and never set a payment tier.
* Payments use the mock provider while the Razorpay test keys are invalid. The code path for Razorpay test mode is real and switches over automatically with valid keys.
