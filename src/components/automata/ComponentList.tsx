import { useMemo, useState } from 'react';
import { ChevronRight, FlaskConical, Search, Sparkles } from 'lucide-react';
import { useAutomata } from '../../stores/useAutomata';
import { useUi } from '../../stores/useUi';
import { sharkAutomata, type ComponentSpec, type ComponentTest } from '../../lib/automata';
import { ComponentIcon } from './icons';
import { canvasCenter, revealOnCanvas, DRAG_TYPE } from './Canvas';

const ORDER = ['Triggers', 'Code Intelligence', 'Data', 'Flow', 'Integrations', 'System', 'Human', 'AI'];

export function ComponentList() {
  const a = useAutomata();
  const [query, setQuery] = useState('');
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const [tests, setTests] = useState<Record<string, ComponentTest | string>>({});
  const q = query.trim().toLowerCase();
  const groups = useMemo(() => {
    const map = new Map<string, ComponentSpec[]>();
    for (const c of a.catalog) if (!q || `${c.label} ${c.description} ${c.category} ${c.type}`.toLowerCase().includes(q)) map.set(c.category, [...(map.get(c.category) ?? []), c]);
    return [...map.entries()].sort(([x], [y]) => (ORDER.indexOf(x) + 1 || 99) - (ORDER.indexOf(y) + 1 || 99) || x.localeCompare(y));
  }, [a.catalog, q]);

  const add = (type: string) => {
    const st = useAutomata.getState();
    if (!st.graph) { void st.newGraph().then(() => useAutomata.getState().addNode(type, 80, 80)); return; }
    // Build left to right: a new step lands to the right of the selected one and is wired to it.
    const from = st.graph.nodes.find(n => n.id === st.selected[0]);
    const fromSpec = from && st.catalog.find(c => c.type === from.type);
    const c = from ? { x: from.x + 270, y: from.y } : canvasCenter();
    const id = st.addNode(type, c.x, c.y);
    if (id && from && fromSpec?.outputs.length) {
      const used = new Set(st.graph.edges.filter(e => e.from === from.id).map(e => e.from_port));
      const port = fromSpec.outputs.find(o => !used.has(o)) ?? fromSpec.outputs[0];
      useAutomata.getState().connect(from.id, port, id);
    }
    if (id) revealOnCanvas(c.x, c.y);
  };
  const test = async (c: ComponentSpec) => { setTests(t => ({ ...t, [c.type]: 'Testing…' })); try { const r = await sharkAutomata.testComponent(c.id!); setTests(t => ({ ...t, [c.type]: r })); } catch (e) { setTests(t => ({ ...t, [c.type]: e instanceof Error ? e.message : String(e) })); } };
  const ask = () => { useUi.getState().set({ draft: { text: 'Build a component that ', nonce: Date.now() }, composerFocus: Date.now() }); };

  return <div className="cl">
    <label className="cl-search"><Search size={13} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search components" aria-label="Search components" /></label>
    <button className="cl-build" onClick={ask}><Sparkles size={13} />Build a component with Shark</button>
    <div className="cl-groups">
      {groups.map(([cat, items]) => { const open = q ? true : !closed.has(cat);
        return <section key={cat}>
          <button className="run-group run-toggle" aria-expanded={open} onClick={() => setClosed(s => { const n = new Set(s); if (n.has(cat)) n.delete(cat); else n.add(cat); return n; })}><ChevronRight size={11} style={{ transform: open ? 'rotate(90deg)' : undefined }} />{cat} · {items.length}</button>
          {open && items.map(c => { const t = tests[c.type]; return <div key={c.type} className="cl-item-wrap">
            <div className="cl-item" draggable onDragStart={e => { e.dataTransfer.setData(DRAG_TYPE, c.type); e.dataTransfer.effectAllowed = 'copy'; }} onClick={() => add(c.type)} title={`${c.description}\nDrag onto the canvas or click to add`} role="button" tabIndex={0}
              onKeyDown={e => { if (e.key === 'Enter') add(c.type); }}>
              <span className="cl-ico"><ComponentIcon name={c.icon} /></span><span className="text"><span className="ellipsis">{c.label}</span><small className="ellipsis">{c.description}</small></span>
              {!c.builtin && <button className="icon-btn sm" aria-label={`Test ${c.label}`} title="Run this component's tests" onClick={e => { e.stopPropagation(); void test(c); }}><FlaskConical size={12} /></button>}
              {c.effect && <span className="cl-tag" title="Asks before running">asks</span>}
            </div>
            {t && <p className={`cl-test ${typeof t === 'object' && t.passed ? 'ok' : 'bad'}`}>{typeof t === 'string' ? t : `${t.cases.filter(x => x.passed).length}/${t.cases.length} tests passed${t.cases.find(x => !x.passed)?.error ? ': ' + t.cases.find(x => !x.passed)!.error!.slice(0, 120) : ''}`}</p>}
          </div>; })}
        </section>; })}
      {!groups.length && <p className="search-meta">No component matches “{query}”. Ask Shark to build it.</p>}
      {a.problems.map(p => <p key={p.file} className="cl-test bad" title={p.file}>{p.file.split('/').pop()}: {p.error}</p>)}
    </div>
  </div>;
}
