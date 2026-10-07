// Investigation drawer for a node of the live universe: live status · role · network / model risk · traced value ·
// recent postings · detector consensus (AccountIntel, corroborating) · "Open account".
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AccountSummary, LedgerTx, UniverseAccount } from "../api/types";
import { formatINR, formatTime, handle } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { ACCOUNT_STATUS_LABEL, ROLE_LABEL, STATUS_HEX, scoreStatus } from "../lib/status";
import { AccountIntelBlock, RoleIcon } from "./intel";
import { KV, Sim } from "./ui";

export function AccountStatusPill({ status }: { status: UniverseAccount["status"] }) {
  return <span className={`pill as-${status}`}>{ACCOUNT_STATUS_LABEL[status]}</span>;
}

export function UniverseDrawer({ id, acct, taint, onClose, onFocus }: {
  id: string; acct: UniverseAccount | null; taint?: number; onClose: () => void; onFocus?: () => void;
}) {
  const ext = id.startsWith("ext:") || acct?.kind === "external";
  const summary = useLoad<AccountSummary | null>(() => (ext ? Promise.resolve(null) : api.account(id)), [id]);
  const txs = useLoad<LedgerTx[]>(() => (ext ? Promise.resolve([]) : api.accountTransactions(id)), [id]);
  const a = summary.data;
  return (
    <aside className="drawer" aria-label="Account investigation drawer">
      <div className="drawer-h">
        <RoleIcon role={acct?.role} size={18} />
        <div className="grow">
          <div className="b">{acct?.label ?? a?.display_name ?? handle(id)}</div>
          <div className="mono xs dim">{id}</div>
        </div>
        <button className="btn xs ghost" onClick={onClose} aria-label="Close drawer">✕</button>
      </div>
      <div className="drawer-b">
        <div className="sect">
          <div className="row wrap tight">
            {acct && <AccountStatusPill status={acct.status} />}
            {acct?.role && <span className="tag">{ROLE_LABEL[acct.role] ?? acct.role}</span>}
            {acct?.group === "merchant" && <span className="tag">merchant</span>}
            {acct?.group === "demo" && <span className="tag">demo customer</span>}
            {ext && <span className="tag">outside the bank's view</span>}
          </div>
          <div className="mstrip dense" style={{ marginTop: 10 }}>
            <div className="m"><div className="k">Network risk</div>
              <div className="v" style={{ color: acct ? STATUS_HEX[scoreStatus(acct.risk)] : undefined }}>{acct ? acct.risk.toFixed(2) : "—"}</div>
              <div className="d">RingWatch · on the authorisation path</div></div>
            <div className="m"><div className="k">Model evidence</div>
              <div className="v">{acct?.model_risk != null ? acct.model_risk.toFixed(2) : "—"}</div>
              <div className="d">corroborating — not used for authorisation</div></div>
            <div className="m"><div className="k">Traced value</div>
              <div className="v" style={{ color: taint ? STATUS_HEX.fraud : undefined }}>{taint ? formatINR(taint) : "₹0"}</div>
              <div className="d">LIBR attributable</div></div>
          </div>
          {a && (
            <div style={{ marginTop: 10 }}>
              <KV c4 rows={[
                ["Balance", <span className="mono">{formatINR(a.balance_paise)}</span>],
                ["Held", <span className="mono" style={{ color: a.held_paise ? STATUS_HEX.held : undefined }}>{formatINR(a.held_paise)}</span>],
                ["Opened", new Date(a.opened_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })],
                ["Devices", a.devices.length],
              ]} />
            </div>
          )}
          <div className="row wrap" style={{ marginTop: 12 }}>
            {onFocus && <button className="btn sm" onClick={onFocus}>Focus camera</button>}
            {!ext && <Link className="btn sm primary" to={`/investigations/account/${encodeURIComponent(id)}`}>Open account</Link>}
            {!ext && <Link className="btn sm ghost" to={`/network?view=scene&focus=${encodeURIComponent(id)}&hops=1`}>Evidence scene</Link>}
          </div>
        </div>
        {!ext && (
          <div className="sect">
            <div className="sect-t">Recent postings</div>
            {txs.loading && !txs.data && <div className="xs muted">Loading…</div>}
            {txs.data && txs.data.length === 0 && <div className="xs muted">No ledger postings.</div>}
            {(txs.data ?? []).length > 0 && (
              <table className="dt compact">
                <tbody>
                  {(txs.data ?? []).slice(0, 10).map((t) => {
                    const inbound = t.recipient_id === id;
                    return (
                      <tr key={t.id}>
                        <td className="mono xs dim">{formatTime(t.ts)}</td>
                        <td className="xs">{inbound ? "← " : "→ "}{handle(inbound ? t.sender_id : t.recipient_id)}</td>
                        <td className="num xs">{inbound ? "+" : "−"}{formatINR(t.amount_paise)}</td>
                        <td className="xs muted">{t.source}{t.source === "scenario" && <> <Sim text="SIM" /></>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
        {!ext && <AccountIntelBlock accountId={id} compact />}
      </div>
    </aside>
  );
}
