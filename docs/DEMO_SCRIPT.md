# Demo Script — five acts, ~7 minutes

## Before you start (2 minutes, once)

1. `powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Reset` (or `./run_demo.sh --reset`). It prints three URLs.
2. Laptop browser, two windows side by side: **Command center** `http://localhost:8000/` and **Pay** `http://localhost:8000/pay?as=ramesh@vigil`.
3. Phone on the same Wi-Fi: open the printed **trusted-contact URL** `http://<laptop-ip>:8000/contact/arjun`. Fallback: a second browser tab.
4. Top bar should show a green "live" dot. Payment chip shows *Razorpay TEST* (valid test keys) or *Mock payments* — both are fine.
5. If anything looks off: **Reset demo** (command center, top right). Every act gives the same result after a reset.

---

## ACT 1 — Normal customer (45 s)

**Do:** Pay screen as Ramesh → *Act 1 · Grocer ₹500* → **Pay**.
**See:** "Vigil is checking this payment" → **Approved** → Paid. Receipt says *DEMO PAYMENT* (or *RAZORPAY TEST MODE — no real money moved* if Checkout is used). Side panel: all five dimensions at 0.00, evaluated in ~1 ms.
**Say:** "Every payment is evaluated before the provider is called. Known recipient, usual amount, known device, clean network: Tier 0. Most payments experience zero additional friction." Point at *After the payment*: "the ledger and graph updated; recipient risk unchanged."

## ACT 2 — Suspicious recipient, before payment (60 s)

**Do:** *New payment* → *Act 2 · Kiran Traders ₹45,000* → **Pay**.
**See:** **Tier 2 · Confirm.** Four blocks: RISK LEVEL / WHY WE ARE INTERRUPTING / WHAT ACTION IS BEING TAKEN; contribution panel on the right (External 0.16 — labelled *SIMULATED*, Network 0.11, Behaviour 0.07). Counterfactual: "without the external evidence → Tier 1".
**Say:** "Ramesh behaves normally. The risk is the recipient: a 9-day-old account whose money leaves within ~17 minutes, reported in a (simulated) shared registry. This is PRIMA: intervention happens **before** irreversible commitment — nothing has been sent." Click **Don't send**.

## ACT 3 — Where that intelligence comes from (2 min)

**Do:** Open **Network**. Show the small graph (only Kiran Traders + counterparties). Click **▶ Inject mule ring** (Scenario 2). Background activity continues.
**See:** in ~20 s: five victims fan in → Kiran Traders (collector, red) → Zenith Exports (pass-through) → split / smurfing → ATM cash-out. 17 nodes, not the whole bank.
**Do:** Click **Kiran Traders** → evidence: *Many first-time senders*, *Rapid pass-through 94 %*, *New account, large inflow* — each with raw numbers.
**Do:** In *Recent ledger postings*, click **Confirm scam** on `← anita.s ₹48,000` ("a verified 1930 report").
**See:** Anita turns blue (source); traced edges turn red; TaintTrace panel: LIBR vs pro rata side by side, both ✓ conserved.
**Say:** "We don't claim a better mule detector — banks have MuleHunter and DPIP for that. This is the post-payment half of the same lifecycle: where the money went, how much is still attributable, under which rule."
**Do:** Back to **Pay** → *Act 2 · Kiran Traders ₹45,000* again → **Pay**.
**See:** **Tier 3 · Scoped hold**. New fact: "₹21,500 now in this account traces back to a payment the bank confirmed was stolen." Bank view shows `CAP_NO_SENDER_EVIDENCE`: score would be Tier 4, but trusted-contact escalation is reserved for sender compromise.
**Say:** "Same recipient, same customer — the network learned something, and the very next decision inherited it."

## ACT 4 — Coerced customer (90 s)

**Do:** Pay screen → switch to **sunita@vigil**. Command center → Scenario **Act 4 · Coerced / digital-arrest** → **▶ Start**.
**See (command center log):** new device (−8 min) → payee added (−6) → limit raised (−4) → *simulated* threat call (−2) → payment of 95 % of savings. *(Time-compressed; the UI says so.)*
**See (Sunita's screen):** **Tier 4 · Hold + CircuitBreaker** appears by itself. "Police, CBI… never ask you to transfer money to avoid arrest. There is no 'digital arrest'." Only ₹5,61,600 on hold; ₹29,570 still available.
**See (phone):** Arjun's alert arrives live: *"An unusually large payment from Sunita's account to a newly-added recipient is awaiting confirmation"* + three facts. Tap **I'm calling them now** → Sunita's screen shows "Arjun Rao (son) is calling."
**Say:** "None of these events alone proves anything. Together, within 8 minutes, the sequence is highly abnormal. The payment hasn't simply been blocked — the system chose a proportionate intervention: hold only this amount, tell a trusted person facts, not accusations."
**Optional:** Investigate → this decision → **Reject payment** (nothing sent) or **Release hold**.

## ACT 5 — Explainability (45 s)

**Do:** Investigate → the Act 4 decision → **Explain (3 views)**.
**See:** 1 · Customer reason (plain language) · 2 · Bank evidence (contributions, every rule with raw evidence, registry, adjustments) · 3 · Audit record (exact inputs, scores, policy version, latency, SHA-256 integrity hash; decision rows are append-only).
**Close:** "We are not proposing another fraud classifier. India already has sophisticated detection — bank EFRMS, MuleHunter and DPIP. Vigil is the layer that converts those signals — plus local journey and network evidence — into an explainable intervention at the last reversible moment." Optionally open **Where it sits**.

## Control (if asked "doesn't it flag everything?")

Pay as Ramesh → *Control · Landlord ₹1,20,000* → **Tier 0**. Behaviour notes the amount is unusual; known payee, known device, clean registry → no friction.

## Fallbacks

| Problem | Do this |
|---|---|
| Razorpay Checkout fails / offline | Click **Complete as DEMO payment** — same lifecycle, labelled DEMO PAYMENT. Or start with `-Mock`. |
| Phone can't reach laptop | Open `/contact/arjun` in a second browser tab. Check Windows firewall allows Python on private networks. |
| Graph doesn't render | Evidence table in the right panel + Investigate → Timeline / Money trace prove the same thing. |
| Anything inconsistent | **Reset demo** — deterministic. |
| Internet down | Everything except Razorpay works locally. |
