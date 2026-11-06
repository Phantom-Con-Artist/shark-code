import { useAutomata } from '../../stores/useAutomata';

/** What Shark needs to edit the open workflow: the file contract, the current graph, the selection and the last run. */
export function automataBrief(): string {
  const a = useAutomata.getState();
  const g = a.graph;
  const parts = [
    'You are working in Shark Automata, the visual workflow canvas. Workflows are plain files in the project, so create or edit them with your file tools; ' +
    'the person reviews your proposal before anything is applied and the canvas reloads from the files.',
    'Call the shark_automata tool with operation "catalog" first for the component list, built-in templates, and exact file format. ' +
    'Automata includes all 10 Codebase Intelligence components out of the box: intel.structure, intel.dependencies, intel.semantic, ' +
    'intel.impact, intel.quality, intel.security, intel.runtime, intel.architecture, intel.history, intel.context, plus intel.ast_grep and intel.gate (outputs pass/fail). ' +
    'Build any custom component as automata/components/<id>.component.json with tests, then use test_component, validate and dry_run and fix failures before you finish. ' +
    'Keep steps small and named by what they do. Add human.approval before any step that writes files, runs commands or calls an external service with side effects. ' +
    'Never claim a test passed unless a tool result shows it. Real runs are the person\'s decision.',
  ];
  if (g) {
    const json = JSON.stringify({ name: g.name, description: g.description, nodes: g.nodes, edges: g.edges });
    parts.push(`Open workflow: automata/${g.id}.automata.json${a.dirty ? ' (the canvas has unsaved edits; the file may lag by a moment)' : ''}\n` + (json.length > 7000 ? json.slice(0, 7000) + ' …(truncated; read the file)' : json));
    if (a.selected.length) parts.push(`Selected on the canvas: ${a.selected.join(', ')}`);
    if (a.validation && !a.validation.ok) parts.push('Current validation errors: ' + a.validation.errors.slice(0, 6).join('; '));
    const run = a.run;
    if (run) {
      const failed = Object.entries(run.nodes).filter(([, n]) => n.status === 'failed').map(([id, n]) => `${id}: ${n.error}`);
      parts.push(`Last ${run.mode === 'test' ? 'test' : 'run'}: ${run.status}${failed.length ? '. Failed steps: ' + failed.join('; ') : ''}`);
    }
  } else parts.push('No workflow is open yet. Create one at automata/<id>.automata.json.');
  return parts.join('\n\n');
}
