# ML Validation Report: Detection Intelligence v2

> **SYNTHETIC VALIDATION.** Every number in this report comes from computer-generated transaction worlds. None of it is a measurement of real-bank accuracy, and none of it may be quoted as one.

Owner: Claude 2 (ML / detection intelligence). Scope: `backend/vigil/intel/**`, `backend/ml/**`, `backend/models/**`.
Operational status: all models here produce **corroborating evidence only**. Payment authorisation stays with the transparent policy engine (`risk/*` + `config/risk_policy.yaml`). See `docs/archive/plans/FINAL_PARALLEL_PLAN.md` §5.

---

## 1. Audit of the original RandomForest and GAT

Audited source: `Indian Bank Project/Indian Bank Project - End half sim - half actual/backend/` (the latest version). `ccmule-main/ccmule-main/backend/` and `CROSS-CHANNEL-MONEY-MULE-DETECTION-streamlit version/backend/` contain byte-identical `training.py`, `features.py`, `detection.py`, `attacks.py`, `gnn.py`, `train_gnn.py`, `generator.py` and `risk_memory.py`. Only `config.py` differs (`MAX_TX_MEMORY`). The findings therefore apply to all three copies. Below, line references use `<file>:<line>` within that `backend/` folder.

No metrics were ever stored. `train_model.py:13-14` prints a confusion matrix, `training.py:105` builds a `classification_report` that is never saved, and `train_gnn.py:271-298` prints P/R/F1 on the **full dataset including training graphs**. Any near-perfect number shown in the old UI or slides cannot be reproduced and, as shown below, would be a leakage artefact.

### 1.1 Findings (most severe first)

| # | Issue | Evidence | Effect |
|---|---|---|---|
| A1 | **Attack-window shortcut / generator leakage** | `generator.py:75` stamps every background transaction `datetime.now()` at generation time. Each attack sets `base_time = datetime.now()` *afterwards* (e.g. `attacks.py:57`). `training.py:30-31` and `train_gnn.py:92-93` keep only `timestamp >= attack_time`. | The training graph contains (almost) only injected transactions. `features.py:17-21` still adds all 500 accounts as nodes, so every non-attack account has all-zero flow features. The model learns *"has any edge in the window"* ≈ *"was touched by the injector"*. |
| A2 | **Labels are "touched by the injector", and victims are labelled as mules** | `attacks.py:99-101` labels the fan-in **feeders** (the people paying the mule) as fraud. `attacks.py:148-150` labels fan-out recipients, `attacks.py:461-462` the smurfing receiver, `attacks.py:383` creates the spike account with `is_fraud=1`. The fan-in exit counterparty (`attacks.py:83`) is *not* labelled. | The target is not "mule". It mixes victims, mules and bystanders, and one structurally identical endpoint is labelled negative. A score trained on it cannot be read as mule likelihood. |
| A3 | **Same simulation in train and test (row-level split)** | `training.py:50` shuffles pooled rows from all runs. `training.py:75-81` does a random 70/30 `train_test_split`. | Rows from the *same run and the same attack instance* (e.g. five feeders of one fan-in) land on both sides. There is no split by run and no held-out attack family, so nothing measures generalisation. |
| A4 | **Unrealistic background (no hard negatives) and amount separation** | `config.py:4` `NUM_TRANSACTIONS = 20` background transactions for 500 accounts. `generator.py:66` background amounts are 500–8,000. Attack amounts are 15,000–80,000 (`attacks.py:63,131,168,211,257,310,350,404,488`). | Amount alone separates the classes. The data has no merchants, payroll, recurring payees, legitimate high-value payments or event collections, which are exactly the accounts that make mule detection hard. |
| A5 | **Device feature inverted by the generator** | `generator.py:14,29` draws devices from a pool of `max(25, N/10) = 50`, so about 10 accounts share every device. The shared-device attack (`attacks.py:298-303`) gives 4 accounts device `D999`. | `device_cluster_size > 2` (`detection.py:41`, +3 rule points) fires for almost everyone. An attack cluster (4) is *smaller* than a normal one (~10). |
| A6 | **Unrealistic class balance, wrong metrics** | 500 nodes per run, 2–8 positives. `class_weight="balanced"` (`training.py:95`). Only accuracy-like summaries are printed. | Prevalence is about 1% here and far lower in reality. Without PR-AUC or precision at a fixed alert budget, the printed figures say nothing about alert quality. |
| A7 | **GAT: transductive scaling leakage** | `gnn.py:155-158` min-max normalises the features **per graph snapshot at inference**. | An account's score depends on who else is in the snapshot. No train-fitted scaler exists, so train and serve transforms differ. |
| A8 | **GAT: no test set; training graphs in the reported metric** | `train_gnn.py:174-176` splits 80/20 by list position. Attack families cycle (`attack_index % 10`), so every family appears in train and val. Val loss selects the checkpoint, then `train_gnn.py:271-298` evaluates "Final Evaluation (full dataset)" over train and val together. | The reported P/R/F1 are mostly training-set numbers. Same shortcut as A1 (attack-window graph). |
| A9 | **Runtime label leakage in the live engine** | `realtime_engine.py:412-413` adds `signals["attack"] = 0.58` when a transaction carries `is_attack`. `realtime_engine.py:283-294` (`_sync_flags`) forces labelled accounts to risk ≥ 0.97 / status "fraud". | The live risk score is told the answer. |
| A10 | **Adaptive threshold and validation read ground truth at runtime** | `api.py:716-727` computes precision/recall against `ground_truth_ids` and feeds `adaptive_threshold_update` (`detection.py:456-473`). `api.py:360-380` (`_validated_attack_ids`) intersects predictions with the endpoints of attack transactions. | The threshold "learns" from labels that production never has. Predictions are filtered to attack endpoints, so false positives are removed by construction and the displayed precision is inflated. |
| A11 | **Pattern memory reads labels** | `risk_memory.py:14` builds the signature from nodes with `is_fraud == 1`. `risk_memory.py:61` stores it after every run. | Similarity is computed between ground-truth clusters, so this is not detection. `risk_memory.py:79-81` normalises by the *past* value (asymmetric, unstable near 0). |
| A12 | **Behavioural drift bug** | `detection.py:424-432` standardises using the mean/std of just the two vectors (baseline, current). With two points each changed feature becomes exactly ±1. | `drift_score = 2·sqrt(#features that changed)`, regardless of magnitude: 2→3 transactions scores the same as 2→200. The baseline is the first ≥ 30 transactions of the session (`api.py:244-259`). |
| A13 | **Fusion of uncalibrated, batch-relative quantities** | `detection.py:139-152` normalises rule points by the max in the current batch and blends 0.5·RF + 0.3·rules + 0.2·GNN. | An account's fused score changes with unrelated accounts. None of the three terms is a probability. |
| A14 | **Non-determinism** | Unseeded `random` / `np.random` in `generator.py` and `attacks.py:_pick_weighted`. `features.py:214` ages accounts against wall clock (`pd.Timestamp.now()`). Only the split and the forest are seeded (`training.py:78,94`). | Datasets and therefore models cannot be reproduced. |
| A15 | **Rule thresholds are unwindowed and fire on any activity** | `detection.py:26-53`: `in_degree >= 2`, `out_degree >= 2`, `transaction_count >= 3`. | On a realistic history almost every active customer scores. They only looked selective because the old graphs were attack-window graphs (A1). |
| A16 | **SHAP explained the leaky model; categories double-count** | `detection.py:115` and `158-201` (`out_degree` appears in both Velocity and Ring Participation). | The explanation was faithful to a model that had learned the generator, not mule behaviour. |

### 1.2 What survives

The **feature vocabulary** (degrees, totals, retention, neighbours, channels, device cluster, transaction count, account age), the **ten attack families**, the **population-relative early-warning idea** (top-% plus ≥ 2 signals), the **role vocabulary** (coordinator / collector / distributor / entry / exit) and the **drift concept** (baseline versus current) are all sound. The protocol around them was what failed. v2 keeps these ideas and repairs the protocol:

| Old failure | v2 repair |
|---|---|
| A1 attack-window features | One windowed feature function (`vigil/intel/features.py`). The window is anchored at the **evaluation time**, which is offset randomly from attack start, and background traffic keeps flowing through the window. |
| A2 label = touched | Labels are **mule / not mule**. Victims and bystanders are negatives. Roles are recorded where meaningful. |
| A3 row split | **Split by world** (train / val / test worlds disjoint), plus a **leave-one-attack-family-out** experiment. |
| A4 easy negatives | Merchants with many recurring senders, payroll fan-out, settlement sweeps, legitimate high-value payments, event collections, family shared devices, dormant-but-legitimate reactivations. Attack amounts overlap background amounts. |
| A5 device pool | Devices are personal by default. Legitimate sharing is limited to small households. |
| A6 metrics | PR-AUC, ROC-AUC, precision/recall/F1 at a threshold chosen on validation worlds, confusion matrix, calibration (reliability bins + Brier), per-attack recall. |
| A7 snapshot scaling | Scaler fitted on **training worlds only**, stored with the model, used identically at inference. |
| A8 no test set | Early stopping on validation worlds. All reported numbers come from untouched test worlds. |
| A9–A11 runtime labels | No runtime component reads `seed_role`, `seed_attack` or labels. Pattern signatures are built offline from training worlds and versioned in `backend/models/`. |
| A12 drift bug | Per-feature scales fitted on training-world populations. The drift score is magnitude-aware and window-length-normalised. |
| A13 fusion | Nothing is fused into the payment tier. Detectors are shown side by side with a **consensus count**, each with an honest `kind`. |
| A14 non-determinism | Seeded worlds (`seed + world index`), seeded models, `torch` single-thread deterministic training. |

---

## 2. Protocol (v2.1)

> Everything from here on is **SYNTHETIC VALIDATION**: measured on computer-generated worlds, never on real bank data.

| Item | Value |
|---|---|
| Generator | `backend/ml/datagen.py` v2.1. 150 independent worlds, each fully determined by `(seed 20261006, world index)`. Every world has 220–320 customers, 8–14 merchants and 2–4 payroll companies, 60 days of history, and 2–4 attack instances drawn from the 10 families. |
| Background (hard negatives) | Salaries, both external and internal payroll fan-out, on a **world-level payday calendar**. Also recurring payees, bills, ATM use, merchants with many regular senders plus daily settlement sweeps, small traders who sweep takings, landlords collecting rent, event organisers paid by many first-time senders, legitimate high-value payments, legitimate lump-sum pass-throughs, family shared devices, dormant-but-legitimate reactivations, and very young legitimate accounts. |
| Labels | Mule / not mule. Victims, feeders and bystanders are **negatives**. A role is recorded where the generator defines one. |
| Evaluation time | Fixed per world. Each attack starts uniformly 15 min to 72 h before it, so an attack may be partly outside the 72 h window or still in progress. This removes the attack-window shortcut (A1). |
| Split | **By world**: 90 train, 30 validation and 30 test worlds, all disjoint. Thresholds, isotonic calibration, GNN early stopping, drift cut-offs and the pattern-memory threshold use train or validation worlds only. **Every number below comes from the 30 untouched test worlds** (8,846 accounts, 310 mules, prevalence 3.5%). |
| Generalisation | Leave-one-attack-family-out (LOAO): the RF and the GNN are retrained ten times, each time without one family's mules, then scored on that unseen family in the test worlds (§6). |
| Features | One windowed extractor (`vigil/intel/features.py`, 15 features) is used **unchanged** for training worlds and for the live graph. A test enforces this. |
| Models | RandomForest (100 trees, depth 10, `balanced_subsample`), isotonic-calibrated on validation worlds. A 2-layer relational GAT in plain torch (sender→recipient and recipient→sender attention, 4 heads, hidden 32), also isotonic-calibrated. Both are served by numpy ports, verified equal to sklearn to 2e-16 and to torch to 1e-7. |
| Thresholds | RF 0.588 and GNN 0.474 on the calibrated scale, pattern memory 0.724 similarity. Each is the max-F1 point on validation worlds. Rules (≥ 4 of 12 points) and early warning (≥ 2 signals, top 8 % of the population, score ≥ 0.15) are set a priori, not tuned. Drift HIGH sits at the 98th percentile of training-world non-mules and also needs ≥ 2 changed features. |

### 2.1 What changed in run 3, and why (honest note)

The run-2 models (generator v2.0) were wired to the live demo world for the first time in run 3. On the **seeded, unattacked** world the GNN flagged 9 ordinary customers (raw score ≈ 0.99) and drift flagged 18 as HIGH, out of 139 scored accounts. Those counts exclude the two seeded pass-through accounts. The cause was a distribution gap, not an attack signal. In the live world **every** salary was credited 1–3 days before "now", inside the 72 h window. The v2.0 generator almost never put a salary inside the evaluation window, and the 30-day drift baseline usually missed last month's salary.

Two generic repairs were made. Neither looks at the demo accounts or their labels:

1. **Generator v2.1, payday calendar.** About 80 % of salaried customers and 70 % of payroll companies pay around a common world-level day of the month. In roughly 1 world in 10 the evaluation window therefore sits just after payday.
2. **Drift v2.1.** The baseline is 45 days (more than one monthly cycle) instead of 30. Each feature's change is capped at 4. HIGH also needs **breadth**: at least 2 features changed by at least 1 scale unit. One large credit can therefore reach MEDIUM at most.

All thresholds were then re-fitted on train and validation worlds only, and the test-world numbers below were recomputed. The risk is that a fix motivated by looking at the demo world flatters the demo. It is mitigated because both changes are realism or robustness fixes that apply to any world. It is not removed: the live-world checks in §10 are **behavioural acceptance checks**, not independent evidence of accuracy.

## 3. Headline results: test worlds (SYNTHETIC VALIDATION)

| Detector | Precision | Recall | F1 | ROC-AUC | PR-AUC | Flag rate | TP | FP | FN | TN |
|---|---|---|---|---|---|---|---|---|---|---|
| Rules (windowed, hand-set) | 0.26 | 0.35 | 0.30 | 0.82 | 0.19 | 4.7% | 108 | 304 | 202 | 8232 |
| Early warning | 0.29 | 0.63 | 0.40 | 0.89 | 0.28 | 7.6% | 194 | 478 | 116 | 8058 |
| Behavioural drift (HIGH) | 0.57 | 0.76 | 0.65 | 0.95 | 0.66 | 4.7% | 236 | 178 | 74 | 8358 |
| Pattern memory | 0.83 | 0.46 | 0.59 | 0.92 | 0.66 | 1.9% | 143 | 29 | 167 | 8507 |
| Random Forest (calibrated) | 0.93 | 0.85 | 0.88 | 0.98 | 0.92 | 3.2% | 262 | 21 | 48 | 8515 |
| GNN (GAT, calibrated) | **0.98** | **0.91** | **0.94** | 0.98 | **0.95** | 3.2% | 282 | 5 | 28 | 8531 |
| Consensus ≥ 3 of the 6 families | 0.85 | 0.78 | 0.81 | 0.96 | 0.82 | 3.2% | 241 | 43 | 69 | 8493 |
| Agreement ≥ moderate, as shown in the UI (consensus-v2.1, run 4, §7) | 0.88 | 0.86 | 0.87 | — | — | 3.4% | 266 | 38 | 44 | 8498 |

How to read this:
* **The learned models beat the rules by a wide margin on these worlds.** The rules' PR-AUC is 0.19 against 0.92 for the RF and 0.95 for the GNN. The rules' false positives are mostly merchants (199 of 331 flagged) and small traders (76 of 470), which are exactly the hard negatives. The windowed rules are still a large improvement on the original unwindowed ones, which fired on almost every active account (A15).
* **These numbers are optimistic.** Train and test worlds come from the same generator, which a real deployment never has. The models learn this generator's notion of a mule. §6 shows how quickly they degrade on a family they have not seen, and that is the better guide to real-world behaviour.
* **The consensus count trades recall for robustness.** 3-of-6 is less precise than the GNN alone on in-distribution worlds. It is the operational display because it does not depend on any single model being right.
* **The agreement level the UI shows** is not "≥ 3 of 6". It is the consensus-v2.1 level: 2 or more flagging families, at least one of them a structural or model family (§7). Under the run-3 rule (raw count, no cap) the same "≥ moderate" line had precision 0.44 at recall 0.865, with 197 merchants among its 341 false positives.
* A flag rate of 3.2 % is **not** a deployable alert rate. Prevalence in these worlds (3.5 %) is orders of magnitude above real mule prevalence.

## 4. Per-attack recall on test worlds (SYNTHETIC VALIDATION)

| Attack family | Test mules | Rules | Early warning | Drift | Pattern | RF | GNN | Consensus ≥ 3 |
|---|---|---|---|---|---|---|---|---|
| fan_in | 10 | 0.70 | 0.70 | 0.90 | 0.40 | 0.80 | 0.70 | 0.90 |
| fan_out | 84 | 0.19 | 0.46 | 0.61 | 0.18 | 0.75 | 0.89 | 0.63 |
| circular | 46 | 0.09 | 0.67 | 0.93 | 0.63 | 1.00 | 0.98 | 0.98 |
| velocity_chain | 36 | 0.08 | 0.72 | 0.94 | 0.72 | 1.00 | 0.97 | 0.97 |
| cross_channel | 29 | 0.21 | 0.45 | 0.48 | 0.28 | 0.79 | 0.90 | 0.48 |
| shared_device | 52 | 0.92 | 1.00 | 1.00 | 0.73 | 0.96 | 1.00 | 1.00 |
| behavioural_drift | 7 | 1.00 | 1.00 | 1.00 | 0.57 | 0.86 | 1.00 | 1.00 |
| volume_spike | 7 | 0.86 | 0.86 | 0.86 | 0.86 | 1.00 | 0.86 | 0.86 |
| smurfing | 29 | 0.21 | 0.34 | 0.45 | 0.31 | 0.48 | 0.69 | 0.45 |
| dormant | 10 | 0.50 | 0.30 | 0.70 | 0.40 | 0.90 | 0.90 | 0.70 |

Several families have under 30 test mules (fan_in, behavioural_drift, volume_spike and dormant have 7–10), so their recall carries roughly ±0.15–0.3 of sampling noise. **Smurfing is the weakest family for every detector.** The structuring band is narrow, recipients are often recruited accounts with normal history, and 25 % of smurfing instances use small amounts that are not near-threshold. Fan-out exits and cross-channel exits are frequently missed by the rule-based families.

Per-attack PR-AUC against all negatives is below. It does not depend on a threshold.

| Family | Rules | RF | GNN |
|---|---|---|---|
| fan_in | 0.02 | 0.82 | 0.68 |
| fan_out | 0.04 | 0.77 | 0.92 |
| circular | 0.03 | 0.98 | 0.98 |
| velocity_chain | 0.03 | 0.99 | 0.99 |
| cross_channel | 0.09 | 0.82 | 0.94 |
| shared_device | 0.16 | 0.96 | 1.00 |
| behavioural_drift | 0.09 | 0.82 | 0.96 |
| volume_spike | 0.03 | 0.81 | 0.62 |
| smurfing | 0.01 | 0.46 | 0.72 |
| dormant | 0.02 | 0.61 | 0.83 |

## 5. Calibration (test worlds)

| Model | Brier, raw | ECE, raw | Brier, calibrated | ECE, calibrated |
|---|---|---|---|---|
| Random Forest | 0.0121 | 0.029 | 0.0065 | 0.002 |
| GNN (GAT) | 0.0078 | 0.018 | 0.0033 | 0.001 |

Raw RF `predict_proba` is badly over-confident in the middle of its range. Accounts scored 0.3–0.4 are mules 7 % of the time, and accounts scored 0.6–0.7 are mules 14 % of the time. That is expected with `balanced_subsample` class weighting. Isotonic regression fitted on validation worlds corrects it on test worlds. For example, the calibrated 0.7–0.8 bin has 22 accounts and 77 % are mules. The calibrated bins are sparse between 0.3 and 0.7, because isotonic maps produce steps.

The API therefore reports `kind="probability_calibrated"` with the caveat **"calibrated on synthetic worlds — not a real-world probability"**, and it also returns the raw score (`raw_kind="probability_uncalibrated"`). SHAP explains the **raw** RF output, `prediction_kind="probability_uncalibrated"`. Calibration is only as good as the match between validation worlds and the world it is applied to. On real data it would have to be re-fitted on labelled outcomes.

## 6. Leave-one-attack-family-out (generalisation to an unseen family)

The default run (`python ml/train_all.py`) retrains the RF with the same parameters, and the GNN with a reduced budget of **at most 20 epochs, early-stopping patience 6** (the main GNN uses 120 / 15). That budget keeps the whole run under 10 minutes. Recall uses the threshold chosen on validation worlds without the held-out family. "Seen" is the main model's recall on the same family.

| Held-out family | Test mules | RF recall unseen | RF recall seen | RF PR-AUC unseen | GNN recall unseen | GNN recall seen | GNN PR-AUC unseen | Rules recall |
|---|---|---|---|---|---|---|---|---|
| fan_in | 10 | 0.70 | 0.80 | 0.72 | 0.30 | 0.70 | 0.33 | 0.70 |
| fan_out | 84 | 0.68 | 0.75 | 0.76 | 0.57 | 0.89 | 0.67 | 0.19 |
| circular | 46 | 1.00 | 1.00 | 0.97 | 0.96 | 0.98 | 0.97 | 0.09 |
| velocity_chain | 36 | 1.00 | 1.00 | 0.98 | 0.94 | 0.97 | 0.98 | 0.08 |
| cross_channel | 29 | 0.79 | 0.79 | 0.80 | 0.76 | 0.90 | 0.82 | 0.21 |
| shared_device | 52 | 0.90 | 0.96 | 0.92 | **0.17** | 1.00 | 0.25 | 0.92 |
| behavioural_drift | 7 | 0.86 | 0.86 | 0.70 | **0.43** | 1.00 | 0.27 | 1.00 |
| volume_spike | 7 | 0.71 | 1.00 | 0.43 | **0.00** | 0.86 | 0.01 | 0.86 |
| smurfing | 29 | **0.28** | 0.48 | 0.30 | **0.34** | 0.69 | 0.34 | 0.21 |
| dormant | 10 | **0.50** | 0.90 | 0.24 | **0.30** | 0.90 | 0.12 | 0.50 |

What this shows:
* **The GNN does not generalise to unseen shared-device clusters (0.17), volume spikes (0.00), behavioural drift (0.43), dormant activation (0.30), smurfing (0.34) or fan-in (0.30).** Its very high in-distribution numbers in §3 come largely from having seen each family. Run 2 found the same failure with a different generator and a 60-epoch budget: shared_device 0.00, smurfing 0.13, dormant 0.14. The weakness is therefore not an artefact of the reduced budget.
* **The RF degrades more gracefully.** It holds on circular, velocity chain, cross-channel and shared device, but loses half its recall on dormant (0.50) and smurfing (0.28).
* **The hand-set rules do not depend on training data.** On shared device, behavioural drift, volume spike and dormant they match or beat the unseen-family models. That is the argument for showing rules and models side by side instead of replacing one with the other.
* **Practical reading:** a new attack shape will be caught first by whichever transparent family happens to describe it (rules, drift, early warning, RingWatch). Treat the models as corroboration, not as a detector of novel schemes.

**Effect of the reduced GNN budget.** A separate run, `python ml/train_all.py --full-loao` (7 min 15 s wall, `models/validation_v2_full_loao.json`), retrains the GNN with **60 epochs and patience 15**. The main models are identical in both runs. Only the LOAO GNN changes:

| Held-out family | GNN recall unseen, 20 ep (default) | GNN recall unseen, 60 ep | GNN PR-AUC unseen, 20 ep | GNN PR-AUC unseen, 60 ep |
|---|---|---|---|---|
| fan_in | 0.30 | 0.40 | 0.33 | 0.48 |
| fan_out | 0.57 | 0.68 | 0.67 | 0.83 |
| circular | 0.96 | 0.98 | 0.97 | 0.98 |
| velocity_chain | 0.94 | 0.94 | 0.98 | 0.98 |
| cross_channel | 0.76 | 0.76 | 0.82 | 0.81 |
| shared_device | 0.17 | 0.21 | 0.25 | 0.24 |
| behavioural_drift | 0.43 | 0.57 | 0.27 | 0.24 |
| volume_spike | 0.00 | 0.00 | 0.01 | 0.01 |
| smurfing | 0.34 | 0.38 | 0.34 | 0.48 |
| dormant | 0.30 | 0.50 | 0.12 | 0.51 |

The 20-epoch default understates the GNN on fan-in, fan-out, smurfing and dormant by 0.1–0.4 PR-AUC. Even the 60-epoch run stops at its cap (best epochs 54–59), so those numbers are still a lower bound. The qualitative finding does **not** change with more training: on unseen shared-device, volume-spike and behavioural-drift families the GNN is near chance, while the RF (§6 table) and the transparent families still catch most of them.

## 7. Roles and detector consensus (roles-v2.1, consensus-v2.1; run 4)

> **SYNTHETIC VALIDATION.** Measured on the same 30 held-out test worlds as §3 (8,846 accounts, 310 mules). No model was refitted: these rules only change how existing detector flags are combined. `python ml/eval_roles_consensus.py` re-scores the test worlds with the **committed** artefacts through the serving path, checks that all six families reproduce the confusion counts in `models/validation_v2.json` exactly, and writes `models/validation_v2_roles_consensus.json`. `validation_v2.json`'s own `roles` block (written by the run-3 training run) is the **v2.0** rule, the "before" column below.

### 7.0 Why the rules changed

In the lead's browser walkthrough of the merged platform, the ordinary payer `ramesh@vigil` paid ₹500 (Act 1), was held on ₹45,000 (Act 2, never paid) and paid ₹1,20,000 rent (control s4, Tier 0). His salary and the rent fell inside the same 72 h window. Drift went HIGH (retention 1.0 → 0.0, ₹ sent 5,757 → 1,21,500) and early warning fired (Pass-Through · High Velocity). No structural or model family flagged him: RF 0.01, GNN 0.00, pattern memory 0.37, RingWatch 0.00, registry clean. Under the run-3 rules he read as role **distributor** with **moderate** agreement ("2 of 10 signal families agree"). Two rules were at fault:

* **roles-v2.0** gave a role to any account flagged by at least 2 of the 6 intel families, whichever they were;
* **consensus-v2.0** set the agreement level from the raw count of flagging families, so two change detectors read as "moderate agreement".

### 7.1 The new rules

* **Mule-evidence families**: Random Forest, GNN and pattern memory (structural or model families), RingWatch (the payment engine's network rules), and the SIMULATED registry when it lists the account as reported or confirmed mule. Not mule evidence: drift and early warning (change against the account's own history, or a population anomaly), the rule engine (window heuristics), and TrailScore / ContextFlag (one payment journey of a recent sender).
* **Agreement (consensus-v2.1)**: none (0) · weak (1) · moderate (2–3) · strong (≥ 4) flagging families, as before, but **capped at weak unless at least one mule-evidence family flags**. `families_flagging` is still the plain count, so the `DetectorConsensus` shape and meaning are unchanged. When the cap applies, the summary says why, for example "2 of 10 signal families flag this account (early warning, drift) — behaviour-change signals only, no structural or model family agrees, so agreement stays weak".
* **Role gate (roles-v2.1)**: a role is assigned only if at least 2 **account-level** families flag (the 6 intel families plus RingWatch and the registry) **and** at least one of them is a mule-evidence family. Otherwise the role is `unclassified` with the reason "Behaviour changed (early warning, drift), but there is no mule-structure evidence…", and `/api/intel/scores` shows `role: null`. Over the account-level families this is the same condition as agreement ≥ moderate, so the UI never shows a role next to "weak" agreement. The "flagged group" that entry and exit positions refer to is the same gated set.

RingWatch and the registry exist only in the live world, so they could not be validated on test worlds. They are counted as mule evidence because RingWatch is the transparent network rule set the payment engine already uses, and a registry listing is direct (simulated) external evidence about the account that does not depend on the windowed features at all.

### 7.2 Consensus: before and after (test worlds)

"≥ moderate" treats agreement of moderate or strong as a flag; "strong" treats only strong as a flag.

| Rule | ≥ moderate: precision | recall | FP | strong: precision | recall | FP |
|---|---|---|---|---|---|---|
| v2.0: raw count (run 3) | 0.44 | 0.865 | 341 | 0.972 | 0.668 | 6 |
| **v2.1: cap at weak without mule evidence (adopted)** | **0.875** | **0.858** | **38** | 0.972 | 0.668 | 6 |
| Alternative: drift + early warning count as one family | 0.474 | 0.865 | 297 | 0.994 | 0.542 | 1 |
| Alternative: one change family **and** the cap | 0.875 | 0.858 | 38 | 0.994 | 0.542 | 1 |
| Alternative: cap, but rules count as mule evidence | 0.474 | 0.865 | 297 | 0.972 | 0.668 | 6 |

Non-mules at agreement ≥ moderate, v2.0 → v2.1:

| Negatives | n | v2.0 | v2.1 |
|---|---|---|---|
| ordinary customers | 7,485 | 82 | 31 |
| merchants (many senders, daily sweeps) | 331 | **197** | **0** |
| small traders | 470 | 47 | 6 |
| event organisers | 19 | 4 | 0 |
| payroll companies | 84 | 9 | 0 |
| landlords | 147 | 2 | 1 |
| victims (paid into an attack) | 187 | 15 | 6 |
| salary credited inside the window | 892 | 24 | 4 |
| **salary in, plus one payment ≥ half the salary in the same window (Ramesh's shape)** | 33 | **15** | **3** |

The last three rows are evaluation-only sub-groups of non-mules, derived from generator ground truth (`ml/train_all.py::negative_groups`). Victims and the salaried customers also appear in the ordinary-customers row.

**What the cap costs.** Two test mules drop from ≥ moderate to weak: one cross-channel mule (recall at ≥ moderate 0.79 → 0.76) and one fan-out mule (0.77 → 0.76). Both were flagged only by rules, drift and early warning. Every other family's per-attack recall at ≥ moderate is unchanged. The strong level is unchanged.

**Why the cap and not "drift + early warning count as one family".** The lead offered both options. The test worlds favour the cap:

| Accounts flagged by ≥ 2 families but no mule-evidence family | Mules | Non-mules |
|---|---|---|
| rules + early warning | 0 | 238 |
| early warning + drift | 0 | 44 |
| rules + early warning + drift | 1 | 18 |
| rules + drift | 1 | 3 |

| Pairwise flag correlation (phi) | All accounts | Non-mules | Mules |
|---|---|---|---|
| RF – GNN | **0.90** | 0.19 | 0.52 |
| rules – early warning | 0.67 | **0.67** | 0.48 |
| drift – early warning | 0.49 | 0.26 | **0.65** |
| drift – pattern memory | 0.59 | 0.29 | 0.44 |
| RF – drift | 0.69 | 0.19 | 0.62 |

* No test mule is flagged by drift and early warning alone, and no test mule is flagged by rules and early warning alone. Agreement that contains no structural or model family is almost always a false agreement: 2 mules against 303 non-mules.
* Among non-mules the pair that co-fires most is **rules + early warning** (phi 0.67, busy merchants and small traders), not drift + early warning (0.26). Merging drift and early warning therefore leaves 197 merchants at "moderate".
* Among mules, drift and early warning co-fire strongly (0.65). Merging them demotes real mules from strong (strong recall 0.668 → 0.542), and RF and GNN are even more correlated (0.90). Merging only the change pair would be an arbitrary choice.
* Merging *and* capping gives the same ≥ moderate numbers as the cap alone. It only trades strong recall (0.668 → 0.542) for strong precision (0.972 → 0.994), so it was not adopted.
* Counting rules as mule evidence brings the merchant false agreements back (FP 297), so the rule engine stays a corroborating family only.

### 7.3 Roles: before and after (test worlds)

Accuracy by true role, for mules with a generator-defined role:

| True role | n | v2.0 (any 2 families) | v2.1 (mule-evidence gate) | Most common confusion (v2.1) |
|---|---|---|---|---|
| coordinator | 10 | 1.00 | 1.00 | — |
| entry | 7 | 0.86 | 0.86 | unclassified (1) |
| distributor | 32 | 0.66 | 0.66 | coordinator (7), unclassified (4) |
| exit | 136 | 0.51 | 0.50 | unclassified (44): exits not flagged by a mule-evidence family get no role |
| collector | 67 | **0.10** | **0.10** | **entry (35)**, coordinator (13) |
| all five | 252 | 113 correct | 112 correct | |

| | v2.0 | v2.1 |
|---|---|---|
| Mules given any role | 238 / 310 | 235 / 310 |
| **Non-mules given a role (false role assignments)** | **279** | **33** |
| Share of assigned roles that sit on a mule | 46 % | 88 % |
| … of which merchants / small traders / payroll / organisers / landlords | 153 / 45 / 9 / 4 / 0 | **0 / 6 / 0 / 0 / 0** |
| … ordinary customers | 68 | 27 |
| … victims (of 187) | 13 | 5 |
| … salary credited inside the window (of 892) | 12 | 2 |
| … salary in plus a payment ≥ half of it (of 33) | 10 | 2 |

The remaining 33 false roles all have at least one mule-evidence family flagging them, so they are model or pattern false positives, not change-detector artefacts. 5 are victims and 2 have the salary-and-payment shape.

**Alternatives considered:**
* *One mule-evidence family alone, without the ≥ 2-family requirement*: exit accuracy 0.61, 251 mules with a role, 39 false role assignments. Not adopted, because it would show a role next to "weak, uncorroborated" agreement. An account flagged by a single model family is better described as uncorroborated than given a position in a mule network.
* *Rules count as mule evidence*: 242 false role assignments, 153 of them merchants. Not adopted.

The **collector** rule is still weak, and the run-4 change does not affect it. A fan-in collector that forwards everything to a single exit looks, by money position, like the place where money enters the flagged group, so it is labelled "entry". Roles are structural descriptions with a stated reason and evidence. They are not accusations, and they should not be shown as validated classifications.

**Limits of this check.** The generator does not model a salaried customer paying a large rent or deposit as such. Ramesh's shape arises only through generic one-off high-value payments, so the sub-group has just 33 test accounts and its rates carry wide sampling error (95 % interval roughly ±0.1–0.17). Real salaried populations would produce this shape far more often, which is why the rule relies on the *kind* of evidence rather than on a tuned threshold.

## 8. Old protocol versus honest protocol (same v2.1 worlds)

| Protocol | Precision | Recall | F1 | PR-AUC | Flag rate |
|---|---|---|---|---|---|
| Original: attack-window features (A1) + random row split (A3) | 0.87 | 0.91 | 0.89 | 0.89 | 4.0 % |
| The same model applied to honest windowed features of the test worlds | **0.06** | 0.96 | 0.11 | 0.16 | **57 %** |

The original protocol gives an impressive F1 of 0.89 on these worlds. Once the same model sees realistic, windowed traffic it flags **57 % of all accounts**. Almost all of the old headline number was leakage from the attack-window graph.

## 9. False positives on hard negatives (test worlds)

| Persona (negatives) | n | Rules | Early warning | Drift | Pattern | RF | GNN | Consensus ≥ 3 | Agreement ≥ moderate (v2.1) | Given a role (v2.1) |
|---|---|---|---|---|---|---|---|---|---|---|
| ordinary customers | 7,485 | 21 | 181 | 138 | 21 | 21 | 4 | 24 | 31 | 27 |
| merchants (many senders, daily sweeps) | 331 | **199** | **197** | 8 | 0 | 0 | 0 | 7 | 0 | 0 |
| small traders (sales swept to cash) | 470 | 76 | 86 | 10 | 8 | 0 | 0 | 5 | 6 | 6 |
| event organisers (many first-time senders) | 19 | 4 | 2 | **11** | 0 | 0 | 0 | 2 | 0 | 0 |
| payroll companies (fan-out) | 84 | 4 | 9 | 9 | 0 | 0 | 0 | 4 | 0 | 0 |
| landlords | 147 | 0 | 3 | 2 | 0 | 0 | 1 | 1 | 1 | 0 |

The population-relative and structural heuristics (rules, early warning) are the noisy families on legitimate collection accounts. Drift is noisy on event organisers, which genuinely change behaviour. The learned models have essentially no merchant or trader false positives here. Real merchants are far more varied than the generator's, so this should not be read as "solved". The last two columns (run 4, §7) show why agreement and roles now need a structural or model family: without that requirement, 197 merchants read as "moderate agreement" and 153 were given a mule role.

## 10. Live demo world: behavioural acceptance checks (not metrics)

The live world is generated by `vigil/sim/seed.py`. That is a **different** generator, so these checks also measure transfer from the training worlds to a world the models never saw. They are enforced by `backend/tests/test_intel_live.py` and, for roles and agreement (run 4), `backend/tests/test_intel_roles.py`.

**Seeded world, before any scenario.** 139 scored accounts. Only `kiran.traders` (5 of 6 families: EW, drift, pattern, RF, GNN) and `zenith.exports` (3 of 6: EW, RF, GNN) are flagged. By design, these are the Act 2 recipient, which is already forwarding money fast, and its layering account. **0 of 131 ordinary (`legit`) customers are flagged by any family.** Before the run-3 repairs (§2.1), 9 were flagged by the GNN and 18 by drift.

**After each scenario** (same seeded world plus the scenario's postings; each scenario starts from a fresh seed). The columns give, for each involved account flagged by ≥ 3 of the 6 families:

| Scenario | Account (seeded role) | Families flagging (of 6) | Role |
|---|---|---|---|
| s2 mule ring | kiran.traders (mule_collector) | 6: rules, EW, drift, pattern, RF, GNN | collector |
| s2 mule ring | pooja.m (mule_downstream) | 5: EW, drift, pattern, RF, GNN | exit |
| s2 mule ring | zenith.exports (mule_layer) | 4: EW, drift, RF, GNN | distributor |
| atk_fan_in | swift.collect (mule_attack) | 6 | collector |
| atk_fan_out | bulk.payouts (mule_attack) | 5: rules, EW, drift, RF, GNN | distributor |
| atk_circular | the 4 ring accounts (seeded `legit`, used as the ring) | 3–4: drift, RF, GNN (+ pattern) | coordinator |
| atk_velocity_chain | the 5 chain accounts | 3–5 | entry / distributor / exit / unclassified |
| atk_cross_channel | the hub | 5: rules, EW, drift, RF, GNN | unclassified |
| atk_shared_device | dc.one–dc.four, dc.hub | 6, 6, 6, 6, 5 | entry ×4, collector |
| atk_behavioural_drift | the drifting account | 6 | distributor |
| atk_volume_spike | fresh.wallet | 5: rules, EW, drift, RF, GNN | coordinator |
| atk_smurfing | the structuring hub | 4: EW, drift, RF, GNN | coordinator |
| atk_dormant | dormant.savings | 5: EW, drift, pattern, RF, GNN | collector |

* **Run 4: the roles in this table are unchanged under roles-v2.1.** Every account listed has RF and GNN among its flags. Re-running every scenario from a fresh seed, the only role that changed anywhere in the live world is the one below.
* **In every scenario, no account outside the scenario's involved accounts is flagged by ≥ 2 families.** The two seeded Act 2 accounts are excluded from this count.
* Involved accounts that are not mules sit at 0–2 flags, usually drift alone. This happens for 3–4 accounts in s2, fan-in, cross-channel, volume spike and dormant. A victim who suddenly sends ₹50,000 to a new counterparty *has* drifted, and the compare view labels such accounts "sent scenario funds", not "missed mule".
* Weak spots also show live. The smurfing **recipients** and the fan-out **recipients** (all seeded `legit` accounts) are not flagged. Pattern memory misses the smurfing hub (it matches "behavioural drift" structurally). The role heuristic labels shared-device members "entry" because money enters the flagged cluster through them.
* **Latency of `corroboration()`.** After a whole scenario's postings the incremental refresh takes 5–13 ms, with a median of 5.5 ms over 10 single postings (max 13.7 ms). A cache hit takes 0.2 ms. A full rebuild of all 139 accounts takes about 47 ms warm and is used only on the API path and after a reset. `test_corroboration_latency_budget` enforces a median below 20 ms.

> **Lead note (Claude 1, 2026-10-07, after merge).** The checks above hold on a freshly seeded world. On the long-running live server they did **not**: after several hours of the v1 background stream ("ambient", one ordinary payment every 3 s), 130 of 140 accounts were flagged by at least one family and ordinary customers were labelled "coordinator" with GNN ≈ 0.93. Measured from a clean world: 29 of 133 ordinary customers were drift-HIGH after 10 min of that stream and 104 after 40 min (RF/GNN stayed clean over 40 min; their false flags came after hours). The detectors were right — the stream made every account ~100× busier than its own history — so the stream was fixed, not the models: it is now routine-preserving (a payment only if both accounts stay at or below their busiest 72 h block of the previous 45 days; one attempt per 20 s). After 800 attempts, 0 ordinary customers are flagged by any family; `test_ambient_stream_keeps_every_account_within_its_own_routine` enforces this. Lesson for any deployment: these detectors measure change against an account's own history, so any synthetic or replayed background traffic must respect each account's own rate, or it manufactures drift.

**Run 4 live checks (roles-v2.1 / consensus-v2.1).** Each row starts from a fresh seed, then runs the scenarios in order (`run_sync`, pinned demo hour). Values are from `/api/intel/accounts/{id}` and `/api/intel/scores`.

| After | Account | Families flagging | Before (run 3 rules) | After (run 4 rules) |
|---|---|---|---|---|
| s0, s1, s4 (Act 1, Act 2 held, rent control) | `ramesh@vigil` (ordinary payer) | 2 of 10: early warning, drift | distributor · moderate | **no role** (`unclassified`; scores `null`) · **weak**: "behaviour-change signals only, no structural or model family agrees" |
| s0, s1, s4 | `kiran.traders` | 7 of 8: RF, GNN, EW, drift, pattern, RingWatch, registry | collector · strong | collector · strong |
| s0, s1, s4, then s2 | the five s2 victims | 0–1 (drift HIGH for anita.s, joseph.d, lakshmi.n) | no role · weak/none | no role · weak/none |
| s0, s1, s4, then s2 | `kiran.traders` / `zenith.exports` / `pooja.m` | 8 / 5 / 6 of 8 | collector / distributor / exit · strong | unchanged |
| s0, s1, s4, then s2 | `ramesh@vigil` | 2 of 10: early warning, drift | distributor · moderate | no role · weak |
| s3 (coercion) | `sunita@vigil` (the coerced sender) | 2 of 10: TrailScore, ContextFlag | no role · **moderate** | no role · **weak**: "payment-journey signals only" |

* The s3 row is a visible side effect. TrailScore and ContextFlag both come from Sunita's own latest payment decision. They describe a coerced *victim's* journey, not mule structure, so on her account-intelligence page they no longer read as moderate agreement. The payment decision itself still carries its Tier 4 hold and CircuitBreaker alert, and none of this touches the payment path.
* `test_intel_roles.py` enforces the Ramesh, victim, ring and Sunita rows. It also checks one invariant over the whole scored population: every account with a role in `/api/intel/scores` has at least 2 flags, including a mule-evidence family.
* **Not changed:** early warning still flags Ramesh (Pass-Through · High Velocity), and drift still reads HIGH. Both are honest change signals: salary in and rent out did change his 72 h behaviour. `/api/intel/overview` therefore still lists him among `early_warnings`, which the Detection page titles "Accounts trending towards mule behaviour". Early warning is meant to fire *before* mule structure exists, so hiding change-only accounts would defeat it. The wording of that panel is a frontend matter (see the run-4 record).

### 10.x consensus-v2.2 on world v3 (2026-10-09, Claude 1)

Found during the v4 functional audit on the denser world v3 (553 accounts, ~31k postings). These are behavioural checks on the live demo world, not metrics; every number is SIMULATED.

| Issue | Before | Change | After |
|---|---|---|---|
| Circular ring, run from the Scenario lab | detected 0 / 4 (all `early_warning`). Live "flagged" needed calibrated model probability ≥ 0.85 (the top of the adaptive band). Ring members score 0.54–0.64, and RingWatch was not part of the live gate | Second route to live "flagged": RingWatch (the payment engine's transparent network rules) ≥ 0.40 **and** ≥ 2 intel families | 4 / 4 detected, 0 false positives, detected 27 ms after the closing posting; fan-in 1 / 1, behavioural drift 1 / 1 |
| s2 victim `lakshmi.n` (paid into the ring) | RF + drift → **moderate** agreement and mule role **distributor** | RF / GNN count as mule evidence only when the account moves *received* money on: RingWatch forwarded fraction ≥ 0.3, a RingWatch flow role, or a closed loop (`NET_CIRCULAR`). An unmeasured flow never downgrades. Applies to consensus, the role gate and the live model route | **weak**, no role, never flagged. The reason reads "model (no onward money flow) and behaviour-change signals" |
| Ambient stream (person-to-merchant) | — | — | after 917 ambient payments, 0 of 543 ordinary accounts trip any family; live statuses are only `normal` / `idle` |

**Limitation kept visible:** on world v3 the Random Forest still raw-flags a victim's large first-time outflow. That is a model false positive in the raw output. The account page shows it beside the consensus that explains why it is not mule structure. Retraining on worlds with explicit victim journeys would address it at the source. `test_intel_live.py` now asserts the victims' *corroboration*: consensus ≤ weak, no role, not flagged. This is the test's stated intent. Attack corroboration counts the platform's 8-family consensus (RingWatch and the registry included), and the spill-over check (no bystander with ≥ 2 flags) is unchanged.

## 11. What these models can and cannot establish

**They can establish:** that an account's recent (72 h) money-flow structure, and its change against its own 45-day baseline, resemble the mule patterns of the training worlds. They can also say which inputs drove the RF score (SHAP) and how many independent *methods* agree.

**They cannot establish:**
* that an account is a mule;
* anything about real-bank precision or recall, because the data is synthetic;
* the behaviour of attack shapes the generator does not produce (§6);
* the intent or ownership behind an account.

The model families share inputs: all of them read the same windowed features. "Agreement" is therefore corroboration between different methods, not between statistically independent sources.

**Operational rule (unchanged):** none of these outputs changes the payment tier. `corroboration()` results are attached to each decision as `model_evidence` and are listed in the audit record as `model_evidence_not_used_for_tier`. The audit still records `ml_models_used: []`, and a test asserts that score and tier are identical with and without intel.

**Known limitations:**
* RF importance is dominated by value (`total_in_amount`, mean |SHAP| 0.155) and counterparty novelty (0.110). Real mules moving small amounts would look less unusual.
* Device sharing carries almost no RF weight (mean |SHAP| 0.001). Shared-device detection in these worlds comes from correlated youth and novelty features, not the device itself.
* Live inference uses a GNN over the whole 72 h window graph. That is cheap at demo scale (about 140 accounts) but would need neighbourhood sampling at bank scale.
* Incremental refreshes keep the features of accounts untouched by new postings at the previous evaluation time until the next full rebuild (≤ 120 s on the API path).
* Agreement levels and roles depend on which families count as mule evidence (§7). That choice is validated on test worlds for RF, GNN and pattern memory only. RingWatch and the SIMULATED registry count as mule evidence in the live world without a synthetic-world measurement. Drift and early warning still flag ordinary customers whose salary and a large payment share a 72 h window. They are now reported as change, not as agreement.

## 12. Reproduction and provenance of every number

| Numbers | Run | Command (from `backend/`) | Wall time |
|---|---|---|---|
| §3–§5 (except the run-4 agreement row), §6 main table, §8, §9 (except its last two columns); all committed model artefacts in `backend/models/` (`trained_at 2026-10-06T20:11:11Z`) | run 3, default | `python ml/train_all.py` | **3 min 20 s** wall (192 s internal: generation 9, features 8, RF 1, GNN 42, SHAP 2, LOAO 125, old protocol 2) |
| §6 full-budget LOAO comparison (`models/validation_v2_full_loao.json`, writes nothing else) | run 3, optional | `python ml/train_all.py --full-loao` | 7 min 15 s wall (426 s internal, LOAO 359 s) |
| Run-2 figures quoted in §6 (generator v2.0, LOAO GNN 60 epochs) | run 2 (superseded) | `python ml/train_all.py` at commit `871df51` | 804 s (LOAO 690 s) |
| §10 live checks | run 3 | `pytest tests/test_intel_live.py tests/test_intel_consensus.py` | — |
| §7 roles and consensus (before/after, alternatives, correlations), the §3 "agreement ≥ moderate" row, the last two §9 columns (`models/validation_v2_roles_consensus.json`) | run 4, **no retraining**: committed run-3 artefacts re-scored through the serving path; the script refuses to write unless all six families reproduce `validation_v2.json`'s confusion counts | `python ml/eval_roles_consensus.py` | 5 s |
| §10 run-4 live checks | run 4 | `pytest tests/test_intel_roles.py` | — |

Training is deterministic: seeded worlds, seeded forest, and `torch` single-threaded with deterministic algorithms. Re-running the default command reproduced the same GNN (best epoch 58, validation PR-AUC 0.9679), RF, drift parameters and pattern memory as the preceding `--no-loao` run of the same code. Optional dependencies are pinned in `backend/requirements-ml.txt`. The platform runs without them, and RF, GNN and SHAP then report `status="unavailable"`, which `test_intel_degrade.py` checks.
