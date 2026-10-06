import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

/** A route the backend does not (yet) serve — distinct from "this record does not exist". */
export function isUnavailable(e: ApiError | null | undefined): boolean {
  return !!e && e.status === 404 && (e.code === "not_found" || e.code === "http_error");
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.status === 0 ? "Cannot reach the Vigil server." : e.message;
  return String(e);
}

/** Load once (and on demand). Errors surface as ApiError for display. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const seq = useRef(0);
  const reload = useCallback(() => {
    const my = ++seq.current;
    setLoading(true);
    return fnRef.current()
      .then((d) => { if (my === seq.current) { setData(d); setError(null); } return d; })
      .catch((e: unknown) => {
        if (my === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, "error", String(e)));
        return null;
      })
      .finally(() => { if (my === seq.current) setLoading(false); });
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setData(null); reload(); }, deps);
  return { data, setData, error, loading, reload, unavailable: isUnavailable(error) };
}

export type Loaded<T> = ReturnType<typeof useLoad<T>>;

/** Coalesce bursts of realtime events into one refresh (event-driven, not polling). */
export function useDebounced(fn: () => void, ms = 600) {
  const t = useRef<number | undefined>(undefined);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => () => window.clearTimeout(t.current), []);
  return useCallback(() => {
    window.clearTimeout(t.current);
    t.current = window.setTimeout(() => fnRef.current(), ms);
  }, [ms]);
}

/** A local clock for relative times ("age", "SLA in"). Re-renders only; never calls the server. */
export function useNow(ms = 15000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(t);
  }, [ms]);
  return now;
}
