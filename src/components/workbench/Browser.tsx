// Shark's built-in browser: previews the project (or a local dev server) through the runtime's preview
// server, which adds a picker. Click "Pick" and then any element: Shark finds the source lines that
// render it and drafts a change request. Console errors stream in; "Check" runs headless Chromium.
import { useEffect, useRef, useState } from 'react';
import { Activity, Crosshair, ExternalLink, RefreshCw, Sparkles, TerminalSquare, X } from 'lucide-react';
import { sharkBrowser, type PageCheck, type PickedElement, type SourceMatch } from '../../lib/sharkBackend';
import { useProjectStore } from '../../stores/useProjectStore';
import { useSettings } from '../../stores/useSettings';
import { askAgent } from './BottomPanel';
import { openPath } from './Sidebar';
import { FileIcon } from './primitives';

type LogLine = { level: string; message: string; at: number };

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
  const frame = useRef<HTMLIFrameElement>(null);

  const load = async (value = address) => {
    setError(''); setLogs([]); setCheck(null);
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
      else if (d.type === 'pick') {
        const p = d as PickedElement; setPick(p); setMatches(null);
        void sharkBrowser.locate(p).then(r => setMatches(r.matches)).catch(() => setMatches([]));
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [base, address]);

  const togglePick = () => frame.current?.contentWindow?.postMessage({ source: 'shark', type: 'pick-mode', on: !picking }, '*');
  const runCheck = async () => {
    setChecking(true);
    try { setCheck(await sharkBrowser.check(src)); } catch (e) { setCheck({ available: false, error: e instanceof Error ? e.message : String(e) }); }
    setChecking(false);
  };
  const askAboutPick = () => {
    if (!pick) return;
    const where = (matches ?? []).slice(0, 3).map(m => `${m.path}:${m.line}`).join(', ');
    const text = pick.text ? ` showing "${pick.text.slice(0, 80)}"` : '';
    askAgent(`In the page ${parse(address).target === 'workspace' ? '/' + address : address}, change the <${pick.tag}> element \`${pick.selector}\`${text}${where ? ` (rendered around ${where})` : ''}.\n\nElement markup:\n\`\`\`html\n${pick.html.slice(0, 600)}\n\`\`\`\n\nChange: `);
  };
  const errors = logs.filter(l => l.level === 'error');
  const sendErrors = () => askAgent(`The page ${address || '/'} logs these console errors. Find the cause and fix it:\n\n${errors.slice(-10).map(l => '- ' + l.message.split('\n')[0]).join('\n')}`);

  if (!native) return <p className="search-meta">The built-in browser runs in the desktop app.</p>;
  return <div className="browser">
    <form className="browser-bar" onSubmit={e => { e.preventDefault(); void load(); }}>
      <button type="button" className="icon-btn sm" aria-label="Reload" title="Reload" onClick={() => { setLogs([]); setNonce(n => n + 1); }}><RefreshCw size={12} /></button>
      <input className="field" value={address} onChange={e => setAddress(e.target.value)} placeholder="index.html or localhost:5173" aria-label="Address" spellCheck={false} />
      <button type="button" className={`icon-btn sm ${picking ? 'on' : ''}`} aria-pressed={picking} title="Pick an element (Esc to cancel)" aria-label="Pick an element" onClick={togglePick}><Crosshair size={12} /></button>
      <button type="button" className="icon-btn sm" title="Check in headless Chromium" aria-label="Check page" disabled={checking || !src} onClick={() => void runCheck()}><Activity size={12} className={checking ? 'spin-slow' : ''} /></button>
      <button type="button" className="icon-btn sm" title="Open in system browser" aria-label="Open externally" disabled={!src} onClick={() => window.open(src, '_blank')}><ExternalLink size={12} /></button>
    </form>
    {error && <p className="notice danger browser-msg">{error}</p>}
    {picking && <p className="fine browser-hint"><Crosshair size={11} />Click any element in the page. Esc cancels.</p>}
    {src && <iframe ref={frame} key={nonce} className={`browser-frame ${picking ? 'picking' : ''}`} src={src} title="Page preview" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals" />}

    {pick && <section className="pick-card" aria-label="Picked element">
      <header><code className="ellipsis" title={pick.selector}>{pick.selector || pick.tag}</code><button className="icon-btn sm" aria-label="Clear" onClick={() => { setPick(null); setMatches(null); }}><X size={12} /></button></header>
      {pick.text && <p className="pick-text">“{pick.text.slice(0, 140)}”</p>}
      <div className="pick-sources">
        {matches === null ? <span className="fine">Finding source…</span>
          : matches.length === 0 ? <span className="fine">No source match. Shark will search when asked.</span>
          : matches.slice(0, 4).map(m => <button key={m.path + m.line} className="pick-source" title={m.snippet} onClick={() => openPath(m.path, m.line)}>
              <FileIcon path={m.path} size={11} /><span className="ellipsis">{m.path}</span><span className="muted">:{m.line}</span></button>)}
      </div>
      <button className="btn primary sm" onClick={askAboutPick}><Sparkles size={12} />Ask Shark to change this</button>
    </section>}

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
