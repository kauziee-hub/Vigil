# Real-World Positioning

> **Vigil consumes — or could consume — existing institutional intelligence and adds a pre-commitment decision and intervention orchestration layer.** It is not a mule detector competing with MuleHunter.AI, not a shared registry competing with DPIP, and not integrated with any RBI, RBIH, NPCI or I4C system.

## 1. The Indian ecosystem (checked October 2026)

| Actor / system | What it is | Relationship to Vigil |
|---|---|---|
| **RBI** | Regulator. Issued the *Authentication Mechanisms for Digital Payment Transactions Directions, 2025* (in force 1 April 2026), which require two factors (one dynamic) and allow risk-based checks; issuers bear losses from non-compliance. *Payments Vision 2028* (March 2026). | Vigil's interventions (confirm, hold, escalate) are the kind of risk-based, proportionate step a bank could take *within* its own authentication and fraud controls. Vigil claims no regulatory approval. |
| **RBIH** (Reserve Bank Innovation Hub, RBI subsidiary) | Built **MuleHunter.AI**, an AI/ML mule-account detection model deployed inside banks (Canara Bank, PNB, Bank of India, Bank of Baroda, AU SFB among adopters; more banks rolling out; the Finance Ministry has asked banks to adopt it). Also building the **DPIP** prototype. | A bank running MuleHunter already has strong mule flags. Vigil would read such a flag as one external input (`ExternalFraudIntelProvider`). We **do not** claim to detect mules better. |
| **DPIP** (Digital Payments Intelligence Platform) | RBI-led shared fraud-intelligence platform being built by RBIH with banks; its Smart Registry phase has run since August 2025; a planned AI risk score aims to warn banks *before* a suspicious UPI/card/net-banking payment completes; to be operated by IDPIC. | DPIP produces intelligence and (planned) risk scores. Vigil is the bank-side layer that decides *what to do* with such a score at commit time, combined with the bank's own journey/behaviour/context evidence, and explains it. Vigil's `LocalRegistryProvider` imitates the *shape* of such a response; it is **simulated**. |
| **NPCI** | Operates UPI and runs network-level fraud-risk controls for UPI participants. | Vigil sits at the issuer/PSP app before the payment request is submitted to the rail; it does not intercept UPI. |
| **Bank EFRMS / AML** | Each bank's enterprise fraud-risk management and AML transaction monitoring. | Natural host or neighbour. Vigil can run as a pre-commit decision service called by the bank's payment flow, emitting decisions EFRMS/AML case management can consume. |
| **I4C / NCRP / 1930 / CFCFRMS** | MHA's Indian Cyber Crime Coordination Centre: National Cybercrime Reporting Portal and 1930 helpline; CFCFRMS for fund-holding on reported frauds; a **Suspect Registry** (launched 2024) shared with banks. | Victim reports via 1930/NCRP are the realistic source of the "confirmed scam" label that triggers TaintTrace in Act 3 (simulated here as an analyst click). A suspect-registry match would be another external input. |
| **DoT Financial Fraud Risk Indicator (FRI)** | Risk rating of mobile numbers (Medium/High/Very High) shared with banks/UPI apps from the Digital Intelligence Platform; PhonePe and others act on it. | Another external signal Vigil could consume for the payee's mobile-linked VPA. Not integrated. |

Sources: RBIH/MuleHunter adoption ([Business Standard](https://www.business-standard.com/industry/banking/15-more-banks-to-adopt-rbi-s-mulehunter-fraud-detection-tool-by-october-125080101845_1.html), [Outlook Business](https://www.outlookbusiness.com/economy-and-policy/finance-ministry-asks-banks-to-use-mulehunterai-to-check-digital-fraud)); DPIP ([Outlook Business](https://www.outlookbusiness.com/economy-and-policy/rbi-led-initiative-to-curb-digital-frauds-gains-momentum-banks-roped-in-to-set-up-dpip), [Business Standard](https://www.business-standard.com/finance/news/fin-min-pushes-rbi-to-expedite-launch-of-platform-to-curb-digital-frauds-125093000979_1.html), [Vision IAS](https://dce.visionias.in/news-today/2025-06-24/economy/rbi-and-banks-to-develop-the-digital-payment-intelligence-platform-dpip)); I4C Suspect Registry / CFCFRMS ([GKToday](https://www.gktoday.in/cybercrime-registry-saves-billions-in-fraud-prevention/)); DoT FRI ([Sanchar Saathi PDF](https://www.sancharsaathi.gov.in/SancharSaathiDocuments/ImportantDocuments/DoT%20Introduces%20Financial%20Fraud%20Risk%20Indicator%20(FRI)%20to%20strengthen%20Cyber%20Fraud%20Prevention.pdf), [Business Standard](https://www.business-standard.com/industry/news/dot-launches-financial-fraud-risk-indicator-to-aid-cybercrime-detection-125052101912_1.html)); RBI authentication directions ([Khaitan & Co](https://khaitanco.com/thought-leadership/RBI-Authentication-Mechanisms-for-Digital-Payments-Transactions-Directions), [Taxmann](https://www.taxmann.com/post/blog/rbi-issues-directions-on-authentication-for-digital-payments)).

### Claims we never make
* "Nobody uses AI for mule detection." (MuleHunter.AI does.)
* "DPIP cannot detect fraud." (It is designed to.)
* "We integrate directly into RBI / NPCI / I4C." (We do not.)
* "Vigil reads calls / WhatsApp / SMS." (It cannot; context is simulated.)

## 2. Where Vigil sits

```
Customer app (bank / PSP)  ──intent──▶  VIGIL pre-commit decision service  ──approved──▶  payment rail (UPI/IMPS…)
                                            ▲            │                                     │
         bank EFRMS/AML, MuleHunter flags,  │            ▼                                     ▼
         DPIP-style registry, I4C/FRI ──────┘   pass / inform / confirm / scoped hold /   ledger postings
                                                hold + trusted-contact CircuitBreaker      │
                                            ▲                                              ▼
                                            └──────── RingWatch + TaintTrace (post-payment monitoring) ◀─┘
```

## 3. Module by module

| Module | Who would host it | Data it needs | When it runs | Integrates with | Decision it produces | Built now or simulated | What changes for production |
|---|---|---|---|---|---|---|---|
| **Payment Intent Gateway** | Issuing bank / PSP app backend | Intent (payer, payee VPA, amount, device, channel) | Every payment, before submission to the rail | Mobile/net banking, UPI PSP flow | Intent state machine; nothing moves until approved | **Built** | Idempotency keys, authN/Z, high-availability service, latency SLO inside the payment timeout |
| **ExternalFraudIntelProvider** | Bank fraud team | Registry responses (status, score, reason codes, source, timestamp) | Per intent (cached) | DPIP, MuleHunter deployment, I4C suspect registry, DoT FRI — via whatever access the bank legitimately has | External dimension score | **Simulated** (`LocalRegistryProvider`, local table) | Real adapters with contracts, freshness/SLA handling, fallback when unavailable, provenance in audit |
| **PathGraph** | Bank | Settled postings (own customers), devices | Updated per posting | Core banking ledger / event stream | In-memory graph for queries | **Built** (single process) | Partitioned graph store or streaming windows; retention policy |
| **RingWatch** | Bank fraud analytics | PathGraph windows, labels, attributable value | Per intent (recipient) and post-posting | EFRMS case management | Network signals with evidence | **Built** (rules) | Tune on real outcomes; segment-specific thresholds; MuleHunter score as an input |
| **TaintTrace** | Bank fraud ops / disputes | Postings + confirmed incident labels | On label (and on demand) | 1930/NCRP-driven incident workflow, CFCFRMS holds | Amount attributable per account under LIBR / pro rata, with derivation | **Built** (vendored PRIMA lineage engine) | Cross-bank coverage needs shared infrastructure (DPIP/CFCFRMS); legal review of rule choice |
| **TrailScore** | Bank digital channel | Session/journey events (device, payee, limit, credentials) | Per intent | Mobile banking telemetry, device binding | Sequence signals | **Built** (events injected in demo) | Real event feeds with consent; tune windows |
| **Behaviour** | Bank | Customer's payment history | Per intent | Core banking | Behaviour signals | **Built** | Larger history, seasonality, cold-start policy |
| **ContextFlag** | Bank (only with legitimate, consented upstream signal) | Category flags from an upstream channel | Per intent | Telecom/OS-level scam-call signals where lawful and consented | Context signals | **Simulated** (operator-supplied text) | A real, lawful signal source; never content interception |
| **Risk fusion + Interrupt ladder** | Bank risk policy owners | Dimension scores, policy file | Per intent | Policy governance | Tier + intervention, named adjustments | **Built** (hand-set weights) | Calibrated on outcomes; change control and approvals for policy versions |
| **ReasonLine** | Bank | Decision record | Per intervention | App UI, analyst console, audit store | Customer / analyst / audit text | **Built** (deterministic templates) | Language localisation (Hindi + regional), accessibility review, legal sign-off on wording |
| **ScopedHold** | Bank | Intent amount | Tier ≥ 3 | Payments hub | Amount-scoped hold with review window | **Built** (simulated review) | Real hold semantics in the payments hub; SLA for review; customer comms |
| **CircuitBreaker** | Bank | Pre-nominated trusted contact (customer consent) | Tier 4 | Notification service (SMS/push) | Facts-only alert, contact response | **Built** (WebSocket to a browser/phone on LAN) | Consent capture and revocation, verified contact channel, abuse safeguards |
| **PaymentProvider** | Bank/PSP | Approved intent | After approval | UPI/IMPS rails | Payment execution | **Built**: provider port + simulated rail | Real rail integration owned by the bank/PSP |

## 4. Adoption path: shadow first

1. **Shadow mode** — the bank calls Vigil for every intent but keeps its existing controls in charge. Vigil records what it *would* have done next to the bank's baseline decision (Governance → Shadow comparison).
2. **Measure** — would-be interventions vs confirmed outcomes: catch rate, false-challenge rate, value that would have been held, latency.
3. **Enable tiers gradually** — Tier 1 (inform) first, then confirm-purpose, then scoped holds; CircuitBreaker last, after trusted-contact consent flows exist.
4. **Govern** — every decision record carries the policy version, provenance and model versions; policy changes are versioned and reviewable; models remain corroborating evidence until validated on real outcomes.

## 5. One-line pitch

> *India already has sophisticated detection — bank EFRMS, MuleHunter and DPIP. Vigil is the layer that converts those signals, plus local journey and network evidence, into an explainable, proportionate intervention at the last reversible moment — and then learns from where the money went.*
