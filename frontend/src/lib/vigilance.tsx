// Vigilance is GLOBAL (v11): the dock and its alerts live in the Shell, so a case stays open while a procedure step
// takes the analyst to the case page, the account page or Interventions. This module is only the shared context; the
// provider and the dock are in components/vigilance/Vigilance.tsx.
//   * `vigilance` / `openVigilance` / `closeVigilance` — what the dock should show (a case, a question, or the feed).
//   * `incidents`, `status` — the open alerts and the model status, loaded once for the whole app (pushed live).
//   * the page bridge — the Overview registers its handlers (select on the map, frame in the network, open a posting's
//     connections, incident mode). On any other page those actions are CARRIED: Vigilance navigates to the Overview,
//     which runs the pending action once its map reference is ready.
import { createContext, useContext } from "react";
import type { CopilotStatus, Incident, UiAction } from "../api/v10";
import type { ActionDeps } from "./vigilanceActions";

export interface VigilanceReq { open: boolean; incidentId: string | null; prompt: string | null; about: string | null; seq: number }
export interface VigilanceOpen { incidentId?: string | null; prompt?: string | null; about?: string | null }
/** Handlers only the Overview has (everything an action needs except navigation and the watch confirmation). */
export type PageDeps = Omit<ActionDeps, "confirmWatch" | "navigate"> & { focusIncident: (i: Incident) => void };
/** Something to do on the Overview once it is on screen. */
export interface Pending { action?: UiAction; focus?: Incident }

export interface VigilanceCtx {
  vigilance: VigilanceReq;
  openVigilance: (o: VigilanceOpen) => void;
  closeVigilance: () => void;
  incidents: Incident[];
  max: number;
  loaded: boolean;
  reloadIncidents: () => void;
  status: CopilotStatus | null;
  reloadStatus: () => void;
  page: PageDeps | null;
  registerPage: (d: PageDeps | null) => void;
  carry: (p: Pending) => void;
  takePending: () => Pending | null;
}

const noop = () => undefined;
export const VigilanceContext = createContext<VigilanceCtx>({
  vigilance: { open: false, incidentId: null, prompt: null, about: null, seq: 0 },
  openVigilance: noop, closeVigilance: noop, incidents: [], max: 5, loaded: false, reloadIncidents: noop,
  status: null, reloadStatus: noop, page: null, registerPage: noop, carry: noop, takePending: () => null,
});

export function useVigilance(): VigilanceCtx {
  return useContext(VigilanceContext);
}
