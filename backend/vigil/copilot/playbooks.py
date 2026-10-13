"""Vigilance procedures: what a bank does next, step by step, for each kind of alert.

Every incident kind has a playbook of ordered steps in four phases — CONTAIN (stop money leaving), INVESTIGATE (find
out what happened), REPORT (regulatory and law-enforcement duties) and RECOVER & CLOSE. Each step says who does it,
how soon, why, and either opens the right place in Vigil (an in-app step) or names the outside process (an outside
step: Vigil never freezes accounts, files reports or calls customers itself).

Steps complete in two ways:
  * automatically, when Vigil can see the outcome (the hold was released or rejected, the trusted contact answered,
    the account is on the watchlist, a scam was confirmed, the alert was acknowledged);
  * manually, when the analyst ticks them (stored in `copilot_playbook_steps`, cleared by a demo reset).

The procedures are an ILLUSTRATIVE bank SOP modelled on commonly cited Indian requirements (not legal advice):
  * PMLA rules: the Principal Officer files a Suspicious Transaction Report (STR) with FIU-IND within seven working
    days of concluding that a transaction is suspicious;
  * RBI Master Directions on Fraud Risk Management (July 2024): frauds are reported to RBI through the Fraud
    Monitoring Return (FMR) within 14 days; early-warning signals and red-flagging of accounts;
  * RBI circular of 6 July 2017 on limiting customer liability: zero liability for a third-party breach reported
    within three working days; shadow credit of the amount within ten working days of the customer's report;
  * I4C's Citizen Financial Cyber Fraud Reporting and Management System (helpline 1930, cybercrime.gov.in): banks
    and police act on a reported fraud in near real time to stop the money trail.
Nothing here changes a status, a hold or a payment tier.
"""

from __future__ import annotations

from typing import Any

from vigil import clock, db

PHASES = [("contain", "Contain", "Stop money leaving while it is still inside the bank"),
          ("investigate", "Investigate", "Establish what happened and who is involved"),
          ("report", "Report", "Regulatory and law-enforcement duties, with their deadlines"),
          ("close", "Recover & close", "Recover what can be recovered, record the outcome")]

# Respond-within targets by severity (an operational service level for this demo, not a regulation).
RESPOND = {"critical": (15, "15 minutes"), "high": (60, "1 hour"), "medium": (240, "4 hours"), "low": (1440, "24 hours")}

# Plain classification of each incident kind: what it is, and the fraud typology it belongs to.
CLASS = {
    "ring_formed": ("Mule ring forming", "Money laundering: layering through mule accounts"),
    "account_flagged": ("Suspected mule account", "Money-mule activity"),
    "cash_out_cluster": ("Cash-out in progress", "Money laundering: integration through ATM cash"),
    "impossible_travel": ("Possible account takeover", "Account takeover (one account, two distant places)"),
    "payment_held_t3": ("Payment held for review", "Authorised push payment risk"),
    "tier4_coercion": ("Customer under coercion", "Social engineering: 'digital arrest' style scam"),
    "fast_pass_through_new_account": ("New account passing money through", "Mule onboarding"),
    "device_farm": ("Device farm", "Controlled or synthetic accounts on one device"),
    "confirmed_scam_trace": ("Stolen money traced", "Recovery opportunity"),
}

# Step fields: id, phase, title, detail (how / why), owner, when, and either `ui` (an in-app action spec) or
# `outside` (an external process); `auto` names a rule that completes the step from Vigil's own data.
_STR = {"id": "str", "phase": "report", "owner": "Principal Officer (AML)", "when": "within 7 working days",
        "title": "File a Suspicious Transaction Report with FIU-IND",
        "detail": "PMLA rules: once the bank concludes the transactions are suspicious, the Principal Officer records "
                  "the reasons and files the STR (FINnet) within seven working days. Attach the case record and the "
                  "money trail from Vigil.", "outside": "FIU-IND FINnet"}
_FMR = {"id": "fmr", "phase": "report", "owner": "Fraud risk / compliance", "when": "within 14 days",
        "title": "Report the fraud to RBI (Fraud Monitoring Return)",
        "detail": "If the bank classifies the case as fraud, RBI's Master Directions on Fraud Risk Management (2024) "
                  "require the FMR within 14 days.", "outside": "RBI FMR"}
_1930 = {"id": "lea", "phase": "close", "owner": "Fraud operations", "when": "as soon as possible",
         "title": "Coordinate on 1930 / cybercrime.gov.in to stop the money trail",
         "detail": "Through I4C's Citizen Financial Cyber Fraud Reporting and Management System, banks and police put "
                   "holds on money that has moved on to other banks before it is withdrawn.",
         "outside": "1930 helpline / CFCFRMS"}
_CLOSE = {"id": "close", "phase": "close", "owner": "Fraud analyst", "when": "when done",
          "title": "Record the outcome and acknowledge the alert",
          "detail": "Write what was found and done; acknowledging keeps the alert in the record but off the open list.",
          "ui": "ack", "auto": "acknowledged"}

PLAYBOOKS: dict[str, list[dict[str, Any]]] = {
    "ring_formed": [
        {"id": "confirm", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Confirm the ring in the network",
         "detail": "Check who pays whom, how fast money moves through, and which members are already flagged.",
         "ui": "show_in_network"},
        {"id": "watch", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Put members that are not yet flagged on close monitoring",
         "detail": "So every new movement from them is in front of you.", "ui": "watch_account", "auto": "watched"},
        {"id": "pending", "phase": "contain", "owner": "Fraud analyst", "when": "within the hour",
         "title": "Review pending outgoing payments from members",
         "detail": "Vigil's payment gate already holds risky ones; release only with evidence.", "ui": "open_page:/interventions"},
        {"id": "freeze", "phase": "contain", "owner": "Branch / operations", "when": "per bank policy",
         "title": "Request a debit freeze or lien on member accounts",
         "detail": "Vigil never freezes an account. A debit freeze or lien is a bank decision under its policy, usually on "
                   "a law-enforcement request, with the Principal Officer informed.", "outside": "Core banking"},
        {"id": "trace", "phase": "investigate", "owner": "Fraud analyst", "when": "today",
         "title": "Trace where the money came from and where it went",
         "detail": "Victims who paid in are the first people to contact; accounts it went on to are the next holds.",
         "ui": "open_connections"},
        {"id": "kyc", "phase": "investigate", "owner": "KYC team", "when": "within 2 days",
         "title": "Re-verify KYC of member accounts",
         "detail": "Video KYC or branch visit; check documents, device and IP sharing, and the stated purpose of the account.",
         "outside": "KYC / branch"},
        {"id": "registry", "phase": "investigate", "owner": "Fraud analyst", "when": "today",
         "title": "Check identifiers against suspect registries",
         "detail": "The bank's negative list and, where the bank has access, the I4C suspect registry (simulated in this demo).",
         "outside": "Registry lookup"},
        {"id": "confirm_scam", "phase": "report", "owner": "Fraud analyst", "when": "when a victim confirms",
         "title": "Mark victim payments as confirmed scams",
         "detail": "Confirming starts TaintTrace, which follows the stolen money and holds the next payments to accounts "
                   "that hold it (Tier 3 floor). In Vigil: Network → Evidence scene → payment drawer → Confirm scam.",
         "ui": "show_in_network", "auto": "scam_confirmed"},
        _STR, _FMR, _1930, _CLOSE],
    "account_flagged": [
        {"id": "why", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Read why the account is flagged", "detail": "Reasons, rules fired, detector agreement and its role.",
         "ui": "select_entity"},
        {"id": "watch", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Add it to close monitoring", "detail": "Every new movement is shown with what would escalate it.",
         "ui": "watch_account", "auto": "watched"},
        {"id": "pending", "phase": "contain", "owner": "Fraud analyst", "when": "within the hour",
         "title": "Review its pending outgoing payments", "detail": "Held payments wait for a bank decision.",
         "ui": "open_page:/interventions"},
        {"id": "trace", "phase": "investigate", "owner": "Fraud analyst", "when": "today",
         "title": "Trace its money, upstream and downstream", "detail": "Who funded it and where the money went next.",
         "ui": "open_connections"},
        {"id": "cdd", "phase": "investigate", "owner": "Branch / relationship manager", "when": "within 2 days",
         "title": "Customer due diligence call and re-KYC",
         "detail": "Ask about the purpose of the account and the inflows; a recruited mule often cannot explain them.",
         "outside": "Branch"},
        _STR, _CLOSE],
    "cash_out_cluster": [
        {"id": "map", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "See the withdrawals on the map", "detail": "Which ATMs, how close together, how fast.", "ui": "show_on_map"},
        {"id": "cards", "phase": "contain", "owner": "Card operations", "when": "now",
         "title": "Block the cards and hold remaining balances",
         "detail": "Per bank policy; cash already withdrawn is unrecoverable, the rest is not.", "outside": "Card management"},
        {"id": "funding", "phase": "investigate", "owner": "Fraud analyst", "when": "today",
         "title": "Find who funded the accounts", "detail": "The upstream accounts are the rest of the network.",
         "ui": "open_connections"},
        {"id": "cctv", "phase": "investigate", "owner": "Branch security", "when": "within the CCTV retention window",
         "title": "Preserve ATM CCTV and journal logs", "detail": "Evidence for the police; footage is overwritten after a while.",
         "outside": "ATM network / branch"},
        _1930, _STR, _CLOSE],
    "impossible_travel": [
        {"id": "map", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "See both locations on the map", "detail": "Two device fixes too far apart for the time between them.",
         "ui": "show_on_map"},
        {"id": "changes", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Check recent device, payee and limit changes", "detail": "Account takeover usually starts with these.",
         "ui": "select_entity"},
        {"id": "call", "phase": "contain", "owner": "Customer service", "when": "within the hour",
         "title": "Call the customer on the registered number",
         "detail": "Confirm whether they made the recent logins and payments. Never use a number from the session.",
         "outside": "Phone"},
        {"id": "secure", "phase": "investigate", "owner": "Digital banking", "when": "if not the customer",
         "title": "End sessions and reset credentials", "detail": "Revoke the unknown device binding.", "outside": "Digital banking"},
        {"id": "liability", "phase": "report", "owner": "Customer service", "when": "within 10 working days",
         "title": "Apply the customer-liability rules if money was taken",
         "detail": "RBI circular of 6 July 2017: zero liability for a third-party breach reported within 3 working days; "
                   "shadow-credit the amount within 10 working days of the report.", "outside": "Disputes"},
        _CLOSE],
    "payment_held_t3": [
        {"id": "case", "phase": "contain", "owner": "Fraud analyst", "when": "within the 30-minute review window",
         "title": "Open the held payment and read the reasons", "detail": "Every rule that fired, with its evidence.",
         "ui": "open_case"},
        {"id": "recipient", "phase": "investigate", "owner": "Fraud analyst", "when": "within the review window",
         "title": "Check the recipient account", "detail": "Its network evidence, detector agreement and history.",
         "ui": "select_recipient"},
        {"id": "call", "phase": "investigate", "owner": "Customer service", "when": "within the review window",
         "title": "Call the customer on the registered number",
         "detail": "Ask who the recipient is and how they were contacted; scam victims are often coached to lie.",
         "outside": "Phone"},
        {"id": "decide", "phase": "contain", "owner": "Fraud analyst", "when": "before the review deadline",
         "title": "Release or reject the payment", "detail": "Release sends it; reject closes it without sending anything.",
         "ui": "open_page:/interventions", "auto": "hold_decided"},
        {"id": "victim", "phase": "report", "owner": "Customer service", "when": "if it was a scam",
         "title": "Help the customer report on 1930 / cybercrime.gov.in",
         "detail": "And confirm the scam in Vigil so TaintTrace follows any money that already moved.", "outside": "1930"},
        _CLOSE],
    "tier4_coercion": [
        {"id": "contact", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Check the trusted contact's response", "detail": "The CircuitBreaker alerted them with facts.",
         "ui": "open_case", "auto": "contact_responded"},
        {"id": "call", "phase": "contain", "owner": "Customer service", "when": "within 15 minutes",
         "title": "Call the customer on the registered number",
         "detail": "Explain calmly that police and RBI never ask anyone to move money for 'verification' and that "
                   "'digital arrest' is a known scam. Keep them on the line if the caller is still active.", "outside": "Phone"},
        {"id": "hold", "phase": "contain", "owner": "Fraud analyst", "when": "until the customer is safe",
         "title": "Keep the hold until the customer confirms they are safe, then decide",
         "detail": "Reject if it is a scam; release only on clear evidence.", "ui": "open_page:/interventions", "auto": "hold_decided"},
        {"id": "recipient", "phase": "investigate", "owner": "Fraud analyst", "when": "today",
         "title": "Check the recipient account", "detail": "Recipients of coerced payments are often mule accounts.",
         "ui": "select_recipient"},
        {"id": "victim", "phase": "report", "owner": "Customer service", "when": "as soon as possible",
         "title": "Help the customer report on 1930 / cybercrime.gov.in", "detail": "Even if no money left the bank.",
         "outside": "1930"},
        {"id": "liability", "phase": "report", "owner": "Customer service", "when": "within 10 working days",
         "title": "If money was already lost elsewhere, apply the customer-liability rules",
         "detail": "RBI circular of 6 July 2017 (reporting within 3 working days, shadow credit within 10).",
         "outside": "Disputes"},
        _CLOSE],
    "fast_pass_through_new_account": [
        {"id": "timeline", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Open the account timeline", "detail": "How quickly it received and forwarded money.", "ui": "select_entity"},
        {"id": "watch", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Add it to close monitoring", "detail": "A new account forwarding most of its inflow is the first job of a mule.",
         "ui": "watch_account", "auto": "watched"},
        {"id": "trace", "phase": "investigate", "owner": "Fraud analyst", "when": "today",
         "title": "Check who funds it and where the money goes", "detail": "", "ui": "open_connections"},
        {"id": "edd", "phase": "investigate", "owner": "Branch / KYC", "when": "within 2 days",
         "title": "Enhanced due diligence on the new account",
         "detail": "Purpose, expected turnover, occupation; compare with what the account is actually doing.", "outside": "Branch"},
        _STR, _CLOSE],
    "device_farm": [
        {"id": "accounts", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Open the accounts that share the device", "detail": "", "ui": "show_in_network"},
        {"id": "watch", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Watch the ones not yet flagged", "detail": "", "ui": "watch_account", "auto": "watched"},
        {"id": "binding", "phase": "investigate", "owner": "Digital banking", "when": "today",
         "title": "Restrict new device bindings from that device", "detail": "Stops new mule accounts being added.",
         "outside": "Digital banking"},
        {"id": "kyc", "phase": "investigate", "owner": "KYC team", "when": "within 2 days",
         "title": "Check the onboarding channel and KYC documents of every account", "detail": "", "outside": "KYC"},
        _STR, _CLOSE],
    "confirmed_scam_trace": [
        {"id": "holders", "phase": "contain", "owner": "Fraud analyst", "when": "now",
         "title": "Open the accounts holding traced money", "detail": "Largest holders first.", "ui": "show_in_network"},
        {"id": "lien", "phase": "contain", "owner": "Operations", "when": "as soon as possible",
         "title": "Request a lien on the traced amounts",
         "detail": "Per bank policy and the police request received through 1930 / CFCFRMS.", "outside": "Core banking"},
        {"id": "refund", "phase": "report", "owner": "Customer service", "when": "within 10 working days",
         "title": "Refund the victim under the customer-liability rules if eligible",
         "detail": "RBI circular of 6 July 2017.", "outside": "Disputes"},
        _FMR, _1930, _CLOSE],
}


# ── state ────────────────────────────────────────────────────────────────
def _manual(incident_id: str) -> dict[str, dict[str, Any]]:
    return {r["step_id"]: r for r in db.q("SELECT step_id, done, done_ts, done_by FROM copilot_playbook_steps "
                                          "WHERE incident_id = ?", (incident_id,))}


def _auto(rule: str | None, inc: dict[str, Any]) -> tuple[bool, str | None]:
    """(done, evidence) for an automatic completion rule, from Vigil's own data. Never raises."""
    if not rule:
        return False, None
    try:
        ents = inc["entities"]
        intent = (inc.get("summary") or {}).get("key_extra")
        if rule == "acknowledged":
            return inc["status"] == "acknowledged", "alert acknowledged" if inc["status"] == "acknowledged" else None
        if rule == "watched":
            pinned = {r["account_id"] for r in db.q("SELECT account_id FROM watchlist")}
            hits = [a for a in ents if a in pinned]
            return bool(hits), f"watching {len(hits)} of {len(ents)}" if hits else None
        if rule == "hold_decided" and intent:
            row = db.q1("SELECT state FROM transaction_intents WHERE id = ?", (intent,))
            st = row["state"] if row else None
            done = st in ("APPROVED", "REJECTED", "CANCELLED", "PAYMENT_INITIATED", "PAYMENT_SUCCEEDED", "MONITORED")
            return done, f"payment {st.lower().replace('_', ' ')}" if done else None
        if rule == "contact_responded" and intent:
            row = db.q1("SELECT response FROM circuit_breaker_events WHERE intent_id = ? AND response IS NOT NULL "
                        "ORDER BY fired_at DESC LIMIT 1", (intent,))
            return bool(row), f"contact: {row['response'].replace('_', ' ')}" if row else None
        if rule == "scam_confirmed" and ents:
            marks = ",".join("?" * len(ents))
            n = db.scalar(f"SELECT COUNT(*) FROM fraud_labels l JOIN transactions t ON t.id = l.transaction_id "
                          f"WHERE t.recipient_id IN ({marks}) OR t.sender_id IN ({marks})", tuple(ents) + tuple(ents))
            return bool(n), f"{n} confirmed scam label(s)" if n else None
    except Exception:
        return False, None
    return False, None


def ui_action(spec: str | None, inc: dict[str, Any]) -> dict[str, str] | None:
    """Resolve a step's action spec to a concrete, whitelisted UI action for this incident."""
    if not spec or spec == "ack":
        return None
    ents = inc["entities"]
    intent_dec = None
    intent = (inc.get("summary") or {}).get("key_extra")
    if intent:
        row = db.q1("SELECT decision_id FROM alerts WHERE intent_id = ? ORDER BY ts DESC LIMIT 1", (intent,))
        intent_dec = row["decision_id"] if row else None
    if spec.startswith("open_page:"):
        return {"type": "open_page", "target": spec.split(":", 1)[1]}
    if spec == "open_case":
        return {"type": "open_page", "target": f"/investigations/decision/{intent_dec}"} if intent_dec else \
            {"type": "open_page", "target": "/interventions"}
    if spec == "select_recipient":           # entities are stored sorted: take the payee from the bank alert itself
        row = db.q1("SELECT recipient_id FROM alerts WHERE intent_id = ? ORDER BY ts DESC LIMIT 1", (intent,)) if intent else None
        rcp = row["recipient_id"] if row else (ents[-1] if ents else None)
        return {"type": "open_page", "target": f"/investigations/account/{rcp}"} if rcp else None
    if spec == "select_entity":
        return {"type": "open_page", "target": f"/investigations/account/{ents[0]}"} if ents else None
    if spec == "show_in_network":
        return {"type": "show_in_network", "target": ",".join(ents[:12])} if ents else None
    if spec == "watch_account":
        from vigil import overview
        sts = overview.statuses()
        cand = [a for a in ents if sts.get(a, {}).get("status") not in ("flagged", "held", "confirmed_fraud")] or ents
        return {"type": "watch_account", "target": cand[0]} if cand else None
    if spec == "open_connections":
        from vigil.graph.pathgraph import GRAPH
        if inc.get("tx_ids"):
            return {"type": "open_connections", "target": inc["tx_ids"][0]}
        for a in ents:
            lst = GRAPH.out_edges.get(a) or GRAPH.in_edges.get(a) or []
            if lst:
                return {"type": "open_connections", "target": lst[-1].tx_id}
        return None
    if spec == "show_on_map":
        city = (inc.get("summary") or {}).get("city")
        return {"type": "show_on_map", "target": city or (ents[0] if ents else "")}
    return None


def view(inc: dict[str, Any]) -> dict[str, Any]:
    """The procedure for one incident, with each step's state (auto / manual / open) and its concrete action."""
    steps_def = PLAYBOOKS.get(inc["kind"], [_CLOSE])
    manual = _manual(inc["id"])
    steps = []
    for s in steps_def:
        auto_done, evidence = _auto(s.get("auto"), inc)
        m = manual.get(s["id"])
        done = auto_done or bool(m and m["done"])
        steps.append({
            "id": s["id"], "phase": s["phase"], "title": s["title"], "detail": s.get("detail", ""),
            "owner": s["owner"], "when": s["when"], "kind": "inside" if (s.get("ui") or s.get("auto")) else "outside",
            "outside": s.get("outside"), "ui_action": ui_action(s.get("ui"), inc), "acknowledge": s.get("ui") == "ack",
            "auto_rule": s.get("auto"), "done": done, "done_by": "vigil" if auto_done else (m["done_by"] if m and m["done"] else None),
            "evidence": evidence or (f"ticked by {m['done_by']} at {m['done_ts'][11:16]} UTC" if m and m["done"] else None),
        })
    done = sum(1 for s in steps if s["done"])
    nxt = next((s for s in steps if not s["done"]), None)
    label, typology = CLASS.get(inc["kind"], (inc["kind"], ""))
    mins, text = RESPOND.get(inc["severity"], RESPOND["medium"])
    return {"incident_id": inc["id"], "classification": label, "typology": typology, "severity": inc["severity"],
            "respond_within": text, "respond_minutes": mins, "phases": [{"id": p, "label": l, "goal": g} for p, l, g in PHASES],
            "steps": steps, "done": done, "total": len(steps), "next_step": nxt["id"] if nxt else None,
            "note": "Illustrative bank procedure modelled on Indian requirements (PMLA STR, RBI fraud reporting, RBI 2017 "
                    "customer liability, 1930 / CFCFRMS). Not legal advice. Vigil never freezes, reports or calls itself."}


def set_step(inc: dict[str, Any], step_id: str, done: bool, by: str = "analyst") -> dict[str, Any] | None:
    if step_id not in {s["id"] for s in PLAYBOOKS.get(inc["kind"], [_CLOSE])}:
        return None
    db.execute("INSERT INTO copilot_playbook_steps(incident_id, step_id, done, done_ts, done_by) VALUES(?, ?, ?, ?, ?) "
               "ON CONFLICT(incident_id, step_id) DO UPDATE SET done = excluded.done, done_ts = excluded.done_ts, "
               "done_by = excluded.done_by", (inc["id"], step_id, 1 if done else 0, clock.now_iso(), by))
    return view(inc)


def brief_text(inc: dict[str, Any]) -> str:
    """The procedure as plain text, for the chat model's context and the offline answers."""
    v = view(inc)
    lines = [f"Procedure for {v['classification']} ({v['severity']}, respond within {v['respond_within']}):"]
    for p, label, _g in PHASES:
        for s in v["steps"]:
            if s["phase"] == p:
                lines.append(f"- [{'x' if s['done'] else ' '}] {label}: {s['title']} — {s['owner']}, {s['when']}"
                             + (f" (outside Vigil: {s['outside']})" if s["outside"] else ""))
    return "\n".join(lines)
