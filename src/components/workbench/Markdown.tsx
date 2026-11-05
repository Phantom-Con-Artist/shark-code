import { useState, type ReactNode } from 'react';
import { Check, Copy } from 'lucide-react';

/** Small, safe Markdown subset for agent prose: fences, headings, lists, inline code, bold. No HTML injection. */
export function Markdown({ text, streaming = false, className = '' }: { text: string; streaming?: boolean; className?: string }) {
  const blocks: ReactNode[] = [];
  const parts = text.split(/```/);
  parts.forEach((part, i) => {
    if (i % 2 === 1) {
      const newline = part.indexOf('\n');
      const lang = newline > 0 ? part.slice(0, newline).trim() : '';
      blocks.push(<CodeBlock key={i} lang={lang} code={(newline >= 0 ? part.slice(newline + 1) : part).replace(/\n$/, '')} />);
      return;
    }
    const lines = part.split('\n');
    let list: { ordered: boolean; items: string[] } | null = null;
    let para: string[] = [];
    const flushPara = () => { if (para.length) { blocks.push(<p key={`${i}-p${blocks.length}`}>{inline(para.join(' '))}</p>); para = []; } };
    const flushList = () => {
      if (!list) return;
      const items = list.items.map((it, k) => <li key={k}>{inline(it)}</li>);
      blocks.push(list.ordered ? <ol key={`${i}-l${blocks.length}`}>{items}</ol> : <ul key={`${i}-l${blocks.length}`}>{items}</ul>);
      list = null;
    };
    let quote: string[] = [];
    const flushQuote = () => { if (quote.length) { blocks.push(<blockquote key={`${i}-q${blocks.length}`}>{inline(quote.join(' '))}</blockquote>); quote = []; } };
    for (let li = 0; li < lines.length; li++) {
      const line = lines[li].trimEnd();
      const isRow = (l?: string) => !!l && /^\s*\|.*\|\s*$/.test(l);
      if (isRow(line) && /^\s*\|?\s*:?-{2,}/.test(lines[li + 1] ?? '')) {
        flushPara(); flushList(); flushQuote();
        const cells = (l: string) => l.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        const head = cells(line); const body: string[][] = [];
        li += 2;
        while (li < lines.length && isRow(lines[li])) body.push(cells(lines[li++]));
        li--;
        blocks.push(<div key={`${i}-t${blocks.length}`} className="md-table"><table><thead><tr>{head.map((c, k) => <th key={k}>{inline(c)}</th>)}</tr></thead><tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody></table></div>);
        continue;
      }
      const q = /^\s*>\s?(.*)$/.exec(line);
      if (q) { flushPara(); flushList(); quote.push(q[1]); continue; } else flushQuote();
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { flushPara(); flushList(); blocks.push(<hr key={`${i}-r${blocks.length}`} />); continue; }
      const bullet = /^\s*[-*•+]\s+(.*)$/.exec(line), numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line), heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (bullet || numbered) {
        flushPara();
        const ordered = !!numbered;
        if (list && list.ordered !== ordered) flushList();
        list = list ?? { ordered, items: [] };
        list.items.push((bullet ?? numbered)![1]);
      } else if (heading) { flushPara(); flushList(); const H = (`h${Math.min(heading[1].length + 1, 6)}`) as 'h2'; blocks.push(<H key={`${i}-h${blocks.length}`} className="md-h">{inline(heading[2])}</H>); }
      else if (!line.trim()) { flushPara(); flushList(); }
      else { flushList(); para.push(line); }
    }
    flushPara(); flushList(); flushQuote();
  });
  return <div className={`prose ${className} ${streaming ? 'streaming' : ''}`}>{blocks}</div>;
}

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|!?\[[^\]]*\]\([^)\s]+\)|\*[^*\s][^*]*\*)/g;
  let last = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    const link = /^!?\[([^\]]*)\]\(([^)\s]+)\)$/.exec(token);
    if (token.startsWith('`')) out.push(<code key={k++}>{token.slice(1, -1)}</code>);
    else if (token.startsWith('**')) out.push(<strong key={k++}>{inline(token.slice(2, -2))}</strong>);
    else if (link) out.push(/^https?:/.test(link[2]) ? <a key={k++} href={link[2]} target="_blank" rel="noreferrer noopener">{link[1] || link[2]}</a> : <span key={k++} className="md-link">{link[1] || link[2]}</span>);
    else out.push(<em key={k++}>{token.slice(1, -1)}</em>);
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return <div className="codeblock">
    <header><span>{lang || 'code'}</span>
      <button className="icon-btn sm" aria-label="Copy code" onClick={() => { void navigator.clipboard?.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1400); }); }}>
        {copied ? <Check size={12} /> : <Copy size={12} />}
      </button>
    </header>
    <pre><code>{code}</code></pre>
  </div>;
}
