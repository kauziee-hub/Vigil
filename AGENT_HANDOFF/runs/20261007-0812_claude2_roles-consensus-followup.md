# Run record — claude2 — roles / consensus follow-up (run 4)

| Field | Value |
|---|---|
| Agent | Claude 2 — fresh subagent (resume of the run-3 agent failed: its worktree had been removed after merge), isolated worktree from master |
| Timestamp | sent 2026-10-07 ~08:12 IST; returned ~08:30 IST (1348 s, 118 tool uses) |
| Objective | Roles only with structural/model evidence; drift + early warning not "moderate agreement" on their own; validate on synthetic test worlds; live acceptance test (Ramesh after Acts 1–2 + control has no role) |
| Exact Prompt | Full message sent: `AGENT_HANDOFF/prompts/v2_claude2_run4_roles_consensus_followup.md` (verbatim) |
| Trigger | Lead browser walkthrough of merged main: `ramesh@vigil` → role Distributor, consensus moderate (EW + drift only) after the s4 rent payment; RF/GNN/PM/RingWatch clean |
| Status | RETURNED — saved verbatim below; lead review/merge recorded after it |

## Agent Output / Summary (verbatim final report)

Run 4 is finished. Ramesh no longer gets a mule role and his agreement reads "weak" instead of "moderate". The full suite passes (286 tests: 285 passed, 1 skipped because the frontend isn't built). No retraining was needed: only the rules that combine existing detector flags changed, and no fitted artefact did.

## 1. Summary
- **Reproduced the walkthrough first.** Fresh seed, then s0, s1, s4: `ramesh@vigil` came out as role "distributor", "moderate", "2 of 10 signal families agree (early warning, drift)", with RF 0.01, GNN 0.00 and RingWatch 0.00.
- **Mule-evidence families.** Defined as RF, GNN, pattern memory, RingWatch, and a registry listing (reported or confirmed mule). Drift, early warning, rules, TrailScore and ContextFlag are not mule evidence. I added the registry to your four on purpose: it is direct (simulated) evidence about the account, independent of the windowed features. Otherwise a confirmed mule plus drift could only ever read "weak".
- **Consensus.** None/weak/moderate/strong still come from the count, but agreement is capped at "weak" unless at least one mule-evidence family flags. `DetectorConsensus` fields are unchanged and `families_flagging` is still the plain count. When the cap applies, the summary says why, e.g. "behaviour-change signals only, no structural or model family agrees, so agreement stays weak".
- **Roles.** A role needs at least 2 account-level families flagging (the 6 intel families plus RingWatch and the registry), at least one of them mule evidence. Otherwise the role is `unclassified` with the reason "Behaviour changed (early warning, drift), but there is no mule-structure evidence…", and `/api/intel/scores` shows `role: null`. For these families this is the same condition as agreement ≥ moderate, so a role never appears next to "weak" agreement.
- **Live cost.** RingWatch is evaluated only for accounts where it can change the answer (9 of 139 after s2). The role gate takes 2.6 ms cold; `/scores` takes 3.1 ms. The payment path (`corroboration`) is untouched.

## 2. Files changed (all within my ownership)
- `backend/vigil/intel/consensus.py`, `roles.py`, `live.py`, `service.py`
- `backend/ml/train_all.py`: before/after role and consensus evaluation, shared with the new script; `role_accuracy` is replaced
- new `backend/ml/eval_roles_consensus.py`
- new `backend/models/validation_v2_roles_consensus.json`
- new `backend/tests/test_intel_roles.py` (15 tests)
- `docs/ML_VALIDATION_REPORT.md`: new §7, plus updates to §3, §9, §10, §11 and §12
- `docs/MODEL_CARD.md`: appendix only

## 3. Commands and results (all from the worktree's `backend/`)
- **Scratch repro, before vs after:** Ramesh distributor/moderate → unclassified/weak.
- **`python ml/eval_roles_consensus.py`:** 4.5 s. It refuses to write unless all six families reproduce `validation_v2.json`'s confusion counts exactly; they do.
- **`python ml/train_all.py --quick`:** smoke run OK, 12.8 s, writes nothing. I did not run the full training: no fitted artefact changed.
- **`pytest`:** 286 tests, 285 passed, 1 skipped. That is 271 on the base plus my 15.

## 4. Before / after — SYNTHETIC VALIDATION (30 test worlds, 8,846 accounts, 310 mules)

**Agreement levels:**

| Rule | ≥ moderate: precision / recall / false positives | strong: precision / recall |
|---|---|---|
| Run 3 (raw count) | 0.44 / 0.865 / 341 | 0.972 / 0.668 |
| **Run 4 (cap, adopted)** | **0.875 / 0.858 / 38** | 0.972 / 0.668 |
| Drift + early warning counted as one family | 0.474 / 0.865 / 297 | 0.994 / 0.542 |
| Merge plus cap | 0.875 / 0.858 / 38 | 0.994 / 0.542 |

Non-mules reading ≥ moderate:
- merchants: 197 → 0
- payroll companies: 9 → 0
- small traders: 47 → 6
- victims: 15 → 6
- salary in plus a payment of at least half the salary in the same window (Ramesh's shape): 15 → 3 of 33

The cost is 2 mules (one cross-channel, one fan-out) dropping from moderate to weak; both were flagged only by rules, drift and early warning.

**Roles:**
- Non-mules given a role: **279 → 33**. Merchants 153 → 0, payroll 9 → 0, small traders 45 → 6, victims 13 → 5, Ramesh-shape accounts 10 → 2 of 33.
- Share of assigned roles that are on mules: 46% → 88%.
- Mules given any role: 238 → 235 of 310.
- Accuracy by true role is unchanged except exit (0.51 → 0.50): coordinator 1.00, entry 0.86, distributor 0.66, collector still 0.10.

**Why the cap rather than merging drift and early warning:**
- No test mule is flagged by early warning plus drift alone (0 mules, 44 non-mules), or by rules plus early warning alone (0 mules, 238 non-mules).
- Among non-mules, the pair that fires together most is rules + early warning (correlation 0.67), not drift + early warning (0.26).
- Merging cuts strong-level recall to 0.542 because drift and early warning genuinely fire together on real mules (0.65). RF and GNN are even more correlated (0.90), so merging only the change pair would be arbitrary.

**Live checks** (enforced by `test_intel_roles.py`):
- After s0, s1, s4: Ramesh has no role and weak agreement.
- After s2: the five victims have no role (anita.s, joseph.d and lakshmi.n are drift-only, so "weak"). kiran.traders (collector), zenith.exports (distributor) and pooja.m (exit) keep their roles with strong agreement.
- Across all 15 scenario runs from a fresh seed, Ramesh's is the only role that changed.

## 5. Problems and decisions
- **Sunita reads "weak" after s3.** Her only flags are TrailScore and ContextFlag, both from her own coerced payment, so she now reads "weak" ("payment-journey signals only") instead of "moderate". I think that is correct for an account-level mule view: her Tier 4 hold is unaffected. It is a visible demo change, so please confirm you agree.
- **Ramesh still appears in the early-warning list.** Early warning and drift are honest that his behaviour changed, so `/api/intel/overview` still lists him under the panel "Accounts trending towards mule behaviour". Early warning exists to fire before mule structure does, so I did not filter it.
- **`validation_v2.json` was left as is.** Its `roles` block is the old rule and serves as the "before" column; the new numbers are in `validation_v2_roles_consensus.json`. A future full `train_all.py` run writes both.

## 6. Remaining work
- **Claude 3 (frontend):**
  - `components/intel.tsx:66` says "N of M **independent** signal families flag this account". With the cap that overstates; suggest dropping "independent", since the summary line already explains.
  - Consider retitling the Detection page's early-warning panel (e.g. "Early-warning signals — behaviour change, not mule evidence on its own").
- **You:** restart :8000 after merging; no artefacts changed.
- **Known limits:**
  - RingWatch and the registry count as mule evidence without any synthetic-world validation.
  - The Ramesh-shape group in the test worlds is small (33 accounts).
  - The collector role is still weak (0.10).

## 7. Branch and commit
Branch `worktree-agent-a199de5f7319b1693`, HEAD **`8391a0c`**, branched from master `69f3197`. Milestone commits: `e00705c` (the rules and the evaluation), `2fc10b0` (acceptance test), `ccbb92a` (summary wording and s3 test), `595c475` (evaluation of flag combinations), `8391a0c` (docs). The worktree is clean and nothing is left running.

_(end of verbatim report)_

## Files Changed
_(lead review pending)_

## Tests Run / Test Results
_(lead verification pending)_

## Problems Found / Decisions Made / Remaining Work
_(lead review pending)_

## Git Commit / Diff Reference
Branch `worktree-agent-a199de5f7319b1693` @ `8391a0c` (from master `69f3197`).
