// The intervention queue as the console shows it: /api/interventions (newest 100 alerts) plus scenario / customer
// decisions (tier ≥ 2) that fell outside that window, each with its LIVE intent state from /api/intents/{id}.
// The window is otherwise filled by background-stream Tier 1 heads-ups (see AGENT_HANDOFF/REQUESTS.md).
import { useMemo } from "react";
import { api } from "../api/client";
import type { IntentState, InterventionRow } from "../api/types";
import { useLoad } from "./hooks";

export type QueueRow = InterventionRow & { outside?: boolean };
export const OPEN_STATES = new Set<IntentState | string>(["HELD", "ESCALATED", "CHALLENGED", "CREATED", "RISK_EVALUATED"]);

export function useInterventionQueue(status: "open" | "all") {
  const rows = useLoad<InterventionRow[]>(() => api.interventions(status), [status]);
  const fetchedAt = useMemo(() => Date.now(), [rows.data]);
  const extra = useLoad<QueueRow[]>(async () => {
    if (!rows.data) return [];
    const have = new Set(rows.data.map((r) => r.decision_id));
    const ds = (await api.decisions(2)).filter((d) => !have.has(d.decision_id)).slice(0, 12);
    const out = await Promise.all(ds.map(async (d): Promise<QueueRow | null> => {
      try {
        const r = await api.intent(d.intent_id);
        const it = r.intent;
        const holdPaise = r.decision?.intervention.hold_paise ?? 0;
        return {
          intent_id: it.intent_id, decision_id: d.decision_id, sender_id: d.sender_id, recipient_id: d.recipient_id,
          amount_paise: d.amount_paise, tier: d.tier, kind: d.kind, state: it.state, headline: d.headline, opened_at: d.created_at,
          age_s: (Date.now() - Date.parse(d.created_at)) / 1000, sla_due: null,
          hold: it.hold_id && holdPaise ? { id: it.hold_id, held_paise: holdPaise, reference: "", outcome: OPEN_STATES.has(it.state) ? null : it.state.toLowerCase() } : null,
          circuit_breaker: null, mode: (r.decision as { mode?: "active" | "shadow" } | null)?.mode ?? "active", outside: true,
        };
      } catch { return null; }
    }));
    return out.filter((x): x is QueueRow => !!x).filter((x) => status === "all" || OPEN_STATES.has(x.state));
  }, [rows.data, status]);
  const all: QueueRow[] = useMemo(() => [...(rows.data ?? []), ...(extra.data ?? [])]
    .sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at)), [rows.data, extra.data]);
  return { rows, extra, all, fetchedAt };
}

/** Age in seconds: server-computed at fetch time, advanced by the local clock (never polled). */
export function rowAge(r: QueueRow, now: number, fetchedAt: number): number {
  return r.outside ? (now - Date.parse(r.opened_at)) / 1000 : r.age_s + Math.max(0, now - fetchedAt) / 1000;
}
