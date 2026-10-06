import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

/** Load once (and on demand). Errors surface as ApiError for display. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(() => {
    setLoading(true);
    return fnRef.current()
      .then((d) => { setData(d); setError(null); return d; })
      .catch((e: unknown) => { setError(e instanceof ApiError ? e : new ApiError(0, "error", String(e))); return null; })
      .finally(() => setLoading(false));
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, deps);
  return { data, setData, error, loading, reload };
}

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
