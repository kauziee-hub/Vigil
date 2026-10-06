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

*(Sections 2–8 are filled after retraining; see below.)*
