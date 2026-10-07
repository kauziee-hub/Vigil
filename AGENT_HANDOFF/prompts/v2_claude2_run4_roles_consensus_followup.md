Lead (Claude 1) — FOLLOW-UP to your run 3 (merged to main as 4fe0a17; your work is live on :8000). One modelling problem surfaced in the lead's browser walkthrough of the merged platform. Please fix it in your own files, on a fresh branch from current `master` (it contains your merge plus lead fixes: routine-preserving ambient stream 0070ff4, min_tier, cache header, UI fixes).

**Workspace:** your run-3 worktree was removed after the merge (branch kept as `claude2/run3`). Create a new one and work only there: `git -C "C:/Users/KausikGH/Documents/Projects/Fraud Detection" worktree add ".claude/worktrees/claude2-run4" -b claude2/run4 master`. Use the main venv as before. Never edit or commit in the main checkout.

## What the walkthrough showed (live world, demo reset at 07:54 IST, then Acts 1–5 + control run from the Scenario Lab)
`ramesh@vigil` — the ordinary customer who pays in Act 1 (₹500 grocer), Act 2 (₹45,000 to kiran.traders, challenged then held — never paid) and the false-positive control s4 (₹1,20,000 rent to landlord.iyer, Tier 0, paid) — now reads in `/api/intel/accounts/ramesh@vigil`:
- consensus `moderate` — "2 of 10 signal families agree (early warning, drift)";
- early_warning 0.35 flagged ("Pass-Through · High Velocity"), drift HIGH 0.69 (retention 1.0 → 0.0, total_out 5,757 → 1,21,500, total_in 7,333 → 1,10,000, tx count 0.87 → 5);
- role `distributor` — "Pays more accounts than it receives from and keeps only 0%";
- RF 0.01, GNN 0.00, pattern memory 0.37, RingWatch 0.00, registry clean.
The Detection & Models page therefore lists Ramesh under "Accounts trending towards mule behaviour" with role Distributor. A salary arriving and rent leaving in the same 72 h makes any salaried customer look like this. Claude 3 also reported that s2's victim senders (anita.s, joseph.d, lakshmi.n) are drift HIGH — that one is honest (they did change behaviour) and is shown as 1/8 "weak", which is fine.

## What to change (your judgement on the exact rule; justify it in the report)
1. **Roles** describe a mule role, so assign one only when at least one STRUCTURAL / model family flags the account (RF, GNN, pattern memory, RingWatch) — not on change detectors (drift, early warning) alone. Otherwise `role = unclassified/null` with a reason such as "behaviour changed; no mule-structure evidence".
2. **Consensus agreement**: drift and early warning both measure change against the account's own history and are strongly correlated; two of them together must not read as "moderate agreement" of independent families. Count them as one behaviour-change family for the agreement level, or cap agreement at `weak` when no structural family flags. Keep `DetectorConsensus` field shapes unchanged (frontend types are frozen).
3. **Validate on the synthetic TEST worlds, not on the demo**: report before/after for roles (accuracy by true role, roles assigned to non-mules = false role assignments, especially hard negatives such as payroll/rent-like personas) and for the consensus rule's precision/recall. Re-run `ml/train_all.py` only if a fitted artefact changes; otherwise say no retraining was needed.
4. **Live acceptance test** (in `backend/tests/test_intel_*.py`): fresh seed → run s0, s1, s4 → `ramesh@vigil` has no role and agreement ≤ weak; after s2 the victims have no role; kiran.traders / zenith.exports keep their roles and strong agreement. Full suite green.
5. Update `docs/ML_VALIDATION_REPORT.md` (roles + consensus sections, §10 live checks) and your MODEL_CARD appendix, honestly.

## Rules
Edit only your files (`backend/vigil/intel/**`, `backend/ml/**`, `backend/models/**`, `backend/tests/test_intel_*.py`, `docs/ML_VALIDATION_REPORT.md`, your MODEL_CARD appendix). Commit after each milestone (prefix `intel:`). Do not start servers on :8000 (the lead's backend runs there). End with the same return format as before (summary, files, commands + results, before/after numbers — SYNTHETIC VALIDATION, problems/decisions, remaining work, branch + commit); your final message is saved verbatim into the run record.
