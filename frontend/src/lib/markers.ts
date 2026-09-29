/** Split claim text into plain-text and [[EVIDENCE-ID]] marker segments. Pure; no HTML. */
export type Segment = { kind: "text"; text: string } | { kind: "marker"; evidenceId: string };

const MARKER = /\[\[([^[\]]+)\]\]/g;

export function splitMarkers(text: string): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const index = match.index ?? 0;
    if (index > last) {
      segments.push({ kind: "text", text: text.slice(last, index) });
    }
    segments.push({ kind: "marker", evidenceId: (match[1] ?? "").trim() });
    last = index + match[0].length;
  }
  if (last < text.length) {
    segments.push({ kind: "text", text: text.slice(last) });
  }
  return segments;
}
