import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, ChevronsDownUp, FilePlus2, FolderOpen, Hammer, Play, Plus, RefreshCw, Search, Sparkles, TestTube2, Trash2, Wrench, X } from 'lucide-react';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { PluginManager, PluginView, usePlugins } from './plugins';
import { SourceControl } from './SourceControl';
import { BrowserView } from './Browser';
import { GIT_LETTER, useGit } from '../../stores/useGit';
import { sharkGit } from '../../lib/sharkBackend';
import { useProjectStore, type ProjectEntry, type SearchHit } from '../../stores/useProjectStore';
import { MODES, PROVIDERS, useSettings, type ProviderId } from '../../stores/useSettings';
import { useUi } from '../../stores/useUi';
import { FileIcon, relativeTime } from './primitives';
import { detectTasks, type TaskGroup, type WorkspaceTask } from './tasks';
import { askAgent } from './BottomPanel';
import { ComponentList } from '../automata/ComponentList';

const TITLES: Record<string, string> = { components: 'Components', sessions: 'Shark sessions', files: 'Explorer', search: 'Search', scm: 'Source control', run: 'Run & Build', browser: 'Browser', plugins: 'Plugins' };

export function Sidebar() {
  const view = useSettings(s => s.sidebarView);
  const automata = useSettings(s => s.view) === 'automata';
  const { all } = usePlugins();
  const plugin = view.startsWith('plugin:') ? all.find(p => `plugin:${p.id}` === view) : undefined;
  const title = plugin?.name ?? TITLES[view] ?? 'Plugin';
  return <aside className="pane pane-side" aria-label={title}>
    <div className="pane-head"><h2 className="label">{title}</h2>
      {automata && (view === 'files' || view === 'components') && <div className="seg" role="group" aria-label="Sidebar content">
        <button aria-pressed={view === 'components'} onClick={() => useSettings.getState().set({ sidebarView: 'components' })}>Components</button>
        <button aria-pressed={view === 'files'} onClick={() => useSettings.getState().set({ sidebarView: 'files' })}>Files</button></div>}
      {view === 'sessions' && <><span className="grow" /><button className="icon-btn sm" aria-label="New chat" title="New chat · Ctrl N" onClick={() => { useAgentWorkspace.getState().fresh(); useUi.getState().set({ composerFocus: Date.now() }); }}><Plus size={14} /></button></>}
    </div>
    {view === 'components' ? <ComponentList /> : view === 'sessions' ? <Sessions /> : view === 'files' ? <Explorer /> : view === 'search' ? <SearchPane /> : view === 'scm' ? <SourceControl /> : view === 'run' ? <RunView />
      : view === 'browser' ? <BrowserView /> : view === 'plugins' ? <PluginManager /> : plugin ? <PluginView plugin={plugin} /> : <p className="search-meta">This plugin is no longer installed.</p>}
  </aside>;
}

const STATUS: Record<string, string> = { created: 'Not started', running: 'Working', review: 'Ready to review', applied: 'Applied', completed: 'Done', cancelled: 'Stopped', interrupted: 'Interrupted', failed: 'Failed' };
function sessionTitle(goal: string) {
  return goal.replace(/^\[automata\][\s\S]*?\[\/automata\]\n\n/, '').replace(/^\[context\][\s\S]*?\[\/context\]\n\n/, '').replace(/\n\nOpen file: .+$/, '').split('\n')[0];
}
function Sessions() {
  const agent = useAgentWorkspace();
  const native = useProjectStore(s => s.kind) === 'native';
  const [query, setQuery] = useState('');
  if (!agent.tasks.length) return <p className="search-meta">{native ? 'Your conversations appear here. Each keeps its activity and review.' : 'Sessions are stored by the desktop app.'}</p>;
  const q = query.trim().toLowerCase();
  const matches = agent.tasks.filter(t => !q || sessionTitle(t.goal).toLowerCase().includes(q));
  return <div className="explorer">
    <div className="filter"><Search size={13} /><input className="field" placeholder="Search sessions…" value={query} onChange={e => setQuery(e.target.value)} aria-label="Search sessions" /></div>
    {matches.length === 0 ? <p className="search-meta">No sessions match “{query}”.</p> : <div className="results">
      {matches.map(t => { const title = sessionTitle(t.goal);
        return <div key={t.id} className="session-item">
          <button className={`session-row ${t.id === agent.activeId ? 'active' : ''}`} onClick={() => void agent.select(t.id)}>
            <span className={`dot ${t.status === 'running' ? 'live' : t.status === 'review' ? 'warn' : t.status === 'failed' ? 'err' : t.status === 'applied' || t.status === 'completed' ? 'ok' : ''}`} />
            <span className="text"><span className="ellipsis">{title}</span><small>{STATUS[t.status]}{t.engine ? ` · ${PROVIDERS[t.engine as ProviderId]?.label ?? t.engine}` : ''}{t.mode && t.mode !== 'builder' ? ` · ${MODES.find(m => m.id === t.mode)?.label ?? t.mode}` : ''}{t.group ? ' · parallel' : ''} · {relativeTime(t.created_at)}</small></span>
          </button>
          <button className="icon-btn sm del" aria-label={`Delete session: ${title || 'Untitled'}`} title="Delete session" disabled={t.status === 'running'}
            onClick={e => { e.stopPropagation(); if (window.confirm(`Delete this session? “${title.slice(0, 80)}”\nThis removes its history. It can't be undone.`)) void agent.remove(t.id); }}>
            <Trash2 size={13} />
          </button>
        </div>; })}
    </div>}
  </div>;
}

export async function runTask(task: Pick<WorkspaceTask, 'command'>) {
  useSettings.getState().set({ terminalOpen: true });
  useUi.getState().set({ panelTab: 'terminal' });
  const { runInTerminal } = await import('./Terminal');
  runInTerminal(task.command);
}

const GROUPS: { id: TaskGroup; label: string; icon: typeof Play }[] = [
  { id: 'build', label: 'Build', icon: Hammer }, { id: 'test', label: 'Test & check', icon: TestTube2 },
  { id: 'run', label: 'Run', icon: Play }, { id: 'other', label: 'Other', icon: Wrench },
];

function DevTools() {
  const native = useProjectStore(s => s.kind) === 'native';
  const root = useProjectStore(s => s.root);
  const [tools, setTools] = useState<Awaited<ReturnType<typeof sharkGit.tools>>['tools']>([]);
  const [open, setOpen] = useState(true);
  useEffect(() => { if (native) void sharkGit.tools().then(r => setTools(r.tools)).catch(() => setTools([])); }, [native, root]);
  if (!tools.length) return null;
  const ready = tools.filter(t => t.available), missing = tools.filter(t => !t.available);
  return <section>
    <button className="run-group run-toggle" aria-expanded={open} onClick={() => setOpen(o => !o)}><ChevronRight size={11} style={{ transform: open ? 'rotate(90deg)' : undefined }} />Developer tools · {ready.length}/{tools.length}</button>
    {open && <>
      {ready.flatMap(t => t.tasks.map(k => <div key={t.id + k.label} className="task-row">
        <button className="task-run" onClick={() => void runTask(k)} title={`${t.purpose}\n${k.command}`}><Play size={11} className="play" /><span className="name">{k.label}</span><span className="cmd">{t.label}</span></button>
      </div>))}
      {missing.map(t => <div key={t.id} className="task-row tool-missing" title={t.purpose}>
        <span className="task-run"><span className="name">{t.label}</span><span className="cmd">{t.purpose}</span></span>
        <button className="icon-btn sm" title={`Install: ${t.install}`} aria-label={`Install ${t.label}`} onClick={() => { if (window.confirm(`Run in the terminal?\n\n${t.install}`)) void runTask({ command: t.install }); }}><Plus size={12} /></button>
      </div>)}
    </>}
  </section>;
}

function Dependencies() {
  const native = useProjectStore(s => s.kind) === 'native';
  const root = useProjectStore(s => s.root);
  const [groups, setGroups] = useState<Awaited<ReturnType<typeof sharkGit.deps>>['groups']>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (native) void sharkGit.deps().then(r => setGroups(r.groups)).catch(() => setGroups([])); }, [native, root]);
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  if (!total) return null;
  return <section>
    <button className="run-group run-toggle" aria-expanded={open} onClick={() => setOpen(o => !o)}><ChevronRight size={11} style={{ transform: open ? 'rotate(90deg)' : undefined }} />Dependencies · {total}</button>
    {open && groups.map(g => <div key={g.manifest + g.section}>
      <div className="dep-head">{g.manifest} · {g.section}<span className="grow" /><button className="icon-btn sm" title="Ask Shark to check for outdated or vulnerable packages" aria-label="Audit dependencies" onClick={() => askAgent(`Audit the ${g.section} in ${g.manifest}: find outdated, unused or vulnerable packages and propose safe upgrades.`)}><Sparkles size={12} /></button></div>
      {g.items.map(d => <div key={d.name} className="dep-row"><span className="ellipsis">{d.name}</span><code>{d.version}</code></div>)}
    </div>)}
  </section>;
}

function RunView() {
  const entries = useProjectStore(s => s.entries);
  const readText = useProjectStore(s => s.readText);
  const kind = useProjectStore(s => s.kind);
  const [tasks, setTasks] = useState<WorkspaceTask[] | null>(null);
  useEffect(() => { let live = true; void detectTasks(entries, readText).then(t => { if (live) setTasks(t); }); return () => { live = false; }; }, [entries, readText]);
  if (!tasks) return <p className="search-meta">Detecting tasks…</p>;
  return <div className="results run-view">
    {kind !== 'native' && <p className="search-meta">Tasks run in the desktop app's terminal.</p>}
    {!tasks.length && <p className="search-meta">No package.json scripts, Cargo, Go, Python or Makefile tasks found.</p>}
    <Dependencies />
    <DevTools />
    {GROUPS.map(g => { const list = tasks.filter(t => t.group === g.id); if (!list.length) return null; const Icon = g.icon; return <section key={g.id}>
      <div className="run-group"><Icon size={12} />{g.label}</div>
      {list.map(t => <div key={t.id} className="task-row">
        <button className="task-run" onClick={() => void runTask(t)} title={`Run: ${t.command}`}>
          <Play size={11} className="play" /><span className="name">{t.label}</span><span className="cmd">{t.command}</span>
        </button>
        <button className="icon-btn sm" title="Ask the agent to run and fix this" aria-label={`Ask agent about ${t.label}`} onClick={() => askAgent(`Run \`${t.command}\` and fix anything that fails.`)}><Sparkles size={12} /></button>
      </div>)}
    </section>; })}
  </div>;
}

function parentOf(path: string) { const i = path.lastIndexOf('/'); return i < 0 ? '' : path.slice(0, i); }
function ancestors(path: string) { const out: string[] = []; let p = parentOf(path); while (p) { out.push(p); p = parentOf(p); } return out; }

export function openPath(path: string, line?: number) {
  void useProjectStore.getState().openFile(path);
  useUi.getState().set({ editorView: 'file', ...(line ? { reveal: { path, line } } : {}) });
}

function Explorer() {
  const project = useProjectStore();
  const git = useGit();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState<null | 'file'>(null);
  const [draft, setDraft] = useState('');
  const treeRef = useRef<HTMLDivElement>(null);

  const children = useMemo(() => {
    const map = new Map<string, ProjectEntry[]>();
    for (const e of project.entries) { const p = parentOf(e.path); if (!map.has(p)) map.set(p, []); map.get(p)!.push(e); }
    for (const list of map.values()) list.sort((a, b) => Number(b.directory) - Number(a.directory) || a.path.localeCompare(b.path, undefined, { sensitivity: 'base' }));
    return map;
  }, [project.entries]);
  const fileCount = useMemo(() => project.entries.filter(e => !e.directory).length, [project.entries]);

  // Reveal the active file in the tree.
  useEffect(() => {
    if (!project.activePath) return;
    setExpanded(cur => { const need = ancestors(project.activePath).filter(a => !cur.has(a)); return need.length ? new Set([...cur, ...need]) : cur; });
  }, [project.activePath]);

  const toggle = (path: string) => setExpanded(cur => { const next = new Set(cur); if (next.has(path)) next.delete(path); else next.add(path); return next; });

  const rows: { entry: ProjectEntry; depth: number }[] = [];
  const walk = (parent: string, depth: number) => {
    for (const entry of children.get(parent) ?? []) { rows.push({ entry, depth }); if (entry.directory && expanded.has(entry.path)) walk(entry.path, depth + 1); }
  };
  const query = filter.trim().toLowerCase();
  const matches = query ? project.entries.filter(e => !e.directory && e.path.toLowerCase().includes(query)).slice(0, 300) : [];
  if (!query) walk('', 0);

  const onKey = (e: React.KeyboardEvent) => {
    const items = Array.from(treeRef.current?.querySelectorAll<HTMLButtonElement>('.tree-row') ?? []);
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    const current = items[index];
    const path = current.dataset.path!, dir = current.dataset.dir === 'true';
    if (e.key === 'ArrowDown') { e.preventDefault(); items[Math.min(index + 1, items.length - 1)].focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[Math.max(index - 1, 0)].focus(); }
    else if (e.key === 'Home') { e.preventDefault(); items[0]?.focus(); }
    else if (e.key === 'End') { e.preventDefault(); items[items.length - 1]?.focus(); }
    else if (e.key === 'ArrowRight' && dir) { e.preventDefault(); if (!expanded.has(path)) toggle(path); else items[index + 1]?.focus(); }
    else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      if (dir && expanded.has(path)) toggle(path);
      else items.find(i => i.dataset.path === parentOf(path))?.focus();
    }
  };

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    const value = draft.trim(); if (!value) return;
    await project.createFile(value);
    if (!useProjectStore.getState().error) { setCreating(null); setDraft(''); useUi.getState().set({ editorView: 'file' }); }
  }

  const openFolder = () => { useSettings.getState().set({ sidebarOpen: true, sidebarView: 'files' }); void project.pickFolder(); };

  return <div className="explorer">
    <div className="project-row">
      <strong className="ellipsis" title={project.root}>{project.name}</strong>
      <button className="icon-btn sm" aria-label="New file" title="New file" onClick={() => { setDraft(project.activePath ? parentOf(project.activePath) + (parentOf(project.activePath) ? '/' : '') : ''); setCreating('file'); }}><FilePlus2 size={14} /></button>
      <button className="icon-btn sm" aria-label="Refresh" title="Refresh" onClick={() => void project.refresh()}><RefreshCw size={13} /></button>
      <button className="icon-btn sm" aria-label="Collapse folders" title="Collapse folders" onClick={() => setExpanded(new Set())}><ChevronsDownUp size={14} /></button>
      <button className="icon-btn sm" aria-label="Open folder" title="Open folder" onClick={openFolder}><FolderOpen size={14} /></button>
    </div>
    {creating && <form className="inline-create" onSubmit={submitCreate}>
      <input className="field" autoFocus value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') setCreating(null); }}
        placeholder="src/new-file.ts" aria-label="New file path" />
      <p>Enter creates the file · Esc cancels</p>
    </form>}
    <div className="filter">
      <Search size={13} />
      <input className="field" placeholder="Filter files" aria-label="Filter files" value={filter} onChange={e => setFilter(e.target.value)} onKeyDown={e => {
        if (e.key === 'Escape') setFilter('');
        if (e.key === 'ArrowDown') { e.preventDefault(); treeRef.current?.querySelector<HTMLButtonElement>('.tree-row')?.focus(); }
        if (e.key === 'Enter' && matches[0]) openPath(matches[0].path);
      }} />
    </div>
    <div className="tree" ref={treeRef} role="tree" aria-label="Project files" onKeyDown={onKey}>
      {query ? matches.map(e => <button key={e.path} className={`tree-row ${project.activePath === e.path ? 'active' : ''}`} data-path={e.path} data-dir="false" role="treeitem" title={e.path} onClick={() => openPath(e.path)} style={{ paddingLeft: 10 }}>
        <FileIcon path={e.path} /><span className="name">{e.path.split('/').pop()}</span><span className="sub">{parentOf(e.path)}</span>
      </button>) : rows.map(({ entry, depth }) => {
        const name = entry.path.split('/').pop();
        const open = expanded.has(entry.path);
        const dirty = !entry.directory && project.tabs.some(t => t.path === entry.path && t.content !== t.saved);
        const gitState = entry.directory ? git.dirtyDirs[entry.path] : git.byPath[entry.path];
        return <button key={entry.path} role="treeitem" data-path={entry.path} data-dir={entry.directory}
          className={`tree-row ${project.activePath === entry.path ? 'active' : ''} ${gitState ? `git-${gitState}` : ''}`} title={gitState ? `${entry.path} · ${gitState}` : entry.path}
          aria-expanded={entry.directory ? open : undefined} aria-level={depth + 1}
          aria-current={!entry.directory && project.activePath === entry.path ? 'true' : undefined}
          onClick={() => entry.directory ? toggle(entry.path) : openPath(entry.path)}>
          <span className="indent" style={{ width: 6 + depth * 14 }} />
          {entry.directory ? <ChevronRight size={13} className="chev" /> : <FileIcon path={entry.path} />}
          <span className="name">{name}</span>
          {dirty && <span className="unsaved" aria-label="Unsaved changes" />}
          {gitState && (entry.directory ? <span className="git-dot" aria-hidden="true" /> : <span className="git-letter">{GIT_LETTER[gitState] ?? 'M'}</span>)}
        </button>;
      })}
      {query && !matches.length && <p className="search-meta" style={{ padding: '8px' }}>No files match “{filter}”.</p>}
    </div>
    <div className="side-foot"><span>{fileCount} files</span><span>{project.kind === 'native' ? 'Local' : project.kind === 'folder' ? 'Folder' : 'Browser preview'}</span></div>
  </div>;
}

function SearchPane() {
  const searchText = useProjectStore(s => s.searchText);
  const kind = useProjectStore(s => s.kind);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!query.trim()) { setHits([]); setError(''); return; }
    let live = true;
    const timer = setTimeout(async () => {
      setBusy(true);
      try { const result = await searchText(query); if (live) { setHits(result); setError(''); } }
      catch (e) { if (live) setError(e instanceof Error ? e.message : String(e)); }
      finally { if (live) setBusy(false); }
    }, 220);
    return () => { live = false; clearTimeout(timer); };
  }, [query, searchText]);

  const groups = useMemo(() => {
    const map = new Map<string, SearchHit[]>();
    for (const h of hits) { if (!map.has(h.path)) map.set(h.path, []); map.get(h.path)!.push(h); }
    return [...map.entries()];
  }, [hits]);

  const highlight = (text: string) => {
    const i = text.toLowerCase().indexOf(query.trim().toLowerCase());
    if (i < 0 || !query.trim()) return text;
    return <>{text.slice(0, i)}<mark>{text.slice(i, i + query.trim().length)}</mark>{text.slice(i + query.trim().length)}</>;
  };

  return <div className="search-pane">
    <div className="search-box filter" style={{ margin: 0 }}>
      <Search size={13} style={{ left: 16 }} />
      <input className="field" autoFocus placeholder="Search in files" aria-label="Search in files" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') setQuery(''); }} />
      {query && <button className="icon-btn sm" style={{ position: 'absolute', right: 11, top: 4 }} aria-label="Clear search" onClick={() => setQuery('')}><X size={12} /></button>}
    </div>
    <p className="search-meta" role="status">
      {error ? error : !query.trim() ? (kind === 'folder' ? 'Searches open files in a connected folder.' : 'Type to search across the project.') : busy ? 'Searching…' : `${hits.length} ${hits.length === 1 ? 'result' : 'results'} in ${groups.length} ${groups.length === 1 ? 'file' : 'files'}`}
    </p>
    <div className="results">
      {groups.map(([path, list]) => <div key={path}>
        <button className="result-file" onClick={() => setCollapsed(c => { const n = new Set(c); if (n.has(path)) n.delete(path); else n.add(path); return n; })} aria-expanded={!collapsed.has(path)} title={path}>
          <ChevronRight size={12} style={{ transform: collapsed.has(path) ? undefined : 'rotate(90deg)', color: 'var(--fg-4)' }} />
          <FileIcon path={path} /><span className="ellipsis">{path.split('/').pop()}</span><small>{list.length}</small>
        </button>
        {!collapsed.has(path) && list.map(h => <button key={`${h.line}:${h.text}`} className="result-line" onClick={() => openPath(h.path, h.line)}>
          <span className="ln">{h.line}</span><span className="ellipsis">{highlight(h.text)}</span>
        </button>)}
      </div>)}
    </div>
  </div>;
}
