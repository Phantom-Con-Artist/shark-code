import { useEffect, useState } from 'react';
import { Check, ChevronRight, Columns2, Rows2 } from 'lucide-react';
import { readArtifact as readAll } from '../../lib/artifacts';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { useUi } from '../../stores/useUi';
import { DiffView } from './CodeEditor';
import { changeKind, FileIcon } from './primitives';

export default function ReviewView() {
  const agent = useAgentWorkspace();
  const proposal = agent.proposal!;
  const task = agent.tasks.find(t => t.proposal_id === proposal?.id) ?? agent.tasks.find(t => t.id === agent.activeId);
  const [selected, setSelected] = useState(0);
  const [inline, setInline] = useState(true);
  const [pair, setPair] = useState<{ before: string; after: string } | null>(null);
  const [error, setError] = useState('');
  const file = proposal.files[Math.min(selected, proposal.files.length - 1)];
  const applied = proposal.status === 'applied';

  useEffect(() => { setSelected(0); }, [proposal.id]);
  useEffect(() => {
    let live = true; setPair(null); setError('');
    if (!file) return;
    Promise.all([readAll(file.before_artifact), readAll(file.after_artifact)])
      .then(([before, after]) => { if (live) setPair({ before, after }); })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [file?.path, file?.before_artifact, file?.after_artifact]);

  return <div className="review">
    <aside className="review-side">
      <div>
        <h2>{applied ? 'Changes applied' : 'Review changes'}</h2>
        <p className="muted" style={{ marginTop: 4, fontSize: 12 }}>{applied ? 'These edits are now in your files.' : 'Nothing is written until you apply.'}</p>
      </div>
      <section>
        <h3 className="label">What changes</h3>
        <p>{task?.summary || 'The agent did not explain this change. Ask it to describe the intended behavior before applying.'}</p>
      </section>
      {task?.review_notes && <section>
        <h3 className="label">What to check</h3>
        <p>{task.review_notes}</p>
      </section>}
      <section>
        <h3 className="label">Files</h3>
        <div className="review-files">
          {proposal.files.map((f, i) => <button key={f.path} aria-pressed={i === selected} onClick={() => setSelected(i)} title={f.path}>
            <FileIcon path={f.path} /><span className="grow ellipsis">{f.path}</span><span className={`badge ${changeKind(f)}`}>{changeKind(f)}</span>
          </button>)}
        </div>
      </section>
      {agent.impact && <details className="impact">
        <summary><ChevronRight size={12} />{agent.impact.affected.length ? `${agent.impact.affected.length} related symbols may be affected` : 'No dependent symbols found'}</summary>
        <ul>
          {agent.impact.affected.slice(0, 20).map(row => <li key={row.node.id}>{row.node.label}<small>{row.node.path}{row.confidence !== 'EXTRACTED' ? ' · inferred' : ''}</small></li>)}
          {agent.impact.truncated && <li className="muted">More results were omitted.</li>}
        </ul>
        <p className="fine" style={{ marginTop: 8 }}>Static analysis; dynamic calls can be missed.</p>
      </details>}
      <div className="review-actions">
        <button className="btn accent" disabled={applied || agent.busy || !task?.summary || proposal.status !== 'prepared'} onClick={() => void agent.apply()}>
          <Check size={15} />{applied ? 'Applied' : agent.busy ? 'Applying…' : 'Apply changes'}
        </button>
        {!applied && <button className="btn ghost" onClick={() => useUi.getState().set({ composerFocus: Date.now() })}>Ask for changes</button>}
        <small>File versions are re-checked when you apply. The agent has not run your tests.</small>
      </div>
    </aside>
    <div className="review-main">
      <div className="review-bar">
        {file && <><FileIcon path={file.path} /><span className="grow ellipsis mono" style={{ color: 'var(--fg-2)' }}>{file.path}</span></>}
        <div className="segmented" role="group" aria-label="Diff layout">
          <button aria-pressed={inline} onClick={() => setInline(true)} title="Inline"><Rows2 size={13} />Inline</button>
          <button aria-pressed={!inline} onClick={() => setInline(false)} title="Side by side"><Columns2 size={13} />Split</button>
        </div>
      </div>
      <div className="review-diff">
        {error ? <div className="editor-empty"><p role="alert">{error}</p></div>
          : !pair ? <div className="editor-empty">Loading changes…</div>
          : <DiffView key={file.path + inline} path={file.path} original={pair.before} modified={pair.after} inline={inline} />}
      </div>
    </div>
  </div>;
}
