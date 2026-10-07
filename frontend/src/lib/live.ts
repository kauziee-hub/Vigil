// Live-platform data hooks (v3). Load once, then follow pushed events. No polling: refetches are triggered by
// WebSocket events and throttled (at most one request per `minMs`).
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { AttackRun, LiveStats } from "../api/types";
import { useConsoleEvents } from "../components/Shell";
import { isUnavailable } from "./hooks";

/** Leading + trailing throttle: run now, and at most once more after `ms` if called again meanwhile. */
export function useThrottled(fn: () => void, ms: number) {
  const last = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return useCallback(() => {
    const now = Date.now();
    const wait = last.current + ms - now;
    if (wait <= 0) { last.current = now; fnRef.current(); return; }
    if (timer.current === undefined) {
      timer.current = window.setTimeout(() => { timer.current = undefined; last.current = Date.now(); fnRef.current(); }, wait);
    }
  }, [ms]);
}

export interface LiveSource<T> { data: T | null; unavailable: boolean; error: string | null; loading: boolean; reload: () => void }

/** Attack runs: GET /api/attacks/runs, then WS attack.run_updated upserts (newest first). */
export function useAttackRuns(): LiveSource<AttackRun[]> {
  const [data, setData] = useState<AttackRun[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    api.attackRuns()
      .then((r) => { setData([...r].sort((a, b) => b.started_at.localeCompare(a.started_at))); setUnavailable(false); setError(null); })
      .catch((e) => { if (e instanceof ApiError && isUnavailable(e)) setUnavailable(true); else setError(e instanceof ApiError ? e.message : String(e)); })
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { reload(); }, [reload]);
  useConsoleEvents((e) => {
    if (e.type === "attack.run_updated") {
      const r = e.data as AttackRun;
      if (!r?.run_id) return;
      setUnavailable(false);
      setData((xs) => {
        const list = (xs ?? []).filter((x) => x.run_id !== r.run_id);
        return [r, ...list].sort((a, b) => b.started_at.localeCompare(a.started_at));
      });
    } else if (e.type === "demo.reset") reload();
  });
  return { data, unavailable, error, loading, reload };
}

/** Live statistics: GET /api/live/stats; refreshed on pushed activity, at most every `minMs`. */
export function useLiveStats(minMs = 5000): LiveSource<LiveStats> {
  const [data, setData] = useState<LiveStats | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const dead = useRef(false);
  const reload = useCallback(() => {
    if (dead.current) return;
    api.liveStats()
      .then((s) => { setData(s); setUnavailable(false); setError(null); })
      .catch((e) => {
        if (e instanceof ApiError && isUnavailable(e)) { setUnavailable(true); }
        else setError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { reload(); return () => { dead.current = true; }; }, [reload]);
  const refresh = useThrottled(reload, minMs);
  useConsoleEvents((e) => {
    if (unavailable && e.type !== "demo.reset") return;
    if (["ledger.posted", "intel.tx_scored", "attack.run_updated", "decision.created", "demo.reset", "intel.account_status"].includes(e.type)) refresh();
  });
  return { data, unavailable, error, loading, reload };
}

/** Fixed-size ring buffer of recent items flushed to React state at most every `ms` (streams). */
export function useBufferedList<T>(max: number, ms = 600) {
  const buf = useRef<T[]>([]);
  const total = useRef(0);
  const [items, setItems] = useState<T[]>([]);
  const [count, setCount] = useState(0);
  const flush = useThrottled(() => { setItems(buf.current.slice()); setCount(total.current); }, ms);
  const push = useCallback((x: T) => {
    buf.current.unshift(x);
    if (buf.current.length > max) buf.current.length = max;
    total.current += 1;
    flush();
  }, [max, flush]);
  const clear = useCallback(() => { buf.current = []; total.current = 0; setItems([]); setCount(0); }, []);
  return { items, count, push, clear };
}

export function msLabel(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}
