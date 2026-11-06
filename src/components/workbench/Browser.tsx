// Shark's built-in browser: previews the project (or a local dev server) through the runtime's preview
// server, which adds a picker. Click "Pick" and then any element: Shark finds the source lines that
// render it and drafts a change request. Console errors stream in; "Check" runs headless Chromium.
import { useEffect, useRef, useState } from 'react';
import { Activity, Crosshair, ExternalLink, Maximize2, Minimize2, Plus, RefreshCw, Sparkles, TerminalSquare, X } from 'lucide-react';
import { useUi } from '../../stores/useUi';
import { showContextMenu } from '../../stores/useContextMenu';
import { sharkBrowser, type PageCheck, type PickedElement, type SourceMatch } from '../../lib/sharkBackend';
import { useProjectStore } from '../../stores/useProjectStore';
import { useSettings } from '../../stores/useSettings';
import { askAgent } from './BottomPanel';
import { openPath } from './Sidebar';
import { FileIcon } from './primitives';

type LogLine = { level: string; message: string; at: number };
type Feedback = { pick: PickedElement; matches: SourceMatch[]; note: string; page: string };

/** Split the address into a preview-server target and the path to open on it. */
function parse(address: string) {
  const a = address.trim();
  if (/^(https?:\/\/)?(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?/i.test(a)) {
    const url = new URL(/^https?:\/\//.test(a) ? a : 'http://' + a);
    return { target: `${url.protocol}//${url.host}`, path: url.pathname + url.search + url.hash };
  }
  return { target: 'workspace', path: '/' + a.replace(/^\/+/, '') };
}

export function BrowserView() {
  const native = useProjectStore(s => s.kind) === 'native';
  const root = useProjectStore(s => s.root);
  const s = useSettings();
  const [address, setAddress] = useState(s.browserUrl && !/^https?:\/\/(localhost|127\.0\.0\.1):5173\/?$/.test(s.browserUrl) ? s.browserUrl : '');
  const [base, setBase] = useState('');
  const [src, setSrc] = useState('');
  const [nonce, setNonce] = useState(0);
  const [error, setError] = useState('');
  const [picking, setPicking] = useState(false);
  const [pick, setPick] = useState<PickedElement | null>(null);
  const [matches, setMatches] = useState<SourceMatch[] | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const [check, setCheck] = useState<PageCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [notes, setNotes] = useState<Feedback[]>([]);
  const [viewport, setViewport] = useState('fit');
  const [sourceError, setSourceError] = useState('');
  const wide = useUi(s => s.browserWide);
  const pickSequence = useRef(0);
  const frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => {setNotes([]); setPick(null); setFeedback(''); pickSequence.current++;}, [root]);

  const load = async (value = address) => {
    setError(''); setLogs([]); setCheck(null); setPick(null); setMatches(null); setPicking(false); pickSequence.current++;
    try {
      const { target, path } = parse(value);
      const served = await sharkBrowser.serve(target);
      setBase(served.base); setSrc(served.base + path); setNonce(n => n + 1);
      s.set({ browserUrl: value });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  useEffect(() => { if (native) void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [native, root]);
  // Opened from elsewhere (e.g. an HTML file's "Pick elements"): follow the requested address.
  const requested = s.browserUrl;
  useEffect(() => { if (native && requested && requested !== address && !requested.startsWith('http://localhost:5173')) { setAddress(requested); void load(requested); } /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [requested]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const d = e.data;
      if (!d || d.source !== 'shark-browser' || e.source !== frame.current?.contentWindow) return;
      if (d.type === 'picking') setPicking(!!d.on);
      else if (d.type === 'console') setLogs(l => [...l.slice(-99), { level: String(d.level), message: String(d.message), at: Date.now() }]);
      else if (d.type === 'loaded') { setPicking(false); const path = String(d.url).replace(base, '') || '/'; if (parse(address).target === 'workspace') setAddress(path.replace(/^\//, '')); }
      else if (d.type === 'context-menu') {
        const rect = frame.current?.getBoundingClientRect();
        showContextMenu((rect?.left ?? 0) + Number(d.x), (rect?.top ?? 0) + Number(d.y), [
          {label: 'Select this element', run: () => {const p = d.pick as PickedElement; setPick(p); setFeedback(''); setMatches(null); const sequence = ++pickSequence.current; void sharkBrowser.locate(p).then(r => {if (sequence === pickSequence.current) setMatches(r.matches);}).catch(() => {if (sequence === pickSequence.current) setMatches([]);});}},
          'separator', {label: 'Reload preview', run: () => setNonce(n => n + 1)},
          {label: 'Check page', run: async () => {setChecking(true); try {setCheck(await sharkBrowser.check(src));} finally {setChecking(false);}}},
          {label: 'Copy page address', run: () => navigator.clipboard.writeText(address || '/')},
          {label: 'Open externally', run: () => {window.open(src, '_blank');}},
        ]);
      }
      else if (d.type === 'pick') {
        const p = d as PickedElement; setPick(p); setMatches(null); setFeedback(''); setSourceError('');
        const sequence = ++pickSequence.current;
        void sharkBrowser.locate(p).then(r => { if (sequence === pickSequence.current) setMatches(r.matches); }).catch(e => { if (sequence === pickSequence.current) { setMatches([]); setSourceError(String(e)); } });
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [base, address, src]);

  const togglePick = () => {frame.current?.contentWindow?.postMessage({ source: 'shark', type: 'pick-mode', on: !picking }, base ? new URL(base).origin : '*'); frame.current?.focus();};
  const runCheck = async () => {
    setChecking(true);
    try { setCheck(await sharkBrowser.check(src)); } catch (e) { setCheck({ available: false, error: e instanceof Error ? e.message : String(e) }); }
    setChecking(false);
  };
  const askAboutPick = () => {
    const all = [...notes, ...(pick && feedback.trim() ? [{pick, matches: matches ?? [], note: feedback.trim(), page: address || '/'}] : [])];
    if (!all.length) return;
    askAgent('Apply this visual feedback to the project. Source matches are hints; verify the current source.\n\n' + all.map((n, i) => {
      const where = n.matches.slice(0, 3).map(m => `${m.path}:${m.line}`).join(', ');
      return `${i + 1}. ${n.note}\nPage: ${n.page}\nElement: ${n.pick.selector || n.pick.tag}\nText: ${n.pick.text}\nBounds: ${n.pick.rect.w} × ${n.pick.rect.h}${n.pick.viewport ? `; viewport ${n.pick.viewport.w} × ${n.pick.viewport.h}` : ''}${where ? `\nPossible source: ${where}` : ''}\nMarkup:\n\`\`\`html\n${n.pick.html.slice(0, 1200)}\n\`\`\``;
    }).join('\n\n'));
    useUi.getState().set({browserWide: false, composerFocus: Date.now()});
    s.set({editorOpen: true});
    setNotes([]); setFeedback(''); setPick(null); setMatches(null);
  };
  const errors = logs.filter(l => l.level === 'error');
  const sendErrors = () => askAgent(`The page ${address || '/'} logs these console errors. Find the cause and fix it:\n\n${errors.slice(-10).map(l => '- ' + l.message.split('\n')[0]).join('\n')}`);

  if (!native) return <p className="search-meta">The built-in browser runs in the desktop app.</p>;
  return <div className="browser">
    <form className="browser-bar" onSubmit={e => { e.preventDefault(); void load(); }}>
      <button type="button" className="icon-btn sm" aria-label="Reload" title="Reload" onClick={() => { setLogs([]); setNonce(n => n + 1); }}><RefreshCw size={12} /></button>
      <input className="field" value={address} onChange={e => setAddress(e.target.value)} placeholder="index.html or localhost:5173" aria-label="Address" spellCheck={false} />
      <button type="button" className={`icon-btn sm ${picking ? 'on' : ''}`} aria-pressed={picking} title="Pick an element (Esc to cancel)" aria-label="Pick an element" onClick={togglePick}><Crosshair size={12} /></button>
      <select className="field browser-viewport" aria-label="Preview width" value={viewport} onChange={e => setViewport(e.target.value)}><option value="fit">Fit width</option>{['1440','1280','1024','768'].map(v => <option key={v} value={v}>{v} px</option>)}</select>
      <button type="button" className="icon-btn sm" aria-label={wide ? 'Restore browser layout' : 'Expand browser'} title={wide ? 'Restore browser layout' : 'Expand browser'} aria-pressed={wide} onClick={() => useUi.getState().set({browserWide: !wide})}>{wide ? <Minimize2 size={14} /> : <Maximize2 size={14} />}</button>
      <button type="button" className="icon-btn sm" title="Check in headless Chromium" aria-label="Check page" disabled={checking || !src} onClick={() => void runCheck()}><Activity size={12} className={checking ? 'spin-slow' : ''} /></button>
      <button type="button" className="icon-btn sm" title="Open in system browser" aria-label="Open externally" disabled={!src} onClick={() => window.open(src, '_blank')}><ExternalLink size={12} /></button>
    </form>
    {error && <p className="notice danger browser-msg">{error}</p>}
    {picking && <p className="fine browser-hint" role="status"><Crosshair size={11} />Hover to inspect, click to select. ↑ picks the parent, Enter selects, Esc cancels.</p>}
    {src && <div className="browser-stage"><iframe ref={frame} key={nonce} style={viewport === 'fit' ? undefined : {width: Number(viewport), flex: 'none'}} className={`browser-frame ${picking ? 'picking' : ''}`} src={src} title="Page preview" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals" /></div>}

    {pick && <section className="pick-card" aria-label="Picked element">
      <header><code className="ellipsis" title={pick.selector}>{pick.selector || pick.tag}</code><span className="fine">{pick.rect.w} × {pick.rect.h}</span><button className="icon-btn sm" aria-label="Clear selection" onClick={() => { pickSequence.current++; setPick(null); setMatches(null); }}><X size={12} /></button></header>
      {pick.text && <p className="pick-text">“{pick.text.slice(0, 140)}”</p>}
      <div className="pick-sources">
        {matches === null ? <span className="fine">Finding source…</span>
          : matches.length === 0 ? <span className="fine">No source match. Shark will search when asked.</span>
          : matches.slice(0, 4).map(m => <button key={m.path + m.line} className="pick-source" title={m.snippet} onClick={() => openPath(m.path, m.line)}>
              <FileIcon path={m.path} size={11} /><span className="ellipsis">{m.path}</span><span className="muted">:{m.line}</span></button>)}
      </div>
      {sourceError && <p className="fine" role="status">Source lookup failed. The feedback will include the element for Shark to investigate.</p>}
      <label className="pick-feedback-label">What should change?<textarea className="field pick-feedback" value={feedback} maxLength={4000} placeholder="Describe the change for this element…" onChange={e => setFeedback(e.target.value)} onKeyDown={e => {if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {e.preventDefault(); askAboutPick();}}} /></label>
      <div className="pick-actions"><button className="btn sm" disabled={!feedback.trim() || notes.length >= 20} onClick={() => {setNotes(n => [...n, {pick, matches: matches ?? [], note: feedback.trim(), page: address || '/'}]); setPick(null); setFeedback(''); setMatches(null);}}><Plus size={12} />Add feedback</button><button className="btn primary sm" disabled={!feedback.trim()} onClick={askAboutPick}><Sparkles size={12} />Draft in Shark</button></div>
    </section>}
    {notes.length > 0 && <section className="pick-card feedback-queue" aria-label="Feedback queue"><header><strong>{notes.length} feedback item{notes.length === 1 ? '' : 's'}</strong><button className="btn sm" onClick={askAboutPick}><Sparkles size={12} />Draft feedback in Shark</button></header>{notes.map((n, i) => <div className="feedback-item" key={i}><code className="ellipsis" title={n.pick.selector}>{n.pick.selector}</code><span>{n.note}</span><button className="icon-btn sm" aria-label={`Remove feedback ${i + 1}`} onClick={() => setNotes(all => all.filter((_, index) => index !== i))}><X size={12} /></button></div>)}</section>}

    {check && <section className="pick-card" aria-label="Page check">
      <header><strong>{check.available ? (check.title || 'Untitled page') : 'Check unavailable'}</strong><button className="icon-btn sm" aria-label="Close" onClick={() => setCheck(null)}><X size={12} /></button></header>
      {check.available ? <>
        <p className="fine">HTTP {check.status ?? '?'} · {check.console?.length ?? 0} console issue{check.console?.length === 1 ? '' : 's'} · {check.failed_requests?.length ?? 0} failed request{check.failed_requests?.length === 1 ? '' : 's'}</p>
        {[...(check.console ?? []).map(c => `${c.level}: ${c.message}`), ...(check.failed_requests ?? []).map(f => `request: ${f.url} (${f.error})`)].slice(0, 6).map((line, i) => <p key={i} className="log-line err">{line}</p>)}
        {(check.console?.length || check.failed_requests?.length) ? <button className="btn sm" onClick={() => askAgent(`A headless check of ${src.replace(base, '') || '/'} found:\n${[...(check.console ?? []).map(c => `- ${c.level}: ${c.message}`), ...(check.failed_requests ?? []).map(f => `- failed request ${f.url}: ${f.error}`)].slice(0, 15).join('\n')}\n\nFix these.`)}><Sparkles size={12} />Fix with Shark</button> : <p className="fine ok-text">Clean: no console errors or failed requests.</p>}
      </> : <p className="fine">{check.error}</p>}
    </section>}

    <button className={`browser-console ${errors.length ? 'has-errors' : ''}`} aria-expanded={showLogs} onClick={() => setShowLogs(v => !v)}>
      <TerminalSquare size={12} />Console{logs.length ? ` · ${logs.length}` : ''}{errors.length ? <span className="count">{errors.length}</span> : null}
    </button>
    {showLogs && <div className="browser-logs">
      {logs.length === 0 ? <p className="fine">No warnings or errors.</p> : logs.slice(-40).map((l, i) => <p key={i} className={`log-line ${l.level === 'error' ? 'err' : 'warn'}`}>{l.message}</p>)}
      {errors.length > 0 && <button className="btn sm" onClick={sendErrors}><Sparkles size={12} />Send errors to Shark</button>}
    </div>}
  </div>;
}
