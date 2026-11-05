import { useEffect, useState } from 'react';
import { Check, ChevronRight, FileCode2, ShieldCheck } from 'lucide-react';
import { sharkBackend } from '../../lib/sharkBackend';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';

export function TaskReview() {
  const agent = useAgentWorkspace();
  const task = agent.tasks.find(t => t.id === agent.activeId);
  const [selected, setSelected] = useState(0);
  const [version, setVersion] = useState<'before' | 'after'>('after');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [truncated, setTruncated] = useState(false);
  const [showCode, setShowCode] = useState(false);
  const file = agent.proposal?.files[selected];
  useEffect(() => { setSelected(0); }, [agent.proposal?.id]);
  useEffect(() => {
    let live = true;
    const id = version === 'before' ? file?.before_artifact : file?.after_artifact;
    setCode(''); setError(''); setTruncated(false);
    if (id && showCode) void sharkBackend.readArtifact(id, 1, 200).then(r => { if (live) { setCode(r.content); setTruncated(r.truncated); } }).catch(e => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [file, version, showCode]);
  if (!agent.proposal) return <div className="panel-empty"><ShieldCheck size={25}/><h2>Review with context.</h2><p>When your agent proposes a change, see the affected files and dependency evidence here before anything is applied.</p><span>Source files stay unchanged during review.</span></div>;
  const applied = agent.proposal.status === 'applied';
  return <section className="task-review"><header className="review-heading"><h2>{agent.proposal.files.length} {agent.proposal.files.length === 1 ? 'file' : 'files'} in this proposal</h2><p className="review-ordinary-status"><ShieldCheck size={14}/>{applied ? 'Changes applied' : 'Ready for review — source is unchanged'}</p></header>
    <div className="review-content"><section className="review-summary"><h3>What changes</h3><p>{task?.summary || 'The agent has not recorded a plain-language behavior summary for this proposal. Clarify the change before applying.'}</p><h3>What to check</h3><p>{task?.review_notes || 'No verification notes were recorded. Review the source and ask for the intended behavior and validation steps.'}</p></section><h3>Files changed</h3><div className="review-files">{agent.proposal.files.map((f, i) => <button key={f.path} className={selected === i ? 'selected' : ''} onClick={() => setSelected(i)} aria-pressed={selected === i}><FileCode2 size={15}/><span>{f.path}</span><small>{f.before_version === null ? 'Create' : f.after_version === null ? 'Delete' : 'Edit'}</small><ChevronRight size={14}/></button>)}</div>
      <section className="review-impact"><h3>Potential impact</h3><p>{agent.impact ? `${agent.impact.affected.length} dependent symbols found in the current graph.` : 'Impact evidence is loading.'}</p><p className="muted">Static analysis can miss dynamic calls and unsupported languages. Tests have not been run by this agent.</p>{agent.impact && <details><summary>Inspect dependency evidence</summary>{agent.impact.affected.slice(0, 15).map(row => <p key={row.node.id}><strong>{row.node.label}</strong><small>{row.node.path} · {row.confidence === 'EXTRACTED' ? 'Source relationship' : 'Inferred relationship'}</small></p>)}{agent.impact.truncated && <p>Impact results are limited.</p>}</details>}</section>
      <button className="secondary-button" aria-expanded={showCode} onClick={() => setShowCode(v => !v)}>{showCode ? 'Hide code details' : 'Inspect before and after'}</button>
      {showCode && <div className="review-source"><div className="version-switch"><button aria-pressed={version === 'before'} onClick={() => setVersion('before')}>Before</button><button aria-pressed={version === 'after'} onClick={() => setVersion('after')}>After</button></div><p className="muted">{file?.path} · {version === 'before' ? 'Original snapshot' : 'Proposed snapshot'}</p>{error ? <p role="alert">{error}</p> : <pre tabIndex={0} aria-label={`${version} source code`}><code>{code || (version === 'before' && !file?.before_artifact ? 'New file — no previous content.' : version === 'after' && !file?.after_artifact ? 'This file will be deleted.' : 'Loading snapshot…')}</code></pre>}{truncated && <p>Showing the first 200 lines. Open the artifact through the backend for more.</p>}</div>}
    </div><footer className="review-actions"><p><ShieldCheck size={14}/>Source versions and reviewed dependencies are checked again on apply.</p><button className="primary-button" disabled={applied || agent.busy || !task?.summary || agent.proposal.status !== 'prepared'} onClick={() => void agent.apply()}><Check size={15}/>{applied ? 'Applied' : agent.busy ? 'Applying…' : 'Apply reviewed proposal'}</button></footer>
  </section>;
}
