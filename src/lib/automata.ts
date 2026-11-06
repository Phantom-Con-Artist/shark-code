import { request } from './sharkBackend';

export type ParamKind = 'text' | 'number' | 'bool' | 'json' | 'code' | 'select';
export interface ParamSpec { name: string; label: string; kind: ParamKind; default: unknown; help: string; required: boolean; options?: string[] }
export interface ComponentSpec {
  type: string; label: string; category: string; description: string; params: ParamSpec[]; outputs: string[]; inputs: boolean;
  effect: string | null; icon: string; builtin: boolean; code?: string; file?: string; id?: string;
}
export interface AutomataNode {
  id: string; type: string; label?: string; x: number; y: number; params: Record<string, unknown>;
  retries?: number; retry_delay?: number; on_error?: 'stop' | 'continue';
}
export interface AutomataEdge { id: string; from: string; from_port: string; to: string }
export interface Graph { id: string; name: string; description?: string; nodes: AutomataNode[]; edges: AutomataEdge[]; version?: number }
export interface WorkflowSummary { id: string; name: string; description: string; nodes: number; version: string; modified: number; broken?: boolean }
export type NodeStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'waiting' | 'cancelled';
export interface NodeRun { status: NodeStatus; attempts: number; output: unknown; port: string | null; error: string | null; logs: string; seconds: number }
export interface Gate { id: string; node: string; kind: 'approval' | 'question'; question: string; detail: unknown; node_type: string }
export interface RunLog { t: number; node: string | null; level: 'info' | 'warn' | 'error'; message: string }
export interface Run {
  id: string; graph_id: string; mode: 'run' | 'test'; status: 'running' | 'waiting_human' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  version: number; started_at: number; updated_at: number; finished_at: number | null; gate: Gate | null; log: RunLog[]; warnings: string[];
  nodes: Record<string, NodeRun>; vars: Record<string, unknown>; execution_boundary: string;
}
export interface Validation { ok: boolean; errors: string[]; warnings: string[] }
export interface EngineRun { provider: string; model: string; effort?: string }
export interface ComponentTest { component: string; passed: boolean; cases: { name: string; passed: boolean; ok: boolean; error?: string; output?: unknown; expected?: unknown }[] }

export interface IntelligenceReport {
  artifact_id: string;
  revision: string;
  status: string;
  kind: string;
  data: Record<string, unknown>;
}

export const sharkAutomata = {
  catalog: () => request<{ components: ComponentSpec[]; problems: { file: string; error: string }[]; categories: string[]; templates?: Graph[] }>('automata/catalog'),
  templates: () => request<{ templates: Graph[] }>('automata/templates'),
  intelligence: (operation: string, params: Record<string, unknown> = {}) => request<IntelligenceReport>(`intelligence/${operation}`, params),
  list: () => request<{ workflows: WorkflowSummary[]; component_count: number; component_problems: { file: string; error: string }[] }>('automata/list'),
  get: (id: string) => request<{ graph: Graph; version: string }>('automata/get', { id }),
  save: (graph: Graph, expected_version?: string) => request<{ id: string; version: string }>('automata/save', { graph, ...(expected_version ? { expected_version } : {}) }),
  remove: (id: string) => request<{ id: string }>('automata/delete', { id }),
  validate: (graph: Graph) => request<Validation>('automata/validate', { graph }),
  codegen: (graph: Graph) => request<{ language: string; filename: string; code: string }>('automata/codegen', { graph }),
  exportCode: (graph: Graph) => request<{ filename: string; code: string }>('automata/export', { graph }),
  run: (graph: Graph, mode: 'run' | 'test', run?: EngineRun, apiKey?: string, trigger?: unknown) =>
    request<Run>('automata/run', { graph, mode, ...(run ? { run } : {}), ...(apiKey ? { api_key: apiKey } : {}), ...(trigger !== undefined ? { trigger } : {}) }),
  runGet: (run_id: string) => request<Run>('automata/run_get', { run_id }),
  runNode: (run_id: string, node_id: string) => request<NodeRun & { run_id: string }>('automata/run_node', { run_id, node_id }),
  respond: (run_id: string, gate_id: string, decision: 'approve' | 'reject' | 'answer', answer = '') => request<Run>('automata/respond', { run_id, gate_id, decision, answer }),
  resume: (run_id: string, retry_failed = false) => request<Run>('automata/resume', { run_id, retry_failed }),
  cancel: (run_id: string) => request<Run>('automata/cancel', { run_id }),
  testNode: (graph: Graph, node_id: string, input: unknown, nodes?: Record<string, unknown>) =>
    request<{ ok: boolean; output?: unknown; port?: string; logs?: string; error?: string; seconds: number }>('automata/test_node', { graph, node_id, input, ...(nodes ? { nodes } : {}) }),
  testComponent: (id: string) => request<ComponentTest>('automata/test_component', { id }),
};
