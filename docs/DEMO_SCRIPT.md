# Demo script — final demonstration (~12 minutes)

Every step below was run end to end on the live backend (last verified 2026-10-13). The results shown are what the system produced, not mock-ups. Records: `AGENT_HANDOFF/runs/`.

The product screens show no simulation controls. Everything you drive for the demo comes from **Test inputs** (top bar, or **Alt + T**). This is a small drawer of minimal inputs, in the style of PRIMA's `/ops` page. Every input is a real API call.

## Before you start (once)

1. `powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Reset` (or `./run_demo.sh --reset`). It prints the URLs.
2. Browser at `http://localhost:8000/` (Operations center), full-screen, 1440–1920 px wide.
3. Phone on the same Wi-Fi: the printed trusted-contact URL `http://<laptop-ip>:8000/contact/arjun` (fallback: a second browser tab).
4. Top bar: the health icon has a green dot and the user chip says **Active mode · live**. The footer says **Payments: simulated rail (no real money)**. No keys or `.env` are needed.
5. If anything looks off: **Test inputs → Reset demo world** (about 5–20 s). Every step gives the same result after a reset.

---

## 1. The operations center (1 min)
**Say:** "This is the bank's fraud operations view: what needs action now, and why."
**Point at, top to bottom:**
- The **KPI strip**: accounts at risk, open interventions, payments passed without friction, decision latency, the last detection run, and postings.
- The live transaction **network**, with **Needs attention** beside it (accounts / payments, each row opens the case).
- **Why accounts are flagged**: SHAP drivers, how many detector families agree, and the last detection run.
- **Transaction traffic.**

**Edge filter** (top left of the network): **Recent** shows the last two minutes. **Risk only** shows flows touching risky accounts. **All** adds the faint history.
Deeper analytics live on their own pages: **Detection** (models, every run, full account scoring for 549 accounts) and **Network** (lenses, live activity streams).

## 2. An everyday payment (1 min)
**Do:** Test inputs → *Everyday · grocer ₹500* → **Open on customer device** → **Pay**.
**See:** the iPhone shows **Paid ₹500**. On the right, the bank sees the full pre-commit assessment (sender, recipient, amount, relationship, device, behaviour, network, external intel (simulated), journey, context) → **Tier 0 · pass**, evaluated in milliseconds.

## 3. A risky recipient (1.5 min)
**Do:** Test inputs → *Risky recipient · ₹45,000* → **Open on customer device** → **Pay**.
**See:** **Tier 2 · "Please confirm before you pay"**, with four plain questions for the customer. The bank side shows why: first-time payee, outlier amount, recipient linked to rapid pass-through, a registry report (simulated).
**Note:** after midnight, an "unusual hour" signal (+0.05) lifts this payment to Tier 3. That is real policy behaviour, and the case page's counterfactuals show it.

## 4. A money-mule network forms (2 min)
**Do:** Test inputs → *Inject a mule-network pattern* → **Money-mule network** → **Inject** (17 real ledger postings over about 20 s). Close the drawer and watch the Overview.
**See:** the ring lights up in the network (Kiran Traders → Zenith Exports → Pooja M). The KPI **Accounts at risk** rises and toasts appear. **Last attack result** shows the run: **3 of 4 injected accounts flagged, the 4th surfaced at early warning, no false positives, about 30 ms after the first posting** (simulator ground truth). Press **Show in network** to switch the edges to **Risk only** and focus on the ring.
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
* Payments settle on a **simulated rail** behind a provider port. No real money moves; a bank would plug its own rail into the same port.
* Detection of the eleven injectable patterns (live check, 2026-10-13): every pattern detected, **0 false positives** in every run, and every injected mule account surfaced at early warning or above. Fully flagged: 9 of 11 patterns. The two partial ones:
  - Money-mule network: 3 of 4 flagged. The downstream account is at early warning.
  - Velocity chain: 3 of 5 flagged. The chain's first and last accounts are at early warning.
  These stay at early warning by design: a lone fast-chain signal also matches a victim who receives money and pays within minutes.
