# Model Card — what decides, what was removed, and why

**Summary: Vigil has no machine-learning model on its decision path.** Decisions come from transparent, versioned rules and robust statistics (`config/risk_policy.yaml`), fused with hand-set weights. This is a deliberate downgrade from the earlier prototypes, made because their models could not establish anything about real fraud. Every decision record states `"ml_models_used": []`.

---

## 1. Models found in the source projects

### 1.1 RandomForest `fraud_model.pkl` (ccmule-main, "Actual ML - Laggy")

| Question | Finding |
|---|---|
| Training data | `training.build_multi_run_dataset()`: 20 runs of the project's own random simulator; each run injects one attack from `attacks.py`. Fully **synthetic**. |
| Target | `is_fraud` = 1 for exactly the accounts the attack injector touched in that run. |
| Features | in/out degree, total in/out amount, retention ratio, unique neighbours, unique channels, device-cluster size, transaction count — computed **only over transactions after `attack_time`**. |
| Split | Random 70/30 `train_test_split` across pooled rows from the same generator (stratified when possible). No temporal split, no held-out generator, no held-out attack type. |
| Leakage | Severe. Features are measured on the attack window, where (by construction) the injected accounts are almost the only ones with in/out degree ≥ 2, high totals and low retention. The model learns *"was touched by the injector"* — i.e. the generator's own rules. Test rows come from the same runs/generator as training rows. |
| Imbalance | `class_weight="balanced"`. |
| Metrics | The repo prints a classification report during training but stores none. Any near-perfect score it shows is an artefact of the leakage above, so we did not re-measure it. |
| Calibration | None. `predict_proba` was blended (0.5/0.3/0.2) with a normalised rule score and the GNN score, then thresholded with a "self-adjusting" threshold driven by precision/recall **computed against ground truth at runtime** — impossible in production. |
| In production path? | ccmule's FastAPI/Sentinel UI: **no** (only the Streamlit UI loaded it). "Laggy" `api.py`: **yes**, loaded and run on every scoring call. |

### 1.2 GAT (graph attention network) `gnn_model.pth`

| Question | Finding |
|---|---|
| Training data / target | `train_gnn.py`: 40 simulator runs, same `is_fraud` target, focal loss. Synthetic. |
| Features | The same 9 structural features + `account_age_days`. |
| Leakage | Same as above; plus node features already encode the target-defining structure. |
| Metrics / calibration | Not stored; not calibrated. |
| In production path? | PRIMA's RingWatch gave it **45 % of the network score**, rebuilding a 2-hop subgraph and running torch on CPU **per request** (cold import of torch + torch-geometric ≈ seconds). |

### 1.3 SHAP, adaptive threshold, "PatternMemory" (`risk_memory.py`)

SHAP explained the leaky RandomForest. The adaptive threshold and PatternMemory both read ground-truth labels at runtime. None of these can be justified on a decision path.

## 2. Decision taken

| Option from the brief | Applied to |
|---|---|
| A. fix cheaply | — (no real labelled data exists to fix them with) |
| B. downgrade to supporting score | — (a leaky score is not "supporting evidence") |
| **C. remove from the critical path** | **RandomForest, GAT, SHAP, adaptive threshold, PatternMemory** |

They were not ported. Torch, torch-geometric, scikit-learn and shap are not dependencies of Vigil.

## 3. What Vigil uses instead

| Dimension | Method | Can establish | Cannot establish |
|---|---|---|---|
| Network (RingWatch) | Time-windowed (72 h) structural rules on the recipient: first-time-sender fan-in, rapid pass-through, fan-out, circular flow, smurfing, velocity chain, shared device, dormant wake, new-account inflow, proximity to confirmed scam accounts, value traced from confirmed scams | That an account's recent money flow has the *shape* commonly associated with collection/layering | Intent, ownership, or that the account is a mule |
| Journey (TrailScore) | Ordered events in a 30-min window (new device → new payee → limit raised → large transfer) | That the sender's account went through a takeover/coercion-shaped sequence | Who was operating the device; whether the customer is coerced |
| Behaviour | Median/MAD robust z-score of amount vs the sender's 6-month history; first-time payee; balance fraction; new-payee burst; velocity; dormancy; odd hour | That *this* payment is unusual *for this customer* | That unusual means wrong (see false-positive control, Scenario 4) |
| Context (ContextFlag) | Keyword-stem lexicon over **simulated** context text in 5 categories | That the supplied text contains pressure patterns | Anything about real calls/messages — Vigil cannot see them |
| External | Registry lookup via `ExternalFraudIntelProvider` (local, **simulated**) | What an institutional feed would say | Truth of that feed |
| TaintTrace | Vendored PRIMA lineage engine: LIBR and pro-rata parcel tracing, exact conservation, property-tested | How much of an account's balance is *attributable under a named rule* to a confirmed incident | That specific rupees moved; legal ownership |

Fusion: `base = Σ weight × dimension score`, plus a corroboration bonus when ≥ 2 independent dimensions are strong, plus named floors/caps. Weights and thresholds are **hand-set, versioned demo values** — not fitted, not validated.

## 4. Synthetic-data limitation

All data is generated by `backend/vigil/sim/seed.py` (fixed seed 20261006) and the scenario injectors. The thresholds were chosen so the five reproducible scenarios behave as designed **and** ordinary seeded accounts stay quiet. That proves internal consistency and explainability, not real-world precision or recall. No real transaction, victim, or bank data was used.

## 5. Metrics we can honestly report

| Check | Result (deterministic seed) |
|---|---|
| Scenario 0 normal payment | Tier 0 |
| Scenario 1 risky recipient | Tier 2 (score 0.34) |
| Scenario 1 after mule ring + confirmed label | Tier 3 (score 0.58 would be Tier 4; `CAP_NO_SENDER_EVIDENCE` keeps it at a scoped hold) |
| Scenario 3 coercion | Tier 4 (score 0.64), CircuitBreaker fired |
| Scenario 4 false-positive control (₹1.2 L to landlord) | Tier 0 — amount anomaly noted, no friction |
| Accounts with any network score before ring injection | Only `kiran.traders` (0.45, by design: the Act 2 recipient) |
| Ordinary (`legit`) accounts with network score ≥ 0.4 after ring injection + label | none; the five victims score 0 (paying into a scam account is not evidence against you) |
| TaintTrace conservation (LIBR, pro rata) | exact (`attributable + left perimeter + no-longer-attributable = origin`) |
| Risk-evaluation latency | p95 ≈ 1 ms (see `docs/BENCHMARK_RESULTS.md`) |

These are **behavioural acceptance checks**, enforced by `backend/tests/test_vigil_lifecycle.py`, not statistical performance metrics.

## 6. Known failure modes

* **Legitimate collection accounts** (small businesses, event organisers, chit funds) receive from many first-time senders and may forward quickly → network evidence fires. Mitigation: it is one dimension of five; friction guard for established payees; analyst review at Tier 3.
* **Slow mules** that hold funds longer than 60 minutes evade `NET_PASS_THROUGH`.
* **Patient takeovers** that space steps beyond the 30-minute window evade the ordered-chain bonus.
* **Context** depends entirely on an upstream signal existing; without it, coercion relies on journey + behaviour.
* **Registry errors** propagate: a wrong `confirmed_mule` status floors the decision at Tier 3.
* **Cold-start customers** have no behaviour baseline (behaviour rules need ≥ 5 past payments).
* **Weights are not learned.** With real labelled outcomes, the right next step is calibrating weights/thresholds offline (e.g. logistic regression over the same interpretable signals) and keeping the rule evidence as the explanation.

## 7. What a credible ML step would look like (roadmap, not built)

Train on real, bank-confirmed outcomes with a temporal split; features restricted to information available at commit time; evaluate per-segment precision at fixed intervention budgets (false-challenge rate as a first-class metric); calibrate probabilities; keep the model as one versioned, monitored input to fusion with rule evidence still rendered for every decision.

---

## Appendix A (2026-10-07, detection intelligence v2.1): models restored as corroborating evidence only

*Appended by Claude 2. Sections 1–7 above still describe the payment decision path accurately and are unchanged.* The RandomForest and GAT have been **repaired, retrained and re-validated** on synthetic worlds. They are shown **beside** each decision as `model_evidence`, together with SHAP, behavioural drift, pattern memory, early warning, the windowed rule engine and a detector-consensus count.

**The payment tier still comes only from the transparent policy engine.** Every decision record still says `ml_models_used: []`, and lists model outputs separately under `model_evidence_not_used_for_tier`. A test (`test_intel_consensus.py::test_model_evidence_is_never_fused_into_the_tier`) checks that score and tier are identical with and without the models.

These are now **optional** dependencies (`backend/requirements-ml.txt`). Without them the platform runs, and RF, GNN and SHAP report `status="unavailable"`. The full audit, protocol and metrics are in `docs/ML_VALIDATION_REPORT.md`.

| Model / family | Version | What it is | Value shown (`kind`) | Test worlds, **SYNTHETIC VALIDATION** (P / R / PR-AUC) | Main known failure |
|---|---|---|---|---|---|
| Random Forest | `rf-v2.1` | 100 trees on 15 windowed features; numpy serving; SHAP TreeExplainer | isotonic-calibrated probability (`probability_calibrated`, "calibrated on synthetic worlds"); raw score in `detail` | 0.93 / 0.85 / 0.92 | unseen smurfing (recall 0.28) and dormant (0.50) |
| GNN (relational GAT) | `gnn-gat-v2.1` | 2 layers, sender→recipient and recipient→sender attention, plain torch training, numpy serving on the live 72 h graph | `probability_calibrated` | 0.98 / 0.91 / 0.95 | **does not generalise to unseen families**: shared device 0.17, volume spike 0.00, dormant 0.30, smurfing 0.34 |
| Rule engine | `rules-v2.0` | the original six rules, 72 h-windowed, hand-set thresholds | points (`score`) | 0.26 / 0.35 / 0.19 | merchants and small traders |
| Early warning | `early-warning-v2.0` | population-relative, ≥ 2 signals, top 8 % | anomaly `score` | 0.29 / 0.63 / 0.28 | merchants and traders |
| Behavioural drift | `drift-v2.1` | change against the account's own 45-day baseline; HIGH needs ≥ 2 changed features | `level` | 0.57 / 0.76 / 0.66 | event organisers; victims after a large unusual payment |
| Pattern memory | `pattern-memory-v2.1` | structural prototypes of the 10 families, built offline from **training** worlds; no labels at runtime | `similarity` ("not criminal attribution") | 0.83 / 0.46 / 0.66 | low recall on fan-out and cross-channel |

**Intended use:** analyst-facing corroboration and explanation, side by side with RingWatch and the SIMULATED registry, with an explicit agreement count ("5 of 8 signal families agree").

**Not intended for:** authorising, blocking or holding a payment; labelling a customer as a mule; quoting accuracy for real banks.

**Data:** synthetic only. The training generator (`ml/datagen.py`) is not the demo world's generator (`vigil/sim/seed.py`). On the seeded demo world only the two seeded pass-through accounts are corroborated, and after the mule-ring scenario the ring is flagged by 4–6 of the 6 families. Those are acceptance checks, not accuracy evidence.

**Two corrections in v2.1 came from wiring the models to the live world:**
* **Payday calendar in the generator.** Salaries inside the evaluation window had made the GNN flag salary receivers.
* **Drift baseline and breadth rule.** A monthly salary alone had driven drift to HIGH.

Both are generic realism or robustness fixes and were re-validated only on held-out worlds. See `ML_VALIDATION_REPORT.md` §2.1.

**What would make this credible:** the roadmap in §7 still applies. Real, bank-confirmed outcomes, a temporal split, alert-budget precision, and re-calibration on real data.
