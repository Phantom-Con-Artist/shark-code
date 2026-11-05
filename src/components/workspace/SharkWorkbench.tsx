import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUp, Check, ChevronDown, ChevronRight, Code2, FileCode2, Files, Focus, FolderOpen, Menu, MessageSquare, PanelLeftClose, PanelRightClose, PanelRightOpen, Plus, Search, Settings2, ShieldCheck, Square, Terminal, X } from 'lucide-react';
import { FileExplorer, ProjectFiles } from './ProjectFiles';
import { TaskReview } from './TaskReview';
import { useProjectStore } from '../../stores/useProjectStore';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { useReadingPreferences } from '../../stores/useReadingPreferences';
const WorkspaceTerminal = lazy(() => import('./WorkspaceTerminal').then(m => ({ default: m.WorkspaceTerminal })));

function SharkMark() { return <svg className="shark-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M5 25C11 19 14 10 16 4c1 9 5 13 11 21H5Z" fill="currentColor"/><path d="m8 25 11-6-3 6H8Z" fill="var(--ground)"/></svg>; }
const statusLabel: Record<string,string> = { created: 'Ready', running: 'Working', review: 'Ready for review', applied: 'Applied', completed: 'Completed', cancelled: 'Stopped', interrupted: 'Interrupted', failed: 'Needs attention' };

export function SharkWorkbench() {
  const project = useProjectStore();
  const agent = useAgentWorkspace();
  const prefs = useReadingPreferences();
  const [sideView, setSideView] = useState<'files' | 'tasks'>('files');
  const [inspector, setInspector] = useState<'source' | 'review'>('source');
  const [editorOpen, setEditorOpen] = useState(() => window.innerWidth > 760);
  const [navOpen, setNavOpen] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [dialog, setDialog] = useState<'settings' | 'search' | null>(null);
  const [search, setSearch] = useState('');
  const [input, setInput] = useState('');
  const [submitError, setSubmitError] = useState('');
  const composer = useRef<HTMLTextAreaElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const task = agent.tasks.find(t => t.id === agent.activeId);
  const running = task?.status === 'running';
  const native = project.kind === 'native';
  const status = running ? 'Working on your task' : agent.busy ? 'Checking the workspace' : task ? statusLabel[task.status] : 'Ready when you are';
  useEffect(() => { void useProjectStore.getState().initialize(); }, []);
  useEffect(() => { if (project.kind === 'native') void useAgentWorkspace.getState().connect(); }, [project.root, project.kind]);
  useEffect(() => {
    document.documentElement.style.setProperty('--ui-size', `${prefs.fontSize}px`);
    document.documentElement.dataset.density = prefs.density;
    document.documentElement.dataset.readingFont = prefs.readingFont;
    document.documentElement.dataset.contrast = prefs.highContrast ? 'high' : 'standard';
    document.documentElement.dataset.motion = prefs.reduceMotion ? 'reduced' : 'system';
  }, [prefs.fontSize, prefs.density, prefs.readingFont, prefs.highContrast, prefs.reduceMotion]);
  useEffect(() => {
    if (!task || !native || task.status !== 'running') return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      if (disposed) return;
      await useAgentWorkspace.getState().poll();
      if (!disposed) timer = setTimeout(tick, 1000);
    }
    timer = setTimeout(tick, 700);
    return () => { disposed = true; clearTimeout(timer); };
  }, [task?.id, task?.status, native]);
  const fresh = () => { agent.fresh(); setInput(''); setSubmitError(''); setNavOpen(false); composer.current?.focus(); };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) {
        if (e.key.toLowerCase() === 'k' || e.key.toLowerCase() === 'p') { e.preventDefault(); setSearch(''); setDialog('search'); }
        if (e.key === ',') { e.preventDefault(); setDialog('settings'); }
        if (e.key.toLowerCase() === 'n') { e.preventDefault(); fresh(); }
        if (e.key === '`') { e.preventDefault(); setTerminalOpen(v => !v); }
        if (e.shiftKey && e.key.toLowerCase() === 'f') { e.preventDefault(); setFocusMode(v => !v); }
      }
      if (e.key === 'Escape') { setDialog(null); setNavOpen(false); }
    };
    window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key);
  }, []);
  useEffect(() => {
    const node = dialog ? dialogRef.current : navOpen ? navRef.current : null;
    if (!node) return;
    const previous = document.activeElement as HTMLElement | null;
    const elements = () => Array.from(node.querySelectorAll<HTMLElement>('button:not(:disabled), input, textarea, select, [tabindex="0"]'));
    elements()[0]?.focus();
    const trap = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const list = elements(), first = list[0], last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    node.addEventListener('keydown', trap);
    return () => { node.removeEventListener('keydown', trap); previous?.focus(); };
  }, [dialog, navOpen]);
  async function send() {
    const value = input.trim(); if (!value || running || agent.busy) return;
    setSubmitError('');
    if (!native) { setSubmitError('Open the Tauri desktop app to run your coding agent. You can edit the browser workspace here.'); return; }
    if (!agent.connected) { setSubmitError('The workspace backend is unavailable. Retry the connection below.'); return; }
    if (!prefs.model.trim()) { setSubmitError('Choose your backend model ID in Settings before starting an agent.'); setDialog('settings'); return; }
    await agent.run(value, prefs.model.trim());
    if (!useAgentWorkspace.getState().error) setInput('');
  }
  function source() { setInspector('source'); setEditorOpen(true); setFocusMode(false); setNavOpen(false); }
  const textEvents = agent.events.filter(e => e.kind === 'text');
  const lastText = agent.events.map(e => e.kind).lastIndexOf('text');
  const partial = agent.events.slice(lastText + 1).filter(e => e.kind === 'text_delta').map(e => String(e.data.text || '')).join('');
  const toolEvents = agent.events.filter(e => e.kind === 'tool_call');
  const fileMatches = project.entries.filter(e => !e.directory && e.path.toLowerCase().includes(search.toLowerCase())).slice(0, 20);
  const commands = [{ name: 'New task', action: fresh }, { name: 'Toggle terminal', action: () => setTerminalOpen(v => !v) }, { name: 'Toggle focus mode', action: () => setFocusMode(v => !v) }, { name: 'Reading preferences', action: () => setDialog('settings') }];
  return <div className={`workbench ${focusMode ? 'focus-mode' : ''} ${editorOpen ? '' : 'editor-collapsed'} ${navOpen ? 'nav-open' : ''}`}>
    <a className="skip-link" href="#task-composer">Skip to task composer</a><a className="skip-link skip-source" href="#source-workspace" onClick={source}>Skip to source</a>
    <header className="window-bar"><div className="window-brand"><SharkMark/><strong>shark<span>code</span></strong></div><button className="window-search" onClick={() => { setSearch(''); setDialog('search'); }}><Search size={14}/><span>{project.name}</span><kbd>Ctrl K</kbd></button><div className="window-controls"><button className="icon-button" onClick={() => setFocusMode(v => !v)} aria-pressed={focusMode} aria-label={focusMode ? 'Exit focus mode' : 'Enter focus mode'} title="Focus mode · Ctrl Shift F"><Focus size={16}/></button><button className="icon-button" onClick={() => setDialog('settings')} aria-label="Settings" title="Settings"><Settings2 size={16}/></button></div></header>
    <div className="workbench-body" inert={dialog !== null || undefined}>
      <nav className="activity-rail" aria-label="Workspace views"><button className={`rail-button ${sideView === 'files' ? 'selected' : ''}`} aria-label="Files" title="Files" onClick={() => { setSideView('files'); setNavOpen(v => !v); setFocusMode(false); }}><Files size={21}/></button><button className={`rail-button ${sideView === 'tasks' ? 'selected' : ''}`} aria-label="Tasks" title="Tasks" onClick={() => { setSideView('tasks'); setNavOpen(true); setFocusMode(false); }}><MessageSquare size={20}/></button><button className="rail-button" aria-label="Find a file" title="Find a file · Ctrl P" onClick={() => { setSearch(''); setDialog('search'); }}><Search size={20}/></button><button className={`rail-button ${terminalOpen ? 'selected' : ''}`} aria-label="Toggle terminal" title="Terminal · Ctrl `" onClick={() => setTerminalOpen(v => !v)}><Terminal size={20}/></button><div className="rail-bottom"><button className="rail-button" aria-label="Reading and focus settings" title="Reading and focus settings" onClick={() => setDialog('settings')}><Settings2 size={20}/></button><span className="local-avatar" title="Local workspace">S</span></div></nav>
      {navOpen && <button className="navigation-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)}/>}
      <aside className="workbench-sidebar" ref={navRef} role={navOpen && window.innerWidth < 1000 ? 'dialog' : undefined} aria-modal={navOpen && window.innerWidth < 1000 ? true : undefined} aria-label="Project navigation"><div className="sidebar-project"><span><FolderOpen size={16}/><strong>{project.name}</strong></span><button className="icon-button mobile-nav-close" aria-label="Close navigation" onClick={() => setNavOpen(false)}><X size={16}/></button><button className="icon-button desktop-nav-close" aria-label="Focus on conversation" title="Focus on conversation" onClick={() => setFocusMode(true)}><PanelLeftClose size={15}/></button></div>
        <div className="sidebar-switch" aria-label="Sidebar view"><button aria-pressed={sideView === 'files'} onClick={() => setSideView('files')}>Explorer</button><button aria-pressed={sideView === 'tasks'} onClick={() => setSideView('tasks')}>Tasks {agent.tasks.length > 0 && <span>{agent.tasks.length}</span>}</button></div>
        {sideView === 'files' ? <FileExplorer onOpen={source}/> : <div className="task-navigation"><button className="new-task-button" onClick={fresh}><Plus size={15}/>New task<kbd>Ctrl N</kbd></button><p className="section-label">Recent tasks</p>{agent.tasks.length ? agent.tasks.map(t => <button className={`task-list-row ${agent.activeId === t.id ? 'active' : ''}`} key={t.id} onClick={() => { void agent.select(t.id); setNavOpen(false); }}><MessageSquare size={14}/><span><strong>{t.goal}</strong><small>{statusLabel[t.status]}</small></span></button>) : <p className="empty-label">Your tasks will appear here.<br/>Each one keeps its conversation and review history.</p>}</div>}
        <div className="sidebar-foot"><ShieldCheck size={14}/><span>{native ? 'Local workspace' : 'Browser workspace'}<small>{native ? 'Changes wait for your review' : 'Edits save in this browser'}</small></span></div>
      </aside>
      <div className="working-area"><div className="workspace-heading"><button className="icon-button mobile-nav-toggle" onClick={() => setNavOpen(true)} aria-label="Open project navigation"><Menu size={17}/></button><span className="workspace-crumb"><span>{project.name}</span><ChevronRight size={12}/><h1>{task ? 'Agent task' : 'New task'}</h1></span><div><button className="text-button" aria-label={focusMode ? 'Exit focus mode' : 'Enter focus mode'} aria-pressed={focusMode} onClick={() => setFocusMode(v => !v)}><Focus size={14}/><span>{focusMode ? 'Exit focus' : 'Focus'}</span></button><button className="icon-button" aria-label={editorOpen ? 'Hide source workspace' : 'Show source workspace'} onClick={() => { setEditorOpen(v => !v); setFocusMode(false); }}>{editorOpen ? <PanelRightClose size={17}/> : <PanelRightOpen size={17}/>}</button></div></div>
        <div className="work-columns"><main className="agent-pane" id="conversation" tabIndex={-1}><div className="pane-toolbar"><span><MessageSquare size={14}/>Conversation</span><button className="icon-button" aria-label="New task" title="New task" onClick={fresh}><Plus size={15}/></button></div>
          <div className="chat-scroll"><div className="chat-content">{task ? <><article className="chat-message"><header><span className="person-mark">S</span><strong>You</strong><span>Task</span></header><p>{task.goal}</p></article><article className="chat-message agent-response"><header><SharkMark/><strong>Shark</strong><span>Agent</span></header>{toolEvents.length > 0 && <details className="activity-disclosure"><summary>{toolEvents.length} workspace {toolEvents.length === 1 ? 'operation' : 'operations'}</summary>{toolEvents.map(e => <div key={e.sequence}><Check size={13}/><span>{String(e.data.name).replace(/_/g, ' ')}</span></div>)}</details>}{textEvents.map(e => <p className="agent-prose" key={e.sequence}>{String(e.data.text)}</p>)}{running && partial && <p className="agent-prose">{partial}</p>}{!textEvents.length && !partial && <p>{running ? 'The agent is inspecting your workspace. You can keep reading or editing alongside it.' : task.status === 'created' ? 'This task is saved. Configure your backend model to start an invocation.' : 'This task’s events and review are kept with your workspace.'}</p>}{task.status === 'review' && <button className="proposal-link" onClick={() => { setInspector('review'); setEditorOpen(true); setFocusMode(false); }}><ShieldCheck size={18}/><span><strong>A proposal is ready.</strong><small>Inspect the files and potential impact before applying.</small></span><ArrowRight size={16}/></button>}</article></> : <div className="workspace-welcome"><h2>A little direction.<br/>A clear path forward.</h2><p>Describe what you want to build.<br/>Keep the conversation, code, and every decision together.</p><div className="welcome-workflow"><div><Search size={16}/><span><strong>Understand the code.</strong><small>Explore files and their connections.</small></span></div><div><Code2 size={16}/><span><strong>Make a focused change.</strong><small>Your agent prepares precise edits.</small></span></div><div><ShieldCheck size={16}/><span><strong>Review with confidence.</strong><small>See what changes and what it could affect.</small></span></div></div><button className="welcome-start" onClick={() => { setInput('Help me understand how this project is structured.'); composer.current?.focus(); }}>Explore this project<ArrowRight size={15}/></button></div>}
<div ref={bottom}/></div></div>
          {task && <div className="latest-control"><button className="text-button" onClick={() => bottom.current?.scrollIntoView({ block: 'end', behavior: 'instant' })}><ArrowDown size={13}/>Latest activity</button></div>}
          <div className="composer-region"><div className="task-state" role="status"><span className={`status-dot ${running ? 'working' : ''}`}/><span>{status}</span>{running && <button className="text-button" onClick={() => void agent.cancel()}><Square size={11}/>Stop</button>}</div>
            {(submitError || agent.error || project.error) && <div className="workspace-error" role="alert"><p>{submitError || agent.error || project.error}</p><button className="icon-button" aria-label="Dismiss message" onClick={() => { setSubmitError(''); agent.clearError(); project.clearError(); }}><X size={14}/></button>{native && !agent.connected && <button className="text-button" onClick={() => void agent.connect()}>Retry backend</button>}</div>}
            <form className="task-composer" onSubmit={e => { e.preventDefault(); void send(); }}><label htmlFor="task-composer" className="sr-only">Describe your task</label><textarea id="task-composer" ref={composer} value={input} onChange={e => setInput(e.target.value)} placeholder="Describe a change, ask a question…" rows={3} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }}/><div className="composer-tools"><span className="composer-mode"><MessageSquare size={13}/>Agent</span><button type="button" className="model-control" onClick={() => setDialog('settings')}>{prefs.model || 'Configure model'}<ChevronDown size={11}/></button><button className="send-task" type="submit" disabled={!input.trim() || running || agent.busy} aria-label="Start agent task" title="Start agent task"><ArrowUp size={17}/></button></div></form><div className="composer-caption"><span>{native ? 'Edits are proposed before applying.' : 'Browser preview · native agents in desktop app'}</span><span>Shift + Enter for a new line</span></div>
          </div>
        </main><aside id="source-workspace" tabIndex={-1} className="source-pane" aria-label="Source and review"><div className="inspector-tabs" aria-label="Source workspace view"><button aria-pressed={inspector === 'source'} onClick={() => setInspector('source')}><Code2 size={14}/>Source</button><button aria-pressed={inspector === 'review'} onClick={() => setInspector('review')}><ShieldCheck size={14}/>Review{agent.proposal && <span>{agent.proposal.files.length}</span>}</button></div>{inspector === 'source' ? <ProjectFiles/> : <TaskReview/>}</aside></div>
        {terminalOpen && <Suspense fallback={<div className="terminal-loading">Opening terminal…</div>}><WorkspaceTerminal onClose={() => setTerminalOpen(false)}/></Suspense>}
      </div>
    </div><footer className="workbench-status"><span><span className="status-dot"/>{native ? agent.connected ? 'Backend connected' : 'Connecting backend' : 'Browser preview'}</span><span className="status-files"><Files size={12}/>{project.entries.filter(e => !e.directory).length} files</span><button onClick={() => setTerminalOpen(v => !v)}><Terminal size={12}/>{terminalOpen ? 'Hide terminal' : 'Terminal'}</button><span className="status-spacer"/><button onClick={() => setDialog('settings')}>{prefs.density === 'compact' ? 'Compact' : 'Comfortable'} · {prefs.fontSize}px</button><span className="review-status"><ShieldCheck size={12}/>Review before applying</span></footer>
    {dialog && <div className="dialog-backdrop" onClick={e => { if (e.currentTarget === e.target) setDialog(null); }}><div className={`workbench-dialog ${dialog === 'search' ? 'command-dialog' : ''}`} ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="dialog-title"><header><h2 id="dialog-title">{dialog === 'settings' ? 'Workspace settings' : 'Go to file or action'}</h2><button className="icon-button" aria-label="Close dialog" onClick={() => setDialog(null)}><X size={18}/></button></header>{dialog === 'search' ? <><label className="command-input"><Search size={17}/><input autoFocus aria-label="Find a file or action" placeholder="Search files or actions…" value={search} onChange={e => setSearch(e.target.value)}/><kbd>Esc</kbd></label><div className="command-results">{commands.filter(c => c.name.toLowerCase().includes(search.toLowerCase())).map(c => <button key={c.name} onClick={() => { setDialog(null); c.action(); }}><ArrowRight size={15}/><span>{c.name}</span></button>)}{fileMatches.map(e => <button key={e.path} onClick={() => { void project.openFile(e.path); source(); setDialog(null); }}><FileCode2 size={15}/><span>{e.path}</span></button>)}{!fileMatches.length && !commands.some(c => c.name.toLowerCase().includes(search.toLowerCase())) && <p>No matching files or actions.</p>}</div></> : <div className="settings-content"><section><h3>Reading & focus</h3><p>Choose what feels comfortable. These settings stay in this browser or desktop profile.</p><div className="settings-grid"><label>Spacing<select value={prefs.density} onChange={e => prefs.set({ density: e.target.value as 'compact' | 'comfortable' })}><option value="compact">Compact</option><option value="comfortable">Comfortable</option></select></label><label>Interface text<select value={prefs.fontSize} onChange={e => prefs.set({ fontSize: Number(e.target.value) })}><option value={13}>13px — default</option><option value={15}>15px — larger</option><option value={17}>17px — largest</option></select></label><label>Reading font<select value={prefs.readingFont} onChange={e => prefs.set({ readingFont: e.target.value as 'system' | 'readable' })}><option value="system">System sans</option><option value="readable">Verdana</option></select></label></div><label className="setting-toggle"><span>Higher contrast<small>Stronger text and control boundaries.</small></span><input type="checkbox" checked={prefs.highContrast} onChange={e => prefs.set({ highContrast: e.target.checked })}/></label><label className="setting-toggle"><span>Reduce motion<small>Keep feedback still and avoid blinking cursors.</small></span><input type="checkbox" checked={prefs.reduceMotion} onChange={e => prefs.set({ reduceMotion: e.target.checked })}/></label><label className="setting-toggle"><span>Focus on the conversation<small>Hide the file explorer and source until you need them.</small></span><input type="checkbox" checked={focusMode} onChange={e => setFocusMode(e.target.checked)}/></label></section><section><h3>Agent connection</h3><p>ADK uses credentials from your backend environment. Set <code>GOOGLE_API_KEY</code> or configure Vertex AI, then enter a supported model ID.</p><label className="model-setting">Backend model ID<input placeholder="Your configured Gemini model ID" value={prefs.model} onChange={e => prefs.set({ model: e.target.value })} spellCheck={false}/></label><p className="muted">This field stores the model name. API keys are not entered or stored here.</p></section><section className="keyboard-help"><h3>Keyboard shortcuts</h3><p><span>Find files & actions</span><kbd>Ctrl / ⌘ K</kbd></p><p><span>Save file</span><kbd>Ctrl / ⌘ S</kbd></p><p><span>Toggle terminal</span><kbd>Ctrl / ⌘ `</kbd></p><p><span>Toggle focus</span><kbd>Ctrl / ⌘ Shift F</kbd></p><p className="muted">In the code editor, Tab moves focus. Ctrl / ⌘ M toggles Tab behavior.</p></section><button className="primary-button" onClick={() => setDialog(null)}>Done</button></div>}</div></div>}
  </div>;
}
