// Pure helpers for Copilot incidents (shared by the strip and the checks).
import type { Incident, Severity } from "../api/v10";

export const SEV_ORDER: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3 };

/** Strip order: severity first (critical → low), then most recently updated. */
export function sortIncidents(list: Incident[]): Incident[] {
  return [...list].sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || b.updated_ts.localeCompare(a.updated_ts));
}
