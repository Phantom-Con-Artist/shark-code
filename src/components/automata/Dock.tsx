import { useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { Check, ChevronDown, FileCode2, FlaskConical, RotateCcw, Square, X } from 'lucide-react';
import { useAutomata } from '../../stores/useAutomata';
import { useProjectStore } from '../../stores/useProjectStore';
import { useUi } from '../../stores/useUi';
import { sharkAutomata, type AutomataNode, type ComponentSpec, type ParamSpec } from '../../lib/automata';
import { useMonacoTheme } from '../workbench/CodeEditor';
import '../workbench/monaco';

const pretty = (v: unknown) => { const t = JSON.stringify(v, null, 2) ?? ''; return t.length > 6000 ? t.slice(0, 6000) + '\n…' : t; };

function ParamField({ spec, value, onChange, theme }: { spec: ParamSpec; value: unknown; onChange(v: unknown): void; theme: string }) {
  const id = `p-${spec.name}`;
  const text = typeof value === 'string' ? value : value === undefined || value === null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  return <div className="field">
    <label htmlFor={id}>{spec.label}{spec.required && <i aria-hidden> *</i>}</label>
    {spec.kind === 'bool' ? <input id={id} type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} />
      : spec.kind === 'select' ? <select id={id} value={text} onChange={e => onChange(e.target.value)}>{spec.options?.map(o => <option key={o}>{o}</option>)}</select>
      : spec.kind === 'number' ? <input id={id} type="number" value={text} onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
      : spec.kind === 'code' && spec.name === 'code' ? <div className="field-code"><Editor language="python" theme={theme} value={text} onChange={v => onChange(v ?? '')} options={{ minimap: { enabled: false }, fontSize: 12, lineNumbers: 'off', scrollBeyondLastLine: false, automaticLayout: true, padding: { top: 6 }, folding: false }} /></div>
      : spec.kind === 'code' || spec.kind === 'json' ? <textarea id={id} className="mono" rows={spec.kind === 'json' ? 3 : 4} value={text} spellCheck={false} onChange={e => onChange(e.target.value)} />
      : <input id={id} value={text} onChange={e => onChange(e.target.value)} spellCheck={false} />}
    {spec.help && <small>{spec.help}</small>}
  </div>;
}

function Inspector() {
  const a = useAutomata();
  const theme = useMonacoTheme();
  const [result, setResult] = useState<{ id: string; r: Awaited<ReturnType<typeof sharkAutomata.testNode>> } | null>(null);
  const [sample, setSample] = useState('{}');
  const node: AutomataNode | undefined = a.graph?.nodes.find(n => n.id === a.selected[0]);
  const spec: ComponentSpec | undefined = node && a.catalog.find(c => c.type === node.type);
  useEffect(() => { setResult(null); }, [node?.id]);
  if (!a.graph) return null;
  if (!node || !spec) return <div className="dock-body">
    <div className="field"><label htmlFor="wf-name">Workflow name</label><input id="wf-name" value={a.graph.name} onChange={e => a.rename(e.target.value)} /></div>
    <p className="search-meta">{a.graph.nodes.length} steps · {a.graph.edges.length} connections · saved as automata/{a.graph.id}.automata.json</p>
    {a.validation && [...a.validation.errors.map(m => ['bad', m]), ...a.validation.warnings.map(m => ['warn', m])].map(([k, m], i) => <p key={i} className={`dock-note ${k}`}>{m}</p>)}
    {a.validation?.ok && !a.validation.warnings.length && a.graph.nodes.length > 0 && <p className="dock-note ok"><Check size={12} />Valid. Ready to test.</p>}
  </div>;
  const last = a.run?.nodes[node.id];
  const test = async () => {
    let input: unknown = {}; try { input = JSON.parse(sample || '{}'); } catch { setResult({ id: node.id, r: { ok: false, error: 'Sample input is not valid JSON', seconds: 0 } }); return; }
    const upstream: Record<string, unknown> = {}; for (const [id, n] of Object.entries(a.run?.nodes ?? {})) if (n.status === 'succeeded') upstream[id] = n.output;
    try { setResult({ id: node.id, r: await sharkAutomata.testNode(a.graph!, node.id, input, upstream) }); } catch (e) { setResult({ id: node.id, r: { ok: false, error: e instanceof Error ? e.message : String(e), seconds: 0 } }); }
  };
  return <div className="dock-body insp">
    <div className="insp-col">
      <div className="field"><label htmlFor="n-label">Name</label><input id="n-label" value={node.label ?? ''} placeholder={spec.label} onChange={e => a.patchNode(node.id, { label: e.target.value })} /><small>{node.id} · {spec.type}</small></div>
      {spec.params.map(p => <ParamField key={p.name} spec={p} theme={theme} value={node.params[p.name] ?? p.default} onChange={v => a.setParam(node.id, p.name, v)} />)}
      <details className="adv"><summary>Retries and errors</summary>
        <div className="field"><label htmlFor="n-retries">Retries on failure</label><input id="n-retries" type="number" min={0} max={5} value={node.retries ?? 0} disabled={!!spec.effect} onChange={e => a.patchNode(node.id, { retries: Math.min(5, Math.max(0, Number(e.target.value) || 0)) })} /><small>{spec.effect ? 'Steps that change things are never retried automatically.' : 'Waits 1s, 2s, 4s… between attempts.'}</small></div>
        <div className="field"><label htmlFor="n-err">If it still fails</label><select id="n-err" value={node.on_error ?? 'stop'} onChange={e => a.patchNode(node.id, { on_error: e.target.value as 'stop' | 'continue' })}><option value="stop">Stop the run</option><option value="continue">Continue with the error</option></select></div>
      </details>
    </div>
    <div className="insp-col">
      <div className="field"><label htmlFor="n-sample">Test input (JSON)</label><textarea id="n-sample" className="mono" rows={2} value={sample} onChange={e => setSample(e.target.value)} spellCheck={false} /></div>
      <button className="btn" onClick={() => void test()}><FlaskConical size={13} />Test this step</button>
      <small className="muted">Tests are dry: files are not written, commands are not run, only GET requests are sent.</small>
      {result?.id === node.id && <div className={`dock-note ${result.r.ok ? 'ok' : 'bad'}`}>{result.r.ok ? `Passed in ${result.r.seconds}s${result.r.port ? ` · output ${result.r.port}` : ''}` : result.r.error}<pre>{result.r.ok ? pretty(result.r.output) : ''}</pre>{result.r.logs && <pre>{result.r.logs}</pre>}</div>}
      {last && <><h4 className="dock-h">Last run</h4><p className={`dock-note ${last.status === 'failed' ? 'bad' : last.status === 'succeeded' ? 'ok' : ''}`}>{last.status}{last.error ? `: ${last.error}` : ''} · {last.attempts} attempt{last.attempts === 1 ? '' : 's'} · {last.seconds}s{last.output !== null && <pre>{pretty(last.output)}</pre>}{last.logs && <pre>{last.logs}</pre>}</p></>}
    </div>
  </div>;
}

function RunPanel() {
  const a = useAutomata();
  const [answer, setAnswer] = useState('');
  const run = a.run;
  if (!run) return <div className="dock-body"><p className="search-meta">Press Test for a safe dry run, or Run to do it for real. Progress shows on the canvas.</p></div>;
  const failed = Object.values(run.nodes).some(n => n.status === 'failed');
  return <div className="dock-body runp">
    <div className="run-head"><span className={`dot ${run.status === 'running' ? 'live' : run.status === 'completed' ? 'ok' : run.status === 'failed' ? 'err' : 'warn'}`} />
      <strong>{run.mode === 'test' ? 'Test run' : 'Run'} · {({ running: 'working', waiting_human: 'waiting for you', completed: 'completed', failed: 'stopped at a failed step', cancelled: 'cancelled', interrupted: 'interrupted' } as Record<string, string>)[run.status]}</strong>
      <span className="grow" />
      {run.status === 'running' && <button className="btn" onClick={() => void a.cancel()}><Square size={12} />Stop</button>}
      {run.status === 'interrupted' && <button className="btn" onClick={() => void a.resume(false)}><RotateCcw size={12} />Resume from checkpoint</button>}
      {(run.status === 'failed' || failed && run.status !== 'running') && <button className="btn" onClick={() => void a.resume(true)}><RotateCcw size={12} />Retry failed step</button>}
    </div>
    {run.gate && <div className="gate"><strong>{run.gate.question}</strong>
      {run.gate.detail != null && <pre>{pretty(run.gate.detail)}</pre>}
      {run.gate.kind === 'question' ? <div className="gate-row"><input value={answer} onChange={e => setAnswer(e.target.value)} placeholder="Your answer" aria-label="Your answer" /><button className="btn primary" onClick={() => { void a.respond('answer', answer); setAnswer(''); }}>Send</button></div>
        : <div className="gate-row"><button className="btn primary" onClick={() => void a.respond('approve')}><Check size={13} />Approve</button><button className="btn" onClick={() => void a.respond('reject')}><X size={13} />Reject</button></div>}</div>}
    <div className="run-cols">
      <ol className="run-steps">{a.graph?.nodes.filter(n => run.nodes[n.id]).map(n => { const r = run.nodes[n.id]; return <li key={n.id}><button className={a.selected[0] === n.id ? 'on' : ''} onClick={() => a.select([n.id])}>
        <span className={`cv-state ${r.status}`}>{r.status === 'succeeded' ? '✓' : r.status === 'failed' ? '!' : r.status === 'waiting' ? '?' : r.status === 'skipped' ? '–' : ''}</span><span className="ellipsis">{n.label || a.catalog.find(c => c.type === n.type)?.label || n.id}</span><small>{r.status}{r.seconds ? ` · ${r.seconds}s` : ''}</small></button></li>; })}</ol>
      <div className="run-log" role="log">{run.log.slice().reverse().map((l, i) => <p key={i} className={l.level}><time>{new Date(l.t * 1000).toLocaleTimeString()}</time>{l.node && <b>{l.node}</b>}{l.message}</p>)}</div>
    </div>
  </div>;
}

function CodePanel() {
  const a = useAutomata();
  const theme = useMonacoTheme();
  useEffect(() => { const t = setTimeout(() => void a.generateCode(), 300); return () => clearTimeout(t); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [a.graph?.nodes, a.graph?.edges]);
  return <div className="dock-body codep">
    <div className="run-head"><FileCode2 size={14} /><strong>{a.code?.filename ?? 'Python'}</strong><span className="grow" />
      <button className="btn" disabled={!a.code} onClick={async () => { await a.exportCode(); const f = useAutomata.getState().code?.filename; if (f) { await useProjectStore.getState().openFile(f); useUi.getState().set({ editorView: 'file' }); } }}>Save and open in editor</button></div>
    {a.error && !a.code ? <p className="dock-note bad">{a.error}</p> : <div className="code-view"><Editor language="python" theme={theme} value={a.code?.code ?? '# Add steps to see the generated code'} options={{ readOnly: true, minimap: { enabled: false }, fontSize: 12, scrollBeyondLastLine: false, automaticLayout: true }} /></div>}
    <small className="muted">Generated from the canvas, one function per step. It runs on its own with Python. Edit steps on the canvas, or change a Code step's Python in its inspector.</small>
  </div>;
}

export function Dock() {
  const a = useAutomata();
  const tabs: [typeof a.dock, string][] = [['inspector', a.selected[0] ? 'Step' : 'Workflow'], ['run', 'Run'], ['code', 'Code']];
  return <section className="dock" aria-label="Details">
    <div className="dock-tabs" role="tablist">{tabs.map(([id, label]) => <button key={id} role="tab" aria-selected={a.dock === id} onClick={() => a.showDock(id)}>{label}</button>)}
      <span className="grow" /><button className="icon-btn sm" aria-label="Collapse details" onClick={() => useAutomata.setState({ dockOpen: false })}><ChevronDown size={14} /></button></div>
    {a.dock === 'inspector' ? <Inspector /> : a.dock === 'run' ? <RunPanel /> : <CodePanel />}
  </section>;
}
