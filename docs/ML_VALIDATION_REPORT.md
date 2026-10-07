# ML Validation Report: Detection Intelligence v2

> **SYNTHETIC VALIDATION.** Every number in this report comes from computer-generated transaction worlds. None of it is a measurement of real-bank accuracy, and none of it may be quoted as one.

Owner: Claude 2 (ML / detection intelligence). Scope: `backend/vigil/intel/**`, `backend/ml/**`, `backend/models/**`.
Operational status: all models here produce **corroborating evidence only**. Payment authorisation stays with the transparent policy engine (`risk/*` + `config/risk_policy.yaml`). See `docs/FINAL_PARALLEL_PLAN.md` §5.

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

How to read this:
* **The learned models beat the rules by a wide margin on these worlds.** The rules' PR-AUC is 0.19 against 0.92 for the RF and 0.95 for the GNN. The rules' false positives are mostly merchants (199 of 331 flagged) and small traders (76 of 470), which are exactly the hard negatives. The windowed rules are still a large improvement on the original unwindowed ones, which fired on almost every active account (A15).
* **These numbers are optimistic.** Train and test worlds come from the same generator, which a real deployment never has. The models learn this generator's notion of a mule. §6 shows how quickly they degrade on a family they have not seen, and that is the better guide to real-world behaviour.
* **The consensus count trades recall for robustness.** 3-of-6 is less precise than the GNN alone on in-distribution worlds. It is the operational display because it does not depend on any single model being right.
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

## 7. Role assessment (test worlds, mules with a generator-defined role)

Roles are only assigned to accounts that at least 2 of the 6 families flag.

| True role | n | Assigned correctly | Most common confusion |
|---|---|---|---|
| coordinator | 10 | 1.00 | — |
| entry | 7 | 0.86 | unclassified (1) |
| distributor | 32 | 0.66 | coordinator (8) |
| exit | 136 | 0.51 | unclassified (42); exits that are not flagged by 2 families get no role |
| collector | 67 | **0.10** | **entry (35)**, coordinator (13) |

The **collector** rule is weak. A fan-in collector that forwards everything to a single exit looks, by money position, like the place where money enters the flagged group, so it is labelled "entry". Roles are structural descriptions with a stated reason and evidence. They are not accusations, and they should not be shown as validated classifications.

## 8. Old protocol versus honest protocol (same v2.1 worlds)

| Protocol | Precision | Recall | F1 | PR-AUC | Flag rate |
|---|---|---|---|---|---|
| Original: attack-window features (A1) + random row split (A3) | 0.87 | 0.91 | 0.89 | 0.89 | 4.0 % |
| The same model applied to honest windowed features of the test worlds | **0.06** | 0.96 | 0.11 | 0.16 | **57 %** |

The original protocol gives an impressive F1 of 0.89 on these worlds. Once the same model sees realistic, windowed traffic it flags **57 % of all accounts**. Almost all of the old headline number was leakage from the attack-window graph.

## 9. False positives on hard negatives (test worlds)

| Persona (negatives) | n | Rules | Early warning | Drift | Pattern | RF | GNN | Consensus ≥ 3 |
|---|---|---|---|---|---|---|---|---|
| ordinary customers | 7,485 | 21 | 181 | 138 | 21 | 21 | 4 | 24 |
| merchants (many senders, daily sweeps) | 331 | **199** | **197** | 8 | 0 | 0 | 0 | 7 |
| small traders (sales swept to cash) | 470 | 76 | 86 | 10 | 8 | 0 | 0 | 5 |
| event organisers (many first-time senders) | 19 | 4 | 2 | **11** | 0 | 0 | 0 | 2 |
| payroll companies (fan-out) | 84 | 4 | 9 | 9 | 0 | 0 | 0 | 4 |
| landlords | 147 | 0 | 3 | 2 | 0 | 0 | 1 | 1 |

The population-relative and structural heuristics (rules, early warning) are the noisy families on legitimate collection accounts. Drift is noisy on event organisers, which genuinely change behaviour. The learned models have essentially no merchant or trader false positives here. Real merchants are far more varied than the generator's, so this should not be read as "solved".

## 10. Live demo world: behavioural acceptance checks (not metrics)

The live world is generated by `vigil/sim/seed.py`. That is a **different** generator, so these checks also measure transfer from the training worlds to a world the models never saw. They are enforced by `backend/tests/test_intel_live.py`.

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

* **In every scenario, no account outside the scenario's involved accounts is flagged by ≥ 2 families.** The two seeded Act 2 accounts are excluded from this count.
* Involved accounts that are not mules sit at 0–2 flags, usually drift alone. This happens for 3–4 accounts in s2, fan-in, cross-channel, volume spike and dormant. A victim who suddenly sends ₹50,000 to a new counterparty *has* drifted, and the compare view labels such accounts "sent scenario funds", not "missed mule".
* Weak spots also show live. The smurfing **recipients** and the fan-out **recipients** (all seeded `legit` accounts) are not flagged. Pattern memory misses the smurfing hub (it matches "behavioural drift" structurally). The role heuristic labels shared-device members "entry" because money enters the flagged cluster through them.
* **Latency of `corroboration()`.** After a whole scenario's postings the incremental refresh takes 5–13 ms, with a median of 5.5 ms over 10 single postings (max 13.7 ms). A cache hit takes 0.2 ms. A full rebuild of all 139 accounts takes about 47 ms warm and is used only on the API path and after a reset. `test_corroboration_latency_budget` enforces a median below 20 ms.

> **Lead note (Claude 1, 2026-10-07, after merge).** The checks above hold on a freshly seeded world. On the long-running live server they did **not**: after several hours of the v1 background stream ("ambient", one ordinary payment every 3 s), 130 of 140 accounts were flagged by at least one family and ordinary customers were labelled "coordinator" with GNN ≈ 0.93. Measured from a clean world: 29 of 133 ordinary customers were drift-HIGH after 10 min of that stream and 104 after 40 min (RF/GNN stayed clean over 40 min; their false flags came after hours). The detectors were right — the stream made every account ~100× busier than its own history — so the stream was fixed, not the models: it is now routine-preserving (a payment only if both accounts stay at or below their busiest 72 h block of the previous 45 days; one attempt per 20 s). After 800 attempts, 0 ordinary customers are flagged by any family; `test_ambient_stream_keeps_every_account_within_its_own_routine` enforces this. Lesson for any deployment: these detectors measure change against an account's own history, so any synthetic or replayed background traffic must respect each account's own rate, or it manufactures drift.

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

## 12. Reproduction and provenance of every number

| Numbers | Run | Command (from `backend/`) | Wall time |
|---|---|---|---|
| §3–§5, §6 main table, §7–§9; all committed artefacts in `backend/models/` (`trained_at 2026-10-06T20:11:11Z`) | run 3, default | `python ml/train_all.py` | **3 min 20 s** wall (192 s internal: generation 9, features 8, RF 1, GNN 42, SHAP 2, LOAO 125, old protocol 2) |
| §6 full-budget LOAO comparison (`models/validation_v2_full_loao.json`, writes nothing else) | run 3, optional | `python ml/train_all.py --full-loao` | 7 min 15 s wall (426 s internal, LOAO 359 s) |
| Run-2 figures quoted in §6 (generator v2.0, LOAO GNN 60 epochs) | run 2 (superseded) | `python ml/train_all.py` at commit `871df51` | 804 s (LOAO 690 s) |
| §10 live checks | run 3 | `pytest tests/test_intel_live.py tests/test_intel_consensus.py` | — |

Training is deterministic: seeded worlds, seeded forest, and `torch` single-threaded with deterministic algorithms. Re-running the default command reproduced the same GNN (best epoch 58, validation PR-AUC 0.9679), RF, drift parameters and pattern memory as the preceding `--no-loao` run of the same code. Optional dependencies are pinned in `backend/requirements-ml.txt`. The platform runs without them, and RF, GNN and SHAP then report `status="unavailable"`, which `test_intel_degrade.py` checks.
