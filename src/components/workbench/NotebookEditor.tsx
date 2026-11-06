import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Code2, FileText, Play, Plus, RotateCcw, Save, Square, Trash2, X } from 'lucide-react';
import { request } from '../../lib/sharkBackend';
import { useProjectStore, type OpenFile } from '../../stores/useProjectStore';
import { Markdown } from './Markdown';

type Output = { output_type: string; text?: string | string[]; name?: string; ename?: string; evalue?: string; traceback?: string[]; data?: Record<string, unknown>; [key: string]: unknown };
type Cell = { id: string; cell_type: 'code' | 'markdown' | 'raw'; source: string | string[]; metadata: Record<string, unknown>; outputs?: Output[]; execution_count?: number | null; [key: string]: unknown };
type Notebook = { nbformat: number; nbformat_minor: number; cells: Cell[]; metadata: Record<string, unknown>; [key: string]: unknown };
type Job = { id: string; path: string; status: string; error: string | null; cells: Record<string, { outputs: Output[]; execution_count: number | null; status: string }> };
const running = new Map<string, {id: string; sources: Record<string, string>}>();
const text = (value: unknown): string => Array.isArray(value) ? value.join('') : typeof value === 'string' ? value : '';
const plain = (value: unknown) => text(value).replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
function parse(content: string): Notebook {
  const nb = JSON.parse(content);
  if (nb.nbformat !== 4 || !Array.isArray(nb.cells) || !nb.metadata || typeof nb.metadata !== 'object') throw Error('Expected a Jupyter notebook in version 4 format.');
  const ids = new Set<string>();
  nb.cells.forEach((cell: Cell, i: number) => {
    if (!['code', 'markdown', 'raw'].includes(cell.cell_type) || !(typeof cell.source === 'string' || Array.isArray(cell.source))) throw Error(`Cell ${i + 1} has an invalid type or source.`);
    cell.id ||= `cell-${i + 1}`;
    if (ids.has(cell.id)) throw Error('Notebook cell IDs must be unique.');
    ids.add(cell.id);
  });
  return nb;
}
export default function NotebookEditor({ file }: { file: OpenFile }) {
  const root = useProjectStore(s => s.root);
  const native = useProjectStore(s => s.kind) === 'native';
  const edit = useProjectStore(s => s.edit);
  const parsed = useMemo(() => { try { return { nb: parse(file.content), error: '' }; } catch (e) { return { nb: null, error: String(e) }; } }, [file.content]);
  const [kernels, setKernels] = useState<{name: string; display_name: string}[]>([]);
  const [kernel, setKernel] = useState('shark-python');
  const [error, setError] = useState('');
  const [jobId, setJobId] = useState(() => running.get(root + ':' + file.path)?.id ?? '');
  const [busy, setBusy] = useState(!!jobId);
  const [status, setStatus] = useState('Ready');
  const [markdownEdit, setMarkdownEdit] = useState<string[]>([]);
  const starting = useRef(false);
  const sourceAtRun = useRef<Record<string, string>>(running.get(root + ':' + file.path)?.sources ?? {});
  const nb = parsed.nb;
  const change = (next: Notebook) => edit(file.path, JSON.stringify(next, null, 1) + '\n');
  useEffect(() => { if (native) void request<{kernels: typeof kernels}>('notebook/kernels').then(r => setKernels(r.kernels)).catch(e => setError(String(e))); }, [native, root]);
  useEffect(() => {
    if (!jobId) return;
    let live = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const job = await request<Job>('notebook/execution', {id: jobId});
        if (!live) return;
        const project = useProjectStore.getState();
        const current = project.root === root && project.tabs.find(t => t.path === file.path);
        if (current) {
          const updated = parse(current.content);
          for (const cell of updated.cells) {
            const result = job.cells[cell.id];
            const original = sourceAtRun.current[cell.id];
            if (result && (original === undefined || original === text(cell.source))) {
              cell.outputs = result.outputs; cell.execution_count = result.execution_count;
            }
          }
          const content = JSON.stringify(updated, null, 1) + '\n';
          if (Object.keys(job.cells).length && content !== current.content) project.edit(file.path, content);
        }
        setStatus(job.status === 'running' ? 'Running…' : job.status === 'completed' ? 'Execution finished · outputs unsaved' : job.status);
        if (job.error) setError(job.error);
        if (job.status === 'running') timer = setTimeout(poll, 250);
        else { running.delete(root + ':' + file.path); setBusy(false); setJobId(''); }
      } catch (e) { if (live) { setError(String(e)); setBusy(false); setJobId(''); running.delete(root + ':' + file.path); } }
    };
    void poll();
    return () => { live = false; clearTimeout(timer); };
  }, [jobId, file.path, root]);
  const execute = async (cellIds?: string[]) => {
    if (!nb || busy || starting.current) return;
    starting.current = true; setBusy(true); setError(''); setStatus('Starting kernel…');
    sourceAtRun.current = Object.fromEntries(nb.cells.map(c => [c.id, text(c.source)]));
    try {
      const job = await request<Job>('notebook/execute', {path: file.path, notebook: nb, kernel, ...(cellIds ? {cell_ids: cellIds} : {})});
      running.set(root + ':' + file.path, {id: job.id, sources: sourceAtRun.current}); setJobId(job.id);
    } catch (e) { setError(String(e)); setBusy(false); setStatus('Ready'); }
    finally { starting.current = false; }
  };
  const control = async (op: string) => {
    try { await request('notebook/' + op, {path: file.path}); if (op !== 'interrupt') setStatus('Kernel stopped · next run starts fresh'); }
    catch (e) { setError(String(e)); }
  };
  if (!nb) return <div className="editor-empty" role="alert">{parsed.error} Open the JSON source to repair it.</div>;
  const updateCell = (id: string, source: string) => change({...nb, cells: nb.cells.map(c => c.id === id ? {...c, source, ...(c.cell_type === 'code' ? {outputs: [], execution_count: null} : {})} : c)});
  const addCell = (kind: Cell['cell_type']) => change({...nb, cells: [...nb.cells, {id: crypto.randomUUID(), cell_type: kind, source: '', metadata: {}, ...(kind === 'code' ? {outputs: [], execution_count: null} : {})}]});
  const move = (i: number, delta: number) => { const cells = [...nb.cells]; [cells[i], cells[i + delta]] = [cells[i + delta], cells[i]]; change({...nb, cells}); };
  return <section className="notebook" aria-label={`Notebook ${file.path}`}>
    <div className="notebook-toolbar">
      <button className="btn sm" disabled={!native || busy} onClick={() => void execute()}><Play size={13} />Run all</button>
      <button className="btn sm" disabled={!busy} onClick={() => void control('interrupt')}><Square size={13} />Interrupt</button>
      <button className="btn sm" disabled={!native || busy} onClick={() => void control('restart')}><RotateCcw size={13} />Restart kernel</button>
      <button className="btn sm" disabled={!native || busy} onClick={() => void control('shutdown')}>Shut down</button>
      <select className="field" aria-label="Notebook kernel" value={kernel} disabled={busy} onChange={e => setKernel(e.target.value)}><option value="shark-python">Shark Python (bundled)</option>{kernels.filter(k => k.name !== 'shark-python').map(k => <option key={k.name} value={k.name}>{k.display_name}</option>)}</select>
      <button className="btn sm" disabled={busy} onClick={() => change({...nb, cells: nb.cells.map(c => c.cell_type === 'code' ? {...c, outputs: [], execution_count: null} : c)})}>Clear outputs</button>
      <button className="btn sm" onClick={() => void useProjectStore.getState().save(file.path)}><Save size={13} />Save</button>
      <span className="fine" role="status">{native ? status : 'Editing only · run cells in the desktop app'}</span>
    </div>
    {error && <div className="notice danger notebook-error" role="alert">{error}<button className="icon-btn sm" aria-label="Dismiss notebook error" onClick={() => setError('')}><X size={13} /></button></div>}
    <div className="notebook-cells">
      {nb.cells.map((cell, i) => <section className="notebook-cell" key={cell.id} aria-label={`${cell.cell_type} cell ${i + 1}`} data-cell-id={cell.id}>
        <header><span className="notebook-count">{cell.cell_type === 'code' ? `[${cell.execution_count ?? ' '}]` : i + 1}</span><select className="notebook-cell-type" aria-label={`Type of cell ${i + 1}`} value={cell.cell_type} disabled={busy} onChange={e => {const kind = e.target.value as Cell['cell_type']; const cells = nb.cells.map(c => {if (c.id !== cell.id) return c; const next = {...c, cell_type: kind}; delete next.outputs; delete next.execution_count; if (kind === 'code') {next.outputs = []; next.execution_count = null;} return next;}); change({...nb, cells});}}><option value="code">Code</option><option value="markdown">Markdown</option><option value="raw">Raw</option></select><span className="grow" />
          {cell.cell_type === 'code' && <button className="icon-btn sm" disabled={!native || busy} aria-label={`Run cell ${i + 1}`} title="Run cell · Ctrl Enter" onClick={() => void execute([cell.id])}><Play size={13} /></button>}
          {cell.cell_type === 'markdown' && <button className="btn sm" onClick={() => setMarkdownEdit(ids => ids.includes(cell.id) ? ids.filter(id => id !== cell.id) : [...ids, cell.id])}>{markdownEdit.includes(cell.id) ? 'Preview' : 'Edit'}</button>}
          <button className="icon-btn sm" disabled={busy || i === 0} aria-label={`Move cell ${i + 1} up`} onClick={() => move(i, -1)}><ArrowUp size={13} /></button>
          <button className="icon-btn sm" disabled={busy || i === nb.cells.length - 1} aria-label={`Move cell ${i + 1} down`} onClick={() => move(i, 1)}><ArrowDown size={13} /></button>
          <button className="icon-btn sm" disabled={busy} aria-label={`Delete cell ${i + 1}`} onClick={() => change({...nb, cells: nb.cells.filter(c => c.id !== cell.id)})}><Trash2 size={13} /></button>
        </header>
        {cell.cell_type === 'markdown' && !markdownEdit.includes(cell.id) ? <div className="notebook-markdown" onDoubleClick={() => setMarkdownEdit(ids => [...ids, cell.id])}><Markdown text={text(cell.source) || '*Empty markdown cell — choose Edit to write.*'} /></div>
          : <textarea className="notebook-source" aria-label={`Source for cell ${i + 1}`} value={text(cell.source)} disabled={busy} rows={Math.max(3, Math.min(24, text(cell.source).split('\n').length + 1))} spellCheck={false} onChange={e => updateCell(cell.id, e.target.value)} onKeyDown={e => {
            if ((e.ctrlKey || e.metaKey || e.shiftKey) && e.key === 'Enter' && cell.cell_type === 'code') { e.preventDefault(); void execute([cell.id]); }
            if (e.key === 'Tab') { e.preventDefault(); const t = e.currentTarget; const start = t.selectionStart; updateCell(cell.id, t.value.slice(0, start) + '    ' + t.value.slice(t.selectionEnd)); requestAnimationFrame(() => { t.selectionStart = t.selectionEnd = start + 4; }); }
          }} />}
        {cell.outputs?.length ? <div className="notebook-outputs">{cell.outputs.map((output, n) => <NotebookOutput key={n} output={output} />)}</div> : null}
      </section>)}
      <div className="notebook-add"><button className="btn sm" disabled={busy} onClick={() => addCell('code')}><Plus size={13} /><Code2 size={13} />Code cell</button><button className="btn sm" disabled={busy} onClick={() => addCell('markdown')}><Plus size={13} /><FileText size={13} />Markdown cell</button></div>
    </div>
  </section>;
}
function NotebookOutput({output}: {output: Output}) {
  if (output.output_type === 'stream') return <pre className={output.name === 'stderr' ? 'notebook-stderr' : ''}>{plain(output.text)}</pre>;
  if (output.output_type === 'error') return <pre className="notebook-stderr">{plain(output.traceback?.join('\n') || `${output.ename}: ${output.evalue}`)}</pre>;
  const data = output.data ?? {};
  for (const mime of ['image/png', 'image/jpeg', 'image/gif']) if (data[mime]) return <img alt="Cell output" src={`data:${mime};base64,${text(data[mime]).replace(/\s/g, '')}`} />;
  if (data['text/html']) return <iframe className="notebook-html" title="Notebook HTML output" sandbox="" srcDoc={`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><style>body{font:13px system-ui;color:#222}table{border-collapse:collapse}td,th{padding:6px;border:1px solid #ddd}</style>${text(data['text/html'])}`} />;
  if (data['text/markdown']) return <Markdown text={text(data['text/markdown'])} />;
  if (data['image/svg+xml']) return <img alt="Cell output" src={'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(text(data['image/svg+xml']))} />;
  return <pre>{plain(data['text/plain']) || 'This output type needs an interactive Jupyter extension.'}</pre>;
}
