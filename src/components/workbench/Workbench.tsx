import { useEffect, useMemo, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { CircleAlert, Files, GitBranch, Globe, MessagesSquare, Moon, Play, Puzzle, Search, Settings2, Sun, TriangleAlert } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { LAYOUT_DEFAULTS, PROVIDERS, resolvedTheme, useSettings, type Settings } from '../../stores/useSettings';
import { useProfiles } from '../../stores/useProfiles';
import { useUi } from '../../stores/useUi';
import { useGit } from '../../stores/useGit';
import { AgentPanel } from './AgentPanel';
import { AutomataView } from '../automata/AutomataView';
import { BottomPanel } from './BottomPanel';
import { CommandPalette, type Command } from './CommandPalette';
import { closeTab, EditorArea } from './EditorArea';
import { SettingsDialog } from './SettingsDialog';
import { runTask, Sidebar } from './Sidebar';
import { TitleBar, type Menu } from './TitleBar';
import { ProfileMenu } from './Profiles';
import { PluginIcon, usePlugins } from './plugins';
import { detectTasks, defaultTask } from './tasks';
import { languageOf, Popover, Splitter } from './primitives';

type View = Settings['sidebarView'];

async function editorAction(id: string, fallback?: string) {
  const { runEditorAction } = await import('./CodeEditor');
  if (!runEditorAction(id) && fallback) document.execCommand(fallback);
}

export function Workbench() {
  const s = useSettings();
  const project = useProjectStore();
  const agent = useAgentWorkspace();
  const ui = useUi();
  const profiles = useProfiles();
  const plugins = usePlugins();
  const [panelMax, setPanelMax] = useState(false);
  const [cache, setCache] = useState<{ hits: number; misses: number } | null>(null);
  const git = useGit();
  const [profileOpen, setProfileOpen] = useState(false);
  const [viewport, setViewport] = useState(() => ({ w: window.innerWidth, h: window.innerHeight }));
  const native = project.kind === 'native';
  const mod = /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl';
  const profile = profiles.profiles.find(p => p.id === profiles.active) ?? profiles.profiles[0];

  useEffect(() => { void useProjectStore.getState().initialize(); }, []);
  useEffect(() => { if (native) void useAgentWorkspace.getState().connect(); }, [project.root, native]);
  useEffect(() => {
    if (!native || !agent.connected) return;
    void useGit.getState().refresh();
    const id = setInterval(() => void useGit.getState().refresh(), 4000);
    return () => clearInterval(id);
  }, [native, agent.connected, project.root]);
  useEffect(() => {
    if (!native || !agent.connected) return;
    const load = () => void import('../../lib/sharkBackend').then(m => m.sharkBackend.cacheStats()).then(setCache).catch(() => {});
    load(); const id = setInterval(load, 15000); return () => clearInterval(id);
  }, [native, agent.connected]);
  useEffect(() => { const r = () => setViewport({ w: window.innerWidth, h: window.innerHeight }); window.addEventListener('resize', r); return () => window.removeEventListener('resize', r); }, []);

  useEffect(() => {
    const st = useSettings.getState();
    if (s.view === 'automata') st.set({ sidebarOpen: true, sidebarView: 'components' });
    else if (st.sidebarView === 'components') st.set({ sidebarView: 'files' });
  }, [s.view]);
  // Opening a file or a review brings the editor pane in beside the conversation.
  useEffect(() => { if (project.activePath) useSettings.getState().set({ editorOpen: true }); }, [project.activePath]);
  useEffect(() => { if (ui.editorView === 'review' && agent.proposal) useSettings.getState().set({ editorOpen: true }); }, [ui.editorView, agent.proposal]);
  useEffect(() => { if (!project.tabs.length && !agent.proposal && useSettings.getState().view === 'shark') useSettings.getState().set({ editorOpen: false }); }, [project.tabs.length, agent.proposal]);

  useEffect(() => {
    const root = document.documentElement;
    const apply = () => { const t = resolvedTheme(s.theme); root.dataset.theme = t; useUi.getState().set({ resolvedTheme: t }); };
    apply();
    root.style.setProperty('--ui', `${s.fontSize}px`);
    root.dataset.density = s.density;
    root.dataset.readingFont = s.readingFont;
    root.dataset.contrast = s.highContrast ? 'high' : 'standard';
    root.dataset.motion = s.reduceMotion ? 'reduced' : 'system';
    const media = window.matchMedia('(prefers-color-scheme: light)');
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [s.theme, s.fontSize, s.density, s.readingFont, s.highContrast, s.reduceMotion]);

  const showView = (view: View) => {
    const st = useSettings.getState();
    if (st.sidebarOpen && st.sidebarView === view) st.set({ sidebarOpen: false });
    else st.set({ sidebarOpen: true, sidebarView: view });
  };
  const focusAgent = () => useUi.getState().set({ composerFocus: Date.now() });
  const newChat = () => { useAgentWorkspace.getState().fresh(); focusAgent(); };
  const runDefault = async (group: 'build' | 'test') => {
    const st = useProjectStore.getState();
    const task = defaultTask(await detectTasks(st.entries, st.readText), group);
    if (task) void runTask(task); else showView('run');
  };
  const togglePanel = (tab?: 'terminal' | 'problems') => {
    const st = useSettings.getState(), u = useUi.getState();
    if (tab && (!st.terminalOpen || u.panelTab !== tab)) { st.set({ terminalOpen: true }); u.set({ panelTab: tab }); }
    else st.toggle('terminalOpen');
  };
  const toggleTheme = () => s.set({ theme: useUi.getState().resolvedTheme === 'dark' ? 'light' : 'dark' });
  const saveAll = () => { const st = useProjectStore.getState(); st.tabs.filter(t => t.content !== t.saved).forEach(t => void st.save(t.path)); };

  const menus: Menu[] = [
    { label: 'File', items: [
      { label: 'New Chat', keys: `${mod} N`, run: newChat },
      { label: 'New File…', run: () => { s.set({ sidebarOpen: true, sidebarView: 'files' }); setTimeout(() => document.querySelector<HTMLButtonElement>('[aria-label="New file"]')?.click()); } },
      { label: 'Open Folder…', run: () => { s.set({ sidebarOpen: true, sidebarView: 'files' }); if (!isTauri()) void project.openFolder(); else setTimeout(() => document.querySelector<HTMLButtonElement>('[aria-label="Open folder"]')?.click()); } },
      { label: 'Go to File…', keys: `${mod} P`, run: () => ui.open('files') }, 'separator',
      { label: 'Save', keys: `${mod} S`, run: () => { if (project.activePath) void project.save(project.activePath); }, disabled: !project.activePath },
      { label: 'Save All', run: saveAll, disabled: !project.tabs.some(t => t.content !== t.saved) },
      { label: 'Close Editor', keys: `${mod} W`, run: () => { if (project.activePath) closeTab(project.activePath); }, disabled: !project.activePath }, 'separator',
      { label: 'Profiles…', run: () => setProfileOpen(true) },
      { label: 'Settings', keys: `${mod} ,`, run: () => ui.open('settings') },
      ...(isTauri() ? ['separator' as const, { label: 'Exit', run: () => void import('@tauri-apps/api/window').then(m => m.getCurrentWindow().close()) }] : []),
    ] },
    { label: 'Edit', items: [
      { label: 'Undo', keys: `${mod} Z`, run: () => void editorAction('undo', 'undo') },
      { label: 'Redo', keys: `${mod} Y`, run: () => void editorAction('redo', 'redo') }, 'separator',
      { label: 'Cut', keys: `${mod} X`, run: () => void editorAction('editor.action.clipboardCutAction', 'cut') },
      { label: 'Copy', keys: `${mod} C`, run: () => void editorAction('editor.action.clipboardCopyAction', 'copy') },
      { label: 'Paste', keys: `${mod} V`, run: () => void editorAction('editor.action.clipboardPasteAction', 'paste') }, 'separator',
      { label: 'Find', keys: `${mod} F`, run: () => void editorAction('actions.find') },
      { label: 'Replace', keys: `${mod} H`, run: () => void editorAction('editor.action.startFindReplaceAction') },
      { label: 'Find in Files', keys: `${mod} ⇧ F`, run: () => s.set({ sidebarOpen: true, sidebarView: 'search' }) }, 'separator',
      { label: 'Toggle Line Comment', keys: `${mod} /`, run: () => void editorAction('editor.action.commentLine') },
      { label: 'Format Document', keys: '⇧ Alt F', run: () => void editorAction('editor.action.formatDocument') },
    ] },
    { label: 'Selection', items: [
      { label: 'Select All', keys: `${mod} A`, run: () => void editorAction('editor.action.selectAll', 'selectAll') },
      { label: 'Expand Selection', keys: '⇧ Alt →', run: () => void editorAction('editor.action.smartSelect.expand') },
      { label: 'Shrink Selection', keys: '⇧ Alt ←', run: () => void editorAction('editor.action.smartSelect.shrink') }, 'separator',
      { label: 'Copy Line Up', keys: '⇧ Alt ↑', run: () => void editorAction('editor.action.copyLinesUpAction') },
      { label: 'Copy Line Down', keys: '⇧ Alt ↓', run: () => void editorAction('editor.action.copyLinesDownAction') },
      { label: 'Move Line Up', keys: 'Alt ↑', run: () => void editorAction('editor.action.moveLinesUpAction') },
      { label: 'Move Line Down', keys: 'Alt ↓', run: () => void editorAction('editor.action.moveLinesDownAction') }, 'separator',
      { label: 'Add Cursor Above', keys: `${mod} Alt ↑`, run: () => void editorAction('editor.action.insertCursorAbove') },
      { label: 'Add Cursor Below', keys: `${mod} Alt ↓`, run: () => void editorAction('editor.action.insertCursorBelow') },
      { label: 'Select All Occurrences', keys: `${mod} ⇧ L`, run: () => void editorAction('editor.action.selectHighlights') },
    ] },
    { label: 'View', items: [
      { label: 'Command Palette…', keys: `${mod} K`, run: () => ui.open('palette') }, 'separator',
      { label: 'Agent Sessions', run: () => showView('sessions') },
      { label: 'Explorer', keys: `${mod} ⇧ E`, run: () => showView('files') },
      { label: 'Search', keys: `${mod} ⇧ F`, run: () => showView('search') },
      { label: 'Source Control', keys: `${mod} ⇧ G`, run: () => showView('scm') },
      { label: 'Run & Build', run: () => showView('run') },
      { label: 'Browser', run: () => showView('browser') },
      { label: 'Plugins', run: () => showView('plugins') }, 'separator',
      { label: 'Problems', run: () => togglePanel('problems') },
      { label: 'Terminal', keys: `${mod} J`, run: () => togglePanel('terminal') }, 'separator',
      { label: s.sidebarOpen ? 'Hide Sidebar' : 'Show Sidebar', keys: `${mod} B`, run: () => s.toggle('sidebarOpen') },
      { label: s.editorOpen ? 'Hide Editor Pane' : 'Show Editor Pane', keys: `${mod} \\`, run: () => s.toggle('editorOpen') },
      { label: 'Go to Symbol in File…', keys: `${mod} ⇧ O`, run: () => void editorAction('editor.action.quickOutline') },
      { label: 'Go to Line…', keys: `${mod} G`, run: () => void editorAction('editor.action.gotoLine') }, 'separator',
      { label: 'Toggle Light / Dark', run: toggleTheme },
      { label: 'Reset Layout', run: () => s.set({ ...LAYOUT_DEFAULTS, sidebarOpen: true }) },
      { label: 'Automata View (visual workflows)', run: () => s.set({ view: 'automata', editorOpen: true }) },
      { label: s.view === 'shark' ? 'Code View (editor first)' : 'Shark View (agent first)', keys: `${mod} ⇧ M`, run: () => s.set({ view: s.view === 'shark' ? 'code' : 'shark', editorOpen: true }) },
    ] },
    { label: 'Terminal', items: [
      { label: 'Toggle Terminal', keys: `${mod} J`, run: () => togglePanel('terminal') },
      { label: 'Clear Terminal', run: () => void import('./Terminal').then(m => m.clearTerminal()) }, 'separator',
      { label: 'Run Build Task', keys: `${mod} ⇧ B`, run: () => void runDefault('build') },
      { label: 'Run Tests', run: () => void runDefault('test') },
      { label: 'Run Task…', run: () => showView('run') },
    ] },
    { label: 'Help', items: [
      { label: 'Keyboard Shortcuts', run: () => ui.open('settings', 'keys') },
      { label: 'Shark Engine & API Keys', run: () => ui.open('settings', 'agents') },
      { label: 'Create a Plugin with AI', run: () => showView('plugins') },
      { label: 'Restart Shark Backend', run: () => void import('../../lib/sharkBackend').then(m => m.restartBackend()).then(() => useAgentWorkspace.getState().connect()) },
    ] },
  ];

  const commands: Command[] = useMemo(() => menus.flatMap(m => m.items.filter((i): i is Exclude<typeof i, 'separator'> => i !== 'separator' && !i.disabled)
    .map(i => ({ id: `${m.label}:${i.label}`, label: `${m.label}: ${i.label.replace('…', '')}`, keys: i.keys, run: i.run }))),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [s.sidebarOpen, s.editorOpen, project.activePath, project.tabs, mod]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const st = useSettings.getState(), u = useUi.getState();
      const handled = () => { e.preventDefault(); e.stopPropagation(); };
      if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && !(e.target as HTMLElement).closest('.monaco-editor, textarea, input')) { handled(); void useProjectStore.getState().navigate(e.key === 'ArrowLeft' ? -1 : 1); return; }
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === 'tab') {
        handled();
        const p = useProjectStore.getState(); if (p.tabs.length < 2) return;
        const i = p.tabs.findIndex(t => t.path === p.activePath);
        void p.openFile(p.tabs[(i + (e.shiftKey ? -1 : 1) + p.tabs.length) % p.tabs.length].path); u.set({ editorView: 'file' });
      }
      else if (k === 'k' && !e.shiftKey) { handled(); u.open(u.dialog === 'palette' ? null : 'palette'); }
      else if (k === 'p' && !e.shiftKey) { handled(); u.open(u.dialog === 'files' ? null : 'files'); }
      else if (k === ',') { handled(); u.open('settings'); }
      else if (k === 'b' && e.shiftKey) { handled(); void runDefault('build'); }
      else if (k === 'b') { handled(); st.toggle('sidebarOpen'); }
      else if (k === '\\') { handled(); st.toggle('editorOpen'); }
      else if (k === 'm' && e.shiftKey) { handled(); st.set({ view: st.view === 'shark' ? 'code' : 'shark', editorOpen: true }); }
      else if (k === 'j' || e.key === '`') { handled(); st.toggle('terminalOpen'); }
      else if (k === 'l') { handled(); u.set({ composerFocus: Date.now() }); }
      else if (k === 'n' && !e.shiftKey) { handled(); newChat(); }
      else if (k === 'g' && e.shiftKey) { handled(); st.set({ sidebarOpen: true, sidebarView: 'scm' }); }
      else if (k === 'e' && e.shiftKey) { handled(); st.set({ sidebarOpen: true, sidebarView: 'files' }); }
      else if (k === 'f' && e.shiftKey) { handled(); st.set({ sidebarOpen: true, sidebarView: 'search' }); }
      else if (k === 'v' && e.shiftKey && /\.(md|mdx|markdown)$/i.test(useProjectStore.getState().activePath)) { handled(); u.set({ mdMode: u.mdMode === 'preview' ? 'edit' : 'preview', editorView: 'file' }); }
      else if (k === 'w' && !e.shiftKey) { const path = useProjectStore.getState().activePath; if (path && u.editorView === 'file') { handled(); closeTab(path); } }
      else if (k === 's' && !e.shiftKey) { handled(); const path = useProjectStore.getState().activePath; if (path) void useProjectStore.getState().save(path); }
    };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rail = 48, agentMin = 360;
  const sideMax = viewport.w - rail - agentMin - (s.editorOpen ? Math.min(s.editorWidth, viewport.w * 0.6) : 0);
  const editorMax = viewport.w - rail - agentMin - (s.sidebarOpen ? Math.min(s.sidebarWidth, viewport.w * 0.34) : 0);
  const active = project.tabs.find(t => t.path === project.activePath);
  const errors = ui.problems.filter(p => p.severity === 'error').length, warnings = ui.problems.length - errors;
  const status = !native ? { tone: '', label: 'Browser preview' } : agent.connected ? { tone: 'ok', label: 'Backend connected' } : agent.error ? { tone: 'err', label: 'Backend offline' } : { tone: 'warn', label: 'Connecting…' };
  const running = agent.tasks.some(t => t.status === 'running');

  const railItem = (view: View, label: string, Icon: typeof Files, badge?: number) =>
    <button key={view} className={`rail-btn ${s.sidebarOpen && s.sidebarView === view ? 'active' : ''}`} aria-label={label} title={label} aria-pressed={s.sidebarOpen && s.sidebarView === view} onClick={() => showView(view)}>
      <Icon size={20} strokeWidth={1.6} />{badge ? <span className="rail-badge">{badge}</span> : null}
    </button>;

  const bottomPanel = s.terminalOpen && <>
          {!panelMax && <Splitter axis="y" invert label="Resize panel" value={s.terminalHeight} min={100} max={Math.max(140, viewport.h - 260)} onChange={v => s.set({ terminalHeight: v })} onReset={() => s.set({ terminalHeight: LAYOUT_DEFAULTS.terminalHeight })} />}
          <div className="panel-slot" style={panelMax ? { flex: 1 } : { height: s.terminalHeight }}>
            <BottomPanel maximized={panelMax} onMaximize={setPanelMax} />
          </div>
        </>;

  return <div className="wb" style={{ '--sidebar-w': `${s.sidebarWidth}px`, '--editor-w': `${s.editorWidth}px`, '--shark-w': `${s.agentWidth}px` } as React.CSSProperties}>
    <TitleBar menus={menus} />
    <div className="wb-body" inert={ui.dialog !== null || undefined}>
      <nav className="rail" aria-label="Views">
        {railItem('sessions', 'Shark sessions', MessagesSquare, running ? 1 : undefined)}
        {railItem('files', 'Explorer', Files)}
        {railItem('search', 'Search', Search)}
        {railItem('scm', 'Source control', GitBranch)}
        {railItem('run', 'Run & Build', Play)}
        {railItem('browser', 'Browser', Globe)}
        {plugins.enabled.length > 0 && <span className="rail-sep" />}
        {plugins.enabled.map(p => <button key={p.id} className={`rail-btn ${s.sidebarOpen && s.sidebarView === `plugin:${p.id}` ? 'active' : ''}`} aria-label={p.name} title={p.name} onClick={() => showView(`plugin:${p.id}`)}><PluginIcon name={p.icon} /></button>)}
        {railItem('plugins', 'Plugins', Puzzle)}
        <span className="grow" />
        <button className="rail-btn" aria-label={`Switch to ${ui.resolvedTheme === 'dark' ? 'light' : 'dark'} theme`} title="Theme" onClick={toggleTheme}>{ui.resolvedTheme === 'dark' ? <Sun size={19} strokeWidth={1.6} /> : <Moon size={19} strokeWidth={1.6} />}</button>
        <div style={{ position: 'relative' }}>
          <button className="rail-btn" data-popover-anchor aria-label={`Profile: ${profile.name}`} title={`Profile · ${profile.name}`} aria-expanded={profileOpen} onClick={() => setProfileOpen(v => !v)}>
            <span className="avatar" style={{ background: profile.color }}>{profile.name.slice(0, 1).toUpperCase()}</span>
          </button>
          <Popover open={profileOpen} onClose={() => setProfileOpen(false)} className="profile-pop" style={{ left: 'calc(100% + 6px)', bottom: 0 }}><ProfileMenu onDone={() => setProfileOpen(false)} /></Popover>
        </div>
        <button className="rail-btn" aria-label="Settings" title={`Settings · ${mod} ,`} onClick={() => ui.open('settings')}><Settings2 size={19} strokeWidth={1.6} /></button>
      </nav>
      {s.sidebarOpen && <>
        <Sidebar />
        <Splitter axis="x" label="Resize sidebar" value={s.sidebarWidth} min={200} max={Math.min(560, sideMax)} onChange={v => s.set({ sidebarWidth: v })} onReset={() => s.set({ sidebarWidth: LAYOUT_DEFAULTS.sidebarWidth })} />
      </>}
      <div className="wb-main">
        {s.view === 'automata'
          ? <div className="wb-row view-code">
              <div className="code-col">
                <div className="pane pane-editor grow-pane"><AutomataView /></div>
                {bottomPanel}
              </div>
              {s.editorOpen && <>
                <Splitter axis="x" invert label="Resize Shark panel" value={s.agentWidth} min={340} max={Math.max(340, viewport.w - rail - 420 - (s.sidebarOpen ? s.sidebarWidth : 0))} onChange={v => s.set({ agentWidth: v })} onReset={() => s.set({ agentWidth: 420 })} />
                <div className="pane pane-shark"><AgentPanel /></div>
              </>}
            </div>
        : s.view === 'code'
          ? <div className="wb-row view-code">
              <div className="code-col">
                {!panelMax && <div className="pane pane-editor grow-pane"><EditorArea /></div>}
                {bottomPanel}
              </div>
              {s.editorOpen && <>
                <Splitter axis="x" invert label="Resize Shark panel" value={s.agentWidth} min={340} max={Math.max(340, viewport.w - rail - 420 - (s.sidebarOpen ? s.sidebarWidth : 0))} onChange={v => s.set({ agentWidth: v })} onReset={() => s.set({ agentWidth: 420 })} />
                <div className="pane pane-shark"><AgentPanel /></div>
              </>}
            </div>
          : <>
              {!panelMax && <div className="wb-row">
                <AgentPanel />
                {s.editorOpen && <>
                  <Splitter axis="x" invert label="Resize editor" value={s.editorWidth} min={320} max={Math.max(320, editorMax)} onChange={v => s.set({ editorWidth: v })} onReset={() => s.set({ editorWidth: LAYOUT_DEFAULTS.editorWidth })} />
                  <div className="pane pane-editor"><EditorArea /></div>
                </>}
              </div>}
              {bottomPanel}
            </>}
      </div>
    </div>

    <footer className="statusbar">
      <span title={project.root}><span className={`dot ${status.tone}`} />{status.label}</span>
      {git.status?.repo && <button onClick={() => showView('scm')} title={`Branch ${git.status.branch} · ${git.status.files.length} changes`}><GitBranch size={12} />{git.status.branch}{git.status.files.length ? ` · ${git.status.files.length}` : ''}</button>}
      <button onClick={() => togglePanel('problems')} title="Problems"><CircleAlert size={12} />{errors}<TriangleAlert size={12} />{warnings}</button>
      {running && <button onClick={() => showView('sessions')}><span className="dot live" />{agent.tasks.filter(t => t.status === 'running').length > 1 ? `${agent.tasks.filter(t => t.status === 'running').length} agents working` : 'Shark is working'}</button>}
      {cache && cache.hits + cache.misses > 0 && <span title={`Tool cache: ${cache.hits} hits, ${cache.misses} misses (content-addressed reads, outlines and search)`}>Cache {Math.round(cache.hits / (cache.hits + cache.misses) * 100)}%</span>}
      <span className="grow" />
      {active && <span>{languageOf(active.path)[1]}</span>}
      {active && <span>UTF-8</span>}
      <button onClick={() => setProfileOpen(true)} title="Profile"><span className="avatar sm" style={{ background: profile.color }}>{profile.name.slice(0, 1).toUpperCase()}</span>{profile.name}</button>
      <button onClick={() => ui.open('settings', 'agents')} title="Shark's engine">Shark · {PROVIDERS[s.provider].label}</button>
    </footer>

    {(ui.dialog === 'palette' || ui.dialog === 'files') && <CommandPalette key={ui.dialog} commands={commands} />}
    {ui.dialog === 'settings' && <SettingsDialog />}
  </div>;
}
