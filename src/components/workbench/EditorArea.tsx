import { lazy, Suspense, useEffect, useState } from 'react';
import { BookOpen, ChevronRight, Code2, Columns2, Crosshair, GitCompareArrows, Globe, Radar, RotateCcw, Sparkles, X } from 'lucide-react';
import { BrowserView } from './Browser';
import { openWorkbenchBrowser } from '../../lib/workbenchBrowser';
import { confirmAction } from '../../stores/useDialogs';
import { isTauri } from '@tauri-apps/api/core';
import { Markdown } from './Markdown';
import { useSettings } from '../../stores/useSettings';
import { sharkWorkspace, type ImpactReport } from '../../lib/sharkBackend';
import { Popover } from './primitives';
import { askAgent } from './BottomPanel';
import { useProjectStore } from '../../stores/useProjectStore';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { useUi } from '../../stores/useUi';
import { FileIcon, SharkMark } from './primitives';

const CodeEditor = lazy(() => import('./CodeEditor'));
const ReviewView = lazy(() => import('./ReviewView'));
const MediaPreview = lazy(() => import('./MediaPreview'));
const NotebookEditor = lazy(() => import('./NotebookEditor'));

export async function closeTab(path: string) {
  const project = useProjectStore.getState();
  const tab = project.tabs.find(t => t.path === path);
  if (tab && tab.content !== tab.saved && !await confirmAction({title: 'Discard unsaved changes?', message: `Your edits to ${path.split('/').pop()} will be lost.`, confirmLabel: 'Discard changes', danger: true})) return;
  project.closeFile(path, true);
}

export function EditorArea() {
  const project = useProjectStore();
  const proposal = useAgentWorkspace(s => s.proposal);
  const view = useUi(s => s.editorView);
  const setUi = useUi(s => s.set);
  const active = project.tabs.find(t => t.path === project.activePath);
  const showReview = view === 'review' && !!proposal;
  const showBrowser = view === 'browser';
  const [browserMounted, setBrowserMounted] = useState(showBrowser);
  useEffect(() => { if (showBrowser) setBrowserMounted(true); }, [showBrowser]);
  const mdMode = useUi(s => s.mdMode);
  const isMd = !!active && /\.(md|mdx|markdown|html?|svg)$/i.test(active.path);
  const isNotebook = !!active && /\.ipynb$/i.test(active.path);

  useEffect(() => { if (!proposal && view === 'review') setUi({ editorView: 'file' }); }, [proposal, view, setUi]);
  // Smart default per file type: documents open rendered, pages open side by side.
  useEffect(() => { const p = project.activePath; if (/\.(md|mdx|markdown|ipynb)$/i.test(p)) setUi({ mdMode: 'preview' }); else if (/\.(html?|svg)$/i.test(p)) setUi({ mdMode: 'split' }); }, [project.activePath, setUi]);
  useEffect(() => {
    if (isTauri()) return;
    const warn = (e: BeforeUnloadEvent) => { if (useProjectStore.getState().tabs.some(t => t.content !== t.saved)) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, []);

  return <section className="wb-editor" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }} aria-label="Editor">
    {(project.tabs.length > 0 || proposal || browserMounted || showBrowser) && <div className="tabs" role="tablist" aria-label="Open files">
      {(browserMounted || showBrowser) && <div className={`tab ${showBrowser ? 'active' : ''}`} role="tab" aria-selected={showBrowser} tabIndex={0} onClick={() => setUi({editorView: 'browser'})} onKeyDown={e => {if (e.key === 'Enter') setUi({editorView: 'browser'});}}><Globe size={13} /><span className="tab-label">Browser</span><button className="tab-close" aria-label="Close browser" onClick={e => {e.stopPropagation(); setBrowserMounted(false); setUi({editorView: 'file', browserWide: false});}}><X size={13} /></button></div>}
      {proposal && <div className={`tab tab-review ${showReview ? 'active' : ''}`} role="tab" aria-selected={showReview} tabIndex={0}
        onClick={() => setUi({ editorView: 'review' })} onKeyDown={e => { if (e.key === 'Enter') setUi({ editorView: 'review' }); }}>
        <GitCompareArrows size={14} /><span className="tab-label">Review · {proposal.files.length} {proposal.files.length === 1 ? 'file' : 'files'}</span><span style={{ width: 6 }} />
      </div>}
      {project.tabs.map(t => {
        const isActive = !showReview && !showBrowser && t.path === project.activePath;
        const dirty = t.content !== t.saved;
        return <div key={t.path} data-file-path={t.path} className={`tab ${isActive ? 'active' : ''}`} role="tab" aria-selected={isActive} tabIndex={0} title={t.path}
          onClick={() => { void project.openFile(t.path); setUi({ editorView: 'file' }); }}
          onKeyDown={e => { if (e.key === 'Enter') { void project.openFile(t.path); setUi({ editorView: 'file' }); } }}
          onAuxClick={e => { if (e.button === 1) closeTab(t.path); }}>
          <FileIcon path={t.path} size={13} />
          <span className="tab-label">{t.path.split('/').pop()}</span>
          <button className="tab-close" aria-label={`Close ${t.path}${dirty ? ' (unsaved)' : ''}`} onClick={e => { e.stopPropagation(); closeTab(t.path); }}>
            {dirty && <span className="unsaved" />}<X size={13} className="x" />
          </button>
        </div>;
      })}
      <div className="tabs-fill" />
    </div>}

    {!showReview && !showBrowser && active && <div className="crumbs">
      {active.path.split('/').map((seg, i) => <span key={i} style={{ display: 'contents' }}>
        {i > 0 && <ChevronRight size={11} />}<button className="seg" onClick={() => useSettings.getState().set({ sidebarOpen: true, sidebarView: 'files' })}>{seg}</button>
      </span>)}
      <span className="state">
        {!active.media && useProjectStore.getState().kind === 'native' && <BlastRadius path={active.path} />}
        {isMd && <div className="segmented" role="group" aria-label="Preview">
          <button aria-pressed={mdMode === 'edit'} title="Source" onClick={() => setUi({ mdMode: 'edit' })}><Code2 size={12} /></button>
          <button aria-pressed={mdMode === 'split'} title="Side by side" onClick={() => setUi({ mdMode: 'split' })}><Columns2 size={12} /></button>
          <button aria-pressed={mdMode === 'preview'} title="Preview · Ctrl Shift V" onClick={() => setUi({ mdMode: 'preview' })}><BookOpen size={12} /></button>
        </div>}
        {isNotebook && <div className="segmented" role="group" aria-label="Notebook view"><button aria-pressed={mdMode !== 'edit'} title="Notebook cells" onClick={() => setUi({mdMode: 'preview'})}><BookOpen size={12} /></button><button aria-pressed={mdMode === 'edit'} title="Notebook JSON source" onClick={() => setUi({mdMode: 'edit'})}><Code2 size={12} /></button></div>}
        {active.media ? <span>Read-only preview</span> : active.content !== active.saved ? <span>Unsaved · <kbd>Ctrl S</kbd></span> : <span>{project.notice || 'Saved'}</span>}
        <button className="icon-btn sm" title="Reload from disk" aria-label="Reload from disk" disabled={project.busy}
          onClick={async () => { if (active.content === active.saved || await confirmAction({title: 'Reload from disk?', message: 'Unsaved edits to this file will be discarded.', confirmLabel: 'Discard and reload', danger: true})) void project.reloadFile(active.path); }}><RotateCcw size={12} /></button>
      </span>
    </div>}

    {(browserMounted || showBrowser) && <div className="workbench-browser" hidden={!showBrowser}><BrowserView /></div>}
    <div className="editor-host" hidden={showBrowser}>
      <Suspense fallback={<div className="editor-empty">Loading editor…</div>}>
        {showReview ? <ReviewView /> : active?.media ? <MediaPreview key={active.media.url} file={active} /> : active && isNotebook && mdMode !== 'edit' ? <NotebookEditor key={project.root + ':' + active.path} file={active} /> : active ? (isMd && mdMode !== 'edit'
          ? <div className={`md-split ${mdMode}`}>{mdMode === 'split' && <div className="md-source"><CodeEditor /></div>}{/\.(html?|svg)$/i.test(active.path) ? <HtmlPreview path={active.path} content={active.content} /> : <article className="md-preview"><Markdown text={active.content} className="doc" /></article>}</div>
          : <CodeEditor />) : <EmptyEditor />}
      </Suspense>
    </div>
  </section>;
}

function EmptyEditor() {
  const [mac] = useState(() => /Mac/.test(navigator.platform));
  const mod = mac ? '⌘' : 'Ctrl';
  return <div className="editor-empty">
    <div>
      <SharkMark className="mark" />
      <div className="shortcut-list">
        <span>Go to file</span><kbd>{mod} P</kbd>
        <span>Commands</span><kbd>{mod} K</kbd>
        <span>Ask the agent</span><kbd>{mod} L</kbd>
        <span>Toggle terminal</span><kbd>{mod} J</kbd>
        <span>Toggle sidebar</span><kbd>{mod} B</kbd>
      </div>
    </div>
  </div>;
}

/** Live HTML/SVG preview. Local stylesheets and scripts are inlined so the page renders as built; sandboxed, no same-origin. */
function HtmlPreview({ path, content }: { path: string; content: string }) {
  const readText = useProjectStore(s => s.readText);
  const [doc, setDoc] = useState('');
  useEffect(() => {
    let live = true;
    const dir = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : '';
    const resolve = (ref: string) => { const parts = (dir + ref).split('/'); const out: string[] = []; for (const p of parts) { if (p === '..') out.pop(); else if (p && p !== '.') out.push(p); } return out.join('/'); };
    const timer = setTimeout(async () => {
      if (/\.svg$/i.test(path)) { if (live) setDoc(`<body style="margin:0;display:grid;place-items:center;min-height:100vh">${content}</body>`); return; }
      let html = content;
      for (const m of [...content.matchAll(/<link[^>]+href=["']([^"':]+\.css)["'][^>]*>/gi)]) { const css = await readText(resolve(m[1])); if (css !== null) html = html.replace(m[0], `<style>${css}</style>`); }
      for (const m of [...content.matchAll(/<script([^>]*)src=["']([^"':]+\.js)["']([^>]*)><\/script>/gi)]) { const js = await readText(resolve(m[2])); if (js !== null) html = html.replace(m[0], `<script${m[1]}${m[3]}>${js.replace(/<\/script/gi, '<\\/script')}</script>`); }
      if (live) setDoc(html);
    }, 250);
    return () => { live = false; clearTimeout(timer); };
  }, [path, content, readText]);
  const native = useProjectStore(s => s.kind) === 'native';
  return <div className="html-preview-wrap">
    <iframe className="html-preview" title={`Preview of ${path}`} sandbox="allow-scripts allow-forms allow-modals" srcDoc={doc} />
    {native && !/\.svg$/i.test(path) && <button className="btn sm html-pick" title="Open in Shark's browser to pick elements and see console errors"
      onClick={() => openWorkbenchBrowser(path)}><Crosshair size={12} />Pick elements</button>}
  </div>;
}

/** What depends on this file, from Shark's code graph, the same evidence agents use. */
function BlastRadius({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<ImpactReport | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { setReport(null); setError(''); }, [path]);
  const load = () => { setOpen(o => !o); if (!report) void sharkWorkspace.impact([path]).then(setReport).catch(e => setError(e instanceof Error ? e.message : String(e))); };
  const affected = report?.affected ?? [];
  return <span style={{ position: 'relative' }}>
    <button className="crumb-btn" data-popover-anchor onClick={load} title="Blast radius: what depends on this file" aria-expanded={open}><Radar size={12} />{report ? affected.length : 'Impact'}</button>
    <Popover open={open} onClose={() => setOpen(false)} className="impact-pop" style={{ right: 0, top: 'calc(100% + 6px)' }}>
      <div className="group label">Blast radius · {path.split('/').pop()}</div>
      {error ? <p className="fine pop-note">{error}</p> : !report ? <p className="fine pop-note">Analysing dependencies…</p> : !affected.length ? <p className="fine pop-note">Nothing in the graph depends on this file.</p> : <>
        {affected.slice(0, 30).map(a => <button key={a.node.id} className="menu-item" onClick={() => { if (a.node.path) { void useProjectStore.getState().openFile(a.node.path); const line = Number(/L(\d+)/.exec(a.node.location ?? '')?.[1]); if (line) useUi.getState().set({ reveal: { path: a.node.path, line }, editorView: 'file' }); } setOpen(false); }}>
          <span className="text"><span className="ellipsis">{a.node.label}</span><small>{a.node.path} · {a.distance === 1 ? 'direct' : `${a.distance} hops`}{a.confidence !== 'EXTRACTED' ? ' · inferred' : ''}</small></span>
        </button>)}
        {report.truncated && <p className="fine pop-note">More results omitted.</p>}
      </>}
      <hr />
      <button className="menu-item" onClick={() => { setOpen(false); askAgent(`Assess the blast radius of changing ${path}: list affected callers and what could break, then suggest a safe change plan.`); }}><Sparkles size={13} /><span className="text">Ask Shark to assess</span></button>
    </Popover>
  </span>;
}
