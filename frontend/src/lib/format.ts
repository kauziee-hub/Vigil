// Formatting helpers. Money arrives as integer paise; time as ISO "Z".

function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const tail = digits.slice(-3);
  let head = digits.slice(0, -3);
  const parts: string[] = [];
  while (head.length > 2) {
    parts.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) parts.unshift(head);
  return `${parts.join(",")},${tail}`;
}

export function formatINR(paise: number | null | undefined, withPaise = false): string {
  if (paise === null || paise === undefined || Number.isNaN(paise)) return "—";
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(Math.trunc(paise));
  const rupees = Math.floor(abs / 100);
  const rem = abs % 100;
  return `${sign}₹${groupIndian(String(rupees))}${withPaise && rem ? `.${String(rem).padStart(2, "0")}` : ""}`;
}

export function formatPaiseShort(paise: number): string {
  const r = paise / 100;
  if (Math.abs(r) >= 1e7) return `₹${(r / 1e7).toFixed(2)}Cr`;
  if (Math.abs(r) >= 1e5) return `₹${(r / 1e5).toFixed(2)}L`;
  if (Math.abs(r) >= 1e3) return `₹${(r / 1e3).toFixed(1)}K`;
  return `₹${Math.round(r)}`;
}

export function rupeesToPaise(input: string): number | null {
  const clean = input.replace(/[₹,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null;
  const [r, p = ""] = clean.split(".");
  return Number(r) * 100 + Number((p + "00").slice(0, 2));
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const handle = (id: string) => id.replace("@vigil", "");

export const TIER_LABEL: Record<number, string> = {
  0: "Tier 0 · Pass",
  1: "Tier 1 · Inform",
  2: "Tier 2 · Confirm",
  3: "Tier 3 · Scoped hold",
  4: "Tier 4 · Hold + CircuitBreaker",
};

export const DIM_LABEL: Record<string, string> = {
  external: "External intel",
  network: "Network (RingWatch)",
  sequence: "Journey (TrailScore)",
  behaviour: "Behaviour",
  context: "Context (ContextFlag)",
};

export const STATE_LABEL: Record<string, string> = {
  CREATED: "Created",
  RISK_EVALUATED: "Risk evaluated",
  APPROVED: "Approved",
  CHALLENGED: "Challenged",
  HELD: "Held",
  ESCALATED: "Escalated",
  CANCELLED: "Cancelled",
  REJECTED: "Rejected",
  PAYMENT_INITIATED: "Payment initiated",
  PAYMENT_SUCCEEDED: "Payment succeeded",
  PAYMENT_FAILED: "Payment failed",
  MONITORED: "Monitored",
};

export function fmtScore(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function pct(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export function formatBytes(b: number | null | undefined): string {
  if (b === null || b === undefined) return "—";
  if (b < 1024) return `${b} B`;
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

export function formatStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" })} ${formatTime(iso)}`;
}

/** "window_hours" → "window hours". */
export function humanKey(k: string): string {
  return k.replace(/_paise$/, "").replace(/_/g, " ");
}

const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

/** Render an evidence value for people, not developers. */
export function evValue(key: string, v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") {
    if (key.endsWith("_paise")) return formatINR(v);
    if (Number.isInteger(v)) return String(v);
    return Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1);
  }
  if (typeof v === "string") return ISO_RE.test(v) ? formatStamp(v) : v;
  if (Array.isArray(v)) return v.map((x) => evValue(key, x)).join(", ");
  return JSON.stringify(v);
}

export function freshness(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return "live";
  return `${duration(seconds)} old`;
}

/** Repair UTF-8 text that was decoded as cp1252 once ("â‚¹" → "₹") — a display fix only; the data is unchanged. */
export function clean(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/â‚¹/g, "₹").replace(/â€”/g, "—").replace(/â€“/g, "–").replace(/â€™/g, "’")
    .replace(/â‰¥/g, "≥").replace(/â‰¤/g, "≤").replace(/Ã—/g, "×");
}
