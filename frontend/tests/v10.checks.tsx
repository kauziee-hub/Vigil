// Frontend checks for overview-v10 (run: node ../scripts/frontend_checks.mjs from the repo root).
// No test framework download needed: esbuild (shipped with Vite) bundles this file; react-dom/server renders it.
import { renderToStaticMarkup } from "react-dom/server";
import type { Incident } from "../src/api/v10";
import { runAction, type ActionDeps } from "../src/lib/copilotActions";
import { sortIncidents } from "../src/lib/incidents";
import { SafeMarkdown } from "../src/lib/safeMarkdown";
import { selectionAccounts } from "../src/lib/selection";

let failed = 0;
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failed++;
}
const html = (t: string) => renderToStaticMarkup(<SafeMarkdown text={t} />);

// 1. SafeMarkdown never emits markup from the input (XSS fixtures)
const fixtures = [
  "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "**<iframe src=javascript:alert(1)>**",
  "[[acct:<svg onload=alert(1)>]]", "`<a href=\"javascript:alert(1)\">x</a>`", "- <b onmouseover=alert(1)>hi</b>",
  "[link](javascript:alert(1))",
];
for (const f of fixtures) {
  const out = html(f);
  // a real tag from the input, or an event-handler attribute INSIDE a real tag (escaped text like &lt;img …&gt; is fine)
  const bad = /<(script|img|iframe|svg|a)\b/i.test(out) || /<[a-z]+\b[^>]*\son\w+=/i.test(out);
  check(`no injected markup: ${f.slice(0, 32)}`, !bad, bad ? out : "");
}
// 2. supported formatting
const rich = html("**Bold** and `code`\n\n- one\n- two\n\n1. first\n2. second\n\nSee [[acct:kiran.traders@vigil]] and [[tx:TX-031200]]");
check("bold/code/lists render", rich.includes("<b>Bold</b>") && rich.includes("<code>code</code>") && rich.includes("<ul>") && rich.includes("<ol>"));
check("entity chips render as buttons", (rich.match(/class="ent-chip acct"/g) ?? []).length === 1 && rich.includes('class="ent-chip tx"') && rich.includes(">kiran.traders<"));

// 3. Copilot UI actions: whitelist only; watch is a proposal the human confirms
const calls: string[] = [];
const deps: ActionDeps = {
  select: (s) => calls.push(`select:${s?.kind}:${s?.id}`), navigate: (to) => calls.push(`nav:${to}`),
  openConnections: (tx) => calls.push(`conn:${tx}`), focusNetwork: (ids) => calls.push(`net:${ids.join("+")}`),
  setTapeOnly: (o) => calls.push(`tape:${o}`), confirmWatch: (id) => calls.push(`confirm-watch:${id}`),
  cityPoint: (c) => (c === "Mumbai" ? { lat: 19.07, lng: 72.87 } : null),
};
check("unknown action ignored", runAction({ type: "freeze_account", target: "x@vigil" }, deps) === false && calls.length === 0);
check("open_page outside whitelist ignored", runAction({ type: "open_page", target: "https://evil.example" }, deps) === false);
check("open_page whitelisted", runAction({ type: "open_page", target: "/interventions" }, deps) && calls.at(-1) === "nav:/interventions");
check("select_entity with a tx id opens connections", runAction({ type: "select_entity", target: "tx-031200" }, deps) && calls.at(-1) === "conn:TX-031200");
check("show_on_map city selects the city", runAction({ type: "show_on_map", target: "Mumbai" }, deps) && calls.at(-1) === "select:city:Mumbai");
check("watch_account only asks for confirmation", runAction({ type: "watch_account", target: "kiran.traders@vigil" }, deps) && calls.at(-1) === "confirm-watch:kiran.traders@vigil");
check("filter_tape sanitises its target", runAction({ type: "filter_tape", target: "drop table" }, deps) && calls.at(-1) === "tape:all");

// 4. incident strip ordering and selection helper
const inc = (id: string, severity: Incident["severity"], updated: string) => ({ id, severity, updated_ts: updated }) as Incident;
const order = sortIncidents([inc("a", "medium", "2026-10-13T01:00:00Z"), inc("b", "critical", "2026-10-13T00:00:00Z"),
  inc("c", "medium", "2026-10-13T02:00:00Z"), inc("d", "high", "2026-10-13T00:30:00Z")]).map((i) => i.id).join("");
check("incidents sorted by severity then recency", order === "bdca", order);
check("selectionAccounts", selectionAccounts({ kind: "account", id: "x" }).join() === "x" &&
  selectionAccounts({ kind: "cluster", id: "c", accounts: ["a", "b"] }).join() === "a,b" && selectionAccounts(null).length === 0);

console.log(failed ? `FAILED ${failed}` : "OK");
if (failed) process.exit(1);
