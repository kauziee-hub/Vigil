"""Live detection stream (v3): per-posting scoring, live account status, adaptive model-evidence threshold.

A listener registered with `vigil.engine.hooks` runs after every LIVE ledger posting (synchronously, on the
event-loop thread; suspended while seeding). For each posting it

  1. refreshes the detection snapshot INCREMENTALLY (`live.CACHE.current(allow_full=False)`: only the two
     touched accounts and their window counterparties are re-measured; early-warning population statistics
     and the GNN pass are recomputed for everyone, so population effects are picked up);
  2. recomputes every account's live status (cheap dictionary work) and publishes
       * `intel.account_status` (AccountStatusChange) for every account whose status changed, with a reason;
       * `intel.tx_scored` (TxScored) for the posting itself, with both parties' status and model evidence.

Status semantics and precedence (docs/V3_LIVE_PLATFORM_PLAN.md):
    confirmed_fraud > held > flagged > early_warning > new > normal > idle      (external accounts: "external")
  * confirmed_fraud — recipient of a BANK-CONFIRMED fraud label (`fraud_labels`, read-only). A
    `reported_unverified` label does not make an account "confirmed".
  * held           — the account is the sender of an active scoped hold (`scoped_holds.released_at IS NULL`).
  * flagged        — MODEL EVIDENCE (the stronger calibrated probability of RF / GNN) >= the live model-evidence
                     threshold AND at least one other detector family flags the account (corroborated).
  * early_warning  — at least one detector family flags the account, but the flagged gate is not met
                     (behaviour change, heuristics, or uncorroborated model evidence).
  * new            — opened less than NEW_ACCOUNT_DAYS ago.
  * normal / idle  — a posting in / no posting in the last LIVE_WINDOW_MINUTES.

The live model-evidence threshold adapts after each evaluated attack run (`on_run_evaluated`), bounded,
in small deterministic steps, every evaluation logged with its reason (`threshold_history()`), and reset
with the demo. It is used ONLY for the live "flagged" status: detector family flags, AccountIntel consensus,
`consensus.corroboration()` and therefore every payment tier are untouched.

Honesty: statuses are computed from the detector snapshot and Vigil state only. Nothing in this module's
scoring reads `seed_role`, `seed_attack` or labels-as-ground-truth. The two exceptions are clearly separated:
  * `TxScored.scenario` passes the posting's SIMULATOR GROUND TRUTH tag through for display (never scored);
  * `on_run_evaluated` consumes an evaluated AttackRun (injected / missed / false positives, i.e. simulator
    ground truth standing in for confirmed case outcomes) — that is the purpose of a feedback threshold.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable

from vigil import clock, db
from vigil.contracts import AccountStatusChange, TxScored
from vigil.intel import live
from vigil.intel.consensus import SHORT

log = logging.getLogger("vigil.intel.stream")

STREAM_VERSION = "live-status-v1"
LIVE_WINDOW_MINUTES = 10           # "idle" = no posting in this window (align /api/live/universe default)
NEW_ACCOUNT_DAYS = 7
PRECEDENCE = ("confirmed_fraud", "held", "flagged", "early_warning", "new", "normal", "idle")
MODEL_FAMILIES = ("random_forest", "gnn")

# Adaptive model-evidence threshold (calibrated-probability scale; SYNTHETIC calibration).
T_MIN, T_MAX, T_STEP = 0.45, 0.85, 0.02
T_DEFAULT = 0.50
LIVE_STATUS_META = Path(__file__).resolve().parents[2] / "models" / "live_status_v1.json"
_ORIGIN = {"seed": "history", "user": "user", "scenario": "scenario", "ambient": "ambient"}


def _initial_threshold() -> tuple[float, str]:
    """Initial threshold: chosen on VALIDATION worlds by ml/eval_live_status.py (falls back to 0.50)."""
    try:
        meta = json.loads(LIVE_STATUS_META.read_text(encoding="utf-8"))
        value = float(meta["threshold"])
        return _clamp(value), str(meta.get("threshold_rule", "chosen on validation worlds"))
    except Exception:
        return T_DEFAULT, "default 0.50 (validation artefact models/live_status_v1.json not found)"


def _clamp(value: float) -> float:
    return round(min(T_MAX, max(T_MIN, value)), 4)


class _State:
    def __init__(self) -> None:
        self.epoch: Any = None
        self.statuses: dict[str, str] = {}
        self.last_t: dict[str, float] = {}          # last posting time per account
        self.n_edges: dict[str, int] = {}           # edge count when last_t was measured
        self.threshold, rule = _initial_threshold()
        self.initial = self.threshold
        self.history: list[dict[str, Any]] = []
        self.evaluated_runs: set[str] = set()
        self.view_key: Any = None
        self.view: dict[str, dict[str, Any]] = {}
        self.latencies: deque[float] = deque(maxlen=5000)
        self.counters = {"postings": 0, "published_tx": 0, "published_status": 0, "errors": 0, "resets": 0}
        self._log_initial(rule)

    def _log_initial(self, rule: str) -> None:
        self.history = [{"t": clock.now_iso(), "value": self.threshold, "previous": None, "changed": False,
                         "run_id": None, "reason": f"initial live model-evidence threshold {self.threshold:.2f} ({rule})"}]

    def reset(self, epoch: Any) -> None:
        """New demo world (reset / reload): forget statuses and restore the initial threshold."""
        self.epoch = epoch
        self.statuses, self.last_t, self.n_edges = {}, {}, {}
        self.threshold, rule = _initial_threshold()
        self.initial = self.threshold
        self.evaluated_runs = set()
        self.view_key, self.view = None, {}
        self.counters["resets"] += 1
        self._log_initial(rule)


STATE = _State()


# ── per-account evidence ──────────────────────────────────────────────────
def model_evidence(snap: live.Snapshot, account_id: str) -> tuple[float | None, str | None]:
    """(strongest calibrated model probability, family) — RF / GNN; None when neither is available."""
    best: tuple[float | None, str | None] = (None, None)
    for fam, store in (("random_forest", snap.rf), ("gnn", snap.gnn)):
        v = store.get(account_id)
        if v is not None and (best[0] is None or v[1] > best[0]):
            best = (float(v[1]), fam)
    return best


def _flagging(snap: live.Snapshot, account_id: str) -> list[str]:
    fl = snap.flags.get(account_id) or {}
    return [f for f in live.INTEL_FAMILIES if fl.get(f)]


def classify(risk: float | None, fam: str | None, flagging: Iterable[str], threshold: float) -> str | None:
    """The live detector-status rule (pure; shared with ml/eval_live_status.py).

    flagged:       strongest model evidence >= threshold AND another family flags;
    early_warning: the early-warning detector flags, OR >= 2 families flag, OR model evidence >= threshold without
                   corroboration. A single drift / rules / pattern-memory flag alone is NOT an early warning: drift
                   alone is what a scam victim or a salaried customer shows (ML_VALIDATION_REPORT §7), rules alone
                   is what a busy merchant shows; both stay visible on the account page.
    """
    flagging = list(flagging)
    above = risk is not None and risk >= threshold
    if above and any(f != fam for f in flagging):
        return "flagged"
    if above or "early_warning" in flagging or len(flagging) >= 2:
        return "early_warning"
    return None


def detector_status(snap: live.Snapshot, account_id: str, threshold: float) -> tuple[str | None, str]:
    """flagged / early_warning / None from the detector snapshot alone (no Vigil state)."""
    risk, fam = model_evidence(snap, account_id)
    flagging = _flagging(snap, account_id)
    others = [f for f in flagging if f != fam]
    status = classify(risk, fam, flagging, threshold)
    if status == "flagged":
        return "flagged", (f"Model evidence {risk:.2f} ({SHORT[fam]}) >= live threshold {threshold:.2f}, "
                           f"corroborated by {', '.join(SHORT[f] for f in others)}")
    if status is None:
        return None, ""
    if risk is not None and risk >= threshold:
        return "early_warning", (f"Model evidence {risk:.2f} ({SHORT[fam]}) >= live threshold {threshold:.2f}, "
                                 "but no other detector family agrees")
    if flagging:
        detail = []
        for f in flagging:
            if f == "early_warning":
                sig = (snap.ew.get(account_id) or {}).get("signals") or []
                detail.append("early warning" + (f" ({', '.join(sig)})" if sig else ""))
            elif f == "drift":
                detail.append("drift HIGH")
            else:
                detail.append(SHORT[f])
        lead = "Behaviour change" if set(flagging) <= {"early_warning", "drift"} else "Detector signal"
        return "early_warning", f"{lead}: {', '.join(detail)} — not mule evidence on its own"
    return None, ""


# ── Vigil state (read-only) ───────────────────────────────────────────────
def _vigil_state() -> tuple[dict[str, str], dict[str, str], str]:
    """(held account -> reason, confirmed recipient -> reason, cache key). Read-only queries."""
    held: dict[str, str] = {}
    confirmed: dict[str, str] = {}
    try:
        for r in db.q("SELECT account_id, COUNT(*) AS n, SUM(held_paise) AS p, MAX(id) AS last FROM scoped_holds "
                      "WHERE released_at IS NULL GROUP BY account_id"):
            held[r["account_id"]] = (f"Active scoped hold on {int(r['n'])} outgoing payment(s), "
                                     f"₹{int(r['p'] or 0) / 100:,.0f} held for review")
        for r in db.q("SELECT t.recipient_id AS a, COUNT(*) AS n FROM fraud_labels l "
                      "JOIN transactions t ON t.id = l.transaction_id WHERE l.grade = 'bank_confirmed' "
                      "GROUP BY t.recipient_id"):
            confirmed[r["a"]] = f"Recipient of {int(r['n'])} bank-confirmed fraud label(s)"
        key = (db.scalar("SELECT COUNT(*) || ':' || COALESCE(MAX(id), '') || ':' || COUNT(released_at) "
                         "FROM scoped_holds") or "") + "|" + \
              (db.scalar("SELECT COUNT(*) || ':' || COALESCE(MAX(id), '') FROM fraud_labels") or "")
    except Exception as exc:  # pragma: no cover - defensive (tables always exist in Vigil)
        log.warning("live status: Vigil state unavailable: %s", exc)
        key = "unavailable"
    return held, confirmed, key


def _last_posting(snap: live.Snapshot, account_id: str) -> float | None:
    n = snap.n_edges.get(account_id)
    if n is None:
        n = len(live.GRAPH.in_edges.get(account_id, ())) + len(live.GRAPH.out_edges.get(account_id, ()))
    if STATE.n_edges.get(account_id) != n:
        edges = list(live.GRAPH.in_edges.get(account_id, ())) + list(live.GRAPH.out_edges.get(account_id, ()))
        STATE.last_t[account_id] = max((e.t for e in edges), default=None) if edges else None
        STATE.n_edges[account_id] = n
    return STATE.last_t.get(account_id)


def _opened_days(account_id: str, now_t: float) -> float | None:
    t = live.SRC.opened_t(account_id)
    return None if t is None else (now_t - t) / 86400.0


# ── the status map ────────────────────────────────────────────────────────
def _compute(snap: live.Snapshot, now_t: float, held: dict[str, str], confirmed: dict[str, str]) -> dict[str, dict[str, Any]]:
    T = STATE.threshold
    window_start = now_t - LIVE_WINDOW_MINUTES * 60
    out: dict[str, dict[str, Any]] = {}
    for a in live.GRAPH.accounts:
        if live.SRC.is_external(a):
            out[a] = {"status": "external", "risk": None, "model_risk": None, "role": None, "families_flagging": 0,
                      "reason": "External counterparty outside the bank's perimeter"}
            continue
        scored = a in snap.feats
        risk, _ = model_evidence(snap, a) if scored else (None, None)
        flagging = _flagging(snap, a) if scored else []
        det, det_reason = detector_status(snap, a, T) if scored else (None, "")
        if a in confirmed:
            status, reason = "confirmed_fraud", confirmed[a]
        elif a in held:
            status, reason = "held", held[a]
        elif det:
            status, reason = det, det_reason
        else:
            age = _opened_days(a, now_t)
            last = _last_posting(snap, a)
            if age is not None and age < NEW_ACCOUNT_DAYS:
                status, reason = "new", f"Account opened {age:.1f} days ago"
            elif last is not None and last >= window_start:
                status, reason = "normal", f"Active in the last {LIVE_WINDOW_MINUTES} min; no detector flags"
            else:
                status, reason = "idle", f"No posting in the last {LIVE_WINDOW_MINUTES} min"
        out[a] = {"status": status, "risk": None if risk is None else round(risk, 4),
                  "model_risk": None if risk is None else round(risk, 4), "role": None,
                  "families_flagging": len(flagging), "reason": reason, "detector_status": det}
    return out


def _live_flags(snap: live.Snapshot, account_id: str) -> dict[str, bool]:
    """Account-level family flags as the live status sees them: the six intel families, with the strongest
    model family counted as flagging when its evidence reaches the LIVE threshold, plus the registry."""
    from vigil.intel import consensus as C
    fl = dict(snap.flags.get(account_id) or {})
    risk, fam = model_evidence(snap, account_id)
    if fam and risk is not None and risk >= STATE.threshold:
        fl[fam] = True
    try:
        fl["external"] = bool(C.external_result(account_id, snap.as_of).flagged)
    except Exception:
        pass
    return fl


def _assign_roles(snap: live.Snapshot, view: dict[str, dict[str, Any]]) -> None:
    """Mule roles (roles-v2.1 rules, `roles.assess`) for accounts the live status calls flagged / confirmed.

    The flagged network is the set of accounts whose live detector status is "flagged" (plus confirmed
    fraud recipients); the gate uses the live family flags (`_live_flags`). RingWatch is not re-scanned per
    posting (a population scan costs ~15 ms), so a stream role can differ from the AccountIntel role in rare
    cases where only RingWatch would have passed the gate; the AccountIntel page remains the reference.
    """
    from vigil.intel import roles as RO
    network = {a for a, v in view.items()
               if v.get("detector_status") == "flagged" or v["status"] == "confirmed_fraud"}
    for a in sorted(network):
        if a not in snap.feats:
            continue
        try:
            flags = _live_flags(snap, a)
            if not RO.gate(flags)[0]:
                continue
            r = RO.assess(live.SRC, a, snap.now_t, snap.feats[a], network, flags,
                          bool((snap.ctx.get(a) or {}).get("in_cycle")))
            view[a]["role"] = r["role"]
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("live status: role unavailable for %s: %s", a, exc)


def _ensure_epoch(snap: live.Snapshot) -> bool:
    """True when the world changed (reset / reload) and state was reset."""
    if STATE.epoch != snap.key[2:]:
        STATE.reset(snap.key[2:])
        return True
    return False


def _sync(snap: live.Snapshot, publish: bool) -> tuple[dict[str, dict[str, Any]], list[AccountStatusChange]]:
    """Recompute the status map for this snapshot; diff against the last published statuses."""
    fresh = _ensure_epoch(snap)
    now_t = clock.now().timestamp()
    held, confirmed, vkey = _vigil_state()
    key = (snap.key, id(snap), STATE.threshold, vkey, int(now_t // 5))
    if key == STATE.view_key:
        return STATE.view, []
    view = _compute(snap, now_t, held, confirmed)
    _assign_roles(snap, view)                       # roles only inside the live flagged network
    changes: list[AccountStatusChange] = []
    if not fresh and STATE.statuses:
        ts = clock.now_iso()
        for a, v in view.items():
            prev = STATE.statuses.get(a)
            if prev is not None and prev != v["status"]:
                changes.append(AccountStatusChange(account_id=a, status=v["status"], previous=prev, risk=v["model_risk"],
                                                   role=v["role"], families_flagging=v["families_flagging"],
                                                   reason=v["reason"], ts=ts))
    STATE.statuses = {a: v["status"] for a, v in view.items()}
    STATE.view_key, STATE.view = key, view
    if publish:
        _publish_changes(changes)
    return view, changes


def _publish_changes(changes: Iterable[AccountStatusChange]) -> None:
    from vigil.realtime import HUB
    for c in changes:
        HUB.publish("console", "intel.account_status", c.model_dump(mode="json"))
        STATE.counters["published_status"] += 1


def _snapshot(allow_full: bool) -> live.Snapshot | None:
    snap = live.CACHE.current(allow_full=allow_full)
    if snap is None:
        snap = live.CACHE.current(allow_full=True)
    return snap


# ── hook listener ─────────────────────────────────────────────────────────
def on_posting(tx: dict[str, Any]) -> None:
    """Hook listener: score one live posting and push status changes. Never raises."""
    started = time.perf_counter()
    try:
        if tx.get("kind") == "opening":
            return
        STATE.counters["postings"] += 1
        snap = _snapshot(allow_full=False)
        if snap is None:
            return
        view, _ = _sync(snap, publish=True)
        s, r = tx["sender_id"], tx["recipient_id"]
        vs, vr = view.get(s) or {}, view.get(r) or {}
        ms = round((time.perf_counter() - started) * 1000, 3)
        event = TxScored(
            tx_id=tx["id"], ts=tx["ts"], sender_id=s, recipient_id=r, amount_paise=int(tx["amount_paise"]),
            channel=tx.get("channel") or "upi", origin=_ORIGIN.get(tx.get("source") or "", tx.get("source") or "user"),
            scenario=tx.get("seed_attack"),      # SIMULATOR GROUND TRUTH tag, display only — never scored
            sender_status=vs.get("status", "external" if live.SRC.is_external(s) else "normal"),
            recipient_status=vr.get("status", "external" if live.SRC.is_external(r) else "normal"),
            sender_risk=vs.get("model_risk"), recipient_risk=vr.get("model_risk"), scored_ms=ms)
        from vigil.realtime import HUB
        HUB.publish("console", "intel.tx_scored", event.model_dump(mode="json"))
        STATE.counters["published_tx"] += 1
        STATE.latencies.append((time.perf_counter() - started) * 1000)
    except Exception as exc:
        STATE.counters["errors"] += 1
        log.warning("live detection stream failed for posting %s: %s", tx.get("id"), exc)


def register() -> None:
    from vigil.engine import hooks
    hooks.register(on_posting)


# ── public read functions (Claude 1: /api/live/universe, /api/live/stats, attack-run evaluation) ──
def status_map() -> dict[str, dict[str, Any]]:
    """account_id -> {status, risk, model_risk, role, families_flagging, reason} for every account.

    Cached per graph state, threshold, Vigil hold/label state and 5 s of wall time (idle depends on time).
    `risk` and `model_risk` are both the strongest calibrated model-evidence value (RF / GNN; corroborating
    evidence only, SYNTHETIC calibration); the RingWatch network score is the payment engine's and is not
    repeated here. Any status change found here is also pushed as `intel.account_status`. Never raises.
    """
    try:
        snap = _snapshot(allow_full=True)
        if snap is None:
            return {}
        view, _ = _sync(snap, publish=True)
        return {a: {k: v[k] for k in ("status", "risk", "model_risk", "role", "families_flagging", "reason")}
                for a, v in view.items()}
    except Exception as exc:
        STATE.counters["errors"] += 1
        log.warning("status_map failed: %s", exc)
        return {}


def roles_flagged() -> dict[str, int]:
    """Role counts over accounts whose live status is flagged or confirmed_fraud (role None -> 'unclassified')."""
    out: dict[str, int] = {}
    for v in status_map().values():
        if v["status"] in ("flagged", "confirmed_fraud"):
            r = v["role"] or "unclassified"
            out[r] = out.get(r, 0) + 1
    return dict(sorted(out.items()))


def current_threshold() -> float:
    return STATE.threshold


def threshold_history() -> list[dict[str, Any]]:
    """[{t, value, reason, previous, changed, run_id, ...}] — every evaluation, oldest first."""
    return [dict(h) for h in STATE.history]


def stats() -> dict[str, Any]:
    lat = sorted(STATE.latencies)

    def pct(q: float) -> float | None:
        return None if not lat else round(lat[min(len(lat) - 1, int(q * (len(lat) - 1) + 0.5))], 3)

    counts: dict[str, int] = {}
    for s in STATE.statuses.values():
        counts[s] = counts.get(s, 0) + 1
    return {"version": STREAM_VERSION, "window_minutes": LIVE_WINDOW_MINUTES, "new_account_days": NEW_ACCOUNT_DAYS,
            "threshold": STATE.threshold, "threshold_initial": STATE.initial, "threshold_bounds": [T_MIN, T_MAX],
            "threshold_step": T_STEP, "latency_ms": {"n": len(lat), "p50": pct(0.5), "p95": pct(0.95),
                                                     "max": round(lat[-1], 3) if lat else None},
            "status_counts": dict(sorted(counts.items())), **STATE.counters}


# ── adaptive model-evidence threshold (evaluation feedback) ───────────────
def _field(run: Any, name: str) -> Any:
    return run.get(name) if isinstance(run, dict) else getattr(run, name, None)


def threshold_step(T: float, fp_evidence: list[float], missed: list[tuple[float, bool]], n_injected: int,
                   collateral: Callable[[float], int]) -> tuple[float, str]:
    """One adaptive-threshold update (pure; shared with ml/eval_live_status.py's offline replay).

    fp_evidence: model evidence of each false positive; missed: (model evidence, corroborated by another family)
    of each missed injected mule; collateral(lowered_T): accounts outside the attack that lowering would newly
    flag. Returns (new threshold, reason).
    """
    fp_model = [e for e in fp_evidence if e >= T]
    if fp_model:
        new_t = _clamp(T + T_STEP)
        reason = (f"{len(fp_model)} false positive(s) let through by model evidence (max {max(fp_model):.2f} >= "
                  f"{T:.2f}) — raise one step")
        return new_t, reason + (f"; already at the upper bound {T_MAX:.2f}" if new_t == T else "")
    if fp_evidence:
        return T, f"{len(fp_evidence)} false positive(s), none let through by model evidence — unchanged"
    if missed:
        lowered = _clamp(T - T_STEP)
        near = [e for e, corr in missed if lowered <= e < T and corr]
        if near and lowered < T:
            n = collateral(lowered)
            if n:
                return T, (f"{len(near)} missed mule(s) just below the threshold, but lowering one step would also "
                           f"flag {n} account(s) outside this attack — unchanged")
            return lowered, (f"{len(near)} missed mule(s) with corroborated model evidence just below the threshold "
                             f"(max {max(near):.2f}) — lower one step")
        if near:
            return T, f"{len(near)} missed mule(s) just below the threshold; already at the lower bound {T_MIN:.2f}"
        best = max(e for e, _ in missed)
        return T, (f"{len(missed)} missed mule(s), none a corroborated near miss (strongest model evidence "
                   f"{best:.2f}); one step would not catch them — unchanged")
    if n_injected:
        return T, "all injected mules detected, no false positives — unchanged"
    return T, "run had no injected mule accounts — unchanged"


def on_run_evaluated(run: Any) -> None:
    """Adapt the live model-evidence threshold after one evaluated attack run. Never raises; idempotent per run.

    Rule (deterministic; one step of T_STEP at most; bounded to [T_MIN, T_MAX]):
      * a false positive whose model evidence reached the threshold (i.e. the threshold let it through)
        -> raise one step;
      * otherwise, a missed mule whose model evidence is a NEAR MISS (within one step below the threshold,
        corroborated by another family) -> lower one step, unless lowering would also newly flag an account
        outside this attack (then hold);
      * otherwise hold (all detected; or misses far below the threshold, which a step cannot fix).
    Every evaluation is logged in threshold_history() with its reason. Only the live "flagged" status uses
    this threshold; payment tiers never do.
    """
    try:
        run_id = str(_field(run, "run_id") or "")
        if run_id and run_id in STATE.evaluated_runs:
            return
        snap = _snapshot(allow_full=True)
        if snap is None:
            return
        _ensure_epoch(snap)
        injected = set(_field(run, "injected") or [])
        missed = list(_field(run, "missed") or [])
        fps = list(_field(run, "false_positives") or [])
        recall = _field(run, "recall")
        T = STATE.threshold

        def ev(a: str) -> tuple[float, bool]:
            if a not in snap.feats:
                return 0.0, False
            risk, fam = model_evidence(snap, a)
            return (risk or 0.0), any(f != fam for f in _flagging(snap, a))

        def collateral(lowered: float) -> int:
            n = 0
            for a in snap.ids:
                if a not in injected:
                    e, corr = ev(a)
                    n += int(lowered <= e < T and corr)
            return n

        new_t, reason = threshold_step(T, [ev(a)[0] for a in fps], [ev(a) for a in missed], len(injected), collateral)
        name = _field(run, "scenario_id") or ""
        STATE.history.append({
            "t": clock.now_iso(), "value": new_t, "previous": T, "changed": new_t != T, "run_id": run_id or None,
            "scenario_id": name or None, "recall": recall, "false_positives": len(fps), "missed": len(missed),
            "reason": f"{name + ': ' if name else ''}{reason}"})
        if len(STATE.history) > 500:
            STATE.history = STATE.history[:1] + STATE.history[-499:]
        if run_id:
            STATE.evaluated_runs.add(run_id)
        if new_t != T:
            STATE.threshold = new_t
            _sync(snap, publish=True)           # statuses that the new threshold changes are pushed at once
    except Exception as exc:
        STATE.counters["errors"] += 1
        log.warning("on_run_evaluated failed: %s", exc)


register()
