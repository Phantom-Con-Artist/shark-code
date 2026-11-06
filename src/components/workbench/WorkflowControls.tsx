import { useEffect, useId, useState } from 'react';
import { Check, ChevronDown, CircleAlert, LoaderCircle, Pause, Play, Square } from 'lucide-react';
import { sharkWorkflows, type AgentTask, type Workflow } from '../../lib/sharkBackend';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { useSettings, type ProviderId } from '../../stores/useSettings';

const LABELS: Record<string, string> = {
  created: 'Ready to start', running: 'Working through the plan', pausing: 'Finishing the current operation',
  paused: 'Paused at a checkpoint', interrupted: 'Interrupted, progress saved', waiting_human: 'Needs your decision',
  blocked: 'Needs attention', failed: 'Workflow failed', review: 'Ready for final review',
  completed: 'Workflow complete', cancelled: 'Workflow stopped',
};
const STEPS: Record<string, string> = {
  pending: 'Waiting', running: 'Working', succeeded: 'Finished', failed: 'Failed', interrupted: 'Interrupted', waiting_human: 'Needs answer',
};

export function WorkflowControls({ task }: { task: AgentTask }) {
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const inputId = useId();
  const workflowId = task.workflow_id!;
  const settings = useSettings();
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let previous = '';
    const poll = async () => {
      try {
        const next = await sharkWorkflows.get(workflowId);
        if (next.next_step_offset !== null) {
          const remaining = await sharkWorkflows.get(workflowId, next.next_step_offset);
          next.steps.push(...remaining.steps);
          next.next_step_offset = remaining.next_step_offset;
        }
        if (disposed) return;
        setLoadError('');
        setWorkflow(next);
        if (previous && next.status !== previous) await useAgentWorkspace.getState().poll();
        previous = next.status;
        if (!['completed', 'cancelled'].includes(next.status)) timer = setTimeout(poll, 800);
      } catch (err) {
        if (!disposed) { setLoadError(err instanceof Error ? err.message : String(err)); timer = setTimeout(poll, 2500); }
      }
    };
    setWorkflow(null); setError(''); setAnswer('');
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [workflowId]);
  useEffect(() => { setAnswer(''); }, [workflow?.gate?.id]);

  const act = async (action: () => Promise<Workflow>) => {
    setBusy(true); setError('');
    try { const next = await action(); setWorkflow(next); await useAgentWorkspace.getState().poll(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };
  const key = settings.keys[(task.engine || settings.provider) as ProviderId];
  const respond = (decision: 'answer' | 'approve' | 'reject') => act(async () => {
    const next = await sharkWorkflows.respond(workflowId, workflow!.gate!.id, decision, answer);
    if (next.status === 'paused') return sharkWorkflows.resume(workflowId, key);
    return next;
  });
  if (!workflow) return <div className="workflow-progress" role="status">{loadError || error || 'Loading workflow progress…'}</div>;
  const done = workflow.steps.filter(step => step.status === 'succeeded').length;
  const current = workflow.steps.find(step => step.status === 'running');
  return <section className="workflow-progress" aria-label="Workflow progress">
    <header>
      <strong>{LABELS[workflow.status] || workflow.status}</strong>
      <span className="muted">{done} of {workflow.step_count} steps</span>
    </header>
    {current && <p className="fine">{current.title}</p>}
    <button type="button" className="workflow-details" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
      <ChevronDown size={13} />{expanded ? 'Hide steps' : 'Show steps'}
    </button>
    {expanded && <ol className="workflow-step-list">{workflow.steps.map(step => <li key={step.id}>
      {step.status === 'succeeded' ? <Check size={13} /> : step.status === 'running' ? <LoaderCircle size={13} /> : <span className="workflow-step-dot" />}
      <span>{step.title}<small>{step.summary}</small></span><span className="muted">{STEPS[step.status] || step.status}</span>
    </li>)}{workflow.next_step_offset !== null && <li className="fine">More steps are available in the workflow API.</li>}</ol>}
    {workflow.gate && <form className="workflow-question" onSubmit={event => { event.preventDefault(); void respond(workflow.gate!.kind === 'question' ? 'answer' : 'approve'); }}>
      <label htmlFor={inputId}>{workflow.gate.question}</label>
      <textarea id={inputId} className="field" rows={3} maxLength={2000} value={answer} onChange={event => setAnswer(event.target.value)}
        placeholder={workflow.gate.kind === 'question' ? 'Your answer' : 'Optional note'} disabled={busy} />
      <div className="workflow-actions">
        <button type="submit" className="btn accent sm" disabled={busy || (workflow.gate.kind === 'question' && !answer.trim())}>
          {busy ? 'Continuing…' : workflow.gate.kind === 'question' ? 'Answer and continue' : 'Approve and continue'}
        </button>
        {workflow.gate.kind === 'approval' && <button type="button" className="btn sm" disabled={busy} onClick={() => void respond('reject')}>Reject</button>}
      </div>
    </form>}
    <div className="workflow-actions">
      {workflow.status === 'running' && <button type="button" className="btn sm" disabled={busy} onClick={() => void act(() => sharkWorkflows.pause(workflowId))}><Pause size={13} />Pause</button>}
      {!workflow.gate && ['created', 'paused', 'interrupted', 'blocked', 'failed'].includes(workflow.status) && <button type="button" className="btn sm" disabled={busy}
        onClick={() => void act(() => workflow.status === 'created' ? sharkWorkflows.start(workflowId, key) : sharkWorkflows.resume(workflowId, key, ['blocked', 'failed'].includes(workflow.status)))}>
        <Play size={13} />{['blocked', 'failed'].includes(workflow.status) ? 'Retry failed step' : 'Continue'}
      </button>}
      {!['completed', 'cancelled', 'review'].includes(workflow.status) && <button type="button" className="btn sm" disabled={busy}
        onClick={() => void act(() => sharkWorkflows.cancel(workflowId))}><Square size={12} />Stop workflow</button>}
    </div>
    {workflow.summary && <p className="fine">{workflow.summary}</p>}
    {(error || loadError) && <p className="notice danger" role="alert"><CircleAlert size={13} />{error || loadError}</p>}
  </section>;
}
