import { useMemo, useRef, useState } from 'react';
import { ArrowRight, Search } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
import { useUi } from '../../stores/useUi';
import { FileIcon, useFocusTrap } from './primitives';
import { openPath } from './Sidebar';

export type Command = { id: string; label: string; keys?: string; run(): void };

/** Subsequence match with a bonus for contiguous runs and filename hits. */
function score(query: string, text: string) {
  if (!query) return 1;
  const q = query.toLowerCase(), t = text.toLowerCase();
  let qi = 0, run = 0, total = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) { qi++; run++; total += run * 2 + (i === 0 || '/._-'.includes(t[i - 1]) ? 4 : 0); } else run = 0;
  }
  if (qi < q.length) return 0;
  const base = t.slice(t.lastIndexOf('/') + 1);
  return total + (base.includes(q) ? 30 : 0) - t.length * 0.05;
}

export function CommandPalette({ commands }: { commands: Command[] }) {
  const dialog = useUi(s => s.dialog);
  const entries = useProjectStore(s => s.entries);
  const filesOnly = dialog === 'files';
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, true);
  const close = () => useUi.getState().open(null);

  const items = useMemo(() => {
    const files = entries.filter(e => !e.directory)
      .map(e => ({ kind: 'file' as const, id: e.path, label: e.path, s: score(query, e.path) }))
      .filter(f => f.s > 0).sort((a, b) => b.s - a.s).slice(0, query ? 40 : 12);
    const cmds = filesOnly ? [] : commands.map(c => ({ kind: 'cmd' as const, id: c.id, label: c.label, s: score(query, c.label), c }))
      .filter(c => c.s > 0).sort((a, b) => b.s - a.s);
    return filesOnly ? files : [...cmds, ...files];
  }, [entries, commands, query, filesOnly]);

  const run = (i: number) => {
    const item = items[i]; if (!item) return;
    close();
    if (item.kind === 'file') openPath(item.id); else item.c.run();
  };

  const firstFile = items.findIndex(i => i.kind === 'file');
  return <div className="scrim" onPointerDown={e => { if (e.target === e.currentTarget) close(); }}>
    <div className="dialog" ref={ref} role="dialog" aria-modal="true" aria-label={filesOnly ? 'Go to file' : 'Command palette'}>
      <label className="palette-input">
        <Search size={16} />
        <input autoFocus value={query} placeholder={filesOnly ? 'Go to file…' : 'Search files and commands…'} aria-label="Search"
          role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={items[index] ? `pi-${index}` : undefined}
          onChange={e => { setQuery(e.target.value); setIndex(0); }}
          onKeyDown={e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setIndex(i => Math.min(i + 1, items.length - 1)); list.current?.querySelector(`#pi-${Math.min(index + 1, items.length - 1)}`)?.scrollIntoView({ block: 'nearest' }); }
            if (e.key === 'ArrowUp') { e.preventDefault(); setIndex(i => Math.max(i - 1, 0)); list.current?.querySelector(`#pi-${Math.max(index - 1, 0)}`)?.scrollIntoView({ block: 'nearest' }); }
            if (e.key === 'Enter') { e.preventDefault(); run(index); }
            if (e.key === 'Escape') { e.preventDefault(); close(); }
          }} />
        <kbd>Esc</kbd>
      </label>
      <div className="palette-list" id="palette-list" role="listbox" ref={list}>
        {!items.length && <p className="empty">Nothing matches “{query}”.</p>}
        {items.map((item, i) => <div key={item.kind + item.id}>
          {i === 0 && item.kind === 'cmd' && <div className="label">Commands</div>}
          {i === firstFile && <div className="label">{query ? 'Files' : 'Recent files'}</div>}
          <button id={`pi-${i}`} role="option" aria-selected={i === index} className={`menu-item ${i === index ? 'focused' : ''}`} onMouseMove={() => setIndex(i)} onClick={() => run(i)}>
            {item.kind === 'file' ? <FileIcon path={item.id} /> : <ArrowRight size={14} style={{ color: 'var(--fg-4)' }} />}
            {item.kind === 'file'
              ? <span className="ellipsis">{item.id.split('/').pop()}<span className="path">{item.id.split('/').slice(0, -1).join('/')}</span></span>
              : <span className="ellipsis">{item.label}</span>}
            {item.kind === 'cmd' && item.c.keys && <kbd>{item.c.keys}</kbd>}
          </button>
        </div>)}
      </div>
    </div>
  </div>;
}
