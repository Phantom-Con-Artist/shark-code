import { useEffect, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { FlaskConical, Play, Plus, Trash2, Workflow } from 'lucide-react';
import { useAutomata } from '../../stores/useAutomata';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { useProjectStore } from '../../stores/useProjectStore';
import { Canvas } from './Canvas';
import { Dock } from './Dock';

export function AutomataView() {
  const a = useAutomata();
  const connected = useAgentWorkspace(s => s.connected);
  const root = useProjectStore(s => s.root);
  const [picker, setPicker] = useState(false);
  const native = isTauri();

  useEffect(() => { if (native && connected) void useAutomata.getState().init(); }, [native, connected, root]);
  useEffect(() => { if (!native || !connected) return; const id = setInterval(() => void useAutomata.getState().refresh(), 2000); return () => clearInterval(id); }, [native, connected]);
  useEffect(() => { const flush = () => { if (useAutomata.getState().dirty) void useAutomata.getState().save(); }; window.addEventListener('beforeunload', flush); return () => window.removeEventListener('beforeunload', flush); }, []);

  if (!native || !connected) return <div className="am-empty"><Workflow size={22} /><p>{native ? 'Connecting to the local backend…' : 'Shark Automata runs in the desktop app. Start it with npm run tauri dev.'}</p></div>;
  const running = a.run?.status === 'running' || a.running;
  const waiting = a.run?.status === 'waiting_human';
  const stats = a.validation;
  return <div className="am">
    <div className="am-bar">
      <div className="am-pick"><button className="am-name" onClick={() => setPicker(p => !p)} aria-expanded={picker} aria-haspopup="listbox"><Workflow size={14} /><span className="ellipsis">{a.graph?.name ?? 'No workflow'}</span></button>
        {picker && <div className="popover am-menu" role="listbox">
          {a.workflows.map(w => <div key={w.id} className="am-opt"><button role="option" aria-selected={w.id === a.graph?.id} onClick={() => { setPicker(false); void a.open(w.id); }}><span className="ellipsis">{w.name}</span><small>{w.nodes} steps</small></button>
            <button className="icon-btn sm" aria-label={`Delete ${w.name}`} onClick={() => { if (window.confirm(`Delete “${w.name}”? The file automata/${w.id}.automata.json will be removed.`)) void a.remove(w.id); }}><Trash2 size={12} /></button></div>)}
          <button className="am-new" onClick={() => { setPicker(false); void a.newGraph(); }}><Plus size={13} />New workflow</button>
        </div>}
      </div>
      {a.graph && <span className="am-save">{a.saving ? 'Saving…' : a.dirty ? 'Unsaved' : 'Saved'}</span>}
      {stats && !stats.ok && <button className="am-chip bad" onClick={() => { a.select([]); a.showDock('inspector'); }}>{stats.errors.length} problem{stats.errors.length === 1 ? '' : 's'}</button>}
      <span className="grow" />
      {running && <span className="am-chip live"><span className="dot live" />Working</span>}
      {waiting && <button className="am-chip warn" onClick={() => a.showDock('run')}>Needs your decision</button>}
      <button className="btn" disabled={!a.graph || running || !a.graph.nodes.length} onClick={() => void a.start('test')} title="Dry run: nothing is written, no commands run"><FlaskConical size={13} />Test</button>
      <button className="btn primary" disabled={!a.graph || running || !a.graph.nodes.length} onClick={() => void a.start('run')} title="Run for real. Steps that change things ask first"><Play size={13} />Run</button>
      <button className="btn" disabled={!a.graph} aria-pressed={a.dockOpen} onClick={() => useAutomata.setState(s => ({ dockOpen: !s.dockOpen }))}>Details</button>
    </div>
    {a.external && <div className="am-banner"><span>This workflow changed on disk, probably from a Shark proposal.</span><span className="grow" /><button className="btn" onClick={() => void a.reload()}>Load the new version</button><button className="btn" onClick={() => void a.save(true)}>Keep mine</button></div>}
    {a.error && <div className="am-banner bad" role="alert"><span>{a.error}</span><span className="grow" /><button className="btn" onClick={() => a.setError('')}>Dismiss</button></div>}
    <div className="am-stage">
      {a.graph ? <Canvas key={a.graph.id} /> : <div className="am-empty"><Workflow size={22} /><strong>Empty canvas</strong><p>Create a workflow, drag components in, or describe your goal to Shark on the right.</p><button className="btn primary" onClick={() => void a.newGraph()}><Plus size={13} />New workflow</button></div>}
    </div>
    {a.graph && a.dockOpen && <Dock />}
  </div>;
}
