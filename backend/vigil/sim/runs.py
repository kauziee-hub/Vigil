"""Attack runs — every execution of an attack scenario, evaluated against SIMULATOR GROUND TRUTH.

The ground-truth mule list per scenario lives HERE (evaluation only). Nothing on
the detection or authorisation path reads it. Evaluation uses the live status
resolver (`engine.livestatus`) after every step and for a short grace period
after the last step, recording when the first injected mule reached early
warning and when the first reached flagged (latency from the first attack
posting), precision / recall over the run's participants, and false positives.
Runs live in memory and are cleared by a demo reset.
"""

from __future__ import annotations

import time
from typing import Any

from vigil import clock
from vigil.contracts import AttackRun
from vigil.engine import livestatus
from vigil.realtime import HUB

GRACE_S = 4.0


def ground_truth_mules(scenario_id: str) -> list[str]:
    """SIMULATOR GROUND TRUTH — which accounts act as mules in this scenario (evaluation only)."""
    from vigil.sim import attacks, seed

    fixed = {
        "s2": ["kiran.traders@vigil", "zenith.exports@vigil", *seed.DOWNSTREAM],
        "atk_fan_in": ["swift.collect@vigil"],
        "atk_fan_out": ["bulk.payouts@vigil"],
        "atk_shared_device": ["dc.one@vigil", "dc.two@vigil", "dc.three@vigil", "dc.four@vigil", "dc.hub@vigil"],
        "atk_volume_spike": ["fresh.wallet@vigil"],
        "atk_dormant": ["dormant.savings@vigil"],
    }
    if scenario_id in fixed:
        return fixed[scenario_id]
    pool = attacks.pool(scenario_id) if scenario_id in attacks.ATTACK_ORDER else []
    return {
        "atk_circular": pool[:4],
        "atk_velocity_chain": pool[:5],
        "atk_cross_channel": pool[:1],
        "atk_behavioural_drift": pool[:1],
        "atk_smurfing": pool[:1],
    }.get(scenario_id, [])


class _Tracker:
    def __init__(self, run: AttackRun, participants: list[str]) -> None:
        self.run = run
        self.participants = participants
        self.first_tx_t: float | None = None
        self.warned_t: float | None = None
        self.detected_t: float | None = None


RUNS: dict[str, _Tracker] = {}
ORDER: list[str] = []


def clear() -> None:
    RUNS.clear()
    ORDER.clear()


def is_tracked(scenario_id: str) -> bool:
    return bool(ground_truth_mules(scenario_id))


def begin(scenario_id: str, run_id: str, name: str, category: str, steps_total: int) -> AttackRun | None:
    if not is_tracked(scenario_id):
        return None
    from vigil.sim import scenarios

    run = AttackRun(run_id=run_id, scenario_id=scenario_id, name=name, category=category, status="running",
                    started_at=clock.now_iso(), steps_total=steps_total, steps_done=0,
                    injected=ground_truth_mules(scenario_id), model_threshold=_threshold())
    RUNS[run_id] = _Tracker(run, scenarios.touched_accounts(scenario_id))
    ORDER.append(run_id)
    _publish(run)
    return run


def _threshold() -> float | None:
    try:
        from vigil.intel import stream  # type: ignore[import-not-found]
        return float(stream.current_threshold())
    except Exception:
        return None


def _count_tx(result: Any) -> int:
    if isinstance(result, dict):
        return 1 if result.get("transaction_id") else 0
    if isinstance(result, (list, tuple)):
        return sum(_count_tx(r) for r in result)
    return 0


def _evaluate(tr: _Tracker) -> None:
    run = tr.run
    sts = livestatus.statuses(tr.participants)
    now_t = time.perf_counter()
    warned = [a for a in tr.participants if livestatus.is_warned(sts.get(a, {}).get("status", "normal"))]
    detected = [a for a in tr.participants if livestatus.is_detected(sts.get(a, {}).get("status", "normal"))]
    injected = set(run.injected)
    if tr.first_tx_t is not None:
        if tr.warned_t is None and injected & set(warned):
            tr.warned_t = now_t
        if tr.detected_t is None and injected & set(detected):
            tr.detected_t = now_t
    # once warned/detected during the run, an account stays counted (statuses can decay later)
    run.warned = sorted(set(run.warned) | set(warned))
    run.detected = sorted(set(run.detected) | set(detected))
    hits = injected & set(run.detected)
    run.missed = sorted(injected - set(run.detected))
    run.false_positives = sorted(set(run.detected) - injected)
    run.recall = round(len(hits) / len(injected), 3) if injected else None
    run.precision = round(len(hits) / len(run.detected), 3) if run.detected else None
    if tr.first_tx_t is not None:
        run.first_warning_ms = round((tr.warned_t - tr.first_tx_t) * 1000, 1) if tr.warned_t else None
        run.detection_ms = round((tr.detected_t - tr.first_tx_t) * 1000, 1) if tr.detected_t else None


def after_step(run_id: str, result: Any) -> None:
    tr = RUNS.get(run_id)
    if tr is None:
        return
    n = _count_tx(result)
    if n and tr.first_tx_t is None:
        tr.first_tx_t = time.perf_counter()
    tr.run.tx_count += n
    tr.run.steps_done += 1
    _evaluate(tr)
    _publish(tr.run)


def set_paused(run_id: str, paused: bool) -> None:
    tr = RUNS.get(run_id)
    if tr and tr.run.status in {"running", "paused"}:
        tr.run.status = "paused" if paused else "running"
        _publish(tr.run)


def finish(run_id: str) -> AttackRun | None:
    tr = RUNS.get(run_id)
    if tr is None:
        return None
    _evaluate(tr)
    tr.run.status = "completed"
    tr.run.completed_at = clock.now_iso()
    try:
        from vigil.intel import stream  # type: ignore[import-not-found]
        stream.on_run_evaluated(tr.run)
    except Exception:
        pass
    _publish(tr.run)
    return tr.run


def mark_evaluating(run_id: str) -> None:
    tr = RUNS.get(run_id)
    if tr:
        tr.run.status = "evaluating"
        _evaluate(tr)
        _publish(tr.run)


def poll(run_id: str) -> None:
    tr = RUNS.get(run_id)
    if tr:
        _evaluate(tr)


def _publish(run: AttackRun) -> None:
    HUB.publish("console", "attack.run_updated", run.model_dump(mode="json"))


def all_runs() -> list[AttackRun]:
    return [RUNS[r].run for r in reversed(ORDER)]


def get(run_id: str) -> AttackRun:
    tr = RUNS.get(run_id)
    if tr is None:
        from vigil.engine.ledger import VigilError
        raise VigilError(404, "unknown_run", f"No attack run '{run_id}'.")
    return tr.run

