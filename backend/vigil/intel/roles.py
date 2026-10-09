"""Mule role assessment: coordinator / collector / distributor / entry / exit / unclassified.

Port of classify_fraud_roles (ccmule detection.py:206-249) with repairs:
  * roles are only assigned to accounts with CORROBORATED MULE EVIDENCE (`gate`): at least 2 account-level
    families flag the account AND at least one of them is a structural / model family (RF, GNN, pattern
    memory, RingWatch) or the registry listing (consensus.MULE_EVIDENCE_FAMILIES). The original applied
    roles to everyone, so every bill-payer became an 'Entry Node'; roles-v2.0 required any 2 families, so a
    salaried customer whose salary and rent fell in the same 72 h (drift + early warning) became a
    'distributor'. A change in behaviour is not a mule role (roles-v2.1; ML_VALIDATION_REPORT §7);
  * entry/exit are defined by position relative to the FLAGGED network (the accounts that pass the same
    gate: where money enters / leaves it), using observed window edges, instead of 'in_degree == 0'.
A role is a structural description of the account's position in the money flow, not an accusation.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from vigil.intel.consensus import ACCOUNT_FAMILIES, CHANGE_FAMILIES, MULE_EVIDENCE_FAMILIES, SHORT
from vigil.intel.features import WINDOW_S, GraphSource

ROLES_VERSION = "roles-v2.1"
ROLE_MIN_FAMILIES = 2
NO_FLAG_REASON = "No corroborated detector flag; roles are only assigned inside suspicious structure."


def gate(flags: Mapping[str, bool]) -> tuple[bool, str]:
    """Is the account eligible for a mule role? (eligible, reason when not). Pure; also used by ml/.

    `flags` maps family -> flagged for the ACCOUNT-level families (consensus.ACCOUNT_FAMILIES); payment-
    journey families (trailscore, context) are ignored.
    """
    on = [f for f in ACCOUNT_FAMILIES if flags.get(f)]
    if len(on) < ROLE_MIN_FAMILIES:
        return False, NO_FLAG_REASON
    # consensus-v2.2: model families alone are not mule structure for an account measured NOT to move received
    # money on ("_onward" is False only when RingWatch measured the flow; absent/None never downgrades)
    if (flags.get("_onward") is False and set(on) & {"random_forest", "gnn"}
            and not set(on) & (MULE_EVIDENCE_FAMILIES - {"random_forest", "gnn"})):
        names = ", ".join(SHORT.get(f, f) for f in on)
        return False, (f"Flagged by {names}, but the account does not move received money on — paying out of its own "
                       "balance (as a scam victim does) is not mule structure. Roles are only assigned inside "
                       "corroborated mule structure.")
    if not set(on) & MULE_EVIDENCE_FAMILIES:
        names = ", ".join(SHORT.get(f, f) for f in on)
        lead = (f"Behaviour changed ({names})" if set(on) <= CHANGE_FAMILIES
                else f"Flagged by change / heuristic signals only ({names})")
        return False, (f"{lead}, but there is no mule-structure evidence: no structural or model family (RF, GNN, "
                       "pattern memory, RingWatch) and no registry listing flags this account. Roles are only "
                       "assigned inside corroborated mule structure.")
    return True, ""


def assess(src: GraphSource, account_id: str, now_t: float, f: dict[str, float], flagged: set[str],
           flags: Mapping[str, bool], in_cycle: bool = False,
           gate_fn: Callable[[Mapping[str, bool]], tuple[bool, str]] | None = None) -> dict[str, Any]:
    """Role of `account_id`. `flagged` = the accounts that pass the gate (the flagged network); `flags` = this
    account's family -> flagged map. `gate_fn` replaces `gate` only for offline before/after evaluation."""
    start = now_t - WINDOW_S
    w_in = [e for e in src.inflows(account_id) if start < e.t <= now_t]
    w_out = [e for e in src.outflows(account_id) if start < e.t <= now_t]
    tin = sum(e.amount_paise for e in w_in)
    tout = sum(e.amount_paise for e in w_out)
    fl_in = sum(e.amount_paise for e in w_in if e.src in flagged) / tin if tin else 0.0
    fl_out = sum(e.amount_paise for e in w_out if e.dst in flagged) / tout if tout else 0.0
    ext_out = sum(e.amount_paise for e in w_out if src.is_external(e.dst)) / tout if tout else 0.0
    flagged_cps = len(({e.src for e in w_in} | {e.dst for e in w_out}) & (flagged - {account_id}))
    eligible, why = (gate_fn or gate)(flags)
    ev = {"in_degree": f["in_degree"], "out_degree": f["out_degree"], "unique_neighbors": f["unique_neighbors"],
          "retention_ratio": round(f["retention_ratio"], 3), "forwarded_fraction": f["forwarded_fraction"],
          "inflow_from_flagged_share": round(fl_in, 3), "outflow_to_flagged_share": round(fl_out, 3),
          "outflow_to_external_share": round(ext_out, 3), "flagged_counterparties": flagged_cps, "in_cycle": in_cycle,
          "families_flagging": [x for x in ACCOUNT_FAMILIES if flags.get(x)],
          "mule_evidence_families": [x for x in ACCOUNT_FAMILIES if flags.get(x) and x in MULE_EVIDENCE_FAMILIES],
          "gate": f"{ROLES_VERSION}: >= {ROLE_MIN_FAMILIES} account-level families flag, at least one structural / "
                  "model family or registry listing"}
    if not eligible:
        return {"role": "unclassified", "evidence": ev, "reason": why}
    i, o, n, ret = f["in_degree"], f["out_degree"], f["unique_neighbors"], f["retention_ratio"]
    if (i >= 2 and o >= 2 and n >= 4 and ret < 0.5) or (in_cycle and flagged_cps >= 2):
        return {"role": "coordinator", "evidence": ev,
                "reason": f"Both receives from {i:.0f} and pays {o:.0f} accounts in 72 h"
                          + (" and sits on a circular flow" if in_cycle else "") + f", keeping {ret:.0%}."}
    if i >= 3 and i > o and ret < 0.3:
        return {"role": "collector", "evidence": ev,
                "reason": f"Collects from {i:.0f} senders and moves {1 - ret:.0%} of it on."}
    if o >= 3 and o >= i and (ret < 0.3 or tin == 0):
        return {"role": "distributor", "evidence": ev,
                "reason": f"Spreads money to {o:.0f} recipients in 72 h."}
    if tin and fl_in < 0.5 and fl_out >= 0.5 and f["forwarded_fraction"] >= 0.5:
        return {"role": "entry", "evidence": ev,
                "reason": f"Money from outside the flagged group enters here and {fl_out:.0%} of outflow goes to flagged accounts."}
    if fl_in >= 0.5 and (ext_out >= 0.5 or ret > 0.6):
        where = "leaves the bank's view (cash / other bank)" if ext_out >= 0.5 else "stops here"
        return {"role": "exit", "evidence": ev,
                "reason": f"{fl_in:.0%} of its inflow comes from flagged accounts and the money {where}."}
    if i > o and ret < 0.3:
        return {"role": "collector", "evidence": ev, "reason": f"Receives from more accounts than it pays and keeps only {ret:.0%}."}
    if o > i and ret < 0.3:
        return {"role": "distributor", "evidence": ev, "reason": f"Pays more accounts than it receives from and keeps only {ret:.0%}."}
    return {"role": "unclassified", "evidence": ev,
            "reason": "Flagged, but its position in the money flow does not match a defined role."}
