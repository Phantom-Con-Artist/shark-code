import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { ChevronDown, ChevronRight, FileCode2, FilePlus2, Folder, FolderOpen, RotateCcw, Save, Search, X } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
const CodeEditor = lazy(() => import('./CodeEditor'));
export function ProjectFiles() {
  const project = useProjectStore();
  const [expanded, setExpanded] = useState(new Set(['src', 'src/components', 'src/components/workspace', 'src/stores']));
  const [search, setSearch] = useState('');
  const [newFile, setNewFile] = useState(false);
  const [newPath, setNewPath] = useState('');
  const [openPath, setOpenPath] = useState(false);
  const [folderPath, setFolderPath] = useState('');
  const [explorerOpen, setExplorerOpen] = useState(true);
  useEffect(() => { void project.initialize(); }, []);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (useProjectStore.getState().tabs.some(t => t.content !== t.saved)) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, []);
  const active = project.tabs.find(t => t.path === project.activePath);
  const entries = useMemo(() => [...project.entries].sort((a,b) => Number(b.directory) - Number(a.directory) || a.path.localeCompare(b.path)), [project.entries]);
  const renderFolder = (parent: string, depth: number): React.ReactNode => entries.filter(e => { const parts = e.path.split('/'); parts.pop(); return parts.join('/') === parent; }).map(entry => <div key={entry.path}><button className={`explorer-row ${project.activePath === entry.path ? 'active' : ''}`} style={{ paddingLeft: 10 + depth * 13 }} onClick={() => {
    if (!entry.directory) { void project.openFile(entry.path); return; }
    setExpanded(current => { const next = new Set(current); if (next.has(entry.path)) next.delete(entry.path); else next.add(entry.path); return next; });
  }} aria-expanded={entry.directory ? expanded.has(entry.path) : undefined} title={entry.path}>
    {entry.directory ? <>{expanded.has(entry.path) ? <ChevronDown size={11}/> : <ChevronRight size={11}/>}<Folder size={13}/></> : <><span className="tree-spacer"/><FileCode2 size={13}/></>}<span>{entry.path.split('/').pop()}</span>{project.tabs.some(t => t.path === entry.path && t.content !== t.saved) && <span className="dirty-dot"/>}</button>{entry.directory && expanded.has(entry.path) && renderFolder(entry.path, depth + 1)}</div>);
  return <div className="project-editor">
    <div className="project-actions"><button className="text-button" onClick={() => setExplorerOpen(v => !v)}><Folder size={14}/>{explorerOpen ? 'Hide explorer' : 'Show explorer'}</button><button className="text-button" onClick={() => isTauri() ? setOpenPath(v => !v) : void project.openFolder()} disabled={project.busy}><FolderOpen size={14}/>Open folder</button><button className="text-button" onClick={() => setNewFile(v => !v)}><FilePlus2 size={14}/>New file</button></div>
    {openPath && <form className="file-create-form" onSubmit={e => { e.preventDefault(); void project.openFolder(folderPath).then(() => setOpenPath(false)); }}><input autoFocus aria-label="Project folder path" placeholder="/path/to/your/project" value={folderPath} onChange={e => setFolderPath(e.target.value)}/><button type="submit" disabled={!folderPath}>Open</button></form>}
    {newFile && <form className="file-create-form" onSubmit={async e => { e.preventDefault(); await project.createFile(newPath); if (!useProjectStore.getState().error) { setNewFile(false); setNewPath(''); } }}><input autoFocus aria-label="New file path" placeholder="src/new-file.ts" value={newPath} onChange={e => setNewPath(e.target.value)}/><button type="submit" disabled={!newPath.trim()}>Create</button><button type="button" aria-label="Cancel new file" onClick={() => setNewFile(false)}><X size={13}/></button></form>}
    {project.error && <div className="project-error" role="alert"><span>{project.error}</span><button className="icon-button" aria-label="Dismiss error" onClick={project.clearError}><X size={13}/></button></div>}
    <div className={`editor-split ${explorerOpen ? '' : 'explorer-hidden'}`}>
      {explorerOpen && <nav className="file-explorer" aria-label="File explorer"><div className="explorer-title">{project.name}</div><label className="file-filter"><Search size={12}/><input placeholder="Find a file…" aria-label="Find a file" value={search} onChange={e => setSearch(e.target.value)}/></label><div className="file-tree">{search ? entries.filter(e => !e.directory && e.path.toLowerCase().includes(search.toLowerCase())).map(e => <button className="explorer-row search-file-result" key={e.path} title={e.path} onClick={() => void project.openFile(e.path)}><FileCode2 size={13}/><span>{e.path}</span></button>) : renderFolder('', 0)}{search && !entries.some(e => !e.directory && e.path.toLowerCase().includes(search.toLowerCase())) && <p className="file-search-empty">No matching files.</p>}</div><div className="explorer-count">{entries.filter(e => !e.directory).length} files</div></nav>}
      <div className="editor-main"><div className="editor-tabs">{project.tabs.map(t => <div key={t.path} className={`editor-tab ${t.path === project.activePath ? 'active' : ''}`}><button title={t.path} onClick={() => void project.openFile(t.path)}><FileCode2 size={12}/>{t.path.split('/').pop()}{t.content !== t.saved && <span className="dirty-dot"/>}</button><button aria-label={`Close ${t.path}`} onClick={() => project.closeFile(t.path)}><X size={12}/></button></div>)}</div><div className="editor-file-toolbar"><span title={project.activePath}>{project.activePath || 'No file selected'}</span><button className="reload-file" aria-label="Reload file" title="Reload from saved file" disabled={!active || project.busy} onClick={() => { if (active && (active.content === active.saved || window.confirm('Discard unsaved edits and reload this file?'))) void project.reloadFile(project.activePath); }}><RotateCcw size={13}/></button><button className="save-file" disabled={!active || active.content === active.saved || project.busy} onClick={() => void project.save(project.activePath)}><Save size={13}/>Save</button></div><div className="monaco-container"><Suspense fallback={<div className="editor-empty">Loading editor…</div>}><CodeEditor/></Suspense></div><div className="editor-save-status" role="status"><span>{active && active.content !== active.saved ? 'Unsaved changes' : project.notice || 'All changes saved'}</span><span>{project.kind === 'browser' ? 'Browser workspace' : 'Local files'}<span className="shortcut-hint"> · Ctrl/⌘ S</span></span></div></div>
    </div>
  </div>;
}
