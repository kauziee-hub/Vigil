# Vigil — a working implementation of PRIMA

**PRIMA** — *Pre-commitment Risk Intelligence & Mitigation Architecture.*
**Vigil** answers one question: *given everything we know at this exact moment, what should happen **before** this customer irreversibly commits this payment?*

Vigil is not another fraud classifier. India already has bank EFRMS/AML, RBIH's MuleHunter.AI and the RBI-led DPIP. Vigil is the bank-side layer that turns those signals — plus its own network, journey, behaviour and context evidence — into an **explainable, proportionate intervention at the last reversible moment**, then traces where money went after payment and feeds that back into the next decision. See [docs/REAL_WORLD_POSITIONING.md](docs/REAL_WORLD_POSITIONING.md).

```
intent ─▶ evaluate (external · network · journey · behaviour · context) ─▶ fuse + explain ─▶ interrupt ladder
        ─▶ (only if approved) payment provider ─▶ ledger + PathGraph ─▶ RingWatch / TaintTrace ─▶ next decision
```

## Quick start

Requirements: Python 3.11+, Node 18+.

```powershell
powershell -ExecutionPolicy Bypass -File run_demo.ps1          # Windows
```
```bash
./run_demo.sh                                                    # macOS / Linux / Git Bash
```

The script creates the venv, installs dependencies, builds the UI, seeds the deterministic demo database on first run, starts one server on port 8000 and prints:

* Command center — `http://localhost:8000/`
* Pay — `http://localhost:8000/pay`
* Trusted contact (open on a phone on the same Wi-Fi) — `http://<lan-ip>:8000/contact/arjun`

Options: `-Reset` / `--reset` (wipe + reseed), `-Mock` / `--mock` (force offline payments), `-Port 8001`. The **Reset demo** button in the command center does the same reset at runtime.

### Razorpay (optional)

Copy `.env.example` to `.env` and set `RAZORPAY_KEY_ID=rzp_test_…` / `RAZORPAY_KEY_SECRET=…`. Vigil probes the keys at startup; if they are missing or rejected it uses the mock provider and the top bar says so. Razorpay **test mode** proves a real gateway integration with test funds — **it does not move real money**. Live keys are refused.

## The five-act demo

Full script: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

| Act | Scenario | Outcome |
|---|---|---|
| 1 | Ramesh pays his grocer ₹500 | Tier 0, approved, paid |
| 2 | Ramesh → Kiran Traders ₹45,000 | Tier 2, confirm purpose — before any money moves |
| 3 | Inject mule ring, confirm one victim payment | RingWatch highlights the ring; TaintTrace attributes value; Kiran Traders now Tier 3 |
| 4 | Sunita, 67: new device → payee → limit → simulated threat call → 95 % of savings | Tier 4, scoped hold, CircuitBreaker alert to her son's phone, live |
| 5 | Open any decision | Customer reason · bank evidence · audit record |
| Control | Ramesh pays landlord ₹1,20,000 | Tier 0 — unusual amount, no friction |

## Repository

```
backend/vigil/      FastAPI service: contracts, sqlite3 (WAL) db, intent lifecycle, risk engine, payments, scenarios
backend/prima/      vendored PRIMA lineage engine (LIBR / pro-rata tracing with exact conservation)
backend/tests/      211 tests (190 lineage + Vigil lifecycle, scenarios, API, invariants)
frontend/           Vite + React + TypeScript + Cytoscape (dagre) — built and served by the backend
config/risk_policy.yaml   the only place weights, thresholds and windows live (versioned)
scripts/benchmark_demo.py latency benchmark
docs/               audit, architecture, positioning, model card, demo script, limitations, agent prompts
AGENT_HANDOFF/      prompts, outputs and STATE.md so any agent can continue
```

## Tests and benchmark

```powershell
cd backend; .venv\Scripts\python.exe -m pytest
backend\.venv\Scripts\python.exe scripts\benchmark_demo.py
```

On the build laptop: risk evaluation p95 ≈ 1 ms (target < 150 ms), graph queries < 1 ms, TaintTrace ≈ 80 ms over ~2,000 journals. See [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md).

## What is real, simulated, synthetic

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md). In short: the decision engine, ledger, graph, tracing, interventions and realtime are real; external intelligence, call context, scam confirmations and bank review are **simulated** and labelled; all data is **synthetic**; no ML model is on the decision path ([docs/MODEL_CARD.md](docs/MODEL_CARD.md)).

## Conventions

Money is integer paise. Time is ISO-8601 UTC with `Z`. Errors are `{"error": {"code", "message", "details?"}}`. The backend is the source of truth; the frontend reads the policy from `/api/policy`.

## Author

Kausik GH
