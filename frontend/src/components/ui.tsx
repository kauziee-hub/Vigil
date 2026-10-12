// Design-system primitives (docs/DESIGN_SYSTEM.md). Presentational only — no data fetching.
import { Component, type ReactNode } from "react";

/** Contain a rendering fault to one page instead of blanking the console. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error) {
      return <div className="notice err">This view failed to render: <span className="mono">{this.state.error.message}</span>. Other pages are unaffected.</div>;
    }
    return this.props.children;
  }
}
import type { ApiError } from "../api/client";
import type { DetectorFamily, IntentState } from "../api/types";
import { STATE_LABEL } from "../lib/format";
import { isUnavailable } from "../lib/hooks";
import {
  FAMILY, STATUS_LABEL, type Status, scoreStatus, stateStatus, tierStatus, TIER_SHORT,
} from "../lib/status";

export function Panel({ title, kicker, q, actions, children, flush, footer, className, id }: {
  title?: ReactNode; kicker?: ReactNode; q?: ReactNode; actions?: ReactNode; children?: ReactNode;
  flush?: boolean; footer?: ReactNode; className?: string; id?: string;
}) {
  return (
    <section className={`panel ${className ?? ""}`} id={id}>
      {(title || kicker || actions) && (
        <header className="panel-h">
          {/* one heading per panel: the kicker is only shown when there is no title */}
          {(title || kicker) && <span className="t">{title || kicker}</span>}
          {q && <span className="q">{q}</span>}
          {actions && <div className="act">{actions}</div>}
        </header>
      )}
      <div className={`panel-b ${flush ? "flush" : ""}`}>{children}</div>
      {footer && <div className="panel-f">{footer}</div>}
    </section>
  );
}

/** Plain-language caption under a chart or panel: what it shows, how to read it, and what it says right now. */
export function Explain({ shows, read, now }: { shows: ReactNode; read?: ReactNode; now?: ReactNode }) {
  return (
    <div className="explain">
      <p><b>Shows</b>{shows}</p>
      {read && <p><b>How to read</b>{read}</p>}
      {now && <p className="now"><b>Right now</b>{now}</p>}
    </div>
  );
}

export function PageHead({ crumb, title, lede, actions, compact }: { crumb?: ReactNode; title: ReactNode; lede?: ReactNode; actions?: ReactNode; compact?: boolean }) {
  return (
    <div className={`page-head ${compact ? "compact" : ""}`}>
      <div style={{ minWidth: 0 }}>
        {crumb && <div className="crumb">{crumb}</div>}
        <h1>{title}</h1>
        {lede && <div className="lede">{lede}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Pill({ status, children, lg, title }: { status: Status; children?: ReactNode; lg?: boolean; title?: string }) {
  return <span className={`pill s-${status} ${lg ? "lg" : ""}`} title={title}>{children ?? STATUS_LABEL[status]}</span>;
}

export function TierPill({ tier, lg, full }: { tier: number | null | undefined; lg?: boolean; full?: boolean }) {
  if (tier === null || tier === undefined) return <span className="pill s-unknown">—</span>;
  return <Pill status={tierStatus(tier)} lg={lg} title={TIER_SHORT[tier]}>{full ? TIER_SHORT[tier] : `T${tier}`}</Pill>;
}

export function StatePill({ state }: { state: IntentState | string }) {
  return <Pill status={stateStatus(state)}>{STATE_LABEL[state] ?? state}</Pill>;
}

export function ScorePill({ score, label }: { score: number | null | undefined; label?: string }) {
  return <Pill status={scoreStatus(score)}>{label ?? (score == null ? "—" : score.toFixed(2))}</Pill>;
}

export function Sim({ text = "SIMULATED" }: { text?: string }) {
  return <span className="sim" title="Simulated input — not a live institutional feed">{text}</span>;
}

export function Glyph({ family, code }: { family?: DetectorFamily; code?: string }) {
  const f = family ? FAMILY[family] : undefined;
  return <span className="glyph" title={f?.label}>{code ?? f?.glyph ?? "?"}</span>;
}

export function KV({ rows, c4 }: { rows: [ReactNode, ReactNode][]; c4?: boolean }) {
  return (
    <dl className={`kv ${c4 ? "c4" : ""}`}>
      {rows.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Metric({ k, v, d, status }: { k: ReactNode; v: ReactNode; d?: ReactNode; status?: Status }) {
  return (
    <div className={`m ${status ? `st-${status}` : ""}`}>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {d && <div className="d">{d}</div>}
    </div>
  );
}

export function Bar({ value, status, max = 1, tick }: { value: number | null | undefined; status?: Status; max?: number; tick?: number }) {
  const w = value == null ? 0 : Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <div className="bar">
      <i style={{ width: `${w}%`, background: status ? `var(--st-${status})` : undefined }} />
      {tick !== undefined && <span className="tick" style={{ left: `${(tick / max) * 100}%` }} />}
    </div>
  );
}

export function BarRow({ label, value, display, status, max = 1 }: {
  label: ReactNode; value: number | null | undefined; display?: ReactNode; status?: Status; max?: number;
}) {
  return (
    <div className="barrow">
      <span className="lbl">{label}</span>
      <Bar value={value} status={status} max={max} />
      <span className="val">{display ?? (value == null ? "—" : value.toFixed(2))}</span>
    </div>
  );
}

export function Unavailable({ what, endpoint, children }: { what: string; endpoint?: string; children?: ReactNode }) {
  return (
    <div className="unavail" role="status">
      <span className="ic">∅</span>
      <div>
        <b>{what}: not yet available.</b>{" "}
        {endpoint && <>The backend does not serve <span className="mono">{endpoint}</span> yet. </>}
        Nothing is shown rather than estimated.
        {children && <div style={{ marginTop: 4 }}>{children}</div>}
      </div>
    </div>
  );
}

export function Loading({ text = "Loading" }: { text?: string }) {
  return <div className="loading"><span className="spinner" />{text}…</div>;
}

export function ErrorNote({ error }: { error: ApiError | null | undefined }) {
  if (!error) return null;
  return <div className="notice err">{error.status === 0 ? "Cannot reach the Vigil server." : error.message}</div>;
}

/**
 * Standard async-state renderer: unavailable endpoint → honest empty state;
 * error → message; loading → spinner; else children(data).
 */
export function Async<T>({ load, what, endpoint, children, empty }: {
  load: { data: T | null; error: ApiError | null; loading: boolean };
  what: string; endpoint?: string; children: (d: T) => ReactNode; empty?: ReactNode;
}) {
  if (load.error && isUnavailable(load.error)) return <Unavailable what={what} endpoint={endpoint} />;
  if (load.error && !load.data) return <ErrorNote error={load.error} />;
  if (load.data === null || load.data === undefined) return load.loading ? <Loading /> : <>{empty ?? <div className="empty">No data.</div>}</>;
  return <>{children(load.data)}</>;
}

export function Tabs<K extends string>({ tabs, value, onChange }: { tabs: [K, ReactNode][]; value: K; onChange: (k: K) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([k, l]) => (
        <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>{l}</button>
      ))}
    </div>
  );
}

export function Seg<K extends string>({ options, value, onChange, disabled }: {
  options: [K, ReactNode][]; value: K; onChange: (k: K) => void; disabled?: (k: K) => boolean;
}) {
  return (
    <div className="seg" role="radiogroup">
      {options.map(([k, l]) => (
        <button key={k} role="radio" aria-checked={value === k} className={value === k ? "on" : ""}
                disabled={disabled?.(k)} onClick={() => onChange(k)}>{l}</button>
      ))}
    </div>
  );
}

export function StatusLegend() {
  const all: Status[] = ["normal", "watch", "high", "critical", "held", "fraud"];
  return (
    <div className="legend">
      {all.map((s) => <span key={s}><i className="sw" style={{ background: `var(--st-${s})` }} />{STATUS_LABEL[s]}</span>)}
    </div>
  );
}
