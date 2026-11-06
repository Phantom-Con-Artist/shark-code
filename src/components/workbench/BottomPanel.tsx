import { lazy, Suspense, useEffect, useMemo } from 'react';
import { CircleAlert, Maximize2, Minimize2, Plus, SquareTerminal, Sparkles, Trash2, TriangleAlert, X } from 'lucide-react';
import { useSettings } from '../../stores/useSettings';
import { useTerminals } from '../../stores/useTerminals';
import { useUi, type Problem } from '../../stores/useUi';
import { FileIcon } from './primitives';
import { openPath } from './Sidebar';

const WorkspaceTerminal = lazy(() => import('./Terminal').then(m => ({ default: m.WorkspaceTerminal })));

export function askAgent(text: string) {
  useUi.getState().set({ draft: { text, nonce: Date.now() } });
}

function TerminalStrip() {
  const tabs = useTerminals(s => s.tabs);
  const activeId = useTerminals(s => s.activeId);
  useEffect(() => { if (useTerminals.getState().tabs.length === 0) useTerminals.getState().add(); }, []);
  return <div className="term-tabs" role="tablist" aria-label="Terminals">
    {tabs.map(t => <div key={t.id} className={`term-tab ${t.id === activeId ? 'active' : ''}`}>
      <button role="tab" aria-selected={t.id === activeId} onClick={() => useTerminals.getState().setActive(t.id)}>
        <SquareTerminal size={12} /><span className="ellipsis">{t.title}</span>
      </button>
      <button className="icon-btn sm" aria-label={`Close ${t.title}`} title="Close terminal" onClick={e => { e.stopPropagation(); useTerminals.getState().remove(t.id); }}><X size={11} /></button>
    </div>)}
    <button className="icon-btn sm" aria-label="New terminal" title="New terminal" onClick={() => useTerminals.getState().add()}><Plus size={13} /></button>
  </div>;
}

export function BottomPanel({ maximized, onMaximize }: { maximized: boolean; onMaximize(v: boolean): void }) {
  const tab = useUi(u => u.panelTab);
  const problems = useUi(u => u.problems);
  const set = useUi(u => u.set);
  const termTabs = useTerminals(s => s.tabs);
  const activeTermId = useTerminals(s => s.activeId);
  const errors = problems.filter(p => p.severity === 'error').length;
  const close = () => { useSettings.getState().set({ terminalOpen: false }); onMaximize(false); };

  return <section className="panel" aria-label="Panel">
    <header className="panel-head">
      <div className="panel-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'terminal'} onClick={() => set({ panelTab: 'terminal' })}>Terminal</button>
        <button role="tab" aria-selected={tab === 'problems'} onClick={() => set({ panelTab: 'problems' })}>Problems{problems.length > 0 && <span className={`count ${errors ? 'err' : ''}`}>{problems.length}</span>}</button>
      </div>
      {tab === 'terminal' && <TerminalStrip />}
      <span className="grow" />
      {tab === 'terminal' && <button className="icon-btn sm" aria-label="Clear terminal" title="Clear scrollback" onClick={() => void import('./Terminal').then(m => m.clearTerminal())}><Trash2 size={13} /></button>}
      {tab === 'problems' && problems.length > 0 && <button className="btn sm ghost" onClick={() => askAgent(`Fix these problems:\n${problems.slice(0, 30).map(p => `- ${p.path}:${p.line}:${p.column} ${p.message}`).join('\n')}`)}><Sparkles size={12} />Fix all with agent</button>}
      <button className="icon-btn sm" aria-label={maximized ? 'Restore panel size' : 'Maximize panel'} title={maximized ? 'Restore' : 'Maximize'} onClick={() => onMaximize(!maximized)}>{maximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</button>
      <button className="icon-btn sm" aria-label="Close panel" title="Close · Ctrl J" onClick={close}><X size={14} /></button>
    </header>
    <div className="panel-body term-body" hidden={tab !== 'terminal'}>
      <Suspense fallback={null}>{termTabs.map(t => <div key={t.id} className="term-slot" hidden={t.id !== activeTermId}><WorkspaceTerminal sessionId={t.id} /></div>)}</Suspense>
    </div>
    {tab === 'problems' && <div className="panel-body problems"><ProblemList problems={problems} /></div>}
  </section>;
}

function ProblemList({ problems }: { problems: Problem[] }) {
  const groups = useMemo(() => {
    const map = new Map<string, Problem[]>();
    for (const p of problems) { if (!map.has(p.path)) map.set(p.path, []); map.get(p.path)!.push(p); }
    return [...map.entries()];
  }, [problems]);
  if (!problems.length) return <p className="fine" style={{ padding: '10px 14px' }}>No problems in open files.</p>;
  return <>{groups.map(([path, list]) => <div key={path}>
    <div className="problem-file"><FileIcon path={path} size={13} /><span>{path.split('/').pop()}</span><small>{path}</small><span className="count">{list.length}</span></div>
    {list.map((p, i) => <div key={i} className="problem">
      <button className="problem-main" onClick={() => openPath(p.path, p.line)}>
        {p.severity === 'error' ? <CircleAlert size={13} className="sev-err" /> : <TriangleAlert size={13} className="sev-warn" />}
        <span className="msg">{p.message.split('\n')[0]}</span>
        <small>{p.source} · Ln {p.line}, Col {p.column}</small>
      </button>
      <button className="icon-btn sm fix" title="Fix with agent" aria-label="Fix with agent" onClick={() => askAgent(`Fix this ${p.severity} in ${p.path} at line ${p.line}:\n${p.message}`)}><Sparkles size={12} /></button>
    </div>)}
  </div>)}</>;
}
