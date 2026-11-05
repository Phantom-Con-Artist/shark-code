import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { ChevronDown, ChevronRight, FileCode2, FilePlus2, Folder, FolderOpen, RotateCcw, Save, Search, X } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
const CodeEditor = lazy(() => import('./CodeEditor'));

export function FileExplorer({ onOpen }: { onOpen?: () => void }) {
  const project = useProjectStore();
  const [expanded, setExpanded] = useState(new Set(['src', 'src/components', 'src/components/workspace', 'src/stores']));
  const [search, setSearch] = useState('');
  const [form, setForm] = useState<'file' | 'folder' | null>(null);
  const [path, setPath] = useState('');
  const entries = useMemo(() => [...project.entries].sort((a,b) => Number(b.directory) - Number(a.directory) || a.path.localeCompare(b.path)), [project.entries]);
  const open = (name: string) => { void project.openFile(name); onOpen?.(); };
  const render = (parent: string, depth: number): React.ReactNode => entries.filter(e => e.path.split('/').slice(0,-1).join('/') === parent).map(entry => <div key={entry.path}>
    <button className={`explorer-row ${project.activePath === entry.path ? 'active' : ''}`} style={{ paddingLeft: 12 + depth * 13 }} onClick={() => {
      if (!entry.directory) { open(entry.path); return; }
      setExpanded(current => { const next = new Set(current); if (next.has(entry.path)) next.delete(entry.path); else next.add(entry.path); return next; });
    }} aria-expanded={entry.directory ? expanded.has(entry.path) : undefined} aria-current={!entry.directory && project.activePath === entry.path ? 'true' : undefined} title={entry.path}>
      {entry.directory ? <>{expanded.has(entry.path) ? <ChevronDown size={12}/> : <ChevronRight size={12}/>}<Folder size={14}/></> : <><span className="tree-spacer"/><FileCode2 size={14}/></>}
      <span>{entry.path.split('/').pop()}</span>{project.tabs.some(t => t.path === entry.path && t.content !== t.saved) && <span className="dirty-dot" aria-label="Unsaved"/>}
    </button>{entry.directory && expanded.has(entry.path) && render(entry.path, depth + 1)}</div>);
  return <div className="file-explorer"><div className="explorer-heading"><strong>Files</strong><button className="icon-button" aria-label="Open folder" title="Open folder" onClick={() => { setPath(''); if (isTauri()) setForm('folder'); else void project.openFolder(); }}><FolderOpen size={15}/></button><button className="icon-button" aria-label="New file" title="New file" onClick={() => { setPath(''); setForm('file'); }}><FilePlus2 size={15}/></button></div>
    {form && <form className="file-create-form" onSubmit={async e => { e.preventDefault(); if (form === 'folder') await project.openFolder(path); else await project.createFile(path); if (!useProjectStore.getState().error) { setForm(null); onOpen?.(); } }}><label>{form === 'folder' ? 'Project folder path' : 'New file path'}<input autoFocus value={path} onChange={e => setPath(e.target.value)} placeholder={form === 'folder' ? '/path/to/project' : 'src/new-file.ts'}/></label><div><button className="secondary-button" type="submit" disabled={!path.trim()}>{form === 'folder' ? 'Open folder' : 'Create file'}</button><button type="button" className="icon-button" aria-label="Cancel" onClick={() => setForm(null)}><X size={14}/></button></div></form>}
    <label className="file-filter"><Search size={14}/><input placeholder="Find a file…" aria-label="Find a file" value={search} onChange={e => setSearch(e.target.value)}/></label>
    <div className="explorer-project"><ChevronDown size={13}/><span>{project.name}</span></div>
    <nav className="file-tree" aria-label="Project files">{search ? entries.filter(e => !e.directory && e.path.toLowerCase().includes(search.toLowerCase())).map(e => <button className="explorer-row" key={e.path} title={e.path} onClick={() => open(e.path)}><FileCode2 size={14}/><span>{e.path}</span></button>) : render('', 0)}{search && !entries.some(e => !e.directory && e.path.toLowerCase().includes(search.toLowerCase())) && <p className="empty-label">No matching files.</p>}</nav>
    <div className="explorer-count">{entries.filter(e => !e.directory).length} files <span>{project.kind === 'native' ? 'On disk' : project.kind === 'folder' ? 'Connected folder' : 'Browser copy'}</span></div>
  </div>;
}

export function ProjectFiles() {
  const project = useProjectStore();
  const active = project.tabs.find(t => t.path === project.activePath);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (useProjectStore.getState().tabs.some(t => t.content !== t.saved)) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, []);
  return <div className="editor-main"><div className="editor-tabs" aria-label="Open files">{project.tabs.map(t => <div key={t.path} className={`editor-tab ${t.path === project.activePath ? 'active' : ''}`}><button title={t.path} aria-pressed={t.path === project.activePath} onClick={() => void project.openFile(t.path)}><FileCode2 size={14}/>{t.path.split('/').pop()}{t.content !== t.saved && <span className="dirty-dot" aria-label="Unsaved"/>}</button><button aria-label={`Close ${t.path}`} onClick={() => project.closeFile(t.path)}><X size={13}/></button></div>)}</div>
    <div className="editor-file-toolbar"><span title={project.activePath}>{project.activePath || 'No file selected'}</span><button className="icon-button" aria-label="Reload file" title="Reload saved file" disabled={!active || project.busy} onClick={() => { if (active && (active.content === active.saved || window.confirm('Discard unsaved edits and reload this file?'))) void project.reloadFile(project.activePath); }}><RotateCcw size={14}/></button><button className="save-file" disabled={!active || active.content === active.saved || project.busy} onClick={() => void project.save(project.activePath)}><Save size={14}/>Save</button></div>
    <div className="monaco-container"><Suspense fallback={<div className="editor-empty">Loading editor…</div>}><CodeEditor/></Suspense></div>
    <div className="editor-save-status" role="status"><span>{active && active.content !== active.saved ? 'Unsaved changes' : project.notice || 'All changes saved'}</span><span>{active?.path.split('.').pop()?.toUpperCase() || 'Text'} · UTF-8</span></div>
  </div>;
}
