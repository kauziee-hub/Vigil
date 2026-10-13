// Safe "markdown-lite" renderer for Vigilance text. No dangerouslySetInnerHTML anywhere: the text is tokenised into
// React elements, so any HTML in the input is rendered as literal characters. Supported: paragraphs, "# " headings,
// "- " / "1. " lists (also directly under a heading line, as language models write them), **bold**, _italic_ /
// *italic*, `inline code`, and entity links [[acct:ID]] / [[tx:ID]] which become clickable chips (the click is
// handled by the caller through `onEntity`).
import type { ReactNode } from "react";

export type EntityRef = { kind: "acct" | "tx"; id: string };

const INLINE = /(\[\[(acct|tx):([^\]\s]{1,80})\]\]|\*\*([^*]+)\*\*|`([^`]+)`|_([^_]+)_|\*([^*]+)\*)/g;
const BULLET = /^\s*[-•*]\s+/;
const NUMBER = /^\s*\d+[.)]\s+/;
const HEADING = /^\s*#{1,6}\s+/;

function inline(text: string, onEntity?: (e: EntityRef) => void, keyBase = ""): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  INLINE.lastIndex = 0;
  while ((m = INLINE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${keyBase}-${i++}`;
    if (m[2]) {
      const ref = { kind: m[2] as "acct" | "tx", id: m[3] };
      const label = ref.kind === "acct" ? ref.id.replace("@vigil", "") : ref.id;
      out.push(<button key={k} type="button" className={`ent-chip ${ref.kind}`} onClick={() => onEntity?.(ref)}
                       title={ref.kind === "acct" ? "Select this account" : "Open this posting's connections"}>{label}</button>);
    } else if (m[4]) out.push(<b key={k}>{m[4]}</b>);
    else if (m[5]) out.push(<code key={k}>{m[5]}</code>);
    else if (m[6] || m[7]) out.push(<em key={k}>{m[6] ?? m[7]}</em>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Run = { kind: "ul" | "ol" | "p" | "h"; lines: string[] };

/** Split one block into runs of the same kind, so "**Do now**\n1. …\n2. …" becomes a paragraph and a list. */
function runs(lines: string[]): Run[] {
  const out: Run[] = [];
  for (const l of lines) {
    const kind: Run["kind"] = HEADING.test(l) ? "h" : BULLET.test(l) ? "ul" : NUMBER.test(l) ? "ol" : "p";
    const prev = out[out.length - 1];
    if (prev && prev.kind === kind && kind !== "h") prev.lines.push(l);
    else out.push({ kind, lines: [l] });
  }
  return out;
}

export function SafeMarkdown({ text, onEntity }: { text: string; onEntity?: (e: EntityRef) => void }) {
  const blocks = (text || "").replace(/\r/g, "").split(/\n{2,}/);
  const out: ReactNode[] = [];
  blocks.forEach((block, bi) => {
    const lines = block.split("\n").filter((l) => l.trim() !== "");
    runs(lines).forEach((r, ri) => {
      const key = `${bi}-${ri}`;
      if (r.kind === "ul") out.push(<ul key={key}>{r.lines.map((l, li) => <li key={li}>{inline(l.replace(BULLET, ""), onEntity, `${key}-${li}`)}</li>)}</ul>);
      else if (r.kind === "ol") out.push(<ol key={key}>{r.lines.map((l, li) => <li key={li}>{inline(l.replace(NUMBER, ""), onEntity, `${key}-${li}`)}</li>)}</ol>);
      else if (r.kind === "h") out.push(<div key={key} className="md-h">{inline(r.lines[0].replace(HEADING, ""), onEntity, key)}</div>);
      else out.push(<p key={key}>{r.lines.map((l, li) => <span key={li}>{li > 0 && <br />}{inline(l, onEntity, `${key}-${li}`)}</span>)}</p>);
    });
  });
  return <div className="safe-md">{out}</div>;
}
