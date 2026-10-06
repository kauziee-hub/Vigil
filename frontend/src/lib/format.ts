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
