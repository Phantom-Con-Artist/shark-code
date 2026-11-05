import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { ProjectFiles } from './ProjectFiles';
import { ChangeReview } from './ChangeReview';
const WorkspaceTerminal = lazy(() => import('./WorkspaceTerminal').then(module => ({ default: module.WorkspaceTerminal })));
import { useProjectStore } from '../../stores/useProjectStore';
import { ArrowDown, ArrowUp, ArrowUpRight, Check, CheckCheck, ChevronDown, ChevronRight, Code2, Command, FileCode2, Folder, GitBranch, GitCompareArrows, Menu, MessageSquare, MoreHorizontal, PanelRightClose, PanelRightOpen, Paperclip, Plus, Search, Settings2, ShieldCheck, Square, Terminal, X } from 'lucide-react';

type Phase = 'idle' | 'planning' | 'working' | 'review' | 'accepted' | 'paused';
type Session = { id: string; title: string; prompt: string; phase: Phase; step: number; replies: string[] };
const samples: Session[] = [
  { id: 'welcome', title: 'Build an agent-first workspace', prompt: 'Let’s build the foundation for Shark Code. Make the conversation the primary workspace, with code and changes right alongside it.', phase: 'review', step: 3, replies: [] },
  { id: 'explore', title: 'Explore the codebase', prompt: 'Help me understand how this project is structured.', phase: 'idle', step: 0, replies: [] },
];
const sampleOriginal = `import { EditorArea } from './components/editor/EditorArea';
import { AgentSidebar } from './components/agent/AgentSidebar';

export default function App() {
  return (
    <main className="editor-layout">
      <EditorArea />
      <AgentSidebar />
    </main>
  );
}
`;
const proposal = `import { ConversationWorkspace } from './components/workspace/ConversationWorkspace';\nimport './App.css';\n\nexport default function App() {\n  return <ConversationWorkspace />;\n}\n`;
const plan = ['Understand the workspace and existing components', 'Build the conversation and code workspace', 'Prepare the changes for your review'];
const suggestions = ['Explore this codebase', 'Build a new feature', 'Find and fix a bug'];
function SharkMark({ small = false }: { small?: boolean }) { return <svg className={small ? 'shark-mark small' : 'shark-mark'} viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M5 25C11 19 14 10 16 4c1 9 5 13 11 21H5Z" fill="currentColor"/><path d="m8 25 11-6-3 6H8Z" fill="var(--ground)"/></svg>; }

export function ConversationWorkspace() {
  const [sessions, setSessions] = useState<Session[]>(samples);
  const [activeId, setActiveId] = useState('welcome');
  const [input, setInput] = useState('');
  const [tab, setTab] = useState<'changes' | 'files'>('changes');
  const project = useProjectStore();
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(() => window.innerWidth > 1000);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mode, setMode] = useState('Build');
  const [model, setModel] = useState('Demo agent');
  const [attached, setAttached] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const [followup, setFollowup] = useState(false);
  useEffect(() => { void useProjectStore.getState().initialize(); }, []);
  const bottom = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const session = sessions.find(s => s.id === activeId)!;
  const running = session.phase === 'planning' || session.phase === 'working';
  const update = (id: string, patch: Partial<Session>) => setSessions(all => all.map(s => s.id === id ? { ...s, ...patch } : s));
  useEffect(() => {
    const pending = sessions.filter(s => s.phase === 'planning' || s.phase === 'working');
    if (!pending.length) return;
    const timer = window.setTimeout(() => setSessions(all => all.map(s => {
      if (s.phase !== 'planning' && s.phase !== 'working') return s;
      const step = s.step + 1;
      return { ...s, step, phase: step >= 3 ? 'review' : 'working' };
    })), 1400);
    return () => window.clearTimeout(timer);
  }, [sessions]);
  useEffect(() => { if (session.replies.length || running) bottom.current?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'end' }); }, [session.phase, session.replies.length, activeId]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'k') { event.preventDefault(); setSearchOpen(v => !v); }
      if ((event.ctrlKey || event.metaKey) && event.key === 'n') { event.preventDefault(); newSession(); }
      if ((event.ctrlKey || event.metaKey) && event.key === ',') { event.preventDefault(); setSettingsOpen(v => !v); }
      if ((event.ctrlKey || event.metaKey) && event.key === '`') { event.preventDefault(); setTerminalOpen(v => !v); }
      if (event.key === 'Escape') { setSearchOpen(false); setSettingsOpen(false); setSidebarOpen(false); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);
  useEffect(() => {
    if (!searchOpen && !settingsOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role=dialog]');
    const targets = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button, input, select, [tabindex="0"]') || []);
    targets()[0]?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const elements = targets();
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', trap);
    return () => { document.removeEventListener('keydown', trap); previous?.focus(); };
  }, [searchOpen, settingsOpen]);
  function newSession() {
    const id = crypto.randomUUID();
    setSessions(all => [{ id, title: 'New conversation', prompt: '', phase: 'idle', step: 0, replies: [] }, ...all]);
    setActiveId(id); setInput(''); setAttached(false); setFollowup(false); setSidebarOpen(false);
    window.setTimeout(() => composer.current?.focus(), 0);
  };
  const send = () => {
    if (!input.trim() || running) return;
    const prompt = input.trim();
    if (!session.prompt) update(activeId, { title: prompt.length > 34 ? `${prompt.slice(0, 34)}…` : prompt, prompt, phase: mode === 'Ask' ? 'idle' : 'planning', step: 0, replies: mode === 'Ask' ? ['Ask mode is ready. Connect an agent runtime to get answers about your workspace.'] : [] });
    else if (mode === 'Ask') update(activeId, { replies: [...session.replies, prompt, 'Ask mode is ready. Connect an agent runtime to get answers about your workspace.'] });
    else update(activeId, { replies: [...session.replies, prompt], phase: 'planning', step: 0 });
    setInput(''); setFollowup(true); setAttached(false);
  };
  const selectSession = (id: string) => { setActiveId(id); setSidebarOpen(false); setInput(''); setAttached(false); setFollowup(false); };
  const ready = session.phase === 'review' || session.phase === 'accepted';
  const status = running ? 'Working' : session.phase === 'paused' ? 'Paused' : session.phase === 'accepted' ? 'Accepted' : session.phase === 'review' ? 'Ready for review' : 'Ready';
  return <div className="workspace-shell">
    <aside className={`workspace-sidebar ${sidebarOpen ? 'is-open' : ''}`} aria-label="Workspace navigation">
      <div className="brand"><SharkMark /><span>shark<span className="brand-light">code</span></span><span className="preview-label">preview</span><button className="icon-button mobile-close" aria-label="Close menu" onClick={() => setSidebarOpen(false)}><X size={17}/></button></div>
      <button className="project-switch" onClick={() => { setTab('files'); setContextOpen(true); setSidebarOpen(false); }}><span className="project-monogram">SC</span><span><strong>{project.name}</strong><small>{project.kind === 'browser' ? 'Browser workspace' : 'Local workspace'}</small></span><ChevronDown size={14}/></button>
      <button className="new-conversation" onClick={newSession}><Plus size={16}/>New conversation<kbd>⌘ N</kbd></button>
      <button className="search-button" aria-label="Search conversations" onClick={() => setSearchOpen(true)}><Search size={15}/>Search conversations<kbd>⌘ K</kbd></button>
      <div className="nav-section-label">Workspace</div>
      <button className="nav-item selected" onClick={() => composer.current?.focus()}><MessageSquare size={16}/>Conversations<span className="nav-count">{sessions.length}</span></button>
      <button className="nav-item" onClick={() => { setTab('files'); setContextOpen(true); setSidebarOpen(false); }}><Folder size={16}/>Project files<ArrowUpRight size={13}/></button>
      <button className="nav-item" aria-label="Toggle terminal" onClick={() => { setTerminalOpen(v => !v); setSidebarOpen(false); }}><Terminal size={16}/>Terminal<kbd>Ctrl `</kbd></button>
      <div className="section-caption"><span>Recent conversations</span><button className="icon-button" aria-label="New conversation" onClick={newSession}><Plus size={14}/></button></div>
      <div className="session-list">{sessions.map(s => <button key={s.id} onClick={() => selectSession(s.id)} className={`session-item ${activeId === s.id ? 'active' : ''}`}><span className={`session-dot ${s.phase === 'review' ? 'needs-review' : s.phase === 'working' || s.phase === 'planning' ? 'in-progress' : ''}`}/><span>{s.title}</span></button>)}</div>
      <div className="sidebar-bottom"><div className="local-note"><ShieldCheck size={16}/><span>Your workspace. Your control.<small>Review every change before applying.</small></span></div><button className="nav-item" aria-label="Preferences" onClick={() => setSettingsOpen(true)}><Settings2 size={16}/>Preferences<kbd>⌘ ,</kbd></button><div className="profile"><span className="avatar">S</span><span>Personal workspace<small>Frontend preview</small></span><span className="version">v0.1</span></div></div>
    </aside>
    {sidebarOpen && <button className="menu-scrim" aria-label="Close navigation" onClick={() => setSidebarOpen(false)}/>}
    <div className="workspace-main">
      <header className="workspace-header"><button className="icon-button menu-toggle" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Menu size={18}/></button><span className="header-project">{project.name}</span><ChevronRight size={13}/><h1 className="header-title">{session.title}</h1><div className="header-actions"><button className={`icon-button ${terminalOpen ? 'is-on' : ''}`} aria-label={terminalOpen ? 'Hide terminal' : 'Show terminal'} title="Toggle terminal" onClick={() => setTerminalOpen(v => !v)}><Terminal size={17}/></button><span className="demo-badge">Demo workspace</span><button className="icon-button" aria-label={contextOpen ? 'Hide code panel' : 'Show code panel'} onClick={() => setContextOpen(v => !v)}>{contextOpen ? <PanelRightClose size={18}/> : <PanelRightOpen size={18}/>}</button></div></header>
      <div className={`workspace-body ${contextOpen ? '' : 'context-hidden'}`}>
        <main className="conversation-pane">
          <div className="conversation-toolbar"><div><MessageSquare size={15}/><span>Conversation</span></div><span className="conversation-date">{session.id === 'welcome' ? 'Sample session' : 'This session'}</span></div>
          <div className="conversation-scroll">
            {!session.prompt ? <div className="empty-conversation"><SharkMark/><h1>What are we building?</h1><p>Bring an idea. Your agent will find the way forward.</p><div className="suggestion-list">{suggestions.map((text, i) => <button key={text} onClick={() => { setInput(text); composer.current?.focus(); }}>{i === 0 ? <Search size={16}/> : i === 1 ? <Code2 size={16}/> : <GitCompareArrows size={16}/>}<span>{text}</span><ArrowUpRight size={14}/></button>)}</div></div> : <div className="thread">
              <div className="thread-context"><GitBranch size={13}/><span>main</span><span className="subtle-separator">/</span><span>shark-code</span></div>
              <article className="message user-message"><div className="message-heading"><span className="avatar user-avatar">S</span><strong>You</strong><time>Just now</time></div><p>{session.prompt}</p></article>
              <article className="message agent-message"><div className="message-heading"><span className="agent-avatar"><SharkMark small/></span><strong>Shark</strong><span className="agent-label">Agent</span></div><p>{session.id === 'welcome' ? 'I’ll put the conversation at the center. You describe the outcome; I’ll handle the plan, the code, and the details—with every change open for review.' : 'Here’s how I’d approach this task. This preview walks through the agent workflow; connecting a runtime will enable real code changes.'}</p>
                <div className="plan"><div className="plan-title"><span>Plan of action</span><span>{session.step} of {plan.length}</span></div>{plan.map((text, i) => <div className={`plan-step ${session.step > i ? 'complete' : ''}`} key={text}><span className="step-marker">{session.step > i ? <Check size={12}/> : i + 1}</span><span>{text}</span>{running && session.step === i && <span className="working-label">In progress</span>}</div>)}</div>
                <button className="activity-summary" onClick={() => setLogsOpen(v => !v)} aria-expanded={logsOpen}><Terminal size={14}/><span>{running ? 'Running demo workflow' : ready ? 'View sample activity' : 'Agent activity'}</span><ChevronDown size={13} className={logsOpen ? 'rotated' : ''}/></button>
                {logsOpen && <div className="activity-log"><code>demo · workspace context loaded</code><code>demo · {session.step >= 1 ? 'plan prepared' : 'waiting for plan'}</code><code>demo · {ready ? 'sample proposal ready' : 'no files changed'}</code></div>}
                {ready && <><p className="completion-copy">{session.id === 'welcome' ? 'The workspace is ready to explore. Conversation on the left, the implementation on the right. Here’s the sample change to the app entry point.' : 'The demo run is complete. The sample proposal in the code panel shows how you’ll inspect and approve an agent’s work.'}</p><button className="change-summary" onClick={() => { setContextOpen(true); setTab('changes'); }}><span className="change-file-icon"><GitCompareArrows size={18}/></span><span><strong>{session.phase === 'accepted' ? 'Sample change accepted' : 'Changes ready for review'}</strong><small>App.tsx <span>·</span> 1 sample file</small></span><span className="review-prompt-label">Review</span><ChevronRight size={15}/></button><div className="agent-signoff"><CheckCheck size={14}/><span>{session.phase === 'accepted' ? 'Accepted in this preview. Workspace files are unchanged.' : 'Your review is the next step.'}</span></div></>}
                {session.phase === 'paused' && <p className="paused-note">Demo run paused. <button onClick={() => update(activeId, { phase: 'working' })}>Resume run</button></p>}
              </article>
              {session.replies.map((reply, i) => <article className="message followup" key={`${i}-${reply}`}><div className="message-heading"><span className="avatar user-avatar">{reply.startsWith('Ask mode') ? 'A' : 'S'}</span><strong>{reply.startsWith('Ask mode') ? 'Shark' : 'You'}</strong></div><p>{reply}</p></article>)}
              <div ref={bottom}/>
            </div>}
          </div>
          <div className="composer-area">{!followup && session.prompt && !running && <button className="followup-suggestion" onClick={() => { setInput('Walk me through the proposed changes'); setMode('Ask'); composer.current?.focus(); }}>Walk me through the changes<ArrowUpRight size={12}/></button>}<form className="composer" onSubmit={e => { e.preventDefault(); send(); }}>
            {attached && <div className="attachment"><FileCode2 size={12}/>{project.activePath || 'No file selected'}<button type="button" aria-label="Remove attachment" onClick={() => setAttached(false)}><X size={12}/></button></div>}
            <textarea ref={composer} value={input} onChange={e => setInput(e.target.value)} placeholder="Describe what you want to build, or ask anything…" aria-label="Message your agent" rows={2} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}/>
            <div className="composer-controls"><button type="button" className="icon-button" aria-label="Attach selected file as context" title="Attach selected file" disabled={!project.activePath} onClick={() => setAttached(v => !v)}><Paperclip size={16}/></button><label className="select-control"><Code2 size={13}/><select aria-label="Agent mode" value={mode} onChange={e => setMode(e.target.value)}><option>Build</option><option>Ask</option></select><ChevronDown size={12}/></label><label className="select-control model-control"><select aria-label="Agent" value={model} onChange={e => setModel(e.target.value)}><option>Demo agent</option><option disabled>Connect a runtime (coming soon)</option></select><ChevronDown size={12}/></label>{running ? <button type="button" className="send-button stop-button" aria-label="Pause agent" onClick={() => update(activeId, { phase: 'paused' })}><Square size={13}/></button> : <button type="submit" className="send-button" aria-label="Send message" disabled={!input.trim()}><ArrowUp size={17}/></button>}</div>
          </form><div className="composer-footnote"><span>Plan. Build. Review. You stay in control.</span><span><kbd>↵</kbd> send <span className="footnote-divider">·</span> <kbd>shift ↵</kbd> new line</span></div></div>
        </main>
        {contextOpen && <aside className={`context-pane ${tab === 'files' ? 'editing-files' : ''}`} aria-label="Code workspace"><div className="context-tabs"><button className={tab === 'changes' ? 'active' : ''} onClick={() => setTab('changes')}><GitCompareArrows size={14}/>Changes<span className="tab-count">{ready ? 1 : 0}</span></button><button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}><Folder size={14}/>Files</button><button className="icon-button context-more" aria-label="Show project files" onClick={() => setTab('files')}><MoreHorizontal size={17}/></button></div>
          <div className="context-project"><span><GitBranch size={13}/>main</span><span className="demo-caption">{tab === 'changes' ? 'Sample proposal' : project.kind === 'browser' ? 'Browser workspace · saves locally' : 'Connected to disk'}</span></div>
          {tab === 'changes' ? ready ? <ChangeReview before={sampleOriginal} after={proposal} accepted={session.phase === 'accepted'} onAccept={() => update(activeId, { phase: 'accepted' })} onExplain={() => { setMode('Ask'); setInput('Explain this change in simple terms. What will be different when I open the app?'); if (window.innerWidth <= 760) setContextOpen(false); window.requestAnimationFrame(() => composer.current?.focus()); }}/>
            : <div className="empty-context"><GitCompareArrows size={25}/><h2>{running ? 'Your agent is working' : 'A clear view of every change'}</h2><p>{running ? 'The demo proposal will appear here when the run finishes.' : 'Start a Build conversation to preview the review workflow.'}</p>{running && <button className="secondary-button" onClick={() => update(activeId, { phase: 'paused' })}>Pause run</button>}</div> : <ProjectFiles/>}
        </aside>}
      </div>
      {terminalOpen && <Suspense fallback={<div className="terminal-loading">Opening terminal…</div>}><WorkspaceTerminal onClose={() => setTerminalOpen(false)}/></Suspense>}
      <footer className="status-bar"><span><span className={`status-dot ${running ? 'busy' : ''}`}/>{status}</span><span><GitBranch size={12}/>main</span><span className="status-right"><ShieldCheck size={12}/>Review before applying<span className="status-divider"/>Frontend preview</span></footer>
    </div>
    {searchOpen && <div className="dialog-backdrop" onClick={() => setSearchOpen(false)}><section className="search-dialog" role="dialog" aria-modal="true" aria-label="Search conversations" onClick={e => e.stopPropagation()}><div className="dialog-search-input"><Search size={18}/><input autoFocus placeholder="Find a conversation…" aria-label="Search query" value={query} onChange={e => setQuery(e.target.value)}/><button className="icon-button" aria-label="Close search" onClick={() => setSearchOpen(false)}><X size={17}/></button></div><div className="search-results">{sessions.filter(s => s.title.toLowerCase().includes(query.toLowerCase())).map(s => <button key={s.id} onClick={() => { selectSession(s.id); setSearchOpen(false); }}><MessageSquare size={15}/>{s.title}<ArrowDown size={13}/></button>)}{!sessions.some(s => s.title.toLowerCase().includes(query.toLowerCase())) && <p>No conversations match “{query}”.</p>}</div></section></div>}
    {settingsOpen && <div className="dialog-backdrop" onClick={() => setSettingsOpen(false)}><section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title" onClick={e => e.stopPropagation()}><header><h2 id="settings-title">Workspace preferences</h2><button className="icon-button" aria-label="Close preferences" onClick={() => setSettingsOpen(false)}><X size={18}/></button></header><p>This frontend preview uses a demo agent. Conversations and approvals stay in memory for this session.</p><label>Default agent mode<select value={mode} onChange={e => setMode(e.target.value)}><option>Build</option><option>Ask</option></select></label><label className="toggle-setting"><span>Show code alongside conversation</span><input type="checkbox" checked={contextOpen} onChange={e => setContextOpen(e.target.checked)}/></label><div className="runtime-note"><Command size={18}/><span>Agent runtime<small>Connect a model provider or CLI agent next.</small></span></div><button className="primary-button" onClick={() => setSettingsOpen(false)}>Done</button></section></div>}
  </div>;
}
