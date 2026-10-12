# Vigil — a working implementation of PRIMA

**PRIMA** — *Pre-commitment Risk Intelligence & Mitigation Architecture.*
**Vigil** answers one question: *given everything we know at this exact moment, what should happen **before** this customer irreversibly commits this payment?*

Vigil is not another fraud classifier. India already has bank EFRMS/AML, RBIH's MuleHunter.AI and the RBI-led DPIP. Vigil is the bank-side layer that turns those signals — plus its own network, journey, behaviour and context evidence — into an **explainable, proportionate intervention at the last reversible moment**, then traces where money went after payment and feeds that back into the next decision. See [docs/REAL_WORLD_POSITIONING.md](docs/REAL_WORLD_POSITIONING.md).

```
intent ─▶ evaluate (external · network · journey · behaviour · context) ─▶ fuse + explain ─▶ interrupt ladder
        ─▶ (only if approved) simulated payment rail ─▶ ledger + PathGraph ─▶ RingWatch / TaintTrace ─▶ next decision
```

## Quick start

Requirements: Python 3.11+, Node 18+.

```powershell
powershell -ExecutionPolicy Bypass -File run_demo.ps1          # Windows
```
```bash
./run_demo.sh                                                    # macOS / Linux / Git Bash
```

The script creates the venv, installs dependencies, builds the UI, seeds the deterministic demo world on first run and starts one server on port 8000. Options: `-Reset` / `--reset` (wipe + reseed), `-Port 8001`.

| Screen | URL | What it is for |
|---|---|---|
| Overview | `/` | Operations center: KPI strip, Copilot incident strip, money map (flat / globe, simulated locations), live transaction tape + connections drawer, compact 3D network, needs attention (₹ in / out), situation brief, close monitoring, mule pipeline, money by channel |
| Payments | `/guard` | The customer's phone beside the bank's pre-commit assessment; customer-only kiosk at `/pay?as=ramesh@vigil` |
| Network | `/network` | Live 3D universe with lenses and edge filter, evidence scenes, live activity streams |
| Detection | `/detection` | Models (synthetic validation), live detection runs, rules, early warning, roles, full account scoring, pattern memory |
| Cases | `/investigations` | Decision replay, counterfactuals, provenance, account investigation |
| Interventions | `/interventions` | Holds and confirmations: release / reject |
| Governance | `/governance` | Policy, tier ladder, model versions, decision records, shadow mode |
| Trusted contact | `/contact/arjun` | Open on a phone on the same Wi-Fi |

**Test inputs** (top bar or Alt + T) is a small drawer of demo-only inputs: a customer payment, inject one of eleven mule-network patterns, a coerced journey, report a confirmed scam, traffic / mode / reset. Product screens carry no simulation controls. Demo walkthrough: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

Payments settle on a **simulated payment rail** behind a provider port (a bank plugs its own rail in there). No real money moves and no gateway keys are needed.

### Vigil Copilot (optional AI)

The Overview's Copilot watches for incidents with a **deterministic** engine (rings, flagged accounts, cash-out clusters,
impossible travel, held payments, coercion, fast pass-through new accounts, device farms, traced scam money) and briefs
the analyst. It is **read-only**. With no key it runs offline on templates and the same read-only tools. To use Google's
Gemini, put `GEMINI_API_KEY=...` in `.env` (git-ignored; see `.env.example`) and restart: this sends incident facts
(synthetic data) to Google's API. Details: `docs/KNOWN_LIMITATIONS.md`, `config/copilot_policy.yaml`.

## Repository

```
backend/vigil/        FastAPI service: contracts, sqlite3 (WAL), intent lifecycle, risk engine, payment port, scenarios, live status
backend/vigil/intel/  detection intelligence: rules, early warning, drift, pattern memory, roles, RF + GNN inference, SHAP, consensus
backend/ml/           synthetic-world generator + training / evaluation (train_all.py); artefacts in backend/models/
backend/prima/        vendored PRIMA lineage engine (LIBR / pro-rata tracing with exact conservation)
backend/tests/        pytest suite (lineage, lifecycle, scenarios, API, invariants, intel, live detection)
frontend/             Vite + React + TypeScript; three.js live network — built and served by the backend
config/risk_policy.yaml   the only place weights, thresholds and windows live (versioned)
scripts/              smoke test and latency benchmark
docs/                 demo script, architecture, design system, ML validation, model card, limitations, positioning, screenshots
docs/archive/         superseded plans, audits and earlier screenshot sets (kept for the record)
AGENT_HANDOFF/        every prompt, run record and the current STATE.md, so any agent can continue
```

## Tests and benchmark

```powershell
cd backend; .venv\Scripts\python.exe -m pytest
backend\.venv\Scripts\python.exe scripts\smoke_demo.py
backend\.venv\Scripts\python.exe scripts\benchmark_demo.py
```

Detection models (optional; the platform runs without them and shows "unavailable"):

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-ml.txt   # numpy, scikit-learn, shap (serving + SHAP)
backend\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu   # training only
cd backend; .venv\Scripts\python.exe ml\train_all.py                             # deterministic; rewrites backend\models\
```

Results are **SYNTHETIC VALIDATION** on computer-generated worlds (split by world, leave-one-attack-family-out), not real-bank accuracy: [docs/ML_VALIDATION_REPORT.md](docs/ML_VALIDATION_REPORT.md). Benchmarks: [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md).

## What is real, simulated, synthetic

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md). In short: the decision engine, ledger, graph, tracing, interventions and realtime are real; the payment rail, external intelligence, call context, scam confirmations and bank review are **simulated** and labelled; all data is **synthetic**; no ML model decides a payment's tier — the Random Forest, graph neural network, drift and pattern-memory detectors are corroborating evidence only ([docs/MODEL_CARD.md](docs/MODEL_CARD.md)).

## Conventions

Money is integer paise. Time is ISO-8601 UTC with `Z`. Errors are `{"error": {"code", "message", "details?"}}`. The backend is the source of truth; the frontend reads the policy from `/api/policy`.

## Author

Kausik GH
