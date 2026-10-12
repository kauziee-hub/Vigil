// Safe "markdown-lite" renderer for Copilot text. No dangerouslySetInnerHTML anywhere: the text is tokenised into
// React elements, so any HTML in the input is rendered as literal characters. Supported: paragraphs, "- " / "1. "
// lists, **bold**, _italic_ / *italic*, `inline code`, and entity links [[acct:ID]] / [[tx:ID]] which become
// clickable chips (the click is handled by the caller through `onEntity`).
import type { ReactNode } from "react";

export type EntityRef = { kind: "acct" | "tx"; id: string };

const INLINE = /(\[\[(acct|tx):([^\]\s]{1,80})\]\]|\*\*([^*]+)\*\*|`([^`]+)`|_([^_]+)_|\*([^*]+)\*)/g;

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

export function SafeMarkdown({ text, onEntity }: { text: string; onEntity?: (e: EntityRef) => void }) {
  const blocks = (text || "").replace(/\r/g, "").split(/\n{2,}/);
  return (
    <div className="safe-md">
      {blocks.map((block, bi) => {
        const lines = block.split("\n").filter((l) => l.trim() !== "");
        if (lines.length && lines.every((l) => /^\s*[-•]\s+/.test(l))) {
          return <ul key={bi}>{lines.map((l, li) => <li key={li}>{inline(l.replace(/^\s*[-•]\s+/, ""), onEntity, `${bi}-${li}`)}</li>)}</ul>;
        }
        if (lines.length && lines.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
          return <ol key={bi}>{lines.map((l, li) => <li key={li}>{inline(l.replace(/^\s*\d+[.)]\s+/, ""), onEntity, `${bi}-${li}`)}</li>)}</ol>;
        }
        return <p key={bi}>{lines.map((l, li) => <span key={li}>{li > 0 && <br />}{inline(l.replace(/^#+\s*/, ""), onEntity, `${bi}-${li}`)}</span>)}</p>;
      })}
    </div>
  );
}
