import type { ReactNode } from "react";

type Props = { text: string; evidenceIds?: string[]; evidencePrefix?: string };

/** Small text-only renderer: model output never becomes executable HTML. */
export function revealEvidence(id: string) {
  const target = document.getElementById(id);
  let parent = target?.parentElement;
  while (parent) {
    if (parent.tagName === "DETAILS") (parent as HTMLDetailsElement).open = true;
    parent = parent.parentElement;
  }
  target?.focus({ preventScroll: true });
}

export function ReportText({ text, evidenceIds = [], evidencePrefix = "report" }: Props) {
  const ids = new Set(evidenceIds);
  function inline(value: string): ReactNode[] {
    return value.split(/(\*\*[^*]+\*\*|`[^`]+`|\bE\d+\b)/g).map((part, index) => {
      if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
      if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
      if (ids.has(part)) return <a className="evidenceRef" key={index} href={`#${evidencePrefix}-evidence-${part}`} onClick={() => revealEvidence(`${evidencePrefix}-evidence-${part}`)}>{part}</a>;
      return part;
    });
  }
  const lines = text.replaceAll("\r\n", "\n").split("\n");
  const blocks: ReactNode[] = [];
  for (let i = 0; i < lines.length;) {
    const line = lines[i].trim();
    if (!line) { i++; continue; }
    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(<pre key={`code-${i}`}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    if (/^#{1,6}\s/.test(line)) {
      blocks.push(<h4 key={`heading-${i}`}>{inline(line.replace(/^#{1,6}\s+/, ""))}</h4>);
      i++; continue;
    }
    const list = /^(?:[-*]\s+|\d+[.)]\s+)/;
    if (list.test(line)) {
      const ordered = /^\d/.test(line);
      const items: ReactNode[] = [];
      while (i < lines.length && list.test(lines[i].trim()) && /^\d/.test(lines[i].trim()) === ordered) {
        items.push(<li key={i}>{inline(lines[i++].trim().replace(list, ""))}</li>);
      }
      blocks.push(ordered ? <ol key={`list-${i}`}>{items}</ol> : <ul key={`list-${i}`}>{items}</ul>);
      continue;
    }
    if (line.length < 90 && !line.includes(".") && list.test(lines[i + 1]?.trim() ?? "")) {
      blocks.push(<h4 key={`heading-${i}`}>{inline(line)}</h4>);
      i++; continue;
    }
    const paragraph = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !list.test(lines[i].trim()) && !/^#{1,6}\s/.test(lines[i].trim())
      && !lines[i].trim().startsWith("```")) paragraph.push(lines[i++].trim());
    blocks.push(<p key={`paragraph-${i}`}>{inline(paragraph.join(" "))}</p>);
  }
  return <div className="reportProse">{blocks}</div>;
}
