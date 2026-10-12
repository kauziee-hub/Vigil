// One data source for both money-map views (flat + globe): the aggregated map for the current window / rail, the
// static reference (cities, every ATM terminal), and a live feed of new postings for the moving particles.
// Refreshes are driven by the console WebSocket (throttled), never by polling.
import { useCallback, useEffect, useRef, useState } from "react";
import type { LedgerTx } from "../../api/types";
import { v10, type GeoMap, type MapAtm, type Window } from "../../api/v10";
import { useConsoleEvents } from "../Shell";
import { useThrottled } from "../../lib/live";

export interface GeoReference {
  cities: { city: string; lat: number; lng: number; state: string; tier: number; kind: string }[];
  atms: MapAtm[];
  basis: Record<string, string>;
}

export interface LivePosting {
  id: string; from: [number, number] | null; to: [number, number] | null; amount: number; risky: boolean; atm: boolean;
}

let refCache: GeoReference | null = null;

export function useGeoReference(): GeoReference | null {
  const [ref, setRef] = useState<GeoReference | null>(refCache);
  useEffect(() => {
    if (refCache) return;
    fetch("/api/geo/reference").then((r) => r.json()).then((d: GeoReference) => { refCache = d; setRef(d); }).catch(() => {});
  }, []);
  return ref;
}

export function useMapData(window: Window, channel: string) {
  const [data, setData] = useState<GeoMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const listeners = useRef(new Set<(p: LivePosting) => void>());
  const load = useCallback(() => {
    v10.map(window, channel).then((d) => { setData(d); setError(null); }).catch((e) => setError(String(e)));
  }, [window, channel]);
  useEffect(() => { load(); }, [load]);
  const refresh = useThrottled(load, 4000);
  const riskyRef = useRef(new Set<string>());
  useEffect(() => {
    riskyRef.current = new Set((data?.flows ?? []).filter((f) => f.risk === "fraud").flatMap((f) => [f.from_city, f.to_city]));
  }, [data]);
  useConsoleEvents((e) => {
    if (e.type === "ledger.posted") {
      const tx = e.data as LedgerTx & { geo_lat?: number | null; geo_lng?: number | null; peer_geo_lat?: number | null;
        peer_geo_lng?: number | null; geo_basis?: string | null; seed_attack?: string | null; source?: string };
      if (tx && tx.geo_lat != null && tx.geo_lng != null) {
        const p: LivePosting = {
          id: tx.id, from: [tx.geo_lng, tx.geo_lat],
          to: tx.peer_geo_lat != null && tx.peer_geo_lng != null ? [tx.peer_geo_lng, tx.peer_geo_lat] : null,
          amount: tx.amount_paise, risky: tx.source === "scenario", atm: tx.geo_basis === "atm_terminal",
        };
        listeners.current.forEach((l) => l(p));
      }
      refresh();
    } else if (["intel.account_status", "demo.reset", "attack.run_updated", "taint.updated"].includes(e.type)) {
      refresh();
    }
  });
  const onPosting = useCallback((fn: (p: LivePosting) => void) => {
    listeners.current.add(fn);
    return () => { listeners.current.delete(fn); };
  }, []);
  return { data, error, reload: load, onPosting };
}
